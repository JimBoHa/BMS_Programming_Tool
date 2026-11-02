# Import original native backup ZIPs

Open **History → Native backups → Import native backup ZIP** from a controller
or local application. Choose an original Studio native backup ZIP. This makes
its immutable original files available on this computer without opening a field
interface or selecting the historical controller. Existing list/search filters
still apply. Imported rows identify themselves as historical copies; Details
retain the first filename, import time and archive/manifest hashes.

The importer requires exactly `manifest.json`, `file-3.bin`, `file-11.bin` and
`file-12.bin`. It validates strict UTF-8 JSON, the original manifest profile and
seal, source metadata, all three original file lengths and SHA-256 values, entry
types and compression before publishing any capture. Paths, extra/duplicate
members, encryption, symlinks, unsupported compression and malformed or truncated
members refuse. It does not extract archive-selected paths or interpret unknown
native application/saved-parameter schemas.

## Original evidence and local state

Original capture ID, sealed metadata and all three binary files remain intact.
The imported manifest's exact incoming bytes are retained. Publication uses the
existing private regular-file writes and flushes, a private capture directory,
and a complete manifest published last. A separate sealed `local-import.json`
records provenance without modifying the original manifest. These local hashes
detect changed evidence; they do not authenticate a manufacturer or operator.
Ordinary ZIP export still contains exactly the manifest and three original
binary files, using the existing manifest JSON serialization. It excludes local
provenance and transfer state.

An identical complete capture is reported as already present without replacing
files or changing its active/archived state. A locally acquired capture is never
relabeled as imported merely because the same ZIP is presented. Conflicting IDs
refuse and retain existing evidence. A damaged provenance sidecar is shown as
unavailable in the catalog while original capture evidence remains inspectable;
reimport will not silently repair that sidecar.

Publication failure retains private incomplete evidence for **Check backup
storage**. Repeating the exact ZIP may finish only an importer-owned partial
capture whose original sidecar and every present file still match. Unknown
entries, changed bytes or unrelated incomplete folders require storage inspection;
the importer does not delete, repair or replace them. A lost UI reply can leave
a completed local capture; refresh and inspect the catalog before retrying.

## Bounds, ownership and authority

Limits remain **8 MiB per ZIP**, **128 KiB per manifest**, **2 MiB per original
file**, and a filename of at most **1,024 UTF-16 units**. The existing **128
active / 1,024 archived** capture limits stay unchanged. Publication serializes
with capture/lifecycle operations through the existing SQLite transaction. A
full active catalog refuses new captures; an identical existing capture needs
no additional slot. No existing capture is evicted or implicitly archived.

The session-token-admitted multipart endpoint is
`POST /api/bacnet/controller/native-application/backup-library/import`, with the
file in `file`. Its separate `native-backup-import/1` response declares
`controller_queries: false`, `field_actions: false` and
`authority_restored: false`. Exactly one of `created`, `resumed` or
`already_present` is true. The browser checks the incoming ZIP's own SHA-256,
capture/snapshot/file bindings, provenance and outcome. Navigation, document
visibility, page hiding and catalog-context changes retire pending display
replies; they do not roll back an already completed local import.

Imported identity and route describe the original acquisition. They do not prove
a responding device, present configuration, compatible compilation or physical
acceptance. No receipt, pending transfer, credential, collision reservation,
review, confirmation or prepared recovery is restored. Later edits/transfers
retain their separate fresh source/identity/configuration, typed review,
one-use intent and complete readback requirements. This is original-file
portability, not whole-state migration or a general controller restore.

## Software qualification

Authored archives exercise exact original-file roundtrip/restart, idempotence,
conflicting metadata, interrupted/resumed publication, malformed archives,
concurrent import, full active capacity, archived state, private permissions and
token-admitted HTTP with no field interface. Existing catalog, integrity and
record readers are regression checked. Chromium/WebKit exercise actual browser
multipart import, both entry paths, exports, repeats, failed files, filtered
catalogs, stale/substituted replies, phone layout and zero import traffic to real
authored direct/routed UDP peers. Held/substituted reply tests explicitly use a
controlled known-file HTTP import to qualify response ownership separately from
the ordinary browser multipart tests. Physical devices and Bluetooth remain
separately qualified.
