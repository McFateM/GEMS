from __future__ import annotations

import csv
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from urllib.request import urlretrieve

COLLECTIONBUILDER_FIELDS = [
    "identifier",
    "title",
    "creator",
    "date",
    "description",
    "subject",
    "type",
    "format",
    "language",
    "coverage",
    "publisher",
    "rights",
    "relation",
    "source",
    "source_system",
    "source_record_url",
    "objectid",
    "filename",
]

FIELD_ALIASES = {
    "identifier": ("identifier", "id", "pid", "mms_id", "alma_id", "record_id", "handle"),
    "title": ("title", "name", "label"),
    "creator": ("creator", "author", "contributor"),
    "date": ("date", "created", "issued", "year"),
    "description": ("description", "abstract", "summary"),
    "subject": ("subject", "keywords", "keyword"),
    "type": ("type", "resource_type"),
    "format": ("format", "mime_type", "mimetype"),
    "language": ("language", "lang"),
    "coverage": ("coverage", "spatial", "temporal"),
    "publisher": ("publisher",),
    "rights": ("rights", "license"),
    "relation": ("relation", "is_part_of", "collection"),
    "source": ("source",),
}

FILE_KEYS = ("files", "digital_objects", "representations", "assets")
URL_KEYS = ("url", "href", "download_url", "source", "path", "local_path", "file")
NAME_KEYS = ("name", "filename", "label", "title")


@dataclass(slots=True)
class ExportResult:
    row_count: int
    file_count: int
    csv_path: Path
    json_path: Path
    objects_dir: Path


def process_export(
    source_path: str | Path,
    output_dir: str | Path,
    *,
    field_map: dict[str, str] | None = None,
    source_system: str = "alma_digital",
) -> ExportResult:
    source = Path(source_path)
    payload = load_payload(source)
    return process_records(payload, output_dir, field_map=field_map, source_system=source_system)


def process_records(
    records: list[dict[str, Any]],
    output_dir: str | Path,
    *,
    field_map: dict[str, str] | None = None,
    source_system: str = "alma_digital",
) -> ExportResult:
    destination = Path(output_dir)
    rows = normalize_records(records, field_map=field_map, source_system=source_system)
    exported_files = export_files(rows, destination / "objects")

    csv_path = destination / "collection_metadata.csv"
    json_path = destination / "normalized_records.json"
    write_collection_csv(rows, csv_path)
    write_structured_records(rows, json_path)

    return ExportResult(
        row_count=len(rows),
        file_count=exported_files,
        csv_path=csv_path,
        json_path=json_path,
        objects_dir=destination / "objects",
    )


