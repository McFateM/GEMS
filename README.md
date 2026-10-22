# GEMS

GEMS: Gather, Export, Map, Serialize.

The Linux/web, Omeka JSON import, and headless retrieval work has been merged
into `main`. Use **`main` on dg-landing** for normal operation; the older `linux`
branch is no longer needed for these features. Use SSH for
headless processing or the private Linux web interface; desktop modes remain
available for compatibility, not as the normal processing environment.
See [INSTALL-LINUX.md](INSTALL-LINUX.md) for host setup and storage safeguards.

### Updating an existing dg-landing checkout

Stop any running GEMS process and wait for its worker to finish before updating.
In a dg-landing shell:

```bash
cd ~/GitHub/GEMS
git status --short
# Continue only with a clean working tree; preserve any local changes first.
git fetch origin
git switch main
git pull --ff-only origin main
```

If the checkout was on `linux`, switching to `main` includes the merged Linux
features and the new [collection-title batch script](#button-1-for-a-list-of-collection-titles).
Do not keep pulling `linux` to obtain new `main` changes. No dependency reinstall
is needed just for the batch script; it uses the existing headless environment.
Some older Linux runbook branch references predate the merge; use `main` when
following those setup instructions.

This repository now contains a small Flet-based application and headless pipeline for:
- loading Alma Digital / Specto exports from JSON or CSV,
- importing Omeka Classic or Omeka S JSON exports for DART,
- extracting digital-object identifiers, files, and structured metadata,
- mapping source metadata into CollectionBuilder-oriented fields, and
- writing a `collection_metadata.csv` plus exported objects and normalized JSON.

## Offload migrated files from dg-landing

Run [scripts/offload_migrated.sh](scripts/offload_migrated.sh) **on your Mac**,
not on dg-landing, with the DGIngest SMB share mounted in Finder:

```bash
cd ~/GitHub/GEMS
# Preview first (also the default when no option is supplied):
bash scripts/offload_migrated.sh --dry-run
# Transfer successfully, then remove each transferred source file:
caffeinate -i bash scripts/offload_migrated.sh --move
```

`caffeinate -i` prevents idle sleep during the transfer, but not sleep from
closing the lid. Keep the Mac open, connected to the network, and DGIngest
mounted. To disconnect, press **Ctrl+C**, wait for the shell prompt, then
eject the share normally. Later, reconnect and remount DGIngest, then rerun
the same command. Completed transfers are preserved; files not yet transferred
remain on dg-landing. The in-progress file may need some or all of its transfer
repeated, so partial-file reuse is not guaranteed.

This pulls **only files inside `objects/.complete/` directories** anywhere
beneath `/data/gems/data/migrated/` over SSH from `sysadmin@dg-landing` into
`/Volumes/DGIngest/_GEMS_Migration/Migrated/`. It preserves the full relative
paths, including hidden files and the `.complete` directory itself. For example,
`migrated/DGIngest-DATA/collection-name/run/objects/.complete/item/file.pdf`
becomes `Migrated/DGIngest-DATA/collection-name/run/objects/.complete/item/file.pdf`.
Other object files, manifests, CSVs, and logs remain on dg-landing.
It requires working
noninteractive SSH authentication and rsync on both machines; it works with
macOS's bundled rsync. The script refuses to run unless DGIngest is an SMB
mount, avoiding accidental copies to your Mac's internal disk. It creates
the destination directory if needed, even in preview mode.

Only offload completed, inactive files. Do not run simultaneous offloads or
write into the selected `.complete` directories while moving them. Check
that the share has enough free space for the selected files (roughly 39 GiB
as of October 22, 2026), plus future collections.
An interrupted or failed move can leave some files already moved; rerun the
same command to resume. Rsync removes source files only after successful
transfer (or confirmation that an existing destination file matches), uses
checksums rather than size/time alone to compare existing files, and keeps
partial downloads for resumption. Checksumming can take time over SMB.

Destination-only files are never deleted. Different existing destination
files are backed up under `Migrated/.replaced/<UTC timestamp>-<process ID>/`
before replacement. Empty directories remain on dg-landing. No other
directories under `/data/gems/data` are moved, and saved commands or manifests
referencing moved server paths are not rewritten; retrieve a file back or
adjust those paths before reusing such a manifest.

## Retrieve from Alma Digital

GEMS can retrieve records directly from Alma using the same environment-variable contract as CABB. Copy `.env.example` to `.env`, then configure `ALMA_API_KEY` and `ALMA_API_REGION`. GEMS does not store the key in its settings file.

Enter a numeric Alma set ID or an exact collection title in the single input. Numeric IDs retrieve set members; text titles find an Alma bibliographic collection and retrieve its bibs. If you enter MMS IDs instead, GEMS retrieves only those IDs and ignores the set/collection field. GEMS retrieves the bib record, Dublin Core metadata, digital representations, and representation-file descriptors. GEMS requests signed download URLs for representation files and downloads them during the CSV export. Signed URLs expire after about an hour. When a stored link has expired, GEMS asks Alma for a fresh one just before downloading that file, so batches can be mapped long after the manifest was created.

During retrieval, the status strip reports progress at 10% milestones based on unique MMS IDs and records the updates in the activity log.

Retrieval and manifests always cover the entire set, collection, or MMS-ID list. If Alma cannot list some collection entries, GEMS skips them and reports their positions.

In the **Map Manifest to CSV** section, **Start record** (1-based, default 1) and **Record limit** (leave blank for all) choose which manifest records button 2 maps and downloads. For example, with a limit of 100, use starts 1, 101, 201, and so on. Both values are remembered. Each batch is merged into the run's single `collection_metadata.csv` in manifest order. Re-mapping a range replaces those records' rows and leaves the others intact.

Before using button 1, set **Destination folder** in the Retrieve from Alma section to an existing parent folder such as `/Volumes/DGIngest/.GEMS-data`. The folder is remembered and checked before GEMS contacts Alma. **1) Retrieve from Alma and Save JSON Manifest** retrieves the records and immediately saves them. It creates a persistent `collection-<title>-<pid>/`, `set-<title>-<id>/`, or `mms-ids-<hash>/` folder in the destination. If the destination can't be written when retrieval finishes, the manifest is saved under `~/.GEMS-data/unsaved-manifests/` instead. Each run gets its own readable local-time subdirectory, such as `2026-09-30_11-52-42_CDT/`, containing the manifest and `gems.log`. The manifest includes `collection_title`, local-time `created_at` (ISO 8601 with UTC offset), the retrieval's `available_records` count, optional `alma_set_id` or `alma_collection_pid`, and the retrieved `records` array. GEMS selects the new manifest automatically. In the **Map Manifest to CSV** section, optionally choose a JSON field map, then use **2) Map and Export Manifest to CSV** to write `collection_metadata.csv`, `normalized_records.json`, and `objects/` into the folder containing the manifest. Run button 2 again with the next **Start record** to map the next batch into the same CSV. Each use of button 1 creates a new manifest and timestamped run under the destination folder. Existing runs remain intact.

