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
        label="Alma set ID",
        hint_text="Optional: retrieve all MMS IDs in an Alma set",
        value=settings.get("alma_set_id", ""),
        expand=True,
    )
    collection_title_field = ft.TextField(
        label="Collection title",
        hint_text="Required for MMS IDs; defaults to Alma set name",
        value=settings.get("collection_title", ""),
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

    def view_log(_: ft.ControlEvent) -> None:
        try:
            dialog = ft.AlertDialog(
                title=ft.Text(f"Activity log: {LOG_PATH}"),
                content=ft.Container(
                    content=ft.TextField(value=LOG_PATH.read_text(encoding="utf-8"), multiline=True, read_only=True),
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
                "alma_set_id": alma_set_field.value or "",
                "collection_title": collection_title_field.value or "",
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
        if not event.path:
            return
        try:
            report("Saving Alma manifest...")
            manifest_path = Path(event.path)
            if manifest_path.suffix.lower() != ".json":
                raise ValueError("Choose a .json filename for the Alma manifest.")
            payload = {
                "collection_title": retrieved_title,
                "created_at": manifest_created_at.isoformat(),
                "records": alma_records,
            }
            if retrieved_set_id:
                payload["alma_set_id"] = retrieved_set_id
            manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            source_field.value = str(manifest_path)
            update_settings()
            report(f"Saved {len(alma_records)} Alma record(s) to {manifest_path}. Ready to map and export.", success=True)
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
            report("Retrieving Alma records...")
            alma_records = []
            retrieved_title = ""
            retrieved_set_id = ""
            client = AlmaClient()
            mms_ids = [value.strip() for value in (alma_ids_field.value or "").replace(",", "\n").splitlines()]
            set_id = (alma_set_field.value or "").strip()
            title = (collection_title_field.value or "").strip()
            if set_id:
                if not title:
                    title = client.fetch_set_title(set_id)
                mms_ids.extend(client.fetch_set_members(set_id))
            if not title:
                raise ValueError("Enter a collection title when retrieving MMS IDs without an Alma set.")
            if not mms_ids:
                raise ValueError("Enter an Alma set ID or at least one MMS ID.")
            alma_records = client.fetch_records(mms_ids)
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
            manifest_created_at = datetime.now(timezone.utc)
            slug = re.sub(r"[^a-z0-9]+", "-", retrieved_title.lower()).strip("-")[:40].strip("-") or "collection"
            report("Choose where to save the Alma manifest...")
            manifest_picker.save_file(
                dialog_title="Save Alma records as JSON manifest",
                file_name=f"gems_{slug}_{manifest_created_at:%Y%m%dT%H%M%SZ}.json",
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["json"],
            )
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
                    collection_title_field,
                    alma_ids_field,
                    ft.OutlinedButton(
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
