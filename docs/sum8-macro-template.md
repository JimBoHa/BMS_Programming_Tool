# Eight-input sum macro template

The source-qualified sum template supplies one editable portable macro with eight required numeric ports and one result. It uses the existing macro library, importer, instance wiring, simulator and interchange paths. It creates no new arithmetic primitive or native JCI block.

The source is **Controller Tool Help18.0**, LIT-12011147, PDF677, tables276–277, dated2025-10-06. Original PDF SHA256: `68935362c85cb1879dc033cc701115e8ea7c4ecb26748f21a9ceaf0454f82903`. [Official Help](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/18.0). The source describes adding Input1 through Input8 into CH-TOT, with zero defaults and editable logic, including Chiller Load Total Calc use. Its neighboring Capacity Calculation module has additional rated/running/availability semantics that this template does not implement.

## Exact portable contract

Profile `studio-sum8-macro-template/1` generates sixteen ordinary nodes: eight Inputs named `i1` through `i8`, seven existing Add nodes, and Output `result`. Fifteen edges fix this evaluation order:

`(((((((i1 + i2) + i3) + i4) + i5) + i6) + i7) + i8)`

The order is authored because the manufacturer description does not specify one. This is a left fold, with no initial extra zero, reassociation, compensated arithmetic, saturation or sum-of-capacities interpretation. It leaves the existing two-input Add unchanged.

Choose one homogeneous unit label: dimensionless (`""`), `A`, `kW`, `cfm`, or `L/s`. Every Input, Add and Output carries that exact label. These are authored catalog labels, not recovered manufacturer enum values. No automatic conversion, absolute-temperature summation, measured flow, chiller capacity, rating or availability is inferred.

All eight exposed macro ports require writers under existing macro rules. Connect an explicit zero for an unused contribution. A standalone definition has zero Input defaults; that does not make an instantiated macro's unwired ports optional. Existing type, unit, library-size, target and dependency checks apply.

The definition identity is deterministic for the chosen unit. Importing an identical definition with the same identity is idempotent. A same-identity definition with different content is refused; it never overwrites an existing definition. Creating an instance remains a separate deliberate action using the existing macro workflow.

## Numbers, quality and edits

The unchanged host runtime uses binary64 arithmetic. The optional host IEC runtime uses REAL/float32. A declared order does not make the two widths numerically identical. For example, the left fold beginning `16777216 + 1 − 16777216` produces1 in binary64 and0 in REAL. The focused native boundary test preserves this exact observed difference, including `matches_reference:false`; it does not widen tolerances or label those values equivalent.

All required inputs participate in the unchanged transactional quality policy. Bad quality or nonfinite arithmetic fails the whole scan and retains previous committed outputs/state, including a nonzero total. Before the first successful scan the runtime does not preseed an engineering safety value. These are simulation policies, not native per-block reliability enums, hardware protection or underflow signaling guarantees.

The template does not normalize source numbers. Its generated defaults use their actual server representation. Existing Program-source transport and portable bundle paths preserve authored signed zero and scientific values when definitions are edited, exported and saved. Original source bytes, projected display text and numeric value comparisons remain distinct.

The existing definition editor can change internal logic while preserving its public port contract. Generation metadata then remains historical provenance: compare the current definition digest to the original generated digest before describing it as an unchanged template. A modified Add-to-Subtract definition is deliberately tested; retaining the source citation does not turn that edited logic into the original sum.

## API and original artifacts

`GET /api/macros/templates/sum8/catalog` returns the source-qualified profile/hash, five units, strict request schema and export choices. `POST /preview` requires `{unit}` and supports the existing `X-Studio-Program-Source:true` response envelope. The report includes profile/choice/definition/Program/bundle hashes, the actual ordinary graph, the existing `bms-macro-library/1` bundle, required ports and diagnostics. The Program appears both at `program` and inside the bundle; both original source descriptors bind the same generated Program digest.

`POST /export` accepts `{unit,format:"review"|"bundle"}`. Review is the default. It returns original compact canonical JSON bytes with `X-File-SHA256`. The bundle export is the existing portable MacroArchive, suitable for the unchanged `/api/macros/import` operation. All POST operations use the application's normal local token policy. No template endpoint saves a project, opens a field interface, leases power or modifies a controller.

Hashes establish content integrity, not manufacturer authentication. Native CAF/package identity, JCI compilation/download, firmware and physical controller acceptance, full capacity calculations, and G36/Title24 acceptance remain outside this feature. `MACRO-SUM8-001` tracks this bounded template; broad `MF-a06ed19e27` remains partial.

## Verification scope

Focused independent core cases cover exact graph/order/units, mixed signs, scientific values, cancellation, all-negative zero, explicit zero contributors, every required bad-quality input, overflow rollback, missing/type/unit writers and definition conflicts. Actual local API tests cover both original exports, existing macro import/instantiate/edit, simulation, saved/reopened revisions, exact SQLite content observations and JSON/ST/PLCopen/GraphML interchange with field/power activity absent.

Three pinned MatIEC/clang cases exercise unchanged macro lowering, normal arithmetic and all eight bad-quality inputs, the explicit REAL/binary64 cancellation boundary, and signed zero. Original Program, pre-generated and actual compiler ST, generated C/host/executable artifacts and decoded worker observations are retained privately. Decoded observations are not raw stdout or JCI firmware evidence. Original test-oracle failures and their affected followups remain separate validation stages.

## Web workflow

Open **Macros → Eight-input sum template** and explicitly choose one of the five unit labels, including dimensionless. Preview shows the actual eight required input ports, result, sixteen editable blocks, fifteen wires and fixed left-fold order. The profile and source citation remain separate from physical measurements or native block identity.

Download the original review or portable bundle only for the current editor, chosen unit and verified profile. Both retain the original HTTP Blob and its byte SHA-256; the bundle also matches the exact preview's bundle digest. Import requires confirmation naming the current editor and uses the existing macro importer. Identical definitions remain idempotent; conflicting definitions refuse without overwriting. Import adds only the library definition and saves no project revision. Use **Add instance to program** separately, then wire all eight ports, using explicit zero for unused contributions.

Changing the editor or unit, discarding a pending response, leaving the macro view, or a failed criteria reload retires the previous preview and downloads. A discarded or unmounted import cannot adopt its late computed response into the editor. Existing definition editing, simulation, deliberate revision saves and interchange remain available; later edits retain historical generation provenance rather than an unchanged-template claim. No template operation opens field networking or acquires a power lease.

## Canonical source conflicts during macro import

The existing import endpoint now compares a same-ID definition's name and canonical Program bytes after validation. Negative zero versus positive zero, and integer versus floating values in parameters or opaque metadata, are distinct sources and produce a conflict. Reordering mapping keys remains idempotent when canonical source bytes agree. A refusal retains the existing definition and editor authority; it does not save or overwrite a project. This corrects the previous use of Python numeric equality, which could treat those different sources as identical.

The sum template profile, generated graph, original-artifact formats, native arithmetic and compiler policies remain unchanged. Generation metadata remains historical after an edit. The comparison binds validated canonical Program identity; it does not claim that different HTTP whitespace or equivalent exponent spellings are different manufacturer programs.
