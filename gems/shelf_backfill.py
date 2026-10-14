"""Backfill only shelf_locator in saved manifests, GEMS outputs, and SHOW CSVs."""

from __future__ import annotations

import argparse
import csv
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from .metadata_refresh import csv_bytes, digest
from .mods import LEGACY_PID, find_legacy_mods, read_legacy_mods
from .pipeline import iter_records, representation_items


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames
        if not headers or len(headers) != len(set(headers)):
            raise ValueError(f"Missing/duplicate CSV headers: {path}")
        rows = list(reader)
        if any(None in row or any(value is None for value in row.values()) for row in rows):
            raise ValueError(f"Malformed CSV: {path}")
    return headers, rows


def row_values(
    rows: list[dict[str, Any]], sources: list[dict[str, Any]],
) -> tuple[list[str | None], list[int]]:
    indexes: dict[str, dict[str, set[int]]] = {key: {} for key in ("objectid", "mms", "filename", "pid")}
    for index, source in enumerate(sources):
        for key, values in source["keys"].items():
            for value in values:
                if value:
                    indexes[key].setdefault(value, set()).add(index)
    by_id = {str(row.get("objectid", "")): row for row in rows if row.get("objectid")}
    values: list[str | None] = []
    unmatched = []
    for position, row in enumerate(rows):
        parent = row
        visited = set()
        while parent.get("parentid"):
            pid = str(parent["parentid"])
            if pid in visited or pid not in by_id:
                raise ValueError(f"Invalid parent chain for row {position + 1}")
            visited.add(pid)
            parent = by_id[pid]
        candidates = set()
        for key, value in (
            ("objectid", str(parent.get("objectid", ""))),
            ("mms", str(parent.get("originating_system_id", ""))),
            ("pid", str(parent.get("identifier", ""))),
        ):
            found = indexes[key].get(value, set())
            if found:
                candidates = found
                break
        if not candidates:
            name = str(row.get("original_file_name", row.get("filename", "")))
            candidates = indexes["filename"].get(name, set())
        found_values = {sources[index]["value"] for index in candidates}
        if len(found_values) > 1:
            raise ValueError(f"Ambiguous source shelf locators for row {position + 1}")
        if not found_values:
            values.append(None)
            unmatched.append(position + 1)
        else:
            values.append(next(iter(found_values)))
    return values, unmatched


def build_plan(roots: list[Path], mods_root: Path, show: Path | None) -> dict[str, Any]:
    if not mods_root.is_dir() or any(not root.is_dir() for root in roots):
        raise ValueError("Every GEMS root and the MODS root must be an existing directory.")
    if show is not None and not (show / "collections").is_dir():
        raise ValueError("SHOW root must contain collections/.")
    manifests = sorted({path.resolve() for root in roots for path in root.glob("*/*/gems_*.json")})
    if not manifests:
        raise ValueError("No saved GEMS manifests found under the supplied roots.")
    sources = []
    files = []
    missing_mods = []
    skipped_files = []
    cache: dict[Path, str] = {}
    for manifest in manifests:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        records = iter_records(payload)
        if not isinstance(payload, dict) or payload.get("records") != records:
            raise ValueError(f"Backfill requires a records-array JSON manifest: {manifest}")
        patches = []
        for index, record in enumerate(records):
            metadata = record.get("metadata", {})
            identifiers = str(metadata.get("dc:identifier") or metadata.get("identifier") or record.get("identifier") or "")
            pids = [value.strip() for value in identifiers.split(";") if LEGACY_PID.fullmatch(value.strip())]
            paths = [find_legacy_mods(mods_root, pid, str(metadata.get("dginfo", ""))) for pid in pids]
            found = {path for path in paths if path is not None}
            if not found:
                for pid in pids:
                    name = pid.replace(":", "_") + "_MODS.xml"
                    found.update(mods_root.glob(f"*/{name}"))
            value = ""
            if found:
                for path in found:
                    if path not in cache:
                        cache[path] = read_legacy_mods(path).get("shelf_locator", "")
                alternatives = {cache[path] for path in found}
                if len(alternatives) > 1:
                    raise ValueError(f"Conflicting MODS shelf locators for {manifest}, record {index + 1}")
                value = next(iter(alternatives))
            else:
                missing_mods.append({"manifest": str(manifest), "record": index + 1, "identifiers": pids})
            existing = str(record.get("shelf_locator") or metadata.get("shelf_locator") or "")
            if existing:
                if value and existing != value:
                    raise ValueError(f"Existing manifest shelf_locator conflicts with MODS: {manifest}, record {index + 1}")
                value = existing
            elif value:
                patches.append({"row": index, "value": value})
            items = representation_items(record)
            children = record.get("child_objectids", {})
            names = [item["filename"] for item in items]
            sources.append({
                "value": value,
                "keys": {
                    "objectid": [str(record.get("objectid", "")), *children.values()],
                    "mms": [str(record.get("mms_id", ""))],
                    "pid": pids,
                    "filename": names + (["_" + names[0]] if names else []),
                },
            })
        files.append({"path": str(manifest), "sha256": digest(manifest),
                      "kind": "manifest", "patches": patches})
    targets = {manifest.parent / "collection_metadata.csv" for manifest in manifests}
    targets.update(manifest.parent / "normalized_records.json" for manifest in manifests)
    if show:
        targets.update(path for path in (show / "collections").glob("*/_data/*.csv")
                       if not path.relative_to(show / "collections").parts[0].startswith("_")
                       and not path.name.startswith("."))
    source_keys = {key: {value for source in sources for value in source["keys"][key] if value}
                   for key in ("objectid", "mms", "filename", "pid")}
    for target in sorted(targets):
        if not target.exists():
            skipped_files.append({"path": str(target), "reason": "output_missing"})
            continue
        kind = "csv" if target.suffix == ".csv" else "normalized"
        if kind == "csv":
            headers, rows = read_rows(target)
            if "objectid" not in headers or not ({"original_file_name", "identifier"} & set(headers)):
                skipped_files.append({"path": str(target), "reason": "not_an_item_metadata_csv"})
                continue
        else:
            rows = json.loads(target.read_text(encoding="utf-8"))
            if not isinstance(rows, list):
                raise ValueError(f"Expected normalized-record array: {target}")
            headers = []
        if not any(
            str(row.get(column, "")) in source_keys[key]
            for row in rows for column, key in (
                ("objectid", "objectid"), ("originating_system_id", "mms"),
                ("identifier", "pid"), ("original_file_name", "filename"), ("filename", "filename"),
            )
        ):
            skipped_files.append({"path": str(target), "reason": "no_available_gems_source_matches"})
            continue
        try:
            values, unmatched = row_values(rows, sources)
        except ValueError as error:
            raise ValueError(f"{target}: {error}") from error
        if len(unmatched) == len(rows):
            continue
        patches = []
        conflicts = []
        for index, (row, value) in enumerate(zip(rows, values)):
            if value is not None:
                current = row.get("shelf_locator", "")
                if current and value and current != value:
                    conflicts.append(index + 1)
                elif not current and (value or "shelf_locator" not in row):
                    patches.append({"row": index, "value": value})
        files.append({"path": str(target), "sha256": digest(target), "kind": kind,
                      "add_column": kind == "csv" and "shelf_locator" not in headers,
                      "patches": patches, "conflicts_preserved": conflicts,
                      "unmatched_rows": unmatched, "rows": len(rows)})
    return {"version": 1, "created_at": datetime.now().astimezone().isoformat(),
            "files": files, "missing_mods": missing_mods, "skipped_files": skipped_files,
            "mods_inputs": [{"path": str(path), "sha256": digest(path)} for path in cache],
            "summary": {"manifests": len(manifests), "sources": len(sources),
                        "sources_with_locator": sum(bool(source["value"]) for source in sources),
                        "missing_mods": len(missing_mods)}}


