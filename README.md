# GEMS

GEMS: Gather, Export, Map, Serialize.

This repository now contains a small Flet-based application and headless pipeline for:
- loading Alma Digital / Specto exports from JSON or CSV,
- extracting digital-object identifiers, files, and structured metadata,
- mapping source metadata into CollectionBuilder-oriented fields, and
- writing a `collection_metadata.csv` plus exported objects and normalized JSON.

## Retrieve from Alma Digital

GEMS can retrieve records directly from Alma using the same environment-variable contract as CABB. Copy `.env.example` to `.env`, then configure `ALMA_API_KEY` and `ALMA_API_REGION`. GEMS does not store the key in its settings file.

Enter an Alma set ID to retrieve every MMS ID in the set, or paste one or more MMS IDs. GEMS retrieves the bib record, Dublin Core metadata, digital representations, and representation-file descriptors. When Alma returns a file `download_url`, GEMS downloads it into the CollectionBuilder export. The representation-file API may return descriptors without a downloadable URL; those records are still exported as metadata, and the status reports zero downloaded files.

## Import a prepared manifest

To prepare an Alma Digital collection:

1. In Alma, identify the digital representations or records you want to publish. Export their descriptive metadata using your local Alma reporting/export workflow, or retrieve it through the Alma REST API.
2. Download the corresponding original files to a local folder, or ensure their URLs can be fetched without an interactive Alma login.
3. Produce a JSON or CSV manifest that pairs every record with its object path or URL. Select that manifest as GEMS's **Prepared export manifest**.

The minimal JSON shape is:

```json
{
  "records": [
    {
      "identifier": "alma-record-123",
      "metadata": {
        "title": "Example item",
        "creator": "Example creator"
      },
      "files": [
        {
          "path": "/absolute/path/to/downloaded/item.tif",
          "filename": "item.tif"
        }
      ]
    }
  ]
}
```

`files` may also contain public `http` or `https` URLs. GEMS recognizes common metadata fields such as `title`, `creator`, `date`, `description`, `subject`, and `rights`; use the field map for institution-specific names. For a CSV, use one row per object and provide metadata columns plus a `path`, `file`, `url`, or `download_url` column.

An Alma REST connector is not included yet. It would need an API key, Alma region, and a selection strategy such as MMS IDs or collection identifiers; it should retrieve representation metadata and files into the manifest format above.

## Usage

### Run the Flet app

```bash
./run.sh
```

The launch script creates `.venv`, installs the Flet desktop dependencies, and starts GEMS. To run with an existing environment, use `python -m gems`.

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
