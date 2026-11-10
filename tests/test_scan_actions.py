# tests/test_scan_actions.py

# Standard Libraries
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

# Third-party Libraries
from PIL import Image

# Custom Modules
from test_templates import panel


class ScanActionTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = TemporaryDirectory(prefix="pi-actions-test-")
        self.addCleanup(directory.cleanup)
        self.scan_dir = Path(directory.name)
        settings = patch.multiple(
            panel, SCAN_DIR=self.scan_dir, last_scan=None
        )
        settings.start()
        self.addCleanup(settings.stop)
        self.client = panel.app.test_client()
        with self.client.session_transaction() as session:
            session["logged_in"] = True

    def image(self, name: str = "scan.png") -> Path:
        path = self.scan_dir / name
        with Image.new("RGB", (40, 60), "white") as image:
            image.save(path)
        return path

    def post(self, url: str, **kwargs):
        response = self.client.post(
            url, headers={"Accept": "application/json"}, **kwargs
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/json")
        return response.get_json()

    def trash_id(self) -> str:
        return next(panel.get_trash_dir().iterdir()).name

    def test_repeated_rotation_updates_preview_without_list(self) -> None:
        path = self.image()
        urls = []
        for expected_size in ((60, 40), (40, 60)):
            data = self.post("/rotate/scan.png?page=2&per_page=10")
            self.assertTrue(data["success"])
            self.assertNotIn("list_html", data)
            self.assertEqual(data["file"]["id"], path.name)
            self.assertIn("/previews/scan.png?v=", data["file"]["preview_url"])
            urls.append(data["file"]["preview_url"])
            with Image.open(path) as image:
                self.assertEqual(image.size, expected_size)
        self.assertNotEqual(*urls)

    def test_rotation_on_later_page_ignores_changed_sort_order(self) -> None:
        for index in range(11):
            path = self.image(f"scan-{index}.png")
            os.utime(path, (1000 + index, 1000 + index))
        data = self.post("/rotate/scan-0.png?page=2&per_page=10")
        self.assertEqual(data["file"]["id"], "scan-0.png")
        self.assertNotIn("list_html", data)

    def test_html_rotation_and_print_remain_supported(self) -> None:
        self.image()
        response = self.client.post("/rotate/scan.png")
        self.assertEqual(response.mimetype, "text/html")
        self.assertIn(
            "Файл повернуто на 90°.", response.get_data(as_text=True)
        )
        with patch.object(
            panel, "print_file_with_lock", return_value=("Printed", "success")
        ):
            response = self.client.post("/print/scan.png")
        self.assertEqual(response.mimetype, "text/html")
        self.assertIn("Printed", response.get_data(as_text=True))

    def test_print_success_busy_and_failure(self) -> None:
        path = self.image()
        for category in ("success", "busy", "error"):
            with self.subTest(category=category), patch.object(
                panel, "print_file_with_lock",
                return_value=(category, category),
            ) as printer:
                data = self.post("/print/scan.png")
                printer.assert_called_once_with(path)
                self.assertEqual(data["success"], category == "success")
                self.assertEqual(data["message"], category)
                self.assertNotIn("list_html", data)

    def test_missing_files_and_invalid_rotation(self) -> None:
        (self.scan_dir / "scan.pdf").write_bytes(b"%PDF-test")
        for url in (
            "/rotate/missing.png", "/print/missing.png", "/rotate/scan.pdf"
        ):
            with self.subTest(url=url):
                data = self.post(url)
                self.assertFalse(data["success"])
                self.assertNotIn("file", data)

    def test_delete_last_item_updates_page_and_last_scan(self) -> None:
        for index in range(11):
            path = self.image(f"scan-{index}.png")
            os.utime(path, (1000 + index, 1000 + index))
        panel.last_scan = {"filename": "scan-0.png", "format": "png"}
        data = self.post("/delete/scan-0.png?page=2&per_page=10")
        self.assertTrue(data["success"])
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["per_page"], 10)
        self.assertEqual(data["url"], "/?page=1&per_page=10")
        self.assertNotIn('data-file-id="scan-0.png"', data["list_html"])
        self.assertEqual(data["list_html"].count('class="scan-item"'), 10)
        self.assertFalse(data["last_scan_html"].strip())
        self.assertFalse((self.scan_dir / "scan-0.png").exists())
        trash_path = panel.get_trash_dir() / self.trash_id() / "scan-0.png"
        self.assertTrue(trash_path.is_file())
        with self.client.session_transaction() as session:
            self.assertNotIn("_flashes", session)

    def test_trash_restore_conflict_then_success_preserves_files(self) -> None:
        self.image()
        self.post("/delete/scan.png")
        entry_id = self.trash_id()
        self.image()
        data = self.post(f"/trash/{entry_id}/restore")
        self.assertFalse(data["success"])
        self.assertIn(entry_id, data["list_html"])
        (self.scan_dir / "scan.png").unlink()
        data = self.post(f"/trash/{entry_id}/restore")
        self.assertTrue(data["success"])
        self.assertIn("Кошик порожній.", data["list_html"])
        self.assertTrue((self.scan_dir / "scan.png").is_file())

    def test_permanent_delete_and_empty_keep_confirmed_snapshot(self) -> None:
        self.image()
        self.post("/delete/scan.png")
        first_id = self.trash_id()
        self.image("other.png")
        self.post("/delete/other.png")
        data = self.post(
            "/trash/empty?per_page=10", data={"entry_id": [first_id]}
        )
        self.assertTrue(data["success"])
        self.assertNotIn(first_id, data["list_html"])
        self.assertIn("other.png", data["list_html"])
        self.assertIn("Очистити кошик (1)", data["list_html"])
        other_id = self.trash_id()
        self.assertIn(f'name="entry_id" value="{other_id}"', data["list_html"])
        data = self.post(f"/trash/{other_id}/delete")
        self.assertTrue(data["success"])
        self.assertIn("Кошик порожній.", data["list_html"])

    def test_missing_delete_and_trash_entries_report_errors(self) -> None:
        for url in (
            "/delete/missing.png", "/trash/missing/restore",
            "/trash/missing/delete",
        ):
            with self.subTest(url=url):
                self.assertFalse(self.post(url)["success"])

    def test_partial_empty_failure_refreshes_remaining_files(self) -> None:
        self.image()
        self.post("/delete/scan.png")
        entry_id = self.trash_id()
        with (
            patch.object(
                panel, "remove_trash_previews", side_effect=OSError("test")
            ),
            self.assertLogs(panel.app.logger, level="ERROR"),
        ):
            data = self.post("/trash/empty", data={"entry_id": entry_id})
        self.assertFalse(data["success"])
        self.assertIn("Кошик порожній.", data["list_html"])

    def test_unavailable_trash_does_not_replace_existing_list(self) -> None:
        with patch.object(
            panel, "list_trash_files", side_effect=OSError("test")
        ):
            data = self.post("/trash/missing/restore")
        self.assertFalse(data["success"])
        self.assertNotIn("list_html", data)

    def test_expired_session_prevents_actions(self) -> None:
        path = self.image()
        with self.client.session_transaction() as session:
            session.clear()
        for url in (
            "/rotate/scan.png", "/print/scan.png", "/delete/scan.png",
            "/trash/missing/restore", "/trash/missing/delete", "/trash/empty",
        ):
            with self.subTest(url=url):
                response = self.client.post(
                    url, headers={"Accept": "application/json"}
                )
                self.assertEqual(response.status_code, 401)
                self.assertFalse(response.get_json()["success"])
        with Image.open(path) as image:
            self.assertEqual(image.size, (40, 60))
        self.assertEqual(self.client.post("/rotate/scan.png").status_code, 302)


if __name__ == "__main__":
    unittest.main()
