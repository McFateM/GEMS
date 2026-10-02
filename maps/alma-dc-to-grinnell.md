# Alma DC → Grinnell CollectionBuilder map: decisions

Map file: [alma-dc-to-grinnell.json](alma-dc-to-grinnell.json)
Target: row 1 (`:ColumnName`) of `DG-with-CB-and-Pagefind/collections/_collection-template/_data/grinnell-template.csv`
Source studied: `metadata` of the Social Justice at Grinnell manifest `2026-09-30_14-04-05_CDT` (4 records, collection PID 81310653130004641).

To use it, choose this JSON file in **Field map** before pressing **2) Map and Export Manifest to CSV**. The CSV columns are the `columns` list, in that order.

**Source keys.** Since 2026-10-01, GEMS keeps Alma's DC granularity. Each `metadata` key is the qualified element name, plus its `xsi:type` in parentheses when Alma records one: `dc:type`, `dcterms:type (dcterms:DCMIType)`, `dcterms:subject (dcterms:LCSH)`, `dcterms:identifier (dcterms:URI)`. Alma-local elements (`dginfo`, `googlesheetsource`, `oldalttitle`, `compoundrelationship`) stay unprefixed. Manifests retrieved before that date use flat keys (`type`, `subject`…); re-retrieve them before mapping with this map.

## Rule vocabulary

Each entry in `rules` is keyed by an output column. Columns without a rule are left blank.

| Key | Meaning |
| --- | --- |
| `from` | Source name, or a list tried in order until one yields a value. Sources: `metadata.<key>` (Alma DC element, e.g. `metadata.dcterms:subject (dcterms:LCSH)`; case-sensitive), `record.<key>` (top-level record field such as `mms_id`), `gems.<key>` (values computed by GEMS, below). |
| `combine` | With a `from` list: merge values from all sources (de-duplicated) instead of stopping at the first. Use it where an element may appear as both `dc:` and `dcterms:`. |
| `value` | A constant. |
| `split` | Default `true`: split on `;`, trim, drop blanks, and remove case-insensitive duplicates, then re-join with `; `. Set `false` for prose (titles, abstracts, rights). |
| `match` / `exclude` | Regex; keep / drop individual values that match. |
| `extract` | Regex; keep group 1 (or the whole match) and drop values that don't match. |
| `replace` | `[pattern, replacement]` passed to `re.sub`; runs after `extract`. |
| `strip_html` | Remove HTML tags and decode entities. |
| `capitalize` | Upper-case the first letter of each value. |
| `child` | Rule for compound-object child rows: `"inherit"` (same rule), a rule object, or omitted (blank for children). |
| `fallback` | A rule (usually `{"from": "mods.<key>"}`) used **only when every `from` source is empty in Alma** before any filtering. `mods.*` sources are rejected anywhere else, so legacy data can never override or be merged with Alma data. A rule with only a `fallback` always uses it. |

`mods.*` values come from the record's legacy Digital Grinnell MODS file (see D7): `extent`, `form`, `genre`, `creator_personal`, `creator_corporate`, `contributor_personal`, `contributor_corporate`.

`gems.*` values: `key`, `objectid`, `parentid`, `display_template`, `filename` (own file; a compound parent takes a borrowed child name with a `_` prefix — DART's convention, D10), `filenames` (all files for the row), `original_name` (the file's pre-rename Alma name, for deriving per-file identifiers under D12), `label` (Alma representation label), `representation_id`, `mime_type`, `dcmi_type`.

## Row structure