def apply_plan(plan: dict[str, Any], backup_dir: Path) -> list[dict[str, str]]:
    if plan.get("version") != 1:
        raise ValueError("Unsupported shelf backfill plan.")
    for entry in [*plan["files"], *plan["mods_inputs"]]:
        if digest(Path(entry["path"])) != entry["sha256"]:
            raise ValueError(f"Input changed since planning: {entry['path']}")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    results = []
    for number, entry in enumerate(plan["files"]):
        if not entry["patches"] and not entry.get("add_column"):
            continue
        path = Path(entry["path"])
        original = path.read_bytes()
        if entry["kind"] == "csv":
            headers, rows = read_rows(path)
            if entry["add_column"]:
                headers.append("shelf_locator")
                for row in rows:
                    row["shelf_locator"] = ""
            payload = rows
        else:
            payload = json.loads(original)
            rows = payload["records"] if entry["kind"] == "manifest" else payload
        for patch in entry["patches"]:
            if rows[patch["row"]].get("shelf_locator"):
                raise ValueError(f"Refusing to overwrite existing shelf_locator: {path}")
            rows[patch["row"]]["shelf_locator"] = patch["value"]
        updated = (csv_bytes(headers, rows, original) if entry["kind"] == "csv"
                   else (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
        backup = backup_dir / f"shelf-backfill-{stamp}-{number}-{path.name}.bak"
        with backup.open("xb") as handle:
            handle.write(original)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".shelf-backfill-", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(updated)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, path.stat().st_mode)
            if digest(path) != entry["sha256"]:
                raise ValueError(f"Input changed during apply: {path}")
            os.replace(temporary, path)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink()
        results.append({"path": str(path), "backup": str(backup), "sha256": digest(path)})
    return results


def cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("--gems-root", type=Path, action="append", required=True)
    plan.add_argument("--legacy-mods", type=Path, required=True)
    plan.add_argument("--show-root", type=Path)
    plan.add_argument("--report", type=Path, required=True)
    apply = commands.add_parser("apply")
    apply.add_argument("report", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "plan":
            report = build_plan(args.gems_root, args.legacy_mods, args.show_root)
            if args.report.resolve() in {Path(item["path"]).resolve() for item in report["files"] + report["mods_inputs"]}:
                raise ValueError("Report must not overwrite an input.")
            with args.report.open("x", encoding="utf-8") as handle:
                handle.write(json.dumps(report, indent=2) + "\n")
            print(json.dumps(report["summary"]))
            for entry in report["files"]:
                if entry["kind"] != "manifest":
                    print(f"{entry['path']}: {len(entry['patches'])} field additions/updates; "
                          f"{len(entry['conflicts_preserved'])} conflicts; "
                          f"{len(entry['unmatched_rows'])} unmatched rows")
        else:
            report = json.loads(args.report.read_text(encoding="utf-8"))
            receipt = args.report.with_name(args.report.stem + "-applied.json")
            if receipt.exists():
                raise ValueError(f"Apply receipt already exists; create a fresh plan: {receipt}")
            results = apply_plan(report, args.report.parent)
            with receipt.open("x", encoding="utf-8") as handle:
                handle.write(json.dumps(results, indent=2) + "\n")
            print(f"Updated {len(results)} files. Backups in {args.report.parent}. Receipt: {receipt}")
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"Shelf backfill failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
