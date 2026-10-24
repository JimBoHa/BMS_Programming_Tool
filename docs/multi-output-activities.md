# Named mixed-output reusable activities

Version2 activities group an editable control graph behind named inputs and one
to32 independently typed outputs. One instance has one shared state graph. A
numeric result, Boolean status and diagnostic result can therefore observe the
same timer, delay or PI state without running a separate copy for each output.

This is an authored Studio graph facility informed by the interface patterns in
Controller Tool Help18.0. It does not implement proprietary JCI/ALC activity
algorithms, Enum values, reliability mapping, native CAF/packages or controller
download. A source-level interface and successful local host simulation do not
establish a physical controller interface or protection.

## Explicit versions

Existing single-output `Macro` libraries and `bms-macro-library/1` archives retain
their version1 services, expansion names and byte contracts. Opening, inspecting,
saving or exporting a document does not migrate it. Existing Sum8 and cancelable
pulse templates remain version1 definitions.

The new source representation is:

```json
{"macros":{"version":2,"definitions":[{"id":"controller","name":"Controller","program":{}}]}}
```

The abbreviated Program in that illustration must be a real validated Program
with named Input and Output interfaces. An activity instance is a Node with
`kind:"Activity"`, `params:{"definition":"controller"}`, `value_type:"number"`
and `unit:""`. These last two fields are a required container sentinel, **not a
numeric output**. The instance disappears during executable lowering. It has no
implicit first output and cannot be forced as a scalar.

Only an exact integer library version2 chooses the new implementation. All other
versions pass through the unchanged version1 validator or fail there; existing
version1 admissions, including its previously accepted Boolean/float aliases for
version1, are preserved. Activity nodes with missing or wrong library context
cannot execute as an ordinary scalar block.

A version2 library contains version2 Activity references. It refuses version1
Macro nodes, recursive dependency cycles, nested library metadata, native Sedona
extensions and physical terminal assignments inside definitions. Migration is a
deliberate separate operation, never an implicit mixed-version interpretation.

## Port and state contracts

All Input node IDs are required named input ports. Each definition contains
one to32 ordinary Output nodes. Each Output node's case-sensitive ID is its public
output port; its label is presentation, and its Boolean/number type and unit are
the exact wiring contract. An ordinary node continues to have only `out`.
An Activity wire names a declared output using `source_port`; `out` is valid only
when the definition actually declares an Output with that ID.

All wires retain one writer per target port, exact type/unit checks and ordinary
cycle rules. A Delay remains an explicit prior-committed-scan boundary. Selection
extraction groups boundary signals by `(source node, source port)`, so two outputs
from one selected or external Activity remain distinct. Fanout shares one alias.
Root Inputs and Outputs remain outside extracted definitions.

Each full instance path expands once into existing ordinary blocks. Definition
Inputs and Outputs become zero-delay typed Switch aliases, driven by one true
selector per instance. They introduce no feedback memory or tuple arithmetic.
Every output observes the same expanded internal state; unused outputs still
exist but do not create extra root published outputs. Two different instance paths
have independent state. Normal edge dependencies remain real: if a definition
wires an Output internally, forcing that alias can affect its downstream logic.

The existing engine's complete-scan transaction governs all outputs and state.
A non-good input quality or arithmetic fault rolls back the entire attempted
scan, including time and previously positive outputs. It is not an immediate
physical shutdown policy. Fresh sessions start with ordinary block defaults;
loading a graph does not restore a running controller's state.

The parent scan and target govern execution. The scan stored inside a definition
does not create another clock. Integer/binary64, native REAL32 and target numeric
differences remain unchanged. Coupled output roles do not imply target arithmetic,
calendar, timing or physical equivalence.

## Authoritative aliases and source identity

`studio-activities/2` is an orthogonal expansion profile. It does not change the
existing numeric literal or private IEC symbol profiles. The binding report
`bms.activity-bindings/1` includes the original Program identity/revision/digest,
the expanded Program digest and each instance path/definition/output ID/type/unit
with its ordinary alias ID. The expanded digest lives outside the expanded
Program; its own metadata does not contain a self-referential digest.

An output alias is `ao2_` followed by the first24 lowercase hexadecimal digits of
SHA256 over compact UTF8 JSON `['output', ...instance_path, output_id]`. Actual JSON
uses double quotes and no whitespace. Existing node ID rules make those strings
ASCII. Private ordinary nodes, selectors and edges use separate `an2_`, `ac2_`
and `ae2_` domains. All generated, root and container identity collisions refuse;
they are never silently reseeded or replaced. The aliases are not controller
addresses or authenticated field identities.

The original Program hierarchy remains editable and is retained by Engine.program
and source exports. Lowering validates a private copy. If a direct Python caller
has made a valid schema-controlled numeric display edit such as integer `x=1`,
the private copy may hold typed float `1.0`; the binding still names that exact
original caller/Engine Program digest. Invalid mutated bounds refuse. Opaque
parameter and metadata numeric atoms are not normalized into floating values.

