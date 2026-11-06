# Parent-bound configured binary recovery transfer

`FMT-NATIVE-BINARY-TERMINAL-RECOVERY-TRANSFER-001` adds explicit field review at
`/api/bacnet/controller/native-application/input/binary-terminal/recovery/preview`.
It consumes the previous-terminal proposal from local binary recovery preparation
and uses the existing profile-3 writer. Ordinary input and earlier recovery
requests keep their existing contracts.

A separate strict request carries the original receipt and sealed recovery origin
under a binary-terminal namespace. Only the exact derived binary-terminal action
is admitted. Preparation is recomputed before field review. The proposal, selected
object/reference, non-counter configuration guard, source target and terminal pair
must agree with the current compilation. Invalid origin evidence is refused before
field reads.

The reviewed body retains all binary recovery lineage fields. Apply rejects missing,
altered or downgraded lineage, then revalidates the parent before durable intent and
application dispatch. Recovery namespaces cannot substitute for one another.
The child receipt retains the exact original receipt and origin.

Current interface, route, identity, source/static-directory, capacity and selected
configuration guards remain required. All three physical-wiring, unchanged-input
configuration and application-transfer confirmations still apply. Current saved
counter values may advance after the proposal or review; the fresh compiler retains
them without treating counter equality as electrical configuration. Other current
saved values remain current. Raw native application changes remain outside the
qualified recovery profile.

Each review is single-use. Complete native preservation and independently published
binary configuration readback establish verification. Uncertain outcomes retain
evidence and reconcile through existing readback without another transfer.

This delivery adds backend transfer binding. Contextual preparation/staging in
Points & I/O and recorded lineage in Changes/History remain next. It does not add
automatic rollback, wiring inference, allocation/electrical changes, dedicated
binary-terminal or SA/cross-host moves, general compilation/restore, resources or
packages. Physical/CCT/BTCVT acceptance remains separate. IO-02/JCI-10 remain partial.

Verification uses strict schema/origin/compilation admission and owned direct and
routed UDP peers. Cases cover current saved values and counters, original lineage
in the child, all confirmations, replay refusal, uncertain outcomes followed by
readback, and parent/source invalidation before dispatch. Re-sealed plans with
removed or mixed recovery metadata cannot regain authority. Earlier input and
recovery families remain in regression coverage. No site controller is used.
