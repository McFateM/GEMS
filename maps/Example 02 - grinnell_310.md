The following metadata source record for `grinnell:310` (MMS ID `991011578728404641`) dumped from Alma maps to CollectionBuilder as you see here.

```xml
<record xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns="http://alma.exlibrisgroup.com/dc/01GCL_INST" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dc="http://purl.org/dc/elements/1.1/">
  <oldalttitle xml:lang="eng">Autobiographical reminiscences of an active career from 1850 to 1890</oldalttitle>
  <googlesheetsource xml:lang="eng">0124  https://docs.google.com/spreadsheets/d/1JzW8TGU8qJlBAlyoMyDS1mkLTGoaLrsCzVtwQo-4JlU/edit?usp=sharing</googlesheetsource>
  <dginfo xml:lang="eng">{/"worksheet/": /"https://docs.google.com/spreadsheets/d/1JzW8TGU8qJlBAlyoMyDS1mkLTGoaLrsCzVtwQo-4JlU#gid=1001438104/", /"directory/": /"smb://storage/mediadb/DGingest/Migration-to-Alma/exports/college-history/", /"object/": {/"pid/": /"grinnell:310/", /"title/": /"Men and Events of Forty Years/", /"files/": [/"grinnell_310_MODS.xml/", /"grinnell_310_RELS-EXT.rdf/"]}}</dginfo>
  <dcterms:abstract xml:lang="eng">Autobiography of Josiah Bushnell Grinnell for the years from 1850-1890.</dcterms:abstract>
  <dcterms:alternative xml:lang="eng">Autobiographical reminiscences of an active career from 1850 to 1889</dcterms:alternative>
  <dc:contributor xml:lang="eng">Parker, Henry W. (Henry Webster), 1822-1903</dc:contributor>
  <dcterms:created xml:lang="eng">1891</dcterms:created>
  <dc:creator xml:lang="eng">Grinnell, Josiah Bushnell, 1821-1891</dc:creator>
  <dcterms:extent xml:lang="eng">466 pages</dcterms:extent>
  <dc:format xml:lang="eng">Digitized Other Analog</dc:format>
  <dc:identifier xml:lang="eng">grinnell:310</dc:identifier>
  <dc:identifier xml:lang="eng">grinnell:310</dc:identifier>
  <dc:identifier xml:lang="eng">http://hdl.handle.net/11084/310</dc:identifier>
  <dc:identifier>alma:01GCL_INST/bibs/991011578728404641</dc:identifier>
  <dcterms:isPartOf xml:lang="eng">Early College History</dcterms:isPartOf>
  <dcterms:isPartOf xml:lang="eng">Digital Grinnell</dcterms:isPartOf>
  <dc:language xml:lang="eng">English</dc:language>
  <dcterms:publisher xml:lang="eng">Boston: D. Lothrop Company</dcterms:publisher>
  <dc:rights xml:lang="eng">&lt;a href="https://rightsstatements.org/page/NoC-US/1.0/?language=en" target="_blank">Public Domain in the United States&lt;/a></dc:rights>
  <dcterms:spatial xml:lang="eng">Grinnell (Iowa)</dcterms:spatial>
  <dcterms:spatial xml:lang="eng">United States</dcterms:spatial>
  <dcterms:spatial xml:lang="eng">Iowa</dcterms:spatial>
  <dc:subject xml:lang="eng">Autobiographical reminiscences of an active career from 1850 to 1890</dc:subject>
  <dc:subject xml:lang="eng">J.B. Grinnell</dc:subject>
  <dc:subject xml:lang="eng">Death</dc:subject>
  <dc:subject xml:lang="eng">Life</dc:subject>
  <dc:subject xml:lang="eng">Grinnell Founding</dc:subject>
  <dc:subject xml:lang="eng">Grinnell history</dc:subject>
  <dc:subject xml:lang="eng">Merit</dc:subject>
  <dc:subject xml:lang="eng">Public service</dc:subject>
  <dcterms:subject xsi:type="dcterms:LCSH" xml:lang="eng">Grinnell, Josiah Bushnell, 1821-1891</dcterms:subject>
  <dcterms:subject xsi:type="dcterms:LCSH" xml:lang="eng">History</dcterms:subject>
  <dcterms:subject xsi:type="dcterms:LCSH" xml:lang="eng">Politics and government</dcterms:subject>
  <dcterms:subject xsi:type="dcterms:LCSH" xml:lang="eng">Grinnell College</dcterms:subject>
  <dcterms:temporal xml:lang="eng">1850</dcterms:temporal>
  <dcterms:temporal xml:lang="eng">1890</dcterms:temporal>
  <dcterms:temporal xml:lang="eng">1849-1877</dcterms:temporal>
  <dc:title xml:lang="eng">Men and Events of Forty Years</dc:title>
  <dc:type xml:lang="eng">book</dc:type>
  <dcterms:type xsi:type="dcterms:DCMIType" xml:lang="eng">Text</dcterms:type>
</record>
```