def load_payload(source_path: Path) -> list[dict[str, Any]]:
    suffix = source_path.suffix.lower()
    if suffix == ".json":
        payload = json.loads(source_path.read_text(encoding="utf-8"))
        return list(iter_records(payload))
    if suffix == ".csv":
        with source_path.open("r", encoding="utf-8", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    raise ValueError(f"Unsupported source format: {source_path.suffix}")


def iter_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("records", "items", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [payload]
    raise ValueError("Source payload must be a JSON object or array of objects")


def normalize_records(
    records: list[dict[str, Any]],
    *,
    field_map: dict[str, str] | None = None,
    source_system: str = "alma_digital",
) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for record in records:
        metadata = flatten_metadata(record)
        files = extract_files(record)
        base_identifier = resolve_field("identifier", record, metadata, field_map) or "record"
        source_url = resolve_field("source", record, metadata, field_map) or stringify(
            record.get("url") or record.get("record_url") or record.get("link")
        )
        base_row = {
            "identifier": base_identifier,
            "title": resolve_field("title", record, metadata, field_map),
            "creator": resolve_field("creator", record, metadata, field_map),
            "date": resolve_field("date", record, metadata, field_map),
            "description": resolve_field("description", record, metadata, field_map),
            "subject": resolve_field("subject", record, metadata, field_map),
            "type": resolve_field("type", record, metadata, field_map),
            "format": resolve_field("format", record, metadata, field_map),
            "language": resolve_field("language", record, metadata, field_map),
            "coverage": resolve_field("coverage", record, metadata, field_map),
            "publisher": resolve_field("publisher", record, metadata, field_map),
            "rights": resolve_field("rights", record, metadata, field_map),
            "relation": resolve_field("relation", record, metadata, field_map),
            "source": source_url,
            "source_system": source_system,
            "source_record_url": source_url,
            "objectid": "",
            "filename": "",
        }
        if not files:
            normalized.append(base_row)
            continue

        for index, file_info in enumerate(files, start=1):
            row = dict(base_row)
            if len(files) > 1:
                row["identifier"] = f"{base_identifier}-{index}"
            row["_source_file"] = file_info["source"]
            row["filename"] = file_info["filename"]
            normalized.append(row)
    return normalized


def flatten_metadata(record: dict[str, Any]) -> dict[str, str]:
    flattened: dict[str, str] = {}
    for key, value in record.items():
        if key in FILE_KEYS:
            continue
        if isinstance(value, (str, int, float, bool)):
            flattened[normalize_key(key)] = stringify(value)
    for container_key in ("metadata", "descriptive_metadata", "descriptiveMetadata", "fields"):
        value = record.get(container_key)
        if isinstance(value, dict):
            for key, nested_value in value.items():
                flattened[normalize_key(key)] = stringify(nested_value)
        elif isinstance(value, list):
            for item in value:
                if not isinstance(item, dict):
                    continue
                label = item.get("label") or item.get("name") or item.get("field")
                nested_value = item.get("value")
                if label and nested_value is not None:
                    flattened[normalize_key(str(label))] = stringify(nested_value)
    return flattened


def resolve_field(
    target_field: str,
    record: dict[str, Any],
    metadata: dict[str, str],
    field_map: dict[str, str] | None,
) -> str:
    candidates: list[str] = []
    if field_map and target_field in field_map:
        candidates.append(field_map[target_field])
    candidates.extend(FIELD_ALIASES.get(target_field, (target_field,)))
    for candidate in candidates:
        normalized_candidate = normalize_key(candidate)
        if normalized_candidate in metadata:
            return metadata[normalized_candidate]
        raw_value = record.get(candidate)
        if raw_value is not None:
            return stringify(raw_value)
    return ""


def extract_files(record: dict[str, Any]) -> list[dict[str, str]]:
    raw_files: Any = None
    for key in FILE_KEYS:
        if key in record:
            raw_files = record[key]
            break
    if raw_files is None:
        return []
    if isinstance(raw_files, dict):
        raw_files = [raw_files]
    files: list[dict[str, str]] = []
    for item in raw_files:
        if isinstance(item, str):
            source = item
            filename = infer_filename(item, len(files) + 1)
        elif isinstance(item, dict):
            source = next((stringify(item.get(key)) for key in URL_KEYS if item.get(key)), "")
            filename = next((stringify(item.get(key)) for key in NAME_KEYS if item.get(key)), "")
            if not filename:
                filename = infer_filename(source, len(files) + 1)
        else:
            continue
        if source:
            files.append({"source": source, "filename": filename})
    return files


def export_files(rows: list[dict[str, str]], objects_dir: Path) -> int:
    objects_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for index, row in enumerate(rows, start=1):
        source = row.pop("_source_file", "")
        if not source:
            continue
        safe_name = safe_filename(row.get("filename") or infer_filename(source, index), index)
        destination = objects_dir / safe_name
        parsed = urlparse(source)
        if parsed.scheme in {"http", "https"}:
            urlretrieve(source, destination)
        elif parsed.scheme == "file":
            shutil.copy2(Path(unquote(parsed.path)), destination)
        else:
            shutil.copy2(Path(source), destination)
        row["filename"] = safe_name
        row["objectid"] = Path("objects", safe_name).as_posix()
        count += 1
    return count


def write_collection_csv(rows: list[dict[str, str]], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLLECTIONBUILDER_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in COLLECTIONBUILDER_FIELDS})


def write_structured_records(rows: list[dict[str, str]], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")


def normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "; ".join(stringify(item) for item in value if item is not None)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def infer_filename(source: str, fallback_index: int) -> str:
    parsed = urlparse(source)
    candidate = Path(unquote(parsed.path or source)).name
    return candidate or f"object-{fallback_index}"


def safe_filename(filename: str, index: int) -> str:
    path = Path(filename)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", path.stem).strip("._") or f"object-{index}"
    suffix = re.sub(r"[^A-Za-z0-9.]+", "", path.suffix)[:16]
    return f"{stem}{suffix}"
