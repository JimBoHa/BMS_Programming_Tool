# Native existing-wire source controller transfer

Connect and verify the intended controller. In **Program → Native backup
defaults**, configure the existing native backup/restore credentials and **Read
current native backup**. Inspect the retained backup, open an actual activity or
control-sequence record, select **Saved effective snapshot**, and **Open saved
wire sources**. Choose an existing connection and a different eligible source.

Its **Controller transfer** section provides **Review controller wire transfer**.
The review identifies the exact station, connection, original/proposed source,
retained snapshot and fresh-setting policy. Both the wire-change confirmation
and controller-interruption confirmation are required before **Apply native wire
to controller**. Saving a local compiled file remains a separate operation.

This is `native-effective-wire-source-transfer/1`, a closed operation for an
existing source index, using the shared native application adapter. It does not
allocate or scan for a Device instance, add an object/connection, reassign I/O or
claim general native compilation. Support is per actual source/operation/transport,
not a model-selected controller inventory.

## Review and fresh transfer

The captured controller route, interface configuration, Device identity, vendor,
source root and original/effective archive/diagram/property hashes must agree.
The existing [effective wire compiler](native-effective-wire-compiler.md) supplies
the actual tuple, candidate, observed pin, class/configuration, execution-order,
cycle and original-width checks. A no-op proposal cannot prepare a transfer.

Immediately before restore, the adapter captures fresh Files 3/11/12. The original
application and static saved directory must still match review. It merges fresh
saved values and compares a configuration signature of the selected diagram,
old source, new source and destination. Existing recognized Real/Boolean default
values may refresh; other opaque configuration, classes and datatypes must stay
unchanged. Changing both sources together cannot bypass this guard by leaving
them compatible with each other. The fresh payload can therefore differ from the
preview while retaining the same reviewed wire intent.

Actual application capacity, credentials, interface ownership and plan expiry are
checked again. Before the first restore request, the original fresh backup,
compiled payload and one-use intent reach durable storage. Only application File
3 is written, using one start-restore/write/end-restore attempt. Capture and
verification use start/end-backup commands; restore can interrupt control. The
existing request/operation/review budgets and no-retry behavior are retained.

## Verification and recovery

Protocol acknowledgement alone is insufficient. Verification checks unchanged
Device identity, operational status, every expanded byte of the expected native
application, all post-restore saved application values under the existing narrow
runtime exceptions, and the selected effective connection. Other fresh settings
and unknown native records remain preserved. Unmatched non-application slots stay
in the original backup and are never invented in the program.

A lost acknowledgement, cancellation after dispatch, changed saved value, invalid
CRC or differing native bytes retains an unresolved receipt. **Read back native
wire transfer** reconciles it, including after an application restart, without
another restore. The operator can reopen the specific retained receipt and export
its original JSON. An unresolved native transfer blocks a further engineering
change. No automatic replay, inverse write or rollback occurs.

The web workflow retains the source and wire draft while locking source, record,
mode and navigation controls during a field operation. **Stop native operation**
remains available. Changing another target/proposal retires the old review before
paint. Reviews and receipts are checked against the operation, tuple, source,
configuration and preservation evidence; an altered reply cannot claim successful
verification. Historical receipts retain their own station and are independent
of the currently selected draft.

The token-admitted routes are:

- `POST /api/bacnet/controller/native-application/wire-source/transfer/preview`
- `POST /api/bacnet/controller/native-application/wire-source/transfer/apply`

Apply accepts only its one-use token, review hash, operation ID and two strict
Boolean confirmations. Instance/name/Real/Boolean/wire plans cannot cross their
operation/profile boundaries. Existing native capture, credentials, cancel,
receipt and readback endpoints remain shared. Native-backup capability profile 7
adds the eighteenth operation as a separate transfer preflight, without preparing
a field change from offline analysis.

Software checks use independently authored graph and saved bytes, actual native
UDP exchanges over direct and explicit routed paths, fresh numeric/Boolean values,
selected configuration changes, source/capacity/credential/expiry refusals,
durability before restore, strict confirmations, complete preservation, lost
acknowledgements, restart and malformed recovery evidence. Chromium/WebKit cover
field ownership, source/navigation locks, altered evidence, retained drafts and
recovery. Existing Real/Boolean transfer and archive/effective compiler workflows
are checked separately.

No site controller or Bluetooth adapter is used for this qualification. CCT/PCT
reopening, native execution/sequence behavior, release/packages/resources,
hardware allocation, full-program authoring and physical control acceptance
remain separate. JCI-03 and JCI-09 remain partial overall.
