# tests/test_templates.py

# Standard Libraries
import importlib
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


# Import without loading .env or using real credentials.
with (
    patch("dotenv.load_dotenv", return_value=False),
    patch.dict(os.environ, {
        "SCANNER_USERNAME": "template-test",
        "SCANNER_PASSWORD": "template-test-only",
        "SCANNER_SECRET_KEY": "template-test-session-key",
        "PI_SCAN_PANEL_MAX_UPLOAD_MB": "25",
    }),
):
    panel = importlib.import_module("app")


class TemplateTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = TemporaryDirectory(prefix="pi-template-test-")
        self.addCleanup(directory.cleanup)
        self.scan_dir = Path(directory.name)
        settings = patch.multiple(
            panel,
            SCAN_DIR=self.scan_dir,
            APP_USERNAME="template-test",
            APP_PASSWORD="template-test-only",
            APP_VERSION="v-test",
            APP_FOOTER_TEXT="Test footer",
        )
        settings.start()
        self.addCleanup(settings.stop)
        self.client = panel.app.test_client()

    def authenticate(self) -> None:
        with self.client.session_transaction() as session:
            session["logged_in"] = True

    def page(self, url: str) -> str:
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def assert_base_layout(self, html: str) -> None:
        self.assertIn('<main class="page">', html)
        self.assertIn('<footer class="site-footer">', html)
        self.assertIn("v-test · Test footer", html)
        self.assertIn('href="/static/styles.css"', html)
        self.assertNotIn("<style>", html)

    def test_login_uses_base_layout_without_authenticated_controls(self) -> None:
        html = self.page("/login")
        self.assert_base_layout(html)
        self.assertIn('action="/login"', html)
        self.assertIn('name="username"', html)
        self.assertIn('name="password"', html)
        self.assertNotIn('src="/static/scan-previews.js"', html)
        self.assertNotIn('id="confirm-dialog"', html)
        self.assertNotIn('href="/logout"', html)

    def test_login_error_retains_form_and_base_layout(self) -> None:
        response = self.client.post("/login", data={
            "username": "invalid", "password": "invalid",
        })
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assert_base_layout(html)
        self.assertIn("Невірний логін або пароль.", html)
        self.assertIn('name="password"', html)

    def test_home_retains_scan_form_preview_links_and_shared_scripts(self) -> None:
        self.authenticate()
        # Listing uses metadata only; it does not render or open this file.
        (self.scan_dir / "sample.pdf").write_bytes(b"%PDF-listing-test")
        html = self.page("/")
        self.assert_base_layout(html)
        self.assertIn('class="scan-form"', html)
        self.assertIn('<strong>sample.pdf</strong>', html)
        self.assertIn('data-preview-src="/previews/sample.pdf?v=', html)
        self.assertIn('href="/files/sample.pdf"', html)
        self.assertIn('action="/rotate/sample.pdf?', html)
        self.assertIn("Повернути 90°", html)
        self.assertIn('src="/static/scan-previews.js"', html)
        self.assertIn('/static/scroll-lock.js', html)
        self.assertIn('id="confirm-dialog"', html)
        self.assertIn('href="/logout"', html)
        self.assertIn('id="action-revert"', html)
        self.assertIn('id="action-close"', html)
        self.assertIn('aria-label="Скасувати дію"', html)
        self.assertIn('hidden>Скасувати дію</button>', html)
        self.assertIn('id="action-notice-text" role="status"', html)

    def test_empty_trash_uses_base_layout(self) -> None:
        self.authenticate()
        html = self.page("/trash")
        self.assert_base_layout(html)
        self.assertIn("Кошик порожній.", html)

    def test_populated_trash_retains_preview_and_actions(self) -> None:
        self.authenticate()
        entry_id = "20260801T120000000000Z-0000000000000000"
        entry = self.scan_dir / ".trash" / entry_id
        entry.mkdir(parents=True)
        (entry / "sample.pdf").write_bytes(b"%PDF-listing-test")
        html = self.page("/trash")
        self.assert_base_layout(html)
        self.assertIn('<strong>sample.pdf</strong>', html)
        self.assertIn(f'data-preview-src="/trash/{entry_id}/preview?v=', html)
        self.assertIn(f'action="/trash/{entry_id}/restore', html)
        self.assertIn(f'action="/trash/{entry_id}/delete', html)
        self.assertIn('src="/static/scan-previews.js"', html)

    def test_text_context_and_flash_messages_are_escaped(self) -> None:
        text = '<script>alert("test")</script>'
        with (
            panel.app.test_request_context("/login"),
            patch.multiple(panel, APP_VERSION=text, APP_FOOTER_TEXT=text),
        ):
            html = panel.render_page(
                title=text, heading=text, subtitle=text,
                message=text, body_template="login.html",
            )
        self.assertNotIn(text, html)
        self.assertGreaterEqual(html.count("&lt;script&gt;"), 6)
        with self.client.session_transaction() as session:
            session["_flashes"] = [("success", text)]
        html = self.page("/login")
        self.assertNotIn(text, html)
        self.assertIn("&lt;script&gt;", html)

    def test_filename_is_escaped_in_child_template(self) -> None:
        self.authenticate()
        (self.scan_dir / "scan-<script>.pdf").write_bytes(b"%PDF-listing-test")
        html = self.page("/")
        self.assertIn("<strong>scan-&lt;script&gt;.pdf</strong>", html)
        self.assertNotIn("<strong>scan-<script>", html)

    def test_stylesheet_is_served_as_css(self) -> None:
        response = self.client.get("/static/styles.css")
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/css")
        css = response.get_data(as_text=True)
        self.assertIn(".pdf-preview img", css)
        self.assertIn("object-fit: contain;", css)
        self.assertIn("@media", css)


if __name__ == "__main__":
    unittest.main()
