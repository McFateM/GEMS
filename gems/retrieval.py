from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Callable
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from .alma import AlmaClient
from .storage import atomic_json


def private_message(message: str) -> str:
    key = os.getenv("ALMA_API_KEY")
    if key:
        message = message.replace(key, "[redacted]")
    return re.sub(r"(https?://[^\s?]+)\?[^\s]+", r"\1?[redacted]", message)


def retrieve_manifest(
    destination: Path,
    *,
    client: AlmaClient,
    selection: str = "",
    collection_title: str | None = None,
    collection_id: str = "",
    mms_ids: str = "",
    on_progress: Callable[[int, int], None] | None = None,
    check_cancelled: Callable[[], None] | None = None,
) -> dict[str, Any]:
    if not destination.is_dir():
        raise ValueError(f"Destination must be an existing directory: {destination}")
    # Fail before contacting Alma if the destination is not writable.
    with tempfile.TemporaryFile(dir=destination):
        pass
    ids = [part.strip() for part in re.split(r"[,\n]", mms_ids) if part.strip()]
    selection = (collection_title if collection_title is not None else selection).strip()
    if not ids and not selection:
        raise ValueError("Enter an Alma set ID, collection title, or MMS IDs.")
    set_id = ""
    title = "MMS ID selection"
    if not ids:
        if collection_id:
            if not collection_id.isascii() or not collection_id.isdecimal() or not selection:
                raise ValueError("A numeric collection PID and a collection title label are required.")
            title = selection
            ids = client.fetch_collection_bibs(collection_id)
        elif selection.isdecimal() and collection_title is None:
            set_id = selection
            title = client.fetch_set_title(set_id)
            ids = client.fetch_set_members(set_id)
        else:
            collection_id, title = client.resolve_collection(selection)
            ids = client.fetch_collection_bibs(collection_id)
    ids = list(dict.fromkeys(value.strip() for value in ids if value.strip()))
    if not ids:
        raise ValueError("No Alma records were found for that selection.")
    if check_cancelled:
        check_cancelled()
    messages: list[str] = []
    milestone = -1

    def progress(done: int, total: int) -> None:
        nonlocal milestone
        if check_cancelled:
            check_cancelled()
        current = done * 10 // total if total else 10
        if current > milestone:
            milestone = current
            messages.append(f"Retrieving Alma records: {current * 10}% ({done}/{total})")
            if on_progress:
                on_progress(done, total)

    records = client.fetch_records(ids, on_progress=progress)
    if check_cancelled:
        check_cancelled()
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40].strip("-") or "collection"
    group = (f"set-{slug}-{set_id}" if set_id else f"collection-{slug}-{collection_id}" if collection_id
             else f"mms-ids-{sha256(','.join(sorted(ids)).encode()).hexdigest()[:12]}")
    created = datetime.now().astimezone()
    parent = destination / group
    parent.mkdir(exist_ok=True)
    run_name = f"{created:%Y-%m-%d_%H-%M-%S_%Z}"
    run = parent / run_name
    suffix = 0
    while True:
        try:
            run.mkdir()
            break
        except FileExistsError:
            suffix += 1
            run = parent / f"{run_name}-{suffix}"
    manifest = run / f"gems_{slug}_{run.name}.json"
    payload: dict[str, Any] = dict(collection_title=title, created_at=created.isoformat(),
                                   retrieval={"available_records": len(ids)}, records=records)
    if set_id:
        payload["alma_set_id"] = set_id
    if collection_id:
        payload["alma_collection_pid"] = collection_id
    atomic_json(manifest, payload)
    warnings = [private_message(str(error)) for error in client.skipped_errors]
    messages.extend(f"Skipped collection entry: {warning}" for warning in warnings)
    messages.append(f"Manifest contains {len(records)} Alma records")
    (run / "gems.log").write_text(
        "\n".join(f"{created.isoformat()} {message}" for message in messages) + "\n", encoding="utf-8",
    )
    return dict(manifest=str(manifest), collection_title=title, records=len(records), available_records=len(ids),
                skipped_positions=list(client.skipped_positions), warnings=warnings)
