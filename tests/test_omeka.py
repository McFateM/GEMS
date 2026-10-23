from __future__ import annotations

import copy
import csv
import io
import json
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import flet as ft
import requests

from gems.__main__ import cli
from gems.app import main
from gems.omeka import load_omeka
from gems.pipeline import ExportCancelled, process_export

FIXTURES = Path(__file__).parent / "fixtures" / "omeka"
ROOT = Path(__file__).parent.parent


class OmekaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source.json"
        self.output = self.root / "output"

    def fixture(self, name):
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    def write_source(self, payload):
        self.source.write_text(json.dumps(payload), encoding="utf-8")

    def download(self, url, destination):
        Path(destination).write_bytes(url.encode())
        return str(destination), None

    def export(self, payload, **kwargs):
        self.write_source(payload)
        with patch("gems.pipeline.urlretrieve", side_effect=self.download):
            return process_export(self.source, self.output, source_type="omeka", **kwargs)

    def rows(self, result, *, include_parents=False):
        with result.csv_path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
            self.assertNotIn("objectid", reader.fieldnames)
            self.assertNotIn("parentid", reader.fieldnames)
            self.assertFalse(any(name.startswith(("dc_", "dcterms_")) for name in reader.fieldnames))
        return rows if include_parents else [row for row in rows if not row["original_file_name"].startswith("_")]

    def assert_assets(self, result):
        rows = self.rows(result)
        assets = [path for path in result.objects_dir.rglob("*") if path.is_file()]
        self.assertEqual(len(rows), len(assets))
        self.assertEqual(sorted(row["original_file_name"] for row in rows), sorted(path.name for path in assets))
        self.assertEqual(len(assets), len({path.name.casefold() for path in assets}))
        self.assertTrue(all(path.parent != result.objects_dir for path in assets))
        self.assertTrue(all(row["filename"] == row["original_file_name"] for row in rows))
        self.assertFalse(any(row.get("display_template") == "compound_object" for row in rows))
        parents = [row for row in self.rows(result, include_parents=True)
                   if row["original_file_name"].startswith("_")]
        self.assertEqual(result.row_count, len(rows) + len(parents))
        for parent in parents:
            folder = next(path.parent for path in assets if path.name == parent["original_file_name"][1:])
            names = {path.name for path in assets if path.parent == folder}
            children = [row for row in rows if row["original_file_name"] in names]
            self.assertGreater(len(children), 1)
            self.assertEqual(f"_{min(row['original_file_name'] for row in children)}", parent["original_file_name"])
            self.assertEqual(children[0]["title"], parent["title"])
        return rows, assets

    def test_classic_single_uses_original_and_preserves_source_not_dart_ids(self):
        result = self.export(self.fixture("classic-single.json"))
        rows, assets = self.assert_assets(result)
        self.assertEqual((1, 1), (result.row_count, result.file_count))
        self.assertEqual("Campus photograph", rows[0]["title"])
        self.assertEqual("Archives", rows[0]["creator"])
        self.assertEqual("photo:1", rows[0]["identifier"])
        self.assertEqual("1", rows[0]["originating_system_id"])
        self.assertEqual("omeka_classic", rows[0]["source_system"])
        self.assertEqual("https://classic.example.org/api/items/1", rows[0]["source_record_url"])
        self.assertEqual("Campus_photo.jpg", rows[0]["original_file_name"])
        self.assertEqual(self.output / "objects" / "Campus_photo" / "Campus_photo.jpg", assets[0])
        self.assertIn("/original/", assets[0].read_text())
        self.assertNotIn("objectid", self.source.read_text())

    def test_classic_multiple_natural_sequence_repeats_metadata_and_reports_progress(self):
        progress = []
        result = self.export(self.fixture("classic-multiple.json"), progress=lambda *args: progress.append(args))
        rows, assets = self.assert_assets(result)
        self.assertEqual(2, len(rows))
        self.assertEqual({"Ledger",}, {row["title"] for row in rows})
        self.assertEqual({"Campus; History"}, {row["subject"] for row in rows})
        self.assertEqual({""}, {row["date"] for row in rows})
        self.assertEqual(["Ledger_10-01.tif", "Ledger_10-02.tif"], [row["original_file_name"] for row in rows])
        self.assertEqual(1, len({path.parent for path in assets}))
        self.assertIn("page2.tif", assets[0].read_text() if assets[0].name.endswith("01.tif") else assets[1].read_text())
        self.assertEqual(0, progress[0][1])
        self.assertEqual(2, progress[0][2])
        self.assertEqual(("", 2, 2), progress[-1])

    def test_s_json_ld_values_media_and_empty_fields(self):
        result = self.export(self.fixture("s-media.json"))
        rows, _ = self.assert_assets(result)
        self.assertEqual(2, len(rows))
        for row in rows:
            self.assertEqual("Oral history", row["title"])
            self.assertEqual("Speaker One; Speaker Two", row["creator"])
            self.assertEqual("https://id.example.org/history", row["subject"])
            self.assertEqual("", row["description"])
            self.assertEqual("", row["language"])
            self.assertEqual("omeka_s", row["source_system"])
        self.assertTrue(rows[0]["original_file_name"].startswith("Interview"))

    def test_wmi_csv_export_loads_metadata_and_direct_media_urls(self):
        self.source = self.root / "wmi-export.csv"
        headers = [
            "o:id", "o:media[o:id]", "o:media[file]", "dcterms:title",
            "dcterms:creator", "wmi:instrumentCategory",
        ]
        with self.source.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers)
            writer.writeheader()
            writer.writerow({
                "o:id": "626",
                "o:media[o:id]": "676 | 678",
                "o:media[file]": (
                    "https://omeka.example/original/cover.jpg | "
                    "https://omeka.example/original/audio.mp3"
                ),
                "dcterms:title": "Rebab",
                "dcterms:creator": "Maker One | Maker Two",
                "wmi:instrumentCategory": "chordophone",
            })
        records = load_omeka(self.source)
        self.assertEqual(1, len(records))
        record = records[0]
        self.assertEqual("626", record["originating_system_id"])
        self.assertEqual("omeka_s-626-1", record["source_record_id"])
        self.assertEqual("Rebab", record["metadata"]["title"])
        self.assertEqual("Maker One; Maker Two", record["metadata"]["creator"])
        self.assertEqual("chordophone", record["metadata"]["wmi:instrumentCategory"])
        self.assertEqual([
            {"source": "https://omeka.example/original/cover.jpg", "filename": "cover.jpg"},
            {"source": "https://omeka.example/original/audio.mp3", "filename": "audio.mp3"},
        ], record["files"])
        self.assertEqual(2, len(load_omeka(self.source)[0]["files"]))

    def test_actual_wmi_csv_export_processes_item_and_downloads_direct_urls(self):
        source = ROOT / "CSV-20261023-022505.csv"
        records = load_omeka(source)
        self.assertEqual(656, len(records))
        self.assertEqual(1877, sum(len(record["files"]) for record in records))
        self.assertEqual("626", records[0]["originating_system_id"])
        self.assertEqual(2, len(records[0]["files"]))
        self.assertEqual("chordophone", records[0]["metadata"]["wmi:instrumentCategory"])
        with patch("gems.pipeline.urlretrieve", side_effect=self.download):
            result = process_export(source, self.output, source_type="omeka", start=1, limit=1)
        rows, assets = self.assert_assets(result)
        self.assertEqual(2, len(rows))
        self.assertEqual({"rebab"}, {row["title"].strip() for row in rows})
        self.assertEqual({"omeka_s"}, {row["source_system"] for row in rows})
        self.assertEqual(2, len(assets))

    def test_template_mapping_reuses_rules_and_creates_parent_metadata_without_ids(self):
        template = json.loads((ROOT / "maps" / "alma-dc-to-grinnell.json").read_text())
        with patch("gems.pipeline.assign_objectids", side_effect=AssertionError("must not assign IDs")):
            result = self.export(self.fixture("classic-multiple.json"), field_map=template)
        rows, _ = self.assert_assets(result)
        self.assertEqual(2, len(rows))
        self.assertEqual({"Campus; History"}, {row["keywords"] for row in rows})
        self.assertEqual({"Ledger"}, {row["title"] for row in rows})

    def test_simple_field_map(self):
        result = self.export(self.fixture("classic-single.json"), field_map={"description": "dc:title"})
        self.assertEqual("Campus photograph", self.rows(result)[0]["description"])

    def test_no_media_skipped_with_warning_and_no_invented_file(self):
        payload = self.fixture("classic-single.json")
        payload[0]["files_list"] = []
        with self.assertLogs("gems", level="WARNING") as logs:
            result = self.export(payload)
        self.assertEqual((0, 0), (result.row_count, result.file_count))
        self.assertEqual(["omeka_classic-1-1"], result.skipped_records)
        self.assertIn("no media", logs.output[0])
        self.assert_assets(result)

    def test_empty_export_has_header_and_no_rows(self):
        self.assertEqual([], self.rows(self.export([])))

    def test_invalid_payloads_and_unexpanded_media_are_actionable(self):
        cases = [
            (None, "array"),
            ([5], "JSON object"),
            ({"title": "not Omeka"}, "Unrecognized"),
            ({"element_texts": "bad"}, "element_texts"),
            ({"element_texts": [], "files": {"count": 1, "url": "https://example.org/api/files"}}, "embed"),
            ({"element_texts": [], "files_list": [{}]}, "media URL"),
            ({"@type": "o:Item", "o:media": [{"@id": "file:///tmp/media.json"}]}, "HTTP"),
            ({"@type": "o:Item", "o:media": [{"o:original_url": "ftp://example.org/file.jpg"}]}, "media URL"),
        ]
        for payload, message in cases:
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(ValueError, message):
                    self.export(payload)
                self.assertFalse((self.output / "collection_metadata.csv").exists())
        self.source.write_text('{"items": [', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Malformed Omeka JSON at line"):
            process_export(self.source, self.output, source_type="omeka")

    def test_fullsize_fallback_uses_derivative_extension(self):
        payload = self.fixture("classic-single.json")
        file = payload[0]["files_list"][0]
        file["original_filename"] = "master.tif"
        del file["file_urls"]["original"]
        result = self.export(payload)
        rows, assets = self.assert_assets(result)
        self.assertEqual("campus.jpg", rows[0]["original_file_name"])
        self.assertIn("/fullsize/", assets[0].read_text())

    def test_filename_and_folder_clashes_are_isolated_even_with_same_source_url(self):
        payload = self.fixture("classic-single.json")
        for index in range(2, 5):
            item = copy.deepcopy(payload[0])
            item["id"] = index
            item["files_list"][0]["original_filename"] = "campus PHOTO.jpg"
            payload.append(item)
        payload[-1]["files_list"] *= 2
        result = self.export(payload)
        rows, assets = self.assert_assets(result)
        self.assertEqual(5, len(rows))
        self.assertEqual(4, len({path.parent for path in assets}))
        self.assertTrue(result.renamed_files)

    def test_generic_and_unsafe_names_never_create_dart_ids_or_escape_output(self):
        payload = self.fixture("classic-multiple.json")["items"]
        payload[0]["files_list"][0]["original_filename"] = "991011591179304641.tif"
        payload[0]["files_list"][1]["original_filename"] = "991011591179304642.tif"
        payload[0]["element_texts"] = []
        result = self.export(payload)
        _, assets = self.assert_assets(result)
        self.assertTrue(all("dg_" not in str(path.relative_to(self.output)) for path in assets))
        payload[0]["files_list"][0]["original_filename"] = "../../outside.jpg"
        self.output = self.root / "unsafe-output"
        self.assert_assets(self.export(payload))

    def test_numeric_single_without_title_keeps_extension(self):
        payload = self.fixture("classic-single.json")
        payload[0]["files_list"][0]["original_filename"] = "991011591179304641.jpg"
        payload[0]["element_texts"] = []
        rows, _ = self.assert_assets(self.export(payload))
        self.assertEqual("omeka-classic-1-1.jpg", rows[0]["original_file_name"])

    def test_local_media_is_copied_through_existing_download_code(self):
        asset = self.root / "local file.pdf"
        asset.write_bytes(b"local original")
        payload = self.fixture("classic-single.json")
        payload[0]["files_list"][0]["original_filename"] = "local file.pdf"
        payload[0]["files_list"][0]["file_urls"]["original"] = asset.as_uri()
        self.write_source(payload)
        result = process_export(self.source, self.output, source_type="omeka")
        _, files = self.assert_assets(result)
        self.assertEqual(asset.read_bytes(), files[0].read_bytes())

    def test_invalid_maps_are_actionable(self):
        for field_map, message in [
            ([], "JSON object"),
            ({"columns": ["title"], "rules": []}, "rules"),
            ({"columns": [5]}, "text field names"),
            ({"columns": ["dc_title"]}, "unprefixed"),
            ({"title": 5}, "as text"),
        ]:
            with self.subTest(field_map=field_map):
                with self.assertRaisesRegex(ValueError, message):
                    self.export(self.fixture("classic-single.json"), field_map=field_map)

    def test_missing_source_identifier_is_not_invented(self):
        payload = self.fixture("classic-single.json")
        del payload[0]["id"]
        rows, _ = self.assert_assets(self.export(payload))
        self.assertEqual("", rows[0]["originating_system_id"])

    def test_s_item_without_media_and_non_json_input(self):
        with self.assertLogs("gems", level="WARNING"):
            result = self.export({"dcterms:title": [{"@value": "No media"}]})
        self.assertEqual((0, 0), (result.row_count, result.file_count))
        self.source = self.root / "export.csv"
        self.source.write_text("title\nNot JSON\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "missing required column"):
            process_export(self.source, self.output, source_type="omeka")

    def test_download_and_write_failures_emit_no_csv_and_remove_partial_files(self):
        for error in (HTTPError("https://example.org", 404, "Not found", {}, None),
                      URLError("unreachable"), PermissionError("read-only volume")):
            if isinstance(error, HTTPError):
                self.addCleanup(error.close)
            with self.subTest(error=error):
                self.write_source(self.fixture("classic-single.json"))

                def fail(url, destination):
                    Path(destination).write_bytes(b"incomplete")
                    raise error

                with patch("gems.pipeline.urlretrieve", side_effect=fail):
                    with self.assertRaisesRegex(ValueError, "Could not save.*Campus_photo"):
                        process_export(self.source, self.output, source_type="omeka")
                self.assertFalse((self.output / "collection_metadata.csv").exists())
                self.assertEqual([], [path for path in self.output.rglob("*") if path.is_file()])

    def test_later_download_failure_does_not_publish_any_rows(self):
        self.write_source(self.fixture("classic-multiple.json"))
        calls = []

        def download(url, destination):
            calls.append(url)
            if len(calls) == 2:
                raise URLError("offline")
            return self.download(url, destination)

        with patch("gems.pipeline.urlretrieve", side_effect=download):
            with self.assertRaises(ValueError):
                process_export(self.source, self.output, source_type="omeka")
        self.assertEqual(2, len(calls))
        self.assertEqual(1, len([path for path in self.output.rglob("*") if path.is_file()]))
        self.assertFalse((self.output / "collection_metadata.csv").exists())

    def test_skip_download_errors_keeps_good_files_and_reports_each_failure(self):
        payload = self.fixture("classic-multiple.json")
        self.write_source(payload)
        calls = []

        def download(url, destination):
            calls.append(url)
            if len(calls) == 1:
                Path(destination).write_bytes(b"partial download")
                raise HTTPError(url, 403, "Forbidden", {}, None)
            return self.download(url, destination)

        with patch("gems.pipeline.urlretrieve", side_effect=download), self.assertLogs("gems", level="WARNING"):
            result = process_export(self.source, self.output, source_type="omeka", skip_download_errors=True)
        rows, assets = self.assert_assets(result)
        self.assertEqual((1, 1, 2), (result.row_count, result.file_count, len(calls)))
        self.assertEqual(1, len(result.failed_downloads))
        with result.download_errors_path.open(encoding="utf-8", newline="") as handle:
            errors = list(csv.DictReader(handle))
        self.assertEqual(result.failed_downloads, errors)
        self.assertEqual("403", errors[0]["http_status"])
        self.assertEqual(calls[0], errors[0]["url"])
        self.assertEqual("Ledger", errors[0]["title"])
        self.assertNotEqual(errors[0]["filename"], rows[0]["original_file_name"])
        self.assertFalse(any(".gems-" in path.name or path.name.endswith(".part") for path in assets))
        recovered = self.export(payload, skip_download_errors=True)
        self.assertEqual((3, 2), (recovered.row_count, recovered.file_count))
        self.assertEqual([], recovered.failed_downloads)
        with (self.output / "download_errors.csv").open(encoding="utf-8", newline="") as handle:
            self.assertEqual(errors, list(csv.DictReader(handle)))

    def test_parent_uses_first_successful_filename_and_is_replaced_on_retry(self):
        payload = self.fixture("classic-multiple.json")
        item = payload["items"][0]
        third = copy.deepcopy(item["files_list"][1])
        third["file_urls"]["original"] = "https://example.org/page3.tif"
        item["files_list"].append(third)
        self.write_source(payload)

        def download(url, destination):
            if "page2.tif" in url:
                raise HTTPError(url, 403, "Forbidden", {}, None)
            return self.download(url, destination)

        with patch("gems.pipeline.urlretrieve", side_effect=download):
            result = process_export(self.source, self.output, source_type="omeka", skip_download_errors=True)
        rows = self.rows(result, include_parents=True)
        self.assertEqual((3, 2), (result.row_count, result.file_count))
        self.assertEqual("_" + min(row["original_file_name"] for row in rows[1:]), rows[0]["original_file_name"])
        self.assertEqual("Ledger", rows[0]["title"])
        result = self.export(payload)
        rows = self.rows(result, include_parents=True)
        self.assertEqual((4, 3), (result.row_count, result.file_count))
        self.assertEqual(1, sum(row["original_file_name"].startswith("_") for row in rows))
        self.assertEqual("_Ledger_10-01.tif", rows[0]["original_file_name"])

    def test_skip_download_errors_does_not_hide_local_write_errors(self):
        self.write_source(self.fixture("classic-single.json"))
        with patch("gems.pipeline.urlretrieve", side_effect=PermissionError("read-only filesystem")):
            with self.assertRaisesRegex(ValueError, "read-only filesystem"):
                process_export(self.source, self.output, source_type="omeka", skip_download_errors=True)
        self.assertFalse((self.output / "collection_metadata.csv").exists())
        self.assertFalse((self.output / "download_errors.csv").exists())

    def test_skip_network_errors_appends_report_across_batches_and_retries(self):
        payload = self.fixture("classic-single.json") + self.fixture("s-media.json")
        self.write_source(payload)
        with patch("gems.pipeline.urlretrieve", side_effect=URLError("unreachable")), self.assertLogs("gems"):
            first = process_export(
                self.source, self.output, source_type="omeka", skip_download_errors=True, start=1, limit=1,
            )
            second = process_export(
                self.source, self.output, source_type="omeka", skip_download_errors=True, start=2, limit=1,
            )
        self.assertEqual((0, 0), (first.row_count, second.row_count))
        with (self.output / "download_errors.csv").open(encoding="utf-8", newline="") as handle:
            failures = list(csv.DictReader(handle))
        self.assertEqual(3, len(failures))
        self.assertEqual({"1", "3"}, {failure["originating_system_id"] for failure in failures})
        self.assertEqual({""}, {failure["http_status"] for failure in failures})
        self.assert_assets(second)

    def test_skip_download_errors_report_write_failure_stops_export(self):
        self.write_source(self.fixture("classic-single.json"))
        self.output.mkdir()
        (self.output / "download_errors.csv").mkdir()
        with patch("gems.pipeline.urlretrieve", side_effect=URLError("unreachable")):
            with self.assertRaises(OSError):
                process_export(self.source, self.output, source_type="omeka", skip_download_errors=True)
        self.assertFalse((self.output / "collection_metadata.csv").exists())

    def test_cli_skip_download_errors_warns_and_excludes_failed_asset(self):
        self.write_source(self.fixture("classic-single.json"))
        with (
            patch("sys.argv", ["gems", "--headless", "--source-type", "omeka",
                               "--source", str(self.source), "--output", str(self.output),
                               "--skip-download-errors"]),
            patch("gems.pipeline.urlretrieve", side_effect=URLError("unreachable")),
            self.assertLogs("gems"),
            redirect_stdout(io.StringIO()) as stdout,
            redirect_stderr(io.StringIO()) as stderr,
        ):
            self.assertEqual(0, cli())
        self.assertIn("0 row(s), 0 file(s)", stdout.getvalue())
        self.assertIn("incomplete export; skipped 1 failed download(s)", stderr.getvalue())
        self.assertIn(str(self.output / "download_errors.csv"), stderr.getvalue())

    def test_incompatible_output_is_rejected_before_downloading(self):
        payload = self.fixture("classic-single.json")
        self.export(payload)
        payload[0]["files_list"][0]["original_filename"] = "different.jpg"
        self.write_source(payload)
        with patch("gems.pipeline.urlretrieve") as download:
            with self.assertRaisesRegex(ValueError, "fresh output folder"):
                process_export(self.source, self.output, source_type="omeka")
        download.assert_not_called()

    def test_unmatched_assets_from_a_previous_failed_run_are_rejected(self):
        self.output.mkdir()
        objects = self.output / "objects"
        objects.mkdir()
        (objects / "unrelated.jpg").write_bytes(b"previous asset")
        self.write_source(self.fixture("classic-single.json"))
        with patch("gems.pipeline.urlretrieve") as download:
            with self.assertRaisesRegex(ValueError, "objects folder contains assets"):
                process_export(self.source, self.output, source_type="omeka")
        download.assert_not_called()

    def test_missing_unselected_asset_is_reported_instead_of_retaining_a_usable_row(self):
        payload = self.fixture("classic-single.json") + self.fixture("s-media.json")
        result = self.export(payload, start=1, limit=1)
        next(result.objects_dir.rglob("*.jpg")).unlink()
        self.write_source(payload)
        with patch("gems.pipeline.urlretrieve") as download:
            with self.assertRaisesRegex(ValueError, "missing asset"):
                process_export(self.source, self.output, source_type="omeka", start=2, limit=1)
        download.assert_not_called()
        self.assertEqual(1, self.export(payload, start=1, limit=1).file_count)

    def test_duplicate_compound_names_keep_sequence_number_last(self):
        payload = self.fixture("classic-multiple.json")["items"]
        payload.append(copy.deepcopy(payload[0]))
        result = self.export(payload)
        rows, assets = self.assert_assets(result)
        self.assertEqual(4, len(rows))
        self.assertEqual(2, len({path.parent for path in assets}))
        for row in rows:
            self.assertRegex(row["original_file_name"], r"-0[12]\.tif$")

    def test_s_qualified_fields_follow_existing_aliases(self):
        payload = self.fixture("s-media.json")
        payload[0]["dcterms:created"] = [{"@value": "1950"}]
        payload[0]["dcterms:spatial"] = [{"@value": "Grinnell"}]
        rows = self.rows(self.export(payload))
        self.assertEqual("1950", rows[0]["date"])
        self.assertEqual("Grinnell", rows[0]["coverage"])

    def test_asset_write_and_csv_write_failures_propagate(self):
        self.write_source(self.fixture("classic-single.json"))
        with patch("gems.pipeline.urlretrieve", side_effect=self.download), patch(
            "gems.pipeline.Path.replace", side_effect=PermissionError("cannot write destination")
        ):
            with self.assertRaisesRegex(ValueError, "cannot write destination"):
                process_export(self.source, self.output, source_type="omeka")
        self.assertFalse((self.output / "collection_metadata.csv").exists())
        with patch("gems.pipeline.urlretrieve", side_effect=self.download), patch(
            "gems.pipeline.write_collection_csv", side_effect=PermissionError("cannot write CSV")
        ):
            with self.assertRaisesRegex(PermissionError, "cannot write CSV"):
                process_export(self.source, self.output, source_type="omeka")

    def test_batches_merge_in_export_order_and_reruns_do_not_duplicate(self):
        payload = self.fixture("classic-single.json") + self.fixture("s-media.json")
        first = self.export(payload, start=2, limit=1)
        self.assertEqual(3, first.row_count)
        second = self.export(payload, start=1, limit=1)
        rows, _ = self.assert_assets(second)
        self.assertEqual(3, len(rows))
        self.assertEqual("Campus photograph", rows[0]["title"])
        third = self.export(payload, start=2, limit=1)
        self.assertEqual(rows, self.rows(third))

    def test_cancellation_preserves_no_success_csv(self):
        with self.assertRaises(ExportCancelled):
            self.export(self.fixture("classic-single.json"), is_cancelled=lambda: True)
        self.assertFalse((self.output / "collection_metadata.csv").exists())

    def test_real_http_download_and_cli(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"physical asset")

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            payload = self.fixture("classic-single.json")
            payload[0]["files_list"][0]["file_urls"]["original"] = f"http://127.0.0.1:{server.server_port}/image.jpg"
            self.write_source(payload)
            with patch("sys.argv", ["gems", "--headless", "--source-type", "omeka",
                                    "--source", str(self.source), "--output", str(self.output)]), redirect_stdout(io.StringIO()) as stdout:
                self.assertEqual(0, cli())
            result_path = self.output / "objects" / "Campus_photo" / "Campus_photo.jpg"
            self.assertEqual(b"physical asset", result_path.read_bytes())
            self.assertIn("1 row(s), 1 file(s)", stdout.getvalue())
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

    def test_cli_malformed_json_has_nonzero_exit_and_actionable_error(self):
        self.source.write_text("{bad", encoding="utf-8")
        with patch("sys.argv", ["gems", "--headless", "--source-type", "omeka",
                                "--source", str(self.source), "--output", str(self.output)]), redirect_stderr(io.StringIO()) as stderr:
            with self.assertRaises(SystemExit) as exc:
                cli()
        self.assertEqual(2, exc.exception.code)
        self.assertIn("Malformed Omeka JSON", stderr.getvalue())

    def test_ui_selects_omeka_exports_to_configured_folder_without_alma(self):
        self.source = self.root / "source.csv"
        with self.source.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["o:id", "o:media[file]", "dcterms:title"])
            writer.writeheader()
            writer.writerow({
                "o:id": "626",
                "o:media[file]": "https://omeka.example/original/cover.jpg",
                "dcterms:title": "Rebab",
            })
        with (
            patch("gems.app.LOG_PATH", self.root / "gems.log"),
            patch("gems.app.load_dotenv"),
            patch("gems.app.load_settings", return_value={
                "source_type": "omeka", "source_path": str(self.source),
                "omeka_output_path": str(self.output),
            }),
            patch("gems.app.save_settings") as save,
            patch("gems.app.AlmaClient") as alma,
            patch("gems.pipeline.urlretrieve", side_effect=self.download),
        ):
            page = MagicMock()
            main(page)
            controls = page.add.call_args_list[0].args[0].content.controls
            dropdown = next(control for control in controls if isinstance(control, ft.Dropdown))
            self.assertEqual("omeka", dropdown.value)
            export = next(control for control in controls if isinstance(control, ft.Row)
                          for control in control.controls if isinstance(control, ft.FilledButton))
            export.on_click(None)
            self.assertTrue((self.output / "collection_metadata.csv").exists())
            self.assertEqual("omeka", save.call_args.args[0]["source_type"])
            alma.assert_not_called()

    def test_ui_surfaces_malformed_json_and_skipped_media(self):
        for malformed in (True, False):
            with self.subTest(malformed=malformed):
                if malformed:
                    self.source.write_text("{bad", encoding="utf-8")
                else:
                    payload = self.fixture("classic-single.json")
                    payload[0]["files_list"] = []
                    self.write_source(payload)
                with (
                    patch("gems.app.LOG_PATH", self.root / "gems.log"),
                    patch("gems.app.load_dotenv"),
                    patch("gems.app.load_settings", return_value={
                        "source_type": "omeka", "source_path": str(self.source),
                        "omeka_output_path": str(self.output),
                    }),
                    patch("gems.app.save_settings"),
                ):
                    page = MagicMock()
                    main(page)
                    controls = page.add.call_args_list[0].args[0].content.controls
                    export = next(control for control in controls if isinstance(control, ft.Row)
                                  for control in control.controls if isinstance(control, ft.FilledButton))
                    export.on_click(None)
                    status = next(control.value for control in page.add.call_args_list[1].args[0].content.controls
                                  if isinstance(control, ft.Text))
                    self.assertIn("Malformed Omeka JSON" if malformed else "Skipped 1 item(s) without media", status)

    def test_loader_does_not_modify_export(self):
        self.write_source(self.fixture("s-media.json"))
        before = self.source.read_bytes()
        records = load_omeka(self.source)
        self.assertEqual(before, self.source.read_bytes())
        self.assertEqual(2, len(records[0]["files"]))

    def reference_payload(self):
        payload = self.fixture("s-media.json")
        payload[0]["o:media"] = [{"@id": "https://s.example.org/api/media/30", "o:id": 30}]
        return payload

    def test_s_media_references_resolve_with_progress_and_preserve_source(self):
        payload = self.reference_payload()
        self.write_source(payload)
        before = self.source.read_bytes()
        progress = []
        with patch("gems.omeka.requests.Session") as session:
            response = session.return_value.__enter__.return_value.get.return_value.__enter__.return_value
            response.json.return_value = self.fixture("s-media.json")[0]["o:media"][0]
            with patch("gems.pipeline.urlretrieve", side_effect=self.download):
                result = process_export(self.source, self.output, source_type="omeka",
                                        progress=lambda *args: progress.append(args))
            client = session.return_value.__enter__.return_value
            client.get.assert_called_once_with("https://s.example.org/api/media/30", timeout=30)
            response.raise_for_status.assert_called_once()
        rows, _ = self.assert_assets(result)
        self.assertEqual(1, len(rows))
        self.assertEqual("Interview.mp3", rows[0]["original_file_name"])
        self.assertTrue(progress[0][0].startswith("Resolving"))
        self.assertEqual(before, self.source.read_bytes())

    def test_s_media_reference_resolution_errors_are_explicit_and_emit_no_csv(self):
        for error, payload in [
            (requests.ConnectionError("network unavailable"), None),
            (requests.HTTPError("403 Forbidden"), None),
            (ValueError("invalid JSON"), None),
            (None, []),
            (None, {"@id": "https://s.example.org/api/media/30"}),
        ]:
            with self.subTest(error=error, payload=payload):
                self.write_source(self.reference_payload())
                with patch("gems.omeka.requests.Session") as session:
                    response = session.return_value.__enter__.return_value.get.return_value.__enter__.return_value
                    response.json.side_effect = error
                    response.json.return_value = payload
                    with self.assertRaisesRegex(ValueError, "omeka_s item 3, media 1:.*media API reference"):
                        process_export(self.source, self.output, source_type="omeka")
                self.assertFalse((self.output / "collection_metadata.csv").exists())

    def test_repeated_s_reference_is_resolved_once_and_offline_preview_never_requests(self):
        payload = self.reference_payload()
        payload[0]["o:media"] *= 2
        self.write_source(payload)
        with patch("gems.omeka.requests.Session") as session:
            client = session.return_value.__enter__.return_value
            preview = load_omeka(self.source)
            self.assertEqual(2, len(preview[0]["files"]))
            client.get.assert_not_called()
            client.get.return_value.__enter__.return_value.json.return_value = self.fixture("s-media.json")[0]["o:media"][0]
            with patch("gems.pipeline.urlretrieve", side_effect=self.download):
                result = process_export(self.source, self.output, source_type="omeka")
            client.get.assert_called_once()
        self.assertEqual(2, len(self.assert_assets(result)[0]))

    def test_cancellation_between_media_reference_requests(self):
        payload = self.reference_payload()
        payload[0]["o:media"].append({"@id": "https://s.example.org/api/media/31"})
        self.write_source(payload)
        cancelled = False

        def resolve():
            nonlocal cancelled
            cancelled = True
            return self.fixture("s-media.json")[0]["o:media"][0]

        with patch("gems.omeka.requests.Session") as session:
            client = session.return_value.__enter__.return_value
            client.get.return_value.__enter__.return_value.json.side_effect = resolve
            with self.assertRaises(ExportCancelled):
                process_export(self.source, self.output, source_type="omeka", is_cancelled=lambda: cancelled)
            client.get.assert_called_once()
        self.assertFalse(self.output.exists())

    def test_real_http_media_resolution_download_and_transient_retry(self):
        calls = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                calls.append(self.path)
                if self.path == "/api/media/30":
                    if calls.count(self.path) == 1:
                        self.send_response(503)
                        self.end_headers()
                        return
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "o:id": 30,
                        "o:source": "Interview.mp3",
                        "o:original_url": f"http://127.0.0.1:{self.server.server_port}/original.mp3",
                    }).encode())
                else:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"resolved physical asset")

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            payload = self.reference_payload()
            payload[0]["o:media"][0]["@id"] = f"http://127.0.0.1:{server.server_port}/api/media/30"
            self.write_source(payload)
            result = process_export(self.source, self.output, source_type="omeka")
            rows, assets = self.assert_assets(result)
            self.assertEqual("Interview.mp3", rows[0]["original_file_name"])
            self.assertEqual(b"resolved physical asset", assets[0].read_bytes())
            self.assertEqual(["/api/media/30", "/api/media/30", "/original.mp3"], calls)
        finally:
            server.shutdown()
            thread.join()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
