from __future__ import annotations

import csv
import html
import json
import mimetypes
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import parse_qs, unquote, urlparse
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
    field_map: dict[str, Any] | None = None,
    source_system: str = "alma_digital",
) -> ExportResult:
    source = Path(source_path)
    if is_template_map(field_map) and source.suffix.lower() == ".json":
        payload = json.loads(source.read_text(encoding="utf-8"))
        records = iter_records(payload)
        prefix = slugify(payload.get("objectid_prefix") or payload.get("collection_title") or "") if isinstance(payload, dict) else ""
        used = used_dg_numbers(records)
        for sibling in source.parent.parent.glob("*/gems_*.json"):
            if sibling.resolve() != source.resolve():
                try:
                    used += used_dg_numbers(iter_records(json.loads(sibling.read_text(encoding="utf-8"))))
                except (OSError, ValueError):
                    continue
        if assign_objectids(records, prefix, used) and isinstance(payload, dict):
            source.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    else:
        records = load_payload(source)
    return process_records(records, output_dir, field_map=field_map, source_system=source_system)


def process_records(
    records: list[dict[str, Any]],
    output_dir: str | Path,
    *,
    field_map: dict[str, Any] | None = None,
    source_system: str = "alma_digital",
) -> ExportResult:
    destination = Path(output_dir)
    if is_template_map(field_map):
        columns = [str(column) for column in field_map["columns"]]
        rows, exported_files = map_to_template(records, field_map, destination / "objects")
    else:
        columns = COLLECTIONBUILDER_FIELDS
        rows = normalize_records(records, field_map=field_map, source_system=source_system)
        exported_files = export_files(rows, destination / "objects")

    csv_path = destination / "collection_metadata.csv"
    json_path = destination / "normalized_records.json"
    write_collection_csv(rows, csv_path, columns)
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
        for key in (normalized_candidate, f"dc_{normalized_candidate}", f"dcterms_{normalized_candidate}"):
            if key in metadata:
                return metadata[key]
        # xsi-typed Alma elements, e.g. "dcterms:subject (dcterms:LCSH)"
        typed = next((value for key, value in metadata.items() if key.startswith(f"dcterms_{normalized_candidate}_")), None)
        if typed is not None:
            return typed
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
        fetch_object(source, objects_dir / safe_name)
        row["filename"] = safe_name
        row["objectid"] = Path("objects", safe_name).as_posix()
        count += 1
    return count


def fetch_object(source: str, destination: Path) -> None:
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"}:
        partial = destination.with_name(destination.name + ".part")
        try:
            urlretrieve(source, partial)
        except HTTPError as error:
            partial.unlink(missing_ok=True)
            expires = parse_qs(parsed.query).get("Expires", [""])[0]
            if error.code == 403 and expires.isdigit() and int(expires) < time.time():
                raise ValueError(
                    f"The download link for {destination.name} expired at "
                    f"{time.strftime('%Y-%m-%d %H:%M:%S %Z', time.localtime(int(expires)))}. "
                    "Retrieve the records again to create a manifest with fresh links."
                ) from error
            raise ValueError(f"Could not download {destination.name}: {error}") from error
        partial.replace(destination)
    elif parsed.scheme == "file":
        shutil.copy2(Path(unquote(parsed.path)), destination)
    else:
        shutil.copy2(Path(source), destination)


def is_template_map(field_map: Any) -> bool:
    return isinstance(field_map, dict) and isinstance(field_map.get("columns"), list)


DCMI_TYPES = {"image": "Still Image", "audio": "Sound", "video": "Moving Image", "pdf": "Text"}
DG_NUMBER = re.compile(r"(?:^|_)dg_(\d+)$")


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def used_dg_numbers(records: list[dict[str, Any]]) -> list[int]:
    ids: list[Any] = []
    for record in records:
        ids.append(record.get("objectid"))
        children = record.get("child_objectids")
        ids.extend(children.values() if isinstance(children, dict) else [])
    return [int(found.group(1)) for value in ids if isinstance(value, str) and (found := DG_NUMBER.search(value))]


def assign_objectids(records: list[dict[str, Any]], prefix: str, used_numbers: list[int]) -> bool:
    """Give records (and compound children) missing `<prefix>_dg_<n>` IDs; n continues from now or the highest used n."""
    number = max([int(time.time()) - 1, *used_numbers])
    changed = False

    def next_id() -> str:
        nonlocal number, changed
        number += 1
        changed = True
        return f"{prefix}_dg_{number}" if prefix else f"dg_{number}"

    for record in records:
        if not record.get("objectid"):
            record["objectid"] = next_id()
        items = representation_items(record)
        if len(items) > 1:
            children = record.get("child_objectids")
            if not isinstance(children, dict):
                children = record["child_objectids"] = {}
            for item in items:
                if not children.get(item["filename"]):
                    children[item["filename"]] = next_id()
    return changed


