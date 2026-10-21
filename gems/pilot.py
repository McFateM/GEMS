from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import mkdtemp
from typing import Any, Callable, Iterator
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

from .service import ACTIVE, JobService, private_message
from .storage import MARKER, Storage, atomic_json, load_environment

REPOSITORY = Path(__file__).resolve().parent.parent
MANUAL_CHECKS = [
    "Administrator approval, quota, retention, monitoring, and institutional backups",
    "Browser operator handoff, visible progress/errors, and job-URL recovery",
    "Real Alma metadata, MODS precedence, compound relationships, and file content",
    "Expired Alma signed-link refresh with previously absent downloads",
    "Administrator-supervised real storage outage and restoration",
    "Institutional backup restoration into separate roots",
]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def wait_for(check: Callable[[], bool], *, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.1)
    raise TimeoutError(f"Acceptance check did not finish within {timeout:g} seconds.")


def wait_job(service: JobService, job_id: str, timeout: float) -> dict[str, Any]:
    wait_for(lambda: next(job for job in service.jobs() if job["id"] == job_id)["state"] not in ACTIVE,
             timeout=timeout)
    # A terminal state can be persisted just before the worker releases its slot.
    if service._thread is not None:
        service._thread.join(timeout=5)
        require(not service._thread.is_alive(), "Job worker did not stop.")
    return next(job for job in service.jobs() if job["id"] == job_id)


@contextmanager
def child(command: list[str], environment: dict[str, str], log: Path) -> Iterator[subprocess.Popen[bytes]]:
    with log.open("w", encoding="utf-8") as handle:
        process = subprocess.Popen(command, cwd=REPOSITORY, env=environment, stdout=handle,
                                   stderr=subprocess.STDOUT)
        try:
            yield process
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def file_hashes(root: Path) -> dict[str, str]:
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
            result[path.relative_to(root).as_posix()] = digest.hexdigest()
    return result


