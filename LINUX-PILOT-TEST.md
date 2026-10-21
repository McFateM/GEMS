# Linux Pilot Acceptance-Testing Guide

Use this guide on `dg-landing` after the offline and browser smoke tests pass.
It covers every acceptance item in section 6, with automated components,
manual procedures, evidence locations, and pass criteria. An automated PASS is
not approval for production or a substitute for administrator sign-off.

## Run the Automated Components

From the **Linux checkout**, with the current code installed:

```bash
export GEMS_CONFIG_DIR="$HOME/gems-pilot/config"
export GEMS_DATA_DIR="$HOME/gems-pilot/data"
export GEMS_ENV_FILE="$GEMS_CONFIG_DIR/gems.env"
.venv/bin/python -m gems.pilot --env-file "$GEMS_ENV_FILE"
```

The runner checks existing storage markers; it does not initialize or modify
your active service roots. It creates a private
`$GEMS_DATA_DIR/pilot/acceptance-<random>/` evidence directory, with its **own**
configuration/data roots. It starts a temporary loopback web process on
**8551**, verifies HTTP readiness, then stops that process. Your normal service
on **8550** stays running. Use `--port 8552` if 8551 is occupied; the runner will
not stop an existing listener.

It runs:

1. Host/version capture, `pip check`, and the full repository unit-test suite.
2. A real offline service export with CSV and byte-for-byte object checks.
3. A real web HTTP check, rejection of a second writer on the isolated roots,
   and retention of completed history after shutdown.
4. Real cancellation and forced termination of a separate child process during
   controlled local HTTP downloads; restart must mark the killed job
   `interrupted`, without resuming it.
5. Missing-marker submission blocking and recovery, followed by a local
   backup/copy restore with SHA-256 and persisted-history comparisons.

Cancellation/interruption use synthetic local files, not Alma. The regression
suite also exercises template merging, stable IDs, MODS precedence, filename
clashes, skipped entries, and injected storage failures. Those regression
checks are not proof of your real metadata or actual mount-outage behavior.
The runner never unmounts storage or kills your normal service.

### Optional Live Retrieval

After approval, add **2-3 real, distinct MMS IDs**:

```bash
# Replace these example numbers with your approved Alma MMS IDs.
.venv/bin/python -m gems.pilot --env-file "$GEMS_ENV_FILE" \
  --mms-ids '991111111111111111,992222222222222222'
```

This repeats the isolated checks, then retrieves only those IDs using the
configured Alma credentials. It does **not** download live objects or judge
metadata. Without `--mms-ids`, no live Alma calls are made. Keep credentials
only in the private environment file or process environment.

The live manifest path is in `live-result.json` and in the retrieval job JSON.
It is inside the runner's isolated `data/` tree, which is also inside the
normal service's data root. You can use that manifest directly in section 3,
skipping a second retrieval in section 2. Do not alter its isolated job history
or run two writers against the same manifest.

### Read the Automated Report

The runner prints the exact evidence directory. In the same Linux terminal,
set `EVIDENCE` to that printed path, then inspect:

```bash
EVIDENCE='/home/sysadmin/gems-pilot/data/pilot/acceptance-REPLACE'
.venv/bin/python -m json.tool "$EVIDENCE/report.json"
```

| Evidence Relative to `$EVIDENCE` | Expected Outcome |
| --- | --- |
| `report.json` | Every executed automated component is `PASS`; manual items remain `PENDING` |
| `host.json`, `revision.log`, `worktree.log`, `packages.log` | OS, architecture, interpreter, revision, local changes, and installed packages recorded |
| `pip-check.log`, `regression-tests.log` | No broken requirements; test run ends `OK`; review skips |
| `data/offline/collection_metadata.csv` | One row titled `Acceptance fixture` |
| `data/offline/objects/sample.txt` | Exactly the contents of `data/offline/original.txt` |
| `web.log`, `second-writer.log` | Web startup; second process explicitly refused with `Another GEMS service` |
| `lifecycle.json`, `data/jobs/<id>.json` | Recorded cancellation ID is `cancelled`; killed job ID is `interrupted` |
| `interruption.log`, `data/objects/` | Interrupted worker log and retained partial output; never a falsely successful killed job |
| `backup/`, `restored/`, `backup-hashes.json` | Local copied backup restores identical file content and job history |
| `live-result.json` (opt-in only) | Requested record count, manifest path, no unexplained skips/warnings |
| `failure.log` (on failure) | Explicit traceback; inspect the corresponding component log too |

