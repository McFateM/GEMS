from __future__ import annotations

import csv
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from gems.pipeline import ExportCancelled, process_export
from gems.service import JobService
from gems.storage import MARKER, Storage, atomic_json, load_environment


class StorageTests(unittest.TestCase):
    def test_explicit_absolute_roots_and_markers_are_required(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"GEMS_CONFIG_DIR": "", "GEMS_DATA_DIR": ""}):
                with self.assertRaisesRegex(ValueError, "GEMS_CONFIG_DIR"):
                    Storage.from_environment()
            with patch.dict(os.environ, {"GEMS_CONFIG_DIR": directory, "GEMS_DATA_DIR": directory}):
                storage = Storage.from_environment()
                with self.assertRaises(FileNotFoundError):
                    storage.check()
                storage.initialize()
                storage.check()
                (Path(directory) / MARKER).unlink()
                with self.assertRaises(FileNotFoundError):
                    storage.check()
                self.assertFalse((Path(directory) / MARKER).exists())

    def test_paths_reject_outside_roots_and_symlink_escape(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory).resolve()
            storage = Storage(root, root)
            external = Path(outside) / "external.json"
            external.write_text("{}")
            link = root / "link.json"
            link.symlink_to(external)
            for path in (external, link):
                with self.assertRaisesRegex(ValueError, "GEMS_DATA_DIR"):
                    storage.data_path(str(path))
                with self.assertRaisesRegex(ValueError, "Field maps"):
                    storage.map_path(str(path))

    def test_failed_atomic_replace_preserves_existing_state_and_cleans_temporary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            atomic_json(path, {"old": True})
            with patch("gems.storage.os.replace", side_effect=OSError("share unavailable")):
                with self.assertRaises(OSError):
                    atomic_json(path, {"new": True})
            self.assertEqual({"old": True}, json.loads(path.read_text()))
            self.assertEqual([path], list(path.parent.iterdir()))

    def test_explicit_environment_file_is_required_and_process_environment_wins(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory) / "private.env"
            env.write_text("GEMS_DATA_DIR=/from-file\n")
            with patch.dict(os.environ, {"GEMS_DATA_DIR": "/from-process"}):
                load_environment(str(env))
                self.assertEqual("/from-process", os.environ["GEMS_DATA_DIR"])
            with self.assertRaisesRegex(ValueError, "does not exist"):
                load_environment(str(env.parent / "missing.env"))


