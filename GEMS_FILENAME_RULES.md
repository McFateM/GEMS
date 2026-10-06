# DART Filename Rules for Compound Objects — A Guide for GEMS

**Audience:** GEMS developers building CSV exports for Digital.Grinnell workflows.
**Purpose:** DART decides which files are parts ("children") of a compound object **purely from their filenames**. GEMS metadata is later merged into DART's core metadata CSV by matching on the `original_file_name` column, so the filenames GEMS reports must (a) exactly match the real files on disk and (b) follow DART's naming conventions — otherwise compound grouping fails or, worse, mis-groups unrelated files.

GEMS never assigns DART identifiers and never creates parent/compound rows. Its only jobs: **name files well** and **report exact filenames**.

---

## How DART Uses Filenames (30-second version)

1. **Function 1** scans a folder of asset files and analyzes filename patterns.
2. Files sharing a filename **base** are grouped into compound objects:
   - Exactly **one untitled compound parent per folder**.
   - A nested **`multiple`** sub-object for each group containing 2+ numbered files.
   - Unnumbered parts (Poster, Program, Cover) attach directly to the compound parent.
3. DART assigns durable IDs (`<collection-id>_dg_<epoch>`) to every object, parent, and child.
4. **Function 2** exports a CollectionBuilder CSV with `objectid`, `parentid`, `original_file_name`, `display_template`, etc.
5. External metadata (GEMS, Alma, Seeklight) is merged into the core CSV afterward, matching rows on **`original_file_name`**.

---

## The Filename Rules

### R1 — Shared base prefix
All parts of one compound object must **start with the same base text**.
- Comparison is case-insensitive; the file extension is ignored.
- The base must be **at least 3 characters**. `AB-1.jpg` / `AB-2.jpg` will *not* group ("ab" is too short).

### R2 — Sequence numbers go last
A part's sequence number must be the **final element of the filename**, immediately before the extension, optionally preceded by a separator:

| Filename | Parsed as |
|---|---|
| `Wit 001.jpg` | ✅ base "Wit", sequence 1 |
| `Wit_042.tif` | ✅ base "Wit", sequence 42 |
| `AnnaChristie-F14-23.pdf` | ✅ base "AnnaChristie-F14", sequence 23 |
| `100 Nights-15.jpg` | ✅ base "100 Nights", sequence 15 (leading numbers inside the base are fine) |
| `001 Wit.jpg` | ❌ number at the start is not a sequence number — see Edge Cases |
| `Wit 001 verso.jpg` | ❌ number not at end → treated as unnumbered |

### R3 — Separators: space, hyphen, or underscore
- Between the base and the number/suffix use ` `, `-`, or `_`.
- **Be consistent within a set.** Mixed separators create different bases and defeat grouping:
  `exhibit_2013_001.tif`, `exhibit 2013 002.tif`, `exhibit-2013-003.tif` → three different bases, no group.
- A separator is **required** between the base and a descriptor: `Wit Poster.jpg` attaches to the "wit" group; `WitPoster.jpg` does not and becomes a standalone object.

### R4 — Two or more parts form a group
- Compounds require **2+ files** sharing a base.
- A file whose base is unique in its folder becomes a standalone object (no parent). That's valid — just don't expect a compound for it.

### R5 — All parts of a compound live in the same folder
- Grouping never crosses folder boundaries; DART creates one compound parent per folder.
- **Best practice: one intellectual object per folder.** If a folder holds several unrelated groups (e.g., "Project A …" and "Project B …"), they all share the folder's single untitled compound parent — legal, but harder to title and manage downstream.

### R6 — Numbering gaps and padding
- Missing numbers are tolerated: `001, 002, 005, 006` still forms one sequence.
- Zero-padding (`001` vs `1`) is optional — DART pads sequence numbers for display itself — but padded filenames sort more predictably everywhere else, so prefer them.

### R7 — Never invent `dg_<digits>` tokens in filenames
- DART treats any `dg_<number>` found in a filename as a **pre-assigned permanent identifier** and preserves it.
- Fabricated or recycled `dg_` values corrupt DART's ID persistence. Only real DART-assigned IDs may appear in filenames.

