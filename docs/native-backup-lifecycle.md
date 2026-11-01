# Retain and archive native backups

Open **History → Native backups** from an open controller or local application.
Search the active or archived list by source identity, Device, route, capture ID
or time. Select a row to inspect its original source evidence, download the
original backup ZIP, archive it locally or restore it to the active list.
Neither a field connection nor a recognized compiler schema is required.

**Archive local backup** frees one active catalog slot. It retains the entire
original capture directory at the same private path, including the manifest,
original Files 3/11/12 and any reviewed payload. No original bytes, timestamps,
capture IDs, hashes, transfer intents, results or readback events are rewritten.
Existing capture references remain readable after restart, including those used
by pending transfers and previous-value, wire, name and instance recovery.

**Restore to active backups** makes a retained capture selectable again in the
ordinary source pickers. It is a local catalog action, never a controller restore.
It does not reconnect, enter controller backup/restore state, replay a transfer,
create a field review, supply allocation authority or bypass source qualification.
A source already open in a local draft remains retained when it is archived.

## Retention and concurrency

The existing **128 active capture** limit remains. There are at most **1,024
archived captures**; archiving does not free disk space. At either capacity, the
operation refuses explicitly without pruning, deleting or overwriting another
source. Restoring at the active limit requires archiving another capture first.
The original ZIP export contains the original manifest and three backup files;
it is not a portable copy of the whole transfer journal or an import/restore path.

Catalog transitions are private SQLite records, sealed with SHA-256, appended
with monotonically increasing per-capture revisions and committed with FULL
synchronous durability. Archive/restore alternation is checked. A stale or reused
revision, including archive/restore/archive ABA, must be refreshed before another
action. Each capture permits 1,024 transitions; the final permitted transition
restores it to active storage. These integrity seals are local evidence, not
manufacturer authentication.

Capture publication, lifecycle changes and bounded catalog snapshots serialize
through SQLite transactions, including across separate application processes.
This prevents two captures or a capture and restore from consuming the final
active slot simultaneously. The UI refuses lifecycle changes during a native
operation in the same application instance. Across processes, catalog changes
cannot move or remove files that an operation has opened or referenced.

Before a transition, all three original files and the manifest must pass the
existing snapshot integrity checks. Symlinked native storage/capture folders,
redirected leaf files and nonregular evidence files are refused. List rows are
historical manifest metadata: their original file hashes and sizes are not live
controller measurements. The list does not load every payload; integrity is
rechecked when changing catalog state, exporting or using the source.

## API and interface ownership

The token-admitted local endpoints are:

- `POST /api/bacnet/controller/native-application/backup-library/list`: active or
  archived state, search up to 256 characters, offset up to 1,024 and pages of at
  most 64 sources. The UI requests 32. Counts distinguish active and archived
  captures; empty search results are not a statement about unqueried controllers.
- `POST /api/bacnet/controller/native-application/backup-library/change`: exact
  capture ID, original snapshot manifest SHA-256, expected catalog revision and
  explicit `archive` or `restore` action. Extra field targets, paths, delete,
  upload and replay instructions are rejected.

Both use `native-backup-lifecycle/1`, `controller_queries: false` and
`field_actions: false`. Original snapshot/source APIs retain their schemas;
ordinary source lists contain active captures, while explicit IDs keep resolving
their immutable originals. Navigation or document visibility changes retire
pending UI replies and selections. No stale response can attach an action to a
different source. Refresh obtains actual catalog state after a lost response.

## Software acceptance and remaining scope

Isolated tests exercise both original readers and exact recovery proposals after
all their sources are archived; original paths, bytes, file permissions, ZIP
contents and receipts survive restart. Actual authored direct and routed UDP
cases apply a newly reviewed instance recovery from archived original,
verified-after and current sources, then preserve an uncertain transfer and read
it back after archiving its pending backup and restarting, without replay.
Concurrent final-slot tests, exact active/archive limits, stale revisions,
substituted files, symlinks, FIFO evidence and strict local HTTP are covered.

Chromium/WebKit workflows cover both local entry paths, real pagination/search,
archive/restore/export, stale and substituted replies, navigation/visibility,
compact layouts and connected catalogs that issue no controller requests.
These are software tests with authored sources and loopback peers. Physical
controller, Bluetooth, whole-state portability, general backup import/restore,
additional native logic and manufacturer compatibility retain separate gates.
