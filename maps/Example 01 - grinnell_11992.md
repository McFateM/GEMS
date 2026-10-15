The following metadata source record for `grinnell:11992` dumped from Alma maps to CollectionBuilder as you see here.

```xml
<record xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns="http://alma.exlibrisgroup.com/dc/01GCL_INST" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dc="http://purl.org/dc/elements/1.1/">
  <compoundrelationship xml:lang="eng">child of: grinnell:11995</compoundrelationship>
  <googlesheetsource xml:lang="eng">0242  https://docs.google.com/spreadsheets/d/1JzW8TGU8qJlBAlyoMyDS1mkLTGoaLrsCzVtwQo-4JlU/edit?usp=sharing</googlesheetsource>
  <dcterms:abstract xml:lang="eng">From left to right: Ivan Palmer, Lorraine Palmer and Mary Lou Palmer.</dcterms:abstract>
  <dcterms:created xml:lang="eng">1952</dcterms:created>
  <dcterms:extent xml:lang="eng">1 sheet</dcterms:extent>
  <dc:format xml:lang="eng">reformatted digital</dc:format>
  <dcterms:format xsi:type="dcterms:IMT" xml:lang="eng">image/tiff</dcterms:format>
  <dc:identifier xml:lang="eng">991011597366604641</dc:identifier>
  <dc:identifier xml:lang="eng">grinnell:11992</dc:identifier>
  <dc:identifier xml:lang="eng">http://hdl.handle.net/11084/11992</dc:identifier>
  <dc:identifier>alma:01GCL_INST/bibs/991011597366604641</dc:identifier>
  <dcterms:isPartOf xml:lang="eng">Poweshiek History Preservation Project</dcterms:isPartOf>
  <dcterms:isPartOf xml:lang="eng">Drake Community Library (Grinnell, Iowa) Archives</dcterms:isPartOf>
  <dcterms:isPartOf xml:lang="eng">Digital Grinnell</dcterms:isPartOf>
  <dc:language xml:lang="eng">English</dc:language>
  <dcterms:provenance xml:lang="eng">Cynthia Levy</dcterms:provenance>
  <dcterms:publisher xml:lang="eng">Poweshiek History Preservation Project</dcterms:publisher>
  <dc:relation xml:lang="eng">Hula Dancing at the Country Club</dc:relation>
  <dc:rights xml:lang="eng">Copyright to this work is held by the author(s), in accordance with United States copyright law (USC 17). Readers of this work have certain rights as defined by the law, including but not limited to fair use (17 USC 107 et seq.).</dc:rights>
  <dcterms:spatial xml:lang="eng">Grinnell (Iowa)</dcterms:spatial>
  <dc:subject xml:lang="eng">1950s</dc:subject>
  <dc:subject xml:lang="eng">Grinnell</dc:subject>
  <dc:subject xml:lang="eng">Family Life</dc:subject>
  <dcterms:subject xsi:type="dcterms:LCSH" xml:lang="eng">Family reunions</dcterms:subject>
  <dcterms:subject xsi:type="dcterms:LCSH" xml:lang="eng">Palmer family</dcterms:subject>
  <dcterms:subject xsi:type="dcterms:LCSH" xml:lang="eng">Hula (Dance)</dcterms:subject>
  <dc:title xml:lang="eng">Hula Dancing at the Country Club, 1 of 3</dc:title>
  <dc:type xml:lang="eng">image</dc:type>
  <dcterms:type xsi:type="dcterms:DCMIType" xml:lang="eng">Still Image</dcterms:type>
</record>
```

## Current GEMS mapping to the target CSV

This table documents the existing rules in [alma-dc-to-grinnell.json](alma-dc-to-grinnell.json), not a proposed AI mapping. It was checked by parsing the XML above with GEMS's metadata extractor and evaluating the template rules. **Not all source metadata is mapped.** Each of the 29 XML element occurrences is accounted for below.

The destinations describe the main CSV row for this Alma bib. If the bib has multiple representation files, GEMS creates a compound parent row for this bib and additional file-child rows; most descriptive fields appear only on that parent. Being an Alma/Islandora child of `grinnell:11995` does not itself make this bib a CSV child of that object.

