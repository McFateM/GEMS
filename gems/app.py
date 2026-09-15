from __future__ import annotations

import json
from pathlib import Path

from .pipeline import process_export


def main(page):
    import flet as ft

    page.title = "GEMS"
    page.scroll = ft.ScrollMode.AUTO
    page.padding = 20

    source_field = ft.TextField(label="Alma Digital / Specto export (.json or .csv)", expand=True)
    output_field = ft.TextField(label="Output directory", expand=True)
    mapping_field = ft.TextField(
        label="Optional field map JSON (CollectionBuilder field -> source field)",
        value="{}",
        multiline=True,
        min_lines=4,
        max_lines=8,
    )
    status = ft.Text(value="Ready.")

    source_picker = ft.FilePicker()
    output_picker = ft.FilePicker()
    page.overlay.extend([source_picker, output_picker])

    def on_source_pick(event: ft.FilePickerResultEvent):
        if event.files:
            source_field.value = event.files[0].path
            page.update()

    def on_output_pick(event: ft.FilePickerResultEvent):
        if event.path:
            output_field.value = event.path
            page.update()

    source_picker.on_result = on_source_pick
    output_picker.on_result = on_output_pick

    def run_export(_):
        try:
            field_map = json.loads(mapping_field.value or "{}")
            result = process_export(
                Path(source_field.value),
                Path(output_field.value),
                field_map=field_map,
            )
            status.value = (
                f"Exported {result.row_count} metadata row(s) and {result.file_count} file(s) to "
                f"{result.csv_path.parent}"
            )
        except Exception as exc:  # pragma: no cover - UI feedback wrapper
            status.value = f"Export failed: {exc}"
        page.update()

    page.add(
        ft.Text("Gather Alma Digital / Specto records and emit CollectionBuilder-ready metadata."),
        ft.Row(
            [
                source_field,
                ft.ElevatedButton("Browse", on_click=lambda _: source_picker.pick_files(allow_multiple=False)),
            ]
        ),
        ft.Row(
            [
                output_field,
                ft.ElevatedButton("Select Folder", on_click=lambda _: output_picker.get_directory_path()),
            ]
        ),
        mapping_field,
        ft.ElevatedButton("Run Export", on_click=run_export),
        status,
    )


def launch() -> None:
    import flet as ft

    ft.app(target=main)
