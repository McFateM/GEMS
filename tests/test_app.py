from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import flet as ft

from gems.app import main
from gems.pipeline import load_payload


class AppTests(unittest.TestCase):
    def test_mms_id_batches_share_a_group_but_not_a_run(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("gems.app.LOG_PATH", Path(directory) / "gems.log"),
            patch("gems.app.load_dotenv"),
            patch("gems.app.load_settings", return_value={
                "alma_mms_ids": "991, 992, 993, 994, 995", "start_record": "2", "record_limit": "2",
                "export_root_path": directory,
            }),
            patch("gems.app.save_settings") as save_settings,
            patch("gems.app.AlmaClient") as alma_client,
            patch.object(ft.FilePicker, "get_directory_path") as directory_picker,
        ):
            alma_client.return_value.fetch_records.side_effect = lambda ids, **kwargs: [
                {"identifier": value} for value in ids
            ]
            page = MagicMock()
            main(page)
            controls = page.add.call_args_list[0].args[0].content.controls
            retrieve = next(
                item for row in controls if isinstance(row, ft.Row)
                for item in row.controls if isinstance(item, ft.FilledButton) and item.text == "Retrieve"
            )
            save_manifest = next(item for item in controls if isinstance(item, ft.FilledButton) and item.text.startswith("1)"))
            export = next(
                item for row in controls if isinstance(row, ft.Row)
                for item in row.controls if isinstance(item, ft.FilledButton) and item.text.startswith("2)")
            )
            numeric_fields = {
                item.label: item for row in controls if isinstance(row, ft.Row)
                for item in row.controls if isinstance(item, ft.TextField)
            }
            retrieve.on_click(None)
            self.assertEqual(["992", "993"], alma_client.return_value.fetch_records.call_args.args[0])
            save_manifest.on_click(None)
            export.on_click(None)
            first = Path(save_settings.call_args.args[0]["source_path"])
            self.assertEqual({"start_record": 2, "record_limit": 2, "available_records": 5},
                             json.loads(first.read_text(encoding="utf-8"))["retrieval"])

            numeric_fields["Start record"].value = "4"
            numeric_fields["Start record"].on_change(None)
            retrieve.on_click(None)
            self.assertEqual(["994", "995"], alma_client.return_value.fetch_records.call_args.args[0])
            export.on_click(None)
            directory_picker.assert_not_called()
            second = Path(save_settings.call_args.args[0]["source_path"])
            self.assertEqual(first.parent.parent, second.parent.parent)
            self.assertNotEqual(first.parent, second.parent)
            self.assertRegex(first.parent.parent.name, r"^mms-ids-[0-9a-f]{12}$")
            self.assertEqual(4, json.loads(second.read_text(encoding="utf-8"))["retrieval"]["start_record"])
            self.assertTrue((first.parent / "collection_metadata.csv").exists())
            self.assertTrue((second.parent / "collection_metadata.csv").exists())

    def test_new_retrieval_needs_a_parent_folder_before_export(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("gems.app.LOG_PATH", Path(directory) / "gems.log"),
            patch("gems.app.load_dotenv"),
            patch("gems.app.load_settings", return_value={"alma_mms_ids": "991"}),
            patch("gems.app.save_settings"),
            patch("gems.app.AlmaClient") as alma_client,
            patch("gems.app.process_export") as process_export,
        ):
            alma_client.return_value.fetch_records.return_value = [{"identifier": "991"}]
            page = MagicMock()
            main(page)
            controls = page.add.call_args_list[0].args[0].content.controls
            retrieve = next(
                item for row in controls if isinstance(row, ft.Row)
                for item in row.controls if isinstance(item, ft.FilledButton) and item.text == "Retrieve"
            )
            export = next(
                item for row in controls if isinstance(row, ft.Row)
                for item in row.controls if isinstance(item, ft.FilledButton) and item.text.startswith("2)")
            )
            retrieve.on_click(None)
            export.on_click(None)
            process_export.assert_not_called()
            footer = page.add.call_args_list[1].args[0].content.controls
            self.assertIn("Choose an existing destination folder", next(item.value for item in footer if isinstance(item, ft.Text)))

    def test_invalid_retrieval_range_is_reported_before_fetch(self):
        for start, limit, message in (
            ("0", "2", "Start record must be a positive whole number"),
            ("abc", "2", "Start record must be a positive whole number"),
            ("1", "0", "Record limit must be a positive whole number"),
            ("1", "abc", "Record limit must be a positive whole number"),
            ("4", "2", "exceeds 3 available record(s)"),
        ):
            with (
                self.subTest(start=start, limit=limit),
                tempfile.TemporaryDirectory() as directory,
                patch("gems.app.LOG_PATH", Path(directory) / "gems.log"),
                patch("gems.app.load_dotenv"),
                patch("gems.app.load_settings", return_value={
                    "alma_mms_ids": "991, 992, 993", "start_record": start, "record_limit": limit,
                }),
                patch("gems.app.AlmaClient") as alma_client,
            ):
                page = MagicMock()
                main(page)
                controls = page.add.call_args_list[0].args[0].content.controls
                retrieve = next(
                    item for row in controls if isinstance(row, ft.Row)
                    for item in row.controls if isinstance(item, ft.FilledButton) and item.text == "Retrieve"
                )
                retrieve.on_click(None)
                alma_client.return_value.fetch_records.assert_not_called()
                footer = page.add.call_args_list[1].args[0].content.controls
                self.assertIn(message, next(item.value for item in footer if isinstance(item, ft.Text)))

    def test_last_typed_selection_restores_even_without_retrieval(self):
        stored = {"alma_set_selection": "9715828820004641", "alma_set_id": "9715828820004641"}
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("gems.app.LOG_PATH", Path(directory) / "gems.log"),
            patch("gems.app.load_dotenv"),
            patch("gems.app.load_settings", side_effect=lambda: dict(stored)),
            patch("gems.app.save_settings", side_effect=lambda settings: stored.update(settings)),
        ):
            def selection_field():
                page = MagicMock()
                main(page)
                controls = page.add.call_args_list[0].args[0].content.controls
                return next(
                    item for row in controls if isinstance(row, ft.Row)
                    for item in row.controls
                    if isinstance(item, ft.TextField) and item.label == "Alma Set ID or Collection Title"
                )

            field = selection_field()
            field.value = "Social Justice at Grinnell"
            field.on_change(None)
            self.assertEqual("Social Justice at Grinnell", stored["alma_set_selection"])
            self.assertEqual("Social Justice at Grinnell", selection_field().value)

            stored.pop("alma_set_selection")
            self.assertEqual("", selection_field().value)

    def test_collection_title_retrieves_collection_bibs_and_saves_pid(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("gems.app.LOG_PATH", Path(directory) / "gems.log"),
            patch("gems.app.load_dotenv"),
            patch("gems.app.load_settings", return_value={
                "alma_set_selection": "Social Justice at Grinnell", "export_root_path": directory,
            }),
            patch("gems.app.save_settings"),
            patch("gems.app.AlmaClient") as alma_client,
        ):
            alma_client.return_value.resolve_collection.return_value = ("8123", "Social Justice at Grinnell")
            alma_client.return_value.fetch_collection_bibs.return_value = ["991"]
            alma_client.return_value.fetch_records.return_value = [{"identifier": "991"}]
            page = MagicMock()
            main(page)
            controls = page.add.call_args_list[0].args[0].content.controls
            retrieve = next(
                item for control in controls if isinstance(control, ft.Row)
                for item in control.controls if isinstance(item, ft.FilledButton) and item.text == "Retrieve"
            )
            retrieve.on_click(None)
            alma_client.return_value.resolve_collection.assert_called_once_with("Social Justice at Grinnell")
            alma_client.return_value.fetch_collection_bibs.assert_called_once_with("8123")
            alma_client.return_value.fetch_set_members.assert_not_called()
            next(control for control in controls if isinstance(control, ft.FilledButton) and control.text.startswith("1)")).on_click(None)
            manifest = json.loads(next(Path(directory).glob("collection-social-justice-at-grinnell-8123/*/*.json")).read_text(encoding="utf-8"))
            self.assertEqual("Social Justice at Grinnell", manifest["collection_title"])
            self.assertEqual("8123", manifest["alma_collection_pid"])
            self.assertNotIn("alma_set_id", manifest)

    def test_retrieval_reports_ten_percent_milestones(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("gems.app.LOG_PATH", Path(directory) / "gems.log"),
            patch("gems.app.load_dotenv"),
            patch("gems.app.load_settings", return_value={"alma_mms_ids": ",".join(str(value) for value in range(100))}),
            patch("gems.app.save_settings"),
            patch("gems.app.AlmaClient") as alma_client,
        ):
            def fetch_records(mms_ids, *, on_progress):
                for completed in range(1, 101):
                    on_progress(completed, 100)
                return [{"identifier": value} for value in mms_ids]

            alma_client.return_value.fetch_records.side_effect = fetch_records
            page = MagicMock()
            main(page)
            controls = page.add.call_args_list[0].args[0].content.controls
            retrieve = next(
                item for control in controls if isinstance(control, ft.Row)
                for item in control.controls if isinstance(item, ft.FilledButton) and item.text == "Retrieve"
            )
            retrieve.on_click(None)

            log = (Path(directory) / "gems.log").read_text(encoding="utf-8")
            milestones = [line for line in log.splitlines() if "Retrieving Alma records:" in line]
            self.assertEqual(10, len(milestones))
            for percent, message in zip(range(10, 101, 10), milestones):
                self.assertIn(f"{percent}% ({percent}/100)", message)
            status = next(item for item in page.add.call_args_list[1].args[0].content.controls if isinstance(item, ft.Text))
            self.assertIn("Retrieved 100 Alma record(s)", status.value)

    def test_alma_set_name_is_used_for_manifest(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("gems.app.LOG_PATH", Path(directory) / "gems.log"),
            patch("gems.app.load_dotenv"),
            patch("gems.app.load_settings", return_value={"alma_set_selection": "123", "export_root_path": directory}),
            patch("gems.app.save_settings") as save_settings,
            patch("gems.app.AlmaClient") as alma_client,
        ):
            alma_client.return_value.fetch_set_title.return_value = "Campus Photo Archive"
            alma_client.return_value.fetch_set_members.return_value = ["991"]
            alma_client.return_value.fetch_records.return_value = [{"identifier": "991"}]
            page = MagicMock()
            main(page)
            controls = page.add.call_args_list[0].args[0].content.controls
            self.assertFalse(any(isinstance(control, ft.TextField) and control.label == "Collection title" for control in controls))
            selector = next(
                item for control in controls if isinstance(control, ft.Row)
                for item in control.controls
                if isinstance(item, ft.TextField) and item.label == "Alma Set ID or Collection Title"
            )
            self.assertEqual("123", selector.value)
            retrieve = next(
                item
                for control in controls if isinstance(control, ft.Row)
                for item in control.controls if isinstance(item, ft.FilledButton) and item.text == "Retrieve"
            )
            retrieve.on_click(None)
            next(control for control in controls if isinstance(control, ft.FilledButton) and control.text == "1) Export Alma Records to JSON Manifest").on_click(None)

            alma_client.return_value.fetch_set_title.assert_called_once_with("123")
            alma_client.return_value.fetch_set_members.assert_called_once_with("123")
            alma_client.return_value.resolve_collection.assert_not_called()
            manifest_path = Path(save_settings.call_args.args[0]["source_path"])
            self.assertRegex(manifest_path.name, r"^gems_campus-photo-archive_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_[^_/]+\.json$")
            self.assertEqual("set-campus-photo-archive-123", manifest_path.parent.parent.name)
            self.assertEqual(Path(directory), manifest_path.parent.parent.parent)
            self.assertEqual(directory, save_settings.call_args.args[0]["export_root_path"])
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual("Campus Photo Archive", manifest["collection_title"])
            self.assertEqual("123", manifest["alma_set_id"])
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
            copy_button = next(item for item in footer.controls if isinstance(item, ft.IconButton) and item.tooltip == "Copy status")
            copy_button.on_click(None)
            page.set_clipboard.assert_called_once_with(status.value)
            log_text = (Path(directory) / "gems.log").read_text(encoding="utf-8")
            self.assertIn("Alma retrieval failed: Cannot connect", log_text)
            self.assertIn("Traceback (most recent call last)", log_text)

    def test_alma_manifest_is_saved_and_used_by_csv_export(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("gems.app.LOG_PATH", Path(directory) / "gems.log"),
            patch("gems.app.load_dotenv"),
            patch("gems.app.load_settings", return_value={"alma_mms_ids": "123", "alma_set_selection": "Ignored set", "export_root_path": directory}),
            patch("gems.app.save_settings") as save_settings,
            patch("gems.app.AlmaClient") as alma_client,
        ):
            object_path = Path(directory) / "scan.txt"
            object_path.write_text("scan data", encoding="utf-8")
            record = {"identifier": "123", "metadata": {"title": "Test"}, "files": [
                {"path": str(object_path), "filename": "scan.txt"},
            ]}
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
            manifest_button = next(
                control for control in controls
                if isinstance(control, ft.FilledButton) and control.text == "1) Export Alma Records to JSON Manifest"
            )
            csv_button = next(
                item
                for control in controls if isinstance(control, ft.Row)
                for item in control.controls
                if isinstance(item, ft.FilledButton) and item.text == "2) Map and Export Manifest to CSV"
            )

            retrieve_button.on_click(None)
            alma_client.return_value.resolve_collection.assert_not_called()
            alma_client.return_value.fetch_set_members.assert_not_called()
            manifest_button.on_click(None)
            manifest_path = Path(save_settings.call_args.args[0]["source_path"])
            run_dir = manifest_path.parent
            self.assertEqual(Path(directory), run_dir.parent.parent)
            self.assertRegex(run_dir.parent.name, r"^mms-ids-[0-9a-f]{12}$")
            self.assertRegex(run_dir.name, r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_[^_/]+$")
            self.assertEqual(f"gems_mms-id-selection_{run_dir.name}.json", manifest_path.name)

            self.assertEqual([record], load_payload(manifest_path))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual("MMS ID selection", manifest["collection_title"])
            self.assertNotIn("alma_set_id", manifest)
            self.assertEqual([record], manifest["records"])
            self.assertIn(datetime.fromisoformat(manifest["created_at"]).strftime("%Y-%m-%d_%H-%M-%S_"), run_dir.name)
            self.assertEqual(str(manifest_path), save_settings.call_args.args[0]["source_path"])
            self.assertEqual(directory, save_settings.call_args.args[0]["export_root_path"])
            csv_button.on_click(None)
            self.assertTrue((run_dir / "collection_metadata.csv").exists())
            self.assertTrue((run_dir / "normalized_records.json").exists())
            self.assertEqual("scan data", (run_dir / "objects" / "scan.txt").read_text(encoding="utf-8"))
            log_text = (run_dir / "gems.log").read_text(encoding="utf-8")
            self.assertIn("Manifest contains 1 Alma record", log_text)
            self.assertIn("Export complete", log_text)
            log_button = next(
                item for item in footer.controls if isinstance(item, ft.IconButton) and item.tooltip == "View activity log"
            )
            log_button.on_click(None)
            self.assertIn("Export complete", page.overlay.append.call_args.args[0].content.content.value)

            retrieve_button.on_click(None)
            self.assertEqual(log_text, (run_dir / "gems.log").read_text(encoding="utf-8"))
            manifest_button.on_click(None)
            next_run_dir = Path(save_settings.call_args.args[0]["source_path"]).parent
            self.assertNotEqual(run_dir, next_run_dir)
            self.assertEqual(run_dir.parent, next_run_dir.parent)
            self.assertTrue((next_run_dir / f"gems_mms-id-selection_{next_run_dir.name}.json").exists())
            self.assertTrue((next_run_dir / "gems.log").exists())
            self.assertEqual(log_text, (run_dir / "gems.log").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()