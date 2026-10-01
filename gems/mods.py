from __future__ import annotations

import json
import re
import xml.etree.ElementTree as element_tree
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

MODS_NS = {"m": "http://www.loc.gov/mods/v3"}
CREATOR_ROLES = {"author", "creator", "photographer", "artist"}
LEGACY_PID = re.compile(r"^([A-Za-z][\w-]*):(\d+)$")


def legacy_collection_folder(dginfo: str) -> str:
    """Folder name from the migration `dginfo` directory, e.g. `social-justice`."""
    try:
        # Alma stores this JSON with every quote escaped as /"
        directory = json.loads(dginfo.replace('/"', '"')).get("directory", "")
    except (ValueError, AttributeError):
        return ""
    return PurePosixPath(urlparse(str(directory)).path).name


def find_legacy_mods(root: Path, legacy_pid: str, dginfo: str = "") -> Path | None:
    found = LEGACY_PID.match(legacy_pid)
    if not found:
        return None
    name = f"{found.group(1)}_{found.group(2)}_MODS.xml"
    folder = legacy_collection_folder(dginfo)
    for candidate in ([root / folder / name] if folder else []) + [root / name]:
        if candidate.is_file():
            return candidate
    return None


def read_legacy_mods(path: Path) -> dict[str, str]:
    root = element_tree.parse(path).getroot()
    values: dict[str, list[str]] = {}

    def add(key: str, text: str | None) -> None:
        text = " ".join((text or "").split())
        if text and text not in values.setdefault(key, []):
            values[key].append(text)

    for element in root.findall("m:physicalDescription/m:extent", MODS_NS):
        add("extent", element.text)
    for element in root.findall("m:physicalDescription/m:form", MODS_NS):
        add("form", element.text)
    for element in root.findall("m:genre", MODS_NS):
        add("genre", element.text)
    for name in root.findall("m:name", MODS_NS):
        kind = name.get("type")
        if kind not in {"personal", "corporate"}:
            continue
        roles = {(term.text or "").strip().lower() for term in name.findall("m:role/m:roleTerm", MODS_NS)}
        group = "creator" if roles & CREATOR_ROLES else "contributor"
        add(f"{group}_{kind}", ", ".join(part.text.strip() for part in name.findall("m:namePart", MODS_NS) if part.text and part.text.strip()))
    return {key: "; ".join(items) for key, items in values.items() if items}