- **D1. One row per Alma bib; compound objects for multi-file bibs.** A bib with one file is one row. A bib with several files becomes a parent row (`display_template` = `compound_object`, no file of its own) plus one child row per file with `parentid` set to the parent's `objectid`. The parent's `original_file_name` is `_` + a borrowed child filename (D10 picks which), per DART's convention. This follows CollectionBuilder's compound-object conventions (`docs/compound_objects.md`). `compound_object` was chosen over `multiple` because Alma representations carry individual labels.
- **D2. Children are sorted by natural filename order** (`grinnell_10379…` before `grinnell_10380…`), and numbered in that order (D12). Alma returns representations in no useful order. The legacy order is in `tableOfContents`/`dginfo`, but it doesn't match the Alma files one-to-one (25 titles vs. 10 files).
- **D3. Children carry only row-specific metadata.** Following CollectionBuilder guidance, child rows get only the control fields, title, type, format, identifier, filename, rights, and Contributing Institution. Everything descriptive lives on the parent.
- **D4. `display_template` comes from the file's MIME type**: image → `image`, PDF → `pdf`, audio → `audio`, video → `video`, otherwise `record`. A bib with no files is `record`.
- **D8. Oral histories become one `transcript` item.** This applies to a bib whose files are exactly one audio or video file plus caption/transcript files (`*.vtt`, or `*TRANSCRIPT*.xml` in the legacy cue format), as in PHPP Oral Histories.
  - It becomes a single row with `display_template` = `transcript`, not a compound object. `original_file_name`, `format` and `type` describe the media file, and `Filename` lists all the files.
  - The caption file is converted to `transcripts/<media-stem>.csv` (`timestamp,speaker,words`) next to `collection_metadata.csv`, where `<media-stem>` is the media file's name without its extension — e.g. `grinnell_1-02.csv` for `grinnell_1-02.mp3` (files are renamed per D12, and captions are still recognized by their original Alma names). The site's `transcript` layout reads `_data/transcripts/<media-stem>.csv`, so copy the folder into the collection's `_data/`.
  - The legacy `oh_speaker` markup is split into one row per speaker turn. Short labels ("Judy") are expanded to the full names in single-speaker cues ("Judy Hunter").
  - The original caption files stay in `objects/`. If conversion fails, the bib falls back to D1.
- **D9. Every CSV row carries a maintained `key`.** Following the common-DG-utilities rules: an existing valid `key` (`dg_<epoch>` or `<slug>_dg_<epoch>`) is kept unchanged; otherwise the first `dg_<epoch>` fragment found in any field or filename is adopted; otherwise a new unique key is minted. Template rows key on the row's `objectid`, so the key lives as long as the manifest's IDs (D5), and a pre-existing valid `key` on a manifest record wins. GEMS adds a `key` column to the CSV even when a map doesn't declare one, and batches still merge with pre-key CSVs — their rows adopt keys from their `objectid`s. The `transcripts/<objectid>.csv` timed-text files keep their fixed `timestamp,speaker,words` shape; the objectid in their filename carries the key.
- **D5. `objectid` follows the site's `<slug>_dg_<n>` convention** (e.g. `tdps_dg_1781104642`). Parents and compound children each get their own ID.
  - `<slug>` is the manifest's `objectid_prefix` if you add one (to match a site slug such as `re26`); otherwise it is the slugified `collection_title`, e.g. `social-justice-at-grinnell`. Since 2026-10-01 the app has an **ObjectID prefix** field next to button 2) (as in DART): the typed value is slugified, overrides the manifest's stored value, and is saved back to the manifest as `objectid_prefix`, so later exports keep the same prefix when the field is left blank. Already-assigned IDs are never re-prefixed — only newly minted ones use it.
  - `<n>` starts at the current Unix time and counts up by one per row, in row order. It always starts above the highest `_dg_` number already used by this manifest or by any sibling `gems_*.json` manifest in the same collection folder, so batches never collide.
  - IDs are assigned on the first **Map and Export** and saved back into the manifest: `objectid` on each record, and `child_objectids` (keyed by filename) for compound children. Re-mapping the same manifest reuses them.
  - Prepared manifests without a `collection_title`, or CSV manifests, get bare `dg_<n>` IDs. CSV IDs aren't saved.
- **D6. DART supplies hosting fields.** `object_location`, `image_small`, and `image_thumb` are left blank for DART to fill.
- **D7. Legacy MODS fills gaps only; Alma always wins.** Records were edited in Alma after migration. For example, `grinnell:184`'s MODS still says "Copyright…" while Alma now says "Public Domain".
  - When **Legacy MODS folder** is set (e.g. OneDrive `Shared with Everyone/DG-Exports`), a record's MODS file is located from its legacy PID (`dc:identifier` `grinnell:<n>`) and the `dginfo` directory name: `<folder>/social-justice/grinnell_<n>_MODS.xml`, else `<folder>/grinnell_<n>_MODS.xml`.
  - The file is read only if some column's fallback is actually needed.
  - "Empty" is judged on the column's Alma source elements, not the column. For example, if Alma's `dc:creator` holds only an organization, `creator_personal` stays blank rather than taking a person from MODS.
  - MODS names are grouped as creators (roles author, creator, photographer, artist) or contributors (all other roles, e.g. `supporting host`), and split by MODS `type` (`personal`/`corporate`).
  - Only parent/single rows use fallbacks; compound children don't.