## Import a prepared manifest

### Import Omeka JSON for DART

Select **Omeka Classic / Omeka S JSON export** in **Input source** under
**Map Manifest to CSV**. Choose the JSON export, enter an **Omeka output folder**,
and use button 2. Omeka does not require Alma credentials or an Alma retrieval.
The selected source and Omeka destination are remembered. The existing Alma
retrieval and export behavior is unchanged; selecting a newly retrieved Alma
manifest switches the source back to Alma.

Headless equivalent, from the repository root using GEMS's virtual environment
(created by `./run.sh`):

```bash
.venv/bin/python -m gems --headless --source-type omeka \
  --source /path/to/omeka-export.json --output /path/to/fresh-output
```

Use `.venv/bin/python` rather than the system `python3`, which may not have
GEMS's dependencies installed. Alternatively, activate the environment with
`source .venv/bin/activate` before using `python -m gems`.

Accepted input is a single item, an array of items, or an object containing an
`items`, `records`, or `data` array:

- **Classic:** Dublin Core `element_texts`, with each entry's `element.name`
  and `text`; embedded file objects in `files_list` (or a `files` array).
  Files use `file_urls.original`, falling back to `file_urls.fullsize`.
- **S:** JSON-LD `dcterms:*` / `dc:*` value arrays (`@value` or URI `@id`)
  and embedded `o:media` objects containing `o:original_url`. Filenames come
  from `o:filename`, a filename-like `o:source`, or the download URL.

