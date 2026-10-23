from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from gems.pipeline import DownloadError, process_export, process_records


class UnmappedMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.asset = self.root / "photo.jpg"
        self.asset.write_bytes(b"original")
        self.output = self.root / "output"

    def rows(self, result):
        with result.csv_path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
            self.assertEqual(rows, json.loads(result.json_path.read_text(encoding="utf-8")))
            return reader.fieldnames, rows

    def csv_source(self):
        source = self.root / "omeka.csv"
        fields = [
            "o:id", "o:media[file]", "dcterms:title", "dcterms:alternative",
            "dcterms:coverage", "dcterms:spatial", "wmi:instrumentCategory",
            "custom:unfamiliar Name", "custom:empty",
        ]
        with source.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerow({
                "o:id": "1", "o:media[file]": self.asset.as_uri(),
                "dcterms:title": "Instrument", "dcterms:alternative": 'Other, "name"\nLine two',
                "dcterms:coverage": "Indonesia", "dcterms:spatial": "Asia",
                "wmi:instrumentCategory": "chordophone",
                "custom:unfamiliar Name": "First | Second",
            })
            writer.writerow({
                "o:id": "2", "o:media[file]": self.asset.as_uri(),
                "dcterms:title": "Another", "custom:unfamiliar Name": "Later",
            })
        return source

    def test_omeka_csv_preserves_unmapped_fields_and_unused_default_alias(self):
        source = self.csv_source()
        before = source.read_bytes()
        result = process_export(source, self.output, source_type="omeka")
        headers, rows = self.rows(result)
        row = rows[0]
        self.assertEqual("Instrument", row["title"])
        self.assertEqual("Indonesia", row["coverage"])
        self.assertEqual("Asia", row["_dcterms:spatial"])
        self.assertEqual('Other, "name"\nLine two', row["_dcterms:alternative"])
        self.assertEqual("chordophone", row["_wmi:instrumentCategory"])
        self.assertEqual("First; Second", row["_custom:unfamiliar Name"])
        self.assertIn("_custom:empty", headers)
        self.assertNotIn("_dcterms:title", headers)
        self.assertNotIn("_o:id", headers)
        self.assertNotIn("_instrumentCategory", headers)
        self.assertEqual(before, source.read_bytes())
        self.assertEqual(b"original", self.asset.read_bytes())

    def test_omeka_batches_use_all_records_for_stable_headers(self):
        source = self.csv_source()
        first = process_export(source, self.output, source_type="omeka", start=2, limit=1)
        headers, rows = self.rows(first)
        self.assertEqual(1, len(rows))
        second = process_export(source, self.output, source_type="omeka", start=1, limit=1)
        second_headers, rows = self.rows(second)
        self.assertEqual(headers, second_headers)
        self.assertEqual(2, len(rows))
        self.assertEqual("chordophone", rows[0]["_wmi:instrumentCategory"])
        self.assertEqual("Later", rows[1]["_custom:unfamiliar Name"])

    def test_explicit_template_mapping_does_not_duplicate_mapped_source(self):
        source = self.csv_source()
        template = {
            "columns": ["title", "continent", "category"],
            "rules": {
                "title": {"from": "metadata.dcterms:title"},
                "continent": {"from": "metadata.dcterms:spatial"},
                "category": {"from": "metadata.wmi:instrumentCategory"},
            },
        }
        before = json.dumps(template)
        result = process_export(source, self.output, source_type="omeka", field_map=template)
        headers, rows = self.rows(result)
        self.assertEqual(["title", "continent", "category", "original_file_name"], headers[:4])
        self.assertEqual("Asia", rows[0]["continent"])
        self.assertNotIn("_dcterms:spatial", headers)
        self.assertNotIn("_wmi:instrumentCategory", headers)
        self.assertIn("_dcterms:alternative", headers)
        self.assertEqual(before, json.dumps(template))

    def test_simple_omeka_map_preserves_fields_not_chosen_by_default_aliases(self):
        result = process_export(
            self.csv_source(), self.output, source_type="omeka",
            field_map={"description": "dcterms:alternative"},
        )
        headers, rows = self.rows(result)
        self.assertEqual('Other, "name"\nLine two', rows[0]["description"])
        self.assertNotIn("_dcterms:alternative", headers)
        self.assertIn("_dcterms:spatial", headers)

    def test_omeka_s_json_preserves_any_vocabulary_and_namespace_collisions(self):
        source = self.root / "omeka.json"
        source.write_text(json.dumps([{
            "@type": "o:Item", "o:id": 1,
            "dcterms:title": [{"@value": "Title"}],
            "dcterms:alternative": [{"@value": "Alternative"}],
            "dc:alternative": [{"@value": "Different alternative"}],
            "wmi:instrumentCategory": [{"@value": "chordophone"}],
            "unknown:property": [{"@id": "https://example.org/value"}],
            "unknown:structured": {"nested": ["one", "two"]},
            "o:media": [{"o:original_url": self.asset.as_uri()}],
        }]), encoding="utf-8")
        headers, rows = self.rows(process_export(source, self.output, source_type="omeka"))
        self.assertEqual("Alternative", rows[0]["_dcterms:alternative"])
        self.assertEqual("Different alternative", rows[0]["_dc:alternative"])
        self.assertEqual("chordophone", rows[0]["_wmi:instrumentCategory"])
        self.assertEqual("https://example.org/value", rows[0]["_unknown:property"])
        self.assertEqual({"nested": ["one", "two"]}, json.loads(rows[0]["_unknown:structured"]))
        self.assertNotIn("_dcterms:title", headers)

    def test_classic_custom_element_set_is_not_discarded(self):
        source = self.root / "classic.json"
        source.write_text(json.dumps([{
            "id": 1, "element_texts": [
                {"element_set": {"name": "Dublin Core"}, "element": {"name": "Title"}, "text": "Photo"},
                {"element_set": {"name": "Local"}, "element": {"name": "Curator Note"}, "text": "Keep this"},
            ],
            "files_list": [{"file_urls": {"original": self.asset.as_uri()}}],
        }]), encoding="utf-8")
        headers, rows = self.rows(process_export(source, self.output, source_type="omeka"))
        self.assertEqual("Photo", rows[0]["title"])
        self.assertEqual("Keep this", rows[0]["_Local:Curator Note"])
        self.assertNotIn("_dc:title", headers)

    def test_generic_and_template_exports_preserve_original_names(self):
        for template in (None, {
            "columns": ["objectid", "title", "original_file_name"],
            "rules": {
                "objectid": {"from": "gems.objectid"},
                "title": {"from": "metadata.title"},
                "original_file_name": {"from": "gems.filename"},
            },
        }):
            with self.subTest(template=bool(template)):
                records = [{
                    "metadata": {"title": "Photo", "dcterms:alternative": "Alt", "custom:List": ["One", "Two"]},
                }]
                result = process_records(records, self.output / str(bool(template)), field_map=template)
                headers, rows = self.rows(result)
                self.assertEqual("Alt", rows[0]["_dcterms:alternative"])
                self.assertEqual("One; Two", rows[0]["_custom:List"])
                self.assertNotIn("_title", headers)

    def test_collision_fails_instead_of_overwriting_metadata(self):
        template = {
            "columns": ["_custom:note"],
            "rules": {"_custom:note": {"value": "Mapped value"}},
        }
        with self.assertRaisesRegex(ValueError, "conflicts with a mapped output column"):
            process_records([{"metadata": {"custom:note": "Source value"}}], self.output, field_map=template)
        self.assertFalse(self.output.exists())

    def test_template_batch_schema_mismatch_does_not_discard_previous_rows(self):
        self.output.mkdir()
        existing = self.output / "collection_metadata.csv"
        existing.write_text("objectid,title\ndg_1,Previously exported\n", encoding="utf-8")
        before = existing.read_bytes()
        template = {
            "columns": ["objectid", "title"],
            "rules": {
                "objectid": {"from": "gems.objectid"},
                "title": {"from": "metadata.title"},
            },
        }
        records = [
            {"objectid": "dg_1", "metadata": {"title": "Previously exported", "custom:note": "Keep"}},
            {"objectid": "dg_2", "metadata": {"title": "Next"}},
        ]
        with self.assertRaisesRegex(ValueError, "different columns"):
            process_records(records, self.output, field_map=template, start=2)
        self.assertEqual(before, existing.read_bytes())

    def test_flat_csv_preserves_underscores_and_normalization_collisions(self):
        source = self.root / "generic.csv"
        source.write_text(
            'title,custom:Note,custom Note,_existing\nPhoto,First,Second,Third\n',
            encoding="utf-8",
        )
        _, rows = self.rows(process_export(source, self.output))
        self.assertEqual("First", rows[0]["_custom:Note"])
        self.assertEqual("Second", rows[0]["_custom Note"])
        self.assertEqual("Third", rows[0]["__existing"])

    def test_failed_downloads_still_excluded_with_passthrough_columns(self):
        source = self.csv_source()

        def download(url, destination):
            if not getattr(download, "attempted", False):
                download.attempted = True
                with HTTPError(url, 403, "Forbidden", {}, None) as error:
                    raise DownloadError("Forbidden") from error
            Path(destination).write_bytes(b"downloaded")

        with patch("gems.pipeline.fetch_object", side_effect=download):
            result = process_export(source, self.output, source_type="omeka", skip_download_errors=True)
        _, rows = self.rows(result)
        self.assertEqual(1, len(rows))
        self.assertEqual("Another", rows[0]["title"])
        self.assertEqual("Later", rows[0]["_custom:unfamiliar Name"])
        self.assertEqual(1, len(result.failed_downloads))


if __name__ == "__main__":
    unittest.main()