### R8 — Don't fake ordering with trailing numbers on supplementary parts
- `Wit Poster 000.jpg` ❌ — the trailing number changes the parsed base and breaks grouping.
- Child display order is controlled by reordering rows in the exported CSV, not by filename tricks.

---

## What the GEMS CSV Must Contain

| Column | Requirement |
|---|---|
| `original_file_name` | **Required.** The exact on-disk filename, including extension, character-for-character. This is the key DART uses to match and merge external metadata rows. |
| `objectid`, `parentid` | **Leave absent or empty.** DART assigns durable IDs and generates compound parent / `multiple` rows itself. Do not synthesize them. |
| Metadata fields | Use canonical unprefixed CollectionBuilder names: `title`, `description`, `date`, `subject`, `creator`, etc. **Never** use legacy `dc_`-prefixed names. |

Additional requirements:

- **One row per physical asset file.** Do NOT create rows for compound or `multiple` parents — DART generates those (a compound parent's `original_file_name` is the first child's filename with a leading underscore, e.g., `_Wit 001.jpg`, and is only an index, not a real file).
- **Supported file types only.** DART processes: images (`.jpg .jpeg .png .gif .tif .tiff .bmp .webp`), `.pdf`, video (`.mp4 .mov .avi .mkv .wmv .flv .webm`), audio (`.mp3 .wav .flac .aac .ogg .m4a .wma`), and archives (`.zip .tar .gz .7z .rar .bz2`). Files with other extensions are ignored entirely.
- Grouping is case-insensitive, but the `original_file_name` value must match the real file **exactly** (including case and extension) for merging to work.

---

## On-Disk Layout: One Folder per Record (GEMS Migration)

DART creates **exactly one untitled compound parent per folder** and, as of v6.1, scans the Inputs Folder **recursively**. So GEMS writes **every record's files into their own subfolder** — a compound under its compound stem, a single-file record under its file's own stem:

```
objects/grinnell_10171/grinnell_10171-01.tiff
objects/grinnell_10171/grinnell_10171-02.tiff
objects/grinnell_10186/grinnell_10186-01.tiff
objects/grinnell_10186/grinnell_10186-05.jpg
objects/grinnell_103_OBJ/grinnell_103_OBJ.pdf   ← single-file bib gets its own folder
```

A folder holding one file can never group, so unrelated singles that share a filename base (`grinnell-310.pdf`, `grinnell-1135.pdf`, `grinnell_214_OBJ.pdf`, …) stay standalone in DART instead of collapsing into one giant compound. Each compound subfolder still yields exactly one DART compound whose parent row is `_` + its first sequenced child (e.g., `_grinnell_10171-01.tiff`). GEMS's parent rows borrow that same first-sequenced-child name, so they merge onto the rows DART generates.

Two consequences:

- **Compound parent name = first sequenced child.** DART names a folder's compound parent after the first child in numbered-first-then-alphabetical order — *not* a "preferred access image". GEMS matches this exactly; it no longer substitutes a web-friendly (`.jpg`) child for a `.tiff` master.
- **Point DART at a fresh working folder.** `file_to_id_map` keys child IDs by full file path, and compound IDs by folder path. Moving an existing flat export into subfolders changes every path, so reusing a working folder built on the old flat layout leaves stale mappings; start a new one. Prefer re-exporting with current GEMS; a legacy flat export of **compounds only** can alternatively be reorganized after the fact with DART's `scripts/organize_compound_folders.py` — it groups by shared filename base, so it cannot separate individual exports that share one (`grinnell-310.pdf`, `grinnell-1135.pdf`, … would be herded into one folder and still mis-group).

---

## Examples

### ✅ Groups correctly

```
Wit 001.jpg
Wit 002.jpg
…
Wit 100.jpg
Wit Poster.jpg        ← unnumbered part, attaches via shared base + separator
Wit Program.pdf
```
→ One compound for the folder, one `multiple` object for the 100 numbered parts, Poster and Program as direct children of the compound.

