# BMS Studio development roadmap

Updated: 2026-10-30. Planning baseline: GitHub `main` at
[`eee38367`](https://github.com/JimBoHa/BMS_Programming_Tool/commit/eee38367aecd0b3f405809a76c500fe09ee2ad9f).

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

The public requirement register currently records 146 scoped criteria: 92
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

## Existing capabilities to preserve and credit

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

| ID | Planned addition | Workspace | Acceptance / dependency |
| --- | --- | --- | --- |
| JCI-01 | Build an operation-specific protocol/format/release capability matrix from discovered identity, application structure, packages and retained evidence | Overview / Program; Settings for toolchains | Credit current identity operations; distinguish read, edit, compile, transfer and physical acceptance; unsupported formats explain why |
| JCI-02 | Extend real CAF/MOI inspection and loss-preserving editable intermediate representation | Program | Preserve unknown records, references, execution order, positions, units and original bytes; supported edits have typed golden cases |
| JCI-03 | Implement general native logic authoring: typed parameters, new block identities, links, ordering and full compile/resource validation | Program / Library | First native graph-editing slice independently compiles and reopens/readbacks on its exact supported format; identity-only compiler is not credited as general logic generation |
| JCI-04 | Extend FX/Metasys and cross-release conversion with explicit semantics and package migrations | Program → conversion review | Every supported source/target pair has a loss report and round-trip/behavior evidence; reject unresolved semantics instead of dropping logic |
| JCI-05 | Implement executable native Enum/reliability/type mappings and restart/retention rules | Program / Library | Verify codes, fallback, units, precision and state; labels or manual named sets alone do not supply native numeric bindings |
| JCI-06 | Add versioned package provenance, native schema migrations and destination resource accounting | Settings / Program validation | Source/package/runtime compatibility and actual RAM/flash/scan/I/O limits are explicit; no silent hardware-definition substitution |
| JCI-07 | Associate a local CAF/project with a connected application using actual identity and compatibility evidence | Program / Changes | Linking never treats an opened file or generic graph as the live controller application; target changes invalidate write reviews |

### Test before JCI deployment

| ID | Planned addition | Workspace | Acceptance / dependency |
| --- | --- | --- | --- |
| QA-01 | Re-triage historical Schedule/String Schedule/source-filter/host-start failures against the current source and original evidence | Developer checks; History for results | Preserve original failures; establish a concrete cause and repair before claiming fixed; a later pass is not an explanation |
| JCI-08 | Add calibration, balancing, actuator tests and target-specific online watch/force workflows | Points & I/O; Program / Commission | Preserve configuration, identify exact affected outputs and ownership, record readback and release/restoration; physical acceptance is separate |
| QA-03 | Extend native golden applications and reference-compiler/independent-runtime comparisons | Program validation; conformance tools | Cover changed logic, settings, resource limits, faults/restart and originals; use the existing direct native adapter where verified, and external CCT/PCT only where a particular route requires it |

Historical Source41 recorded 4,888 passes, one signed Schedule reference capture
failure and one intentional skip. It is historical evidence from a different
source baseline, not the latest regression result for `eee3836`. Retain its
original timing and evidence; do not mark it fixed by widening a timeout or by
asserting that newer native routed-transfer budgets repair unrelated Schedule
capture behavior.

### Deploy and verify JCI changes

| ID | Planned addition | Workspace | Acceptance / dependency |
| --- | --- | --- | --- |
| JCI-09 | Extend existing native backup/compile/transfer into each additional supported application edit and full-program workflow | Changes | Preserve original application and saved parameters, capacity checks, fresh preflight, exact one-use intent and readback; support is declared per operation/format, not all controllers |
| JCI-10 | Add supported restore/recovery operations and a broader post-change verification package | Changes / History | Read-only reconciliation first for uncertain outcomes; no automatic replay or assumed inverse write. A restore requires its own verified contract and application/settings/operational checks |
| IO-01 | Strengthen discovered hardware/live/archive correlation and candidate spare-input evidence | Points & I/O | Distinguish configured records, exposed objects, published capacities and physical wiring; missing points do not prove unused terminals |
| IO-02 | Extend validated terminal reassignment, electrical modes and cross-module/native allocation | Points & I/O / Program; Changes | Verify electrical capabilities, native references, package/resource limits, original settings and independent readback; current narrow same-controller CAF edits remain supported |
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

## Workspace and shared features

| ID | Planned addition | Placement and acceptance |
| --- | --- | --- |
| BASE-01 | Reconcile current capability/validation statements and the old requirement gaps | Operation-level evidence ledger in Help/docs; credit native instance/name transfer and direct serial survey without claiming general logic download |
| BASE-02 | Maintain the preferred GitHub baseline and preserve local source ideas | Private original backups plus reviewed idea mapping; no stale whole-tree merge, private data publication or graphics rollback |
| BASE-03 | Keep requirement IDs, evidence classes and dependency/acceptance status current | Update the public register when an implemented slice is verified; distinguish code, simulation, loopback, reference-oracle and physical results |
| UX-01 | Finish full target propagation to older trends and single-log history views | Trends & Alarms: use the complete authoritative ControllerTarget, discovered point choices and stale-result invalidation instead of repeated manual addresses |
| UX-02 | Consolidate a searchable change/receipt ledger | Changes: exact target, local-versus-field operation, state, review/dispatch/readback and links to recovery. Do not turn separate operations into an atomic batch |
| UX-03 | Implement responsive navigation and inspector drawers | Preserve desktop engineering tables and current teal design; keyboard/touch focus, labelled states and draft preservation on smaller screens |
| UX-04 | Apply common source, unavailable-capability and recovery presentation | Existing task views retain one primary action, live/file/simulator labels and precise save/apply language; improve incomplete older integrations without a dashboard redesign |
| QA-02 | Preserve the useful local real-wire acquisition and route-handoff test ideas | Existing browser suites: random independent peer, actual HTTP/UDP, changed later sensor reading, nondefault ports, no implicit connection/write and no duplicate fixture stack |
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