class Runner:
    def __init__(self, root: Path, storage: Storage, args: argparse.Namespace) -> None:
        self.root, self.storage, self.args = root, storage, args
        self.results: list[dict[str, str]] = []
        self.environment = dict(os.environ, GEMS_CONFIG_DIR=str(storage.config),
                                GEMS_DATA_DIR=str(storage.data), GEMS_ENV_FILE=str(root / "empty.env"),
                                FLET_SERVER_IP="127.0.0.1", FLET_SERVER_PORT=str(args.port),
                                ALMA_API_KEY="", ALMA_API_REGION="")
        (root / "empty.env").write_text("", encoding="utf-8")

    def command(self, name: str, arguments: list[str]) -> None:
        log = self.root / f"{name}.log"
        with log.open("w", encoding="utf-8") as handle:
            result = subprocess.run(arguments, cwd=REPOSITORY, env=self.environment,
                                    stdout=handle, stderr=subprocess.STDOUT, timeout=self.args.timeout)
        require(result.returncode == 0, f"{name} failed; inspect {log}")

    def step(self, name: str, action: Callable[[], None]) -> None:
        print(f"RUN: {name}", flush=True)
        try:
            action()
        except Exception as exc:
            self.results.append(dict(check=name, status="FAIL", evidence=private_message(str(exc))))
            raise
        self.results.append(dict(check=name, status="PASS", evidence=str(self.root)))
        self.report()

    def report(self) -> None:
        manual = [dict(check=name, status="PENDING") for name in MANUAL_CHECKS]
        if not self.args.mms_ids:
            manual.append(dict(check="Authorized live Alma retrieval (not requested)", status="PENDING"))
        atomic_json(self.root / "report.json", {
            "evidence_root": str(self.root), "automated": self.results,
            "manual": manual,
            "live_alma_requested": bool(self.args.mms_ids),
            "not_run": "Checks after the first failure are not run; only listed PASS entries passed.",
            "acceptance": "PENDING: automated passes are not full pilot acceptance",
        })

    def baseline(self) -> None:
        atomic_json(self.root / "host.json", {
            "platform": platform.platform(), "architecture": platform.machine(),
            "os_release": platform.freedesktop_os_release() if sys.platform.startswith("linux") else {},
            "python": sys.version, "executable": sys.executable,
            "free_bytes": shutil.disk_usage(self.root).free,
        })
        for name, arguments in [
            ("revision", ["git", "rev-parse", "HEAD"]),
            ("worktree", ["git", "--no-pager", "status", "--short"]),
            ("packages", [sys.executable, "-m", "pip", "freeze"]),
            ("pip-check", [sys.executable, "-m", "pip", "check"]),
            ("regression-tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests",
                                  "-p", "test_*.py"]),
        ]:
            self.command(name, arguments)

    def offline(self) -> None:
        run = self.storage.data / "offline"
        run.mkdir()
        original = run / "original.txt"
        original.write_text("GEMS acceptance fixture\n", encoding="utf-8")
        manifest = run / "manifest.json"
        atomic_json(manifest, {"records": [{
            "identifier": "pilot", "metadata": {"title": "Acceptance fixture"},
            "files": [{"path": str(original), "filename": "sample.txt"}],
        }]})
        with self.service() as service:
            job = wait_job(service, service.submit("pilot", "export", {"source": str(manifest)}),
                           self.args.timeout)
            require(job["state"] == "succeeded", f"Offline job failed: {job['message']}")
            require(job["result"]["rows"] == 1 and job["result"]["files"] == 1, "Wrong offline counts.")
        with (run / "collection_metadata.csv").open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        require(len(rows) == 1 and rows[0]["title"] == "Acceptance fixture", "Wrong offline CSV.")
        require((run / "objects" / "sample.txt").read_bytes() == original.read_bytes(),
                "Offline object differs from source.")

    @contextmanager
    def service(self) -> Iterator[JobService]:
        service = JobService(self.storage)
        service.claim("pilot")
        try:
            yield service
        finally:
            service.close()

    def web(self) -> None:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", self.args.port))
        opener = build_opener(ProxyHandler({}))

        def ready() -> bool:
            require(process.poll() is None, f"Web process exited; inspect {self.root / 'web.log'}")
            try:
                with opener.open(f"http://127.0.0.1:{self.args.port}/", timeout=1) as response:
                    return response.status == 200 and b"flutter" in response.read().lower()
            except (URLError, TimeoutError):
                return False

        command = [sys.executable, "-m", "gems", "--web", "--port", str(self.args.port),
                   "--env-file", str(self.root / "empty.env")]
        with child(command, self.environment, self.root / "web.log") as process:
            wait_for(ready)
            with (self.root / "second-writer.log").open("w", encoding="utf-8") as handle:
                second = subprocess.run(command, cwd=REPOSITORY, env=self.environment,
                                        stdout=handle, stderr=subprocess.STDOUT, timeout=15)
            require(second.returncode != 0 and "Another GEMS service" in
                    (self.root / "second-writer.log").read_text(), "Second writer was not rejected.")
        with self.service() as service:
            require(any(job["state"] == "succeeded" for job in service.jobs()),
                    "Completed history was lost after web restart.")

    def lifecycle(self) -> None:
        entered, release = threading.Event(), threading.Event()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                entered.set()
                if not release.wait(30):
                    self.send_error(504)
                    return
                try:
                    self.send_response(200)
                    self.send_header("Content-Length", "2")
                    self.end_headers()
                    self.wfile.write(b"ok")
                except (BrokenPipeError, ConnectionResetError):
                    # The forced-termination check intentionally closes its socket.
                    pass

            def log_message(self, format: str, *args: Any) -> None:
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        manifest = self.storage.data / "slow.json"
        url = f"http://127.0.0.1:{server.server_port}/fixture"
        atomic_json(manifest, {"records": [
            {"identifier": str(index), "files": [{"url": url, "filename": f"slow-{index}.txt"}]}
            for index in (1, 2)
        ]})
        try:
            with self.service() as service:
                job_id = service.submit("pilot", "export", {"source": str(manifest)})
                require(entered.wait(10), "Cancellation fixture did not start downloading.")
                service.cancel("pilot")
                release.set()
                require(wait_job(service, job_id, 30)["state"] == "cancelled", "Cancellation failed.")
                require((self.storage.data / "objects" / "slow-1.txt").is_file(),
                        "Expected partial output was not retained.")
            entered.clear()
            release.clear()
            command = [sys.executable, "-m", "gems.pilot", "--worker", str(manifest)]
            with child(command, self.environment, self.root / "interruption.log") as process:
                require(entered.wait(10), "Interruption fixture did not start downloading.")
                running = [json.loads(path.read_text()) for path in (self.storage.data / "jobs").glob("*.json")]
                job_ids = [job["id"] for job in running if job["state"] == "running"]
                require(len(job_ids) == 1, "Expected exactly one running job before termination.")
                process.kill()
                process.wait(timeout=5)
            release.set()
            with self.service() as service:
                recovered = next(job for job in service.jobs() if job["id"] == job_ids[0])
                require(recovered["state"] == "interrupted", "Killed job was not marked interrupted.")
                require(service._thread is None, "Interrupted job was automatically resumed.")
            atomic_json(self.root / "lifecycle.json", {"cancelled": job_id, "interrupted": job_ids[0]})
        finally:
            release.set()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def storage_and_restore(self) -> None:
        marker = self.storage.data / MARKER
        saved = self.storage.data / f"{MARKER}.pilot-held"
        with self.service() as service:
            before = service.jobs()
            marker.rename(saved)
            try:
                try:
                    service.submit("pilot", "export", {"source": str(self.storage.data / "offline/manifest.json")})
                except FileNotFoundError:
                    pass
                else:
                    raise RuntimeError("Missing storage marker did not block submission.")
                require(service.jobs() == before, "Storage failure created a job.")
            finally:
                saved.rename(marker)
        with self.service() as service:
            require(service.jobs() == before, "History changed after storage restoration.")
        backup = self.root / "backup"
        restored = self.root / "restored"
        for destination in (backup, restored):
            destination.mkdir()
        for name, source in (("config", self.storage.config), ("data", self.storage.data)):
            shutil.copytree(source, backup / name)
            shutil.copytree(backup / name, restored / name)
            require(file_hashes(source) == file_hashes(restored / name), f"Restored {name} differs.")
        with (restored / "data/offline/collection_metadata.csv").open(newline="", encoding="utf-8") as handle:
            require(next(csv.DictReader(handle))["title"] == "Acceptance fixture", "Restored CSV is invalid.")
        require((restored / "data/offline/objects/sample.txt").read_text() == "GEMS acceptance fixture\n",
                "Restored object is invalid.")
        restored_service = JobService(Storage(restored / "config", restored / "data"))
        try:
            require(restored_service.jobs() == before, "Restored job history differs.")
        finally:
            restored_service.close()
        atomic_json(self.root / "backup-hashes.json", file_hashes(backup))

    def live(self) -> None:
        require(bool(os.getenv("ALMA_API_KEY")), "Live retrieval requires ALMA_API_KEY.")
        ids = self.args.mms_ids.split(",")
        require(2 <= len(ids) <= 3 and all(value.strip().isdecimal() for value in ids)
                and len({value.strip() for value in ids}) == len(ids),
                "Provide exactly 2-3 distinct, comma-separated numeric MMS IDs.")
        with self.service() as service:
            job = wait_job(service, service.submit("pilot", "retrieve", {
                "mms_ids": self.args.mms_ids, "destination": str(self.storage.data), "selection": "",
            }), self.args.timeout)
            require(job["state"] == "succeeded", f"Alma retrieval failed: {job['message']}")
            require(job["result"]["records"] == len(ids) and not job["result"]["warnings"]
                    and not job["result"]["skipped_positions"], "Incomplete live retrieval; inspect job evidence.")
            atomic_json(self.root / "live-result.json", job["result"])