```
Traditions and Encounters - Poster.pdf
Traditions and Encounters_Program.pdf
```
→ Grouped even without any numbered file: both share the base "traditions and encounters" (≥ 3 chars, 2+ files). Adding one numbered file (`Traditions and Encounters 01.pdf`) makes the grouping bulletproof.

### ❌ Won't group (or mis-groups)

```
AB-1.jpg, AB-2.jpg                    → base "ab" < 3 chars; both become standalone objects
Poster.pdf, Program.pdf               → no shared base; two standalone objects
photo1.jpg, photo2.jpg, photo9.jpg    → technically groups, but a base this generic can
                                        swallow unrelated "photo…" files in the same folder.
                                        Use project-specific bases (e.g., "2024_Exhibit_…").
Wit Poster 000.jpg                    → trailing number changes the base; breaks the "wit" group
```

### ⚠️ Edge case: leading numbers can mis-group

`2024-Roses.jpg` and `2024-Lilies.jpg` have no trailing number, so DART falls back to removing the last word after a separator — leaving base **"2024"** (4 characters, valid). Result: two unrelated objects get grouped together. Avoid filenames that start with a bare number + separator followed by a free-text word; embed the number in the base instead (`Roses 2024 01.jpg`).

---

## How GEMS Complies

- **Every CSV row has a non-blank, unique `original_file_name`.** Compound parents carry `_` + a borrowed child's filename (DART's own indexing convention), and metadata-only records carry `_` + their `objectid`. These pseudo-names are index keys only — the files on disk and the child-row values always match real files exactly.
- **Meaningless names are rebuilt, not reported.** When Alma's stored name is one long number (an MMS ID or representation file PID, e.g. `991011591179304641.jpg`), GEMS renames the file during mapping — permitted per this workflow — from record context, so no MMS-ID filename reaches the CSV.
- **Each compound is one obvious `<stem>-NN` sequence.** Every multi-file bib's files are renamed on export to the record's own grinnell PID plus a two-digit sequence number in natural filename order — e.g. `grinnell_21716-01.jpg`, `grinnell_21716-02.tiff` — so a DART folder scan sees exactly one sequence per compound instead of reading unrelated compounds' per-file PIDs (`grinnell_21716…`, `grinnell_21717…`) as a single 130+-part group (R1/R2/R4). Single-file bibs keep meaningful names unsequenced.
- **No invented `dg_` tokens in filenames** (R7). `<slug>_dg_<n>` values appear only in the `objectid` column and in the `_`-prefixed index value of metadata-only rows, where it is that row's own real ID.
- **No ordering tricks** (R8). Children are exported in natural filename order; display order comes from CSV row order, never from fabricated trailing numbers.

---

## Quick Checklist for a GEMS Export

1. ☐ Every compound part is named `<Base><sep><seq>.<ext>` or `<Base><sep><descriptor>.<ext>`.
2. ☐ The base is identical (case aside) across all parts of the object and is ≥ 3 characters.
3. ☐ One separator style per set (all spaces, all hyphens, or all underscores).
4. ☐ Sequence numbers appear only at the very end of the name, before the extension.
5. ☐ All parts of each compound object are in the same folder — ideally one object per folder.
6. ☐ The CSV has one row per real file, and every `original_file_name` matches the on-disk filename exactly.
7. ☐ No invented `dg_` tokens in filenames; no `dc_`-prefixed column names; no parent/compound rows.

---

## Reference

For the full algorithm and troubleshooting detail, see DART's own documentation:

- `BEST_PRACTICES.md` — filename conventions and compound grouping guidance
- `FUNCTION_1_ANALYZE_ASSETS.md` — the three-pass grouping algorithm and ID persistence
- `FUNCTION_2_EXPORT_CSV.md` — the exact CSV shape DART produces (including compound parent rows)
- `FUNCTION_4_COMPARE_MERGE_CSV.md` — how external CSVs merge into the core metadata CSV on `original_file_name`