- **D10. Compound parents use DART's `_`-prefixed filename convention.** DART matches every CSV row to assets by `original_file_name`, so a compound parent — which has no file of its own in Alma — borrows a child's filename with a `_` prefix, e.g. `_grinnell_10379_OBJ.jpg`. The borrowed child is the first whose name is a web-friendly image (`.jpg`, `.jpeg`, `.png`, `.gif`, `.bmp`, `.webp` — never a `.tif`/`.tiff` preservation master), so the derivative DART copies onto the parent comes from the access image; with no such child, the first child in natural filename order is used. Child row order itself stays natural (D2); only the parent's pseudo-name is affected. DART skips `_`-prefixed rows when generating derivatives, then copies the named child's `image_small`/`image_thumb` onto the parent, and its csvdiff and Seeklight merges key on `original_file_name`, so blank parent names mis-diff or are silently dropped. The pseudo-name is only an index key: `objects/` holds only real files. A bib with no files at all (a `record` row) has no child name to borrow, so it uses `_` + its `objectid`. No real filename can start with `_` (`safe_filename` strips leading `.`/`_`), so pseudo-names never collide with files; the DG-with-CB-and-Pagefind site never reads `original_file_name`, so the convention is invisible to visitors.

- **D11. Long numeric-only Alma filenames are rebuilt from record context.** DART groups compound children purely by shared filename bases (see `GEMS_FILENAME_RULES.md`), and an Alma stored name that is one long number — an MMS ID or representation file PID, e.g. `991011591179304641.jpg` — is meaningless. When mapping, such a file is renamed (the file in `objects/` and `original_file_name` change together) to the stem of a meaningful sibling file in the same record, keeping its own extension — so a `grinnell_26615_OBJ.tiff` master and its MMS-ID-named access image both become base `grinnell_26615_OBJ` — else the record's legacy grinnell PID (`grinnell_26615.jpg`), else its slugified title. A second file rebuilt to the same name gets the usual clash suffix. Short numeric stems like `991.jpg` are kept: they can be legitimate sequence numbers (R2). Every Alma compound therefore has at least one meaningful child filename, and no MMS-ID filename reaches the CSV. Rebuilt names are deterministic, so re-exports of the same manifest reproduce them.

- **D12. Compound children are renumbered as a `<stem>-NN` sequence.** DART groups compounds purely by shared filename bases (GEMS_FILENAME_RULES.md), and per-file PIDs like `grinnell_21716_OBJ.jpg`, `grinnell_21717_OBJ.jpg`, … from unrelated compounds look like one giant sequence in a folder scan — one DART run merged 130+ files into a single compound. So every multi-file bib's files are renamed on export: the `<stem>` is the record's own grinnell PID (the smallest one among its files, or from `dc:identifier`), else the record's meaningful anchor, else its objectid — never a generic title slug like `photographs`, which would group unrelated compounds; and `-NN` is a two-digit sequence number in natural filename order (01, 02, …). A `grinnell_21716_OBJ.tiff` master and its MMS-ID access image therefore become `grinnell_21716-01.jpg` and `grinnell_21716-02.tiff`: one obvious sequence per compound. Child rows are already in that order (D2). The child `identifier` still recovers each file's own PID from its pre-rename name (`gems.original_name`), and the parent still borrows the first web-friendly image child (D10). Oral-history pairs are renamed too; captions are recognized by their original names (D8). Single-file bibs keep their (meaningful or rebuilt) names unsequenced.

## Column decisions

