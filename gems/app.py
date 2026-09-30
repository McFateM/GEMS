from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import flet as ft
from dotenv import load_dotenv

from .alma import AlmaClient
from .pipeline import process_export

APP_TITLE = "GEMS - Gather, Export, Map, Serialize"
DATA_DIR = Path.home() / ".GEMS-data"
SETTINGS_PATH = DATA_DIR / "settings.json"
LOG_PATH = DATA_DIR / "logfiles" / "gems.log"


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
        handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
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
        hint_text="Folder for CollectionBuilder metadata and objects",
        value=settings.get("output_path", ""),
        expand=True,
    )
    mapping_field = ft.TextField(
        label="Field map (optional JSON file)",
        hint_text="Choose a JSON field map",
        value=settings.get("field_map_path", ""),
        read_only=True,
        expand=True,
    )
    alma_set_field = ft.TextField(
        label="Alma Set ID or Collection Title",
        hint_text="Retrieve an Alma set by ID or exact title",
        value=settings.get("alma_set_selection", settings.get("alma_set_id", "")),
        expand=True,
    )
    alma_ids_field = ft.TextField(
        label="MMS IDs",
        hint_text="Optional: comma-separated MMS IDs",
        value=settings.get("alma_mms_ids", ""),
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
                "output_path": output_field.value or "",
                "field_map_path": mapping_field.value or "",
                "alma_set_selection": alma_set_field.value or "",
                "alma_mms_ids": alma_ids_field.value or "",
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

    def on_manifest_save(event: ft.FilePickerResultEvent) -> None:
        nonlocal run_log_handler, active_log_path
        if not event.path:
            return
        try:
            report("Saving Alma manifest...")
            slug = re.sub(r"[^a-z0-9]+", "-", retrieved_title.lower()).strip("-")[:40].strip("-") or "collection"
            run_name = f"gems_{slug}_{manifest_created_at:%Y%m%dT%H%M%S%fZ}"
            run_dir = Path(event.path) / run_name
            suffix = 1
            while True:
                try:
                    run_dir.mkdir()
                    break
                except FileExistsError:
                    run_dir = Path(event.path) / f"{run_name}-{suffix}"
                    suffix += 1
            manifest_path = run_dir / f"{run_dir.name}.json"
            payload = {
                "collection_title": retrieved_title,
                "created_at": manifest_created_at.isoformat(),
                "records": alma_records,
            }
            if retrieved_set_id:
                payload["alma_set_id"] = retrieved_set_id
            manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            handler = logging.FileHandler(run_dir / "gems.log", encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
            close_run_log()
            logger.addHandler(handler)
            run_log_handler = handler
            active_log_path = run_dir / "gems.log"
            logger.info("Manifest contains %s Alma record(s) from %s", len(alma_records), retrieved_set_id or "MMS IDs")
            source_field.value = str(manifest_path)
            output_field.value = str(run_dir)
            update_settings()
            report(f"Saved {len(alma_records)} Alma record(s) to {run_dir}. Ready to map and export.", success=True)
        except Exception as exc:  # pragma: no cover - UI feedback wrapper
            report(f"Alma manifest export failed: {exc}", error=True)

    source_picker = ft.FilePicker(on_result=on_source_pick)
    output_picker = ft.FilePicker(on_result=on_output_pick)
    mapping_picker = ft.FilePicker(on_result=on_mapping_pick)
    manifest_picker = ft.FilePicker(on_result=on_manifest_save)
    page.overlay.extend([source_picker, output_picker, mapping_picker, manifest_picker])

    def load_field_map() -> dict[str, str]:
        field_map = json.loads(Path(mapping_field.value).read_text(encoding="utf-8")) if mapping_field.value else {}
        if not isinstance(field_map, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in field_map.items()
        ):
            raise ValueError("The field map must be a JSON object with string field names and values.")
        return field_map

    def run_export(_: ft.ControlEvent) -> None:
        try:
            report("Mapping and exporting manifest...")
            if not source_field.value or not output_field.value:
                raise ValueError("Choose both an export file and a destination folder.")
            field_map = load_field_map()
            result = process_export(
                Path(source_field.value),
                Path(output_field.value),
                field_map=field_map,
            )
            update_settings()
            report(
                f"Export complete: {result.row_count} metadata row(s), {result.file_count} file(s). "
                f"Results saved to {result.csv_path.parent}",
                success=True,
            )
        except Exception as exc:  # pragma: no cover - UI feedback wrapper
            report(f"Export failed: {exc}", error=True)

    def fetch_alma_records(_: ft.ControlEvent) -> None:
        nonlocal alma_records, retrieved_title, retrieved_set_id
        try:
            close_run_log()
            report("Retrieving Alma records...")
            alma_records = []
            retrieved_title = ""
            retrieved_set_id = ""
            client = AlmaClient()
            mms_ids = [value.strip() for value in (alma_ids_field.value or "").replace(",", "\n").splitlines()]
            if mms_ids:
                set_id = ""
                title = "MMS ID selection"
            else:
                selection = (alma_set_field.value or "").strip()
                if not selection:
                    raise ValueError("Enter an Alma set ID, collection title, or at least one MMS ID.")
                set_id, title = client.resolve_set(selection)
                mms_ids = client.fetch_set_members(set_id)
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
            update_settings()
            report(f"Retrieved {len(alma_records)} Alma record(s). Ready to export.", success=True)
        except Exception as exc:  # pragma: no cover - UI feedback wrapper
            report(f"Alma retrieval failed: {exc}", error=True)

    def export_alma_records(_: ft.ControlEvent) -> None:
        nonlocal manifest_created_at
        try:
            if not alma_records:
                raise ValueError("Retrieve Alma records before exporting.")
            close_run_log()
            manifest_created_at = datetime.now(timezone.utc)
            report("Choose a parent folder for the Alma export...")
            manifest_picker.get_directory_path(dialog_title="Choose a parent folder for the Alma export")
        except Exception as exc:  # pragma: no cover - UI feedback wrapper
            report(f"Alma manifest export failed: {exc}", error=True)

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
                    ft.Row([alma_set_field, ft.FilledButton("Retrieve", icon=ft.Icons.DOWNLOAD, on_click=fetch_alma_records)]),
                    alma_ids_field,
                    ft.FilledButton(
                        "1) Export Alma Records to JSON Manifest",
                        icon=ft.Icons.ARCHIVE,
                        on_click=export_alma_records,
                    ),
                    ft.Divider(),
                    ft.Text("Export", size=20, weight=ft.FontWeight.W_600),
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
                            output_field,
                            ft.IconButton(
                                icon=ft.Icons.FOLDER_OPEN,
                                tooltip="Choose destination folder",
                                on_click=lambda _: output_picker.get_directory_path(),
                            ),
                        ]
                    ),
                    ft.Divider(),
                    ft.Text("Metadata mapping", size=20, weight=ft.FontWeight.W_600),
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
                    ft.IconButton(icon=ft.Icons.RECEIPT_LONG, tooltip="View activity log", on_click=view_log),
                ],
            ),
            padding=ft.padding.symmetric(horizontal=24, vertical=8),
            bgcolor=ft.Colors.GREY_100,
        )
    )


def launch() -> None:
    ft.app(target=main)
