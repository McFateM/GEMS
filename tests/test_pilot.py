from __future__ import annotations

import argparse
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from gems.pilot import Runner, file_hashes, main, wait_for
from gems.storage import Storage


class PilotTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.storage = Storage(self.root / "config", self.root / "data")
        self.storage.config.mkdir()
        self.storage.data.mkdir()
        self.storage.initialize()
        args = argparse.Namespace(port=8551, timeout=30, mms_ids=None)
        self.runner = Runner(self.root, self.storage, args)

    def test_offline_lifecycle_and_restore_leave_verifiable_evidence(self):
        self.runner.offline()
        self.runner.lifecycle()
        self.runner.storage_and_restore()
        lifecycle = json.loads((self.root / "lifecycle.json").read_text())
        for outcome, job_id in lifecycle.items():
            job = json.loads((self.storage.data / "jobs" / f"{job_id}.json").read_text())
            self.assertEqual(outcome, job["state"])
        self.assertEqual(file_hashes(self.root / "backup"), file_hashes(self.root / "restored"))

    def test_report_keeps_manual_acceptance_pending(self):
        self.runner.step("Synthetic check", lambda: None)
        report = json.loads((self.root / "report.json").read_text())
        self.assertEqual("PASS", report["automated"][0]["status"])
        self.assertTrue(all(item["status"] == "PENDING" for item in report["manual"]))
        self.assertFalse(report["live_alma_requested"])
        self.assertTrue(report["acceptance"].startswith("PENDING"))

    def test_failure_is_explicit_and_never_recorded_as_pass(self):
        def fail():
            raise RuntimeError("deliberate fixture failure")

        with self.assertRaisesRegex(RuntimeError, "deliberate fixture"):
            self.runner.step("Failing check", fail)
        self.runner.report()
        report = json.loads((self.root / "report.json").read_text())
        self.assertEqual("FAIL", report["automated"][0]["status"])
        self.assertIn("deliberate fixture failure", report["automated"][0]["evidence"])

    def test_wait_timeout_is_not_success(self):
        with self.assertRaises(TimeoutError):
            wait_for(lambda: False, timeout=0.01)

    def test_live_selection_is_validated_before_contacting_alma(self):
        self.runner.args.mms_ids = "123"
        with patch.dict("os.environ", {"ALMA_API_KEY": "fixture-key"}):
            with self.assertRaisesRegex(RuntimeError, "2-3 distinct"):
                self.runner.live()
        self.assertFalse((self.storage.data / "jobs").exists())

    def test_opt_in_retrieval_retains_manifest_and_result(self):
        self.runner.args.mms_ids = "123,456"
        client = MagicMock()
        client.fetch_records.return_value = [{"mms_id": "123"}, {"mms_id": "456"}]
        client.skipped_errors = []
        client.skipped_positions = []
        with patch.dict("os.environ", {"ALMA_API_KEY": "fixture-key"}), patch(
            "gems.service.AlmaClient", return_value=client
        ):
            self.runner.live()
        result = json.loads((self.root / "live-result.json").read_text())
        self.assertEqual(2, result["records"])
        self.assertTrue(Path(result["manifest"]).is_relative_to(self.storage.data))
        self.assertTrue(Path(result["manifest"]).is_file())
        self.assertFalse((Path(result["manifest"]).parent / "objects").exists())

    def test_occupied_port_is_not_reused_or_stopped(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            self.runner.args.port = listener.getsockname()[1]
            with patch("gems.pilot.child") as child:
                with self.assertRaises(OSError):
                    self.runner.web()
                child.assert_not_called()

    def test_command_failure_stops_runner_and_persists_report(self):
        (self.storage.data / "pilot").mkdir()
        environment = {
            "GEMS_CONFIG_DIR": str(self.storage.config),
            "GEMS_DATA_DIR": str(self.storage.data),
            "GEMS_ENV_FILE": str(self.root / "empty.env"),
        }
        with patch.dict("os.environ", environment), patch("sys.argv", ["gems.pilot"]), patch(
            "gems.pilot.Runner.baseline", side_effect=RuntimeError("baseline fixture failure")
        ), patch("gems.pilot.Runner.web") as web:
            self.assertEqual(1, main())
            web.assert_not_called()
        evidence = next((self.storage.data / "pilot").glob("acceptance-*"))
        report = json.loads((evidence / "report.json").read_text())
        self.assertEqual(1, len(report["automated"]))
        self.assertEqual("FAIL", report["automated"][0]["status"])
        self.assertIn("baseline fixture failure", (evidence / "failure.log").read_text())


if __name__ == "__main__":
    unittest.main()
