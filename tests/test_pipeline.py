from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from gems.pipeline import normalize_records, process_export


class PipelineTests(unittest.TestCase):
    def test_normalize_records_honors_field_map_and_expands_files(self):
        records = [
            {
                "record_id": "abc123",
                "metadata": {"display title": "Campus Photo", "license statement": "CC-BY"},
                "descriptiveMetadata": [
                    {"label": "creator name", "value": "University Archives"},
                    {"label": "resource type", "value": "Image"},
                ],
                "files": [
                    {"path": "/tmp/file-one.jpg", "name": "first.jpg"},
                    {"path": "/tmp/file-two.jpg", "name": "second.jpg"},
                ],
            }
        ]

        rows = normalize_records(
            records,
            field_map={"title": "display title", "creator": "creator name", "rights": "license statement"},
            source_system="specto",
        )

        self.assertEqual(2, len(rows))
        self.assertEqual("abc123-1", rows[0]["identifier"])
        self.assertEqual("abc123-2", rows[1]["identifier"])
        self.assertEqual("Campus Photo", rows[0]["title"])
        self.assertEqual("University Archives", rows[0]["creator"])
        self.assertEqual("CC-BY", rows[0]["rights"])
        self.assertEqual("specto", rows[0]["source_system"])

    def test_process_export_writes_collectionbuilder_csv_and_copies_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source_file = tmp / "source.json"
            file_one = tmp / "scan-1.tif"
            file_two = tmp / "scan-2.tif"
            file_one.write_text("image-one", encoding="utf-8")
            file_two.write_text("image-two", encoding="utf-8")
            source_file.write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "identifier": "obj-9",
                                "metadata": {"title": "Ledger", "creator": "Town Clerk"},
                                "files": [
                                    {"path": str(file_one), "filename": "ledger-1.tif"},
                                    {"path": str(file_two), "filename": "ledger-2.tif"},
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = process_export(source_file, tmp / "out")

            self.assertEqual(2, result.row_count)
            self.assertEqual(2, result.file_count)
            self.assertTrue((tmp / "out" / "objects" / "ledger-1.tif").exists())
            self.assertTrue((tmp / "out" / "objects" / "ledger-2.tif").exists())

            with result.csv_path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual("obj-9-1", rows[0]["identifier"])
            self.assertEqual("Ledger", rows[0]["title"])
            self.assertEqual("Town Clerk", rows[0]["creator"])
            self.assertEqual("objects/ledger-1.tif", rows[0]["objectid"])
            self.assertEqual("objects/ledger-2.tif", rows[1]["objectid"])
            self.assertTrue(result.json_path.exists())


if __name__ == "__main__":
    unittest.main()
