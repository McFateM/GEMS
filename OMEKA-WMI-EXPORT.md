# Omeka WMI export history

## Session and outcome

On the evening of **October 22, 2026 (America/Chicago, CDT)**, we investigated
how to export WMI objects and metadata from Grinnell's Omeka S installation
with usable original-media URLs. An existing JSON export contained media API
references that could not be used for media retrieval in the intended workflow.
Admin access made it possible to generate a new export through Bulk Export.

The session produced a completed CSV export for **item set 7397**, with
descriptive metadata, WMI-specific properties, item/media IDs, and direct
original-file URLs. The user downloaded it and placed it in this repository:

- [CSV-20261023-022505.csv](./CSV-20261023-022505.csv)
- Size of the local file: **2,547,969 bytes**
- SHA-256: `fcc0cebf1589e2f6b792e23cc0f43b77c9a70642db4e189ec1642d82a981d129`

The filename uses the server's UTC date/time: October 23 at 02:25:05 UTC is
October 22 at 9:25:05 p.m. CDT. It is the same evening's export, not a later run.

## 1. Initial problem and guidance

The starting point was the
[Bulk Export dashboard](https://omeka-s.grinnell.edu/admin/bulk-export/bulk-export).
The important distinction was between:

- A media API resource URL, such as
  `https://omeka-s.grinnell.edu/api/media/676`, which describes a media record.
- The media record's `o:original_url`, which points to the actual downloadable
  original file.
- The ingest source, which may describe an old server or source location and
  should not be mistaken for the current original-file URL.

The initial recommendation was to export CSV first so that the metadata and
media URLs could be inspected easily. We also discussed:

- Testing direct URLs without an authenticated browser session.
- Testing from the eventual GEMS execution host, since browser access alone
  does not establish server-side access.
- Exporting originals as a ZIP if the installed Bulk Export version supports it.
- Avoiding a simple repeat of the JSON/JSON-LD export, which might retain the
  same unresolved media API references.

The first attempts to inspect the admin page were blocked by Cloudflare,
including an HTTP 403 and a browser security-verification page. Initial
instructions therefore came from the current upstream module documentation,
not from the installed form.

Current upstream documentation describes separate "Url to original" and
"File name of original" fields, and ZIP options. Those options were not
established as available on this installation.

## 2. Inspecting the installed export form

After the user supplied **set ID 7397** and shared an authenticated browser
page, we successfully inspected the actual Omeka admin interface.

The site footer reported **Omeka S 3.1.2**. We did not record the installed
Bulk Export module version.

The dashboard offered existing exporters for CSV, OpenDocument spreadsheet,
OpenDocument text, text, and TSV. We used the existing **CSV exporter (ID 1)**
through its
[Start export form](https://omeka-s.grinnell.edu/admin/bulk-export/exporter/1/start),
rather than editing the exporter's shared configuration page.

The installed form differed from current upstream examples:

- It offered **Media (for item) -> Url / File**.
- Its field key was `o:media[file]`, using bracket notation.
- It did not offer the separate "Url to original" selection described in the
  initial guidance.

The subsequent output confirmed that **Url / File** produced direct
original-file URLs for the file-backed media sampled.

## 3. Exact export settings

We selected the following fields for this run:

| Setting | Value |
|---|---|
| Exporter | CSV, ID 1 |
| Resource types | Items (`o:Item`) |
| Resource query | `item_set_id=7397` |
| Metadata | Resource internal ID (`o:id`) |
| Metadata | All used properties (`properties`) |
| Metadata | Media internal ID (`o:media[o:id]`) |
| Metadata | Media Url / File (`o:media[file]`) |
| Metadata to exclude | None |
| Use a background job | Checked |
| Metadata names or headers | RDF names |
| Format of values | String |
| Format of linked resources | ID |
| Property for linked resources | `dcterms:identifier` |
| Format of URI | URI and label separated by a space |
| Multi-value separator | ` | ` |
| CSV delimiter | Comma |
| CSV enclosure | Double quote |
| CSV escape | Backslash |

Comment entered:

```text
WMI item set 7397: all used metadata, item/media IDs, and media file URLs.
```

After choosing **Continue**, the confirmation page showed these writer
parameters:

```json
{
  "delimiter": ",",
  "enclosure": "\"",
  "escape": "\\",
  "separator": " | ",
  "format_fields": "name",
  "format_generic": "string",
  "format_resource": "id",
  "format_resource_property": "dcterms:identifier",
  "format_uri": "uri_label",
  "resource_types": ["o:Item"],
  "metadata": [
    "o:id",
    "properties",
    "o:media[o:id]",
    "o:media[file]"
  ],
  "metadata_exclude": null,
  "query": "item_set_id=7397"
}
```

We then chose **Start export**.

## 4. Completion and output locations

The background export completed successfully:

- Export ID: **15**
- Job ID: **901**
- Job status: **Completed**
- Started: **October 22, 2026, 9:25:05 p.m. CDT**
- Ended: **October 22, 2026, 9:25:15 p.m. CDT**

Relevant links:

- [Job 901](https://omeka-s.grinnell.edu/admin/job/901)
- [Export 15 parameters](https://omeka-s.grinnell.edu/admin/bulk-export/export/15)
- [Export 15 logs](https://omeka-s.grinnell.edu/admin/bulk-export/export/15/logs)
- [Download the CSV](https://omeka-s.grinnell.edu/files/bulk_export/CSV-20261023-022505.csv)
- [Local CSV](./CSV-20261023-022505.csv)

The dashboard displayed the completed export under the comment recorded above.
Fetching the CSV through the authenticated browser returned HTTP 200 with
content type `text/csv`.

No ZIP of originals was generated, and no bulk download of media files was
performed during this session.

## 5. Verified CSV contents

The generated CSV was parsed in the browser, respecting quoted cells and
embedded newlines. The results were:

| Check | Result |
|---|---:|
| Item rows, excluding the header | **656** |
| Columns | **70** |
| Attached media IDs | **2,774** |
| Direct file URL entries | **1,877** |
| Items without any file URL | **0** |
| Rows with a different column count from the header | **0** |

The file contains standard descriptive properties, custom `wmi:*` properties,
and `lrmi:learningResourceType`. "All used properties" was selected without a
metadata exclusion or the alternative small-property-only selection.

All exported file URLs had this host:

```text
digital-grinnell.nyc3.digitaloceanspaces.com
```

They used the storage path:

```text
https://digital-grinnell.nyc3.digitaloceanspaces.com/omeka-s/digital-grinnell/original/
```

The local CSV begins with a UTF-8 byte-order mark (BOM). Future readers should
handle that explicitly so that the first header is recognized as `o:id`.
Descriptions contain embedded newlines, so physical line counts are not item
counts; use a real CSV parser.

## 6. Anonymous original-file access tests

Two URLs from the first exported item, item **626** ("rebab"), were tested
outside the authenticated browser using `curl -I`:

| Media | Stored filename | HTTP status | Content type | Content length |
|---|---|---:|---|---:|
| Image, media 676 | `0065c089e1d69a63249485868ded0fec.jpg` | **200** | `image/jpeg` | 41,408 bytes |
| Audio, media 677 | `445e942a2ea918d12aaba031aa0bf7c3.mp3` | **200** | `audio/mpeg` | 479,398 bytes |

Reproducible checks:

```sh
curl -I --max-time 30 \
  'https://digital-grinnell.nyc3.digitaloceanspaces.com/omeka-s/digital-grinnell/original/0065c089e1d69a63249485868ded0fec.jpg'

curl -I --max-time 30 \
  'https://digital-grinnell.nyc3.digitaloceanspaces.com/omeka-s/digital-grinnell/original/445e942a2ea918d12aaba031aa0bf7c3.mp3'
```

These checks established anonymous access to the two sampled originals without
going through Omeka's API or its Cloudflare-protected admin pages. They did
**not** validate every exported URL, download full file bodies, or establish
access from the eventual Linux processing host.

## 7. Media IDs and file URLs are not positional pairs

There are more media IDs than file URLs. We inspected all four media records
attached to the first item through the authenticated browser:

| Media ID | Ingester | Renderer | Original URL |
|---|---|---|---|
| 676 | `url` | `file` | Present; JPG tested above |
| 678 | `html` | `html` | Null |
| 677 | `url` | `file` | Present; MP3 tested above |
| 679 | `html` | `html` | Null |

This confirmed that some attached media are HTML records rather than
downloadable originals. We did not classify all remaining media records.

**Do not zip together the media-ID and file-URL lists by array position.**
For this first item, four IDs accompany only two file URLs. The CSV's URL
column is useful as an item-level list of downloadable files, but does not
preserve a complete per-media ID-to-URL mapping.

The sampled file media also retained old `omeka1.grinnell.edu` ingest sources.
Those are not the current DigitalOcean original URLs and should not replace
the exported file links.

## 8. What this means for GEMS

The export solves the immediate need to obtain metadata and direct file URLs
without depending on media API resolution during later downloads.

It does **not** by itself complete GEMS integration:

- As documented in the [README](./README.md), the existing Omeka JSON path
  supports embedded `o:media` entries containing `o:original_url`, or resolves
  media API references to obtain those fields.
- This CSV is not a drop-in replacement for that JSON input.
- A conversion or CSV importer adjustment remains necessary before using it
  through that workflow.
- A converter must preserve WMI-specific properties, multi-valued metadata,
  and item-to-file associations.
- Preserve the distinction between Omeka's internal `o:id` and descriptive
  identifiers such as `dcterms:identifier`.
- Exported linked-resource values use IDs under this run's settings; they
  should not be assumed to be fully expanded resource descriptions.
- Recovering HTML media or exact media-ID-to-file associations requires
  additional data; this CSV alone does not establish those relationships.

Suggested next steps, not performed during this session:

1. Choose whether to convert the CSV into the existing GEMS-supported input
   shape or add explicit CSV support.
2. Define handling for custom WMI metadata and non-file media.
3. Test direct-file access from the actual GEMS processing host.
4. Run a small end-to-end import/download test, including a multi-file item.
5. Validate the complete URL inventory before declaring all media retrieved.

No GEMS application code, importer behavior, or Omeka access-control settings
were changed as part of this export work.

## References

- [Bulk Export upstream documentation](https://github.com/Daniel-KM/Omeka-S-module-BulkExport#readme)
- [Current upstream media-field definitions](https://github.com/Daniel-KM/Omeka-S-module-BulkExport/blob/master/src/Form/Formatter/MetadataSelectTrait.php)
- [Current upstream JSON formatter](https://github.com/Daniel-KM/Omeka-S-module-BulkExport/blob/master/src/Formatter/Json.php)
- [GEMS README](./README.md)

Upstream references describe the current module source and may not match the
older installed form. The executed settings and observed output recorded here
take precedence for reproducing this particular export.