Exit **0** means automated components passed, not full acceptance. A failure
returns **1** and stops later components; only explicit `PASS` entries passed.
Startup/argument errors can return another nonzero status. Do not check off
unexecuted items. Correct the problem and rerun into a new evidence directory.
Retain failed evidence as well as successful evidence.

Evidence may contain collection metadata, local paths, and signed URLs in
manifests. Keep it private; do not attach whole evidence trees to public issues.
Backups increase disk usage, and live object downloads can be large.

## 1. Prepare a Small, Approved Selection

- Choose **2-3 real Alma MMS IDs**, preferably from one collection. Include a
  single-file record and, if practical, a multi-file record.
- To check MODS fallback, include a record with a known empty Alma field and a
  matching legacy MODS file. Also identify a nonempty Alma field to verify it is
  not overwritten. Note the expected values before testing.
- Confirm the running service has an authorized `ALMA_API_KEY` and the correct
  `ALMA_API_REGION` from your private environment file. Never put the key in
  screenshots, logs, or pilot notes.
- Keep the Linux GEMS process and the Mac SSH tunnel running. Open
  <http://127.0.0.1:8550> on the Mac.

In a **second Linux terminal**, create a separate destination:

```bash
umask 077
export GEMS_CONFIG_DIR="$HOME/gems-pilot/config"
export GEMS_DATA_DIR="$HOME/gems-pilot/data"
PILOT_DIR=$(mktemp -d "$GEMS_DATA_DIR/pilot/mms-pilot-XXXXXXXX")
printf 'Browser destination: %s\n' "$PILOT_DIR"
ls -l "$GEMS_CONFIG_DIR/maps/alma-dc-to-grinnell.json"
```

Use your approved roots instead if different. Stop if the directory creation
or map check fails. These commands assume storage was initialized and the map
was copied during [Linux installation](INSTALL-LINUX.md).

## 2. Retrieve Only the Selected MMS IDs

In the browser's **Retrieve from Alma** section:

| Field | Value |
| --- | --- |
| Alma Set ID or Collection Title | Blank |
| MMS IDs (optional, comma-separated) | Your 2-3 approved MMS IDs, separated by commas |
| Destination (existing server directory inside GEMS_DATA_DIR) | The exact Linux path printed above |

1. Click **1) Retrieve from Alma and Save JSON Manifest**.
2. Wait for the job state to become **succeeded** (message **Completed**). Use **Refresh job log** to
   inspect the log.
3. Confirm `records` and `available_records` match the number of distinct IDs
   requested. Investigate any warnings or skipped records before proceeding.
4. Record the retrieval job ID and returned `manifest` path.
5. Click **Use this retrieved manifest for step 2**.

MMS IDs override the set/collection field. Retrieval fetches the **entire ID
selection**; the start/limit controls below do not limit retrieval.

## 3. Map and Download the First Record

In **Map Manifest to CSV**, use:

| Field | Value |
| --- | --- |
| Prepared manifest | The retrieved manifest selected in step 2 |
| Field map | `/home/sysadmin/gems-pilot/config/maps/alma-dc-to-grinnell.json` |
| Legacy MODS folder | `/home/sysadmin/gems-pilot/data/legacy-mods`, or blank if not testing MODS |
| Start record | `1` |
| Record limit | `1` |
| ObjectID prefix | `linux-pilot` |

Replace `/home/sysadmin` if your actual Linux home differs. Browser paths must
be absolute **Linux server paths**, not Mac paths or literal `$HOME` variables.
Use the MODS root containing collection subdirectories, not a single collection
subdirectory. See the [map decisions](maps/alma-dc-to-grinnell.md) for fallback rules.

Click **2) Map and Export Manifest to CSV**. Wait for **succeeded**, then record
the job ID and result paths. Inspect the CSV, normalized JSON, object files,
and job log **before continuing**:

- The result covers record 1; downloads exist and open correctly.
- Titles, identifiers, filenames, and expected metadata match the source.
- Multi-file records have the expected compound parent/child rows and links.
- MODS fills the selected empty Alma field, without replacing nonempty Alma
  values. Blank DART hosting fields are expected at this stage.

A manifest record is not necessarily one CSV row or one file. Compound records
produce additional rows. With the template map, `rows` is the merged CSV row
count; `files` counts files processed in this export, including reused files.
Neither count alone proves all requested files downloaded correctly.

### Locate Every Output

The browser's **Job history** dropdown selects a job; the status and JSON
details below it show the state and result. Use **Refresh job log** for its
last 32 KiB. Full logs and persisted state are on **Linux**, not the Mac:

