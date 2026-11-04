# Johnson Controls operation coverage

This ledger reconciles GitHub's field-tested controller workspace and subsequent
reviewed native engineering profiles with older capability prose. It records
existing behavior; publishing it does not add another compiler, transfer method
or physical acceptance result. Help reads the same scoped capabilities and
requirement records from the public JSON files.

## Keep the operations separate

| Operation | Implemented scope | Evidence class | Remaining boundary |
| --- | --- | --- | --- |
| Identity, inventory, values and scan | Actual discovered BACnet objects through the supported direct/routed IP and direct serial read profiles | Authored wire/API/browser peers; historical site observations | A response window is not a complete inventory, and an old observation is not current reachability |
| Ordinary BACnet File copy | Bounded existing advertised stream/record files with source and byte evidence | Software protocol peers and retained captures | Opaque bytes are not an editable CAF, coherent application backup or allocation service |
| Offline CAF engineering | Observed containers, scalar edits, guarded existing wiring/connection and narrow terminal-binding edits into a separate copy | Authorized archive fixtures and preservation/readback checks | Creating arbitrary native blocks, complete application semantics and native hardware deployment remain incomplete |
| Native application capture | Qualified vendor-5 MCE backup operation captures application File 3 and saved-parameter Files 11/12, verifies identity and retains originals | Authored UDP peers and the documented private field capture | Backup changes controller backup state; it is separate from passive File copying and does not include firmware or every device setting |
| Standard Device instance write | One reviewed Device.object-identifier WriteProperty at the exact IPv4/routed station, with collision checks, ownership, readback and durable uncertainty | Authored direct/routed UDP, API and browser peers | Controller permission can reject the method; a retained denial stays blocked. This method does not transfer an application |
| Native application instance change | Independent typed edit of the existing generation-1 tagged-MOI root identities, fresh saved-parameter merge and one reviewed File-3 transfer/readback | Authored protocol/API/browser peers; documented private reference-compiler comparison; one documented physical instance-transfer acceptance | This is an edit of an existing captured application, not arbitrary CAF/MOI logic generation or acceptance of every model/firmware |
| Native controller-name change | Separate typed root Device-name edit with native encoding/framing, preserved instance and the same guarded application transfer | Authored compiler/protocol cases and preservation checks | The implementation does not establish a separate physical rename result or support unknown encodings |
| Actual native inspection | Qualified original MOI/MOZ records, signed Integer evidence, retained backup record exploration and operation-specific capability reports | Authored archives, seven private authorized CAF sources and their separately qualified comparison profiles | A readable record or CAF/native identity/File comparison does not establish complete semantics or destination package compatibility |
| One existing native Real or Boolean default | Separate typed archive copies, effective saved-setting compilers and guarded one-change File-3 transfer/readback | Authored direct/routed UDP, API and browser cases, including fresh settings, rejected/lost acknowledgment and restart recovery | Existing supported typed fields only; general parameter typing, signed packages, arbitrary logic and physical acceptance of these edits remain separate |
| One existing native wire source | A source tuple within the existing four-Unsigned-3118 wire width, observed ports/class/configuration, preserved destination/order/layout, cycle/order guards, fresh saved settings and one reviewed transfer/readback | Authored archive/UDP/API/browser cases and private offline source transformations | No block/port/wire allocation, changed execution order, general graph compilation or physical wire-edit acceptance |
| One matching native connection archive copy | A separately qualified local append between existing observed members/pins, matching endpoint configuration, unused input, order/cycle and known continuation framing, exact unrelated bytes and independent native readback | Authored raw/gzip frames, literal tuple/framing expectations, strict immutable API and Chromium/WebKit local/routed-context checks | No new blocks/I/O, saved-effective merge, field transfer, general compiler/resources, CCT reopening or physical acceptance; see [matching connection copies](native-matching-connection-copies.md) |
| One saved-effective matching native connection | Identity-qualified retained saved merge, original graph/continuation preservation, followed by the separate matching-connection append with exact other merged bytes and nested/outer proofs | Independent retained Real/Boolean and literal tuple/frame expectations, strict immutable local API and Chromium/WebKit basis/lifecycle/context checks | Captured effective values are not fresh live settings; no field transfer, arbitrary blocks/I/O, general compiler/resources or CCT/physical acceptance; see [saved-effective connections](native-effective-connection-compiler.md) |
| Hardware reassignment/new input | Surveys, archive correlation, capacity evidence, candidate electrical/voltage/relocation plans and narrow offline CAF engineering | Software/source evidence within each engineering profile | Native allocation/references, full compile/transfer for a hardware change, actual terminal suitability and the unused-input/open-circuit field test remain pending |
| Restore/recovery | Retained originals, durable uncertainty and explicit readback; separate [Real](native-real-default-recovery.md) and [Boolean recovery](native-boolean-default-recovery.md) derive local previous-effective-value proposals from verified receipts and require fresh confirmed transfers/full readback with current other settings | Authored direct/routed transfer, lost-acknowledgement, source/lineage guards, restart and browser cases | [Existing-wire-source recovery](native-wire-source-recovery.md) separately qualifies verified receipt/current-source proposals with current observed-pin and graph guards, then a new confirmed transfer. An original ZIP is not a general restore service. [Verified original-pin recovery](native-historical-wire-pin-recovery.md) additionally qualifies a missing current pin from original verified bytes and matching current source configuration. [Previous-name recovery](native-controller-name-recovery.md) has a separate same-instance source/proof contract, new confirmed transfer and full readback with fresh-setting preservation. [Previous-instance recovery](native-controller-instance-recovery.md) separately qualifies verified-after source bindings and projected destination settings, requires a new reservation/collision/transfer, and preserves name/fresh settings with full readback. Broader restore needs its own typed contract; no automatic inverse write/replay or physical acceptance is inferred |
| General application authoring/deployment | Portable graphs, simulation and qualified native/interchange subsets remain useful independently | Each adapter's declared software/reference evidence | Full JCI native logic compilation, signed packages/migrations, firmware conversion, commissioning/balancing and six qualified 2025 Title 24 CAFs remain incomplete |