| Column | Source / rule | Rationale |
| --- | --- | --- |
| key | `gems.key`: the row's `objectid`, or the record's own valid `key` | Maintained for life under the common-DG-utilities rules (D9). |
| objectid | `gems.objectid`: `<slug>_dg_<n>` | See D5. |
| parentid | `gems.parentid` | Blank except on children. |
| display_template | `gems.display_template` | See D1/D4. |
| original_file_name | `gems.filename` | Alma file label, e.g. `grinnell_187_OBJ.jpg`, with long numeric-only names rebuilt from record context (D11). Compound parents carry `_` + a borrowed child's name (the first web-friendly image child if there is one, else the first child), and fileless `record` rows `_` + `objectid`, so DART can match every row by filename (D10). |
| originating_system_id | `record.mms_id`; children: Alma representation ID | Alma is now the system of record; this allows round-trips back to Alma. |
| object_location, image_small, image_thumb | — | Filled by DART (D6). |
| image_alt_text, thumb_focus | — | CollectionBuilder falls back to description/title for alt text. |
| title | `dc:title`, else `dcterms:title`; children: representation label, else filename | Representation labels are the legacy child titles. |
| creator_personal / creator_org | `dc:creator` + `dcterms:creator` (combined), split by a personal-name regex; fallback: MODS personal / corporate creators | DC doesn't distinguish persons from organizations. Values shaped like LC personal names (`Surname, Forename…`, optional second surname word) are treated as persons; everything else as organizations. Multi-word surnames beyond two words (e.g. `Van Der Berg, …`) will be misfiled as organizations. MODS only when Alma has no creator at all (D7). |
| interviewee, interviewer | — | No source element. |
| date | `dcterms:created`, else `dc:date`, else `dcterms:date` | The column is "Date Created", and `dcterms:created` is a clean year. |
| Time Period | `dcterms:temporal` | e.g. `Eighteen fifties`. |
| description | `dcterms:abstract`, else `dc:description`/`dcterms:description` (not split) | |
| Subject (Topic) / Subject (Person) | `dcterms:subject (dcterms:LCSH)` + untyped `dcterms:subject` (combined), split by the same personal-name regex | e.g. `Brown, John, 1800-1859` → Person. `dc:subject` is deliberately excluded: in this collection it holds legacy alternate titles (identical to `oldalttitle`), not subjects. |
| Subject (Organization) | — | Can't be reliably separated from topics in DC (Q4). |
| contributor_personal / contributor_org | `dc:contributor` + `dcterms:contributor` (combined), personal-name regex; fallback: MODS personal / corporate contributors | Same approach as creator. |
| location | `dcterms:spatial` | |
| latitude, longitude | — | No source element. |
| lanugage | `dc:language` + `dcterms:language` (combined) | The column name keeps the template's spelling (`lanugage`) so it matches the site's CSV. |
| source, provenance, Call Number, Archival Series, Box, Folder Title, Folder Number, Finding Aid Permalink | — | No source element in the sample. |
| Contributing Institution | constant `Grinnell College Libraries` | Every sample item is held by the Libraries. Confirm the wording (Q5). |
| publisher | `dcterms:publisher` + `dc:publisher` (combined) | |
| extent | `dcterms:extent`; fallback: MODS `physicalDescription/extent` | Alma DC has no extent for this collection, so MODS supplies it (e.g. `1 leaf`, `24 photographs`). |
| medium | `dcterms:medium`; fallback: MODS `physicalDescription/form` | MODS `form` describes the physical carrier (`paper`, `cardboard mounted photograph`). |
| genre | fallback only: MODS `genre` | Alma DC has no genre element. |
| type | `dcterms:type (dcterms:DCMIType)`, else `gems.dcmi_type`. Children: `gems.dcmi_type` | Uses Alma's DCMI vocabulary values (`Text`, `Still Image`). GEMS's computed values use the same labels. Compound parents have no DCMIType, so they take their children's shared type. |
| format | `gems.mime_type` | CollectionBuilder expects a MIME type. `dc:format` values (`born digital`, `reformated digital`) describe digital origin, not file format. |
| Digital Collection Title | `dcterms:isPartOf` without `Digital Grinnell` | `Digital Grinnell` is the whole repository, not a collection. |
| Digital Collection Permalink, related, Avian Identifier, Disclaimer | — | No source element. |
| identifier | `dc:identifier` value matching `grinnell:<n>`; children: derived from the file's original Alma name (`gems.original_name`) `grinnell_<n>_…` | Keeps the legacy Islandora PID for continuity with old URLs and handles. |
| Filename | `gems.filenames` | Compound parents list all child filenames. |
| Item Permalink | `dcterms:identifier (dcterms:URI)`, else `dc:identifier`, value matching `http(s)://hdl.handle.net/…` | The URI-typed identifier is the authoritative handle. Handles exist only for parent/single objects. |
| rights | `dc:rights`, else `dcterms:rights`, HTML stripped | The rights anchor text, e.g. `Public Domain in the United States`. |
| Standardized Rights | the rightsstatements.org `href` in `dc:rights`/`dcterms:rights`, normalized to `http://rightsstatements.org/vocab/<code>/<version>/` | Uses the canonical URI instead of the language-specific page URL. The plain copyright statement has no URL and stays blank (Q6). |

## Source elements intentionally not mapped