@unittest.skipIf(os.name == "nt", "Managed web service requires a POSIX host")
class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        config = self.root / "config"
        data = self.root / "data"
        config.mkdir()
        data.mkdir()
        self.storage = Storage(config, data)
        self.storage.initialize()
        self.service = JobService(self.storage)
        self.service.claim("operator")

    def tearDown(self):
        self.service.close()
        self.temporary.cleanup()

    def wait(self, job_id):
        self.service._thread.join(timeout=5)
        self.assertFalse(self.service._thread.is_alive())
        return next(job for job in self.service.jobs() if job["id"] == job_id)

    def manifest(self):
        original = self.storage.data / "original.txt"
        original.write_text("offline smoke test\n")
        manifest = self.storage.data / "prepared.json"
        manifest.write_text(json.dumps({"records": [{
            "identifier": "test-1", "metadata": {"title": "Offline export"},
            "files": [{"path": str(original), "filename": "sample.txt"}],
        }]}))
        return manifest

    def test_export_results_and_preferences_persist_and_survive_reopen(self):
        manifest = self.manifest()
        job_id = self.service.submit("operator", "export", {"source": str(manifest), "start": "1", "limit": ""})
        job = self.wait(job_id)
        self.assertEqual("succeeded", job["state"], job["message"])
        self.assertEqual((1, 1), (job["result"]["rows"], job["result"]["files"]))
        self.assertEqual("offline smoke test\n", (self.storage.data / "objects" / "sample.txt").read_text())
        with Path(job["result"]["csv"]).open(newline="") as handle:
            self.assertEqual("Offline export", list(csv.DictReader(handle))[0]["title"])
        self.assertIn("Completed", self.service.log_tail(job_id))
        self.service.close()
        self.service = JobService(self.storage)
        self.assertEqual("succeeded", self.service.jobs()[0]["state"])
        self.assertEqual(str(manifest), self.service.preferences()["source"])

    def test_retrieval_preserves_selection_group_timestamp_counts_and_warnings(self):
        client = MagicMock()
        client.resolve_collection.return_value = ("123", "Social Justice")
        client.fetch_collection_bibs.return_value = ["991", "992", "991"]
        client.fetch_records.side_effect = lambda ids, **kwargs: [{"identifier": value} for value in ids]
        client.skipped_positions = [3]
        client.skipped_errors = ["Entry 3 unavailable"]
        with patch("gems.service.AlmaClient", return_value=client):
            job_id = self.service.submit("operator", "retrieve", {
                "selection": "Social Justice", "mms_ids": "", "destination": str(self.storage.data),
                "start": "2", "limit": "1",
            })
            job = self.wait(job_id)
        self.assertEqual("succeeded", job["state"], job["message"])
        client.fetch_records.assert_called_once()
        self.assertEqual(["991", "992"], client.fetch_records.call_args.args[0])
        manifest = Path(job["result"]["manifest"])
        payload = json.loads(manifest.read_text())
        self.assertEqual("123", payload["alma_collection_pid"])
        self.assertEqual(2, len(payload["records"]))
        self.assertEqual(2, payload["retrieval"]["available_records"])
        self.assertEqual("collection-social-justice-123", manifest.parent.parent.name)
        self.assertEqual([3], job["result"]["skipped_positions"])
        self.assertIn("Entry 3 unavailable", (manifest.parent / "gems.log").read_text())

    def test_omeka_classic_and_s_jobs_use_separate_output_without_alma(self):
        fixtures = Path(__file__).parent / "fixtures" / "omeka"
        original = self.storage.data / "asset.bin"
        original.write_bytes(b"Omeka physical asset")
        for fixture, count in (("classic-single.json", 1), ("s-media.json", 2)):
            with self.subTest(fixture=fixture):
                payload = json.loads((fixtures / fixture).read_text())
                if fixture.startswith("classic"):
                    payload[0]["files_list"][0]["file_urls"]["original"] = original.as_uri()
                else:
                    for media in payload[0]["o:media"]:
                        media["o:original_url"] = original.as_uri()
                source = self.storage.data / fixture
                source.write_text(json.dumps(payload))
                output = self.storage.data / fixture.removesuffix(".json")
                output.mkdir()
                with patch("gems.service.AlmaClient") as alma:
                    job_id = self.service.submit("operator", "export", {
                        "source": str(source), "source_type": "omeka", "omeka_output": str(output),
                        "legacy_mods": "/not-an-alma-input", "prefix": "ignored",
                    })
                    job = self.wait(job_id)
                self.assertEqual("succeeded", job["state"], job["message"])
                alma.assert_not_called()
                expected_rows = count + (1 if count > 1 else 0)
                self.assertEqual((expected_rows, count), (job["result"]["rows"], job["result"]["files"]))
                self.assertEqual(output / "collection_metadata.csv", Path(job["result"]["csv"]))
                with Path(job["result"]["csv"]).open(newline="") as handle:
                    rows = list(csv.DictReader(handle))
                self.assertEqual(expected_rows, len(rows))
                for row in rows:
                    self.assertNotIn("objectid", row)
                assets = [path for path in (output / "objects").rglob("*") if path.is_file()]
                self.assertEqual(count, len(assets))
                self.assertTrue(all(path.read_bytes() == original.read_bytes() for path in assets))
                self.assertTrue((output / "gems.log").is_file())
                self.assertEqual("omeka", self.service.preferences()["source_type"])
        self.assertFalse((self.storage.data / "collection_metadata.csv").exists())

    def test_omeka_output_and_source_type_are_validated_before_job_creation(self):
        source = self.manifest()
        outside = self.root / "outside"
        outside.mkdir()
        for values in (
            {"source_type": "invalid"},
            {"source_type": "omeka"},
            {"source_type": "omeka", "omeka_output": str(outside)},
            {"source_type": "omeka", "omeka_output": str(self.storage.data / "missing")},
        ):
            with self.subTest(values=values), self.assertRaises((ValueError, FileNotFoundError)):
                self.service.submit("operator", "export", {"source": str(source), **values})
        self.assertEqual([], self.service.jobs())

    def test_serialized_jobs_operator_lease_and_tab_disconnect(self):
        entered, release = threading.Event(), threading.Event()

        def export(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(5))
            raise ExportCancelled()

        with patch("gems.service.process_export", side_effect=export):
            try:
                manifest = self.manifest()
                values = {"source": str(manifest)}
                job_id = self.service.submit("operator", "export", values)
                self.assertTrue(entered.wait(5))
                self.assertFalse(self.service.claim("second-tab"))
                with self.assertRaisesRegex(ValueError, "active operator"):
                    self.service.submit("second-tab", "export", values)
                with self.assertRaisesRegex(ValueError, "already running"):
                    self.service.submit("operator", "export", values)
                self.service.release("operator")
                self.assertTrue(self.service.claim("second-tab"))
                self.assertEqual("running", self.service.jobs()[0]["state"])
                self.service.cancel("second-tab")
                self.assertEqual("cancelling", self.service.jobs()[0]["state"])
            finally:
                release.set()
            self.assertEqual("cancelled", self.wait(job_id)["state"])

    def test_restart_marks_unfinished_job_interrupted_without_resubmitting(self):
        self.service.close()
        job = dict(id="test-job", kind="export", state="running", created_at="2026-10-19",
                   inputs={"source": "review-me"}, result={}, message="working", progress=0.5)
        atomic_json(self.storage.data / "jobs" / "test-job.json", job)
        self.service = JobService(self.storage)
        recovered = self.service.jobs()[0]
        self.assertEqual("interrupted", recovered["state"])
        self.assertIn("Review partial output", recovered["message"])
        self.assertIsNone(self.service._thread)
        self.assertEqual("interrupted", json.loads((self.storage.data / "jobs" / "test-job.json").read_text())["state"])

    def test_second_service_process_is_rejected(self):
        result = subprocess.run([sys.executable, "-c",
                                 "from gems.service import JobService; from gems.storage import Storage;"
                                 "from pathlib import Path; import sys;"
                                 "JobService(Storage(Path(sys.argv[1]), Path(sys.argv[2])))",
                                 str(self.storage.config), str(self.storage.data)], capture_output=True, text=True)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("Another GEMS service", result.stderr)

    def test_missing_mount_marker_blocks_submission_without_local_fallback(self):
        manifest = self.manifest()
        (self.storage.data / MARKER).unlink()
        with self.assertRaises(FileNotFoundError):
            self.service.submit("operator", "export", {"source": str(manifest)})
        self.assertEqual([], self.service.jobs())
        self.assertFalse((self.storage.config / "web-settings.json").exists())

    def test_storage_loss_during_job_is_visible_and_blocks_further_jobs(self):
        entered, release = threading.Event(), threading.Event()

        def export(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(5))
            raise OSError("network storage lost")

        manifest = self.manifest()
        with patch("gems.service.process_export", side_effect=export), patch("sys.stderr", new_callable=io.StringIO) as stderr:
            try:
                job_id = self.service.submit("operator", "export", {"source": str(manifest)})
                self.assertTrue(entered.wait(5))
                (self.storage.data / MARKER).unlink()
            finally:
                release.set()
            job = self.wait(job_id)
            self.assertIn("write-blocked", stderr.getvalue())
        self.assertEqual("failed", job["state"])
        self.assertIn("write-blocked", job["message"])
        self.storage.initialize()
        with self.assertRaisesRegex(OSError, "write-blocked"):
            self.service.submit("operator", "export", {"source": str(manifest)})

    def test_job_failures_are_persisted_with_secrets_redacted(self):
        with patch.dict(os.environ, {"ALMA_API_KEY": "private-api-key"}), patch(
            "gems.service.process_export",
            side_effect=ValueError("private-api-key https://example.test/object?signature=secret"),
        ):
            job = self.wait(self.service.submit("operator", "export", {"source": str(self.manifest())}))
        self.assertEqual("failed", job["state"])
        persisted = (self.storage.data / "jobs" / f"{job['id']}.json").read_text()
        log = self.service.log_tail(job["id"])
        for text in (persisted, log):
            self.assertNotIn("private-api-key", text)
            self.assertNotIn("signature=secret", text)
            self.assertIn("[redacted]", text)

    def test_basic_map_cancellation_and_progress_are_supported(self):
        manifest = self.manifest()
        with self.assertRaises(ExportCancelled):
            process_export(manifest, self.storage.data, is_cancelled=lambda: True)
        progress = MagicMock()
        result = process_export(manifest, self.storage.data, progress=progress)
        self.assertEqual(1, result.file_count)
        progress.assert_any_call("sample.txt", 0, 1)
        progress.assert_any_call("", 1, 1)

    def test_web_controls_have_server_paths_no_native_pickers_and_recover_job(self):
        import flet as ft
        from gems.web import main

        job_id = self.service.submit("operator", "export", {"source": str(self.manifest())})
        self.wait(job_id)
        self.service.release("operator")
        page = MagicMock(session_id="browser", route=f"/jobs/{job_id}")
        main(page, self.service)
        controls = page.add.call_args.args[0].controls
        self.assertFalse(any(isinstance(control, ft.FilePicker) for control in controls))
        self.assertTrue(any(isinstance(control, ft.Text) and job_id in (control.value or "") for control in controls))
        page.window.assert_not_called()
        page.on_disconnect(None)
        page.run_task.return_value.cancel.assert_called_once()
        page.on_connect(None)
        self.assertEqual(2, page.run_task.call_count)
        page.on_disconnect(None)
        self.assertTrue(self.service.claim("new-browser"))

    def test_invalid_ranges_are_rejected_without_creating_jobs(self):
        for start, limit in (("0", ""), ("1", "0"), ("abc", ""), ("1", "abc")):
            with self.subTest(start=start, limit=limit), self.assertRaises(ValueError):
                self.service.submit("operator", "export", {"source": str(self.manifest()), "start": start, "limit": limit})
        self.assertEqual([], self.service.jobs())

    def test_corrupt_preferences_fail_startup_and_release_process_lock(self):
        self.service.close()
        settings = self.storage.config / "web-settings.json"
        settings.write_text("not json")
        with self.assertRaises(json.JSONDecodeError):
            JobService(self.storage)
        settings.unlink()
        self.service = JobService(self.storage)


class EntryPointTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {
            "GEMS_CONFIG_DIR": "",
            "GEMS_DATA_DIR": "",
            "GEMS_ENV_FILE": "",
            "ALMA_API_KEY": "",
        })
        environment.start()
        self.addCleanup(environment.stop)

    def test_headless_help_does_not_import_ui_or_flet(self):
        result = subprocess.run([sys.executable, "-c", """
import sys
from gems.__main__ import cli
sys.argv = ["gems", "--help"]
try:
    cli()
except SystemExit as exc:
    assert exc.code == 0
assert "flet" not in sys.modules
assert "gems.app" not in sys.modules
"""], capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("--web", result.stdout)

    def test_desktop_remains_default_and_web_mode_has_explicit_port(self):
        from gems.__main__ import cli

        with patch("sys.argv", ["gems"]), patch("gems.__main__.load_environment"), patch("gems.app.launch") as desktop:
            self.assertEqual(0, cli())
            desktop.assert_called_once_with()
        with patch("sys.argv", ["gems", "--web", "--port", "8551"]), patch(
            "gems.__main__.load_environment"
        ), patch("gems.web.launch") as web:
            self.assertEqual(0, cli())
            web.assert_called_once_with(port=8551)

    def test_cli_headless_export_works_when_flet_import_is_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env_file = root / "test.env"
            env_file.write_text("")
            source = root / "manifest.json"
            source.write_text(json.dumps({"records": [{"identifier": "cli", "metadata": {"title": "No UI"}}]}))
            result = subprocess.run([sys.executable, "-c", """
import sys
sys.modules["flet"] = None
from gems.__main__ import cli
raise SystemExit(cli())
""", "--env-file", str(env_file), "--headless", "--source", str(source), "--output", str(root / "output")],
                                    capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertTrue((root / "output" / "collection_metadata.csv").is_file())

    def test_non_loopback_flet_override_is_rejected(self):
        from gems.web import launch

        with patch.dict(os.environ, {"FLET_SERVER_IP": "0.0.0.0"}):
            with self.assertRaisesRegex(ValueError, "loopback"):
                launch()
