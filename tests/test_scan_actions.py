# tests/test_scan_actions.py

# Standard Libraries
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

# Third-party Libraries
import pypdfium2 as pdfium
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

    def pdf(self, name: str = "scan.pdf") -> Path:
        path = self.scan_dir / name
        with pdfium.PdfDocument.new() as document:
            for rotation in (0, 90, 180, 270):
                page = document.new_page(40, 60)
                try:
                    page.set_rotation(rotation)
                finally:
                    page.close()
            document.save(path)
        return path

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

    def test_rotation_revert_restores_orientation_once(self) -> None:
        for extension in ("png", "jpg", "jpeg", "pdf"):
            with self.subTest(extension=extension):
                name = f"scan.{extension}"
                path = (
                    self.pdf(name) if extension == "pdf" else self.image(name)
                )
                if extension != "pdf":
                    with Image.new("RGB", (40, 60), "white") as image:
                        image.paste("red", (0, 0, 20, 30))
                        image.save(path)
                data = self.post(f"/rotate/{name}")
                revert = data["revert"]
                self.assertEqual(revert["file_id"], name)
                self.assertEqual(
                    revert["fields"]["direction"], "counterclockwise"
                )
                reverted = self.post(revert["url"], data=revert["fields"])
                self.assertTrue(reverted["success"])
                self.assertEqual(reverted["message"], "Дію скасовано.")
                self.assertNotIn("revert", reverted)
                self.assertNotIn("list_html", reverted)
                self.assertNotEqual(
                    data["file"]["preview_url"],
                    reverted["file"]["preview_url"],
                )
                if extension == "pdf":
                    with pdfium.PdfDocument(path) as document:
                        for index in range(len(document)):
                            page = document[index]
                            try:
                                self.assertEqual(
                                    page.get_rotation(), index * 90
                                )
                            finally:
                                page.close()
                else:
                    with Image.open(path) as image:
                        self.assertEqual(image.size, (40, 60))
                        red, green, blue = image.getpixel((5, 5))
                        self.assertGreater(red, green + 100)
                        self.assertGreater(red, blue + 100)
                        self.assertGreater(min(image.getpixel((35, 55))), 200)
                original = path.read_bytes()
                repeated = self.post(revert["url"], data=revert["fields"])
                self.assertFalse(repeated["success"])
                self.assertEqual(path.read_bytes(), original)

    def test_old_revert_preserves_newer_or_replaced_file(self) -> None:
        for extension in ("png", "pdf"):
            with self.subTest(extension=extension):
                name = f"scan.{extension}"
                path = (
                    self.pdf(name) if extension == "pdf" else self.image(name)
                )
                first = self.post(f"/rotate/{name}")["revert"]
                second = self.post(f"/rotate/{name}")["revert"]
                original = path.read_bytes()
                self.assertFalse(
                    self.post(first["url"], data=first["fields"])["success"]
                )
                self.assertEqual(path.read_bytes(), original)
                path.unlink()
                if extension == "pdf":
                    self.pdf(name)
                else:
                    self.image(name)
                replacement = path.read_bytes()
                self.assertFalse(
                    self.post(second["url"], data=second["fields"])["success"]
                )
                self.assertEqual(path.read_bytes(), replacement)

    def test_rotation_revert_validates_version_and_missing_file(self) -> None:
        path = self.image()
        original = path.read_bytes()
        for fields in (
            {"direction": "counterclockwise"},
            {"direction": "counterclockwise", "expected_version": ""},
            {"direction": "invalid"},
        ):
            with self.subTest(fields=fields):
                data = self.post("/rotate/scan.png", data=fields)
                self.assertFalse(data["success"])
                self.assertNotIn("revert", data)
                self.assertEqual(path.read_bytes(), original)
        revert = self.post("/rotate/scan.png")["revert"]
        path.unlink()
        self.assertFalse(
            self.post(revert["url"], data=revert["fields"])["success"]
        )

    def test_pdf_rotation_updates_every_page_and_preview_url(self) -> None:
        path = self.pdf()
        urls = []
        for turn in range(1, 5):
            data = self.post("/rotate/scan.pdf?page=2&per_page=10")
            self.assertTrue(data["success"])
            self.assertNotIn("list_html", data)
            self.assertEqual(data["file"]["id"], path.name)
            self.assertIn("/previews/scan.pdf?v=", data["file"]["preview_url"])
            urls.append(data["file"]["preview_url"])
            with pdfium.PdfDocument(path) as document:
                self.assertEqual(len(document), 4)
                for index in range(len(document)):
                    page = document[index]
                    try:
                        self.assertEqual(
                            page.get_rotation(), ((index + turn) * 90) % 360
                        )
                    finally:
                        page.close()
        self.assertEqual(len(set(urls)), 4)
        self.assertEqual(set(self.scan_dir.iterdir()), {path})

    def test_pdf_save_failure_preserves_original_and_cleans_up(self) -> None:
        path = self.pdf()
        original = path.read_bytes()

        def fail_save(document, destination):
            Path(destination).write_bytes(b"incomplete PDF")
            raise pdfium.PdfiumError("test save failure")

        with patch.object(pdfium.PdfDocument, "save", fail_save):
            data = self.post("/rotate/scan.pdf")
        self.assertFalse(data["success"])
        self.assertNotIn("file", data)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(set(self.scan_dir.iterdir()), {path})

    def test_pdf_rotation_replace_failure_preserves_original(self) -> None:
        path = self.pdf()
        original = path.read_bytes()
        with patch.object(Path, "replace", side_effect=OSError("test")):
            data = self.post("/rotate/scan.pdf")
        self.assertFalse(data["success"])
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(set(self.scan_dir.iterdir()), {path})

    def test_broken_pdf_rotation_preserves_original(self) -> None:
        path = self.scan_dir / "broken.pdf"
        original = b"%PDF-invalid"
        path.write_bytes(original)
        data = self.post("/rotate/broken.pdf")
        self.assertFalse(data["success"])
        self.assertNotIn("file", data)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(set(self.scan_dir.iterdir()), {path})

    def test_html_pdf_rotation_remains_supported(self) -> None:
        self.pdf()
        response = self.client.post("/rotate/scan.pdf")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/html")
        self.assertIn("Файл повернуто на 90°.", response.get_data(as_text=True))

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

    def test_missing_files_and_invalid_pdf(self) -> None:
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

    def test_delete_revert_restores_entry_and_original_page(self) -> None:
        for index in range(11):
            path = self.image(f"scan-{index}.png")
            os.utime(path, (1000 + index, 1000 + index))
        path = self.scan_dir / "scan-0.png"
        original = path.read_bytes()
        deleted = self.post("/delete/scan-0.png?page=2&per_page=10")
        self.assertEqual(deleted["page"], 1)
        revert = deleted["revert"]
        self.assertEqual(revert["file_id"], path.name)
        restored = self.post(revert["url"], data=revert["fields"])
        self.assertTrue(restored["success"])
        self.assertNotIn("revert", restored)
        self.assertEqual(restored["message"], "Дію скасовано.")
        self.assertEqual(restored["url"], "/?page=2&per_page=10")
        self.assertIn('data-file-id="scan-0.png"', restored["list_html"])
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(list(panel.get_trash_dir().iterdir()), [])
        repeated = self.post(revert["url"], data=revert["fields"])
        self.assertFalse(repeated["success"])
        self.assertIn('data-file-id="scan-0.png"', repeated["list_html"])

    def test_delete_revert_keeps_other_entry_with_same_filename(self) -> None:
        path = self.image()
        first_revert = self.post("/delete/scan.png")["revert"]
        with Image.new("RGB", (60, 40), "red") as image:
            image.save(path)
        original = path.read_bytes()
        second_revert = self.post("/delete/scan.png")["revert"]
        restored = self.post(
            second_revert["url"], data=second_revert["fields"]
        )
        self.assertTrue(restored["success"])
        self.assertEqual(path.read_bytes(), original)
        conflict = self.post(first_revert["url"], data=first_revert["fields"])
        self.assertFalse(conflict["success"])
        self.assertNotIn("revert", conflict)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(len(list(panel.get_trash_dir().iterdir())), 1)

    def test_expired_session_revert_preserves_files(self) -> None:
        path = self.image()
        rotation = self.post("/rotate/scan.png")["revert"]
        original = path.read_bytes()
        self.image("other.png")
        deletion = self.post("/delete/other.png")["revert"]
        with self.client.session_transaction() as session:
            session.clear()
        for revert in (rotation, deletion):
            response = self.client.post(
                revert["url"], data=revert["fields"],
                headers={"Accept": "application/json"},
            )
            self.assertEqual(response.status_code, 401)
            self.assertNotIn("revert", response.get_json())
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse((self.scan_dir / "other.png").exists())

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
        pdf_path = self.pdf()
        original_pdf = pdf_path.read_bytes()
        with self.client.session_transaction() as session:
            session.clear()
        for url in (
            "/rotate/scan.png", "/rotate/scan.pdf", "/print/scan.png",
            "/delete/scan.png",
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
        self.assertEqual(pdf_path.read_bytes(), original_pdf)
        self.assertEqual(self.client.post("/rotate/scan.png").status_code, 302)


if __name__ == "__main__":
    unittest.main()