| Element | Reason |
| --- | --- |
| `dc:subject`, `dcterms:alternative`, `oldalttitle` | Alternate titles. The template has no alternative-title column. |
| `dc:type` | Coarse legacy Islandora types (`compound`, `text`, `image`), superseded by `dcterms:type (dcterms:DCMIType)`. |
| `dcterms:tableOfContents` | Lists child titles, which already appear as child rows. |
| `dc:format` | Digital-origin statement (see `format` above). |
| `dcterms:dateAccepted` | Not a creation date. |
| `googlesheetsource`, `dginfo`, `compoundrelationship` | Migration and administrative data from the Islandora-to-Alma move. |
| `dc:identifier` `alma:…` value | Superseded by `originating_system_id`. |

## Open questions

- ~~**Q1.**~~ Resolved 2026-09-30: use `<slug>_dg_<n>` (D5).
- ~~**Q2.**~~ Resolved 2026-09-30: DART defines `object_location` (D6).
- ~~**Q3.**~~ Resolved 2026-09-30: DART defines thumbnails and smalls (D6).
- **Q4.** Can organizational subjects be identified (e.g. from MARC 610 instead of DC)?
- **Q5.** What is the exact preferred wording for Contributing Institution?
- **Q6.** Should the standard copyright statement map to `http://rightsstatements.org/vocab/InC/1.0/`?

## Decision log

Add new entries at the top. Record the date, the column(s), what changed in the JSON map, and why. Mark any answered open question as resolved here.

| Date | Column(s) | Decision | Reason |
| --- | --- | --- | --- |
| 2026-10-02 | original_file_name, identifier | Compound children are renumbered `<stem>-NN` on the record's own grinnell PID (D12); child identifiers come from the pre-rename name. | A DART folder scan read unrelated compounds' per-file PIDs as one 130+-part sequence; obvious per-compound sequences fix it. |
| 2026-10-01 | original_file_name | Long numeric-only Alma filenames (MMS IDs, file PIDs) are rebuilt from a meaningful sibling stem, the grinnell PID, or the title (D11). | DART groups compounds by shared filename bases; MMS-ID names are meaningless and defeat grouping (GEMS_FILENAME_RULES.md). |
| 2026-10-01 | objectid | Added the app's **ObjectID prefix** input field (D5); the typed slug overrides and is saved as the manifest's `objectid_prefix`. | Match a site slug when minting new IDs without editing the manifest by hand, as in DART. |
| 2026-10-01 | original_file_name | A compound parent borrows the first JPG-style image child's name rather than a TIFF master when both exist (D10). | The derivative DART copies onto the parent then comes from the lightweight access image, not the preservation master. |
| 2026-10-01 | original_file_name | Fileless `record` rows get `_` + `objectid` (D10). | Every CSV row now has a non-blank unique match key for DART. |
| 2026-10-01 | original_file_name | Compound parents get `_` + first child's filename instead of a blank (D10). | DART treats `original_file_name` as the universal match key; blank parent names were skipped by derivative generation and broke csvdiff/Seeklight merges. |
| 2026-10-01 | key | Added the `key` column and adopted common-DG-utilities key handling (D9). | Every CSV record keeps a stable `dg_<epoch>` identity for life. |
| 2026-10-01 | display_template, Filename | Audio/video + caption bibs become one `transcript` item with a converted `transcripts/<objectid>.csv` (D8). | Matches the site's `transcript` layout for oral histories (PHPP). |
| 2026-10-01 | extent, medium, genre, creator_*, contributor_* | Added legacy MODS `fallback` rules and the **Legacy MODS folder** setting (D7). | Fill gaps from the pre-migration records without overriding post-migration edits in Alma. |
| 2026-10-01 | all metadata-sourced columns | Sources switched to qualified keys (`dc:*`, `dcterms:*`, with `xsi:type`). Added `combine`. Subjects now come only from `dcterms:subject`; `type` from `dcterms:type (dcterms:DCMIType)`. | GEMS previously merged `dc:` and `dcterms:` elements and dropped `xsi:type`, which mixed alternate titles into subjects and legacy types into DCMI types. |
| 2026-09-30 | objectid, parentid | `objectid` is `<slug>_dg_<n>`, persisted in the manifest (D5). Resolves Q1. | Matches site convention. |
| 2026-09-30 | object_location, image_small, image_thumb | Rules removed; left blank (D6). Resolves Q2, Q3. | DART defines hosting and derivative fields. |
| 2026-09-30 | all | Initial map (D1–D4 and the column table above). | Built from the Social Justice at Grinnell manifest `2026-09-30_14-04-05_CDT`. |
