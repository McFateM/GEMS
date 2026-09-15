# GEMS

GEMS: Gather, Export, Map, Serialize.

This repository now contains a small Flet-based application and headless pipeline for:
- loading Alma Digital / Specto exports from JSON or CSV,
- extracting digital-object identifiers, files, and structured metadata,
- mapping source metadata into CollectionBuilder-oriented fields, and
- writing a `collection_metadata.csv` plus exported objects and normalized JSON.

## Usage

### Run the Flet app

```bash
python -m gems
```

### Run headlessly

```bash
python -m gems --headless --source /path/to/export.json --output /path/to/output
```

### Optional field mapping

Pass a JSON object that maps CollectionBuilder fields to source field names:

```bash
python -m gems \
  --headless \
  --source /path/to/export.json \
  --output /path/to/output \
  --field-map '{"title": "display title", "creator": "creator name"}'
```

The export writes:
- `/path/to/output/collection_metadata.csv`
- `/path/to/output/normalized_records.json`
- `/path/to/output/objects/*`
