from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which("bash") and shutil.which("rsync"), "Bash and rsync are required")
class OffloadMigratedTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.volume = self.root / "DGIngest"
        self.volume.mkdir()
        self.source = self.root / "source"
        self.source.mkdir()
        self.relative = Path("DGIngest-DATA/collection/run/objects/.complete")
        self.complete = self.source / self.relative
        self.complete.mkdir(parents=True)
        self.destination = self.volume / "_GEMS_Migration" / "Migrated"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        mount = self.bin / "mount"
        mount.write_text('#!/bin/sh\nprintf "%s\\n" "$TEST_MOUNT"\n')
        mount.chmod(0o755)
        original = Path(__file__).parents[1] / "scripts" / "offload_migrated.sh"
        self.script = self.root / original.name
        self.script.write_text(
            original.read_text()
            .replace("mount_point=/Volumes/DGIngest", f"mount_point='{self.volume}'")
            .replace("source=sysadmin@dg-landing:/data/gems/data/migrated/", f"source='{self.source}/'")
        )
        self.environment = {
            **os.environ,
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "TEST_MOUNT": f"//user@storage/DGIngest on {self.volume} (smbfs, mounted by user)",
        }

    def run_script(self, *args):
        return subprocess.run(
            ["bash", str(self.script), *args], env=self.environment,
            capture_output=True, text=True, timeout=30,
        )

    def test_default_preview_does_not_transfer_or_remove_source(self):
        asset = self.complete / "asset.txt"
        asset.write_text("keep me")
        result = self.run_script()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(asset.exists())
        self.assertFalse((self.destination / self.relative / asset.name).exists())
        self.assertIn("PREVIEW ONLY", result.stdout)

    def test_move_preserves_tree_hidden_files_and_destination_only_files(self):
        folder = self.complete / "collection with spaces"
        folder.mkdir()
        (folder / "asset.txt").write_text("content")
        (self.complete / ".hidden").write_text("hidden")
        untouched = [
            self.source / "manifest.json",
            self.complete.parent / "active.pdf",
            self.complete.parent / "complete" / "not-hidden.pdf",
            self.source / "unrelated" / ".complete" / "not-an-object.pdf",
        ]
        for path in untouched:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("stay on server")
        self.destination.mkdir(parents=True)
        (self.destination / "older.txt").write_text("older")
        result = self.run_script("--move")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("content", (self.destination / self.relative / folder.name / "asset.txt").read_text())
        self.assertEqual("hidden", (self.destination / self.relative / ".hidden").read_text())
        self.assertTrue((self.destination / "older.txt").exists())
        self.assertFalse((folder / "asset.txt").exists())
        self.assertFalse((self.complete / ".hidden").exists())
        for path in untouched:
            self.assertTrue(path.exists())
            self.assertFalse((self.destination / path.relative_to(self.source)).exists())
        self.assertTrue(folder.exists())
        repeated = self.run_script("--move")
        self.assertEqual(0, repeated.returncode, repeated.stderr)

    def test_checksum_detects_same_size_same_timestamp_conflict_and_keeps_backup(self):
        target = self.destination / self.relative
        target.mkdir(parents=True)
        source = self.complete / "asset.txt"
        destination = target / source.name
        source.write_text("new content")
        destination.write_text("old content")
        for path in (source, destination):
            os.utime(path, (1700000000, 1700000000))
        result = self.run_script("--move")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse(source.exists())
        self.assertEqual("new content", destination.read_text())
        backups = list((self.destination / ".replaced").glob("*/**/asset.txt"))
        self.assertEqual(1, len(backups))
        self.assertEqual("old content", backups[0].read_text())

    def test_identical_existing_file_is_removed_from_source(self):
        target = self.destination / self.relative
        target.mkdir(parents=True)
        for parent in (self.complete, target):
            (parent / "asset.txt").write_text("same")
        result = self.run_script("--move")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse((self.complete / "asset.txt").exists())
        self.assertEqual("same", (target / "asset.txt").read_text())

    def test_missing_mount_refuses_to_create_destination_or_remove_files(self):
        self.environment["TEST_MOUNT"] = ""
        (self.source / "asset.txt").write_text("keep")
        result = self.run_script("--move")
        self.assertEqual(2, result.returncode)
        self.assertIn("Mount the DGIngest SMB share", result.stderr)
        self.assertFalse(self.destination.exists())
        self.assertTrue((self.source / "asset.txt").exists())

    def test_destination_symlink_outside_volume_is_rejected(self):
        outside = self.root / "outside"
        outside.mkdir()
        (self.volume / "_GEMS_Migration").symlink_to(outside, target_is_directory=True)
        result = self.run_script("--move")
        self.assertEqual(2, result.returncode)
        self.assertIn("outside the network volume", result.stderr)

    def test_rsync_failure_preserves_status_and_does_not_report_success(self):
        rsync = self.bin / "rsync"
        rsync.write_text("#!/bin/sh\nexit 23\n")
        rsync.chmod(0o755)
        result = self.run_script("--move")
        self.assertEqual(23, result.returncode)
        self.assertIn("Transfer failed", result.stderr)
        self.assertNotIn("Move completed", result.stdout)

    def test_invalid_arguments_and_help(self):
        for args in (("--delete",), ("--move", "extra")):
            with self.subTest(args=args):
                result = self.run_script(*args)
                self.assertEqual(2, result.returncode)
                self.assertFalse(self.destination.exists())
        result = self.run_script("--help")
        self.assertEqual(0, result.returncode)
        self.assertIn("Usage:", result.stdout)
