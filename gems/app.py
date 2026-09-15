from __future__ import annotations

import json
from pathlib import Path

import flet as ft
from dotenv import load_dotenv

from .alma import AlmaClient
from .pipeline import process_export, process_records

APP_TITLE = "GEMS - Gather, Export, Map, Serialize"
DATA_DIR = Path.home() / ".GEMS-data"
SETTINGS_PATH = DATA_DIR / "settings.json"


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
    alma_records: list[dict] = []

    page.title = APP_TITLE
    page.theme_mode = ft.ThemeMode.LIGHT
    page.theme = ft.Theme(color_scheme_seed=ft.Colors.TEAL)
    page.padding = 0
    page.window.width = 920
    page.window.height = 700
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
    source_system = ft.Dropdown(
        label="Source system",
        value=settings.get("source_system", "alma_digital"),
        options=[
            ft.dropdown.Option("alma_digital", "Alma Digital"),
            ft.dropdown.Option("specto", "Specto"),
        ],
        width=210,
    )
    mapping_field = ft.TextField(
        label="Field map (optional JSON)",
        hint_text='{"title": "display title", "creator": "creator name"}',
        value=settings.get("field_map", "{}"),
        multiline=True,
        min_lines=4,
        max_lines=8,
    )
    alma_set_field = ft.TextField(
        label="Alma set ID",
        hint_text="Optional: retrieve all MMS IDs in an Alma set",
        value=settings.get("alma_set_id", ""),
        expand=True,
    )
    alma_ids_field = ft.TextField(
        label="MMS IDs",
        hint_text="Optional: one MMS ID per line or comma-separated",
        value=settings.get("alma_mms_ids", ""),
        multiline=True,
        min_lines=2,
        max_lines=4,
    )
    status = ft.Text("Choose an export file and destination folder.")

    def update_settings() -> None:
        save_settings(
            {
                "source_path": source_field.value or "",
                "output_path": output_field.value or "",
                "source_system": source_system.value or "alma_digital",
                "field_map": mapping_field.value or "{}",
                "alma_set_id": alma_set_field.value or "",
                "alma_mms_ids": alma_ids_field.value or "",
            }
        )

    def on_source_pick(event: ft.FilePickerResultEvent) -> None:
        if event.files:
            source_field.value = event.files[0].path
            update_settings()
            page.update()

    def on_output_pick(event: ft.FilePickerResultEvent) -> None:
        if event.path:
            output_field.value = event.path
            update_settings()
            page.update()

    source_picker = ft.FilePicker(on_result=on_source_pick)
    output_picker = ft.FilePicker(on_result=on_output_pick)
    page.overlay.extend([source_picker, output_picker])

    def run_export(_: ft.ControlEvent) -> None:
        try:
            if not source_field.value or not output_field.value:
                raise ValueError("Choose both an export file and a destination folder.")
            field_map = json.loads(mapping_field.value or "{}")
            if not isinstance(field_map, dict) or not all(
                isinstance(key, str) and isinstance(value, str) for key, value in field_map.items()
            ):
                raise ValueError("The field map must be a JSON object with string field names and values.")
            result = process_export(
                Path(source_field.value),
                Path(output_field.value),
                field_map=field_map,
                source_system=source_system.value or "alma_digital",
            )
            update_settings()
            status.value = (
                f"Export complete: {result.row_count} metadata row(s), {result.file_count} file(s). "
                f"Results saved to {result.csv_path.parent}"
            )
            status.color = ft.Colors.GREEN_800
        except Exception as exc:  # pragma: no cover - UI feedback wrapper
            status.value = f"Export failed: {exc}"
            status.color = ft.Colors.RED_700
        page.update()

    def fetch_alma_records(_: ft.ControlEvent) -> None:
        nonlocal alma_records
        try:
            client = AlmaClient()
            mms_ids = [value.strip() for value in (alma_ids_field.value or "").replace(",", "\n").splitlines()]
            if alma_set_field.value:
                mms_ids.extend(client.fetch_set_members(alma_set_field.value.strip()))
            if not mms_ids:
                raise ValueError("Enter an Alma set ID or at least one MMS ID.")
            alma_records = client.fetch_records(mms_ids)
            update_settings()
            status.value = f"Retrieved {len(alma_records)} Alma record(s). Ready to export."
            status.color = ft.Colors.GREEN_800
        except Exception as exc:  # pragma: no cover - UI feedback wrapper
            status.value = f"Alma retrieval failed: {exc}"
            status.color = ft.Colors.RED_700
        page.update()

    def export_alma_records(_: ft.ControlEvent) -> None:
        try:
            if not alma_records:
                raise ValueError("Retrieve Alma records before exporting.")
            if not output_field.value:
                raise ValueError("Choose a destination folder.")
            field_map = json.loads(mapping_field.value or "{}")
            result = process_records(alma_records, Path(output_field.value), field_map=field_map)
            status.value = f"Export complete: {result.row_count} metadata row(s), {result.file_count} file(s)."
            status.color = ft.Colors.GREEN_800
        except Exception as exc:  # pragma: no cover - UI feedback wrapper
            status.value = f"Alma export failed: {exc}"
            status.color = ft.Colors.RED_700
        page.update()

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
                    ft.OutlinedButton("Export retrieved Alma records", icon=ft.Icons.ARCHIVE, on_click=export_alma_records),
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
                    source_system,
                    ft.Divider(),
                    ft.Text("Metadata mapping", size=20, weight=ft.FontWeight.W_600),
                    mapping_field,
                    ft.Row(
                        [
                            ft.FilledButton(
                                "Run export",
                                icon=ft.Icons.PLAY_ARROW,
                                on_click=run_export,
                            ),
                            status,
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
            ),
        )
    )


def launch() -> None:
    ft.app(target=main)
