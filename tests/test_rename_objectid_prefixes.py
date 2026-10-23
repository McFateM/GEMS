from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).parents[1] / "scripts" / "rename_objectid_prefixes.py"
spec = importlib.util.spec_from_file_location("rename_prefixes", SCRIPT)
assert spec and spec.loader
rename = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rename)


class RenameObjectidPrefixesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.mapping_file = self.root / "mapping.tsv"
        self.mapping_file.write_text("long_prefix\tshort_prefix\nlong-title\tshort\n")
        self.mapping = rename.load_mapping(self.mapping_file)
        self.run = self.root / "collection-long-title-123" / "run"
        self.run.mkdir(parents=True)
        self.manifest = self.run / "gems_test.json"
        self.payload = {
            "collection_title": "Long Title",
            "records": [{"objectid": "long-title_dg_123", "child_objectids": {"file.jpg": "long-title_dg_124"}}],
        }
        self.manifest.write_text(json.dumps(self.payload))
        self.rows = [
            {"objectid": "long-title_dg_123", "parentid": ""},
            {"objectid": "long-title_dg_124", "parentid": "long-title_dg_123"},
        ]
        (self.run / "normalized_records.json").write_text(json.dumps(self.rows))
        (self.run / "collection_metadata.csv").write_text(
            "objectid,parentid\nlong-title_dg_123,\nlong-title_dg_124,long-title_dg_123\n"
        )
        self.command = self.root / "button-2-commands-test"
        self.command.write_text(
            f"#!/bin/bash\nset -euo pipefail\n/python -m gems --headless --source {self.manifest} --output {self.run}\n"
        )

    def test_apply_backups_relationships_commands_and_idempotence(self):
        changes = rename.plan_changes(self.root, self.mapping)
        self.assertEqual(4, len(changes))
        self.assertIn("long-title_dg_123", self.manifest.read_text())
        backup = rename.apply_changes(self.root, changes, self.mapping_file)
        original = json.loads((backup / self.manifest.relative_to(self.root)).read_text())
        self.assertEqual(self.payload, original)
        payload = json.loads(self.manifest.read_text())
        self.assertEqual("short", payload["objectid_prefix"])
        self.assertEqual("short_dg_124", payload["records"][0]["child_objectids"]["file.jpg"])
        rows = json.loads((self.run / "normalized_records.json").read_text())
        self.assertEqual(rows[0]["objectid"], rows[1]["parentid"])
        self.assertIn("--objectid-prefix short", self.command.read_text())
        self.assertEqual([], rename.plan_changes(self.root, self.mapping))

    def test_excludes_media_historical_data_and_backups(self):
        for relative in [
            "migrated/collection-x/run/gems_old.json",
            ".objectid-prefix-backups/collection-x/run/gems_old.json",
            "collection-long-title-123/run/objects/media.json",
        ]:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("long-title_dg_123")
        changes = rename.plan_changes(self.root, self.mapping)
        self.assertEqual(4, len(changes))

    def test_replaces_whole_ids_only_preserving_suffixes(self):
        text = "long-title_dg_123 other-long-title_dg_123 long-title_dg_123abc long-title"
        self.assertEqual(
            "short_dg_123 other-long-title_dg_123 long-title_dg_123abc long-title",
            rename.replace_ids(text, self.mapping),
        )

    def test_rejects_duplicate_targets_and_chains(self):
        for body in ["one\tx\ntwo\tx\n", "one\ttwo\ntwo\tthree\n"]:
            self.mapping_file.write_text("long_prefix\tshort_prefix\n" + body)
            with self.assertRaises(ValueError):
                rename.load_mapping(self.mapping_file)

    def test_existing_prefix_setting_does_not_hide_old_ids(self):
        self.payload["objectid_prefix"] = "short"
        self.manifest.write_text(json.dumps(self.payload))
        changes = rename.plan_changes(self.root, self.mapping)
        updated = next(new for path, _, new in changes if path == self.manifest)
        self.assertNotIn(b"long-title_dg_", updated)

    def test_replaces_existing_command_prefix_without_changing_source_paths(self):
        with self.command.open("a") as handle:
            handle.write(
                f"/python -m gems --headless --source {self.manifest} --objectid-prefix long-title\n"
            )
        changes = rename.plan_changes(self.root, self.mapping)
        updated = next(new.decode() for path, _, new in changes if path == self.command)
        self.assertEqual(2, updated.count("--objectid-prefix short"))
        self.assertEqual(2, updated.count(str(self.manifest)))

    def test_preflight_change_prevents_any_writes(self):
        changes = rename.plan_changes(self.root, self.mapping)
        self.manifest.write_text("changed concurrently")
        before = self.command.read_bytes()
        with self.assertRaisesRegex(ValueError, "nothing applied"):
            rename.apply_changes(self.root, changes, self.mapping_file)
        self.assertEqual(before, self.command.read_bytes())
        self.assertEqual("changed concurrently", self.manifest.read_text())

    def test_detects_id_collisions_before_writing(self):
        self.payload["records"].append({"objectid": "short_dg_123"})
        self.manifest.write_text(json.dumps(self.payload))
        with self.assertRaisesRegex(ValueError, "Duplicate objectids"):
            rename.plan_changes(self.root, self.mapping)

    def test_refuses_symlink_and_unmapped_command(self):
        self.manifest.unlink()
        other = self.root / "outside.json"
        other.write_text(json.dumps(self.payload))
        self.manifest.symlink_to(other)
        with self.assertRaisesRegex(ValueError, "symlink"):
            rename.plan_changes(self.root, self.mapping)
        self.manifest.unlink()
        self.manifest.write_text(json.dumps(self.payload))
        self.command.write_text("/python -m gems --headless --source /elsewhere.json\n")
        with self.assertRaisesRegex(ValueError, "not an active"):
            rename.plan_changes(self.root, self.mapping)


if __name__ == "__main__":
    unittest.main()
