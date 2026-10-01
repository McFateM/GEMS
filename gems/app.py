from __future__ import annotations

import json
import logging
import re
from hashlib import sha256
from datetime import datetime
from pathlib import Path
from typing import Any

import flet as ft
from dotenv import load_dotenv

from .alma import AlmaClient
from .pipeline import is_template_map, process_export

APP_TITLE = "GEMS - Gather, Export, Map, Serialize"
DATA_DIR = Path.home() / ".GEMS-data"
SETTINGS_PATH = DATA_DIR / "settings.json"
LOG_PATH = DATA_DIR / "logfiles" / "gems.log"
LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S %Z"


def configure_logging() -> logging.Logger:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in logger.handlers[:]:
        if isinstance(handler, logging.FileHandler) and handler.baseFilename != str(LOG_PATH):
            logger.removeHandler(handler)
            handler.close()
    if not any(isinstance(handler, logging.FileHandler) and handler.baseFilename == str(LOG_PATH) for handler in logger.handlers):
        handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
        handler.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))
        logger.addHandler(handler)
    return logger


def load_settings() -> dict[str, str]:
    try:
        settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return settings if isinstance(settings, dict) else {}


def save_settings(settings: dict[str, str]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")


def main(page: ft.Page) -> None:
    load_dotenv()
    settings = load_settings()
    logger = configure_logging()
    logger.info("GEMS started")
    alma_records: list[dict] = []
    retrieved_title = ""
    retrieved_set_id = ""
    retrieved_collection_id = ""
    retrieved_total = 0
    retrieved_group = ""
    manifest_created_at: datetime | None = None
    run_log_handler: logging.FileHandler | None = None
    active_log_path = LOG_PATH

    page.title = APP_TITLE
    page.theme_mode = ft.ThemeMode.LIGHT
    page.theme = ft.Theme(color_scheme_seed=ft.Colors.TEAL)
    page.padding = 0
    page.window.width = 920
    page.window.height = 1000
    page.window.min_width = 720
    page.window.min_height = 560

    source_field = ft.TextField(
        label="Prepared export manifest",
        hint_text="JSON or CSV metadata with local paths or accessible object URLs",
        value=settings.get("source_path", ""),
        expand=True,
    )
    output_field = ft.TextField(
        label="Destination folder",
        hint_text="e.g. /Volumes/DGIngest/.GEMS-data; subfolders are named from the set, collection, or MMS IDs",
        value=settings.get("export_root_path", ""),
        on_change=lambda _: update_settings(),
        expand=True,
    )
    mapping_field = ft.TextField(
        label="Field map (optional JSON file)",
        hint_text="Choose a JSON field map",
        value=settings.get("field_map_path", ""),
        read_only=True,
        expand=True,
    )
    legacy_mods_field = ft.TextField(
        label="Legacy MODS folder (optional)",
        hint_text="e.g. DG-Exports; only fills fields that are empty in Alma",
        value=settings.get("legacy_mods_path", ""),
        on_change=lambda _: update_settings(),
        expand=True,
    )
    alma_set_field = ft.TextField(
        label="Alma Set ID or Collection Title",
        hint_text="Numeric set ID or exact collection title",
        value=settings.get("alma_set_selection", ""),
        on_change=lambda _: update_settings(),
        expand=True,
    )
    alma_ids_field = ft.TextField(
        label="MMS IDs",
        hint_text="Optional: comma-separated MMS IDs",
        value=settings.get("alma_mms_ids", ""),
    )
    start_field = ft.TextField(
        label="Start record",
        value=settings.get("start_record", "1"),
        on_change=lambda _: update_settings(),
        keyboard_type=ft.KeyboardType.NUMBER,
        width=160,
    )
    limit_field = ft.TextField(
        label="Record limit",
        hint_text="All",
        value=settings.get("record_limit", ""),
        on_change=lambda _: update_settings(),
        keyboard_type=ft.KeyboardType.NUMBER,
        width=160,
    )
    prefix_field = ft.TextField(
        label="ObjectID prefix",
        hint_text="Site slug for new objectids, e.g. ghm; blank uses the manifest's",
        value=settings.get("objectid_prefix", ""),
        on_change=lambda _: update_settings(),
        width=320,
    )
    status = ft.Text("Ready", expand=True)

    def report(message: str, *, error: bool = False, success: bool = False) -> None:
        status.value = message
        status.color = ft.Colors.RED_700 if error else ft.Colors.GREEN_800 if success else ft.Colors.BLACK87
        if error:
            logger.exception(message)
        else:
            logger.info(message)
        page.update()

    def close_run_log() -> None:
        nonlocal run_log_handler, active_log_path
        if run_log_handler is not None:
            logger.removeHandler(run_log_handler)
            run_log_handler.close()
            run_log_handler = None
            active_log_path = LOG_PATH

    def view_log(_: ft.ControlEvent) -> None:
        try:
            dialog = ft.AlertDialog(
                title=ft.Text(f"Activity log: {active_log_path}"),
                content=ft.Container(
                    content=ft.TextField(value=active_log_path.read_text(encoding="utf-8"), multiline=True, read_only=True),
                    width=720,
                    height=420,
                ),
                actions=[ft.TextButton("Close", on_click=lambda _: close_log(dialog))],
            )
            page.overlay.append(dialog)
            dialog.open = True
            page.update()
        except OSError as exc:
            report(f"Could not open activity log: {exc}", error=True)

    def close_log(dialog: ft.AlertDialog) -> None:
        dialog.open = False
        page.update()

    def update_settings() -> None:
        save_settings(
            {
                "source_path": source_field.value or "",
                "field_map_path": mapping_field.value or "",
                "legacy_mods_path": legacy_mods_field.value or "",
                "alma_set_selection": alma_set_field.value or "",
                "alma_mms_ids": alma_ids_field.value or "",
                "start_record": start_field.value or "1",
                "record_limit": limit_field.value or "",
                "objectid_prefix": prefix_field.value or "",
                "export_root_path": output_field.value or "",
            }
        )

    def on_source_pick(event: ft.FilePickerResultEvent) -> None:
        if event.files:
            source_field.value = event.files[0].path
            update_settings()
            report(f"Selected manifest: {source_field.value}")

    def on_output_pick(event: ft.FilePickerResultEvent) -> None:
        if event.path:
            output_field.value = event.path
            update_settings()
            report(f"Selected destination: {output_field.value}")

    def on_mapping_pick(event: ft.FilePickerResultEvent) -> None:
        if event.files:
            mapping_field.value = event.files[0].path
            update_settings()
            report(f"Selected field map: {mapping_field.value}")

    def clear_mapping(_: ft.ControlEvent) -> None:
        mapping_field.value = ""
        update_settings()
        report("Field map cleared")

    def on_legacy_mods_pick(event: ft.FilePickerResultEvent) -> None:
        if event.path:
            legacy_mods_field.value = event.path
            update_settings()
            report(f"Selected legacy MODS folder: {legacy_mods_field.value}")

    def destination_root() -> Path:
        raw = (output_field.value or "").strip()
        if not raw or not Path(raw).is_dir():
            raise ValueError("Choose an existing destination folder before using button 1.")
        return Path(raw)

    def save_retrieved_manifest(parent: Path, note: str = "") -> bool:
        nonlocal run_log_handler, active_log_path
        report("Saving Alma manifest...")
        try:
            slug = re.sub(r"[^a-z0-9]+", "-", retrieved_title.lower()).strip("-")[:40].strip("-") or "collection"
            group_dir = parent / retrieved_group
            group_dir.mkdir(exist_ok=True)
            run_name = f"{manifest_created_at:%Y-%m-%d_%H-%M-%S_%Z}"
            run_dir = group_dir / run_name
            suffix = 1
            while True:
                try:
                    run_dir.mkdir()
                    break
                except FileExistsError:
                    run_dir = group_dir / f"{run_name}-{suffix}"
                    suffix += 1
            manifest_path = run_dir / f"gems_{slug}_{run_dir.name}.json"
            payload = {
                "collection_title": retrieved_title,
                "created_at": manifest_created_at.isoformat(),
                "retrieval": {
                    "available_records": retrieved_total,
                },
                "records": alma_records,
            }
            if retrieved_set_id:
                payload["alma_set_id"] = retrieved_set_id
            if retrieved_collection_id:
                payload["alma_collection_pid"] = retrieved_collection_id
            manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            handler = logging.FileHandler(run_dir / "gems.log", encoding="utf-8")
            handler.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))
            close_run_log()
            logger.addHandler(handler)
            run_log_handler = handler
            active_log_path = run_dir / "gems.log"
            logger.info(
                "Manifest contains %s Alma record(s) from %s",
                len(alma_records), retrieved_set_id or retrieved_collection_id or "MMS IDs",
            )
            source_field.value = str(manifest_path)
            update_settings()
            report(f"Saved {len(alma_records)} Alma record(s) to {run_dir}. Ready to map and export.{note}", success=True)
            return True
        except Exception as exc:  # pragma: no cover - UI feedback wrapper
            report(f"Alma manifest export failed: {exc}", error=True)
            return False

    source_picker = ft.FilePicker(on_result=on_source_pick)
    output_picker = ft.FilePicker(on_result=on_output_pick)
    mapping_picker = ft.FilePicker(on_result=on_mapping_pick)
    legacy_mods_picker = ft.FilePicker(on_result=on_legacy_mods_pick)
    page.overlay.extend([source_picker, output_picker, mapping_picker, legacy_mods_picker])

    def load_field_map() -> dict[str, Any]:
        field_map = json.loads(Path(mapping_field.value).read_text(encoding="utf-8")) if mapping_field.value else {}
        if is_template_map(field_map):
            if not isinstance(field_map.get("rules", {}), dict):
                raise ValueError("A template field map's \"rules\" must be a JSON object keyed by column name.")
            return field_map
        if not isinstance(field_map, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in field_map.items()
        ):
            raise ValueError("The field map must be a template map or a JSON object with string field names and values.")
        return field_map

    def run_export(_: ft.ControlEvent) -> None:
        try:
            report("Mapping and exporting manifest...")
            if not source_field.value:
                raise ValueError("Choose a prepared export manifest.")
            try:
                start = int(start_field.value or "")
            except ValueError as exc:
                raise ValueError("Start record must be a positive whole number.") from exc
            if start < 1:
                raise ValueError("Start record must be a positive whole number.")
            try:
                limit = int(limit_field.value) if limit_field.value else None
            except ValueError as exc:
                raise ValueError("Record limit must be a positive whole number.") from exc
            if limit is not None and limit < 1:
                raise ValueError("Record limit must be a positive whole number.")
            field_map = load_field_map()
            manifest_path = Path(source_field.value)
            legacy_mods = (legacy_mods_field.value or "").strip()
            if legacy_mods and not Path(legacy_mods).is_dir():
                raise ValueError(f"Legacy MODS folder not found: {legacy_mods}")
            result = process_export(
                manifest_path,
                manifest_path.parent,
                field_map=field_map,
                legacy_mods_dir=legacy_mods or None,
                start=start,
                limit=limit,
                refresh_source=AlmaClient().refresh_file_link,
                objectid_prefix=(prefix_field.value or "").strip() or None,
                page=page,
            )
            update_settings()
            for name in result.renamed_files:
                logger.warning("Renamed to avoid a filename clash with a different Alma file: %s", name)
            renamed_note = (
                f" {len(result.renamed_files)} file(s) shared a name with a different file and were saved with their "
                "Alma file ID appended; see the activity log."
                if result.renamed_files else ""
            )
            report(
                f"Mapped records {result.first_record}–{result.last_record} of {result.total_records}: "
                f"{result.file_count} file(s); CSV now has {result.row_count} row(s). "
                f"Results saved to {result.csv_path.parent}.{renamed_note}",
                success=True,
            )
        except Exception as exc:  # pragma: no cover - UI feedback wrapper
            report(f"Export failed: {exc}", error=True)

    def fetch_alma_records(_: ft.ControlEvent) -> None:
        nonlocal alma_records, retrieved_title, retrieved_set_id, retrieved_collection_id
        nonlocal retrieved_total, retrieved_group, manifest_created_at
        try:
            # Check the destination first so a long retrieval is never left unsaved.
            root = destination_root()
            close_run_log()
            report("Retrieving Alma records...")
            alma_records = []
            retrieved_title = ""
            retrieved_set_id = ""
            retrieved_collection_id = ""
            retrieved_group = ""
            client = AlmaClient()
            mms_ids = [value.strip() for value in (alma_ids_field.value or "").replace(",", "\n").splitlines()]
            if mms_ids:
                set_id = ""
                title = "MMS ID selection"
            else:
                selection = (alma_set_field.value or "").strip()
                if not selection:
                    raise ValueError("Enter an Alma set ID, collection title, or at least one MMS ID.")
                if selection.isdecimal():
                    set_id = selection
                    title = client.fetch_set_title(set_id)
                    mms_ids = client.fetch_set_members(set_id)
                else:
                    set_id = ""
                    retrieved_collection_id, title = client.resolve_collection(selection)
                    mms_ids = client.fetch_collection_bibs(retrieved_collection_id)
                    for error in client.skipped_errors:
                        logger.warning("Skipped collection entry: %s", error)
            mms_ids = list(dict.fromkeys(value.strip() for value in mms_ids if value.strip()))
            if not mms_ids:
                raise ValueError("No Alma records were found for that selection.")
            total = len(mms_ids)
            slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40].strip("-") or "collection"
            if set_id:
                group = f"set-{slug}-{set_id}"
            elif retrieved_collection_id:
                group = f"collection-{slug}-{retrieved_collection_id}"
            else:
                digest = sha256(",".join(sorted(mms_ids)).encode("utf-8")).hexdigest()[:12]
                group = f"mms-ids-{digest}"
            last_milestone = 0

            def update_progress(completed: int, total: int) -> None:
                nonlocal last_milestone
                milestone = completed * 10 // total
                if milestone > last_milestone:
                    last_milestone = milestone
                    report(f"Retrieving Alma records: {milestone * 10}% ({completed}/{total})")

            alma_records = client.fetch_records(mms_ids, on_progress=update_progress)
            retrieved_title = title
            retrieved_set_id = set_id
            retrieved_total = total
            retrieved_group = group
            note = ""
            skipped = list(client.skipped_positions)
            if skipped:
                positions = ", ".join(str(position) for position in skipped)
                note = (
                    f" Alma could not list {len(skipped)} collection entr"
                    f"{'y' if len(skipped) == 1 else 'ies'} (position {positions}); "
                    "they were skipped. See the activity log for Alma tracking IDs."
                )
            manifest_created_at = datetime.now().astimezone()
            if not save_retrieved_manifest(root, note):
                fallback = DATA_DIR / "unsaved-manifests"
                fallback.mkdir(parents=True, exist_ok=True)
                save_retrieved_manifest(fallback, f"{note} The destination {root} could not be written, so it was saved locally.")
        except Exception as exc:  # pragma: no cover - UI feedback wrapper
            report(f"Alma retrieval failed: {exc}", error=True)

    page.add(
        ft.Container(
            expand=True,
            padding=24,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text("GEMS", size=32, weight=ft.FontWeight.BOLD),
                    ft.Text("Gather, export, map, and serialize digital collection records."),
                    ft.Divider(),
                    ft.Text("Retrieve from Alma", size=20, weight=ft.FontWeight.W_600),
                    alma_set_field,
                    alma_ids_field,
                    ft.Row(
                        [
                            output_field,
                            ft.IconButton(
                                icon=ft.Icons.FOLDER_OPEN,
                                tooltip="Choose destination folder",
                                on_click=lambda _: output_picker.get_directory_path(
                                    initial_directory=output_field.value or None,
                                ),
                            ),
                        ]
                    ),
                    ft.FilledButton(
                        "1) Retrieve from Alma and Save JSON Manifest",
                        icon=ft.Icons.DOWNLOAD,
                        on_click=fetch_alma_records,
                    ),
                    ft.Divider(),
                    ft.Text("Map Manifest to CSV", size=20, weight=ft.FontWeight.W_600),
                    ft.Row(
                        [
                            source_field,
                            ft.IconButton(
                                icon=ft.Icons.UPLOAD_FILE,
                                tooltip="Choose prepared export manifest",
                                on_click=lambda _: source_picker.pick_files(
                                    allow_multiple=False,
                                    allowed_extensions=["json", "csv"],
                                ),
                            ),
                        ]
                    ),
                    ft.Row(
                        [
                            mapping_field,
                            ft.IconButton(
                                icon=ft.Icons.UPLOAD_FILE,
                                tooltip="Choose JSON field map",
                                on_click=lambda _: mapping_picker.pick_files(
                                    allow_multiple=False,
                                    allowed_extensions=["json"],
                                ),
                            ),
                            ft.IconButton(
                                icon=ft.Icons.CLEAR,
                                tooltip="Clear field map",
                                on_click=clear_mapping,
                            ),
                        ]
                    ),
                    ft.Row(
                        [
                            legacy_mods_field,
                            ft.IconButton(
                                icon=ft.Icons.FOLDER_OPEN,
                                tooltip="Choose legacy MODS folder",
                                on_click=lambda _: legacy_mods_picker.get_directory_path(
                                    initial_directory=legacy_mods_field.value or None,
                                ),
                            ),
                        ]
                    ),
                    ft.Row([start_field, limit_field, prefix_field]),
                    ft.Row(
                        [
                            ft.FilledButton(
                                "2) Map and Export Manifest to CSV",
                                icon=ft.Icons.PLAY_ARROW,
                                on_click=run_export,
                            ),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
            ),
        )
    )
    page.add(
        ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.INFO_OUTLINE),
                    status,
                    ft.IconButton(
                        icon=ft.Icons.COPY,
                        tooltip="Copy status",
                        on_click=lambda _: page.set_clipboard(status.value or ""),
                    ),
                    ft.IconButton(icon=ft.Icons.RECEIPT_LONG, tooltip="View activity log", on_click=view_log),
                ],
            ),
            padding=ft.padding.symmetric(horizontal=24, vertical=8),
            bgcolor=ft.Colors.GREY_100,
        )
    )


def launch() -> None:
    ft.app(target=main)
