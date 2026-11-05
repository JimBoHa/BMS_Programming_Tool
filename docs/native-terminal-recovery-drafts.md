# Prepare a previous analog terminal draft

`FMT-NATIVE-TERMINAL-RECOVERY-DRAFT-001` adds the local
`POST /api/bacnet/controller/native-application/input/terminal-recovery/prepare`
endpoint. Its strict request contains only `receipt_id`, `capture_id` and
`snapshot_sha256`. The existing session token remains required. This first scope
supplies a source-bound draft API; contextual controls and separately enforced
parent lineage in a new field transfer remain subsequent work.

## Required evidence

The parent must be a resolved, confirmed native input terminal transfer under
`native-local-universal-input-transfer/2`. It must retain possible dispatch and
an immutable verified result or verified historical readback, with operational
status, matching native image and complete input preservation. Later observations
do not rewrite the original result. Pending, unknown without verification,
not-dispatched, allocation/mode/profile-1 or contradictory receipts refuse.

Preparation reloads the original hash-checked backup and reconstructs its typed
terminal compilation. Exact full compilation and compressed/expanded payload
hashes, controller name/instance, identity and route must match the parent intent.
The current retained source independently qualifies its identity and saved merge.
Its identity, route and static directory remain exact. Its native application
must equal the recorded forward image or the original saved-merged previous
image; unrelated engineering changes refuse.

The same analog object/reference must retain the recorded current terminal and
selected electrical/scaling configuration. A change only in a saved selected
configuration value also refuses, even if raw File 3 is unchanged. Other current
saved settings remain current. The existing profile-2 compiler rechecks the old
terminal's availability and creates a discarded inverse image, retaining all of
its input/output namespace, property-width, graph and framing requirements.

## Returned draft and limits

`native-analog-terminal-recovery-draft/1` returns the exact current source,
immutable parent/original/current bindings, verified proof, previous/after/current
slots, a sealed origin, complete inverse compilation and output fingerprint.
`proposal` contains the current source and an ordinary typed terminal edit. If
the previous merged image is already recorded, proposal/compilation/output are
null and `new_review_required` is false. A sealed response never grants Apply.

Preparation reads local files and journal evidence. It makes no controller query,
backup-state command, file export, intent, field review, receipt update or retry.
It does not verify physical rewiring, send an inverse program or replay an old
plan. `parent_lineage_enforced_by_field_transfer` is explicitly false: an ordinary
input transfer still has its existing independent review/confirmation authority.
This draft is not yet an enforced recovery transfer or a whole-controller restore.

Software checks use independent literal image expectations, current unrelated
saved-value changes, framing/compression/Slot-width variants, already-previous
state, typed receipt/configuration/hash faults, session/schema guards and an
owned UDP transfer/capture that produces the parent evidence. Controller and
intent access are replaced with failing sentinels in the local HTTP check.
Existing compilers, field transfer/readback, recovery helpers, journal formats,
interface and graphics remain unchanged. No live-site, VM or Bluetooth operation
is part of this qualification. JCI-10 and IO-02 remain partial overall.
