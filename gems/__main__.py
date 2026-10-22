from __future__ import annotations

import argparse
import json
import os

from .alma import AlmaClient
from .pipeline import process_export
from .storage import Storage, load_environment


def cli() -> int:
    parser = argparse.ArgumentParser(description="GEMS: Gather, Export, Map, Serialize")
    parser.add_argument("--source", help="Path to an Alma / Specto manifest or Omeka JSON export")
    parser.add_argument("--source-type", choices=("alma", "omeka"), default="alma",
                        help="Input adapter: alma (existing manifest workflow) or omeka (Classic or S JSON)")
    parser.add_argument("--output", help="Directory for exported objects and collection_metadata.csv")
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

    if args.source or args.output or args.headless:
        if args.web or args.desktop:
            parser.error("UI modes cannot be combined with headless export arguments")
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
                refresh_source=AlmaClient().refresh_file_link if args.source_type == "alma" and os.getenv("ALMA_API_KEY") else None,
            )
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
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
