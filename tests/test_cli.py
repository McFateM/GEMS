from __future__ import annotations

import io
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from requests import ConnectionError

from gems.__main__ import cli


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.client = MagicMock()
        self.client.skipped_errors = []
        self.client.skipped_positions = []

        def fetch(ids, *, on_progress):
            records = []
            for value in ids:
                records.append({"identifier": value, "metadata": {"title": value}})
                on_progress(len(records), len(ids))
            return records

        self.client.fetch_records.side_effect = fetch
        self.stdout, self.stderr = io.StringIO(), io.StringIO()

    def run_cli(self, *args):
        with (
            patch("sys.argv", ["gems", *args]),
            patch("gems.__main__.load_environment"),
            patch("gems.__main__.AlmaClient", return_value=self.client),
            redirect_stdout(self.stdout), redirect_stderr(self.stderr),
        ):
            return cli()

    def retrieve(self, *args):
        self.assertEqual(0, self.run_cli("--headless", "--retrieve", "--output", str(self.root), *args))
        manifests = list(self.root.glob("*/*/gems_*.json"))
        self.assertEqual(1, len(manifests))
        command = shlex.split(self.stdout.getvalue().splitlines()[-1])
        self.assertEqual([sys.executable, "-m", "gems", "--headless"], command[:4])
        self.assertEqual(str(manifests[0].resolve()), command[command.index("--source") + 1])
        self.assertEqual(str(manifests[0].parent.resolve()), command[command.index("--output") + 1])
        self.assertNotIn("--retrieve", command)
        self.assertNotIn("--limit", command)
        return manifests[0], json.loads(manifests[0].read_text())

    def test_set_retrieves_all_unique_members_and_saves_manifest_only(self):
        self.client.fetch_set_title.return_value = "Test Set"
        self.client.fetch_set_members.return_value = ["991", "992", "991"]
        path, payload = self.retrieve("--set-id", "123")
        self.client.fetch_set_members.assert_called_once_with("123")
        self.assertEqual(["991", "992"], self.client.fetch_records.call_args.args[0])
        self.assertEqual("123", payload["alma_set_id"])
        self.assertEqual({"available_records": 2}, payload["retrieval"])
        self.assertEqual(2, len(payload["records"]))
        self.assertEqual("set-test-set-123", path.parent.parent.name)
        self.assertIsNotNone(datetime.fromisoformat(payload["created_at"]).utcoffset())
        self.assertTrue((path.parent / "gems.log").is_file())
        self.assertFalse((path.parent / "collection_metadata.csv").exists())
        self.assertFalse((path.parent / "objects").exists())
        self.assertIn(str(path), self.stdout.getvalue())
        self.assertIn("100% (2/2)", self.stderr.getvalue())

    def test_collection_saves_pid_and_reports_skipped_entries(self):
        self.client.resolve_collection.return_value = ("456", "Social Justice")
        self.client.fetch_collection_bibs.return_value = ["991"]
        self.client.skipped_errors = ["Entry 3 unavailable"]
        self.client.skipped_positions = [3]
        path, payload = self.retrieve("--collection-title", "Social Justice")
        self.client.resolve_collection.assert_called_once_with("Social Justice")
        self.client.fetch_collection_bibs.assert_called_once_with("456")
        self.assertEqual("456", payload["alma_collection_pid"])
        self.assertEqual("collection-social-justice-456", path.parent.parent.name)
        self.assertIn("Entry 3 unavailable", self.stderr.getvalue())
        self.assertIn("skipped collection positions: [3]", self.stderr.getvalue())
        self.assertIn("Entry 3 unavailable", (path.parent / "gems.log").read_text())

    def test_collection_id_bypasses_all_title_searches_and_preserves_label(self):
        title = "Scarlet & Black (S&B) Archives"
        self.client.fetch_collection_bibs.return_value = ["991", "992", "991"]
        path, payload = self.retrieve("--collection-id", "81310703090004641", "--collection-title", title)
        self.client.resolve_collection.assert_not_called()
        self.client.fetch_set_members.assert_not_called()
        self.client.fetch_collection_bibs.assert_called_once_with("81310703090004641")
        self.assertEqual(["991", "992"], self.client.fetch_records.call_args.args[0])
        self.assertEqual("81310703090004641", payload["alma_collection_pid"])
        self.assertEqual(title, payload["collection_title"])
        self.assertEqual("collection-scarlet-black-s-b-archives-81310703090004641", path.parent.parent.name)
        command = shlex.split(self.stdout.getvalue().splitlines()[-1])
        self.assertEqual("scarlet-black-s-b-archives", command[command.index("--objectid-prefix") + 1])

    def test_invalid_collection_id_arguments_fail_before_contacting_alma(self):
        cases = [
            ("--retrieve", "--collection-id", "abc", "--collection-title", "Title"),
            ("--retrieve", "--collection-id", "123"),
            ("--retrieve", "--collection-id", "123", "--collection-title", " "),
            ("--retrieve", "--collection-id", "", "--collection-title", "Title"),
            ("--retrieve", "--collection-id", "123", "--set-id", "456"),
            ("--retrieve", "--collection-id", "123", "--mms-ids", "991"),
            ("--collection-id", "123", "--collection-title", "Title"),
        ]
        for args in cases:
            with self.subTest(args=args), self.assertRaises(SystemExit) as error:
                self.run_cli("--headless", "--output", str(self.root), *args)
            self.assertEqual(2, error.exception.code)
        self.client.fetch_collection_bibs.assert_not_called()
        self.client.resolve_collection.assert_not_called()

    def test_explicit_numeric_collection_title_is_not_treated_as_a_set(self):
        self.client.resolve_collection.return_value = ("456", "2026")
        self.client.fetch_collection_bibs.return_value = ["991"]
        self.retrieve("--collection-title", "2026")
        self.client.resolve_collection.assert_called_once_with("2026")
        self.client.fetch_set_members.assert_not_called()

    def test_followup_prefix_uses_full_resolved_collection_title(self):
        cases = [
            ("Social Justice at Grinnell", "social-justice-at-grinnell"),
            ("Scarlet & Black (S&B) Archives", "scarlet-black-s-b-archives"),
            (" Alumni of the 1940's ", "alumni-of-the-1940-s"),
            ("A Very Long Collection Title That Must Not Be Truncated After Forty Characters",
             "a-very-long-collection-title-that-must-not-be-truncated-after-forty-characters"),
        ]
        self.client.fetch_collection_bibs.return_value = ["991"]
        for title, expected in cases:
            with self.subTest(title=title):
                self.client.resolve_collection.return_value = ("456", title)
                self.assertEqual(0, self.run_cli("--headless", "--retrieve", "--collection-title", "Lookup title",
                                                 "--output", str(self.root)))
                command = shlex.split(self.stdout.getvalue().splitlines()[-1])
                self.assertEqual(expected, command[command.index("--objectid-prefix") + 1])
                payload = json.loads(Path(command[command.index("--source") + 1]).read_text())
                self.assertNotIn("objectid_prefix", payload)
                self.assertNotIn("objectid", payload["records"][0])

    def test_mms_ids_accept_commas_and_newlines_and_do_not_resolve_a_set(self):
        path, payload = self.retrieve("--mms-ids", "991, 992\n991\n")
        self.assertEqual(["991", "992"], self.client.fetch_records.call_args.args[0])
        self.client.fetch_set_members.assert_not_called()
        self.client.resolve_collection.assert_not_called()
        self.assertEqual("MMS ID selection", payload["collection_title"])
        self.assertRegex(path.parent.parent.name, r"^mms-ids-[a-f0-9]{12}$")
        self.assertNotIn("alma_set_id", payload)
        self.assertNotIn("alma_collection_pid", payload)

    def test_repeated_retrieval_keeps_both_runs(self):
        for _ in range(2):
            self.assertEqual(0, self.run_cli("--headless", "--retrieve", "--mms-ids", "991",
                                             "--output", str(self.root)))
        manifests = list(self.root.glob("*/*/gems_*.json"))
        self.assertEqual(2, len(manifests))
        self.assertEqual(manifests[0].parent.parent, manifests[1].parent.parent)

    def test_followup_command_quotes_paths_and_preserves_environment_file(self):
        destination = self.root / "operator's output"
        destination.mkdir()
        for explicit in (False, True):
            with self.subTest(explicit=explicit), patch.dict(
                os.environ, {"GEMS_ENV_FILE": str(self.root / "environment's default.env")},
            ):
                args = ["--env-file", str(self.root / "selected environment's.env")] if explicit else []
                self.assertEqual(0, self.run_cli(
                    "--headless", "--retrieve", "--mms-ids", "991",
                    "--output", str(destination), *args,
                ))
                command = shlex.split(self.stdout.getvalue().splitlines()[-1])
                manifest = Path(command[command.index("--source") + 1])
                self.assertTrue(manifest.is_file())
                self.assertEqual(destination.resolve(), manifest.parent.parent.parent)
                self.assertEqual(str(manifest.parent), command[command.index("--output") + 1])
                expected = args[1] if explicit else os.environ["GEMS_ENV_FILE"]
                self.assertEqual(str(Path(expected).resolve()), command[command.index("--env-file") + 1])

    def test_invalid_options_fail_before_contacting_alma(self):
        cases = [
            ("--retrieve",),
            ("--retrieve", "--mms-ids", ""),
            ("--retrieve", "--set-id", "abc"),
            ("--retrieve", "--mms-ids", "991", "--source", "manifest.json"),
            ("--retrieve", "--mms-ids", "991", "--source-type", "omeka"),
            ("--retrieve", "--mms-ids", "991", "--limit", "10"),
            ("--retrieve", "--mms-ids", "991", "--start", "2"),
            ("--retrieve", "--mms-ids", "991", "--web"),
            ("--retrieve", "--set-id", "123", "--collection-title", "Test"),
            ("--mms-ids", "991"),
        ]
        for args in cases:
            with self.subTest(args=args), self.assertRaises(SystemExit) as error:
                self.run_cli("--headless", "--output", str(self.root), *args)
            self.assertEqual(2, error.exception.code)
        self.client.fetch_records.assert_not_called()
        self.client.fetch_set_members.assert_not_called()

    def test_missing_output_or_destination_fails_before_contacting_alma(self):
        for args in [(), ("--output", str(self.root / "missing"))]:
            with self.subTest(args=args), self.assertRaises(SystemExit) as error:
                self.run_cli("--headless", "--retrieve", "--mms-ids", "991", *args)
            self.assertEqual(2, error.exception.code)
        self.client.fetch_records.assert_not_called()

    def test_unwritable_destination_fails_before_contacting_alma(self):
        with patch("gems.retrieval.tempfile.TemporaryFile", side_effect=PermissionError("read-only destination")):
            with self.assertRaises(SystemExit):
                self.run_cli("--headless", "--retrieve", "--mms-ids", "991", "--output", str(self.root))
        self.client.fetch_records.assert_not_called()
        self.assertIn("read-only destination", self.stderr.getvalue())

    def test_empty_selection_results_and_api_errors_are_explicit_failures(self):
        for failure in (ValueError("ALMA_API_KEY is not configured."), RuntimeError("Alma API failed"),
                        ConnectionError("Alma connection failed")):
            self.client.fetch_records.side_effect = failure
            with self.subTest(failure=failure), self.assertRaises(SystemExit) as error:
                self.run_cli("--headless", "--retrieve", "--mms-ids", "991", "--output", str(self.root))
            self.assertEqual(2, error.exception.code)
            self.assertIn(str(failure), self.stderr.getvalue())
        self.client.fetch_set_title.return_value = "Empty"
        self.client.fetch_set_members.return_value = []
        with self.assertRaises(SystemExit):
            self.run_cli("--headless", "--retrieve", "--set-id", "123", "--output", str(self.root))
        self.assertIn("No Alma records", self.stderr.getvalue())
        self.assertEqual([], list(self.root.iterdir()))
        self.assertNotIn("Button 2:", self.stdout.getvalue())

    def test_api_errors_redact_credentials(self):
        self.client.fetch_records.side_effect = ConnectionError("failed: https://example.org/file?token=private secret-key")
        with patch.dict(os.environ, {"ALMA_API_KEY": "secret-key"}), self.assertRaises(SystemExit):
            self.run_cli("--headless", "--retrieve", "--mms-ids", "991", "--output", str(self.root))
        self.assertNotIn("secret-key", self.stderr.getvalue())
        self.assertNotIn("token=private", self.stderr.getvalue())

    def test_existing_alma_export_supports_range_and_objectid_prefix(self):
        source = self.root / "manifest.json"
        source.write_text(json.dumps({"records": [{"identifier": str(i)} for i in (1, 2, 3)]}))
        self.assertEqual(0, self.run_cli("--headless", "--source", str(source), "--output", str(self.root),
                                        "--start", "2", "--limit", "1", "--objectid-prefix", "test"))
        self.assertTrue((self.root / "collection_metadata.csv").is_file())
        self.client.fetch_records.assert_not_called()

    def test_retrieved_manifest_can_be_exported_by_button_2(self):
        original = self.root / "original.txt"
        original.write_text("Alma asset bytes\n")
        self.client.fetch_records.side_effect = None
        self.client.fetch_records.return_value = [{
            "identifier": "991", "metadata": {"title": "Retrieved title"},
            "files": [{"path": str(original), "filename": "sample.txt"}],
        }]
        manifest, _ = self.retrieve("--mms-ids", "991")
        command = shlex.split(self.stdout.getvalue().splitlines()[-1])
        completed = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(original.read_bytes(), (manifest.parent / "objects" / "sample.txt").read_bytes())
        self.assertIn("Retrieved title", (manifest.parent / "collection_metadata.csv").read_text())

    def test_retrieval_imports_no_flet(self):
        script = """
import sys
from unittest.mock import MagicMock, patch
sys.modules['flet'] = None
from gems.__main__ import cli
client = MagicMock()
client.fetch_records.return_value = [{'identifier': '991'}]
client.skipped_errors = []
client.skipped_positions = []
with patch('gems.__main__.AlmaClient', return_value=client), patch('gems.__main__.load_environment'):
    sys.argv = ['gems', '--headless', '--retrieve', '--mms-ids', '991', '--output', sys.argv[1]]
    assert cli() == 0
assert 'gems.app' not in sys.modules
assert 'gems.web' not in sys.modules
"""
        completed = subprocess.run([sys.executable, "-c", script, str(self.root)],
                                   capture_output=True, text=True, timeout=30)
        self.assertEqual(0, completed.returncode, completed.stderr)


if __name__ == "__main__":
    unittest.main()
