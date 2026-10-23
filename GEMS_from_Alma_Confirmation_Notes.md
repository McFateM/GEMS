# GEMS from Alma: confirmation notes

## Verification performed October 23, 2026

Alma's live collection membership was queried for all 40 collections mapped in
[collections.tsv](./collections.tsv) and
[objectid-prefixes.tsv](./objectid-prefixes.tsv). Actual MMS IDs were compared
with the active GEMS manifests on dg-landing, rather than relying on record
counts or successful button 2 exports alone.

The findings are recorded in the **confirmed Alma coverage** column of
[GEMS_digital_collections.csv](./GEMS_digital_collections.csv). All 47 inventory
rows and the original six columns were preserved.

## Summary

| Finding | Collections |
|---|---:|
| Confirmed: exact live-to-manifest membership match | 36 |
| Partial: PHPP-DCL | 1 |
| Empty in Alma: Alumni 2020s | 1 |
| Unconfirmed: no active manifest for comparison | 2 |
| Not audited: inventory rows outside the Alma mapping | 7 |

For the 36 confirmed collections, the unique live MMS IDs exactly matched the
saved manifest membership, with no missing or extra IDs and no API skips.
For 35 of these collections, all manifest parent ObjectIDs also matched the
exported CSV's parent IDs, with no missing or extra parent IDs. Scarlet & Black
used an older basic CSV and was checked by MMS identifier instead, as described
below.

## Exceptions and follow-up

### PHPP Drake Community Library Archives (`phpp-dcl`)

- Alma reports **1,910 members**.
- Only **1,908 MMS IDs** can currently be retrieved.
- Those 1,908 IDs exactly match the active manifest, and all 1,908 manifest
  parent ObjectIDs match the exported CSV's parent IDs.
- Alma API HTTP 500 errors at **1-based collection positions 1,571 and 1,572**
  prevent confirmation of the remaining two members.
- There are no additional missing IDs among the retrievable members.

**Conclusion:** partial coverage; full Alma coverage is not confirmed. Resolve
the two API failures and reconcile those members before treating the collection
as complete.

### Alumni of the 2020's (`alumni-2020s`)

- Alma reports **zero members** and returns zero MMS IDs.
- No active GEMS manifest or export was found.

**Conclusion:** the missing manifest is consistent with an empty collection.
This does not prove that any historically populated collection was migrated.

### PHPP Community Contributions (`phpp-community`)

- Alma reports **1,443 members**.
- All 1,443 MMS IDs were enumerated without skips.
- No active GEMS manifest or export was found for comparison.

**Conclusion:** current GEMS coverage is unconfirmed. Existing inventory notes
about an earlier published migration were preserved, not independently checked.

### Grinnell Historical Museum (`phpp-ghm`)

- Alma reports **137 members**.
- All 137 MMS IDs were enumerated without skips.
- No active GEMS manifest or export was found for comparison.

**Conclusion:** current GEMS coverage is unconfirmed. Existing inventory notes
about an earlier published migration were preserved, not independently checked.

### Scarlet & Black Archives (`scarlet-black`)

- All **417 live MMS IDs** exactly match the saved manifest.
- All 417 MMS IDs also exactly match the `identifier` column in the older basic
  CSV export.
- A separate Grinnell-template test output exists.

**Conclusion:** Alma membership coverage is confirmed. Production
Grinnell-template readiness and media completeness remain separate checks.

### Seven inventory rows outside the Alma mapping

No mapped Alma collection PID was available for these rows, so their existing
migration or publication claims were not independently audited:

- `tdps`
- `georgia-dentel`
- `demo`
- `demo-seeklight`
- `parents-handbook`
- `cs-museum`
- `alden`

## Scope and limitations

These findings confirm **current API-visible direct collection membership**.
They do not establish:

- Coverage of nested subcollections.
- Historical membership or records no longer visible through the API.
- Downloaded media integrity or completeness.
- DART ingestion or publication in SHOW.
- Production readiness merely because a CSV or test export exists.

The overnight log separately recorded four batch scripts, 36 individual export
success lines, and the final message **All batches completed successfully**.
That establishes successful button 2 execution for those batches, not full Alma
coverage by itself. In particular, a successful export of PHPP-DCL's 1,908
retrievable records does not resolve its two inaccessible Alma members.