| # | XML field | Source value | Target CSV column(s) | Result / omission |
| --- | --- | --- | --- | --- |
| 1 | `compoundrelationship` | `child of: grinnell:11995` | None | **Omitted.** GEMS does not use this relationship to set `parentid` or join separate bibs into the original compound. |
| 2 | `googlesheetsource` | `0242` plus the Google Sheets URL above | None | **Omitted.** Administrative migration reference; no rule populates `source` from it. |
| 3 | `dcterms:abstract` | From left to right: Ivan Palmer, Lorraine Palmer and Mary Lou Palmer. | `description` | Preserved verbatim as prose. Names in the abstract are not separately extracted into person columns. |
| 4 | `dcterms:created` | `1952` | `date` | `1952`. Does not populate `time_period`, which requires `dcterms:temporal`. |
| 5 | `dcterms:extent` | `1 sheet` | `extent` | `1 sheet`. Existing Alma value takes precedence over any legacy MODS fallback. |
| 6 | `dc:format` | `reformatted digital` | `format` | Appended after the inferred MIME type, e.g. `image/jpeg; reformatted digital`. With no file, `format` is `reformatted digital`. |
| 7 | `dcterms:format` with `xsi:type="dcterms:IMT"` | `image/tiff` | None directly | **XML value omitted.** CSV `format` comes from `gems.mime_type`, inferred from the exported filename, not this field. It can therefore differ, e.g. `image/jpeg` for a JPG file. |
| 8 | `dc:identifier` | `991011597366604641` | `originating_system_id` indirectly | This XML value is filtered out of `identifier` and `item_permalink`. The same MMS ID is retained in `originating_system_id` from the separate top-level `record.mms_id` supplied by Alma retrieval. |
| 9 | `dc:identifier` | `grinnell:11992` | `identifier` | `grinnell:11992`, selected by the `^grinnell:\d+$` filter. |
| 10 | `dc:identifier` | `http://hdl.handle.net/11084/11992` | `item_permalink` | `http://hdl.handle.net/11084/11992`, selected by the handle URL filter. |
| 11 | `dc:identifier` | `alma:01GCL_INST/bibs/991011597366604641` | None | **Omitted.** The Alma URI is not retained; the numeric record ID is available through `originating_system_id`. |
| 12 | `dcterms:isPartOf` | `Poweshiek History Preservation Project` | `digital_collection_title` | Retained as the first value. |
| 13 | `dcterms:isPartOf` | `Drake Community Library (Grinnell, Iowa) Archives` | `digital_collection_title` | Retained as the second value, joined with `; `. This descriptive text does not determine Alma collection membership or the export's collection selection. |
| 14 | `dcterms:isPartOf` | `Digital Grinnell` | None | **Excluded** by the `^Digital Grinnell$` rule. The final collection-title cell is `Poweshiek History Preservation Project; Drake Community Library (Grinnell, Iowa) Archives`. |
| 15 | `dc:language` | `English` | `lanugage` | `English`. The misspelled target column name `lanugage` is the literal name in the current template. |
| 16 | `dcterms:provenance` | `Cynthia Levy` | `provenance` | `Cynthia Levy`. Not mapped to contributor or creator columns. |
| 17 | `dcterms:publisher` | `Poweshiek History Preservation Project` | `publisher` | Preserved verbatim. |
| 18 | `dc:relation` | `Hula Dancing at the Country Club` | `related` | `Hula Dancing at the Country Club`. Combined with any `dcterms:relation` values. |
| 19 | `dc:rights` | Copyright statement above | `rights`; evaluated for `standardized_rights` | Full statement preserved in `rights` (HTML would be stripped if present). `standardized_rights` remains **blank** because this statement has no rightsstatements.org link; GEMS does not infer an `InC` URI from the wording. |
| 20 | `dcterms:spatial` | `Grinnell (Iowa)` | `location` | `Grinnell (Iowa)`. Coordinates are not inferred; `latitude` and `longitude` remain blank. |
| 21 | `dc:subject` | `1950s` | `keywords` | First keyword. Does not populate `time_period`. |
| 22 | `dc:subject` | `Grinnell` | `keywords` | Second keyword. Not added to topic or location columns. |
| 23 | `dc:subject` | `Family Life` | `keywords` | Third keyword. Final cell: `1950s; Grinnell; Family Life`. |
| 24 | `dcterms:subject` with `xsi:type="dcterms:LCSH"` | `Family reunions` | `subject_topic` | Retained as the first topic. Does not match the personal-name pattern. |
| 25 | `dcterms:subject` with `xsi:type="dcterms:LCSH"` | `Palmer family` | `subject_topic` | Retained as the second topic, **not** `subject_person`: the rule recognizes comma-form personal names, not family names. |
| 26 | `dcterms:subject` with `xsi:type="dcterms:LCSH"` | `Hula (Dance)` | `subject_topic` | Retained as the third topic. Final cell: `Family reunions; Palmer family; Hula (Dance)`. `subject_person` stays blank; `subject_organization` has no rule. |
| 27 | `dc:title` | `Hula Dancing at the Country Club, 1 of 3` | `title` | Preserved verbatim on the main row. Generated file-child titles instead use representation labels, falling back to filenames. |
| 28 | `dc:type` | `image` | `type` (fallback) | Not selected for this record because typed DCMI metadata supplies `Still Image`. If that typed value were absent, `image` would be used before file-type inference. |
| 29 | `dcterms:type` with `xsi:type="dcterms:DCMIType"` | `Still Image` | `type` | `Still Image` on the main row. Generated file-child types are inferred from their files instead. |

