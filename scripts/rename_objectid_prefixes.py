#!/usr/bin/env python3
"""Rename Alma objectid prefixes without changing numeric suffixes or media."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import fcntl
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import sys
import tempfile


def load_mapping(path: Path) -> dict[str, str]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        if next(reader, None) != ["long_prefix", "short_prefix"]:
            raise ValueError("Mapping header must be long_prefix<TAB>short_prefix")
        mapping: dict[str, str] = {}
        for number, row in enumerate(reader, 2):
            if not row:
                continue
            if len(row) != 2 or any(
                not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value) for value in row
            ):
                raise ValueError(f"Invalid mapping at line {number}: {row!r}")
            old, new = row
            if old in mapping or new in mapping.values():
                raise ValueError(f"Duplicate prefix at line {number}: {row!r}")
            mapping[old] = new
    if not mapping:
        raise ValueError("Mapping is empty")
    for old, new in mapping.items():
        if old != new and new in mapping:
            raise ValueError(f"Chained mapping is unsafe: {old} -> {new}")
    return mapping


def collection_prefix(payload: dict, mapping: dict[str, str]) -> str:
    title = payload.get("collection_title")
    if not isinstance(title, str):
        raise ValueError("Manifest has no collection_title")
    long = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    if long not in mapping:
        raise ValueError(f"No prefix mapping for collection {title!r} ({long})")
    return mapping[long]


def replace_ids(text: str, mapping: dict[str, str]) -> str:
    changed = {old: new for old, new in mapping.items() if old != new}
    if not changed:
        return text
    pattern = re.compile(
        r"(?<![A-Za-z0-9_-])("
        + "|".join(re.escape(old) for old in sorted(changed, key=len, reverse=True))
        + r")(_dg_[0-9]+)(?![A-Za-z0-9_-])"
    )
    return pattern.sub(lambda match: changed[match[1]] + match[2], text)


def unique_ids(values: list[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"Duplicate objectids after replacement in {label}")


def validate_metadata(text: str, path: Path) -> None:
    if path.suffix == ".csv":
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
        if not reader.fieldnames or any(
            None in row or any(value is None for value in row.values()) for row in rows
        ):
            raise ValueError(f"Malformed CSV: {path}")
    else:
        payload = json.loads(text)
        rows = payload.get("records", []) if isinstance(payload, dict) else payload
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError(f"Unexpected JSON record shape: {path}")
    ids = []
    for row in rows:
        if row.get("objectid"):
            ids.append(row["objectid"])
        children = row.get("child_objectids", {})
        if not isinstance(children, dict):
            raise ValueError(f"Invalid child_objectids in {path}")
        ids.extend(children.values())
    unique_ids(ids, str(path))


def plan_changes(root: Path, mapping: dict[str, str]) -> list[tuple[Path, bytes, bytes]]:
    manifests = sorted(root.glob("collection-*/*/gems_*.json"))
    if not manifests:
        raise ValueError(f"No active Alma manifests found under {root}")
    prefixes: dict[Path, str] = {}
    changes: list[tuple[Path, bytes, bytes]] = []

    def read(path: Path) -> tuple[bytes, str]:
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError(f"Refusing symlink or path outside data root: {path}")
        original = path.read_bytes()
        return original, original.decode("utf-8-sig")

    def remember(path: Path, original: bytes, text: str) -> None:
        updated = text.encode("utf-8")
        if original != updated:
            changes.append((path, original, updated))

    for manifest in manifests:
        original, text = read(manifest)
        payload = json.loads(text)
        if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
            raise ValueError(f"Unexpected Alma manifest: {manifest}")
        prefix = collection_prefix(payload, mapping)
        prefixes[manifest.resolve()] = prefix
        updated = replace_ids(text, mapping)
        updated_payload = json.loads(updated)
        if updated_payload.get("objectid_prefix") != prefix:
            updated_payload["objectid_prefix"] = prefix
            updated = json.dumps(updated_payload, indent=2) + "\n"
        validate_metadata(updated, manifest)
        remember(manifest, original, updated)
        for name in ("collection_metadata.csv", "normalized_records.json"):
            path = manifest.parent / name
            if path.exists():
                original, text = read(path)
                updated = replace_ids(text, mapping)
                validate_metadata(updated, path)
                remember(path, original, updated)

    for script in sorted(root.glob("button-2-commands-*")):
        original, text = read(script)
        lines = []
        for line in text.splitlines(keepends=True):
            if line.strip() and not line.lstrip().startswith("#") and line.strip() != "set -euo pipefail":
                args = shlex.split(line)
                if args.count("--source") != 1 or args.count("--objectid-prefix") > 1:
                    raise ValueError(f"Unsupported command in {script}: {line}")
                if args[1:4] != ["-m", "gems", "--headless"]:
                    raise ValueError(f"Not a saved GEMS command in {script}: {line}")
                source_index = args.index("--source") + 1
                if source_index >= len(args):
                    raise ValueError(f"Missing --source value in {script}")
                source = Path(args[source_index]).resolve()
                if source not in prefixes:
                    raise ValueError(f"Command source is not an active mapped manifest: {source}")
                prefix = prefixes[source]
                if "--objectid-prefix" in args:
                    index = args.index("--objectid-prefix") + 1
                    if index >= len(args) or args[index].startswith("--"):
                        raise ValueError(f"Missing --objectid-prefix value in {script}")
                    if args[index] != prefix:
                        args[index] = prefix
                        line = shlex.join(args) + "\n"
                else:
                    args += ["--objectid-prefix", prefix]
                    line = shlex.join(args) + "\n"
            lines.append(line)
        remember(script, original, "".join(lines))
    return changes


def apply_changes(root: Path, changes: list[tuple[Path, bytes, bytes]], mapping_path: Path) -> Path:
    # Back up the entire plan before replacing the first file.
    backup = Path(tempfile.mkdtemp(
        prefix=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-"),
        dir=make_backup_root(root),
    ))
    shutil.copy2(mapping_path, backup / "mapping.tsv")
    for path, original, _ in changes:
        if path.read_bytes() != original:
            raise ValueError(f"File changed during preflight: {path}; nothing applied")
        target = backup / path.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        if target.read_bytes() != original:
            raise ValueError(f"Backup verification failed: {target}; nothing applied")
    print(f"Backup: {backup}", flush=True)
    for path, original, updated in changes:
        if path.read_bytes() != original:
            raise ValueError(f"File changed during apply: {path}; restore earlier files from {backup}")
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".prefix-", delete=False) as handle:
            temporary = Path(handle.name)
            try:
                handle.write(updated)
                handle.flush()
                os.fsync(handle.fileno())
                temporary.chmod(path.stat().st_mode & 0o777)
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
        if path.read_bytes() != updated:
            raise ValueError(f"Write verification failed: {path}; backup at {backup}")
    return backup


def make_backup_root(root: Path) -> Path:
    path = root / ".objectid-prefix-backups"
    if path.is_symlink():
        raise ValueError(f"Refusing symlink backup directory: {path}")
    path.mkdir(mode=0o700, exist_ok=True)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="Back up and apply; default is dry run")
    args = parser.parse_args()
    try:
        mapping = load_mapping(args.mapping)
        root = args.data_root.resolve(strict=True)
        with (root / ".objectid-prefix.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            changes = plan_changes(root, mapping)
            for path, _, _ in changes:
                print(f"CHANGE {path.relative_to(root)}")
            print(f"{'APPLY' if args.apply else 'DRY RUN'}: {len(changes)} file(s)")
            if args.apply and changes:
                apply_changes(root, changes, args.mapping)
                remaining = plan_changes(root, mapping)
                if remaining:
                    raise ValueError(f"Verification failed: {len(remaining)} files still need changes")
                print("Verified: all planned files written; second pass reports zero changes.")
    except (OSError, ValueError, csv.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
