from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .pipeline import (
    COLLECTIONBUILDER_FIELDS, FIELD_ALIASES, CancelCheck, ExportCancelled,
    ProgressCallback, is_template_map, normalize_key, stringify,
)

DC_FIELDS = {
    "title", "creator", "subject", "description", "publisher", "contributor", "date",
    "type", "format", "identifier", "source", "language", "relation", "coverage", "rights",
}


def load_omeka(
    source: Path, *, resolve_media: bool = False,
    progress: ProgressCallback | None = None, is_cancelled: CancelCheck | None = None,
) -> list[dict[str, Any]]:
    with requests.Session() as session:
        retries = Retry(total=3, backoff_factor=0.5, status_forcelist=(429, 500, 502, 503, 504),
                        allowed_methods=frozenset({"GET"}))
        session.mount("https://", HTTPAdapter(max_retries=retries))
        session.mount("http://", HTTPAdapter(max_retries=retries))
        return _load_omeka(source, session, resolve_media=resolve_media,
                           progress=progress, is_cancelled=is_cancelled)


def _load_omeka(
    source: Path, session: requests.Session, *, resolve_media: bool,
    progress: ProgressCallback | None, is_cancelled: CancelCheck | None,
) -> list[dict[str, Any]]:
    if source.suffix.lower() != ".json":
        raise ValueError("Omeka input must be a JSON export.")
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Malformed Omeka JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}") from exc
    if isinstance(payload, dict):
        for key in ("items", "records", "data", "@graph"):
            if key in payload:
                payload = payload[key]
                break
        else:
            payload = [payload]
    if not isinstance(payload, list):
        raise ValueError("Omeka export must contain an item object or an array of items.")
    records: list[dict[str, Any]] = []
    resolved: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(payload, start=1):
        if is_cancelled is not None and is_cancelled():
            raise ExportCancelled()
        if not isinstance(item, dict):
            raise ValueError(f"Omeka item {index} must be a JSON object.")
        if "element_texts" in item:
            system = "omeka_classic"
        elif "o:media" in item or "o:Item" in values(item.get("@type")) or any(key.startswith("dcterms:") for key in item):
            system = "omeka_s"
        else:
            raise ValueError(f"Unrecognized Omeka item {index}: expected element_texts or an Omeka S item with o:media.")
        source_id = stringify(item.get("o:id") if system == "omeka_s" else item.get("id"))
        context = f"{system} item {source_id or f'at position {index}'}"
        metadata: dict[str, list[str]] = {}
        if system == "omeka_classic":
            texts = item["element_texts"]
            if not isinstance(texts, list):
                raise ValueError(f"{context}: element_texts must be an array.")
            for text in texts:
                if not isinstance(text, dict) or not isinstance(text.get("element"), dict):
                    raise ValueError(f"{context}: each element_texts entry needs an element name and text.")
                element_set = text.get("element_set", {})
                if isinstance(element_set, dict) and element_set.get("name", "Dublin Core") != "Dublin Core":
                    continue
                name = normalize_key(stringify(text["element"].get("name")))
                if name in DC_FIELDS:
                    metadata.setdefault(name, []).extend(values(text.get("text")))
            raw_media = item.get("files_list", item.get("files", []))
            if isinstance(raw_media, dict) and raw_media.get("count") == 0:
                raw_media = []
        else:
            for key, value in item.items():
                if key.startswith(("dcterms:", "dc:")):
                    name = key.split(":", 1)[1]
                    metadata.setdefault(name, []).extend(values(value))
            raw_media = item.get("o:media", [])
        if not isinstance(raw_media, list):
            raise ValueError(f"{context}: export must embed a media array (files_list or o:media), not an API listing link.")
        files: list[dict[str, str]] = []
        for media_index, media in enumerate(raw_media, start=1):
            if is_cancelled is not None and is_cancelled():
                raise ExportCancelled()
            if not isinstance(media, dict):
                raise ValueError(f"{context}, media {media_index}: expected an embedded file object.")
            if system == "omeka_s" and not media.get("o:original_url") and media.get("@id"):
                if not resolve_media:
                    # Offline previews need only item/file counts, not downloadable URLs.
                    files.append({"source": "", "filename": ""})
                    continue
                reference = media["@id"]
                if not isinstance(reference, str) or urlparse(reference).scheme not in {"http", "https"}:
                    raise ValueError(f"{context}, media {media_index}: media API reference must be an HTTP(S) URL.")
                if reference not in resolved:
                    if progress is not None:
                        progress(f"Resolving {context}, media {media_index} of {len(raw_media)}", index - 1, len(payload))
                    resolved[reference] = resolve_media_reference(session, reference, context, media_index)
                media = {**media, **resolved[reference]}
            urls = media.get("file_urls") or {}
            if not isinstance(urls, dict):
                raise ValueError(f"{context}, media {media_index}: file_urls must be an object.")
            original = media.get("o:original_url") or urls.get("original")
            url = original or urls.get("fullsize")
            if not isinstance(url, str) or urlparse(url).scheme not in {"http", "https", "file"}:
                raise ValueError(
                    f"{context}, media {media_index}: missing accessible original/fullsize media URL. "
                    "Provide an original asset URL or an Omeka S media API reference that returns o:original_url."
                )
            url_name = Path(unquote(urlparse(url).path)).name
            name = media.get("o:filename") or media.get("original_filename") or media.get("filename") or url_name
            media_source = media.get("o:source")
            if name == url_name and isinstance(media_source, str) and not urlparse(media_source).scheme and Path(media_source).suffix:
                name = media_source
            if not isinstance(name, str):
                raise ValueError(f"{context}, media {media_index}: filename must be text.")
            # A fullsize derivative may have a different format than the unavailable original.
            if not original and Path(name).suffix.lower() != Path(url_name).suffix.lower():
                name = url_name
            files.append({"source": url, "filename": name or f"object-{media_index}"})
        flattened = {key: "; ".join(dict.fromkeys(value)) for key, value in metadata.items()}
        for key, value in list(flattened.items()):
            flattened[f"dcterms:{key}"] = value
            if key in DC_FIELDS:
                flattened[f"dc:{key}"] = value
        records.append({
            "metadata": flattened,
            "files": files,
            "source_system": system,
            "source_record_id": f"{system}-{source_id or 'item'}-{index}",
            "source_record_url": stringify(item.get("@id") or item.get("url")),
            "originating_system_id": source_id,
        })
    return records