The native family is selected by validated protocol/framing and actual standard
and native identity. Controller model names and expansion counts do not select
invented I/O inventories or replacement programs. Legacy PCV/VMA 1630/1615
compatibility continues to require exact application/release and hardware evidence.
Neither a successful model-independent parse nor one physical result proves the
entire model family.

## Native operation contracts

The connected adapter supports vendor 5's MCE envelope and generation-1 tagged
MOI, including qualified ordinary single-member gzip input. It uses direct or
explicitly routed plain BACnet/IPv4. Direct serial MS/TP and BBMD/foreign-device
application transfer remain outside that profile, even though other services
support those transports.

The application path runs independently of a CCT/PCT process, vendor SDK or
Windows VM. It still needs the controller family's private backup/transfer
credentials and a supported native source. General future operations may need
additional independent schemas, compiler oracles or a licensed vendor toolchain;
that is an operation-specific dependency, not a blanket gate on the existing
identity/name path.

Before applying, the existing service captures a fresh source, merges saved
parameters under the supported storage contract, checks application capacity,
source/identity/route/interface, review expiry and required confirmations. It
transfers only File 3. Verified outcomes require operational status, the reviewed
identity/name and the application/parameter preservation checks. Runtime outputs
permitted by the preservation policy remain explicitly recorded; this does not
guarantee every equipment behavior or supervisory relationship.

Reviews last 900 seconds, the operation deadline is 1,800 seconds, and individual
File requests retain their four-second, single-dispatch bounds. These are the
existing constants, not new settings introduced by this ledger. An unresolved
dispatched attempt blocks another application/instance attempt until explicit
reconciliation; it never gains an automatic retry or assumed rollback.

Native application verification calls the backup capture path to compare the
application and saved parameters. Current captures and verification evidence
report `read_only: false` and carry the versioned backup-effects declaration:
start-backup and end-backup state commands can be sent, but verification never
reapplies the reviewed application. The declaration describes possible services,
not a dispatch log; an early preflight refusal can send no state command. Older
sealed evidence retains its original bytes, including its historical flag.
Treat native verification separately from passive identity/property reads.

Contracts and implementation:
[native transfer](native-application-transfer.md),
[name commissioning](controller-name-commissioning.md),
[settings preservation](native-settings-preservation.md),
[parameter storage](native-parameter-storage.md),
[native service](../backend/bms_tool/native_applications.py),
[typed MOI edits](../backend/bms_tool/moi_identity.py) and
[saved-parameter merge](../backend/bms_tool/moi_parameters.py),
[Real-default transfer](native-default-transfer.md),
[Boolean-default transfer](native-boolean-default-transfer.md),
[existing-wire transfer](native-wire-source-transfer.md),
[actual MOZ reading](moz-application-reading.md),
[retained records](native-backup-record-inspection.md) and
[backup operation support](native-backup-operation-capabilities.md).

## Evidence, dates and register status

Implemented means the stated software profile exists and has its stated checks.
It does not make every transport/model physically accepted. Keep code/API,
authored protocol peer, native/reference comparison and physical equipment
evidence distinct. The transfer contract documents one physically acknowledged
instance change with operational status and expanded-application readback.
Name-only code does not imply another physical rename test.

The [2026-10-20 validation record](VALIDATION.md) retains its original test counts,
VM inventory and read-only site observations. Its statements about then-missing
native services and then-pending publication are historical. They must not
override later implemented operations or be relabelled as a current full-suite
run. No fresh site access or vendor-binary analysis is claimed here.

The broad `FMT-002`, `FMT-003`, `OPS-001` and `RES-001` criteria remain partial;
`IO-001`, `PKG-001`, `PKG-002`, commissioning and code-compliance criteria retain
their actual remaining work. Separate native capture/instance/name rows credit
their existing supported scope without marking those broader requirements done.
Direct serial survey/archive acquisition is also credited without treating it
as BTCVT or serial native application transfer. See
[serial surveys](jci-direct-serial-survey.md),
[native targets](NATIVE_TARGETS.md) and the [roadmap](../ROADMAP.md).

The original #118 reconciliation recorded 105 existing MOI
identity/name/parameter and native application/API passes against its own source.
That is a scoped historical run, not a regression total for the later integrated
stack. The metadata
API served the reconciled register and the native status reported its existing
limits with field interfaces closed. These are scoped software checks; no new
site result, current full-suite pass or physical acceptance is inferred.