The audit below was generated with:

```bash
python -m gems.mapping_audit record.xml --mms-id 991011578728404641
```

## Alma XML to GEMS CSV mapping audit

This table evaluates the current template rules for the main row of one Alma bib.
Repeated fields are combined as GEMS combines them; each XML occurrence is listed separately.
No representation files, generated IDs, or legacy MODS are supplied. File-derived values
and MODS fallbacks cannot be determined from this XML alone. An optional MMS ID supplies
`record.mms_id`; it is not inferred from XML identifiers.

| # | XML field | Source value | Target CSV column(s) | Result / omission |
| --- | --- | --- | --- | --- |
| 1 | oldalttitle | Autobiographical reminiscences of an active career from 1850 to 1890 | None | Omitted: no target column rule reads this XML field. |
| 2 | googlesheetsource | 0124  https://docs.google.com/spreadsheets/d/1JzW8TGU8qJlBAlyoMyDS1mkLTGoaLrsCzVtwQo-4JlU/edit?usp=sharing | None | Omitted: no target column rule reads this XML field. |
| 3 | dginfo | {/"worksheet/": /"https://docs.google.com/spreadsheets/d/1JzW8TGU8qJlBAlyoMyDS1mkLTGoaLrsCzVtwQo-4JlU#gid=1001438104/", /"directory/": /"smb://storage/mediadb/DGingest/Migration-to-Alma/exports/college-history/", /"object/": {/"pid/": /"grinnell:310/", /"title/": /"Men and Events of Forty Years/", /"files/": [/"grinnell_310_MODS.xml/", /"grinnell_310_RELS-EXT.rdf/"]}} | None | Omitted: no target column rule reads this XML field. |
| 4 | dcterms:abstract | Autobiography of Josiah Bushnell Grinnell for the years from 1850-1890. | description | description: Autobiography of Josiah Bushnell Grinnell for the years from 1850-1890. |
| 5 | dcterms:alternative | Autobiographical reminiscences of an active career from 1850 to 1889 | title_alternative | title_alternative: Autobiographical reminiscences of an active career from 1850 to 1889 |
| 6 | dc:contributor | Parker, Henry W. (Henry Webster), 1822-1903 | contributor_personal | contributor_personal: Parker, Henry W. (Henry Webster), 1822-1903 contributor_org: omitted by filtering or empty source value. |
| 7 | dcterms:created | 1891 | date | date: 1891 |
| 8 | dc:creator | Grinnell, Josiah Bushnell, 1821-1891 | creator_personal | creator_personal: Grinnell, Josiah Bushnell, 1821-1891 creator_org: omitted by filtering or empty source value. |
| 9 | dcterms:extent | 466 pages | extent | extent: 466 pages |
| 10 | dc:format | Digitized Other Analog | format | format: Digitized Other Analog |
| 11 | dc:identifier | grinnell:310 | identifier | identifier: grinnell:310 item_permalink: omitted by filtering or empty source value. |
| 12 | dc:identifier | grinnell:310 | identifier | identifier: grinnell:310 item_permalink: omitted by filtering or empty source value. |
| 13 | dc:identifier | http://hdl.handle.net/11084/310 | item_permalink | identifier: omitted by filtering or empty source value. item_permalink: http://hdl.handle.net/11084/310 |
| 14 | dc:identifier | alma:01GCL_INST/bibs/991011578728404641 | None | identifier: omitted by filtering or empty source value. item_permalink: omitted by filtering or empty source value. |
| 15 | dcterms:isPartOf | Early College History | digital_collection_title | digital_collection_title: Early College History |
| 16 | dcterms:isPartOf | Digital Grinnell | None | digital_collection_title: omitted by filtering or empty source value. |
| 17 | dc:language | English | lanugage | lanugage: English |
| 18 | dcterms:publisher | Boston: D. Lothrop Company | publisher | publisher: Boston: D. Lothrop Company |
| 19 | dc:rights | &lt;a href="https://rightsstatements.org/page/NoC-US/1.0/?language=en" target="_blank"&gt;Public Domain in the United States&lt;/a&gt; | rights; standardized_rights | rights: Public Domain in the United States standardized_rights: http://rightsstatements.org/vocab/NoC-US/1.0/ |
| 20 | dcterms:spatial | Grinnell (Iowa) | location | location: Grinnell (Iowa); United States; Iowa |
| 21 | dcterms:spatial | United States | location | location: Grinnell (Iowa); United States; Iowa |
| 22 | dcterms:spatial | Iowa | location | location: Grinnell (Iowa); United States; Iowa |
| 23 | dc:subject | Autobiographical reminiscences of an active career from 1850 to 1890 | keywords | keywords: Autobiographical reminiscences of an active career from 1850 to 1890; J.B. Grinnell; Death; Life; Grinnell Founding; Grinnell history; Merit; Public service |
| 24 | dc:subject | J.B. Grinnell | keywords | keywords: Autobiographical reminiscences of an active career from 1850 to 1890; J.B. Grinnell; Death; Life; Grinnell Founding; Grinnell history; Merit; Public service |
| 25 | dc:subject | Death | keywords | keywords: Autobiographical reminiscences of an active career from 1850 to 1890; J.B. Grinnell; Death; Life; Grinnell Founding; Grinnell history; Merit; Public service |
| 26 | dc:subject | Life | keywords | keywords: Autobiographical reminiscences of an active career from 1850 to 1890; J.B. Grinnell; Death; Life; Grinnell Founding; Grinnell history; Merit; Public service |
| 27 | dc:subject | Grinnell Founding | keywords | keywords: Autobiographical reminiscences of an active career from 1850 to 1890; J.B. Grinnell; Death; Life; Grinnell Founding; Grinnell history; Merit; Public service |
| 28 | dc:subject | Grinnell history | keywords | keywords: Autobiographical reminiscences of an active career from 1850 to 1890; J.B. Grinnell; Death; Life; Grinnell Founding; Grinnell history; Merit; Public service |
| 29 | dc:subject | Merit | keywords | keywords: Autobiographical reminiscences of an active career from 1850 to 1890; J.B. Grinnell; Death; Life; Grinnell Founding; Grinnell history; Merit; Public service |
| 30 | dc:subject | Public service | keywords | keywords: Autobiographical reminiscences of an active career from 1850 to 1890; J.B. Grinnell; Death; Life; Grinnell Founding; Grinnell history; Merit; Public service |
| 31 | dcterms:subject (dcterms:LCSH) | Grinnell, Josiah Bushnell, 1821-1891 | subject_person | subject_topic: omitted by filtering or empty source value. subject_person: Grinnell, Josiah Bushnell, 1821-1891 |
| 32 | dcterms:subject (dcterms:LCSH) | History | subject_topic | subject_topic: History; Politics and government; Grinnell College subject_person: omitted by filtering or empty source value. |
| 33 | dcterms:subject (dcterms:LCSH) | Politics and government | subject_topic | subject_topic: History; Politics and government; Grinnell College subject_person: omitted by filtering or empty source value. |
| 34 | dcterms:subject (dcterms:LCSH) | Grinnell College | subject_topic | subject_topic: History; Politics and government; Grinnell College subject_person: omitted by filtering or empty source value. |
| 35 | dcterms:temporal | 1850 | time_period | time_period: 1850; 1890; 1849-1877 |
| 36 | dcterms:temporal | 1890 | time_period | time_period: 1850; 1890; 1849-1877 |
| 37 | dcterms:temporal | 1849-1877 | time_period | time_period: 1850; 1890; 1849-1877 |
| 38 | dc:title | Men and Events of Forty Years | title | title: Men and Events of Forty Years |
| 39 | dc:type | book | None | type: omitted because a constant or earlier source takes precedence. |
| 40 | dcterms:type (dcterms:DCMIType) | Text | type | type: Text |

