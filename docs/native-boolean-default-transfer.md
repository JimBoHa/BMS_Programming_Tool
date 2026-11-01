# Native Boolean default controller transfer

[Previous effective Boolean-default recovery](native-boolean-default-recovery.md)
adds an offline receipt-derived proposal and a separately confirmed new transfer.
It preserves this operation's fresh-setting, one-use and full-readback guards.

The effective Boolean editor now has a separate connected **Controller transfer**
workflow for one existing class 530/531 Boolean Default Value (3113). It reuses
the authoritative workspace controller and exact direct or explicit routed
BACnet/IPv4 station. The local archive/effective compilers remain separate.

1. Open and verify the intended controller. In Program's native backup workflow,
   configure the shared native backup/restore credentials and read a current
   native backup. Capture enters and ends backup mode; it is not a passive File read.
2. Inspect the actual Boolean record, choose **Merge retained saved settings**,
   open its saved defaults and select a different effective Boolean value.
3. Choose **Review controller default transfer** in the Boolean transfer section.
   Check the exact controller, reference, previous/proposed values and preservation
   policy. Confirm both the selected change and application interruption.
4. **Apply native default to controller** performs one native application restore.
   Keep the receipt. A verified result requires complete native and effective
   saved-setting readback plus operational status; it does not establish physical
   control performance.

The profile is `native-effective-boolean-default-transfer/1`, with change kind
`boolean-default`. Real-default and instance/name plans keep their existing
contracts. Plans are one-use, have the existing 15-minute lifetime and are bound
to original capture/manifest/archive/property evidence, exact route/interface,
identity and credential digest. Strict JSON Booleans are required. Cross-kind
Apply routes and unknown profiles are refused.

Apply captures fresh Files 3/11/12 before restoring anything. Original application
and saved selector directory must match. The selected effective Boolean and its
encoding must still match the reviewed prior value. Other fresh saved values,
including other Boolean and numeric settings, are merged into the final payload.
The actual controller-reported application capacity is checked. Original backup,
compiled payload and readable durable intent precede the first restore request.
Only File 3 is written. Existing transport, overall-operation, preparation and
individual request limits remain unchanged; no retry or fallback is added.

Readback requires the exact expected expanded application bytes and preserved
Device instance/name/model. It merges the observed saved values, checks the
selected Boolean with its actual type/value, and permits only the existing known
runtime-output exceptions for other saved settings. An old saved value overriding
the new archive default, changed other settings, CRC errors or changed native
records prevent verification even when restore was acknowledged.

After any possible restore dispatch, uncertainty remains pending in the durable
journal. **Read back native default transfer** reconciles that exact receipt after
reload/restart without another restore. No automatic retry, rollback or assumed
inverse write occurs. `not_sent` means no restore dispatch; preflight may already
have read the controller and entered/ended backup mode. Cancellation after restore
start retains an uncertain receipt even if no File block was sent.

The shared web workflow binds plans/receipts to their explicit operation kind and
station, retains exact review/receipt downloads and requires both confirmations.
During native operations, controller/source/record/mode/draft navigation is locked
while Stop remains available. Independent busy owners prevent a stale completion
from unlocking another operation. A Real operation retires a Boolean review and
vice versa, while their local drafts remain separate. Target/interface/source or
proposal changes also retire pending reviews before paint.

Token-admitted endpoints are `POST
/api/bacnet/controller/native-application/boolean-default/transfer/preview` and
`POST /apply`. They share native capture, credentials, cancellation, receipt/backup
exports and readback endpoints. The native-backup matrix advances to profile 4,
with a fifteenth, separately preflighted Boolean transfer operation. Reading or
compiling a source never creates a transfer review implicitly.

Qualification uses authored direct/routed UDP peers and literal saved Boolean
bytes, including fresh other-setting preservation, capacity/source/credential/
expiry checks, complete readback, retained saved overrides, journal faults,
cancellation, single-use/cross-kind admission and restart recovery without replay.
Both browser engines exercise actual capture/review/restore/readback, source and
navigation locks, altered-review cancellation and exact receipt bytes. A test
fixture initially omitted Real signal selection in a cross-profile scenario; the
original failures remain retained and the explicit selection was corrected.
No site, Bluetooth, general graph, new I/O allocation or physical acceptance is
claimed. JCI-03/JCI-09 and broader native engineering remain partial overall.
