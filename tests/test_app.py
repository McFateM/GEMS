from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import flet as ft

from gems.app import main
from gems.pipeline import load_payload


class AppTests(unittest.TestCase):
    def test_alma_set_name_is_used_for_manifest(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("gems.app.LOG_PATH", Path(directory) / "gems.log"),
            patch("gems.app.load_dotenv"),
            patch("gems.app.load_settings", return_value={"alma_set_id": "set-123"}),
            patch("gems.app.save_settings"),
            patch("gems.app.AlmaClient") as alma_client,
            patch.object(ft.FilePicker, "save_file") as save_dialog,
        ):
            alma_client.return_value.fetch_set_title.return_value = "Campus Photo Archive"
            alma_client.return_value.fetch_set_members.return_value = ["991"]
            alma_client.return_value.fetch_records.return_value = [{"identifier": "991"}]
            page = MagicMock()
            main(page)
            controls = page.add.call_args_list[0].args[0].content.controls
            retrieve = next(
                item
                for control in controls if isinstance(control, ft.Row)
                for item in control.controls if isinstance(item, ft.FilledButton) and item.text == "Retrieve"
            )
            retrieve.on_click(None)
            next(control for control in controls if isinstance(control, ft.OutlinedButton)).on_click(None)

            alma_client.return_value.fetch_set_title.assert_called_once_with("set-123")
            filename = save_dialog.call_args.kwargs["file_name"]
            self.assertRegex(filename, r"^gems_campus-photo-archive_\d{8}T\d{6}Z\.json$")
            manifest_path = Path(directory) / filename
            page.overlay.extend.call_args.args[0][3].on_result(SimpleNamespace(path=str(manifest_path)))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual("Campus Photo Archive", manifest["collection_title"])
            self.assertEqual("set-123", manifest["alma_set_id"])
            self.assertEqual([{"identifier": "991"}], load_payload(manifest_path))

    def test_retrieval_error_is_visible_and_logged(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("gems.app.LOG_PATH", Path(directory) / "gems.log"),
            patch("gems.app.load_dotenv"),
            patch("gems.app.load_settings", return_value={"alma_mms_ids": "123"}),
            patch("gems.app.AlmaClient", side_effect=ValueError("Cannot connect")),
        ):
            page = MagicMock()
            main(page)
            controls = page.add.call_args_list[0].args[0].content.controls
            retrieve_button = next(
                item
                for control in controls if isinstance(control, ft.Row)
                for item in control.controls if isinstance(item, ft.FilledButton) and item.text == "Retrieve"
            )
            retrieve_button.on_click(None)

            footer = page.add.call_args_list[1].args[0].content
            status = next(item for item in footer.controls if isinstance(item, ft.Text))
            self.assertIn("Alma retrieval failed: Cannot connect", status.value)
            self.assertEqual(ft.Colors.RED_700, status.color)
            log_text = (Path(directory) / "gems.log").read_text(encoding="utf-8")
            self.assertIn("Alma retrieval failed: Cannot connect", log_text)
            self.assertIn("Traceback (most recent call last)", log_text)

    def test_alma_manifest_is_saved_and_used_by_csv_export(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("gems.app.LOG_PATH", Path(directory) / "gems.log"),
            patch("gems.app.load_dotenv"),
            patch("gems.app.load_settings", return_value={"alma_mms_ids": "123", "collection_title": "Test Collection", "output_path": directory}),
            patch("gems.app.save_settings") as save_settings,
            patch("gems.app.AlmaClient") as alma_client,
            patch("gems.app.process_export") as process_export,
            patch.object(ft.FilePicker, "save_file") as save_dialog,
        ):
            record = {"identifier": "123", "metadata": {"title": "Test"}, "files": []}
            alma_client.return_value.fetch_records.return_value = [record]
            page = MagicMock()
            main(page)
            controls = page.add.call_args_list[0].args[0].content.controls
            footer = page.add.call_args_list[1].args[0].content
            self.assertTrue(any(isinstance(item, ft.Text) and item.value == "Ready" for item in footer.controls))
            retrieve_button = next(
                item
                for control in controls if isinstance(control, ft.Row)
                for item in control.controls if isinstance(item, ft.FilledButton) and item.text == "Retrieve"
            )
            manifest_button = next(control for control in controls if isinstance(control, ft.OutlinedButton))
            csv_button = next(
                item
                for control in controls if isinstance(control, ft.Row)
                for item in control.controls
                if isinstance(item, ft.FilledButton) and item.text == "2) Map and Export Manifest to CSV"
            )

            retrieve_button.on_click(None)
            manifest_button.on_click(None)
            save_dialog.assert_called_once()
            filename = save_dialog.call_args.kwargs["file_name"]
            self.assertRegex(filename, r"^gems_test-collection_\d{8}T\d{6}Z\.json$")
            manifest_path = Path(directory) / filename
            page.overlay.extend.call_args.args[0][3].on_result(SimpleNamespace(path=str(manifest_path)))

            self.assertEqual([record], load_payload(manifest_path))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual("Test Collection", manifest["collection_title"])
            self.assertEqual([record], manifest["records"])
            self.assertIn(datetime.fromisoformat(manifest["created_at"]).strftime("%Y%m%dT%H%M%SZ"), filename)
            self.assertEqual(str(manifest_path), save_settings.call_args.args[0]["source_path"])
            csv_button.on_click(None)
            self.assertEqual(manifest_path, process_export.call_args.args[0])
            self.assertEqual({}, process_export.call_args.kwargs["field_map"])
            log_text = (Path(directory) / "gems.log").read_text(encoding="utf-8")
            self.assertIn("Retrieved 1 Alma record", log_text)
            self.assertIn("Export complete", log_text)
            log_button = next(item for item in footer.controls if isinstance(item, ft.IconButton))
            log_button.on_click(None)
            self.assertIn("Export complete", page.overlay.append.call_args.args[0].content.content.value)


if __name__ == "__main__":
    unittest.main()