### Attribute and row-structure notes

- Per-element `xml:lang` attributes are not retained by GEMS.
- `xsi:type` is retained in manifest field keys, not as a separate CSV column.
- Namespace declarations identify fields; they are not CSV values.
- Repeated values are de-duplicated and joined with `; `.
- Generated file-child rows use each rule's `child` override or remain blank when none exists.
- The default map does not read `compoundrelationship`: separate Alma bibs are not joined
  into the legacy compound by that field. CSV compounds are generated from a bib's files.

### Target columns without an XML-derived value

| Target CSV column | Current value / other source |
| --- | --- |
| objectid | Blank for this input. Rule sources: gems.objectid. |
| parentid | Blank for this input. Rule sources: gems.parentid. |
| display_template | Blank for this input. Rule sources: gems.display_template. |
| original_file_name | Blank for this input. Rule sources: gems.filename. |
| originating_system_id | Value: 991011578728404641 (constant or supplied non-XML source). |
| object_location | Blank: no rule. |
| image_small | Blank: no rule. |
| image_thumb | Blank: no rule. |
| image_alt_text | Blank: no rule. |
| thumb_focus | Blank: no rule. |
| creator_org | Blank for this input. Rule sources: metadata.dc:creator; metadata.dcterms:creator; mods.creator_corporate. |
| interviewee | Blank: no rule. |
| interviewer | Blank: no rule. |
| subject_organization | Blank: no rule. |
| contributor_org | Blank for this input. Rule sources: metadata.dc:contributor; metadata.dcterms:contributor; mods.contributor_corporate. |
| latitude | Blank: no rule. |
| longitude | Blank: no rule. |
| source | Blank: no rule. |
| provenance | Blank for this input. Rule sources: metadata.dcterms:provenance. |
| call_number | Blank: no rule. |
| archival_series | Blank: no rule. |
| box | Blank: no rule. |
| folder_title | Blank: no rule. |
| folder_number | Blank: no rule. |
| finding_aid_permalink | Blank: no rule. |
| contributing_institution | Value: Grinnell College Libraries (constant or supplied non-XML source). |
| medium | Blank for this input. Rule sources: metadata.dcterms:medium; mods.form. |
| genre | Blank for this input. Rule sources: mods.genre. |
| digital_collection_permalink | Blank: no rule. |
| related | Blank for this input. Rule sources: metadata.dcterms:relation; metadata.dc:relation. |
| avian_identifier | Blank: no rule. |
| filename | Blank for this input. Rule sources: gems.filenames. |
| disclaimer | Blank: no rule. |

**Omission summary:** `oldalttitle`, `googlesheetsource`, and `dginfo` are not mapped. `dc:type` (`book`) is not selected because the typed DCMI value `Text` wins. The duplicate `grinnell:310` identifier is collapsed to one value, and the `Digital Grinnell` collection value and Alma identifier URI are filtered out (the MMS ID is retained in `originating_system_id`). The `format` cell is prefixed by the inferred MIME type only if the bib has a representation file; with no file it is just `Digitized Other Analog`. Per-element `xml:lang` attributes are lost.
