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

### Audit an Alma XML record's CSV mapping

Run the reusable mapping audit from the repository root:

```bash
.venv/bin/python -m gems.mapping_audit /path/to/record.xml \
  --mms-id 991011597366604641 \
  --output /path/to/mapping-table.md
```

Omit `--output` to print Markdown for copying into a context document. Use `-`
instead of an input path to read XML from standard input. `--field-map /path/to/map.json`
selects another GEMS template map; the default is
[maps/alma-dc-to-grinnell.json](maps/alma-dc-to-grinnell.json).
The optional `--mms-id` supplies Alma's top-level record ID; the audit does not
guess it from XML identifiers.

The report lists every XML element occurrence, its target columns, actual mapped
values, and omissions caused by missing rules, filters, or source precedence.
It also lists target columns without an XML-derived value. It evaluates the main
bib row using the same parser and rules as GEMS, without contacting Alma,
downloading files, generating IDs, or reading legacy MODS. Representation-file
values and MODS fallbacks require those additional sources and are not inferred.

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

The default remains the Mac/desktop UI; `./run.sh --desktop` selects it explicitly.
On first use, the script creates `.venv` and installs the selected runtime.
Subsequent launches do not install or upgrade packages. Use `./run.sh --install`
when setting up another mode or after changing dependencies:

```bash
./run.sh --install --desktop
./run.sh --install --web --env-file /mounted/private/gems.env
```

`python_requirements.txt` remains the desktop installation entry point.
Packaging separates the core pipeline (`pip install -e .`), desktop
(`pip install -e '.[desktop]'`), and web (`pip install -e '.[web]'`) runtimes.
The headless CLI does not import Flet. To run with an existing environment,
use `python -m gems` with the same switches. `GEMS_PYTHON` selects the interpreter
when the script creates a new environment; Python 3.11+ is required.

The status strip at the bottom shows progress, results, and errors for retrieval and export. Use its copy button to copy the current status message. Its activity-log button reads the current run's `gems.log` after a manifest is saved; startup and pre-run messages remain in `~/.GEMS-data/logfiles/gems.log`.

### Linux/Web service and network storage

For the ordered installation, legacy-data migration, acceptance testing, and
development procedure, follow [Installing GEMS on dg-landing](INSTALL-LINUX.md).

The `linux` branch adds a private, single-operator Flet web service with durable
job history. It is **not a public, multi-user service**. It listens only on
`127.0.0.1` (default port 8550), launches no desktop/browser on the server, and
requires explicit configuration and data directories. Both directories must
already exist on administrator-provisioned network mounts. No data is moved
automatically, and web mode never falls back to the server home or checkout.

Example private environment file, stored outside Git on protected storage:

```dotenv
GEMS_CONFIG_DIR=/mnt/workflow/gems/config
GEMS_DATA_DIR=/mnt/workflow/gems/data
ALMA_API_REGION=America
ALMA_API_KEY=replace-with-authorized-key
```

These are examples, not selected deployment paths. The service account needs
read/write access to both roots. Restrict roots, secrets, and backups to approved
operators. Use restrictive share ACLs as well as POSIX permissions. Set
`umask 077` for manual service launches.

