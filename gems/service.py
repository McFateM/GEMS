from __future__ import annotations

import copy
import json
import os
import sys
import threading
import uuid
from datetime import datetime
from typing import Any

from .alma import AlmaClient
from .pipeline import ExportCancelled, is_template_map, process_export
from .retrieval import private_message, retrieve_manifest
from .storage import Storage, atomic_json

ACTIVE = {"queued", "running", "cancelling"}


def now() -> str:
    return datetime.now().astimezone().isoformat()


class JobService:
    """One process and one worker for a private, single-operator service."""

    def __init__(self, storage: Storage) -> None:
        if os.name == "nt":
            raise RuntimeError("The managed web service requires a POSIX host; use desktop mode on Windows.")
        import fcntl

        self.storage = storage
        storage.check()
        self.jobs_dir = storage.data / "jobs"
        self.jobs_dir.mkdir(exist_ok=True)
        self._lock_file = (storage.data / ".gems-service.lock").open("a")
        try:
            fcntl.flock(self._lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._lock_file.close()
            raise RuntimeError("Another GEMS service owns this data root; refusing a second writer.") from None
        self._mutex = threading.RLock()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._operator: str | None = None
        self._active: str | None = None
        self._closing = False
        self.storage_error = ""
        self._jobs: dict[str, dict[str, Any]] = {}
        try:
            self.preferences()
            for path in sorted(self.jobs_dir.glob("*.json")):
                job = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(job, dict) or job.get("id") != path.stem or "state" not in job:
                    raise ValueError(f"Invalid job state: {path}")
                if job["state"] in ACTIVE:
                    job.update(state="interrupted", updated_at=now(), finished_at=now(),
                               message="Service stopped during this job. Review partial output before submitting a new job.")
                    atomic_json(path, job)
                self._jobs[job["id"]] = job
        except Exception:
            self._lock_file.close()
            raise

    def claim(self, session: str) -> bool:
        with self._mutex:
            if self._operator not in (None, session):
                return False
            self._operator = session
            return True

    def release(self, session: str) -> None:
        with self._mutex:
            if self._operator == session:
                self._operator = None

    def _require_operator(self, session: str) -> None:
        if self._operator != session:
            raise ValueError("Another browser session is the active operator. Close it before taking control.")
        if self._closing:
            raise ValueError("Service is shutting down.")
        if self.storage_error:
            raise OSError(self.storage_error)

    def preferences(self) -> dict[str, Any]:
        self.storage.check()
        path = self.storage.config / "web-settings.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        if not isinstance(value, dict):
            raise ValueError(f"Invalid settings object: {path}")
        return value

    def jobs(self) -> list[dict[str, Any]]:
        with self._mutex:
            return copy.deepcopy(sorted(self._jobs.values(), key=lambda job: job["created_at"], reverse=True))

    def submit(self, session: str, kind: str, inputs: dict[str, Any]) -> str:
        with self._mutex:
            self._require_operator(session)
            if self._active is not None:
                raise ValueError("A job is already running. Wait until it stops before starting another.")
            if kind not in {"retrieve", "export"}:
                raise ValueError(f"Unknown job type: {kind}")
            self.storage.check()
            inputs = self._validate(kind, inputs)
            job_id = uuid.uuid4().hex
            job = dict(id=job_id, kind=kind, state="queued", inputs=inputs, created_at=now(),
                       updated_at=now(), message="Queued", result={}, progress=None)
            atomic_json(self.storage.config / "web-settings.json", inputs)
            atomic_json(self.jobs_dir / f"{job_id}.json", job)
            self._jobs[job_id] = job
            self._active = job_id
            self._cancel.clear()
            self._thread = threading.Thread(target=self._run, args=(job_id,), name=f"gems-{job_id}", daemon=False)
            try:
                self._thread.start()
            except RuntimeError as exc:
                self._active = None
                self._update(job_id, state="failed", message=str(exc), finished_at=now())
                raise
            return job_id

    def _validate(self, kind: str, inputs: dict[str, Any]) -> dict[str, Any]:
        values = dict(inputs)
        if kind == "retrieve":
            values["destination"] = str(self.storage.data_path(values["destination"], directory=True))
            if not values.get("mms_ids", "").strip() and not values.get("selection", "").strip():
                raise ValueError("Enter an Alma set ID, collection title, or MMS IDs.")
        else:
            values["source"] = str(self.storage.data_path(values["source"]))
            source_type = values.get("source_type") or "alma"
            if source_type not in {"alma", "omeka"}:
                raise ValueError("Input source must be alma or omeka.")
            values["source_type"] = source_type
            if source_type == "omeka":
                values["omeka_output"] = str(self.storage.data_path(values.get("omeka_output", ""), directory=True))
                values["legacy_mods"] = ""
                values["prefix"] = ""
            start = int(values.get("start") or 1)
            limit = int(values["limit"]) if values.get("limit") else None
            if start < 1 or (limit is not None and limit < 1):
                raise ValueError("Start record and record limit must be positive whole numbers.")
            values.update(start=start, limit=limit)
        if values.get("field_map"):
            values["field_map"] = str(self.storage.map_path(values["field_map"]))
        if values.get("legacy_mods"):
            values["legacy_mods"] = str(self.storage.data_path(values["legacy_mods"], directory=True))
        return values

    def _update(self, job_id: str, **changes: Any) -> None:
        with self._mutex:
            job = self._jobs[job_id]
            if "message" in changes:
                changes["message"] = private_message(changes["message"])
            job.update(changes, updated_at=now())
            self.storage.check()
            atomic_json(self.jobs_dir / f"{job_id}.json", job)

    def _log(self, job_id: str, message: str) -> None:
        self.storage.check()
        with (self.jobs_dir / f"{job_id}.log").open("a", encoding="utf-8") as handle:
            handle.write(f"{now()} {private_message(message)}\n")

    def log_tail(self, job_id: str) -> str:
        with self._mutex:
            if job_id not in self._jobs:
                raise ValueError("Unknown job.")
        self.storage.check()
        path = self.jobs_dir / f"{job_id}.log"
        if not path.exists():
            return "No job log yet."
        with path.open("rb") as handle:
            handle.seek(max(0, path.stat().st_size - 32768))
            return handle.read(32768).decode("utf-8", errors="replace")

    def cancel(self, session: str) -> None:
        with self._mutex:
            self._require_operator(session)
            if self._active is None:
                raise ValueError("No active job to cancel.")
            self._cancel.set()
            self._update(self._active, state="cancelling", message="Cancellation requested; waiting for the current operation.")

    def _check_cancelled(self) -> None:
        if self._cancel.is_set():
            raise ExportCancelled()
        self.storage.check()

    def _run(self, job_id: str) -> None:
        try:
            self._update(job_id, state="running", started_at=now(), message="Starting")
            job = self._jobs[job_id]
            self._log(job_id, f"Starting {job['kind']} job {job_id}")
            self._check_cancelled()
            result = self._retrieve(job_id, job["inputs"]) if job["kind"] == "retrieve" else self._export(job_id, job["inputs"])
            self._update(job_id, state="succeeded", result=result, progress=1, finished_at=now(), message="Completed")
            self._log(job_id, f"Completed: {json.dumps(result)}")
        except ExportCancelled:
            self._finish_error(job_id, "cancelled", "Cancelled. Partial files remain; review output before retrying.")
        except Exception as exc:
            self._finish_error(job_id, "failed", private_message(f"{type(exc).__name__}: {exc}"))
        finally:
            with self._mutex:
                self._active = None

    def _finish_error(self, job_id: str, state: str, message: str) -> None:
        try:
            self._update(job_id, state=state, message=message, finished_at=now())
            self._log(job_id, message)
        except (OSError, ValueError) as exc:
            with self._mutex:
                self.storage_error = f"Storage unavailable; service is write-blocked until restart: {private_message(str(exc))}"
                self._jobs[job_id].update(state="failed", message=f"{message}. {self.storage_error}")
            print(self.storage_error, file=sys.stderr, flush=True)

    def _retrieve(self, job_id: str, values: dict[str, Any]) -> dict[str, Any]:
        def progress(done: int, total: int) -> None:
            current = done * 10 // total if total else 10
            message = f"Retrieving Alma records: {current * 10}% ({done}/{total})"
            self._update(job_id, message=message, progress=done / total if total else 1)
            self._log(job_id, message)

        result = retrieve_manifest(
            self.storage.data_path(values["destination"], directory=True), client=AlmaClient(),
            selection=values.get("selection", ""), mms_ids=values.get("mms_ids", ""),
            on_progress=progress, check_cancelled=self._check_cancelled,
        )
        for warning in result["warnings"]:
            self._log(job_id, f"Skipped collection entry: {warning}")
        return result

    def _export(self, job_id: str, values: dict[str, Any]) -> dict[str, Any]:
        source = self.storage.data_path(values["source"])
        source_type = values.get("source_type", "alma")
        destination = (self.storage.data_path(values["omeka_output"], directory=True)
                       if source_type == "omeka" else source.parent)
        field_map = json.loads(self.storage.map_path(values["field_map"]).read_text(encoding="utf-8")) if values.get("field_map") else {}
        if not isinstance(field_map, dict) or (
            not is_template_map(field_map) and not all(isinstance(v, str) for v in field_map.values())
        ) or (is_template_map(field_map) and not isinstance(field_map.get("rules", {}), dict)):
            raise ValueError("Field map must be a template map or an object of string field mappings.")

        def progress(name: str, done: int, total: int) -> None:
            self._check_cancelled()
            self._update(job_id, message=f"Mapping file {min(done + 1, total)} of {total}: {name}",
                         progress=done / total if total else 0)

        def cancelled() -> bool:
            self.storage.check()
            return self._cancel.is_set()

        result = process_export(
            source, destination, source_type=source_type,
            field_map=field_map, start=values["start"], limit=values["limit"],
            legacy_mods_dir=values.get("legacy_mods") or None,
            objectid_prefix=values.get("prefix") or None,
            refresh_source=AlmaClient().refresh_file_link if source_type == "alma" else None,
            progress=progress, is_cancelled=cancelled,
        )
        summary = dict(csv=str(result.csv_path), normalized=str(result.json_path), objects=str(result.objects_dir),
                       rows=result.row_count, files=result.file_count, first_record=result.first_record,
                       last_record=result.last_record, total_records=result.total_records,
                       renamed_files=result.renamed_files, skipped_records=result.skipped_records)
        self.storage.check()
        with (destination / "gems.log").open("a", encoding="utf-8") as handle:
            handle.write(f"{now()} Job {job_id}: {json.dumps(summary)}\n")
        return summary

    def close(self) -> None:
        with self._mutex:
            self._closing = True
            self._cancel.set()
            thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join()
        self._lock_file.close()
