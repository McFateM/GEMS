from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from gems.pipeline import normalize_records, process_export, process_records


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

    def test_grinnell_template_map_builds_compound_and_single_rows(self):
        field_map = json.loads((Path(__file__).parent.parent / "maps" / "alma-dc-to-grinnell.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            for name in ("grinnell_12_OBJ.jpg", "grinnell_11_OBJ.jpg", "grinnell_5_OBJ.pdf"):
                (tmp / name).write_text(name, encoding="utf-8")
            metadata = {
                "dc:title": "Symposium photos", "dc:creator": "Brown, John, 1800-1859; Des Moines Register",
                "dc:subject": "Old alt title", "dcterms:subject (dcterms:LCSH)": "Slavery; Brown, John, 1800-1859",
                "dc:type": "compound", "dcterms:created": "2011", "dcterms:dateAccepted": "2011-10",
                "dc:identifier": "grinnell:10; http://hdl.handle.net/11084/10; alma:x",
                "dcterms:identifier (dcterms:URI)": "http://hdl.handle.net/11084/10",
                "dcterms:isPartOf": "Social Justice at Grinnell; Digital Grinnell",
                "dc:rights": '<a href="https://rightsstatements.org/page/NoC-US/1.0/?language=en">Public Domain</a>',
            }
            records = [
                {
                    "mms_id": "991", "metadata": metadata,
                    "representations": [
                        {"id": f"rep{number}", "label": f"Photo {number}",
                         "files": {"representation_file": [{"label": f"grinnell_{number}_OBJ.jpg", "thumbnail_url": f"thumb{number}"}]}}
                        for number in (12, 11)
                    ],
                    "files": [{"source": str(tmp / f"grinnell_{number}_OBJ.jpg"), "filename": f"grinnell_{number}_OBJ.jpg"} for number in (12, 11)],
                },
                {
                    "mms_id": "992", "metadata": {"dc:title": "Clipping", "dc:type": "text", "dcterms:type (dcterms:DCMIType)": "Text"},
                    "files": [{"source": str(tmp / "grinnell_5_OBJ.pdf"), "filename": "grinnell_5_OBJ.pdf"}],
                },
            ]

            result = process_records(records, tmp / "out", field_map=field_map)

            self.assertEqual(3, result.file_count)
            with result.csv_path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)
            self.assertEqual(field_map["columns"], reader.fieldnames)
            parent, first, second, single = rows
            self.assertRegex(parent["objectid"], r"^dg_\d{10}$")
            self.assertEqual(("", "compound_object"), (parent["parentid"], parent["display_template"]))
            numbers = [int(row["objectid"].rsplit("_", 1)[1]) for row in rows]
            self.assertEqual(list(range(numbers[0], numbers[0] + 4)), numbers)
            self.assertEqual("Brown, John, 1800-1859", parent["creator_personal"])
            self.assertEqual("Des Moines Register", parent["creator_org"])
            self.assertEqual(("Slavery", "Brown, John, 1800-1859"), (parent["Subject (Topic)"], parent["Subject (Person)"]))
            self.assertEqual("2011", parent["date"])
            self.assertEqual("Still Image", parent["type"])
            self.assertEqual("Social Justice at Grinnell", parent["Digital Collection Title"])
            self.assertEqual(("grinnell:10", "http://hdl.handle.net/11084/10"), (parent["identifier"], parent["Item Permalink"]))
            self.assertEqual(("Public Domain", "http://rightsstatements.org/vocab/NoC-US/1.0/"), (parent["rights"], parent["Standardized Rights"]))
            self.assertEqual("", parent["image_thumb"])
            self.assertEqual((parent["objectid"], "image"), (first["parentid"], first["display_template"]))
            self.assertEqual(("Photo 11", "rep11", "grinnell:11"), (first["title"], first["originating_system_id"], first["identifier"]))
            self.assertEqual(("", "image/jpeg"), (first["object_location"], first["format"]))
            self.assertEqual("", first["description"])
            self.assertEqual("Public Domain", first["rights"])
            self.assertEqual(parent["objectid"], second["parentid"])
            self.assertEqual(("", "pdf", "Text"), (single["parentid"], single["display_template"], single["type"]))
            self.assertTrue((tmp / "out" / "objects" / "grinnell_5_OBJ.pdf").exists())

    def test_template_objectids_are_persisted_and_unique_across_batches(self):
        field_map = {"columns": ["objectid", "parentid"], "rules": {
            "objectid": {"from": "gems.objectid", "child": "inherit"},
            "parentid": {"from": "gems.parentid", "child": "inherit"},
        }}
        with tempfile.TemporaryDirectory() as tmpdir:
            group = Path(tmpdir) / "collection-social-justice-1"
            manifests = []
            for run in ("run-1", "run-2"):
                (group / run).mkdir(parents=True)
                files = []
                for number in (1, 2):
                    path = group / run / f"{run}-{number}.jpg"
                    path.write_text("x", encoding="utf-8")
                    files.append({"source": str(path), "filename": path.name})
                manifest = group / run / f"gems_social-justice_{run}.json"
                manifest.write_text(json.dumps({
                    "collection_title": "Social Justice at Grinnell",
                    "records": [{"mms_id": "991", "files": files}, {"mms_id": "992"}],
                }), encoding="utf-8")
                manifests.append(manifest)

            def objectids(manifest: Path) -> list[str]:
                result = process_export(manifest, manifest.parent, field_map=field_map)
                with result.csv_path.open("r", encoding="utf-8", newline="") as handle:
                    return [row["objectid"] for row in csv.DictReader(handle)]

            first = objectids(manifests[0])
            second = objectids(manifests[1])

            self.assertEqual(4, len(first))
            for value in first + second:
                self.assertRegex(value, r"^social-justice-at-grinnell_dg_\d+$")
            self.assertFalse(set(first) & set(second))
            self.assertEqual(first, objectids(manifests[0]))
            saved = json.loads(manifests[0].read_text(encoding="utf-8"))["records"][0]
            self.assertEqual(first[0], saved["objectid"])
            self.assertEqual(first[1:3], list(saved["child_objectids"].values()))

    def test_template_mapping_reuses_downloaded_objects_and_explains_expired_links(self):
        field_map = {"columns": ["objectid"], "rules": {"objectid": {"from": "gems.objectid"}}}
        url = "https://example.org/scan.jpg?Expires=1000&Signature=x"
        records = [{"mms_id": "991", "files": [{"source": url, "filename": "scan.jpg"}]}]
        expired = HTTPError(url, 403, "Forbidden", None, None)
        with tempfile.TemporaryDirectory() as tmpdir, patch("gems.pipeline.urlretrieve", side_effect=expired) as download:
            out = Path(tmpdir) / "out"
            with self.assertRaisesRegex(ValueError, "scan.jpg expired .* Retrieve the records again"):
                process_records(records, out, field_map=field_map)
            self.assertFalse((out / "objects" / "scan.jpg.part").exists())

            (out / "objects" / "scan.jpg").write_text("already here", encoding="utf-8")
            download.reset_mock()
            result = process_records(records, out, field_map=field_map)
            download.assert_not_called()
            self.assertEqual(1, result.file_count)


if __name__ == "__main__":
    unittest.main()
