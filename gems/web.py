from __future__ import annotations

import asyncio
import importlib.util
import json
import os
from concurrent.futures import Future
from pathlib import Path

import flet as ft

from .service import ACTIVE, JobService
from .storage import Storage


def main(page: ft.Page, service: JobService) -> None:
    page.title = "GEMS - Linux/Web"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.theme = ft.Theme(color_scheme_seed=ft.Colors.TEAL)
    page.padding = 24
    session = page.session_id
    service.claim(session)
    preferences = service.preferences()
    selection = ft.TextField(label="Alma Set ID or Collection Title", value=preferences.get("selection", ""))
    ids = ft.TextField(label="MMS IDs (optional, comma-separated)", value=preferences.get("mms_ids", ""))
    destination = ft.TextField(label="Destination (existing server directory inside GEMS_DATA_DIR)",
                               value=preferences.get("destination", str(service.storage.data)))
    source = ft.TextField(label="Prepared manifest (server JSON or CSV path)",
                          value=preferences.get("source", ""))
    source_type = ft.Dropdown(
        label="Input source", value=preferences.get("source_type", "alma"),
        options=[ft.dropdown.Option("alma", "Alma / Specto prepared manifest"),
                 ft.dropdown.Option("omeka", "Omeka Classic / Omeka S JSON export")],
    )
    omeka_output = ft.TextField(
        label="Omeka output folder (existing server directory inside GEMS_DATA_DIR)",
        value=preferences.get("omeka_output", ""),
    )
    field_map = ft.TextField(label="Field map (optional server JSON path in configuration or data)",
                             value=preferences.get("field_map", ""))
    legacy = ft.TextField(label="Legacy MODS folder (optional server directory inside GEMS_DATA_DIR)",
                          value=preferences.get("legacy_mods", ""))
    start = ft.TextField(label="Start record (1-based)", value=str(preferences.get("start", 1)), width=160)
    limit = ft.TextField(label="Record limit (blank for all)", value=str(preferences.get("limit") or ""), width=200)
    prefix = ft.TextField(label="ObjectID prefix (optional)", value=preferences.get("prefix", ""), width=280)
    notice = ft.Text()
    status = ft.Text("Ready", selectable=True)
    details = ft.Text(selectable=True)
    progress = ft.ProgressBar(value=0, visible=False)
    log = ft.TextField(label="Job activity log (last 32 KiB)", multiline=True, read_only=True,
                       min_lines=4, max_lines=14)
    jobs = ft.Dropdown(label="Job history (persisted across sessions and service restarts)")
    initialized = False
    selected: str | None = None
    disconnected = False
    poll_task: Future[None] | None = None
    fields = [selection, ids, destination, source_type, source, omeka_output, field_map, legacy, start, limit, prefix]

    def values() -> dict[str, str]:
        return dict(selection=selection.value or "", mms_ids=ids.value or "",
                    destination=destination.value or "", source=source.value or "",
                    source_type=source_type.value or "alma", omeka_output=omeka_output.value or "",
                    field_map=field_map.value or "", legacy_mods=legacy.value or "",
                    start=start.value or "1", limit=limit.value or "", prefix=prefix.value or "")

    def error(exc: Exception) -> None:
        notice.value = str(exc)
        notice.color = ft.Colors.RED_700

    def submit(kind: str) -> None:
        try:
            job_id = service.submit(session, kind, values())
            notice.value = f"Submitted {kind} job {job_id}. Closing the tab will not stop it."
            notice.color = ft.Colors.GREEN_800
            page.go(f"/jobs/{job_id}")
        except (OSError, ValueError, RuntimeError) as exc:
            error(exc)
        refresh()

    def cancel(_: ft.ControlEvent) -> None:
        try:
            service.cancel(session)
        except (OSError, ValueError) as exc:
            error(exc)
        refresh()

    retrieve_button = ft.FilledButton("1) Retrieve from Alma and Save JSON Manifest",
                                     on_click=lambda _: submit("retrieve"))
    export_button = ft.FilledButton("2) Map and Export Manifest to CSV", on_click=lambda _: submit("export"))
    cancel_button = ft.ElevatedButton("Cancel active job", on_click=cancel, disabled=True)

    def route_changed(_: ft.RouteChangeEvent | None) -> None:
        nonlocal selected
        parts = page.route.strip("/").split("/")
        selected = parts[1] if len(parts) == 2 and parts[0] == "jobs" else None
        refresh()

    jobs.on_change = lambda _: page.go(f"/jobs/{jobs.value}")
    page.on_route_change = route_changed

    def read_log(_: ft.ControlEvent) -> None:
        try:
            log.value = service.log_tail(selected) if selected else "Select a job."
        except (OSError, ValueError) as exc:
            error(exc)
        page.update()

    def use_manifest(_: ft.ControlEvent) -> None:
        if not service.claim(session):
            error(ValueError("Another browser session is the active operator."))
        else:
            job = next((job for job in service.jobs() if job["id"] == selected), None)
            if job and job["result"].get("manifest"):
                source.value = job["result"]["manifest"]
                source_type.value = "alma"
        refresh()

    use_button = ft.TextButton("Use this retrieved manifest for step 2", on_click=use_manifest, disabled=True)

    def refresh() -> None:
        nonlocal selected, initialized
        history = service.jobs()
        operator = service.claim(session)
        busy = any(job["state"] in ACTIVE for job in history)
        for control in fields:
            control.disabled = not operator or busy or bool(service.storage_error)
        omeka = source_type.value == "omeka"
        omeka_output.visible = omeka
        legacy.disabled = prefix.disabled = legacy.disabled or omeka
        source.label = "Omeka JSON export (server path)" if omeka else "Prepared manifest (server JSON or CSV path)"
        retrieve_button.disabled = export_button.disabled = not operator or busy or bool(service.storage_error)
        cancel_button.disabled = not operator or not busy or bool(service.storage_error)
        if not operator:
            notice.value = "Read-only session: another browser tab is the active operator."
        elif service.storage_error:
            notice.value = service.storage_error
            notice.color = ft.Colors.RED_700
        elif notice.value == "Read-only session: another browser tab is the active operator.":
            notice.value = "This browser is now the active operator."
        jobs.options = [ft.dropdown.Option(job["id"], f"{job['created_at']} | {job['kind']} | {job['state']}")
                        for job in history]
        if not initialized and selected is None and history:
            selected = history[0]["id"]
        initialized = True
        jobs.value = selected
        job = next((job for job in history if job["id"] == selected), None)
        use_button.disabled = not operator or busy or not job or not job["result"].get("manifest")
        if job:
            status.value = f"{job['id']} | {job['state']}: {job['message']}"
            status.color = ft.Colors.RED_700 if job["state"] in {"failed", "interrupted"} else None
            details.value = json.dumps(job["result"], indent=2)
            progress.visible = job["state"] in ACTIVE
            progress.value = job["progress"]
        else:
            status.value = "Unknown job." if selected else "Ready"
            details.value = ""
            progress.visible = False
        page.update()

    async def poll() -> None:
        while not disconnected:
            await asyncio.sleep(1)
            if not disconnected:
                refresh()

    def disconnect(_: ft.ControlEvent) -> None:
        nonlocal disconnected
        disconnected = True
        service.release(session)
        if poll_task is not None:
            poll_task.cancel()

    def connect(_: ft.ControlEvent) -> None:
        nonlocal disconnected, poll_task
        was_disconnected = disconnected
        disconnected = False
        refresh()
        if was_disconnected:
            poll_task = page.run_task(poll)

    page.on_disconnect = disconnect
    page.on_close = disconnect
    page.on_connect = connect
    source_type.on_change = lambda _: refresh()
    page.add(ft.Column(scroll=ft.ScrollMode.AUTO, expand=True, controls=[
        ft.Text("GEMS - Linux/Web", size=30, weight=ft.FontWeight.BOLD),
        ft.Text("Private single-operator service. Paths refer to mounted server storage, not your workstation."),
        ft.Text(f"Configuration: {service.storage.config}\nData: {service.storage.data}", selectable=True),
        notice, ft.Divider(), ft.Text("Retrieve from Alma", size=20), selection, ids, destination, retrieve_button,
        ft.Divider(), ft.Text("Map Manifest to CSV", size=20), source_type, source, omeka_output, field_map, legacy,
        ft.Row([start, limit, prefix], wrap=True), export_button, ft.Divider(),
        jobs, status, progress, details, use_button, cancel_button,
        ft.TextButton("Refresh job log", on_click=read_log), log,
        ft.Text("Jobs survive tab closure. On service restart, unfinished jobs become interrupted; review partial output before retrying."),
    ]))
    route_changed(None)
    poll_task = page.run_task(poll)


def launch(*, port: int = 8550) -> None:
    if importlib.util.find_spec("flet_web") is None:
        raise RuntimeError("Web runtime is missing. Install it with ./run.sh --install --web.")
    if os.getenv("FLET_SERVER_IP", "127.0.0.1") != "127.0.0.1":
        raise ValueError("Web mode only supports loopback access. Use an SSH tunnel or authenticated reverse proxy.")
    os.environ["FLET_SERVER_IP"] = "127.0.0.1"
    os.environ["FLET_SERVER_PORT"] = str(port)
    os.umask(0o077)
    storage = Storage.from_environment()
    service = JobService(storage)
    try:
        ft.app(target=lambda page: main(page, service), host="127.0.0.1", port=port, view=None,
               assets_dir=str(Path(__file__).parent / "_web_assets"))
    finally:
        service.close()