Catalog descriptors include `program_sha256`, full `definition_sha256` and
`archive_sha256`. The last is the digest of the exact dependency-closed canonical
archive2 download. Catalog and resolve bind the current source digest, enabling
the browser to check original response bytes without emulating Python float
serialization. Digests bind bytes and context; they authenticate no sender.

Executable graphs return a resolve binding. Unfinished ordinary editor graphs
retain catalog handles and diagnostics, but cannot gain active alias/force
authority until their expansion validates. Portable simulation forces use the
existing force map and an explicitly chosen bound output alias. Existing forces
remain held until explicitly changed or released. Native IEC/Sedona internal-port
forcing is not added or inferred.

Current IEC compile, verification and scenario reports carry the activity binding
once beside the actual returned typed SymbolTable. Individual scan frames remain
unchanged. Ordinary root Input/Output observations continue to work in declared
portable conformance suites. Direct Activity-container scalar observations or
per-port conformance selectors are not provided. Existing dependency analysis
remains a hierarchy-level source view; an Activity has no scalar scan index.

## Version2 services and editing

`GET /api/activities/profile` returns the expansion rules and DTO schemas.
Explicit local authenticated POST operations provide:

- `/catalog` and executable-only `/resolve`.
- `/create` from a bounded internal selection, `/instantiate` and `/definition`.
- `/update`, `/delete`, dependency-closed `/import` and original-byte `/export`.
- `/migration/preview` and `/migration/apply` for an original version1 Program.
- `/migration/bundle-preview` and `/migration/bundle-export` for an archive1.

Program-bearing responses support the existing exact Program source transport.
Archive downloads are original canonical JSON with `X-File-SHA256`. Authoring
does not save a project automatically, acquire a power request or open field
networking. Ordinary project revision/save/reopen and existing simulation APIs
continue to operate on the original source hierarchy.

Inspection includes the exact dependency context required to apply an edit. The
new update service compares that context by canonical source, including signed
zero and integer/float distinctions. The definition inherits the parent clock
and target. While any root or nested instance uses it, input/output IDs, types
and units must stay unchanged. Labels, layout and logic may change with ordinary
validation. Unused definitions may change contracts. Deletion refuses any active
root/nested reference.

Import compares the validated definition name and canonical Program bytes.
An identical same-ID definition is idempotent; a source conflict refuses without
overwriting the current definition. Canonical key reordering is harmless, while
`-0.0` versus `0.0` and `0` versus `0.0` remain distinct opaque source atoms.
Archives must contain exactly their root dependency closure, with no unrelated
hidden definitions.

Limits retain the existing64 definitions,4000 total definition nodes,8 dependency
levels,256 expanded instances,2000 expanded nodes or the lower parent target
limit,10000 edges and4MiB library. Each definition has at most32 Inputs and32
Outputs. This is no global resource increase or native hardware capacity claim.

## Deliberate migration and retirement

Migration validates the complete version1 dependency library and resolves its
Macro references and existing wires. It changes each Macro container once to
Activity/sentinel and each old `out` source edge to the referenced definition's
single existing Output ID, across the root and shared definitions. It preserves
ordinary IDs, values, metadata atoms, state boundaries and missing wires. An
unwired ordinary block or newly placed instance may remain an unfinished draft;
migration does not invent connections. Ambiguous references, ports, contracts,
cycles, native extensions or physical bindings refuse.

An explicit empty-library initialization is allowed for an ordinary unfinished
Program with no unresolved Macro/Activity containers. A source already at
version2 is not repeatedly promoted. An archive1 requires deliberate promotion
before import into a version2 library; version2-to1 downgrade is not implemented.

Preview retains the converted Program or archive, original source digest,
converted digest, exact rewrite list/digest, expansion profile and review digest.
Apply/export rederive the same result and compare the supplied profile/review.
This is stateless provenance and stale-payload admission. It is not persisted
server review, compare-and-swap, a signature, target identity or field authority.
Keep the original Program/archive separately; there is no state or force
migration.

The graphical workflow retires the owned simulation and clears values, history,
forces and alias authority when applying migration or changing source/contracts.
It must recheck source/version/epoch/mount ownership before adopting any pending
response, including a delayed legacy editor response. No alias force is remapped
to a new source, even when a later source has a similar label.

## Formats and evidence scope

Current portable JSON, ST V3, symbol-qualified PLCopen and GraphML retain the
original hierarchy and named ports on strict Studio reimport. Version1/2 legacy
IEC export/import envelopes refuse version2 activities instead of relabeling new
semantics under an old source contract. The actual old emitters, old numeric/
symbol rules and accepted legacy Program/source/kit bytes remain separate.

