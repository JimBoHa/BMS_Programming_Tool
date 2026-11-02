# Inspect original native backup storage

Open **History → Native backups → Check backup storage** from an open controller
or local application. Choose **Inspect backup storage** to read the stored entries
on this computer. The diagnostics remain available when a damaged manifest prevents
the ordinary active/archived catalog from opening. Opening the disclosure itself
does not start an inspection or a field connection.

The table distinguishes a readable original manifest, an unavailable/malformed
manifest, and an unrecognized entry name. It includes capture folders that have
original files but no published manifest. Those incomplete folders are retained
evidence, not usable backups. Search matches stored entry names or capture IDs;
the ordinary catalog separately searches captured controller identities and routes.

Selecting a readable source exposes **Check original backup files**. This explicit
read compares original Files 3, 11 and 12 with the exact stored manifest's sizes
and SHA-256 values. Results distinguish matching bytes, mismatches and unavailable
files. A missing file does not hide a mismatch in another file. Oversized,
redirected and nonregular files remain unavailable; they are not followed or
interpreted as valid payloads.

**Export integrity report** saves the observed source, exact manifest byte hash,
original snapshot evidence hash, expected/observed sizes and hashes, problems,
observation time, scope and report seal. It does not export replacement payloads
or create a recovery or transfer plan. These local SHA-256 seals detect changed
evidence; they do not authenticate a manufacturer or prove program compatibility.

## Preservation and bounds

Diagnostics do not repair, delete, rename, reseal, archive, restore or republish
anything. They leave original files, modes, catalog transitions, pending transfers,
receipts, recovery references and active/archive quotas unchanged. The ordinary
catalog and existing source consumers retain their original failure checks.
A diagnostic result does not make damaged evidence eligible for compilation.

Each inspection observes at most **1,152 entries** at the native storage root,
including unrecognized entries. If more exist, the response and UI explicitly
report an incomplete scan. Search and counts then describe only the observed
portion; another page is not a promise to reach entries beyond that bound.
Names are sorted within the observed portion. A directory that changes between
pages may produce a different observed set; this is not a locked catalog snapshot.

Only the displayed page's original manifests are read, at most **32 per API
request** and **128 KiB each**. The UI requests 16. Inventory never reads payloads
or the contents of unrecognized entries. An explicit file check reads three
original files with their existing **2 MiB per-file** limit. The original manifest
must match the selected exact byte hash before the check and remain byte-for-byte
unchanged afterward. Native safe-file and retained-directory guards are reused.

Files are read sequentially. Even three matching observations are **not an atomic
snapshot**, proof of a complete controller backup, current controller state,
native application validity, or controller restore acceptance. Retain damaged
originals for investigation; this view provides no destructive cleanup action.

## API and response ownership

Both endpoints require the existing local session token and strict request bodies:

- `POST /api/bacnet/controller/native-application/backup-library/storage-inventory`:
  optional `query` (256 characters), `offset` (0–1,152) and `limit` (1–32).
- `POST /api/bacnet/controller/native-application/backup-library/check-originals`:
  exact lowercase 32-character `capture_id` and original manifest byte
  `manifest_sha256`. Paths, field targets, Apply, deletion and repair requests
  are not accepted.

Responses use `native-backup-integrity/1` and declare `read_only: true`,
`controller_queries: false`, `field_actions: false` and `storage_mutations: false`.
The snapshot evidence hash remains distinct from the exact serialized manifest
hash. A changed manifest requires another explicit inspection and selection.

The browser binds each result to its selected capture and both manifest hashes.
Changing source, leaving the task, closing the disclosure, visibility changes
and source A→B→A retire pending results. An old result cannot enable an export for
a different source. These are read-only observations; they carry no field review,
reservation, transfer authority, retry or automatic reconnection.

## Software qualification

Authored sources cover valid and damaged manifests, unknown and unpublished
entries, exact preserved bytes/modes, independent missing/mismatched files,
size bounds, native file guards, before/during-check manifest substitution,
bounded pagination/search, strict token-admitted HTTP and zero controller effects.
Chromium/WebKit workflows cover both local entry paths, compact layouts, exact
report export and delayed/substituted source responses. Physical controllers,
Bluetooth, whole-state migration and general native authoring remain separate.
