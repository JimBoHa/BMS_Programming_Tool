# BMS Studio development roadmap

Updated: 2026-11-02. Implementation baseline: GitHub `main` at
[`b89ea258`](https://github.com/JimBoHa/BMS_Programming_Tool/commit/b89ea25866e3793faaec749dc5561e488bb92b44).

## Baseline and purpose

GitHub is the authoritative implementation baseline, including its newer field
work and controller-centered interface. Future work starts from current `main`,
preserves its graphics and behavior, and adds one reviewed feature or small
coherent group per PR. The older Mac checkout is a source of ideas and historical
evidence, not a replacement implementation to merge wholesale.

This roadmap supersedes the older local roadmap based on `6af07d9`. It captures
the planned work, its order, dependencies, interface placement and acceptance
conditions. It does not change application behavior or claim that planned work
is implemented. Items are ordered within each group by usefulness for configuring,
testing, deploying and verifying controllers. Johnson Controls FX/Metasys comes
first; other manufacturers follow after independent JCI work or blocked work has
been addressed.

The public requirement register currently records 185 scoped criteria: 131
implemented, 46 partial and eight pending. Those 54 partial/pending rows are
cross-referenced in [the roadmap backlog](docs/roadmap-backlog.csv), together with
additional preserved ideas and workspace gaps. These counts describe the existing
register, not the entire current feature set: some older gap text predates native
commissioning. The backlog preserves those original statements and adds current
scope qualifications rather than silently granting or removing support.

The separate local manual inventory contains 2,343 entries. Many are unassessed,
overlap reusable primitives, or describe already implemented subsets. They are
an evidence inventory, not 2,343 missing features. Reassess before adding work.

## Keep the current interface contract

Implementation progress: **UX-01 has a verified first IPv4 slice** under
[UI-MONITOR-CTX-001](docs/controller-monitoring-context.md): selected-controller
field recording and single-log history now retain the complete target and
captured interface, discovered objects and original saved evidence. Selected
serial field recording and single-log history now have a separately qualified
software profile. Physical bus/BTCVT and other profiles remain under PORT-01. The
following work packages retain their remaining scope; this does not mark the
broader monitoring/transport roadmap complete.

[AGENTS.md](AGENTS.md) and the [workflow style guide](docs/workflow-style-guide.md)
remain the design authority. The deliberate changes in `32d0887`, `dff2273`,
`20eff81`, `847b5b4` and `f43fe8d` are part of the baseline to preserve.

- Start with **Connect to a controller** or **Open a CAF file**. A known address
  can skip discovery; offline editing and saving never require a connection.
- Keep the selected controller, exact interface/router/network/station/Device
  identity, verification age, current file and source visible. An open interface
  and a responding verified controller are different states.
- Add functions within **Overview**, **Points & I/O**, **Program**, **Schedules**,
  **Trends & Alarms**, or **Changes**. Keep reusable assets in **Library**,
  cross-session records in **History**, configuration in **Settings** and research
  in **Help**. Do not restore feature tiles or add a destination per feature.
- Retain explicit **Edit**, **Simulate** and **Commission** modes. Connected
  views acquire the selected controller's actual data; a local CAF or sample graph
  must never silently populate a live view.
- Reuse the authoritative target instead of asking for its address again. Target
  changes retire pending results and write reviews, preserve local drafts and
  leave uncertain operations attached to their original station.
- Discover inventory and capabilities across protocol/format families. A model
  name or expansion count must not select a fabricated point list or substitute
  application. Documented capacities are supplementary compatibility evidence.
- Use focused views, searchable engineering tables, progressive disclosure and
  one visually primary action. Put raw protocol details and hashes in Details.
- Preserve teal accents, neutral surfaces, clear borders, 8/16/24 pixel spacing,
  readable 14–16 pixel body text, aligned numbers, explicit units, visible focus
  and labelled controls. Status colors require text; offline remains neutral.
- Use precise action labels such as **Open controller**, **Save CAF copy**,
  **Review change**, **Apply to controller**, **Read back** and **Release override**.
  Saving a local file does not imply a controller write.
- Field changes follow **Edit → Review → Apply → Verify**. A common Changes view
  is not an atomic batch. Preserve source checks, one-use reviews, transaction
  limits, ownership and durable recovery.

State mapping declarations and standard instance proposals now have
[workspace draft continuity](docs/workspace-draft-continuity.md). Navigation
retains unreviewed work and imported provenance while retiring reviews and
allocation confirmations. Instance text stays with its exact route/interface;
verified Apply or explicit readback clears only its matching completed proposal.
This is in-memory workspace retention, not durable draft storage across reloads.

## Existing capabilities to preserve and credit

[IP route-change qualification](docs/ip-route-change-qualification.md) now
exercises the genuine guided workflow against two authored routed controllers
with the same Device instance. It preserves the bind and verifies each selected
route. A suspected extra-field product error was traced to inaccurate simulated
status; those fixtures now follow the real IP contract. Production connection
and strict server-admission code remain unchanged.

[Unfinished exception import](docs/unfinished-exception-import.md) now restores
source-bound raw exception text after reload. Strict file/source/buffer checks,
explicit replacement refusal and existing no-eviction workspace limits preserve
partial numeric/time/String/date work without creating native or field authority.
File provenance stays separate from reviewed encoding proof. Separately qualified
[numeric/String weekly recovery](docs/unfinished-weekly-recovery.md) and
[Calendar text recovery](docs/unfinished-calendar-recovery.md) now preserve their
own exact source-bound raw buffers after reload. They retain existing workspace
limits, require explicit discard before replacement and never restore review or
field authority. [Native identity text recovery](docs/unfinished-identity-recovery.md)
now restores name/instance proposals for the same interface configuration and
exact route/Device/edit kind, verifies locally retained original backups and
keeps receipt/recovery references unverified. It restores no plan, confirmation
or field authority. All four recovery families retain separate native admission
and physical acceptance requirements.

[Native review cancellation](docs/native-review-cancellation.md) now retires owned
completed Calendar and numeric/String weekly reviews, including weekly workspace
lifecycle changes. Invalid returned previews also retire their owned server
review. Valid Apply, active-write uncertainty, unrelated reviews and immutable
historical receipts retain their existing contracts. The original profile/rule
seals and journal formats stay unchanged.

[Matching weekday assistance](docs/calendar-weekday-assistance.md) now supplies an
explicit civil-date action in shared Calendar and exception controls. It changes
only the selected weekday for a complete valid date, preserves wildcard/unfinished
text, and uses the existing edit/review retirement path. It queries no clock or
field interface and changes no native profile or deployment authority.

[Native Schedule exception deployment](docs/native-schedule-exception-deployment.md)
now adds fresh selected-controller review, one whole-array write attempt, exact
static context/Calendar identity/revision checks, an independent durable journal
and separate explicit read-only reconciliation. The local exception editor keeps
unfinished work through lifecycle changes and late receipts. This is simulated
plain IPv4 direct/routed software qualification; physical acceptance, Calendar
contents/evaluation and context/link editing remain pending under SCH-01–SCH-03.

[Native Schedule exceptions](docs/native-schedule-exceptions.md) retain their
separate local source/review/exact export/import profile. Typed periods, values,
priorities, order and modern captured week patterns retain native proof and
source-specific unfinished buffers. This local profile queries no references and
issues no field authority; deployment uses the independent profile above.
Existing weekly/String and Calendar rules and writers stay separate.

[Calendar range admission](docs/native-calendar-date-ranges.md) now distinguishes
fully specified or wholly unspecified DateRange endpoints from broader Date
patterns before new field review and request encoding. Invalid new ranges create
no field reads or write authority. Original sources, local exports, no-change
observation and historical receipt readback remain useful without granting a new
write. This does not complete general context/link editing or schedule evaluation.

[Native identity draft capacity](docs/native-identity-draft-capacity.md) now
retains unfinished name/instance contexts without evicting earlier work. Empty
views and passive receipts use no slot; a full 32-context cache refuses new work
until explicit discard. Retained-source inspection and raw-text JSON export do
not change the selected controller or grant field authority. Original backups
and journals stay independent; durable draft storage/import remains separate.

[Weekly workspace continuity](docs/native-weekly-workspace-continuity.md)
now retains exact unfinished numeric/time/String rows and imported provenance by
capture, Schedule and day through task and surface navigation. Bounded buffers
refuse replacement at capacity; explicit discard frees only the selected day.
Restoring local work never restores a field review. Reload persistence remains
an explicit export/import workflow; this does not complete wider scheduling.

[Omitted-field datatype qualification](docs/native-omitted-field-qualification.md)
now guards fields newly materialized by native transfers. Unknown or mismatched
application types retain their original snapshots and block transfer review.
[Backup failure diagnostics](docs/native-backup-failures.md) retain both a failed
File read and unconfirmed cleanup without retrying either operation.
[Legacy actuator state verification](docs/native-legacy-actuator-state.md)
separates one version-scoped changing saved counter from fixed configuration and
shows both values in existing receipts. Exact application bytes and all other
preservation checks remain required. These scopes do not establish arbitrary
native generation or physical acceptance.

[Original native recovery readback](docs/native-original-recovery-readback.md)
now distinguishes complete original-image/settings recovery from applying the
proposed change. Fresh identity, operational status, full image/settings and
published point-name checks precede lock release. Failed intent/results remain
immutable with appended proof; readback does not send a recovery application.
The [additional qualification](docs/native-original-recovery-qualification.md)
also preserves newer local captures and proposals during older receipt readback.
Broader restore orchestration and physical acceptance remain separate.

[Schedule deployment selection](docs/native-schedule-controller-selection.md)
now binds preview, Apply and receipt readback to the exact controller and route
shown in the workspace. Foreign captures remain useful for local review/export,
and original receipt evidence remains available offline. Target transitions
retire authority without changing the weekly/String wire services. The separate
weekly workspace continuity now retains unfinished buffers across navigation;
export remains necessary before reloading or restarting the application.

[Live flow calibration readback](docs/native-runtime-calibration.md) separately
reports one qualified calculated output from each discovered native Flow
Primitive. Stored-image/settings verification does not imply live calibration
equality. Missing/unavailable values and the read budget remain explicit; no
calibration command or old-value write is introduced. This does not complete
physical calibration, actuator tests or general runtime verification.

[Native point-name editing](docs/native-point-names.md) now belongs to the
selected point's Configuration within Points & I/O. It preserves the existing
point identifier, logic references, I/O setup and other merged settings, and
requires both full native readback and the published BACnet name to agree.
Bounded drafts refuse eviction; exact review/operation/receipt ownership and
uncertainty recovery remain explicit. This does not allocate points, move
terminals, rename supervisor objects or complete general native authoring.
The separate [recorded point-name ledger](docs/native-point-name-ledger.md) now
shows attributable before/after metadata in Changes and History without querying
live names or reopening backups. Its tool link retains the current controller
and requires the user to choose a point for any fresh operation.

[Previous point-name recovery](docs/native-point-name-recovery.md) now derives a
local proposal from verified original receipt/backup evidence and an exact current
point source. The web workflow preserves ordinary name text separately, stages
the previous name explicitly, and requires a new confirmed transfer and complete
readback with durable origin binding. JCI-10 remains partial overall; general
application rollback remains separate. The [recorded point-name recovery
lineage](docs/native-point-name-recovery-ledger.md) now separately projects known
origin/child bindings and local parent-ID search in Changes/History without
revalidating originals, parents or field state.

Native parameter preservation now handles qualified repeated unsaved runtime
slots, restores typed saved properties omitted from existing application records,
and resolves only exact declared logical root references across assigned Device
instances. Binary event timestamp slots now retain their validated original epoch
as runtime evidence instead of synthesizing an integer application default;
other saved settings still merge and read back independently. See the
[timestamp qualification](docs/native-runtime-timestamp-qualification.md).
Already-present unqualified date/time encodings and wider runtime schemas need
their own preservation evidence. [Post-restore readiness](docs/native-restore-readiness.md) performs
bounded identity/status reads after a validated commit ACK before full native
verification, without repeating the transfer. Preserve these contracts and their
[additional UDP and recovery regression checks](docs/native-transfer-regression-validation.md).
This extends the existing preservation scope; it does not complete arbitrary
logic/hardware generation, broader restore, other transports or physical acceptance.

[Native Calendar date drafts](docs/native-calendar-drafts.md) add a separate
source-qualified local Date_List editor for captured Date, DateRange and WeekNDay
entries. Exact original/native bytes, stateless reviewed JSON export/import and
source-specific unfinished workspace buffers are retained without field traffic.
Newer week patterns explicitly retain their protocol-revision requirement.
This is the first Calendar authoring slice of SCH-01. A separate
[Date_List transfer backend](docs/native-calendar-write.md) now adds fresh exact
source/target checks, actual protocol-revision qualification, one-use dispatch,
durable intent/results and independent readback/reconciliation. It preserves the
local-only draft boundary and all older weekly authorities. The
[Calendar deployment interface](docs/native-calendar-controller-deployment.md)
now integrates that API into the selected-controller Calendar editor with
explicit fresh review, one-use Apply, immutable receipts, interrupted-intent
recovery and separate read-only reconciliation. Target, source, interface,
navigation and visibility transitions retire field authority while preserving
local dates and original evidence. Special-event/context/link editing, timezone
evaluation and physical acceptance remain separate; SCH-01–SCH-03 stay partial.

[Schedule inventory continuation](docs/schedule-inventory-continuation.md)
retains a verified controller's last completed Object_List offset after a
deadline or cancellation. Preparing the next page changes the form only;
another explicit read is required. Previously discovered objects with unread
fields still require separate explicit selection. This does not complete SCH-01
or imply a coherent controller backup.

[Read-only native backup integrity diagnostics](docs/native-backup-integrity.md)
now expose damaged/unpublished storage entries independently of the ordinary
catalog and check selected original file sizes/hashes. They retain all originals,
quotas, receipts and source eligibility checks. A local hash match is not program
validation, an atomic snapshot or controller restore acceptance.

| Existing scope | Baseline to retain | Remaining boundary |
| --- | --- | --- |
| Controller workspace | Two entry paths, router/trunk explorer, verified opening, authoritative target, persistent CAF context, explicit local/live source selection | Finish older views' target integration and responsive drawers; do not redo the workspace |
| Actual controller data | Discovered inventories, live values/quality, application metadata, native tagged-MOI diagrams and separate live block reads | General native diagram editing and full logic generation remain separate |
| Native JCI identity commissioning | Vendor-5 MCE/tagged-MOI backup, typed instance compilation and connected application transfer/readback; separate name-only editing | This is a narrow verified operation family, not arbitrary CAF/MOI logic compilation or unrestricted application replacement |
| Preservation and recovery | Original application/Static/Dynamic captures, fresh parameter merge, exact application and parameter preservation checks, one-use reviews, durable uncertain receipts | Extend each new edit type with its own typed contract and recovery proof |
| Routed operation budgets | Existing 1,800-second overall native operation budget, 900-second review lifetime, four-second individual File limits and one dispatch | Measure future profiles; do not add hidden retransmission or widen limits to hide failures |
| Hardware and offline CAF work | Saved surveys, archive correlation, candidate spare-input/voltage/relocation plans, guarded existing CAF terminal edits and direct MS/TP software integration | Physical wiring, electrical suitability, broader allocation and native hardware deployment remain distinct |
| Portable programming | Graph editing, simulation, reusable activities, equipment foundations, conformance tests and qualified native/interchange subsets | Full manufacturer sequences, proprietary semantics and physical acceptance remain incomplete |

The native transfer documentation records one physically acknowledged and
verified application transfer, with operational status and exact expanded
application readback. Preserve that positive evidence without generalizing it to
every controller. Name-only commissioning has its own implementation and
preservation contract; do not infer a separate physical rename result merely
from merged code. The user's field-tested baseline is preferred, while exact
coverage continues to be recorded per operation and target.

Relevant current contracts:
[workspace](docs/controller-workspace.md),
[device-driven architecture](docs/device-workspace-architecture.md),
[native transfer](docs/native-application-transfer.md),
[settings preservation](docs/native-settings-preservation.md),
[controller names](docs/controller-name-commissioning.md),
[parameter storage](docs/native-parameter-storage.md) and
[read-only batch observation](docs/batch-controller-observation.md).

## Preserve the older local ideas without restoring older code

All 31 affected files in the original Mac checkout were privately copied and
hashed before this planning work. The original checkout remains unchanged. Do
not publish local state, credentials, source controller archives, site results,
vendor binaries or downloaded manuals as roadmap fixtures.

| Idea/source | Treatment going forward | Placement / planned work |
| --- | --- | --- |
| Hardware survey, saved evidence, archive/live correlation, spare-input and voltage/relocation planning | Already present in newer forms; retain their evidence and extend specific gaps | Points & I/O; IO-01–IO-04 |
| Guarded offline CAF terminal changes and draft protection | Already implemented in a narrow profile; preserve source/preview guards and separate-copy meaning | Program / CAF hardware; Changes; JCI-04 and IO-02 |
| Router handoff and pausing old observations after an interface change | Preserve intent in the newer continuous workflow; do not restore ambiguous “Use” controls or the old monolithic Connect view | Router/trunk explorer; UX-01 and QA-02 |
| `inventory_feature_review.py`, `ocr_feature_review.swift`, `build_feature_review.py`, `prioritize_feature_review.py` | Port useful tooling after removing dated directories and absolute machine links; retain citations, hashes, OCR confidence, ranking and formula escaping | Parameterized developer tools and Help; REF-01–REF-03 |
| Dated native-research and workflow-coverage notes | Preserve useful distinctions and evidence leads; rewrite current operation coverage instead of copying obsolete “no native Apply” or “no serial survey” claims | Help and versioned capability evidence; BASE-01 and REF-03 |
| Browser → production HTTP → independent real loopback BACnet peer → changed sensor on a later survey | Retain missing end-to-end assertions with random identity and proof of zero writes; adapt selectors to current workspace | Existing browser/acquisition suites; QA-02 |
| Nondefault router ports, route propagation, reopen/pause and no implicit discovery on selection | Extend existing workflow/scan tests only where coverage is absent; avoid duplicate test harnesses | Existing connection/workspace suites; QA-02 |

Three preserved files already match GitHub byte-for-byte, 19 paths exist in newer
or different forms, and nine paths are absent. The absent paths are the four
research scripts, two dated notes and three test/support files above. Their ideas
are retained here; their old implementation is not automatically approved for
import. In particular, old October 20 notes must not override current native
commissioning or direct serial survey behavior.

## Delivery order

| Order | Work group | First deliverables | Dependency / completion gate |
| --- | --- | --- | --- |
| 0 | Baseline and evidence | BASE-01–BASE-03: reconcile old claims, preserve current tests and retain local ideas | Current GitHub baseline remains authoritative; no old code/layout replacement |
| 1 | Workspace coherence and acquisition reliability | UX-01–UX-04, QA-01–QA-02 | Complete target propagation, source isolation and regression coverage before broad new UI |
| 2 | JCI configuration, native engineering and hardware | JCI-01–JCI-07, JCI-09–JCI-10, IO-01–IO-04 | Reuse current adapter; supported typed edits, allocation, compilation and transfer expand independently |
| 3 | JCI schedules, application families and commissioning | SCH-01–SCH-03, SEQ-01–SEQ-07, JCI-08 | Build on existing portable foundations; target/code acceptance remains explicit |
| 4 | Shared semantics, diagnostics and portability | RUN-01–RUN-05, QA-03, PORT-01–PORT-03, REF-01–REF-03 | Small useful groups can proceed while a native or hardware dependency is unavailable |
| 5 | Remaining manufacturers | ALC-01, HON-01, TRI-01, SED-01, TEM-01, REF-04 | Each adapter has its own format/runtime/transfer and physical acceptance evidence |

Within a group, implement one feature or a coherent small set, test it, update
its criteria and submit a separate PR. Work that needs unavailable hardware or
new source evidence does not stop independent tasks. If a necessary question is
unanswered after 15 minutes, record the dependency and move to independent work;
elapsed time does not answer the question or authorize a dependent field write.
Bluetooth physical acceptance remains deferred until the adapter is available.

## Johnson Controls FX and Metasys: configure first

The native editing prerequisite integration combines the supported local Real-default
file-copy editor (`FMT-SIGNAL-DEFAULT-COPY-001`) with explicit backup/readback
state effects (`COMM-NATIVE-EFFECTS-001`). Both criteria and scopes remain intact.
This integration enables no new default-value transfer. A separate operation
must review the effective saved value, merge fresh settings, preserve other
application bytes, and verify the edited application and effective settings after
transfer. General logic generation and physical acceptance remain separate.

`FMT-NATIVE-EFFECTIVE-DEFAULT-001` adds snapshot-based compilation of one existing
Real default after merging the retained native saved settings. Program shows
archive versus effective values and exports a source-bound compiled copy; no new
field-transfer operation is enabled. JCI-03 and JCI-09 remain partial overall.

The [native workspace integration](docs/jci-native-workspace-integration.md)
combines source capabilities, actual MOI/MOZ reading and native record inspection
with the default editors/compiler/transfer. Capability analysis distinguishes
local copies, a required native saved-setting snapshot and separately reviewed
transfer, while preserving draft and target ownership. These credits do not
complete general native logic or package/resource validation.

`COMM-NATIVE-DEFAULT-TRANSFER-001` adds a separate one-default transfer operation
with fresh selected-value checks, merging of other fresh saved settings, durable
single-attempt restore and full native/effective-setting verification. Its web
workflow stays in Program and retains uncertain receipts for readback without
replay. Direct and explicit routed IP are qualified against authored protocol
peers; physical acceptance, arbitrary graph edits, package/resource validation and
hardware reassignment remain separate. JCI-03 and JCI-09 remain partial overall.

| ID | Planned addition | Workspace | Acceptance / dependency |
| --- | --- | --- | --- |
| JCI-01 | Build an operation-specific protocol/format/release capability matrix from discovered identity, application structure, packages and retained evidence | Overview / Program; Settings for toolchains | Partial: [captured-source operation support](docs/application-operation-capabilities.md) and [native backup analysis](docs/native-backup-operation-capabilities.md) credit actual readers, saved merging and typed compilers while separating transfer preflight, general logic, packages and physical acceptance. Continue package/release evidence, CAF correlation and retained transfer outcomes |
| JCI-02 | Extend real CAF/MOI inspection and loss-preserving editable intermediate representation | Program | Partial: [actual MOI/MOZ reading](docs/moz-application-reading.md), [native record explorer](docs/native-record-explorer.md), [Boolean archive copies](docs/native-boolean-default-copies.md) and [effective Boolean compilation](docs/native-effective-boolean-compiler.md) expose recorded properties, exact bytes and scoped typed local edits. [Existing-wire source copies](docs/native-wire-source-copies.md) preserve the remaining expanded bytes, identities, ports, targets, order and layout. [Retained backup comparison](docs/native-backup-comparison.md) separately preserves original file, recognized engineering-property and unaligned metadata evidence without field queries. Continue the broader editable representation, units and typed golden edits; no general logic generation is inferred |
| JCI-03 | Implement general native logic authoring: typed parameters, new block identities, links, ordering and full compile/resource validation | Program / Library | Partial: [existing-wire source archive copies](docs/native-wire-source-copies.md) change one observed source index within the original width and independently reparse/preserve the remaining graph bytes. [Effective wire compilation](docs/native-effective-wire-compiler.md) separately merges retained saved settings before that edit and guards original graph structure. [Existing-wire transfer](docs/native-wire-source-transfer.md) separately guards fresh selected configuration and verifies full native/effective readback. Continue full-program transfer, broader typed authoring/new identities and full resource/package/runtime validation; no general compiler or physical acceptance is inferred |
| JCI-04 | Extend FX/Metasys and cross-release conversion with explicit semantics and package migrations | Program → conversion review | Every supported source/target pair has a loss report and round-trip/behavior evidence; reject unresolved semantics instead of dropping logic |
| JCI-05 | Implement executable native Enum/reliability/type mappings and restart/retention rules | Program / Library | Partial groundwork: [original native Enum code copies](docs/native-enum-default-copies.md), [local effective Enum compilation](docs/native-effective-enum-compiler.md) and [CAF Enum default copies](docs/caf-enum-default-copies.md) preserve typing, source metadata and actual captured numeric capacity. Verify set membership, executable codes, fallback, units, precision, reliability and state/restart behavior separately; labels or manual named sets alone do not supply native numeric bindings |
| JCI-06 | Add versioned package provenance, native schema migrations and destination resource accounting | Settings / Program validation | Source/package/runtime compatibility and actual RAM/flash/scan/I/O limits are explicit; no silent hardware-definition substitution |
| JCI-07 | Associate a local CAF/project with a connected application using actual identity and compatibility evidence | Program / Changes | Partial: [original CAF/native identity comparison](docs/caf-native-source-correlation.md) and [retained File comparison](docs/caf-native-file-correlation.md) retain actual root/record IDs, separate source families, source/route/coverage and contradictions without granting full program or compiler equivalence. Continue semantic/package compatibility and persistent association; local files never supply live data implicitly |

### Test before JCI deployment

| ID | Planned addition | Workspace | Acceptance / dependency |
| --- | --- | --- | --- |
| QA-01 | Re-triage historical Schedule/String Schedule/source-filter/host-start and newly retained File/native-capture timeout failures against their exact source and original evidence | Developer checks; History for results | Preserve original failures; establish a concrete cause and repair before claiming fixed; a later pass is not an explanation |
| JCI-08 | Add calibration, balancing, actuator tests and target-specific online watch/force workflows | Points & I/O; Program / Commission | Preserve configuration, identify exact affected outputs and ownership, record readback and release/restoration; physical acceptance is separate |
| QA-03 | Extend native golden applications and reference-compiler/independent-runtime comparisons | Program validation; conformance tools | Cover changed logic, settings, resource limits, faults/restart and originals; use the existing direct native adapter where verified, and external CCT/PCT only where a particular route requires it |

Historical Source41 recorded 4,888 passes, one signed Schedule reference capture
failure and one intentional skip. It is historical evidence from a different
source baseline, not the latest regression result for `eee3836`. Retain its
original timing and evidence; do not mark it fixed by widening a timeout or by
asserting that newer native routed-transfer budgets repair unrelated Schedule
capture behavior.

The focused Calendar/Schedule diagnostic slice extends COMM-DIAG-001: an explicit
single-property trace accompanies the ordinary inventory and its exact original
export, without extra reads or timeout changes. Optional bounded observations at
the existing owned local UDP callback can retain a reflected frame discarded
before the native multiplexer, without changing source acceptance. Direct/routed
deliberate reference loss retains incomplete edit eligibility. Earlier signed primitive success
does not establish the historical Source41 cause; QA-01 remains open for that
cause and the separate String Schedule/source-filter/host-start investigations.

The focused Schedule and owned-UDP diagnostic branches are integrated with the
native Real/Boolean default and existing-wire compiler/transfer workspace. This
integration preserves the separate native capability profiles, source-bound
drafts and durable recovery paths. It does not resolve any historical missing
reply or promote local protocol qualification into physical acceptance.

### Deploy and verify JCI changes

| ID | Planned addition | Workspace | Acceptance / dependency |
| --- | --- | --- | --- |
| JCI-09 | Extend existing native backup/compile/transfer into each additional supported application edit and full-program workflow | Changes | Narrow Real, [Boolean default transfers](docs/native-boolean-default-transfer.md) and [fixed-storage Enum code transfer](docs/native-enum-default-transfer.md) preserve original application/settings, capacity, fresh selected-value guards, one-use typed intent and full readback. Enum meaning/membership remains unverified and previous-value recovery is separate. [Existing-wire source transfer](docs/native-wire-source-transfer.md) adds a separately reviewed graph edit with fresh configuration signatures, saved merging and full readback/recovery. Extend additional edits and full-program workflows separately; support is per operation/format, not all controllers |
| JCI-10 | Add supported restore/recovery operations and a broader post-change verification package | Changes / History | Partial: [Real-default recovery](docs/native-real-default-recovery.md) and the separate [Boolean-default recovery](docs/native-boolean-default-recovery.md) derive local previous-effective-value proposals from verified immutable receipt/source evidence, then require new confirmed one-use transfers and full readback while preserving other current settings. Read-only reconciliation comes first for uncertain outcomes; no automatic replay or assumed inverse write. [Existing-wire-source recovery](docs/native-wire-source-recovery.md) separately derives a previous connection source with current observed-pin/configuration/order/cycle/width proof and requires a new confirmed transfer. [Verified original-pin recovery](docs/native-historical-wire-pin-recovery.md) separately supports a missing current output pin using original connection evidence and unchanged current non-default source configuration, while retaining order/cycle/width checks and new confirmed transfer/readback. [Previous controller-name recovery](docs/native-controller-name-recovery.md) separately qualifies the original/current name-only evidence, preserves the instance and other fresh saved settings, and requires a new confirmed review/transfer/full readback with recorded lineage. [Previous instance recovery](docs/native-controller-instance-recovery.md) separately checks original and verified-after sources/static bindings, latent destination settings, a new reservation/collision/review/transfer and full readback with typed lineage. General application restore remains separate |
| IO-01 | Strengthen discovered hardware/live/archive correlation and candidate spare-input evidence | Points & I/O | Distinguish configured records, exposed objects, published capacities and physical wiring; missing points do not prove unused terminals |
| IO-02 | Extend validated terminal reassignment, electrical modes and cross-module/native allocation | Points & I/O / Program; Changes | [Native local universal-input allocation/mode editing](docs/native-inputs.md) adds source-pinned local copies and one-input native transfer with complete image, published-property and saved-setting readback. Integral/SA allocation, output modes and graph connections remain separate. Verify electrical capabilities, native references, package/resource limits and physical wiring; existing narrow CAF edits remain supported |
| IO-03 | Complete outdoor-air temperature/humidity voltage input engineering and supported deployment | Points & I/O | Sensor power, ranges, voltage mode/common/reference and scaling are explicit; any binary-point relocation has its own reviewed native change and restoration path |
| IO-04 | Verify a real unused-input/sensor change and post-deployment I/O quality | Points & I/O / Commission | Exact authorized target/terminal, backup and recovery; verify open-circuit/quality, scaling and actual wiring as applicable. Never infer native allocation from an ordinary point write |

Compatibility coverage must include the intended legacy FX-PCV/VMA 1630 and
cooling-only 1615 families when evidence and hardware allow. A target matrix
describes tested compatibility; it must not become a fixed model-selected live
inventory or an assertion that every release accepts the same application.

### Complete JCI application families and sequence acceptance

| ID | Planned addition | Workspace | Remaining behavior / acceptance |
| --- | --- | --- | --- |
| SEQ-01 | Six qualified native VAV deliverables: FX and Metasys × cooling-only, inline reheat without a fan, parallel fan-powered reheat | Program / Library; conformance | Extend existing graphs with full required sequence behavior; independently verify native files, exact hardware/releases and project-specific 2025 Title 24 requirements. Inline reheat is not a series fan-powered box |
| SEQ-02 | Complete series-fan and dual-duct VAV variants | Program / Library | Occupancy recovery, variable fan/pickup options, calibration/balancing, reheat/discharge protection, flow/ventilation and native deployment |
| SEQ-03 | Complete single-/dual-deck AHU applications | Program / Library | Return/relief/exhaust coordination, ventilation/CO2/humidity/enthalpy, heat recovery, reset, staging, zones and native protection priorities |
| SEQ-04 | Complete fan-coil, heat-pump and unit-ventilator applications | Program / Library | Coil/fan/changeover/staging options, occupied/unoccupied behavior, frost/condensate/proof protection and native acceptance |
| SEQ-05 | Complete chilled/hot/condenser-water plant sequences and distributed signals | Program / Points & I/O | Staging, pumps/valves, demand, pressure loops, towers/HX/WSE and real supervisory mapping; current hydraulic role/capacity plans are not plant control |
| SEQ-06 | Finish shared thermal/occupancy/request activities | Library | Demand/local adjustment/fallback and bypass; flow/occupancy fan requests, native CO2 airflow reset, CW output/ramp and pulse/Add-8 reliability semantics; reuse existing activities rather than add duplicate cards |
| SEQ-07 | Add complete functional acceptance and AFDD/reference comparisons | Program validation / Commission | Independent expected trajectories, relevant G36/reference cases, fault/recovery and post-transfer behavior. Authored examples and simulator passes do not certify code compliance |

The [November 1 software qualification](docs/software-validation-2026-11-01.md)
records 5,796 distinct backend passes across the original full run and an
explicit-toolchain follow-up. It retains two unexplained BACnet File/native
capture timeout failures and one intentional skip. This is not a single-run
full-suite pass or a repair for earlier Schedule observations.

The [read-only retained-backup comparison](docs/native-backup-comparison.md)
compares original Files 3/11/12 and bounded recognized record/property evidence
without a controller query. It does not merge saved values, infer semantic
compatibility or supply the general restore operation still required by JCI-09.

The [native backup catalog](docs/native-backup-lifecycle.md) adds reversible local
archiving within the unchanged 128 active-capture limit. Original files and
transfer/recovery references remain available, including across restart. This
implements a bounded retention workflow; general controller restore and whole-state
portability under JCI-09/10 and PORT-03 remain separate.

The [original native backup ZIP importer](docs/native-backup-import.md) adds
explicit bounded local ingestion in the same History catalog. Original IDs,
metadata and Files 3/11/12 remain intact, conflicting IDs refuse, and local
provenance stays separate from original acquisition evidence. Identical imports
preserve active/archived state; known unchanged partial imports can resume.
This implements IDEA-NATIVE-BACKUP-ZIP-IMPORT-001 without restoring field
authority, receipts, credentials or pending transfers. General controller
restore and whole-state migration remain separate.

The [native application storage profile](docs/native-application-storage.md)
reuses native POSIX/Win32 safe file handles without changing original backup or
transfer formats. Current computer durability appears separately from original
capture evidence. This extends PORT-03 storage support, while whole-state
migration and physical transport acceptance remain separate.

## Workspace and shared features

| ID | Planned addition | Placement and acceptance |
| --- | --- | --- |
| BASE-01 | Reconcile current capability/validation statements and the old requirement gaps | Delivered [JCI operation evidence ledger](docs/jci-operation-coverage.md): native capture/instance/name credit, scoped Real/Boolean/wire profiles, serial acquisition and historical validation. General logic, hardware deployment, broad restore and exact physical qualification remain separate; BASE-02/BASE-03 continue |
| BASE-02 | Maintain the preferred GitHub baseline and preserve local source ideas | Private original backups plus reviewed idea mapping; no stale whole-tree merge, private data publication or graphics rollback |
| BASE-03 | Keep requirement IDs, evidence classes and dependency/acceptance status current | Update the public register when an implemented slice is verified; distinguish code, simulation, loopback, reference-oracle and physical results |
| UX-01 | Finish full target propagation to older trends and single-log history views | Trends & Alarms: use the complete authoritative ControllerTarget, discovered point choices and stale-result invalidation instead of repeated manual addresses |
| UX-02 | Consolidate a searchable change/receipt ledger | Delivered [read-only recorded Changes ledger](docs/change-ledger.md): local drafts, eight evidence families, exact original route/interface, recorded outcomes/readback, bounded search and recovery navigation. Actual canonical native default references, exact wire indices and recorded Real-recovery lineage/parent search now appear without field dispatch or parent/source revalidation. Remaining: centralize unapplied transient reviews and add providers when they gain retained journals. Separate adapter transactions remain separate |
| UX-03 | Implement responsive navigation and inspector drawers | Delivered [primary responsive workspace panels](docs/responsive-workspace.md): labelled menu/task/tool controls, controller explorer, graph and CAF properties; touch/keyboard focus, repeated selection, retained drafts and resize. Desktop teal tabs/columns remain; full-page manufacturer engineering forms keep their existing task layouts |
| UX-04 | Apply common source, unavailable-capability and recovery presentation | Partial: [native backup and readback effects](docs/native-application-transfer.md#backup-and-verification-effects) are explicit in controls and new evidence. [Source-owned graph inspector drafts](docs/inspector-drafts.md) now preserve unfinished parameter text by exact block/field/source across task/drawer changes. Complete source/capability/recovery presentation in remaining older task views |
| QA-02 | Preserve the useful local real-wire acquisition and route-handoff test ideas | Existing browser suites: random independent peer, actual HTTP/UDP, changed later sensor reading, nondefault ports, no implicit connection/write and no duplicate fixture stack. [CAF race/draft regressions](docs/caf-workflow-validation.md) now follow the current entry/task/save workflow and pin fixture imports; their original eight scenarios remain intact. The [CAF local-scenario harness](docs/caf-local-input-scenarios.md) now follows Open CAF → Simulate while retaining its exact original source, quality, revision and delayed-export assertions. [History evidence regressions](docs/history-evidence-downloads.md) now use current Trends & Alarms navigation and suspend a still-unvisited module while preserving all original numeric, seal, cancellation and delayed-response assertions; [Schedule inventory regressions](docs/schedule-workflow-validation.md) now use verified controller selection and actual request targets at desktop/compact widths, retaining original native-byte/seal, routing, cancellation, no-retry and stale-result checks |
| SCH-01 | Complete native Calendar/exception/context editing and source-safe destination linking | Schedules: preserve existing guarded weekly-day and qualified String Schedule Apply; add typed special events and actual target/time/priority semantics |
| SCH-02 | Complete occupancy/supervisory schedule integration | Schedules / Program: warmup/cooldown, countdown, exceptions, group requests and qualified native mappings |
| SCH-03 | Complete cross-platform schedule semantics and deployment | Schedules: explicit timezone/DST/facets/ORD/status differences, SCT/Niagara/CAF integration and per-target readback/physical verification |
| RUN-01 | Add actual-runtime-dt/live-duration timer contracts | Program / Library: versioned startup, dynamic-duration, reset, quality rollback and target-width behavior; preserve legacy fixed-cadence profiles |
| RUN-02 | Add versioned canonical-unit control/state/gain policies | Program validation: qualify finite-precision and F/C trajectory differences independently; do not silently alter existing PI/control semantics |
| RUN-03 | Complete native reliability, resource, force/watch and retained-state semantics | Program / Points & I/O: connect actual quality and target limits to engineering results; qualify break conditions and metering debounce/overflow/persistence. Labels and finite values alone are insufficient |
| RUN-04 | Extend trends, COV, alarms, notification and history integration | Trends & Alarms / History: discovered points, exact route/source, lifecycle/acknowledgment/retention, supported notification channels, transport/failure coverage and supported vendor services; retain existing webhook/ownership guarantees |
| RUN-05 | Extend bounded operation power leases | Settings / operation status: cover additional capture/transfer and host/VM/platform paths; retire owned resources, never change global power preferences or replay operations |
| PORT-01 | Complete physical serial, direct MS/TP and additional IP transport acceptance | Settings / connection flow: retain existing software/pseudoterminal support; verify adapter direction/timing, physical routing and each supported native transfer profile |
| PORT-02 | Implement verified BTCVT/Bluetooth compatibility; assess additional protocol families | Settings / connection flow: verify actual BTCVT protocol/driver/firmware before claiming support. Evaluate BBMD hosting, BACnet/SC, IPv6, extended MS/TP/N2/proxy support as separate bounded profiles; physical Bluetooth testing waits for hardware |
| PORT-03 | Complete portable engineering environments and toolchain delivery | Settings / distribution: qualify reproducible Mac/Windows installs, source-bound artifacts and safe project/state migration. Preserve the Apple-silicon Mac-to-Mac Windows VM/reference-tool option where needed; licenses, vendor assets, adapter drivers and private credentials remain separate. The current direct native identity adapter does not require that VM |
| REF-01 | Parameterize the local manual inventory/OCR pipeline | Developer tools / Help: optional Apple Vision OCR, documented PyMuPDF dependencies, deduplication/editions, page/section hashes and confidence; no hardcoded Mac folders |
| REF-02 | Publish reproducible feature reports and ranking tools | Developer tools / Help: HTML/XLSX/CSV/JSON, source citations, formula-safe spreadsheets, configurable roots and manufacturer/workflow priorities; no private source documents in Git |
| REF-03 | Reassess the manual feature inventory against reusable implementations | Help/docs: retain original 2,343 IDs and source restrictions; add current scope credit, remaining behavior and evidence, avoiding one block or tile per manual heading |
| REF-04 | Review reusable ASHRAE/BACnet, OpenBuildingControl and Belimo functions | Program / Library / Help: verify sequence references and sensor/protocol behavior; document format/runtime and physical constraints instead of treating all restrictions as removable |

## Other manufacturers after Johnson Controls

For each family, use **Configure → Test before deployment → Deploy → Test after
deployment**. Common UI and interchange do not establish native compatibility.

| ID / order | Configure | Test before deployment | Deploy | Test after deployment |
| --- | --- | --- | --- | --- |
| ALC-01 / 1 | Verified native editable-source bridge, EIKON/WebCTRL types, modules and I/O mapping | Actual supported compiler/runtime and semantic/resource golden cases | Supported application transfer, backup/recovery and supported online edits | Physical application identity, live quality, behavior and restoration |
| HON-01 / 2 | Spyder/CIPer product-family formats, native modules/types, packages and I/O | Correct compiler/runtime, package and controller limits | Supported upload/download and live changes with original preservation | Actual firmware/model execution, faults and readback |
| TRI-01 / 3 | Extend existing Niagara BOG subset to verified components, station services and migrations | Workbench/station runtime, stateful semantics, module signatures and dependencies | Supported station/package transfer and online changes | Native station behavior, schedules, links, permissions and recovery |
| SED-01 / 4 | Extend existing Sedona compiler/runtime/kit support to matching physical platforms | ABI/kits/resources, retained state, native components and target semantics | Physical Sox/application transfer and restart/recovery | Physical I/O and sustained native behavior; host SVM coverage remains separate |
| TEM-01 / 5 | Extend existing Control Basic conversion/compiler/interpreter to supported physical firmware and full-device scope | Calendar/VAR limits, scan cadence, memory and settings | Retain existing slot backup/replace/readback/compensating restore; qualify physical transfer/flash and broader configuration | Physical execution, timing, flash persistence and recovery |

“Universal conversion” remains the goal for supported semantics. Every format pair
must explicitly map types, units, quality, priorities, state, execution order,
schedules, dependencies and physical I/O. Unknown private semantics require a
loss report or refusal, never a plausible but incorrect exported program.

## Per-feature review and release checklist

1. Confirm the task is still missing on current `main`; record its requirement
   IDs, manufacturer/protocol family, supported operation and workspace location.
2. Define the smallest useful behavior and meaningful acceptance criteria. Reuse
   existing primitives, acquisition and design patterns; preserve current layout.
3. Verify both entry paths, target propagation, offline work, draft retention,
   target-change invalidation, partial/error/uncertain results and keyboard access
   when the change affects those workflows.
4. Run checks appropriate to the change. Use authored peers and isolated state
   for mutation tests; do not use live writes to test interface changes. Preserve
   original failed evidence and investigate actual failures before broad reruns.
5. For a native edit, verify original source, type/schema/package compatibility,
   capacity, intended binary/semantic delta, saved settings and readback. Broader
   field acceptance uses its own defined scope and evidence.
6. Update requirement/roadmap status and source-bound test results. Do not replace
   current coverage with old private counts or claim simulator evidence is field
   acceptance. Keep site data and secrets outside commits and public reports.
7. Submit one coherent PR against current `main`. Review the exact final source
   and preserve existing receipts, UI contracts and accepted behavior. Close a
   superseded PR with a delivery mapping rather than replaying older code.

This roadmap publishes the plan and preserved ideas only. Application source,
graphics and current field behavior are unchanged by its publication.


## 2026-10-31 JCI-02/JCI-03 delivery: signal default file copies

The new scoped `FMT-SIGNAL-DEFAULT-COPY-001` criterion is implemented. Program
provides reviewed local copies of existing finite Real Default Value fields in
fully framed native Input Float/Output Float records. Only the four expanded
payload bytes may change; originals, unknown records and metadata are retained.
Exact source/property/route/configuration/review ownership and explicit rounding
are checked before a digest-verified download. Draft text remains attached to its
original source and station. See [the profile](docs/native-signal-default-copies.md).

JCI-02 and JCI-03 remain partial overall. This delivery adds no field write or
native-file upload entry path, saved-parameter update, arbitrary parameter/logic
compiler, resource/package/release qualification, CCT reopen result or physical
controller acceptance. The current operation family does not require a vendor
runtime; general native compilation still needs independent acceptance evidence.

The scoped [signed Integer reader](docs/native-signed-integer-reading.md) adds exact
signed32 stored values under JCI-02, retaining opaque byte evidence for other
widths/structures. It grants no additional write or general logic capability.

[Native backup archive inspection](docs/native-backup-record-inspection.md) extends
JCI-02 to retained File 3 sources without a connection or recognized saved schema.
It retains acquisition identity errors and does not grant a compiler or field action.


## 2026-10-31 QA-02 delivery: actual scan/survey freshness

`QA-ACQUISITION-001` qualifies the real browser → production HTTP → actual UDP
peer path with random identity and changed input values. The peer reuses existing
workspace fixtures; no saved scan or mocked acquisition supplies the results.
The same-configuration reopen test exposed pending metadata automatically
restarting. The scan workspace now retires old owners and requires explicit
resume/reread/new scan after an interface/bind/epoch change, while retaining
original observations. Read-only peer request evidence and owned cleanup are
checked. Current controller-centered navigation and hidden target fields remain.

This implements a concrete part of QA-02 and preserves the original local ideas
without restoring older layout or dated source files. Other operation/transport
and physical acceptance remain independent. See [the scope and tests](docs/scan-survey-freshness.md).


## 2026-10-31 UX-01 delivery: selected serial monitoring

`UI-MONITOR-SERIAL-001` adds explicit selected-controller direct-MS/TP field
recording and single-log history to the earlier IPv4 context work. Actual
object-list/name choices, full original serial interface identity, before/after
Device/object checks, staged samples and exact historical byte evidence use the
existing open master. Changing source/cursor retires visible old pages, and a
newly admitted recording remains selectable before its first catalog entry.
Irrelevant IP route fields are hidden/cleared for serial controller selection.

This is an extension of the earlier selected-monitoring feature and is delivered
as a separate dependent PR. The broader UX-01/PORT-01 work remains partial:
physical RS-485/adapter/controller and BTCVT acceptance, other monitoring profiles
and additional native operations retain separate gates. No native application
write, generic API widening, automatic reconnect/resume, extra retry or timeout
expansion is added. See [the serial profile](docs/controller-monitoring-context.md).

## 2026-11-02 JCI-02 / UX-03 delivery: graphical CAF inspection

Program → CAF file → Logic now displays actual CAF blocks, named ports, arrowed
connections and nested activity/sequence navigation. Readable signal-flow layout,
source-specific view positions, search, upstream/downstream tracing and a
responsive stored-property inspector keep this work inside the existing file
workflow. Dragging native ports stages the existing guarded source-substitution
or prototype-connection export between existing blocks; original archive data
stays separate from the local view and proposed wiring.

Authored backend/browser fixtures cover nested identities, source isolation,
delayed property responses, view-only moves and exports that preserve native
object inventory, positions and order. Local private-file checks supplement these
fixtures without committing controller files or site data. No new native block
creation, complete program compiler or controller download is added. JCI-02 and
JCI-03 remain partial. See [the graphical workspace and guards](docs/caf-native-graph.md).

## 2026-11-02 JCI-02/JCI-03/JCI-05 delivery: original Enum code file copies

`FMT-NATIVE-ENUM-DEFAULT-COPY-001` adds reviewed local copies of actual class
528/529 Enumerated Default Value (3113) fields. The compiler retains the original
width when sufficient, grows only the selected value/framing when necessary and
independently reparses and checks unrelated native bytes. No-op copies preserve
original archive bytes. Sources and all retained Files 3/11/12 remain unchanged.

The existing Program record inspector exposes this operation for captured fields,
with source-specific unfinished text, exact response evidence and digest-checked
artifact downloads. No connection is required. Saved settings, semantic set
membership, executable mappings, Enum transfer and general native compilation
remain separate. The generic backup operation table separately qualifies the local Enum copy
using actual eligible encodings. JCI-02/JCI-03/JCI-05 remain partial overall. See
[the supported profile and qualification](docs/native-enum-default-copies.md).

## 2026-11-02 QA-02 delivery: isolate native copy browser fixtures

`QA-NATIVE-COPY-TEST-ISOLATION-001` moves legacy Boolean/wire copy browser cases
to the existing per-test server and explicit state directory. Combined source
and installed qualification uses the same 106 cases while the global runner
directories are already full at the unchanged 128-backup quota. Original runner
archives remain intact. Production code, assertions, deadlines and retries are
unchanged. See [the failure and qualification scope](docs/native-copy-test-isolation.md).

## 2026-11-02 JCI-01 delivery: original Enum-copy capability reporting

`QUAL-NATIVE-ENUM-COPY-CAPABILITY-001` adds a twentieth operation to retained
backup analysis. Actual native class/property/datatype/encoding eligibility
qualifies local Enum code copies independently of saved schema or transport.
The report preserves identity/framing errors, counts eligible captured fields
and explicitly leaves Enum semantics unverified. Existing controller preflight,
semantic mappings and physical acceptance remain separate. See
[the operation profile](docs/native-backup-operation-capabilities.md).

## 2026-11-02 JCI-02/JCI-03/JCI-05 delivery: CAF Enum default code copies

`FMT-CAF-ENUM-DEFAULT-COPY-001` extends the existing local CAF scalar editor to
actual class 528/529 ordinary Default Value (3113) Enum fields under an explicit
source-bound profile. It retains raw set references and other XML bytes, supports
mixed scalar edits, and preserves the existing clicked-snapshot save behavior
while newer drafts stay dirty. Source/request/artifact hashes now guard scalar
CAF downloads. New controls follow the existing inspector/review layout.

This is a local numeric code copy. Membership, meaning, executable mappings,
Enum simulation, native compilation, field transfer and CCT/physical acceptance
remain separate work. JCI-02/JCI-03/JCI-05 stay partial overall. See
[the supported profile and qualification](docs/caf-enum-default-copies.md).

## 2026-11-02 JCI-02/JCI-03/JCI-05/JCI-09 delivery: local effective Enum compilation

`FMT-NATIVE-EFFECTIVE-ENUM-COMPILE-001` merges identity-qualified retained saved
settings before changing one existing class 528/529 Enum default. Original and
merged values stay separate; an actual fixed Enum slot supplies its numeric
capacity, with no capacity or domain selected from a model name. The compiler
preserves other merged native bytes and all original backup files.

The existing record editor gains an explicit source mode, independent unfinished
raw text and source-bound review/artifact downloads. No connection is required.
Enum meaning/membership, executable mappings, general native compilation and
Enum field transfer remain separate. The generic operation table separately
qualifies the actual effective compiler. These JCI roadmap groups remain partial overall. See
[the compiler profile](docs/native-effective-enum-compiler.md).

## 2026-11-02 JCI-01 delivery: effective Enum compiler capability reporting

`FMT-NATIVE-EFFECTIVE-ENUM-CAPABILITIES-001` adds one source-specific local
effective-Enum compilation operation to the existing native backup support
table. Actual retained identity, saved merge and eligible typed fields determine
support. Captured fixed numeric storage and unknown selected capacity retain
separate counts; neither establishes allowed states or meanings. Archive-only
Enum copies remain independent of the saved format and acquisition interface.

The browser independently binds all original files, saved-merge hashes,
historical identity, counts, error and ordered row status. Readable records and
unfinished drafts remain available when compilation is unsupported or a reply
is rejected. No Enum field preflight, transfer or physical acceptance is added.
JCI-01/JCI-05/JCI-09 remain partial overall. See
[the operation support profile](docs/native-backup-operation-capabilities.md).

## 2026-11-02 JCI-03/JCI-05/JCI-09 delivery: one fixed-storage Enum code transfer

`COMM-NATIVE-ENUM-DEFAULT-TRANSFER-001` separately transfers one existing typed
Enum default with an actual selected fixed saved slot. It adds exact native
IPv4 source/target review, fresh selected code/state-metadata fingerprints and application/
directory guards, merging of other fresh settings, capacity qualification,
durable one-use restore and full native/effective readback. No-slot local
UInt32 copies remain local-only. The support table separately reports its
source/storage/transport preflight requirement.

Program reuses the effective Enum editor and existing transfer panel, with exact
code confirmation, source/navigation locking, preserved drafts, canceled late
review retirement and original review/receipt downloads. Changes identifies the
recorded Enum operation without querying a controller. Uncertain outcomes retain
readback/restart reconciliation without replay. Code meaning, allowed states,
executable mappings, previous-Enum-value recovery, general logic authoring and
physical acceptance remain separate. These JCI groups remain partial overall.
See [the operation's scope and evidence](docs/native-enum-default-transfer.md).

## 2026-11-02 JCI-03/JCI-05/JCI-09 delivery: previous effective Enum code proposals

`COMM-NATIVE-ENUM-DEFAULT-RECOVERY-001` prepares a local previous-code proposal
from a resolved, historically verified separate Enum-default transfer receipt.
It reconstructs the original payload and binds the exact current source/identity,
selected fixed slot, strict codes, actual encoding widths and encoded state
metadata. Other current saved values remain current; an already-previous source
creates no Apply proposal. Missing proof, unrelated codes or changed configuration
refuse preparation without controller queries.

Program retains ordinary raw drafts separately, exports exact proposal JSON and
requires a new review, both confirmations, fresh pre-intent qualification and
full readback. Lifecycle/Stop/source changes retire late proposals and reviews
while preserving dispatched uncertainty. Direct/routed authored software tests
cover new transfers and restart reconciliation without replay. Common Changes
lineage projection, historical slot capacity after removal, Enum semantics,
general native authoring and physical acceptance remain separate. These JCI
groups remain partial overall. See [the recovery profile](docs/native-enum-default-recovery.md).

## 2026-11-02 JCI-03/JCI-09 delivery: recorded Enum recovery lineage

`COMM-NATIVE-ENUM-RECOVERY-LEDGER-001` projects a known sealed previous-Enum
origin and its child receipt into the existing Changes/History table and evidence
drawer. It binds strict codes, actual encodings, selected storage/state metadata,
review snapshot, unchanged identity and recorded confirmations. Original dispatch
facts remain separate from later observations. Missing parent/source availability
does not erase recorded lineage or establish current live state.

The browser validates the projection independently, retains unavailable markers
and exact original JSON, and supports local parent-reference search. No controller
query, original backup load, parent-proof lookup or new field authority is added.
Existing workspace routes, source filters and styles remain in place. Historical
capacity after a saved slot is removed, Enum meanings, general native authoring
and physical acceptance remain separate; these JCI groups remain partial overall.
See [the projection and evidence scope](docs/native-enum-recovery-ledger.md).

## 2026-11-02 PORT-03 / QA-03 delivery: browser build input/output provenance

`UI-BUILD-PROVENANCE-001` prevents a portable package from stamping current source
while reusing unrelated prebuilt browser assets. The standard build compiles a
frozen UI input snapshot, records exact input/output hashes and checks current
input/environment continuity before publication. Failed or changed-source builds
invalidate prior proof; ordinary and development packaging both require a known
matching proof. The Python packager independently checks the declared inputs,
locked compiler versions and actual staged bytes before invoking pip.

The application layout, controller operations and all styles remain unchanged.
The wheel keeps prebuilt browser assets and requires no Node.js on the receiving
computer. This is source/artifact provenance, not a claim of hermetic builds,
cross-platform bit reproducibility, a manufacturer compiler or physical acceptance.
Broader environment/toolchain delivery remains partial. See
[the portable build contract](docs/portable-distribution.md).
