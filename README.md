# GEMS

GEMS: Gather, Export, Map, Serialize.

> Running GEMS/DART on a remote Windows workstation inside the campus network?
> See [REMOTE_WINDOWS.md](../Remote-Desktop/REMOTE_WINDOWS.md) in the sibling
> Remote-Desktop repository for the RDP connection guide and
> the one-command Windows bootstrap script.

This repository now contains a small Flet-based application and headless pipeline for:
- loading Alma Digital / Specto exports from JSON or CSV,
- extracting digital-object identifiers, files, and structured metadata,
- mapping source metadata into CollectionBuilder-oriented fields, and
- writing a `collection_metadata.csv` plus exported objects and normalized JSON.

## Retrieve from Alma Digital

GEMS can retrieve records directly from Alma using the same environment-variable contract as CABB. Copy `.env.example` to `.env`, then configure `ALMA_API_KEY` and `ALMA_API_REGION`. GEMS does not store the key in its settings file.

Enter a numeric Alma set ID or an exact collection title in the single input. Numeric IDs retrieve set members; text titles find an Alma bibliographic collection and retrieve its bibs. If you enter MMS IDs instead, GEMS retrieves only those IDs and ignores the set/collection field. GEMS retrieves the bib record, Dublin Core metadata, digital representations, and representation-file descriptors. GEMS requests signed download URLs for representation files and downloads them during the CSV export. Signed URLs expire after about an hour. When a stored link has expired, GEMS asks Alma for a fresh one just before downloading that file, so batches can be mapped long after the manifest was created.

During retrieval, the status strip reports progress at 10% milestones based on unique MMS IDs and records the updates in the activity log.

Retrieval and manifests always cover the entire set, collection, or MMS-ID list. If Alma cannot list some collection entries, GEMS skips them and reports their positions.

In the **Map Manifest to CSV** section, **Start record** (1-based, default 1) and **Record limit** (leave blank for all) choose which manifest records button 2 maps and downloads. For example, with a limit of 100, use starts 1, 101, 201, and so on. Both values are remembered. Each batch is merged into the run's single `collection_metadata.csv` in manifest order. Re-mapping a range replaces those records' rows and leaves the others intact.

Before using button 1, set **Destination folder** in the Retrieve from Alma section to an existing parent folder such as `/Volumes/DGIngest/.GEMS-data`. The folder is remembered and checked before GEMS contacts Alma. **1) Retrieve from Alma and Save JSON Manifest** retrieves the records and immediately saves them. It creates a persistent `collection-<title>-<pid>/`, `set-<title>-<id>/`, or `mms-ids-<hash>/` folder in the destination. If the destination can't be written when retrieval finishes, the manifest is saved under `~/.GEMS-data/unsaved-manifests/` instead. Each run gets its own readable local-time subdirectory, such as `2026-09-30_11-52-42_CDT/`, containing the manifest and `gems.log`. The manifest includes `collection_title`, local-time `created_at` (ISO 8601 with UTC offset), the retrieval's `available_records` count, optional `alma_set_id` or `alma_collection_pid`, and the retrieved `records` array. GEMS selects the new manifest automatically. In the **Map Manifest to CSV** section, optionally choose a JSON field map, then use **2) Map and Export Manifest to CSV** to write `collection_metadata.csv`, `normalized_records.json`, and `objects/` into the folder containing the manifest. Run button 2 again with the next **Start record** to map the next batch into the same CSV. Each use of button 1 creates a new manifest and timestamped run under the destination folder. Existing runs remain intact.

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

## Usage

### Run the Flet app

```bash
./run.sh
```

The launch script creates `.venv`, installs everything in `python_requirements.txt`, and starts GEMS. To run with an existing environment, use `python -m gems`.

The status strip at the bottom shows progress, results, and errors for retrieval and export. Use its copy button to copy the current status message. Its activity-log button reads the current run's `gems.log` after a manifest is saved; startup and pre-run messages remain in `~/.GEMS-data/logfiles/gems.log`.

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

A field map may instead be a *template map*: a JSON object with an ordered `columns` list and per-column `rules`. It writes a CSV with exactly those columns, including compound-object parent/child rows. [maps/alma-dc-to-grinnell.json](maps/alma-dc-to-grinnell.json) targets the Grinnell CollectionBuilder template. Its rule syntax and mapping decisions are documented in [maps/alma-dc-to-grinnell.md](maps/alma-dc-to-grinnell.md). Headless: `--field-map "$(cat maps/alma-dc-to-grinnell.json)"`. Optionally set **Legacy MODS folder** (headless: `--legacy-mods /path/to/DG-Exports`) so the map can fill fields that are empty in Alma from the legacy Digital Grinnell MODS files. Values present in Alma are never overridden.

The export writes:
- `/path/to/output/collection_metadata.csv`
- `/path/to/output/normalized_records.json`
- `/path/to/output/objects/*`

The `transcripts/<objectid>.csv` timed-text files keep their fixed `timestamp,speaker,words` shape.
