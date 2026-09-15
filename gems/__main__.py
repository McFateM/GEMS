from __future__ import annotations

import argparse
import json

from .app import launch
from .pipeline import process_export


def cli() -> int:
    parser = argparse.ArgumentParser(description="GEMS: Gather, Export, Map, Serialize")
    parser.add_argument("--source", help="Path to an Alma Digital / Specto export (.json or .csv)")
    parser.add_argument("--output", help="Directory for exported objects and collection_metadata.csv")
    parser.add_argument(
        "--field-map",
        default="{}",
        help="JSON mapping of CollectionBuilder fields to source metadata fields",
    )
    parser.add_argument("--source-system", default="alma_digital", help="Label stored in the output CSV")
    parser.add_argument("--headless", action="store_true", help="Run without starting the Flet UI")
    args = parser.parse_args()

    if args.source or args.output or args.headless:
        if not args.source or not args.output:
            parser.error("--source and --output are required in headless mode")
        result = process_export(
            args.source,
            args.output,
            field_map=json.loads(args.field_map),
            source_system=args.source_system,
        )
        print(
            f"Exported {result.row_count} row(s), {result.file_count} file(s), "
            f"CSV: {result.csv_path}, JSON: {result.json_path}"
        )
        return 0

    launch()
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
