from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gems.metadata_refresh import apply_refresh, plan_refresh, read_csv, reconcile_compound_parents
from gems.pipeline import map_to_template, representation_items


class MetadataRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = self.root / "manifest.json"
        self.baseline = self.root / "baseline.csv"
        self.core = self.root / "core.csv"
        self.mapping = self.root / "map.json"
        self.records = [{
            "mms_id": "991", "objectid": "gems_1",
            "metadata": {"dc:title": "New title", "dc:subject": "New keyword"},
            "files": [{"filename": "scan.jpg", "source": "https://example.org/expired.jpg"}],
        }]
        self.manifest.write_text(json.dumps({"records": self.records}), encoding="utf-8")
        self.columns = ["objectid", "parentid", "original_file_name", "title", "genre",
                        "subject_topic", "object_location", "custom"]
        self.old = {
            "objectid": "gems_1", "parentid": "", "original_file_name": "scan.jpg",
            "title": "Old title", "genre": "Photo", "subject_topic": "Old topic",
            "object_location": "", "custom": "",
        }
        self.published = {**self.old, "objectid": "published_1",
                          "object_location": "https://azure.example/published_1.jpg",
                          "custom": "Editorial enrichment"}
        self.write_csv(self.baseline, [self.old])
        self.write_csv(self.core, [self.published])
        self.mapping.write_text(json.dumps({
            "columns": self.columns + ["keywords"],
            "rules": {
                "objectid": {"from": "gems.objectid", "child": "inherit"},
                "parentid": {"from": "gems.parentid", "child": "inherit"},
                "original_file_name": {"from": "gems.filename", "child": "inherit"},
                "title": {"from": "metadata.dc:title"},
                "genre": {"fallback": {"from": "mods.genre"}},
                "subject_topic": {"from": "metadata.dcterms:subject"},
                "keywords": {"from": "metadata.dc:subject"},
                "object_location": {"value": "must not replace published URL"},
            },
        }), encoding="utf-8")

    def write_csv(self, path, rows, columns=None):
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns or self.columns)
            writer.writeheader()
            writer.writerows(rows)

    def plan(self, **kwargs):
        return plan_refresh(self.manifest, self.baseline, self.core, self.mapping, **kwargs)

    def resolve(self, report, decision="keep"):
        for change in report["changes"]:
            if change["decision"] is None:
                change["decision"] = decision

    def test_three_way_refresh_preserves_identity_urls_curations_and_source_files(self):
        originals = {path: path.read_bytes() for path in (self.manifest, self.baseline, self.core)}
        with patch("gems.pipeline.fetch_object") as fetch:
            report = self.plan()
        fetch.assert_not_called()
        self.assertFalse((self.root / "objects").exists())
        for path, content in originals.items():
            self.assertEqual(content, path.read_bytes())
        self.assertEqual(["keywords"], report["added_columns"])
        changes = {change["field"]: change for change in report["changes"]}
        self.assertEqual("safe", changes["title"]["status"])
        self.assertEqual("safe", changes["keywords"]["status"])
        self.assertEqual("", changes["subject_topic"]["proposed"])
        self.assertEqual("legacy_mods_unavailable", changes["genre"]["reason"])
        self.resolve(report)
        backup = apply_refresh(report)
        self.assertIsNotNone(backup)
        self.assertEqual(originals[self.core], backup.read_bytes())
        headers, rows = read_csv(self.core)
        expected = {**self.published, "title": "New title", "subject_topic": "", "keywords": "New keyword"}
        self.assertEqual([expected], rows)
        self.assertEqual(self.columns + ["keywords"], headers)
        self.assertIn(b"\r\n", self.core.read_bytes())
        self.assertEqual(originals[self.manifest], self.manifest.read_bytes())
        self.assertEqual(originals[self.baseline], self.baseline.read_bytes())
        second = self.plan()
        self.resolve(second)
        self.assertIsNone(apply_refresh(second))

    def test_published_edit_is_conflict_and_explicit_acceptance_works(self):
        self.published["title"] = "Curated title"
        self.write_csv(self.core, [self.published])
        report = self.plan()
        title = next(change for change in report["changes"] if change["field"] == "title")
        self.assertEqual("conflict", title["status"])
        with self.assertRaisesRegex(ValueError, "Resolve the conflict"):
            apply_refresh(report)
        self.resolve(report)
        title["decision"] = "apply"
        apply_refresh(report)
        self.assertEqual("New title", read_csv(self.core)[1][0]["title"])

    def test_stale_inputs_are_rejected(self):
        for path in (self.manifest, self.baseline, self.mapping, self.core):
            with self.subTest(path=path):
                report = self.plan()
                self.resolve(report)
                original = path.read_bytes()
                path.write_bytes(original + b"\n")
                with self.assertRaisesRegex(ValueError, "changed since planning"):
                    apply_refresh(report)
                path.write_bytes(original)

    def test_cli_keep_conflicts_records_decisions_and_backs_up_beside_report(self):
        report = self.plan()
        report_dir = self.root / "reviews"
        report_dir.mkdir()
        path = report_dir / "review.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        command = [sys.executable, "-m", "gems.metadata_refresh", "apply", str(path)]
        rejected = subprocess.run(command, capture_output=True, text=True)
        self.assertNotEqual(0, rejected.returncode)
        self.assertIn("Resolve the conflict", rejected.stderr)
        applied = subprocess.run(command + ["--keep-conflicts"], capture_output=True, text=True)
        self.assertEqual(0, applied.returncode, applied.stderr)
        self.assertEqual(1, len(list(report_dir.glob("core.csv.backup_*"))))
        self.assertFalse(list(self.root.glob("core.csv.backup_*")))
        reviewed = json.loads(path.read_text())
        self.assertTrue(all(change["decision"] in {"keep", "apply"} for change in reviewed["changes"]))
        self.assertEqual("Photo", read_csv(self.core)[1][0]["genre"])

    def test_protected_changes_and_columns_are_rejected(self):
        report = self.plan()
        self.resolve(report)
        report["changes"][0]["field"] = "objectid"
        with self.assertRaisesRegex(ValueError, "Invalid/duplicate field"):
            apply_refresh(report)
        report = self.plan()
        self.resolve(report)
        report["added_columns"].append("image_thumb")
        with self.assertRaisesRegex(ValueError, "Invalid added columns"):
            apply_refresh(report)

    def test_unmatched_full_collection_blocks_apply_and_partial_keeps_extra_rows(self):
        extra = {**self.published, "objectid": "published_2", "original_file_name": "extra.jpg"}
        self.write_csv(self.core, [extra, self.published])
        report = self.plan()
        self.resolve(report)
        with self.assertRaisesRegex(ValueError, "Unmatched rows"):
            apply_refresh(report)
        report = self.plan(allow_partial=True)
        self.resolve(report)
        apply_refresh(report)
        rows = read_csv(self.core)[1]
        self.assertEqual([extra["objectid"], self.published["objectid"]], [row["objectid"] for row in rows])
        self.assertEqual({**extra, "keywords": ""}, rows[0])

    def test_partial_does_not_allow_unmatched_source_records(self):
        self.write_csv(self.core, [{**self.published, "original_file_name": "wrong.jpg"}])
        report = self.plan(allow_partial=True)
        self.resolve(report)
        with self.assertRaisesRegex(ValueError, "Unmatched rows"):
            apply_refresh(report)

    def test_core_row_limit_preserves_later_rows_and_rejects_out_of_scope_changes(self):
        extra = {**self.records[0], "objectid": "gems_2",
                 "files": [{"filename": "extra.jpg", "source": "https://example.org/extra.jpg"}]}
        self.manifest.write_text(json.dumps({"records": [*self.records, extra]}), encoding="utf-8")
        extra_old = {**self.old, "objectid": "gems_2", "original_file_name": "extra.jpg"}
        extra_core = {**self.published, "objectid": "published_2", "original_file_name": "extra.jpg"}
        self.write_csv(self.baseline, [self.old, extra_old])
        self.write_csv(self.core, [self.published, extra_core])
        for limit in (0, -1, 3):
            with self.subTest(limit=limit), self.assertRaisesRegex(ValueError, "Core row limit"):
                self.plan(core_row_limit=limit)
        report = self.plan(core_row_limit=1)
        self.resolve(report)
        self.assertTrue(all(c["original_file_name"] == "scan.jpg" for c in report["changes"]))
        invalid = json.loads(json.dumps(report))
        invalid["changes"][0].update(original_file_name="extra.jpg", objectid="published_2")
        with self.assertRaisesRegex(ValueError, "outside the selected"):
            apply_refresh(invalid)
        apply_refresh(report)
        rows = read_csv(self.core)[1]
        self.assertEqual("New title", rows[0]["title"])
        self.assertEqual({**extra_core, "keywords": ""}, rows[1])

    def test_explicit_exclusion_only_allows_unpublished_source_rows(self):
        extra = {**self.records[0], "objectid": "gems_2",
                 "files": [{"filename": "extra.jpg", "source": "https://example.org/extra.jpg"}]}
        self.manifest.write_text(json.dumps({"records": [*self.records, extra]}), encoding="utf-8")
        self.write_csv(self.baseline, [self.old, {**self.old, "objectid": "gems_2",
                                                 "original_file_name": "extra.jpg"}])
        report = self.plan(exclude_source=("extra.jpg",))
        self.assertEqual("extra.jpg", report["excluded_source_rows"][0]["original_file_name"])
        self.assertFalse(any(report["unmatched"].values()))
        self.resolve(report)
        apply_refresh(report)
        self.assertEqual(1, len(read_csv(self.core)[1]))
        for name in ("scan.jpg", "nonexistent.jpg"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "absent from core"):
                self.plan(exclude_source=(name,))

    def test_compound_parent_reconciliation_requires_unique_mms_and_exact_families(self):
        old = {
            "_source.jpg": {"objectid": "gems_parent", "parentid": "",
                            "display_template": "compound_object", "originating_system_id": "991"},
            "child.jpg": {"objectid": "gems_child", "parentid": "gems_parent"},
        }
        new = {key: dict(row) for key, row in old.items()}
        core = {
            "_dart.jpg": {**old["_source.jpg"], "objectid": "dart_parent"},
            "child.jpg": {"objectid": "dart_child", "parentid": "dart_parent"},
        }
        for scenario in ("missing_child", "extra_child", "ambiguous_mms", "different_mms"):
            changed = {key: dict(row) for key, row in core.items()}
            if scenario == "missing_child":
                del changed["child.jpg"]
            elif scenario == "extra_child":
                changed["extra.jpg"] = {"objectid": "extra", "parentid": "dart_parent"}
            elif scenario == "ambiguous_mms":
                changed["_other.jpg"] = {**changed["_dart.jpg"], "objectid": "other"}
            else:
                changed["_dart.jpg"]["originating_system_id"] = "992"
            with self.subTest(scenario=scenario):
                self.assertEqual([], reconcile_compound_parents(old, new, changed))
                self.assertIn("_source.jpg", new)
        result = reconcile_compound_parents(old, new, core)
        self.assertEqual([{"source_original_file_name": "_source.jpg",
                          "core_original_file_name": "_dart.jpg", "originating_system_id": "991"}], result)
        self.assertIn("_dart.jpg", new)
        self.assertIn("_dart.jpg", old)
        self.assertNotIn("_source.jpg", new)
        self.assertEqual("dart_parent", core["_dart.jpg"]["objectid"])

    def test_parent_reconciliation_allows_verified_standalone_source_asset(self):
        source = {
            "_source.jpg": {"objectid": "source", "parentid": "", "display_template": "compound_object",
                            "originating_system_id": "991"},
            "child.jpg": {"objectid": "child", "parentid": "source"},
            "standalone.jpg": {"objectid": "standalone", "parentid": "source"},
        }
        core = {
            "_dart.jpg": {**source["_source.jpg"], "objectid": "dart"},
            "child.jpg": {"objectid": "dart_child", "parentid": "dart"},
            "standalone.jpg": {"objectid": "dart_single", "parentid": "",
                               "originating_system_id": "991", "display_template": "image"},
        }
        for mms in ("wrong", "991"):
            core["standalone.jpg"]["originating_system_id"] = mms
            old = {key: dict(value) for key, value in source.items()}
            new = {key: dict(value) for key, value in source.items()}
            result = reconcile_compound_parents(old, new, core)
            self.assertEqual(0 if mms == "wrong" else 1, len(result))
        self.assertEqual("", core["standalone.jpg"]["parentid"])

    def test_duplicate_filenames_ids_and_missing_parents_fail(self):
        self.write_csv(self.baseline, [self.old, self.old])
        with self.assertRaisesRegex(ValueError, "duplicate original_file_name"):
            self.plan()
        self.write_csv(self.baseline, [self.old])
        self.write_csv(self.core, [self.published, {**self.published, "original_file_name": "other.jpg"}])
        with self.assertRaisesRegex(ValueError, "unique objectids"):
            self.plan()
        self.write_csv(self.core, [{**self.published, "parentid": "missing"}])
        with self.assertRaisesRegex(ValueError, "Missing core parent"):
            self.plan()

    def test_old_headers_normalize_and_ambiguous_headers_fail(self):
        alias = {("Subject (Topic)" if key == "subject_topic" else key): value for key, value in self.old.items()}
        columns = list(alias)
        self.write_csv(self.baseline, [alias], columns)
        self.assertEqual([], self.plan()["unmatched"]["source_without_baseline"])
        self.write_csv(self.baseline, [{**alias, "subject_topic": ""}], columns + ["subject_topic"])
        with self.assertRaisesRegex(ValueError, "ambiguous CSV headers"):
            self.plan()

    def test_missing_persisted_ids_fail_without_writing_manifest(self):
        self.records[0].pop("objectid")
        content = json.dumps({"records": self.records})
        self.manifest.write_text(content, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "persisted parent and child IDs"):
            self.plan()
        self.assertEqual(content, self.manifest.read_text())

    def test_metadata_only_compound_mapping_uses_persisted_children(self):
        record = {
            "objectid": "gems_parent", "metadata": {"dc:title": "Compound"},
            "files": [{"filename": name, "source": f"https://example.org/{name}"}
                      for name in ("page-01.jpg", "page-02.jpg")],
        }
        record["child_objectids"] = {
            item["filename"]: f"gems_child{index}"
            for index, item in enumerate(representation_items(record), start=1)
        }
        mapping = json.loads(self.mapping.read_text())
        with patch("gems.pipeline.fetch_object") as fetch:
            rows, count = map_to_template([record], mapping, self.root / "no-assets", None, metadata_only=True)
        fetch.assert_not_called()
        self.assertEqual(0, count)
        self.assertFalse((self.root / "no-assets").exists())
        self.assertEqual(["gems_parent", "gems_child1", "gems_child2"], [row["objectid"] for row in rows])
        self.assertEqual(["", "gems_parent", "gems_parent"], [row["parentid"] for row in rows])

    def test_transcripts_are_explicitly_rejected_without_io(self):
        record = {**self.records[0], "files": [
            {"filename": "sound.mp3", "source": "https://example.org/sound.mp3"},
            {"filename": "sound.vtt", "source": "https://example.org/sound.vtt"},
        ]}
        with self.assertRaisesRegex(ValueError, "does not support transcript"):
            map_to_template([record], json.loads(self.mapping.read_text()), self.root / "no-assets",
                            None, metadata_only=True)
        self.assertFalse((self.root / "no-assets").exists())


if __name__ == "__main__":
    unittest.main()
