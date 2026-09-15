from __future__ import annotations

import os
import xml.etree.ElementTree as element_tree
from collections.abc import Iterable
from typing import Any

import requests

REGION_URLS = {
    "America": "https://api-na.hosted.exlibrisgroup.com",
    "Europe": "https://api-eu.hosted.exlibrisgroup.com",
    "Asia Pacific": "https://api-ap.hosted.exlibrisgroup.com",
    "Canada": "https://api-ca.hosted.exlibrisgroup.com",
    "China": "https://api-cn.hosted.exlibrisgroup.com",
}


class AlmaClient:
    """Retrieve Alma Digital metadata using the read-only Bibs and Sets APIs."""

    def __init__(self, api_key: str | None = None, region: str | None = None, session=None) -> None:
        self.api_key = api_key or os.getenv("ALMA_API_KEY", "")
        self.region = region or os.getenv("ALMA_API_REGION", "America")
        self.base_url = REGION_URLS.get(self.region, REGION_URLS["America"])
        self.session = session or requests.Session()

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

    def fetch_records(self, mms_ids: Iterable[str]) -> list[dict[str, Any]]:
        records = []
        for mms_id in dict.fromkeys(item.strip() for item in mms_ids if item.strip()):
            bib = self._get(f"/almaws/v1/bibs/{mms_id}", params={"view": "full", "expand": "None"})
            records.append(self._to_gems_record(mms_id, bib))
        return records

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
            raise RuntimeError(f"Alma API request failed for {path}: HTTP {response.status_code}") from error
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"Alma API returned an unexpected response for {path}.")
        return payload

    def _to_gems_record(self, mms_id: str, bib: dict[str, Any]) -> dict[str, Any]:
        metadata = _extract_dc_metadata(bib.get("anies", []))
        metadata.setdefault("title", str(bib.get("title", "")))
        metadata.setdefault("creator", str(bib.get("author", "")))
        metadata.setdefault("date", str(bib.get("date_of_publication", "")))
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
        files = _extract_downloadable_files(representations)
        return {
            "mms_id": mms_id,
            "identifier": mms_id,
            "metadata": metadata,
            "representations": representations.get("representation", []),
            "files": files,
        }


def _extract_dc_metadata(anies: Any) -> dict[str, str]:
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
            name = element.tag.rsplit("}", 1)[-1]
            value = (element.text or "").strip()
            if value:
                metadata.setdefault(name, []).append(value)
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
                extracted.append({"source": str(source), "filename": str(file_info.get("label") or "object")})
    return extracted