Omeka S exports may contain only `@id` media API references in `o:media`.
During export, GEMS automatically reads each referenced HTTP(S) API resource
and uses its `o:original_url` and filename metadata. Resolution reports progress,
checks cancellation between requests, uses a 30-second request timeout, and
retries transient failures up to three times. Repeated references are fetched
once per run. The JSON input is not modified, and the UI range preview stays
offline. Resolution currently covers all items before batch selection so naming
remains stable across batches.

Classic file listing links still need to be expanded into `files_list` before
importing. Media APIs and asset URLs must be accessible without interactive
authentication. API errors, invalid responses, and non-file media without an
original URL stop the export with item/media context; API JSON is never saved
as an asset.
Local `file://` asset URLs are also supported.
Representative, documented-shape fixtures are in
[tests/fixtures/omeka](tests/fixtures/omeka/README.md).

Omeka normalizes into GEMS's existing metadata/file model and uses the shared
template mapper, download code, filename rules, per-object folders, progress,
cancellation, and CSV/JSON writers:

- Output contains `objects/<object-folder>/<asset-name>`,
  `collection_metadata.csv`, and `normalized_records.json`.
- Every physical media file has one row, repeating the item's metadata.
  `original_file_name` and `filename` exactly match the final on-disk basename,
  including sanitization, sequence numbering, and conflict suffixes.
- Canonical fields such as `title`, `creator`, `description`, `subject`, and
  `date` are unprefixed. Repeated values use `; `, following GEMS conventions.
  Omeka IDs appear only in `originating_system_id`; `source_system` and
  `source_record_url` retain provenance. They are not DART IDs.
- Omeka exports never assign `objectid` / `parentid`, create structural rows,
  or convert transcript assets. DART determines structure later from the files.
- Items with no media are skipped with an activity-log warning and an explicit
  completion notice; no fake file or metadata-only row is created.
- A missing media URL, unsupported structure, malformed JSON, download failure,
  or write failure stops the export with an error. Metadata is not published
  for a failed download. Completed assets may remain after failure/cancellation;
  incomplete downloads are removed. Rerunning downloads selected assets again.

An optional simple field map follows the existing canonical-field-to-source-name
syntax. Existing template maps also work: Omeka applies their item-level rules
to every physical file, omits ID columns, and forces `original_file_name` to the
actual basename. It does not apply Alma child-row rules or legacy MODS fallbacks.
The default mapping needs no field map and uses canonical unprefixed columns.

**Start record** and **Record limit** retain their existing 1-based meanings.
Naming is planned across the entire input before selecting a batch, keeping
filenames stable. Subsequent batches merge by `original_file_name` in input
order. Use a fresh output directory for a different export or mapping; GEMS
rejects incompatible existing CSV columns or unrelated assets before downloading.
Do not edit source identities or media filenames between batches.

The asset-only contract above applies to the new Omeka adapter. The existing
Alma template workflow, including its legacy structural rows, is preserved.

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
./run.sh --install --web --env-file "$HOME/gems-pilot/config/gems.env"
```

`python_requirements.txt` remains the desktop installation entry point.
Packaging separates the core pipeline (`pip install -e .`), desktop
(`pip install -e '.[desktop]'`), and web (`pip install -e '.[web]'`) runtimes.
The web extra requires FastAPI `<0.145` because Flet 0.25.2 uses the
`openapi_prefix` constructor argument removed in FastAPI 0.145.
The headless CLI does not import Flet. To run with an existing environment,
use `python -m gems` with the same switches. `GEMS_PYTHON` selects the interpreter
when the script creates a new environment; Python 3.11+ is required.

For isolated Linux acceptance checks, run
`.venv/bin/python -m gems.pilot --env-file "$GEMS_ENV_FILE"`.
For the terminal layout and everyday browser workflow, read
[GEMS on Linux: How the Pieces Fit Together](LINUX-WEB-OVERVIEW.md).
See the [Linux Pilot Acceptance-Testing Guide](LINUX-PILOT-TEST.md) for setup,
optional MMS-ID retrieval, retained evidence, and required manual checks.

The status strip at the bottom shows progress, results, and errors for retrieval and export. Use its copy button to copy the current status message. Its activity-log button reads the current run's `gems.log` after a manifest is saved; startup and pre-run messages remain in `~/.GEMS-data/logfiles/gems.log`.

### Linux/Web service and local storage

For the ordered installation, legacy-data migration, acceptance testing, and
development procedure, follow [Installing GEMS on dg-landing](INSTALL-LINUX.md).

The Linux support now included in `main` provides a private, single-operator Flet web service with durable
job history. It is **not a public, multi-user service**. It listens only on
`127.0.0.1` (default port 8550), launches no desktop/browser on the server, and
requires explicit configuration and data directories. Both directories must
already exist on approved storage; the current pilot uses explicitly configured
home-directory roots. No data is moved automatically, and web mode never falls
back to the server home or checkout.

**dg-landing storage plan (2026-10-20):** because the host is web-facing, it
cannot access the campus SMB `//storage` server. A **500 GB local `/data` store
has been requested** for GEMS and DART operations, but **it is not ready**.
All current Linux storage and transfer examples use `$HOME/gems-pilot` on
dg-landing. Keep inputs/downloads small and confirm home-directory quota,
access controls, encryption, and backups with the administrator.
Do not create a substitute `/data` on the root disk or mount campus SMB.

