import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gems.mods import legacy_collection_folder, read_legacy_mods
from gems.pipeline import build_template_row, process_records
from gems.shelf_backfill import apply_plan, build_plan, read_rows, row_values


class ShelfBackfillTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.gems = self.root / "gems"
        self.run = self.gems / "collection" / "run"
        self.run.mkdir(parents=True)
        self.mods = self.root / "mods"
        (self.mods / "collection").mkdir(parents=True)
        self.mod = self.mods / "collection" / "grinnell_7_MODS.xml"
        self.mod.write_text("""<mods xmlns="http://www.loc.gov/mods/v3"><location>
          <shelfLocator>MS 39,  Series 3; Box 2: Commercial</shelfLocator>
          <shelfLocator>MS 39,  Series 3; Box 2: Commercial</shelfLocator>
          <holdingSimple><copyInformation><shelfLocator>Folder 9</shelfLocator>
          </copyInformation></holdingSimple></location></mods>""")
        self.value = "MS 39,  Series 3; Box 2: Commercial; Folder 9"
        self.manifest = self.run / "gems_collection.json"
        self.manifest.write_text(json.dumps({"records": [{
            "objectid": "gems_parent", "mms_id": "991",
            "metadata": {"dc:identifier": "grinnell:7"},
            "files": [], "child_objectids": {},
        }]}))
        self.rows = [
            {"objectid": "dart_parent", "parentid": "", "originating_system_id": "991",
             "original_file_name": "_parent.jpg", "title": "Parent"},
            {"objectid": "dart_child", "parentid": "dart_parent", "originating_system_id": "rep",
             "original_file_name": "child.jpg", "title": "Child"},
            {"objectid": "other", "parentid": "", "originating_system_id": "999",
             "original_file_name": "other.jpg", "title": "Unrelated"},
        ]
        self.csv = self.run / "collection_metadata.csv"
        self.write_csv(self.rows)
        self.normalized = self.run / "normalized_records.json"
        self.normalized.write_text(json.dumps(self.rows))
        self.backups = self.root / "backups"
        self.backups.mkdir()

    def write_csv(self, rows):
        with self.csv.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    def test_mods_and_map_preserve_whole_string_and_inherit(self):
        self.assertEqual(self.value, read_legacy_mods(self.mod)["shelf_locator"])
        mapping = json.loads((Path(__file__).parent.parent / "maps/alma-dc-to-grinnell.json").read_text())
        for child in (False, True):
            row = build_template_row(mapping["columns"], mapping["rules"], {}, {}, {},
                                     lambda: read_legacy_mods(self.mod), child=child)
            self.assertEqual(self.value, row["shelf_locator"])
            row = build_template_row(mapping["columns"], mapping["rules"],
                                     {"shelf_locator": "Cached; exact  text"}, {}, {},
                                     lambda: read_legacy_mods(self.mod), child=child)
            self.assertEqual("Cached; exact  text", row["shelf_locator"])

    def test_migration_directory_with_trailing_marker(self):
        self.assertEqual("phpp-dcl", legacy_collection_folder(
            '{/"directory/": /"smb://storage/exports/phpp-dcl/"}dgi'))
        self.assertEqual("phpp-dcl", legacy_collection_folder(
            '{/"directory/": /"smb://storage/exports/phpp-dcl/", /"title/": /"bad "quotes"/"}'))

    def test_non_template_export_also_reads_original_mods_locator(self):
        records = [{"identifier": "grinnell:7", "metadata": {
            "dc:identifier": "grinnell:7", "dginfo": '{"directory":"smb://storage/collection/"}',
        }}]
        result = process_records(records, self.root / "plain", legacy_mods_dir=self.mods)
        headers, rows = read_rows(result.csv_path)
        self.assertIn("shelf_locator", headers)
        self.assertEqual(self.value, rows[0]["shelf_locator"])

    def test_backfill_changes_only_locator_and_is_idempotent(self):
        originals = {path.resolve(): path.read_bytes() for path in (self.manifest, self.csv, self.normalized)}
        plan = build_plan([self.gems], self.mods, None)
        for path, value in originals.items():
            self.assertEqual(value, path.read_bytes())
        result = apply_plan(plan, self.backups)
        self.assertEqual(3, len(result))
        for entry in result:
            self.assertEqual(originals[Path(entry["path"])], Path(entry["backup"]).read_bytes())
        _, rows = read_rows(self.csv)
        for index, row in enumerate(rows):
            self.assertEqual(self.rows[index], {key: value for key, value in row.items() if key != "shelf_locator"})
            self.assertEqual(self.value if index < 2 else "", row["shelf_locator"])
        self.assertEqual(self.value, json.loads(self.manifest.read_text())["records"][0]["shelf_locator"])
        again = build_plan([self.gems], self.mods, None)
        self.assertEqual([], apply_plan(again, self.backups))

    def test_existing_values_preserved_and_changed_sources_rejected(self):
        rows = [{**row, "shelf_locator": "Editorial" if index == 0 else ""}
                for index, row in enumerate(self.rows)]
        self.write_csv(rows)
        plan = build_plan([self.gems], self.mods, None)
        entry = next(item for item in plan["files"] if item["path"] == str(self.csv.resolve()))
        self.assertEqual([1], entry["conflicts_preserved"])
        self.mod.write_text(self.mod.read_text() + "\n")
        with self.assertRaisesRegex(ValueError, "changed since planning"):
            apply_plan(plan, self.backups)

    def test_missing_mods_reported_and_duplicate_mods_rejected(self):
        self.mod.unlink()
        plan = build_plan([self.gems], self.mods, None)
        self.assertEqual(1, len(plan["missing_mods"]))
        for folder in ("one", "two"):
            (self.mods / folder).mkdir()
            (self.mods / folder / self.mod.name).write_text('<mods xmlns="http://www.loc.gov/mods/v3"/>')
        self.assertEqual(0, build_plan([self.gems], self.mods, None)["summary"]["missing_mods"])
        (self.mods / "two" / self.mod.name).write_text(
            '<mods xmlns="http://www.loc.gov/mods/v3"><location><shelfLocator>Different</shelfLocator></location></mods>')
        with self.assertRaisesRegex(ValueError, "Conflicting MODS"):
            build_plan([self.gems], self.mods, None)

    def test_ambiguous_matches_and_invalid_parent_chains_rejected(self):
        sources = [{"keys": {"mms": ["991"]}, "value": value} for value in ("A", "B")]
        with self.assertRaisesRegex(ValueError, "Ambiguous"):
            row_values(self.rows, sources)
        with self.assertRaisesRegex(ValueError, "Invalid parent"):
            row_values([self.rows[1]], [])


if __name__ == "__main__":
    unittest.main()