def worker(manifest: Path) -> int:
    storage = Storage.from_environment()
    service = JobService(storage)
    try:
        service.claim("pilot")
        job_id = service.submit("pilot", "export", {"source": str(manifest)})
        wait_job(service, job_id, 60)
    finally:
        service.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run isolated GEMS pilot acceptance components; never certifies production.")
    parser.add_argument("--env-file", help="Existing private GEMS environment file")
    parser.add_argument("--parent", type=Path, help="Existing evidence directory inside configured GEMS_DATA_DIR")
    parser.add_argument("--port", type=int, default=8551, help="Unused loopback port (default: 8551)")
    parser.add_argument("--timeout", type=float, default=300, help="Per-command/job timeout in seconds")
    parser.add_argument("--mms-ids", help="Opt-in live retrieval of 2-3 approved comma-separated MMS IDs; no live export")
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        return worker(args.worker)
    if os.name != "posix" or not 1 <= args.port <= 65535 or args.timeout <= 0:
        parser.error("Requires POSIX, port 1-65535, and a positive timeout.")
    load_environment(args.env_file)
    configured = Storage.from_environment()
    configured.check()
    parent = configured.data_path(str(args.parent or configured.data / "pilot"), directory=True)
    os.umask(0o077)
    root = Path(mkdtemp(prefix="acceptance-", dir=parent))
    storage = Storage(root / "config", root / "data")
    storage.config.mkdir()
    storage.data.mkdir()
    storage.initialize()
    runner = Runner(root, storage, args)
    print(f"Evidence directory: {root}", flush=True)
    try:
        for name, action in [
            ("Host, dependencies, and regression suite", runner.baseline),
            ("Offline service export and byte comparison", runner.offline),
            ("Real web HTTP, second-writer rejection, and history", runner.web),
            ("Real cancellation and forced-process interruption", runner.lifecycle),
            ("Marker-loss simulation and local backup restoration", runner.storage_and_restore),
        ]:
            runner.step(name, action)
        if args.mms_ids:
            runner.step("Opt-in live Alma retrieval", runner.live)
    except Exception:
        (root / "failure.log").write_text(private_message(traceback.format_exc()), encoding="utf-8")
        print(f"FAIL: inspect {root / 'failure.log'}", file=sys.stderr)
        return 1
    finally:
        runner.report()
    print(f"Automated checks passed. Manual acceptance remains PENDING. Report: {root / 'report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
