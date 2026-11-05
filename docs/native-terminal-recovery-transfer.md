# A fresh parent-bound analog terminal recovery transfer

`COMM-NATIVE-TERMINAL-RECOVERY-001` adds a separate strict review endpoint,
`POST /api/bacnet/controller/native-application/input/terminal-recovery/preview`.
It accepts the usual exact target, current capture/snapshot, operation ID and
terminal edit, plus required `recovery_parent_receipt` and
`recovery_origin_sha256`. The edit must equal the proposal from the
[local previous-terminal draft](native-terminal-recovery-drafts.md).
Contextual web controls remain subsequent work; this scope qualifies the API
and transfer backend.

## Review and single-attempt transfer

The service independently prepares the original parent/current evidence again.
The exact source/target, origin hash, typed inverse edit, analog object/reference,
current terminal and previous destination must agree. Allocation/mode/removal
actions cannot use this endpoint. Rejected local origin checks send no field
read or command. A valid request enters the existing input review, including
current published input configuration and controller identity checks.

The review retains operation profile `native-local-universal-input-transfer/2`
and adds the explicit `native-analog-terminal-recovery-transfer/1` lineage marker,
parent receipt, sealed origin and `terminal_recovery_lineage_enforced: true`.
The typed review options must retain those bindings; missing or demoted lineage
refuses. Ordinary input reviews keep their original shapes and authority.

Apply uses the existing `/input/apply` endpoint and all three typed physical
wiring, input-change and application-transfer confirmations. The existing
one-use token, complete review seal, interface/credentials/expiry/capacity,
fresh source and published configuration checks still apply. After fresh saved
settings are acquired and compiled, the service revalidates the parent/current
origin before creating the new intent or dispatching the program. Other newer
saved values remain current. The durable new intent retains the exact lineage;
the parent and original result remain immutable.

Full image/settings/published input readback remains mandatory. Unknown outcomes
retain their lineage and use the existing explicit readback/reconciliation path
without another download. Applying can restart control; capture/verification can
enter native backup state. This is a newly reviewed inverse terminal transfer,
not an old-token replay or a general controller restore.

## Preservation and qualification

Ordinary input review delegates its unchanged behavior to the same shared review
body. With no recovery options, the added derivation returns no metadata. All
older input actions, profile-2 terminal moves, other native transfer families,
readback, existing recovery helpers and UI remain separately preserved.

Software qualification uses actual owned direct/routed UDP transfers. Tests
preserve an unrelated saved value changed after review, require every
confirmation, verify whole-image/published readback, reject parent proof changed
before intent, retain uncertain outcomes, reconcile without replay and consume
the one-use plan. Independent local tests cover typed parent/origin/target/edit
bindings and missing/demoted metadata. HTTP dispatch checks validate only the
new session/schema boundary; protocol peers independently qualify real transfer.

No live-site, VM or Bluetooth test is part of this scope. Physical rewiring and
controller/CCT acceptance, broader binary/SA/cross-host reassignment, native
resources/packages and general rollback remain separate. JCI-10/IO-02 remain
partial overall.
