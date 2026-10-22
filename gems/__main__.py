from __future__ import annotations

import argparse
import json
import os

from .alma import AlmaClient
from .pipeline import process_export


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
    args = parser.parse_args()

    if args.source or args.output or args.headless:
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

    from .app import launch

    launch()
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
