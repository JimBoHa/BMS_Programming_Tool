# Reanalyze a saved hardware archive

`IO-SAVED-HARDWARE-REANALYSIS-001` adds **Reanalyze saved archive** inside the
existing Points & I/O hardware task's archive details. It works disconnected,
uses the exact selected saved source and creates a separate local evidence record.
The original metadata and original file remain unchanged and available to export.
The current controller, graph/CAF and historical report remain separate; reanalysis
does not silently correlate a report or verify current physical wiring.

The request binds the archive identifier and expected source SHA-256. The backend
validates the stored metadata wrapper, requires a bounded regular source file,
rejects symlinks or an inode/size replacement during open, and verifies both the
recorded byte count and source digest before analysis. It runs the current parser
against those actual bytes, rather than trusting earlier cached host/capacity
claims. The child records the parent identifier, source digest, complete parent
evidence digest and preserved original provenance. It grants no current identity,
network-query, controller-write or native compilation authority.

Existing archive-count/storage limits and atomic import cleanup still apply. A
missing, altered or unavailable original source is an error; a metadata-only record
cannot become freshly analyzed evidence. Failed reanalysis leaves the parent
unchanged and creates no partial child. Reanalysis is explicit and does not run
on list/open, background refresh or application startup.

The browser independently admits the child identity, unchanged source and closed
lineage before replacing its selection. It keeps matching admitted evidence visible
while the saved copy reloads, preserving the open details and download controls.
The child option and selection update together before library refresh, so a slow
refresh cannot leave the selected archive blank.
It retires old local relocation/sensor reviews. Target/task/lifecycle invalidation
prevents delayed results from restoring retired work; an already-created child
stays in the saved library without being silently selected in another task.

Checks cover earlier cached false-local claims corrected from source bytes,
parent/source preservation across restart, malformed requests, missing/modified/
symlinked/replaced/oversized files, retention and storage failures, strict browser
admission, exact source downloads, graph/CAF entry at both widths, inconsistent
responses and delayed task retirement. All mutation tests use isolated local state.
No site, VM or Bluetooth operation is required or claimed.

Next: further typed Device Reference and host-specific reassignment semantics.
Reanalysis cannot manufacture missing host bindings. General native compilation,
SA/cross-host writes, resources/packages and physical acceptance remain separate.