Existing Sedona, Temco and Niagara encoders consume the ordinary lowered graph
only where their existing primitive, unit, resource, timing and numeric profiles
admit it. A conversion may refuse a larger graph or unsupported state. Native
Sox reflection exposes existing root slots, not every private Activity port.
GraphML's external edges alone do not encode all typed semantics; its original
Studio source envelope is required for the strict hierarchy round trip.

Validation includes hand-calculated mixed numeric/Boolean outputs from one
shared stateful element, nesting, independent instances, fanout/unused ports,
explicit feedback/calendars, quality rollback, canonical source conflicts,
bounded migration and actual local HTTP authoring/revision/interchange. Native
IEC evidence retains original Program/expanded graph/ST/C/host/executable,
actual returned SymbolTable and output bindings before the first scan, plus
observed frames and process-reaping receipts. Native REAL precision and host
clock/quality assumptions remain distinct from portable binary64 behavior.

## Primary criteria and remaining gaps

Johnson Controls Controller Tool Help18.0, LIT-12011147, dated2025-10-06, original
PDF SHA256 `68935362c85cb1879dc033cc701115e8ea7c4ecb26748f21a9ceaf0454f82903`:
PDF43 describes modules with inputs/outputs; PDF224–225 lists named unit-qualified
interfaces; PDF905/Table572 publishes Boolean OnOff and numeric Effective Command;
PDF1278–1279/Table1036 publishes several damper commands; PDF1297/Figure162 shows
nested control/hybrid activity outputs including commands, state and diagnostics.
These criteria support reusable multiple output roles. They do not reveal native
algorithms, native Enum codes or a portable reliability encoding. The source is
[Controller Tool Help](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/18.0).

Retained ALC LogicBuilder help pages21767/25375/25377 and diagrams8829/8831 likewise
show separate Point name/Valid? roles and distinguish primary/secondary/locked
values. Their local extraction folder name is not a verified controller release,
and generic Studio good quality is not equated to those vendor roles.

Native JCI/ALC algorithms, Enum/reliability adaptation, hardware I/O allocation,
vendor packages, CAF compilation, controller transfers, physical safety and code
acceptance remain incomplete. No unchanged SDK or successful local host run
removes those gaps.

## Browser authority and native report boundary

The browser checks original response/archive bytes, supported profiles and named
port alias formulas, then binds adoption to its current source, draft generation,
mount and authority epoch. The canonical source/expanded hashes remain
server-reported provenance; the browser does not independently regenerate Python
canonical Program seals. These checks authenticate no server or physical device.

An explicit criteria/port-authority refresh, or a failed current catalog reload,
retires the portable session and clears history, values, forces and old aliases.
Unresolved version2 Activity authority gates portable stepping, scenarios and
pacing until the current executable bindings are accepted. Browsing a definition
with unchanged valid source does not itself transfer or recreate control state.

The additive native IEC binding report is enabled only by the original Program's
explicit exact-integer macros.version2 source. Arbitrary activity_expansion
metadata in an ordinary/version1 Program stays opaque: it neither enables new
report fields nor supplies native binding authority.

## Web workflow

Open **Macros**. A version1 editor retains the existing single-output library and
shows a separate migration card. Export the original project/archive first if
needed; the migration review binds its digest but is not an automatic saved
backup. Review the explicit rewrites, download the original review response,
then deliberately confirm Apply. Dismissing the review or confirmation preserves
the current source. Applying starts fresh local simulation with no transferred
time, state, history or forces and saves no project revision.

A version2 editor shows **Reusable activities**. Select internal blocks on the
Program wiresheet, enter an Activity name and create the reusable definition.
Keep root Input/Output blocks outside the selection. Choose a definition to see
its required inputs and each named output's type/unit, inspect its graph, place
an instance, export its original dependency-closed archive or edit on the
wiresheet with Apply/Discard. Used definitions cannot be deleted or silently
change port contracts. Version1 archive import opens an explicit promotion
review, with separate original archive/review/promoted downloads; it does not
silently merge a different library version.

The Program canvas renders one handle and value for each declared output. Wire
those exact named handles; selecting the Activity opens per-port values,
computed values and portable Hold/Release controls after current executable
port authority validates. The container has no single scalar value or force.
Criteria refresh resets local simulation and alias authority as described above.
Ordinary Save revision, undo/recovery, project JSON/ST/PLCopen/GraphML exchange
and root-output trends continue to use the editable hierarchical source.

Pending exports, mutations, definition reads and migration responses are guarded
by source/version/generation/mount ownership. Changing source, leaving the view,
explicitly discarding or migrating retires stale adoption, including old
single-output library callbacks. An identical-looking later source does not
restore an earlier request's authority. Original response/Blob downloads remain
separate from displayed numbers and formatted summaries; native or physical
control permissions are not granted by these authoring operations.