### XML attributes and repeated fields

- `xml:lang="eng"` is **not retained** as per-value language metadata. The CSV's `lanugage` value comes from the separate `dc:language` element.
- `xsi:type` **is retained in manifest keys** such as `dcterms:subject (dcterms:LCSH)` and `dcterms:type (dcterms:DCMIType)`, allowing the map to select typed fields. It is not exported as a separate CSV column.
- Namespace declarations identify source fields but are not CSV values. Alma-local fields such as `compoundrelationship` and `googlesheetsource` become unprefixed manifest keys.
- Repeated elements become de-duplicated, semicolon-separated manifest values; target rules then filter or combine them as shown above.

### Target values supplied outside this XML

| Target CSV column(s) | Source / behavior |
| --- | --- |
| `objectid` | A generated and persisted `<prefix>_dg_<n>` ID, not the legacy PID or MMS ID. |
| `parentid` | Blank on this bib's main row. Generated file-child rows use this bib's GEMS `objectid`, not `grinnell:11995`. |
| `display_template` | Inferred from file structure and type: one-file image, multi-file `compound_object`, or fileless `record`, for example. Not derived from `compoundrelationship`. |
| `original_file_name`, `filename` | Exported/renamed representation filenames. A multi-file parent borrows a child's filename with an initial `_`; a fileless row uses `_` plus its `objectid` for `original_file_name`. |
| `originating_system_id` | Alma's top-level `record.mms_id` on the main row; representation ID on generated file-child rows. |
| `format` | MIME type inferred from the exported filename on file-bearing rows, followed by any unqualified `dc:format` values. A multi-file parent or an XML-only/fileless record gets only the `dc:format` values. |
| `contributing_institution` | Constant `Grinnell College Libraries`, not `Cynthia Levy` or the publisher. |
| `title_alternative`, `creator_personal`, `creator_org`, `contributor_personal`, `contributor_org`, `medium`, `genre` | No matching source values in this XML. May be filled by configured legacy MODS fallbacks; otherwise blank. |
| `object_location`, `image_small`, `image_thumb` | Blank in GEMS; supplied downstream by DART. |

**Omission summary:** `compoundrelationship`, `googlesheetsource`, and typed `dcterms:format` are not mapped from this XML. `dc:type` is available as a fallback but is not selected here because the typed DCMI value wins. The `Digital Grinnell` collection value and Alma identifier URI are filtered out; the numeric identifier is preserved only through the separate top-level MMS ID. Per-element `xml:lang` attributes are lost. These omissions describe current behavior, not a recommendation to discard the values.
