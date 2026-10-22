from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from requests import RequestException

from .alma import AlmaClient
from .pipeline import process_export
from .retrieval import private_message, retrieve_manifest
from .storage import Storage, load_environment


def cli() -> int:
    parser = argparse.ArgumentParser(description="GEMS: Gather, Export, Map, Serialize")
    parser.add_argument("--source", help="Path to an Alma / Specto manifest or Omeka JSON export")
    parser.add_argument("--source-type", choices=("alma", "omeka"), default="alma",
                        help="Input adapter: alma (existing manifest workflow) or omeka (Classic or S JSON)")
    parser.add_argument("--output", help="Existing parent directory for --retrieve; export directory for --source")
    parser.add_argument("--retrieve", action="store_true", help="Button 1: retrieve Alma records and save a JSON manifest")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--set-id", help="Alma set ID to retrieve")
    selection.add_argument("--collection-title", help="Exact Alma collection title to retrieve")
    selection.add_argument("--mms-ids", help="Comma-separated or newline-separated Alma MMS IDs to retrieve")
    parser.add_argument(
        "--field-map",
        default="{}",
        help="JSON mapping of CollectionBuilder fields to source metadata fields",
    )
    parser.add_argument("--source-system", default="alma_digital", help="Label stored in the output CSV")
    parser.add_argument(
        "--legacy-mods",
        help="Folder of legacy Digital Grinnell MODS exports; used only to fill fields empty in Alma",
    )
    parser.add_argument("--start", type=int, default=1, help="First manifest record to map (1-based)")
    parser.add_argument("--limit", type=int, help="Number of manifest records to map (default: all)")
    parser.add_argument("--objectid-prefix", help="Prefix for newly assigned Alma object IDs (button 2)")
    parser.add_argument("--headless", action="store_true", help="Run without starting the Flet UI")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--web", action="store_true", help="Run the private browser service")
    modes.add_argument("--desktop", action="store_true", help="Run the desktop UI (default)")
    parser.add_argument("--port", type=int, default=8550, help="Web loopback listener port (default: 8550)")
    parser.add_argument("--env-file", help="Private environment file, e.g. on a protected network share")
    parser.add_argument("--init-storage", action="store_true", help="Initialize markers in configured storage roots, then exit")
    args = parser.parse_args()
    try:
        load_environment(args.env_file)
        if args.init_storage:
            Storage.from_environment().initialize()
            print("GEMS storage initialized.")
            return 0
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    if (args.set_id is not None or args.collection_title is not None or args.mms_ids is not None) and not args.retrieve:
        parser.error("--set-id, --collection-title, and --mms-ids require --retrieve")

    if args.source or args.output or args.headless or args.retrieve:
        if args.web or args.desktop:
            parser.error("UI modes cannot be combined with headless retrieval or export arguments")
        if args.retrieve:
            if args.source or args.source_type != "alma":
                parser.error("--retrieve cannot be combined with --source or --source-type omeka")
            if not args.output:
                parser.error("--output is required with --retrieve")
            if args.start != 1 or args.limit is not None or args.field_map != "{}" or args.legacy_mods or args.objectid_prefix:
                parser.error("Mapping options apply to button 2 only; --retrieve always retrieves the whole selection")
            if args.set_id is not None and not args.set_id.isdecimal():
                parser.error("--set-id must be numeric")
            if not (args.set_id or (args.collection_title or "").strip() or (args.mms_ids or "").strip()):
                parser.error("--retrieve requires --set-id, --collection-title, or --mms-ids")

            def progress(done: int, total: int) -> None:
                print(f"Retrieving Alma records: {done * 100 // total if total else 100}% ({done}/{total})",
                      file=sys.stderr, flush=True)

            try:
                retrieval_result = retrieve_manifest(
                    Path(args.output).expanduser(), client=AlmaClient(),
                    selection=args.set_id or args.collection_title or "", mms_ids=args.mms_ids or "",
                    collection_title=args.collection_title,
                    on_progress=progress,
                )
            except (OSError, ValueError, RuntimeError, RequestException) as exc:
                parser.error(private_message(str(exc)))
            for warning in retrieval_result["warnings"]:
                print(f"Warning: {warning}", file=sys.stderr)
            if retrieval_result["skipped_positions"]:
                print(f"Warning: skipped collection positions: {retrieval_result['skipped_positions']}", file=sys.stderr)
            print(f"Saved {retrieval_result['records']} Alma record(s). Manifest: {retrieval_result['manifest']}")
            return 0
        if not args.source or not args.output:
            parser.error("--source and --output are required in headless mode")
        try:
            result = process_export(
                args.source,
                args.output,
                field_map=json.loads(args.field_map),
                source_system=args.source_system,
                source_type=args.source_type,
                legacy_mods_dir=args.legacy_mods,
                start=args.start,
                limit=args.limit,
                objectid_prefix=args.objectid_prefix,
                refresh_source=AlmaClient().refresh_file_link if args.source_type == "alma" and os.getenv("ALMA_API_KEY") else None,
            )
        except (OSError, ValueError, RuntimeError, RequestException) as exc:
            parser.error(private_message(str(exc)))
        print(
            f"Exported {result.row_count} row(s), {result.file_count} file(s), "
            f"CSV: {result.csv_path}, JSON: {result.json_path}"
        )
        if result.skipped_records:
            print(f"Skipped {len(result.skipped_records)} item(s) without media: {', '.join(result.skipped_records)}")
        return 0

    if args.web:
        if not 1 <= args.port <= 65535:
            parser.error("--port must be between 1 and 65535")
        from .web import launch

        launch(port=args.port)
    else:
        if os.getenv("GEMS_CONFIG_DIR") or os.getenv("GEMS_DATA_DIR"):
            Storage.from_environment().check()
        from .app import launch

        launch()
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