On **dg-landing**, create and verify the pilot roots. Re-export these variables
in each new Linux shell:

```bash
export YOUR_LINUX_USER=sysadmin
umask 077
export GEMS_CONFIG_DIR="$HOME/gems-pilot/config"
export GEMS_DATA_DIR="$HOME/gems-pilot/data"
export GEMS_ENV_FILE="$GEMS_CONFIG_DIR/gems.env"
mkdir -p "$GEMS_CONFIG_DIR" "$GEMS_DATA_DIR/pilot"
findmnt -T "$GEMS_CONFIG_DIR"
findmnt -T "$GEMS_DATA_DIR"
df -h "$GEMS_CONFIG_DIR" "$GEMS_DATA_DIR"
test -d "$GEMS_CONFIG_DIR" && test -w "$GEMS_CONFIG_DIR"
test -d "$GEMS_DATA_DIR" && test -w "$GEMS_DATA_DIR"
printf 'Configuration: %s\nData: %s\n' "$GEMS_CONFIG_DIR" "$GEMS_DATA_DIR"
touch "$GEMS_ENV_FILE"
chmod 600 "$GEMS_ENV_FILE"
nano "$GEMS_ENV_FILE"
```

Set `YOUR_LINUX_USER` once per shell, or add `export YOUR_LINUX_USER=sysadmin`
to `~/.bashrc` using nano to retain it across interactive Bash sessions.

Example private environment file for `sysadmin`, stored outside Git on
protected storage. Use the full absolute paths printed above if your home is
elsewhere. Shell variables are not expanded in this file; do not use literal
`$YOUR_LINUX_USER`, `$HOME`, or `~`:

```dotenv
GEMS_CONFIG_DIR=/home/sysadmin/gems-pilot/config
GEMS_DATA_DIR=/home/sysadmin/gems-pilot/data
ALMA_API_REGION=America
ALMA_API_KEY=replace-with-authorized-key
```

The pilot runs as your normal Linux account, which needs read/write access
to both roots. Restrict roots, secrets, and backups to approved
operators. Use restrictive local permissions and any filesystem ACLs. Set
`umask 077` for manual service launches.

From the Linux checkout, after configuring and verifying the pilot roots:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[web]'
.venv/bin/python -m pip check
# Explicit one-time initialization, AFTER verifying the intended pilot roots:
.venv/bin/python -m gems --init-storage --env-file "$GEMS_ENV_FILE"
./run.sh --web --env-file "$GEMS_ENV_FILE"
```

`--init-storage` places a `.gems-storage` marker in each configured root.
Normal startup and job writes require these markers and successful write probes.
Missing/unwritable storage fails explicitly; do not initialize an unintended
directory to bypass this check. Markers detect ordinary missing mounts, not
every storage failure. Filesystem and
capacity supervision remain administrator tasks.
If storage fails during a job and its failure state cannot be persisted, the
browser and stderr report a write-blocked service. Restore storage and restart;
the last persisted unfinished state becomes **interrupted**, not successful.
An already-started file operation cannot be rolled back.

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
  uploads. Copy prepared manifests, originals, and MODS into the data root,
  and copy your chosen field map into the configuration or data root over SSH.
  Workstation `/Volumes/...` paths embedded in manifests must be reviewed and
  translated to absolute Linux `gems-pilot` paths before mapping. Transfer
  material from `//storage` via an approved workstation that can access it,
  not from dg-landing.
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
- Outputs stay on dg-landing's private local storage. The UI displays result
  paths and logs; it does not publicly serve originals, offer artifact downloads, or expose
  metadata-refresh/shelf-backfill maintenance operations.