def resolve_media_reference(
    session: requests.Session, reference: str, context: str, media_index: int,
) -> dict[str, Any]:
    try:
        with session.get(reference, timeout=30) as response:
            response.raise_for_status()
            payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise ValueError(
            f"{context}, media {media_index}: could not resolve media API reference {reference}: {exc}. "
            "Check network access and whether the media API is public."
        ) from exc
    if not isinstance(payload, dict) or not payload.get("o:original_url"):
        raise ValueError(
            f"{context}, media {media_index}: media API reference {reference} did not return an "
            "o:original_url. Export a stored physical media file; HTML, private, and non-file media are unsupported."
        )
    return payload


def values(value: Any) -> list[str]:
    if isinstance(value, list):
        return [text for entry in value for text in values(entry)]
    if isinstance(value, dict):
        if "@value" in value:
            return values(value["@value"])
        return values(value.get("@id") or value.get("display_title"))
    return [str(value).strip()] if isinstance(value, (str, int, float)) and str(value).strip() else []


def asset_field_map(field_map: dict[str, Any] | None) -> dict[str, Any]:
    if field_map is not None and not isinstance(field_map, dict):
        raise ValueError("The field map must be a JSON object.")
    if is_template_map(field_map):
        template = dict(field_map or {})
        if not isinstance(template.get("rules", {}), dict):
            raise ValueError('A template field map needs a "rules" object keyed by column name.')
        if not all(isinstance(column, str) for column in template["columns"]):
            raise ValueError("Template columns must be text field names.")
        template["columns"] = [column for column in template["columns"] if column not in {"objectid", "parentid"}]
        if any(str(column).startswith(("dc_", "dcterms_")) for column in template["columns"]):
            raise ValueError("Omeka output requires canonical, unprefixed metadata columns, not dc_ or dcterms_ headers.")
        if "original_file_name" not in template["columns"]:
            template["columns"].append("original_file_name")
        return template
    if field_map and not all(isinstance(value, str) for value in field_map.values()):
        raise ValueError("A simple field map must map field names to source field names as text.")
    columns = [column for column in COLLECTIONBUILDER_FIELDS if column != "objectid"]
    columns += ["contributor", "original_file_name", "originating_system_id"]
    rules: dict[str, Any] = {}
    for column in columns:
        aliases = FIELD_ALIASES.get(column, (column,))
        if field_map and column in field_map:
            aliases = (field_map[column], *aliases)
        rules[column] = {"from": [f"metadata.{alias}" for alias in aliases], "split": False}
    for column in ("source_system", "source_record_url", "originating_system_id"):
        rules[column] = {"from": f"record.{column}"}
    return {"columns": columns, "rules": rules}
