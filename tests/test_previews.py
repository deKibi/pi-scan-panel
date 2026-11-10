# tests/test_previews.py

# Standard Libraries
import importlib
import os
import shutil
import subprocess
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

# Third-party Libraries
from PIL import Image

# Custom Modules
from generate_preview_pdfs import generate_samples


# Import the app without reading .env or using real credentials.
with (
    patch("dotenv.load_dotenv", return_value=False),
    patch.dict(os.environ, {
        "SCANNER_USERNAME": "preview-test",
        "SCANNER_PASSWORD": "preview-test-only",
        "SCANNER_SECRET_KEY": "preview-test-session-key",
        "PI_SCAN_PANEL_MAX_UPLOAD_MB": "25",
    }),
):
    panel = importlib.import_module("app")


class PreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        directory = TemporaryDirectory(prefix="pi-scan-preview-fixtures-")
        cls.addClassCleanup(directory.cleanup)
        cls.fixtures = Path(directory.name)
        generate_samples(cls.fixtures)

    def setUp(self) -> None:
        self.directory = TemporaryDirectory(prefix="pi-scan-preview-test-")
        self.addCleanup(self.directory.cleanup)
        self.scan_dir = Path(self.directory.name)
        self.settings = patch.multiple(
            panel, SCAN_DIR=self.scan_dir, UPLOAD_DIR=self.scan_dir / "uploads"
        )
        self.settings.start()
        self.addCleanup(self.settings.stop)
        self.client = self.make_client()

    def make_client(self):
        client = panel.app.test_client()
        with client.session_transaction() as session:
            session["logged_in"] = True
        return client

    def get_preview(self, url: str):
        response = self.client.get(url)
        self.addCleanup(response.close)
        return response

    def copy_pdf(self, name: str = "portrait") -> Path:
        source = self.fixtures / f"preview-{name}.pdf"
        destination = self.scan_dir / source.name
        shutil.copyfile(source, destination)
        return destination

    def assert_jpeg(self, response) -> tuple[int, int]:
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/jpeg")
        self.assertTrue(response.cache_control.private)
        with Image.open(BytesIO(response.data)) as image:
            self.assertEqual(image.format, "JPEG")
            self.assertLessEqual(image.width, 640)
            self.assertLessEqual(image.height, 640)
            return image.size

    def test_portrait_and_landscape_previews(self) -> None:
        for name, landscape in (("portrait", False), ("landscape", True)):
            with self.subTest(name=name):
                path = self.copy_pdf(name)
                response = self.get_preview(f"/previews/{path.name}")
                width, height = self.assert_jpeg(response)
                self.assertEqual(width > height, landscape)
                self.assertEqual(max(width, height), 640)

    def test_multipage_preview_contains_only_first_page(self) -> None:
        path = self.copy_pdf("multipage")
        response = self.get_preview(f"/previews/{path.name}")
        self.assert_jpeg(response)
        with Image.open(BytesIO(response.data)) as image:
            center = (image.width // 2, image.height // 2)
            red, _, blue = image.getpixel(center)
            self.assertGreater(red, blue + 20)
        previews = list(panel.get_preview_dir(path).glob("*.jpg"))
        self.assertEqual(len(previews), 1)

    def test_warm_cache_does_not_start_renderer(self) -> None:
        path = self.copy_pdf()
        first = self.get_preview(f"/previews/{path.name}")
        self.assert_jpeg(first)
        with patch.object(panel.subprocess, "run") as renderer:
            second = self.get_preview(f"/previews/{path.name}")
        renderer.assert_not_called()
        self.assertEqual(first.data, second.data)

    def test_replaced_pdf_invalidates_cache(self) -> None:
        path = self.copy_pdf()
        previous = panel.get_scan_preview(path)
        shutil.copyfile(self.fixtures / "preview-landscape.pdf", path)
        current = panel.get_scan_preview(path)
        self.assertNotEqual(previous, current)
        self.assertFalse(previous.exists())
        with Image.open(current) as image:
            self.assertGreater(image.width, image.height)

    def test_png_jpeg_and_transparency_still_work(self) -> None:
        for name, mode in (
            ("test.png", "RGB"), ("test.jpg", "RGB"), ("alpha.png", "RGBA")
        ):
            with self.subTest(name=name):
                color = (0, 0, 0, 0) if mode == "RGBA" else "white"
                with Image.new(mode, (800, 1000), color) as image:
                    image.save(self.scan_dir / name)
                with patch.object(panel.subprocess, "run") as renderer:
                    response = self.get_preview(f"/previews/{name}")
                renderer.assert_not_called()
                self.assert_jpeg(response)
                with Image.open(BytesIO(response.data)) as thumbnail:
                    pixel = thumbnail.getpixel((0, 0))
                    self.assertTrue(all(value > 250 for value in pixel))

    def test_pdf_previews_require_login(self) -> None:
        path = self.copy_pdf()
        with patch.object(panel, "get_scan_preview") as renderer:
            client = panel.app.test_client()
            for url in (f"/previews/{path.name}", "/trash/invalid/preview"):
                self.assertEqual(client.get(url).status_code, 302)
        renderer.assert_not_called()

    def test_invalid_preview_paths_do_not_start_renderer(self) -> None:
        with patch.object(panel, "get_scan_preview") as renderer:
            for url, status in (
                ("/previews/missing.pdf", 400),
                ("/previews/subdirectory/file.pdf", 400),
                ("/trash/invalid/preview", 404),
            ):
                self.assertEqual(self.client.get(url).status_code, status)
        renderer.assert_not_called()

    def test_broken_pdf_does_not_leave_cached_jpeg(self) -> None:
        path = self.scan_dir / "broken.pdf"
        path.write_bytes(b"This is not a PDF")
        with self.assertLogs(panel.app.logger, level="ERROR"):
            response = self.client.get(f"/previews/{path.name}")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.data, b"Preview unavailable")
        self.assertEqual(list(panel.get_preview_dir(path).iterdir()), [])
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_timeout_kills_child_and_removes_partial_jpeg(self) -> None:
        path = self.copy_pdf()
        helper = self.scan_dir / "pdf_preview.py"
        helper.write_text(
            "import sys, time\nfrom pathlib import Path\n"
            "Path(sys.argv[2]).write_bytes(b'partial JPEG')\ntime.sleep(30)\n"
        )
        started = time.monotonic()
        with (
            patch.object(panel, "__file__", str(self.scan_dir / "app.py")),
            patch.object(panel, "PDF_PREVIEW_TIMEOUT_SECONDS", 0.25),
            self.assertLogs(panel.app.logger, level="ERROR"),
        ):
            response = self.client.get(f"/previews/{path.name}")
        self.assertEqual(response.status_code, 500)
        self.assertLess(time.monotonic() - started, 3)
        self.assertEqual(list(panel.get_preview_dir(path).iterdir()), [])
        # A later request can generate a preview after the timeout.
        self.assert_jpeg(self.get_preview(f"/previews/{path.name}"))

    def test_missing_renderer_returns_preview_error(self) -> None:
        path = self.copy_pdf()
        with (
            patch.object(
                panel.subprocess, "run", side_effect=FileNotFoundError
            ),
            self.assertLogs(panel.app.logger, level="ERROR"),
        ):
            response = self.client.get(f"/previews/{path.name}")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(list(panel.get_preview_dir(path).iterdir()), [])

    def test_pages_do_not_wait_for_running_pdf_preview(self) -> None:
        path = self.copy_pdf()
        self.client.post(f"/delete/{path.name}")
        entry_id = next(panel.get_trash_dir().iterdir()).name
        started = threading.Event()
        release = threading.Event()

        def render(command, **kwargs):
            started.set()
            if not release.wait(5):
                raise TimeoutError("Test did not release renderer")
            with Image.new("RGB", (100, 120), "white") as image:
                image.save(command[3], format="JPEG")
            return subprocess.CompletedProcess(command, 0)

        with (
            patch.object(panel.subprocess, "run", side_effect=render),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            preview = executor.submit(
                lambda: self.make_client().get(f"/trash/{entry_id}/preview")
            )
            try:
                self.assertTrue(started.wait(3))
                for url in ("/", "/trash"):
                    page = executor.submit(
                        lambda url=url: self.make_client().get(url)
                    )
                    self.assertEqual(page.result(timeout=2).status_code, 200)
                self.assertFalse(preview.done())
            finally:
                release.set()
            response = preview.result(timeout=3)
            self.addCleanup(response.close)
            self.assert_jpeg(response)

    def test_concurrent_requests_generate_same_pdf_only_once(self) -> None:
        path = self.copy_pdf()
        real_run = subprocess.run
        with (
            patch.object(panel.subprocess, "run", wraps=real_run) as renderer,
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            responses = list(executor.map(
                lambda _: self.make_client().get(f"/previews/{path.name}"),
                range(2),
            ))
        self.assertEqual(renderer.call_count, 1)
        for response in responses:
            self.addCleanup(response.close)
            self.assert_jpeg(response)

    def test_html_uses_lazy_pdf_previews_without_rendering(self) -> None:
        self.copy_pdf()
        with patch.object(panel.subprocess, "run") as renderer:
            response = self.client.get("/")
        renderer.assert_not_called()
        html = response.get_data(as_text=True)
        self.assertIn('class="scan-preview pdf-preview"', html)
        self.assertIn(
            'data-preview-src="/previews/preview-portrait.pdf?v=', html
        )
        self.assertNotIn(
            'src="/previews/', html.replace("data-preview-src=", "data-lazy=")
        )
        self.assertNotIn(">Повернути 90°</button>", html)
        self.assertFalse((self.scan_dir / "previews").exists())

    def test_trash_restore_and_delete_clean_up_pdf_previews(self) -> None:
        path = self.copy_pdf()
        self.assert_jpeg(self.get_preview(f"/previews/{path.name}"))
        original_cache = panel.get_preview_dir(path)
        response = self.client.post(f"/delete/{path.name}")
        self.assertEqual(response.status_code, 302)
        self.assertFalse(original_cache.exists())
        entry_id = next(panel.get_trash_dir().iterdir()).name
        self.assert_jpeg(self.get_preview(f"/trash/{entry_id}/preview"))
        trash_cache = panel.get_preview_dir(path, entry_id)
        self.assertTrue(trash_cache.is_dir())
        html = self.client.get("/trash").get_data(as_text=True)
        self.assertIn("data-preview-src=", html)
        response = self.client.post(f"/trash/{entry_id}/restore")
        self.assertEqual(response.status_code, 302)
        self.assertFalse(trash_cache.exists())
        self.assertTrue(path.exists())
        self.assert_jpeg(self.get_preview(f"/previews/{path.name}"))
        self.client.post(f"/delete/{path.name}")
        entry_id = next(panel.get_trash_dir().iterdir()).name
        self.assert_jpeg(self.get_preview(f"/trash/{entry_id}/preview"))
        trash_cache = panel.get_preview_dir(path, entry_id)
        response = self.client.post(f"/trash/{entry_id}/delete")
        self.assertEqual(response.status_code, 302)
        self.assertFalse(trash_cache.exists())
        self.assertFalse((panel.get_trash_dir() / entry_id).exists())

    def test_trash_listing_tolerates_concurrent_removal(self) -> None:
        path = self.copy_pdf()
        self.client.post(f"/delete/{path.name}")
        with patch.object(
            panel, "get_trash_file", side_effect=FileNotFoundError
        ):
            self.assertEqual(panel.list_trash_files(), [])


if __name__ == "__main__":
    unittest.main()