Job state uses atomic same-directory JSON replacement rather than SQLite WAL,
which is unsuitable for many network mounts. The filesystem must support
reliable POSIX advisory file locks, atomic rename, and file/directory `fsync`.
The service holds an exclusive data-root lock for its entire lifetime; a second
service process using that root fails startup. Verify these semantics on the
actual pilot filesystem before use, and repeat after any storage migration.
Do not run desktop, CLI,
maintenance, DART, or another host against the same active output tree; those independent
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
state, copy selected settings/maps/runs to the approved storage roots, and review all
saved paths. The desktop **Destination folder** remains a separate remembered
setting and must point at the intended output location on that desktop.
dg-landing's `$HOME/gems-pilot` is not a shared Mac mount; keep workstation and Linux
paths/settings separate. No existing local data is deleted.

Encryption is deliberately not invented inside GEMS. Environment files contain
plaintext unless protected by approved encrypted storage. Use institutional
encryption at rest/in transit and backup policy, or inject `ALMA_API_KEY` through
an approved secret manager into the service environment. Do not put a decryption
key beside an encrypted secret or assume an application password protects
stored files. Logs/manifests can contain restricted metadata and signed
URLs and require the same access controls as originals.

#### Moving to /data when ready

Continue using `$HOME/gems-pilot` until the administrator provisions and verifies
the requested store. The 500 GB capacity will be shared by GEMS and DART; agree
on allocation, retention, monitoring, access controls, and backups first.
Follow [Moving the pilot to the new /data store](INSTALL-LINUX.md#moving-the-pilot-to-the-new-data-store)
for the full cutover: stop writers, back up the pilot, verify empty destination
roots, copy both complete trees including hidden state, checksum the copies,
update the destination environment file and launch variables, and review saved
paths without rewriting archival evidence. Repeat storage and browser acceptance
tests on the new filesystem. Keep the pilot source until acceptance and backup
review; never run writers against both copies.

#### Future managed hosting after migration

The current pilot runs in the foreground through the SSH tunnel. Do not install
the managed-service template for home-directory storage: `ProtectHome=true`
deliberately blocks those paths.

[scripts/gems-web.service](scripts/gems-web.service) is a **template**, not an
enabled deployment. After migration and acceptance, choose the service account, checkout,
virtual environment, and approved `/data` roots; replace the `ReadWritePaths`
placeholders and add `RequiresMountsFor=` for both paths to order their backing
mounts. Its local `/etc/gems/bootstrap.env` should contain only a non-secret
`GEMS_ENV_FILE` pointer
to the approved private configuration file (or use the institution's secret
injection mechanism). Allow outbound HTTPS to Alma and actual object hosts.
Install/build dependencies during deployment, never at service start.

The template uses restrictive permissions, a read-only system filesystem, and a
five-minute shutdown grace period. Tune this for measured maximum download
times; a forced stop can leave interrupted/partial output. Capture stdout/stderr
in the journal, back up both storage roots, and test restore with the service
stopped. Local `/data` storage is not itself a backup.

Until an approved HTTPS reverse proxy and institutional authentication protect
**both HTTP and WebSockets**, use only the SSH tunnel. Loopback is not user
authentication: other local server users may reach it. Use a dedicated trusted
host/account. The current workflow trusts authorized operators and their
manifests/maps, including referenced local files and download URLs; it is not
an untrusted-upload sandbox. Do not expose it to untrusted users.

Linux deployment acceptance still requires tests on dg-landing: exact Python
and OS, local filesystem locking/rename semantics, offline export, a small
authorized Alma retrieval/download, tab disconnect/reconnect, restart/interruption, and storage
outage/restore. Tests run on a Mac do not certify those host-specific behaviors.
After a passing Linux deployment, capture a platform-specific dependency
constraints file and release revision. DART migration is a separate follow-up.

### Run headlessly

Run these commands **on dg-landing**, from `~/GitHub/GEMS`. Keep credentials
in the existing private environment file, not in command-line arguments.
Do not run headless processing against a run directory while a browser job is
writing to it. Headless commands run in the foreground and do not create entries
in browser job history; use a persistent SSH session (for example, `tmux`) for
long operations.

#### Button 1: retrieve Alma records and save a manifest

Choose exactly one of the three input branches:

```bash
cd ~/GitHub/GEMS
export GEMS_ENV_FILE="$HOME/gems-pilot/config/gems.env"

# Alma set
.venv/bin/python -m gems --headless --retrieve \
  --set-id 123456789 --output "$HOME/gems-pilot/data"

# Exact Alma collection title
.venv/bin/python -m gems --headless --retrieve \
  --collection-title "Social Justice at Grinnell" \
  --output "$HOME/gems-pilot/data"

# Explicit MMS IDs, separated by commas or newlines
.venv/bin/python -m gems --headless --retrieve \
  --mms-ids "991234567890,991234567891" \
  --output "$HOME/gems-pilot/data"
```

The set/MMS numbers above are placeholders; replace them with approved IDs.
`--output` must be an existing writable parent directory. Each invocation saves
a new timestamped run under `set-...`, `collection-...`, or `mms-ids-...`,
containing the JSON manifest and `gems.log`, and prints the manifest path.
It ends with a shell-quoted, copy-and-paste **button 2 command** using the current
Python interpreter, the new manifest, and its run directory as the output folder.
The printed command includes `--objectid-prefix` derived from the full resolved
collection title: lowercase, with runs of spaces or punctuation replaced by
hyphens (for example, `Social Justice at Grinnell` becomes
`social-justice-at-grinnell`). This uses the existing ObjectID slug rules and
does not truncate the title to the shorter run-folder name. Batch command files
save this option too. Previously retrieved manifests and previously saved
commands are not modified.
Newly generated button 2 commands also include
`--field-map-file /path/to/GEMS/maps/alma-dc-to-grinnell.json`, selecting the
Grinnell template explicitly. Keep that option when running or editing them.
The command exports all retrieved records by default; add `--start` and `--limit`
to batch the export, or add your field map and other mapping options before running
it. An explicit `--env-file` or `GEMS_ENV_FILE` is carried forward as `--env-file`.
The command is printed only; button 1 does not automatically start button 2.
Retrieval always covers the entire selection; `--start`, `--limit`, and other
mapping options are rejected for button 1. Objects are downloaded only by
button 2. Progress and skipped-entry warnings go to stderr. Errors exit nonzero;
headless retrieval does not silently redirect output to a local fallback folder.
`--env-file /path/to/private.env` can replace `GEMS_ENV_FILE`.

Collection titles containing the word `and` are searched using a portion without
that word because Alma treats it as a query operator, even inside quoted values.
GEMS still requires an exact, case-insensitive match against the full collection
name; a partial match is never selected automatically.

#### Button 1 for a list of collection titles

**Recommended: retrieve directly by collection PID**, avoiding Alma's title
query parser entirely. [collections.tsv](collections.tsv) contains the current
40-title list with two tab-separated columns: **collection PID first, title
second**, without a header. IDs were taken from Alma's collection editor, not
guessed from titles. They are collection PIDs, not set IDs or bibliographic
MMS IDs.

```bash
cd ~/GitHub/GEMS
bash scripts/retrieve_collections.sh --ids \
  collections.tsv /data/gems/data /data/gems/config/gems.env
```

In `--ids` mode, the title is only a supplied label for the manifest, directory,
and button 2 ObjectID prefix. GEMS requests collection members by PID and never
searches or resolves that title. Keep the labels paired with the correct IDs;
GEMS does not validate their names through the collections API. Use a literal
tab between the two columns, not commas or spaces. Blank lines and CRLF files
are supported; malformed rows stop the batch with a line-numbered error.
The same fail-fast and saved-button-2-command behavior described below applies.
This does not change Alma suppression or publication settings.

To retrieve one collection directly:

```bash
.venv/bin/python -m gems --headless --retrieve \
  --collection-id 81310703090004641 \
  --collection-title 'Scarlet & Black (S&B) Archives' \
  --output /data/gems/data --env-file /data/gems/config/gems.env
```

`--collection-id` requires `--collection-title` as the output label. Without
`--collection-id`, the title-only commands below retain their existing behavior.
For a partial restart, make a TSV with only the rows still needed; the batch
does not automatically skip previously retrieved collections.

Use [scripts/retrieve_collections.sh](scripts/retrieve_collections.sh), included
in `main`, to run headless button 1 against a list without starting button 2.

Save a UTF-8 text file with one exact Alma collection title per line, without
surrounding quotes:

```text
Social Justice at Grinnell
Another Exact Collection Title
```

After updating the dg-landing checkout to `main` as described above, run:

```bash
cd ~/GitHub/GEMS
bash scripts/retrieve_collections.sh \
  /path/to/collection-titles.txt \
  /data/gems/data \
  /data/gems/config/gems.env
```

The third argument is optional if `GEMS_ENV_FILE` is exported or the checkout's
`.env` is configured. The script uses the checkout's `.venv/bin/python`; it does
not install dependencies. You can invoke it from Bash or zsh using `bash` as
shown, including from another directory by giving the script's full path.

Titles are processed sequentially. Blank lines are skipped, surrounding whitespace
is trimmed, and Windows CRLF line endings are accepted. Other characters,
including quotes and `#`, are literal parts of the title, not shell syntax or
comments. Each successful retrieval prints its manifest and button 2 follow-up
command. **The script stops immediately at the first failure**, reports the
failed line/title and completed count, and preserves the failing exit status.
Earlier manifests remain intact; retry with a list containing only the remaining
titles to avoid retrieving successful collections again. An empty list is an
error. It never runs button 2 automatically. Use `tmux` for long batches.

Each batch also creates a private, uniquely named
`button-2-commands-<UTC-timestamp>-<unique>` Bash script in the output directory.
Its path is printed at startup and on completion or retrieval failure. Each
successful collection's shell-quoted button 2 command is appended immediately,
with its collection title as a comment. Commands already saved survive a later
failure, and a new batch never overwrites an earlier command file. Failed
collections are not included.

Review the saved file and copy individual commands when ready. Alternatively,
after reviewing all commands and adding any desired field-map or batching
options, run the file with `bash /data/gems/data/button-2-commands-...`.
That explicitly starts button 2 exports sequentially and stops on the first
export failure. Rerunning the file repeats its exports; it does not track which
button 2 commands have already completed.

#### Button 2: map an existing manifest and download its objects

```bash
.venv/bin/python -m gems --headless \
  --source /path/printed/by/button-1/manifest.json \
  --output /path/printed/by/button-1 \
  --start 1 --limit 100
```

Use the directory containing the manifest as `--output` to match button 2 in
the UI. Omit `--limit` to map all remaining records. Repeat with `--start 101`,
etc., to merge batches. Optional `--objectid-prefix`, `--legacy-mods`, and
`--field-map` provide the corresponding mapping controls.

For either Omeka Classic or Omeka S JSON, button 1 is unnecessary:

```bash
.venv/bin/python -m gems --headless --source-type omeka \
  --source "$HOME/gems-pilot/data/omeka-export.json" \
  --output "$HOME/gems-pilot/data/omeka-output"
```

In the Linux browser UI, choose **Omeka Classic / Omeka S JSON export** under
**Input source** and supply an existing **Omeka output folder** inside
`GEMS_DATA_DIR`. Alma-only prefix and legacy-MODS controls are disabled.

### Optional field mapping

For the Grinnell workflow, always select the supplied template explicitly:

```bash
.venv/bin/python -m gems --headless \
  --source /path/to/manifest.json --output /path/to/output \
  --field-map-file maps/alma-dc-to-grinnell.json
```

`--field-map-file` reads JSON from a file and cannot be combined with the inline
`--field-map` option. Omitting both still selects the older basic export; an
ObjectID prefix alone does not select the Grinnell template.

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