| Item | Exact Location |
| --- | --- |
| Job result/state | `$GEMS_DATA_DIR/jobs/<job-id>.json`; inspect `state`, `message`, `inputs`, and `result` |
| Full job log | `$GEMS_DATA_DIR/jobs/<job-id>.log` |
| Retrieved manifest | Retrieval result's exact `manifest` path |
| Run directory | The directory containing that manifest |
| Mapped CSV | `<run>/collection_metadata.csv` (export result's `csv`) |
| Normalized rows | `<run>/normalized_records.json` (result's `normalized`) |
| Downloaded files | `<run>/objects/` (result's `objects`) |
| Run log | `<run>/gems.log` |
| Saved browser inputs | `$GEMS_CONFIG_DIR/web-settings.json` |

For runner jobs, substitute `$EVIDENCE/data/jobs/` for the normal jobs directory.
When the normal browser exports a runner-created manifest, that **new export
job** is in the normal `$GEMS_DATA_DIR/jobs/`; outputs remain beside the manifest.

Set these variables to the actual paths/ID shown by the browser:

```bash
MANIFEST='/home/sysadmin/gems-pilot/data/pilot/REPLACE/REPLACE.json'
RUN_DIR=$(dirname "$MANIFEST")
JOB_ID='REPLACE_WITH_EXPORT_JOB_ID'
ls -lh "$RUN_DIR"
find "$RUN_DIR/objects" -type f -exec ls -lh {} \;
cat "$GEMS_DATA_DIR/jobs/$JOB_ID.log"
.venv/bin/python -m json.tool "$GEMS_DATA_DIR/jobs/$JOB_ID.json"
```

The normal MMS retrieval layout is
`<destination>/mms-ids-<hash>/<timestamp>/gems_mms-id-selection_<timestamp>.json`.
Use the returned path, not a guessed hash or timestamp.

### Inspect Metadata and Files

Open the CSV using a CSV-aware editor, or print selected fields without
breaking quoted titles/descriptions:

```bash
.venv/bin/python - "$RUN_DIR/collection_metadata.csv" <<'PY'
import csv
import json
import sys
with open(sys.argv[1], encoding="utf-8", newline="") as handle:
    for row in csv.DictReader(handle):
        print(json.dumps({key: row.get(key, "") for key in (
            "objectid", "parentid", "title", "identifier", "display_template",
            "original_file_name", "creator", "extent", "rights", "shelf_locator"
        )}, ensure_ascii=False))
PY
```

Compare against these sources, recording the MMS ID, field, expected value,
actual value, and pass/fail for each selected record:

- **Alma:** the selected bib in the Alma interface, plus the retrieved
  manifest's `records` entries and `metadata`. Compare titles, identifiers,
  rights, and your chosen descriptive fields.
- **MODS:** the matching `grinnell_<n>_MODS.xml` under
  `$GEMS_DATA_DIR/legacy-mods/<collection>/`, located using the legacy
  `grinnell:<n>` identifier in the manifest. Follow the field's fallback rule
  in the [map decisions](maps/alma-dc-to-grinnell.md). A missing MODS file is
  not proof of successful fallback.
- **Mapped rows:** compare the CSV and normalized JSON. Verify each compound
  child's `parentid` points to its parent `objectid`; the parent's borrowed
  `original_file_name` starts with `_` and is not a separate missing download.
- **Objects:** open each selected PDF/image/audio/video with an appropriate
  viewer after securely copying it to your Mac if necessary. Compare its
  content to Alma's representation preview/original. Zero-byte, unreadable,
  wrong-record, or unexpectedly absent files fail acceptance.

**Pass:** all expected records/children/files are present, selected values match
their authoritative sources, MODS fills only the known gaps, and every selected
object opens correctly. Record any intentional map transformations. A
`succeeded` job without these comparisons is not sufficient.

## 4. Check Merging and Stable IDs

Use the **same manifest**, map, MODS folder, and prefix throughout:

1. In your Linux terminal, save the first CSV outside the active run directory:

   ```bash
   REVIEW_DIR=$(mktemp -d "$GEMS_DATA_DIR/pilot/review-XXXXXXXX")
   cp "$RUN_DIR/collection_metadata.csv" "$REVIEW_DIR/after-record-1.csv"
   ```

2. Set **Start record** to `2` and **Record limit** to `1`; export again.
   Repeat with start `3` if you selected three records.
3. Inspect the cumulative CSV: earlier rows remain, new rows appear in manifest
   order, `objectid` values are unique, and child `parentid` links are correct.
4. Save the merged CSV, then rerun start `1`, limit `1`:

   ```bash
   cp "$RUN_DIR/collection_metadata.csv" "$REVIEW_DIR/before-repeat.csv"
   ```

   After the repeat finishes, compare:

   ```bash
   diff -u "$REVIEW_DIR/before-repeat.csv" "$RUN_DIR/collection_metadata.csv"
   ```

   **Pass:** exit 0/no differences with unchanged inputs. Earlier rows and all
   assigned IDs remain, and no duplicate rows are introduced. If values differ,
   investigate before accepting; do not discard the comparison files.
5. Check every batch's log for failures, skipped entries, and `renamed_files`.
   Investigate unexpected filename changes; do not assume they are harmless.

Do not retrieve again to test merging: button 1 creates a **new run**.
No desktop, CLI, maintenance, or DART writer may modify this active output tree.

## 5. Check Signed-Link Refresh and Retain Evidence

Successful immediate downloads prove download access, not expired-link refresh.
GEMS reuses existing object files, so merely repeating an export will not prove
refresh. Retrieve the same approved IDs into a **new run**, but do not export
it yet. Retain that manifest and wait until its signed links have expired
(typically about an hour). Then select that manifest and export start `1`,
limit `1`, with the same map/MODS settings, without retrieving again. Confirm
the previously absent object files download successfully and inspect the job
log. Record the retrieval/export times and any refresh evidence; if expiry or
refresh cannot be established, leave that acceptance item pending. Do not
publish signed URLs in pilot notes.

Keep the selected IDs, Git revision, job IDs, job logs, manifest path, CSV
comparisons, and observed results in approved pilot records. Retain the pilot
outputs for review; do not delete source records or migrated baselines.

This procedure supports the retrieval/mapping checks below. Test concurrency,
cancellation, restart/interruption, storage failure, and backup restoration
as follows before marking those items complete.

### Browser Handoff, Progress, Errors, and Job Recovery

Use a disposable pilot run, not a production export:

1. In tab A, submit a small export and save its `/jobs/<job-id>` URL. Observe
   status/progress while it runs; for fast jobs retain the full job log.
2. Open tab B. **Pass:** it explicitly says read-only and submission controls
   are disabled. Close tab A. Tab B should become the active operator; if the
   job is still running, it must continue rather than cancel.
3. Refresh/open the saved job URL and select it in **Job history**.
   **Pass:** the same job, state, result paths, and log are recovered.
4. On a disposable run, enter a nonexistent manifest path. **Pass:** an explicit
   validation error is visible, not a success message. Restore the real path.
5. Review `regression-tests.log` for the skipped-entry, error-redaction, and
   filename-clash tests. For real warnings/clashes, inspect the retrieval's
   `warnings`/`skipped_positions` and export's `renamed_files`, plus their full
   logs. No unexpected renaming/skipping may remain unexplained. If your
   selection has none, record that; do not claim it exercised those cases live.

### Cancellation, Locking, Restart, and Interruption

The isolated runner automates actual cancellation, second-writer refusal,
completed-history retention, and forced-worker termination/recovery. Use its
`lifecycle.json`, job JSON/logs, `second-writer.log`, and `interruption.log` as
evidence on the pilot filesystem. A `cancelled` or `interrupted` outcome is the
expected **pass** for these deliberate tests, not a successful export.

Also verify the browser controls once: start a disposable export large enough
to observe, click **Cancel active job**, wait for `cancelled`, then inspect its
run's partial objects and job log. Cancellation waits for the current
operation; do not assume it is instant. If it finishes before cancellation,
record the attempt as untested and choose a suitable approved fixture.

For browser-history restart, with no active job, stop your foreground GEMS
process using Ctrl+C. Restart it with the same roots/environment file:

```bash
./run.sh --web --env-file "$GEMS_ENV_FILE"
```

**Pass:** completed jobs remain in history and their saved URLs/results still
work. Do not forcibly terminate the normal service; the runner confines the
forced-termination test to its own child process.

### Storage Approval, Failure, and Restoration

1. Record administrator approval of pilot content, quota, retention, free-space
   monitoring, and backups. Save `findmnt -T "$GEMS_DATA_DIR"` and
   `df -h "$GEMS_DATA_DIR"` output in approved records. **Pass:** the roots are
   on the intended approved filesystem, writable, and have sufficient quota
   for originals, outputs, evidence copies, and backups.
2. The runner temporarily removes **only its own marker**, checks that
   submission fails without creating a job, restores the marker, and reopens
   storage. Its unit tests inject an in-job write failure and verify the
   service remains write-blocked until restart. These are simulations, not
   actual mount/unmount tests.
3. For the real outage check, an administrator must provision a separate,
   disposable mount with isolated config/data roots and markers. Stop all
   other writers and verify it is **not** your home or any shared active mount.
   Launch a separate GEMS process against those roots on an unused loopback
   port and connect through a matching SSH tunnel.
4. Under administrator supervision, make that test storage unavailable during
   a disposable job. Observe the browser, the process terminal, and any
   available job log. **Pass:** explicit failure/write-blocked behavior; no
   successful completion or writes redirected to a home/checkout fallback.
   A failed storage write may prevent the final job state reaching disk, so
   retain terminal evidence outside the unavailable mount.
5. Restore the test mount/permissions, stop and restart the isolated service,
   and verify markers, writable roots, recovered/interrupted history, and a
   new offline export. **Pass:** no automatic resume of unfinished work, and
   normal writes recover only on the verified roots.

Do not run unmount/chmod experiments against the shared home filesystem.
If an isolated real outage cannot be arranged, mark this item **PENDING** with
the administrator's reason; a simulated pass does not silently replace it.

### Restore an Institutional Backup

The runner's `backup/` and `restored/` prove a **local copy** round trip, not
institutional backup availability or disaster recovery.

1. Stop writers for a consistent backup, or use the administrator's approved
   snapshot procedure. Back up both complete configuration and data roots,
   including hidden markers, settings, jobs, manifests, and objects.
2. Ask the administrator to restore that backup into **separate approved
   roots**, never over the active pilot. Keep permissions private; the
   configuration may contain credentials.
3. Compare file inventories and SHA-256 hashes against the backup/snapshot
   inventory. Open a restored CSV and a representative object; inspect job
   JSON and marker contents. Record backup ID/time, restore roots, counts,
   comparisons, and any exceptions.
4. In a **separate terminal**, set `GEMS_CONFIG_DIR`, `GEMS_DATA_DIR`, and
   `GEMS_ENV_FILE` to the restored paths, then launch on a different unused
   port. Remember that process variables override environment-file values.
   **Pass:** storage checks and persisted history load from restored roots.
5. Historical paths inside settings, job results, and manifests may still point
   at the original tree. Do not submit those historical jobs or use old
   absolute local-file references. Create a fresh offline fixture entirely
   inside the restored data root (use installation step 6 with that explicit
   root), export it, and verify all outputs remain inside the restored root.
   Stop the restored service after inspection.

**Pass:** a real approved backup is restorable, file content/state is intact,
and the isolated restored service can create verified new output. Leave the
item pending if you tested only the runner's local copies.

## 6. Pilot Acceptance Checklist

Copied from [section 8 of INSTALL-LINUX.md](INSTALL-LINUX.md#8-pilot-acceptance-checklist).

For each item, retain the evidence path, observed result, reviewer/date, and
`PASS`, `FAIL`, or `PENDING` in your approved pilot records. Check a box only
after all its clauses pass. Any unresolved failure or pending requirement
blocks full acceptance; only the institution can authorize an exception.

- [ ] Record Linux OS/architecture, Python version, Git revision, and package
  versions (`.venv/bin/python -m pip freeze`); tests and `pip check` pass.
- [ ] The `$HOME/gems-pilot` filesystem is approved for the pilot inputs;
  quota, retention, free-space monitoring, and backups are agreed.
- [ ] Offline and browser smoke exports write correct objects/CSV under
  `$HOME/gems-pilot/data`.
- [ ] Authorized Alma retrieval and signed-link refresh work from dg-landing.
- [ ] Template-map batches merge correctly, IDs remain stable, and MODS fills
  only fields empty in Alma.
- [ ] Progress, failures, skipped records, and filename clashes are visible.
- [ ] Second browser tab is read-only. Closing the operator tab transfers
  control, while any running job continues; history/job URL restores status.
- [ ] A second web process using the same roots refuses startup while the first
  holds the lock. Verify this on the actual pilot filesystem.
- [ ] Cancel a disposable job, wait for it to stop, and inspect partial output.
- [ ] Restart with a completed job and confirm persisted history. On a
  disposable test job, exercise forced termination and verify the unfinished
  job is **interrupted**, never automatically resumed or reported successful.
- [ ] With administrator supervision and isolated pilot storage, simulate
  unavailable storage and restoration. Never unmount a shared home filesystem
  simply to test this. Verify explicit failure/no alternate-directory
  fallback, restore storage, and restart a write-blocked service.
- [ ] Restore a backup into separate pilot roots and validate its files/state.

No concurrent desktop/CLI/maintenance/DART writer may touch the active output
tree. These other tools do not participate in the web service lock.

Pilot acceptance does not certify future storage or authorize production data.
Repeat these checks after migration before approving production use.
