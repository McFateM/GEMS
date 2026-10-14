"""Plan and apply a reviewed, three-way metadata refresh without ingesting assets."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import shutil
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from .mapping_audit import DEFAULT_MAP
from .pipeline import is_template_map, iter_records, map_to_template, representation_items

PROTECTED = frozenset({
    "key", "objectid", "parentid", "original_file_name", "originating_system_id",
    "display_template", "object_location", "image_small", "image_thumb", "filepath",
    "filename", "object_transcript", "image_alt_text", "thumb_focus",
})
HEADER_ALIASES = {
    "Time Period": "time_period", "Subject (Topic)": "subject_topic",
    "Subject (Person)": "subject_person", "Subject (Organization)": "subject_organization",
    "Call Number": "call_number", "Archival Series": "archival_series", "Box": "box",
    "Folder Title": "folder_title", "Folder Number": "folder_number",
    "Finding Aid Permalink": "finding_aid_permalink",
    "Contributing Institution": "contributing_institution",
    "Digital Collection Title": "digital_collection_title",
    "Digital Collection Permalink": "digital_collection_permalink",
    "Avian Identifier": "avian_identifier", "Filename": "filename",
    "Item Permalink": "item_permalink", "Standardized Rights": "standardized_rights",
    "Disclaimer": "disclaimer",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"CSV has no headers: {path}")
        headers = [HEADER_ALIASES.get(name, name) for name in reader.fieldnames]
        if len(headers) != len(set(headers)):
            raise ValueError(f"Duplicate/ambiguous CSV headers: {path}")
        rows = []
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"Malformed CSV row: {path}, line {reader.line_num}")
            rows.append({HEADER_ALIASES.get(key, key): value for key, value in row.items()})
    return headers, rows


def index_rows(rows: list[dict[str, str]], label: str) -> dict[str, dict[str, str]]:
    result = {}
    for row in rows:
        name = row.get("original_file_name", "")
        if not name or name in result:
            raise ValueError(f"Missing or duplicate original_file_name in {label}: {name!r}")
        result[name] = row
    return result


def validate_core(rows: list[dict[str, str]]) -> None:
    ids = [row.get("objectid", "") for row in rows]
    if not all(ids) or len(ids) != len(set(ids)):
        raise ValueError("Core CSV must have non-empty, unique objectids.")
    known_ids = set(ids)
    for row in rows:
        if row.get("parentid") and row["parentid"] not in known_ids:
            raise ValueError(f"Missing core parent: {row['parentid']}")


def reconcile_compound_parents(
    old: dict[str, dict[str, str]], new: dict[str, dict[str, str]],
    current: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    """Resolve parent-name changes with unique compound MMS IDs and verified source files."""
    reconciled = []
    for name in list(current.keys() - new.keys()):
        row = current[name]
        mms = row.get("originating_system_id", "")
        if not mms or row.get("parentid") or row.get("display_template") != "compound_object":
            continue
        candidates = [
            (source_name, source) for source_name, source in new.items()
            if source.get("originating_system_id") == mms and not source.get("parentid")
        ]
        core_candidates = [item for item in current.values()
                           if item.get("originating_system_id") == mms and not item.get("parentid")
                           and item.get("display_template") == "compound_object"]
        if len(candidates) != 1 or len(core_candidates) != 1:
            continue
        source_name, source = candidates[0]
        baseline = old.get(source_name)
        if (source_name in current or baseline is None
                or source.get("display_template") != "compound_object"
                or baseline.get("originating_system_id") != mms
                or baseline.get("parentid")):
            continue
        def children(index: dict[str, dict[str, str]], parent: dict[str, str]) -> set[str]:
            return {key for key, child in index.items() if child.get("parentid") == parent["objectid"]}
        source_children = children(new, source)
        core_children = children(current, row)
        if (not core_children or not core_children.issubset(source_children)
                or source_children != children(old, baseline)):
            continue
        standalone = source_children - core_children
        if any(
            key not in current or current[key].get("parentid")
            or current[key].get("originating_system_id") != mms
            or current[key].get("display_template") == "compound_object"
            for key in standalone
        ):
            continue
        new[name] = new.pop(source_name)
        old[name] = old.pop(source_name)
        reconciled.append({"source_original_file_name": source_name,
                           "core_original_file_name": name, "originating_system_id": mms})
    return reconciled


def csv_bytes(headers: list[str], rows: list[dict[str, str]], original: bytes) -> bytes:
    ending = "\r\n" if b"\r\n" in original else "\n"
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=headers, lineterminator=ending)
    writer.writeheader()
    writer.writerows(rows)
    content = stream.getvalue().encode("utf-8")
    return (b"\xef\xbb\xbf" + content) if original.startswith(b"\xef\xbb\xbf") else content


def plan_refresh(
    manifest: Path, baseline: Path, core: Path, field_map: Path = DEFAULT_MAP,
    legacy_mods: Path | None = None,
    *, allow_partial: bool = False, exclude_source: tuple[str, ...] = (),
    core_row_limit: int | None = None,
) -> dict[str, Any]:
    paths = {"manifest": manifest.resolve(), "baseline": baseline.resolve(),
             "core": core.resolve(), "field_map": field_map.resolve()}
    if len(set(paths.values())) != len(paths):
        raise ValueError("Manifest, baseline, core, and field map must be different files.")
    inputs = {key: {"path": str(path), "sha256": digest(path)} for key, path in paths.items()}
    mapping = json.loads(field_map.read_text(encoding="utf-8"))
    if not is_template_map(mapping):
        raise ValueError("Refresh requires a template field map.")
    if legacy_mods is not None and not legacy_mods.is_dir():
        raise ValueError(f"Legacy MODS folder not found: {legacy_mods}")
    records = iter_records(json.loads(manifest.read_text(encoding="utf-8")))
    if not records:
        raise ValueError("Manifest has no records.")
    for record in records:
        items = representation_items(record)
        children = record.get("child_objectids", {})
        if not record.get("objectid") or (
            len(items) > 1 and any(not children.get(item["filename"]) for item in items)
        ):
            raise ValueError("Use the original mapped manifest with persisted parent and child IDs.")
    fresh, _ = map_to_template(records, mapping, manifest.parent / "objects",
                               legacy_mods, metadata_only=True)
    baseline_headers, old_rows = read_csv(baseline)
    headers, core_rows = read_csv(core)
    validate_core(core_rows)
    old = index_rows(old_rows, "baseline")
    new = index_rows(fresh, "remapped manifest")
    current = index_rows(core_rows, "core")
    reconciled = reconcile_compound_parents(old, new, current)
    if core_row_limit is not None:
        if core_row_limit < 1 or core_row_limit > len(core_rows):
            raise ValueError("Core row limit must be between 1 and the number of core data rows.")
        selected_names = {row["original_file_name"] for row in core_rows[:core_row_limit]}
        current = {key: row for key, row in current.items() if key in selected_names}
        new = {key: row for key, row in new.items() if key in selected_names}
        old = {key: row for key, row in old.items() if key in selected_names}
        reconciled = [row for row in reconciled if row["core_original_file_name"] in selected_names]
    excluded = []
    for name in exclude_source:
        if name not in new or name in current or name not in old:
            raise ValueError(f"Exclusion must identify a source/baseline row absent from core: {name}")
        excluded.append({"original_file_name": name, "title": new[name].get("title", ""),
                         "originating_system_id": new[name].get("originating_system_id", "")})
        del new[name]
        del old[name]
    unmatched = {
        "core_without_source": sorted(current.keys() - new.keys()),
        "source_without_core": sorted(new.keys() - current.keys()),
        "source_without_baseline": sorted(new.keys() - old.keys()),
        "baseline_without_source": sorted(old.keys() - new.keys()),
    }
    eligible = [col for col in mapping["columns"]
                if col in mapping.get("rules", {}) and col not in PROTECTED]
    added_columns = [col for col in eligible if col not in headers]
    changes = []
    for name, row in current.items():
        if name not in new or name not in old:
            continue
        for column in eligible:
            previous = old[name].get(column, "")
            proposed = new[name].get(column, "")
            published = row.get(column, "")
            if proposed == published or (
                column in baseline_headers and proposed == previous
            ):
                continue
            missing_fallback = (
                legacy_mods is None and not proposed and bool(previous)
                and "fallback" in mapping["rules"][column]
            )
            safe = not missing_fallback and (published == previous or not published)
            reason = ("legacy_mods_unavailable" if missing_fallback else
                      "source_refresh" if safe else "published_value_differs_from_baseline")
            changes.append({
                "original_file_name": name, "objectid": row["objectid"],
                "field": column, "baseline": previous, "current": published,
                "proposed": proposed, "status": "safe" if safe else "conflict",
                "reason": reason, "decision": "apply" if safe else None,
            })
    for key, value in inputs.items():
        if digest(Path(value["path"])) != value["sha256"]:
            raise ValueError(f"{key} changed while planning; retry.")
    return {
        "version": 1, "created_at": datetime.now().astimezone().isoformat(),
        "inputs": inputs, "legacy_mods": str(legacy_mods) if legacy_mods else None,
        "allow_partial": allow_partial,
        "core_row_limit": core_row_limit,
        "excluded_source_rows": excluded,
        "reconciled_compound_parents": reconciled,
        "core_rows": len(core_rows), "source_rows": len(fresh),
        "added_columns": added_columns, "unmatched": unmatched,
        "changes": changes,
        "summary": dict(Counter(change["status"] for change in changes)),
    }


def apply_refresh(report: dict[str, Any], *, backup_dir: Path | None = None) -> Path | None:
    if report.get("version") != 1:
        raise ValueError("Unsupported refresh report version.")
    blocking = ("source_without_core", "source_without_baseline") if report.get("allow_partial") else tuple(report["unmatched"])
    if any(report["unmatched"][key] for key in blocking):
        raise ValueError("Unmatched rows must be reconciled before applying this collection-wide refresh.")
    for key, value in report["inputs"].items():
        if digest(Path(value["path"])) != value["sha256"]:
            raise ValueError(f"{key} changed since planning; create a new plan.")
    core = Path(report["inputs"]["core"]["path"])
    headers, rows = read_csv(core)
    validate_core(rows)
    by_name = index_rows(rows, "core")
    limit = report.get("core_row_limit")
    if limit is not None and (not isinstance(limit, int) or limit < 1 or limit > len(rows)):
        raise ValueError("Invalid core row limit.")
    permitted = {row["original_file_name"] for row in rows[:limit]}
    added = report["added_columns"]
    if any(column in PROTECTED or column in headers for column in added) or len(added) != len(set(added)):
        raise ValueError("Invalid added columns.")
    headers.extend(added)
    for row in rows:
        row.update({column: "" for column in added})
    seen = set()
    for change in report["changes"]:
        column = change["field"]
        name = change["original_file_name"]
        if name not in permitted:
            raise ValueError(f"Change lies outside the selected core rows: {name}")
        if column in PROTECTED or column not in headers or (name, column) in seen:
            raise ValueError(f"Invalid/duplicate field change: {name}, {column}")
        seen.add((name, column))
        row = by_name[name]
        if row["objectid"] != change["objectid"] or row[column] != change["current"]:
            raise ValueError(f"Change does not match current core: {name}, {column}")
        if change["decision"] not in {"apply", "keep"}:
            raise ValueError(f"Resolve the conflict with decision apply or keep: {name}, {column}")
        if not isinstance(change["proposed"], str):
            raise ValueError(f"Proposed value must be a string: {name}, {column}")
        if change["decision"] == "apply":
            row[column] = change["proposed"]
    original = core.read_bytes()
    updated = csv_bytes(headers, rows, original)
    if updated == original:
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup = (backup_dir or core.parent) / f"{core.name}.backup_{stamp}"
    with backup.open("xb") as handle:
        handle.write(original)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=core.parent, prefix=".metadata-refresh-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(updated)
            handle.flush()
            os.fsync(handle.fileno())
        shutil.copymode(core, temporary)
        if digest(core) != report["inputs"]["core"]["sha256"]:
            raise ValueError("Core changed during apply; refusing to replace it.")
        os.replace(temporary, core)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink()
    return backup


def cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan", help="Write a JSON review plan; no source or core files are changed")
    plan.add_argument("--manifest", type=Path, required=True)
    plan.add_argument("--baseline", type=Path, required=True, help="Old GEMS collection_metadata.csv")
    plan.add_argument("--core", type=Path, required=True, help="Published SHOW/core CSV")
    plan.add_argument("--field-map", type=Path, default=DEFAULT_MAP)
    plan.add_argument("--legacy-mods", type=Path)
    plan.add_argument("--allow-partial", action="store_true",
                      help="Refresh only source-matched rows; leave other core rows untouched")
    plan.add_argument("--exclude-source", action="append", default=[],
                      help="Explicit original_file_name of an unpublished source row to exclude (repeatable)")
    plan.add_argument("--core-row-limit", type=int,
                      help="Refresh only the first N core CSV data rows (not Alma records)")
    plan.add_argument("--report", type=Path, required=True)
    apply = commands.add_parser("apply", help="Apply reviewed decisions after checking source fingerprints")
    apply.add_argument("report", type=Path)
    apply.add_argument("--keep-conflicts", action="store_true",
                       help="Explicitly preserve all unresolved conflicts and record those decisions")
    args = parser.parse_args()
    try:
        if args.command == "plan":
            sources = [args.manifest, args.baseline, args.core, args.field_map]
            if args.report.resolve() in {path.resolve() for path in sources}:
                raise ValueError("Report must not overwrite an input file.")
            report = plan_refresh(args.manifest, args.baseline, args.core, args.field_map,
                                  args.legacy_mods, allow_partial=args.allow_partial,
                                  exclude_source=tuple(args.exclude_source),
                                  core_row_limit=args.core_row_limit)
            with args.report.open("x", encoding="utf-8") as handle:
                handle.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
            print(f"Plan: {args.report}\n{json.dumps(report['summary'])}")
            print(f"Added columns: {report['added_columns']}")
            print(f"Unmatched rows: {json.dumps(report['unmatched'])}")
            print(f"Excluded source rows: {json.dumps(report['excluded_source_rows'])}")
            print(f"Reconciled compound parents: {json.dumps(report['reconciled_compound_parents'])}")
        else:
            report = json.loads(args.report.read_text(encoding="utf-8"))
            if args.keep_conflicts:
                for change in report["changes"]:
                    if change["decision"] is None:
                        change["decision"] = "keep"
            backup = apply_refresh(report, backup_dir=args.report.parent)
            if args.keep_conflicts:
                args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"Applied refresh. Backup: {backup}" if backup else "No changes needed.")
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"Metadata refresh failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
