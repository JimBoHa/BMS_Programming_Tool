# Parent-bound configured analog recovery transfer

`FMT-NATIVE-ENCODED-ANALOG-RECOVERY-TRANSFER-001` adds explicit field review at
`/api/bacnet/controller/native-application/input/encoded-terminal/recovery/preview`.
It consumes the derived previous-terminal proposal from local preparation and
uses the existing profile-4 writer. Ordinary input and legacy recovery requests
keep their existing contracts.

A separate strict request carries the parent receipt and sealed recovery origin
under an encoded-analog namespace. Only the exact derived encoded-terminal action
is admitted. Local preparation is recomputed before field review. Proposal,
selected object/reference/configuration guard, typed configuration/field presence,
source target and terminal pair must agree with the current compilation. Invalid
origin evidence is refused before field reads.

All recovery lineage fields are included in the reviewed body. Apply refuses
missing, altered or downgraded lineage even if the body is resealed, then recomputes
the parent origin again immediately before creating a durable intent. An invalidated
parent cannot dispatch a new application or create a child intent. Separate key
names prevent accidental admission through the earlier analog recovery contract.

The existing current-interface/target/identity, capture/static-directory, fresh
saved-setting merge, capacity and configuration guards remain required. All three
wiring, unchanged input configuration and application-transfer confirmations still
apply. Each review is single-use. The child receipt retains the exact parent/origin;
complete native preservation and independently published input readback establish
verification. Uncertain outcomes reconcile through existing readback without
another transfer. Other current saved values remain current.

This delivery adds backend field binding. Contextual web preparation/staging and
recorded recovery-lineage presentation remain next. It does not automatically
restore a backup, infer wiring or add general compilation, allocation/electrical
changes, SA/cross-host movement, packages/resources or physical/CCT/BTCVT
acceptance. IO-02/JCI-10 remain partial.

Verification covers strict origin/schema/compilation admission and owned direct/
routed UDP transfers, current saved-value preservation, all confirmations, child
lineage, replay refusal, unknown reconciliation, parent revalidation and resealed
missing-lineage plans rejected before field work. Earlier transfer/recovery
families remain in regression coverage. No live-site controller is modified.
