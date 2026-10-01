from __future__ import annotations

import os
import re
import xml.etree.ElementTree as element_tree
from collections.abc import Callable, Iterable
from typing import Any

import requests

REGION_URLS = {
    "America": "https://api-na.hosted.exlibrisgroup.com",
    "Europe": "https://api-eu.hosted.exlibrisgroup.com",
    "Asia Pacific": "https://api-ap.hosted.exlibrisgroup.com",
    "Canada": "https://api-ca.hosted.exlibrisgroup.com",
    "China": "https://api-cn.hosted.exlibrisgroup.com",
}


class AlmaServerError(RuntimeError):
    """Alma answered with an HTTP 5xx error."""


class AlmaClient:
    """Retrieve Alma Digital metadata using the read-only Bibs and Sets APIs."""

    def __init__(self, api_key: str | None = None, region: str | None = None, session=None) -> None:
        self.api_key = api_key or os.getenv("ALMA_API_KEY", "")
        self.region = region or os.getenv("ALMA_API_REGION", "America")
        self.base_url = REGION_URLS.get(self.region, REGION_URLS["America"])
        self.session = session or requests.Session()
        self.skipped_positions: list[int] = []
        self.skipped_errors: list[str] = []

    def fetch_set_members(self, set_id: str) -> list[str]:
        members: list[str] = []
        offset = 0
        while True:
            payload = self._get(f"/almaws/v1/conf/sets/{set_id}/members", params={"limit": 100, "offset": offset})
            page = payload.get("member", [])
            if not isinstance(page, list):
                page = [page] if page else []
            members.extend(str(member["id"]) for member in page if isinstance(member, dict) and member.get("id"))
            total = int(payload.get("total_record_count", len(members)))
            if not page or len(members) >= total:
                return members
            offset += 100

    def fetch_set_title(self, set_id: str) -> str:
        title = self._get(f"/almaws/v1/conf/sets/{set_id}").get("name")
        if not isinstance(title, str) or not title.strip():
            raise ValueError(f"Alma set {set_id} has no name; enter a collection title.")
        return title.strip()

    def resolve_collection(self, title: str) -> tuple[str, str]:
        payload = self._get("/almaws/v1/bibs/collections", params={"q": f"collection_name~{title}"})
        collections = payload.get("collection", [])
        if not isinstance(collections, list):
            collections = [collections] if collections else []
        matches = [
            item for item in collections
            if isinstance(item, dict) and isinstance(item.get("name"), str)
            and item["name"].strip().casefold() == title.casefold()
        ]
        if len(matches) != 1:
            raise ValueError(f"Found {len(matches)} Alma collections titled {title!r}; check the title.")
        pid = matches[0].get("pid")
        collection_id = pid.get("value") if isinstance(pid, dict) else pid
        if not collection_id:
            raise ValueError(f"Alma collection {title!r} has no PID.")
        return str(collection_id), matches[0]["name"].strip()

    def fetch_collection_bibs(self, collection_id: str) -> list[str]:
        """List a collection's MMS IDs, skipping (and recording in `skipped_positions`) entries Alma can't serve."""
        path = f"/almaws/v1/bibs/collections/{collection_id}/bibs"
        self.skipped_positions = []
        self.skipped_errors = []

        def page(offset: int, limit: int) -> tuple[list[Any], int | None]:
            try:
                payload = self._get(path, params={"limit": limit, "offset": offset})
            except AlmaServerError as error:
                # One bad bib fails its whole page, so narrow down to single entries and skip only those.
                if limit == 1:
                    self.skipped_positions.append(offset + 1)
                    self.skipped_errors.append(str(error))
                    return [], None
                step = max(1, limit // 10)
                bibs: list[Any] = []
                total: int | None = None
                for start in range(offset, offset + limit, step):
                    if total is not None and start >= total:
                        break
                    sub_bibs, sub_total = page(start, min(step, offset + limit - start))
                    bibs.extend(sub_bibs)
                    total = total if sub_total is None else sub_total
                return bibs, total
            bibs = payload.get("bib", [])
            return (bibs if isinstance(bibs, list) else [bibs] if bibs else []), int(payload.get("total_record_count", 0))

        mms_ids: list[str] = []
        offset = 0
        while True:
            skipped_before = len(self.skipped_positions)
            bibs, total = page(offset, 100)
            mms_ids.extend(str(bib["mms_id"]) for bib in bibs if isinstance(bib, dict) and bib.get("mms_id"))
            advanced = len(bibs) + len(self.skipped_positions) - skipped_before
            offset += advanced
            if not advanced or total is None or offset >= total:
                return mms_ids

    def fetch_records(
        self, mms_ids: Iterable[str], *, on_progress: Callable[[int, int], None] | None = None
    ) -> list[dict[str, Any]]:
        records = []
        unique_ids = list(dict.fromkeys(item.strip() for item in mms_ids if item.strip()))
        for mms_id in unique_ids:
            bib = self._get(f"/almaws/v1/bibs/{mms_id}", params={"view": "full", "expand": "None"})
            records.append(self._to_gems_record(mms_id, bib))
            if on_progress is not None:
                on_progress(len(records), len(unique_ids))
        return records

    def refresh_file_link(self, record: dict[str, Any], item: dict[str, str]) -> str:
        """Request a new signed download URL for a manifest file whose stored link has expired."""
        mms_id, representation_id, file_pid = record.get("mms_id"), item.get("representation_id"), item.get("file_pid")
        if not (mms_id and representation_id and file_pid):
            raise ValueError(f"The download link for {item.get('filename')} has expired; retrieve the records again.")
        details = self._get(
            f"/almaws/v1/bibs/{mms_id}/representations/{representation_id}/files/{file_pid}", params={"expand": "url"}
        )
        url = details.get("download_url") or details.get("url")
        if not url:
            raise ValueError(f"Alma returned no download link for {item.get('filename')}.")
        return str(url)

    def _get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.api_key:
            raise ValueError("ALMA_API_KEY is not configured.")
        response = self.session.get(
            path if path.startswith("http") else f"{self.base_url}{path}",
            headers={"Accept": "application/json", "Authorization": f"apikey {self.api_key}"},
            params=params,
            timeout=30,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as error:
            message = f"Alma API request failed for {path}: HTTP {response.status_code}"
            if response.status_code >= 500:
                tracking = re.search(r'"trackingId"\s*:\s*"([^"]+)"', response.text or "")
                raise AlmaServerError(message + (f" (Alma tracking ID {tracking.group(1)})" if tracking else "")) from error
            raise RuntimeError(message) from error
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"Alma API returned an unexpected response for {path}.")
        return payload

    def _to_gems_record(self, mms_id: str, bib: dict[str, Any]) -> dict[str, Any]:
        metadata = _extract_dc_metadata(bib.get("anies", []))
        qualified = {key.split(" (")[0] for key in metadata}
        for name, field in (("title", "title"), ("creator", "author"), ("date", "date_of_publication")):
            if not {f"dc:{name}", f"dcterms:{name}"} & qualified and bib.get(field):
                metadata[f"dc:{name}"] = str(bib[field])
        representations = self._get(f"/almaws/v1/bibs/{mms_id}/representations", params={"expand": "p_files"})
        representation_items = representations.get("representation", [])
        if not isinstance(representation_items, list):
            representation_items = [representation_items] if representation_items else []
        for representation in representation_items:
            if not isinstance(representation, dict):
                continue
            files = representation.get("files")
            if isinstance(files, dict) and files.get("link") and "representation_file" not in files:
                representation["files"] = self._get(str(files["link"]))
                files = representation["files"]
            if not isinstance(files, dict):
                continue
            file_items = files.get("representation_file", [])
            if not isinstance(file_items, list):
                file_items = [file_items] if file_items else []
            for file_info in file_items:
                if not isinstance(file_info, dict) or file_info.get("url") or file_info.get("download_url"):
                    continue
                if representation.get("id") and file_info.get("pid"):
                    details = self._get(
                        f"/almaws/v1/bibs/{mms_id}/representations/{representation['id']}/files/{file_info['pid']}",
                        params={"expand": "url"},
                    )
                    file_info.update(details)
        files = _extract_downloadable_files(representations)
        return {
            "mms_id": mms_id,
            "identifier": mms_id,
            "metadata": metadata,
            "representations": representations.get("representation", []),
            "files": files,
        }


DC_PREFIXES = {
    "http://purl.org/dc/elements/1.1/": "dc",
    "http://purl.org/dc/terms/": "dcterms",
}
XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"


def _extract_dc_metadata(anies: Any) -> dict[str, str]:
    """Key values by qualified element name plus any xsi:type, e.g. `dcterms:type (dcterms:DCMIType)`."""
    xml_values = anies if isinstance(anies, list) else [anies]
    metadata: dict[str, list[str]] = {}
    for xml_value in xml_values:
        if not isinstance(xml_value, str):
            continue
        try:
            root = element_tree.fromstring(xml_value)
        except element_tree.ParseError:
            continue
        for element in root.iter():
            namespace, _, name = element.tag[1:].rpartition("}") if element.tag.startswith("{") else ("", "", element.tag)
            prefix = DC_PREFIXES.get(namespace)
            key = f"{prefix}:{name}" if prefix else name
            if element.get(XSI_TYPE):
                key = f"{key} ({element.get(XSI_TYPE)})"
            value = (element.text or "").strip()
            if value:
                metadata.setdefault(key, []).append(value)
    return {name: "; ".join(dict.fromkeys(values)) for name, values in metadata.items()}


def _extract_downloadable_files(representations: dict[str, Any]) -> list[dict[str, str]]:
    extracted: list[dict[str, str]] = []
    items = representations.get("representation", [])
    if not isinstance(items, list):
        items = [items] if items else []
    for representation in items:
        if not isinstance(representation, dict):
            continue
        representation_files = representation.get("files", {})
        if not isinstance(representation_files, dict):
            continue
        files = representation_files.get("representation_file", [])
        if not isinstance(files, list):
            files = [files] if files else []
        for file_info in files:
            if not isinstance(file_info, dict):
                continue
            source = file_info.get("download_url") or file_info.get("url")
            if source:
                # Labels can repeat across files ("MediaTrack VTT"); the storage path name is unique and keeps the extension.
                stored_name = str(file_info.get("path") or "").rsplit("/", 1)[-1]
                if "." not in stored_name:
                    stored_name = ""
                extracted.append({"source": str(source), "filename": stored_name or str(file_info.get("label") or "object")})
    return extracted