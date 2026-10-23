#!/usr/bin/env python3
"""Rebuild an Omeka run's GEMS metadata with unmapped-field preservation, without downloading.

Replays GEMS's own Omeka export into a scratch folder. Files that downloaded in the original run
become empty placeholders; URLs listed in the run's download_errors.csv fail again, so metadata
asset rows match the original run exactly. Compound parent metadata rows are added when
two or more successful assets belong to the same item.
With --install, only collection_metadata.csv and normalized_records.json are replaced (after
backup). objects/ and download_errors.csv are never written.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def snapshot(objects: Path) -> dict[str, tuple[int, int]]:
    return {
        str(path.relative_to(objects)): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in objects.rglob("*") if path.is_file()
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="Omeka CSV/JSON export used for the run")
    parser.add_argument("--run", required=True, type=Path, help="Existing GEMS Omeka output folder")
    parser.add_argument("--scratch", required=True, type=Path, help="New folder for the rebuild (must not exist)")
    parser.add_argument("--install", action="store_true", help="Replace the run's CSV/JSON after verification")
    parser.add_argument("--preserve-source-names", action="store_true",
                        help="Also retain mapped source fields as _<original-name> columns")
    args = parser.parse_args()

    from gems.pipeline import DownloadError, process_export
    from gems.omeka import asset_field_map, load_omeka
    from gems.pipeline import prepare_asset_records, preserve_unmapped_fields, source_metadata

    run, scratch = args.run.resolve(), args.scratch.resolve()
    if scratch.exists():
        sys.exit(f"Scratch folder already exists: {scratch}")
    if scratch == run or run in scratch.parents:
        sys.exit("Scratch folder must be outside the run folder.")
    old_csv, old_json, errors = run / "collection_metadata.csv", run / "normalized_records.json", run / "download_errors.csv"
    for path in (old_csv, old_json, run / "objects"):
        if not path.exists():
            sys.exit(f"Missing {path}")
    _, failures = read_csv(errors) if errors.exists() else ([], [])
    failed_urls = {row["url"] for row in failures}
    before = snapshot(run / "objects")

    def offline_fetch(url: str, destination: Path) -> None:
        if url in failed_urls:
            with HTTPError(url, 403, "Replayed failure from download_errors.csv", {}, None) as error:
                raise DownloadError("Replayed failure from original run (no network request)") from error
        Path(destination).write_bytes(b"")

    records = load_omeka(args.source)
    field_map = None
    if args.preserve_source_names:
        field_map = preserve_unmapped_fields(records, asset_field_map(None))
        for record in records:
            for key in source_metadata(record):
                column = f"_{key}"
                if column not in field_map["columns"]:
                    field_map["columns"].append(column)
                    field_map["rules"][column] = {"_source_field": key, "child": "inherit"}

    logging.getLogger("gems").setLevel(logging.ERROR)
    with patch("gems.pipeline.fetch_object", side_effect=offline_fetch):
        result = process_export(args.source, scratch, source_type="omeka", field_map=field_map,
                                skip_download_errors=True)

    problems: list[str] = []
    old_headers, old_rows = read_csv(old_csv)
    new_headers, new_rows = read_csv(result.csv_path)
    if {f["url"] for f in result.failed_downloads} != failed_urls:
        problems.append("Replayed failures differ from download_errors.csv.")
    if set(snapshot(scratch / "objects")) != set(before):
        problems.append("Rebuilt object paths differ from the run's objects/ folder.")
    prepare_asset_records(records)
    by_name = {item["filename"]: record for record in records for item in record["_asset_items"]}
    old_assets = [row for row in old_rows if row["original_file_name"] in by_name]
    new_assets = [row for row in new_rows if row["original_file_name"] in by_name]
    if [r["original_file_name"] for r in new_assets] != [r["original_file_name"] for r in old_assets]:
        problems.append("Asset row order or original_file_name values differ.")
    old_names = {row["original_file_name"] for row in old_rows}
    new_by_name = {row["original_file_name"]: row for row in new_rows}
    if len(new_by_name) != len(new_rows) or old_names - set(new_by_name):
        problems.append("Duplicate rebuilt names or missing existing rows.")
    if [column for column in new_headers if column in old_headers] != old_headers:
        problems.append("Existing columns were not kept in their original order.")
    added = [column for column in new_headers if column not in old_headers]
    if any(not column.startswith("_") for column in added):
        problems.append(f"Unexpected non-underscore columns: {[c for c in added if not c.startswith('_')]}")
    changed = [
        (old["original_file_name"], column)
        for old in old_rows for column in old_headers
        if old["original_file_name"] in new_by_name
        and old[column] != new_by_name[old["original_file_name"]][column]
    ]
    if changed:
        problems.append(f"{len(changed)} existing values changed, e.g. {changed[:5]}")
    if json.loads(result.json_path.read_text(encoding="utf-8")) != new_rows:
        problems.append("normalized_records.json does not match the rebuilt CSV.")

    expected_names = {row["original_file_name"] for row in new_assets}
    for record in records:
        assets = [item["filename"] for item in record["_asset_items"] if item["filename"] in new_by_name]
        if len(assets) > 1:
            parent_name = f"_{min(assets)}"
            by_name[parent_name] = record
            expected_names.add(parent_name)
    if set(new_by_name) != expected_names:
        problems.append("Missing or unexpected synthetic parent rows.")
    missing = [
        (row["original_file_name"], key)
        for row in new_rows
        if row["original_file_name"] in by_name
        for key, value in by_name[row["original_file_name"]]["source_metadata"].items()
        if value and (row.get(f"_{key}") != value if args.preserve_source_names else value not in row.values())
    ]
    if missing:
        problems.append(f"{len(missing)} source values missing from output, e.g. {missing[:5]}")
    if snapshot(run / "objects") != before:
        problems.append("The run's objects/ folder changed during the rebuild.")

    print(f"Rows: {len(new_rows)} (was {len(old_rows)}); replayed failures: {len(result.failed_downloads)}")
    print(f"Columns: {len(new_headers)} (was {len(old_headers)}); added {len(added)}:")
    for column in added:
        print(f"  {column}: {sum(1 for row in new_rows if row[column])} nonempty rows")
    if problems:
        print("VERIFICATION FAILED; run left unchanged:", *problems, sep="\n  ")
        return 1
    print("Verification passed: same asset rows, files, failures, and existing values; "
          "compound parent metadata added; no source values missing.")

    if args.install:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        for new, old in ((result.csv_path, old_csv), (result.json_path, old_json)):
            backup = old.with_name(f"{old.name}.pre-unmapped-{stamp}")
            shutil.copy2(old, backup)
            temporary = old.with_name(f".{old.name}.{stamp}.tmp")
            shutil.copyfile(new, temporary)
            os.chmod(temporary, old.stat().st_mode & 0o777)
            os.replace(temporary, old)
            print(f"Installed {old} (backup: {backup.name})")
    else:
        print(f"Dry run only. Review {result.csv_path}, then rerun with --install and a new --scratch folder.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
