# Offline native backup record inspection

In **Program → Native backup defaults**, select a retained native backup and use
**Inspect retained native backup**. **Browse captured native records** reads the
original File 3 archive without opening an interface, entering backup mode or
creating an application-change review. The archive source, original route, Device,
capture time, manifest hash and File 3 hash remain visible.

This view is independent of the effective-default compiler. A readable archive
can still be inspected when the retained acquisition reported an identity mismatch
or its saved-parameter schema is not understood. The original identity error is
shown; inspection does not override it or qualify compilation/transfer. A source
integrity failure still blocks inspection: all three retained File 3/11/12 hashes
are checked against the original manifest, even though the view reads File 3.

Values come from the original archive. They are not saved-setting-merged values,
current live measurements or proof of the currently running application. The
separate default table/compiler retains its own archive/effective distinction.
No missing value, record, controller model or hardware inventory is invented.

The shared record explorer retains its bounded search/paging, original order,
typed values, metadata records, unknown encoding evidence, offsets and hashes.
Native backup requests bind both capture ID and manifest hash; response checks
also bind the File 3 hash and original station. Published-File requests retain
their existing controller/interface ownership contract. Source/target/interface
or view changes retire pending results before paint, including A→B→A selection.
Local compiler text remains independent and survives inspection/navigation.

Token-admitted endpoints under
`/api/bacnet/controller/native-application/inspection` are `POST /source`,
`POST /records` and `POST /record`. They use only immutable local backup storage.
They do not use BACnet, a compiler or the native transfer service. Their
`read_only: true`, `controller_queries: false` and `field_actions: false` describe
this inspection; the backup's original acquisition may have entered/ended backup
mode. The original manifest is not rewritten.

Qualification uses original versus merged values, opaque saved-schema and
unverified-identity sources, strict page/identifier bounds, altered files/seals,
source redirection, HTTP token admission and response ownership. An authored
native UDP backup is acquired, disconnected, then fully inspected with zero
additional requests. Browser checks cover local drafts, original values,
unverified sources, altered responses and late property replies. No site or
Bluetooth acceptance is inferred.