On the Linux host, after provisioning and verifying the mounts:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[web]'
.venv/bin/python -m pip check
# Explicit one-time provisioning, AFTER verifying these are the intended shares:
.venv/bin/python -m gems --init-storage --env-file /mounted/private/gems.env
./run.sh --web --env-file /mounted/private/gems.env
```

`--init-storage` places a `.gems-storage` marker in each configured root.
Normal startup and job writes require these markers and successful write probes.
Missing/unwritable storage fails explicitly; do not initialize an unmounted
mountpoint to bypass this check. Markers detect ordinary missing mounts, not all
network-filesystem failures. Mount supervision remains an administrator task.
If storage fails during a job and its failure state cannot be persisted, the
browser and stderr report a write-blocked service. Restore storage and restart;
the last persisted unfinished state becomes **interrupted**, not successful.
An already-started file operation cannot be rolled back, and a hard-mounted
network filesystem can block inside the OS until the mount recovers.

On the operator workstation, open the SSH tunnel and then the browser:

```bash
ssh -N -o ExitOnForwardFailure=yes -L 8550:127.0.0.1:8550 dg-landing
# Open http://127.0.0.1:8550 on this workstation.
```

Use `--port 8551` and a matching tunnel if 8550 is occupied. A non-loopback
`FLET_SERVER_IP` override is rejected. The CLI-selected port takes precedence
over `FLET_SERVER_PORT`.

#### Browser workflow and job lifecycle

- All paths are **server paths**. There are no native file/directory pickers or
  uploads. Copy prepared manifests, originals, and MODS into the data share,
  and copy your chosen field map into the configuration or data share.
  Workstation `/Volumes/...` paths embedded in manifests must be reviewed and
  translated to Linux-mounted paths before mapping.
- Step 1 retrieves the **whole** set, exact collection title, or MMS-ID selection.
  It preserves collection/set grouping, timestamped run directories, retrieval
  counts, and skipped-entry warnings. There is no local emergency-manifest path.
- Select the completed retrieval job and click **Use this retrieved manifest
  for step 2**, or enter a prepared manifest path. Step 2 uses the existing
  pipeline, writes beside the manifest, and retains 1-based range selection,
  template-map batch merging, persisted IDs, filename-clash reporting, MODS
  precedence, and signed-link refresh.
- The service owns one background worker. Jobs continue after tab closure.
  History, inputs, progress, results, errors, and timestamps persist in
  `GEMS_DATA_DIR/jobs/<job-id>.json`; bounded log viewing reads the last 32 KiB
  of the matching job log. Run-level summaries also appear in `gems.log`.
  Preferences persist on submission in `GEMS_CONFIG_DIR/web-settings.json`,
  separately from desktop `settings.json`. Secrets are not stored in either.
- The job URL `/jobs/<job-id>` and history dropdown recover status on refresh or
  reconnect. New sessions can select any persisted job. One browser session
  holds the operator lease; other tabs are read-only. Closing/disconnecting the
  operator tab releases that lease, not the running job.
- Only one retrieval/export may run at a time, even across tabs. Cancellation is
  cooperative: wait for the current network operation/file; discovery may finish
  before retrieval notices cancellation. The worker retains its slot until it
  actually stops. Basic and template-map exports both support cancellation.
- Graceful shutdown requests cancellation and waits for the worker. Forced
  termination, power loss, or service restart marks queued/running/cancelling
  jobs **interrupted** on next startup. Review partial output and submit a new
  job explicitly; automatic resume/retry is intentionally not implemented.
- Outputs stay on the private share. The UI displays result paths and logs;
  it does not publicly serve originals, offer artifact downloads, or expose
  metadata-refresh/shelf-backfill maintenance operations.

Job state uses atomic same-directory JSON replacement rather than SQLite WAL,
which is unsuitable for many network mounts. The filesystem must support
reliable POSIX advisory file locks, atomic rename, and file/directory `fsync`.
The service holds an exclusive data-root lock for its entire lifetime; a second
service process using that root fails startup. Verify these semantics on the
actual NFS/SMB mount before deployment. Do not run desktop, CLI, maintenance,
DART, or another host against the same active output tree; those independent
tools do not participate in this service's lock.

#### Configuration, secrets, and desktop migration

`--env-file` (or `GEMS_ENV_FILE`) selects a required, explicit environment file.
Without it, the checkout's existing `.env` remains available for desktop
compatibility. Process environment variables take precedence over file values.
Both headless and UI launches load this configuration before creating clients.
Web mode still requires explicit storage roots even when `.env` is used.

Desktop mode also honors `GEMS_CONFIG_DIR` for settings and `GEMS_DATA_DIR` for
startup logs and emergency manifests; without overrides its current
`~/.GEMS-data` behavior is preserved. When overriding desktop storage, configure
both roots and initialize their markers first, just as for web mode.
To migrate, stop writers, back up existing
state, copy selected settings/maps/runs to the approved shares, and review all
saved paths. The desktop **Destination folder** remains a separate remembered
setting and must also point at the share. No existing local data is deleted.

Encryption is deliberately not invented inside GEMS. Environment files contain
plaintext unless protected by approved encrypted storage. Use institutional
encryption at rest/in transit and backup policy, or inject `ALMA_API_KEY` through
an approved secret manager into the service environment. Do not put a decryption
key beside an encrypted secret or assume an application password protects
network-share files. Logs/manifests can contain restricted metadata and signed
URLs and require the same access controls as originals.

#### Managed hosting

[scripts/gems-web.service](scripts/gems-web.service) is a **template**, not an
enabled deployment. Before installing it, choose the service account, checkout,
virtual environment, and actual mounted roots; replace the `ReadWritePaths`
placeholders and add `RequiresMountsFor=` for both mounts. Its local
`/etc/gems/bootstrap.env` should contain only a non-secret `GEMS_ENV_FILE` pointer
to the approved private configuration file (or use the institution's secret
injection mechanism). Allow outbound HTTPS to Alma and actual object hosts.
Install/build dependencies during deployment, never at service start.

The template uses restrictive permissions, a read-only system filesystem, and a
five-minute shutdown grace period. Tune this for measured maximum download
times; a forced stop can leave interrupted/partial output. Capture stdout/stderr
in the journal, back up both shares, and test restore with the service stopped.

Until an approved HTTPS reverse proxy and institutional authentication protect
**both HTTP and WebSockets**, use only the SSH tunnel. Loopback is not user
authentication: other local server users may reach it. Use a dedicated trusted
host/account. The current workflow trusts authorized operators and their
manifests/maps, including referenced local files and download URLs; it is not
an untrusted-upload sandbox. Do not expose it to untrusted users.

Linux deployment acceptance still requires tests on dg-landing: exact Python
and OS, mount locking/rename semantics, offline export, a small authorized Alma
retrieval/download, tab disconnect/reconnect, restart/interruption, and storage
outage/restore. Tests run on a Mac do not certify those host-specific behaviors.
After a passing Linux deployment, capture a platform-specific dependency
constraints file and release revision. DART migration is a separate follow-up.

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

The Grinnell map includes `title_alternative` from `dcterms:alternative`, a `keywords` column for unqualified `dc:subject` values,
`provenance` from `dcterms:provenance`, and `related` from `dcterms:relation` plus `dc:relation`.
`format` combines the inferred MIME type with unqualified `dc:format` values, for
example `image/jpeg; reformatted digital`.
The main row's `type` uses typed DCMI metadata first, then `dc:type`, then file
inference. Generated file-child types remain file-derived. Re-map existing
manifests to apply these rules; because the CSV schema now includes `keywords`,
map the entire manifest to rebuild a complete CSV rather than relying on merging
old-schema batches. Ensure downstream templates retain the new `keywords` column.
Column names follow the snake_case header of SHOW's `grinnell-template.csv`
(for example `subject_topic`, `contributing_institution`, `filename`); CSVs
written with the earlier Title Case headers must also be re-mapped in full.

The export writes:
- `/path/to/output/collection_metadata.csv`
- `/path/to/output/normalized_records.json`
- `/path/to/output/objects/*`

The `transcripts/<objectid>.csv` timed-text files keep their fixed `timestamp,speaker,words` shape.

### Original MODS shelf locators

The Grinnell map writes `shelf_locator` from MODS `location/shelfLocator`,
including item-level `holdingSimple/copyInformation/shelfLocator`. Original
internal spacing and punctuation are preserved; distinct repeated elements are
joined with `; `. Parents and children inherit the same physical-source locator.
There is no Dublin Core equivalent or automatic box/folder parsing.

For future exports, set **Legacy MODS folder** (or headless `--legacy-mods`) to
the original MODS export root. Without that source, GEMS can only use a previously
cached `record.shelf_locator` or local `metadata.shelf_locator`; it cannot recover
MODS-only data from Alma DC. Custom maps must include the shelf-locator rule.

Backfill existing processed records without remapping other metadata:

```bash
.venv/bin/python -m gems.shelf_backfill plan \
  --gems-root /Volumes/DGIngest/_GEMS-Migration \
  --gems-root /path/to/other/GEMS-data \
  --legacy-mods /Volumes/DGIngest/Migration-to-Alma/exports \
  --show-root /path/to/SHOW \
  --report /path/outside/SHOW/shelf-backfill.json
.venv/bin/python -m gems.shelf_backfill apply /path/outside/SHOW/shelf-backfill.json
```

The plan reports missing MODS, unmatched rows, and non-empty conflicting values.
Apply fills empty locators only, preserves existing values and all unrelated
cells, and backs up each modified file beside the report. Matching uses saved
GEMS IDs, Alma MMS IDs, legacy identifiers, or filenames; child rows follow their
published parent. Ambiguous values block planning. The manifest caches non-empty
locators for subsequent remapping, and processed CSV/normalized JSON outputs and
matching SHOW collections receive only that field. Original MODS is never changed.
Missing MODS or absent elements leave locators blank, not inferred. Rerunning a
fresh plan is idempotent. Build and review affected SHOW collections separately.

## Refresh metadata already published through DART and SHOW

Use the original **mapped** JSON manifest and its **old, unmodified** GEMS CSV
as a baseline. Do not remap over that baseline first. The refresh command applies
the current map to the saved metadata in memory: no Alma requests, downloads,
asset moves, transcript writes, or manifest changes occur.

```bash
.venv/bin/python -m gems.metadata_refresh plan \
  --manifest /path/to/original/gems_collection_timestamp.json \
  --baseline /path/to/original/collection_metadata.csv \
  --core /path/to/SHOW/collections/ech/_data/collection_metadata.csv \
  --report /path/to/ech-refresh.json
```

The default map is `maps/alma-dc-to-grinnell.json`; use `--field-map` to choose
another template and `--legacy-mods` to read legacy MODS fallbacks. Old Title Case
headers are normalized to SHOW's snake_case names. Matching uses exact
`original_file_name`, not GEMS IDs (DART may have assigned different published
IDs). Missing/duplicate filenames, invalid published identities/parent links,
and manifests without persisted IDs are rejected.
If DART changed a compound parent's filename, reconciliation requires a unique
matching compound Alma MMS ID, identical source/baseline child sets, and verified
published source files. Core children must belong to that source family; any
source child DART published separately must retain the same MMS ID and have no
parent. Reconciled parents are recorded in the report; published filenames,
identities, and DART's grouping are never changed.

The JSON report lists added mapped columns, unmatched rows, and individual
changes with baseline/current/proposed values. Three-way comparison automatically
proposes a change only when the published value still equals the old GEMS value
or is empty. Published edits are conflicts. Potentially lost legacy-MODS values
are also conflicts when no MODS directory is supplied. Unchanged source values
do not replace editorial changes. Existing row order, extra editorial columns,
IDs, relationships, filenames, display templates, media/transcript URLs,
image alt text, and thumbnail focus are preserved.

Review all changes, including safe changes that clear obsolete source values.
Set each unresolved `"decision": null` to `"keep"` or `"apply"` in the report;
safe changes default to `"apply"` and can also be changed to `"keep"`.
Then apply:

```bash
.venv/bin/python -m gems.metadata_refresh apply /path/to/ech-refresh.json
```

Alternatively, after reviewing the plan, add `--keep-conflicts` to explicitly
preserve all unresolved conflicts. The command records those `"keep"` decisions
in the report after a successful apply.

Apply refuses unresolved conflicts, unmatched rows, and inputs changed since
planning. It creates a timestamped backup next to the review report and atomically
replaces the core, preserving UTF-8 BOM and line endings. An already-current
refresh makes no write. For a partial manifest, explicitly use `--allow-partial`
when planning: unmatched core/baseline rows remain untouched, but unmatched
source rows still block apply. No records are added or removed.
If a known source record was never published, explicitly exclude its exact
`original_file_name` with `--exclude-source NAME` when planning (repeatable).
Only records present in both source and baseline but absent from the core can
be excluded; the report records each exclusion for review.
To refresh the first N **SHOW CSV data rows**, add `--core-row-limit N` when
planning. The header does not count; parent and child rows each count separately.
Matching and changes are restricted to those rows, without expanding compound
families. Later rows retain every existing value; any newly added columns are
blank there. Apply also rejects changes outside the recorded row limit.
Keep reports outside SHOW's collection overlay so review files and backups
cannot accidentally be published or committed as collection data.

Use the same commands for `life`, `phpp-ghm`, `phpp-community`, and `phpp-dcl`,
with each collection's own manifest, original baseline, and actual SHOW CSV.
Transcript-bearing manifests are explicitly unsupported by this metadata-only
route. To incorporate subsequent Alma edits, retrieve a new manifest and
reconcile its identities first; this tool refreshes the saved Alma snapshot.
After applying, build and review the affected SHOW collection before deployment.