def map_to_template(
    records: list[dict[str, Any]],
    template_map: dict[str, Any],
    objects_dir: Path,
) -> tuple[list[dict[str, str]], int]:
    """Build one row per record, plus child rows for records with several files (CollectionBuilder compound objects)."""
    columns = [str(column) for column in template_map["columns"]]
    rules = template_map.get("rules", {})
    assign_objectids(records, "", used_dg_numbers(records))
    objects_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, str]] = []
    count = 0
    for record in records:
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        record_id = str(record["objectid"])
        items = representation_items(record)
        for item in items:
            if not (objects_dir / item["filename"]).exists():
                fetch_object(item["source"], objects_dir / item["filename"])
            count += 1
        if len(items) == 1:
            parent = file_context(items[0])
        elif items:
            child_types = {file_context(item)["dcmi_type"] for item in items}
            parent = {
                "display_template": "compound_object",
                "filenames": "; ".join(item["filename"] for item in items),
                "dcmi_type": child_types.pop() if len(child_types) == 1 else "",
            }
        else:
            parent = {"display_template": "record"}
        parent.update(objectid=record_id, parentid="")
        rows.append(build_template_row(columns, rules, record, metadata, parent, child=False))
        if len(items) > 1:
            for item in items:
                context = file_context(item)
                context.update(objectid=record["child_objectids"][item["filename"]], parentid=record_id)
                rows.append(build_template_row(columns, rules, record, metadata, context, child=True))
    return rows, count


def representation_items(record: dict[str, Any]) -> list[dict[str, str]]:
    details: dict[str, dict[str, str]] = {}
    representations = record.get("representations")
    for representation in representations if isinstance(representations, list) else []:
        files = representation.get("files") if isinstance(representation, dict) else None
        file_items = files.get("representation_file", []) if isinstance(files, dict) else []
        for file_info in file_items if isinstance(file_items, list) else [file_items]:
            if isinstance(file_info, dict) and file_info.get("label"):
                details[str(file_info["label"])] = {
                    "label": stringify(representation.get("label")),
                    "representation_id": stringify(representation.get("id")),
                }
    items = [
        {"source": file_info["source"], **details.get(file_info["filename"], {}),
         "filename": safe_filename(file_info["filename"], index)}
        for index, file_info in enumerate(extract_files(record), start=1)
    ]
    return sorted(items, key=lambda item: [
        int(token) if token.isdigit() else token.lower() for token in re.split(r"(\d+)", item["filename"])
    ])


def file_context(item: dict[str, str]) -> dict[str, str]:
    mime_type = mimetypes.guess_type(item["filename"])[0] or ""
    kind = "pdf" if mime_type == "application/pdf" else mime_type.split("/")[0]
    kind = kind if kind in DCMI_TYPES else ""
    return {
        "filename": item["filename"],
        "filenames": item["filename"],
        "label": item.get("label", ""),
        "representation_id": item.get("representation_id", ""),
        "mime_type": mime_type,
        "display_template": kind or "record",
        "dcmi_type": DCMI_TYPES.get(kind, ""),
    }


def build_template_row(
    columns: list[str],
    rules: dict[str, Any],
    record: dict[str, Any],
    metadata: dict[str, Any],
    gems: dict[str, str],
    *,
    child: bool,
) -> dict[str, str]:
    row: dict[str, str] = {}
    for column in columns:
        rule = rules.get(column)
        if child and isinstance(rule, dict) and rule.get("child") != "inherit":
            rule = rule.get("child")
        row[column] = apply_rule(rule, record, metadata, gems) if isinstance(rule, dict) else ""
    return row


def apply_rule(rule: dict[str, Any], record: dict[str, Any], metadata: dict[str, Any], gems: dict[str, str]) -> str:
    if "value" in rule:
        return stringify(rule["value"])
    sources = rule.get("from", [])
    scopes = {"metadata": metadata, "record": record, "gems": gems}
    collected: list[str] = []
    for source in [sources] if isinstance(sources, str) else sources:
        scope, _, key = str(source).partition(".")
        if scope not in scopes:
            raise ValueError(f"Unknown field map source {source!r}; use metadata.*, record.*, or gems.*")
        values = transform_values(stringify(scopes[scope].get(key)), rule)
        if values and not rule.get("combine"):
            return "; ".join(values)
        seen = {value.casefold() for value in collected}
        collected.extend(value for value in values if value.casefold() not in seen)
    return "; ".join(collected)


def transform_values(value: str, rule: dict[str, Any]) -> list[str]:
    results: list[str] = []
    for part in value.split(";") if rule.get("split", True) else [value]:
        if rule.get("strip_html"):
            part = html.unescape(re.sub(r"<[^>]+>", "", part))
        part = part.strip()
        if not part:
            continue
        if "match" in rule and not re.search(rule["match"], part):
            continue
        if "exclude" in rule and re.search(rule["exclude"], part):
            continue
        if "extract" in rule:
            found = re.search(rule["extract"], part)
            if not found:
                continue
            part = found.group(1) if found.groups() else found.group(0)
        if "replace" in rule:
            part = re.sub(rule["replace"][0], rule["replace"][1], part)
        if rule.get("capitalize"):
            part = part[:1].upper() + part[1:]
        if part.casefold() not in {existing.casefold() for existing in results}:
            results.append(part)
    return results


def write_collection_csv(
    rows: list[dict[str, str]],
    destination: Path,
    columns: list[str] = COLLECTIONBUILDER_FIELDS,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in columns})


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
