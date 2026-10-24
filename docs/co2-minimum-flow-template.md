# Authored CO2 minimum-airflow reset activity

`CO2-MIN-FLOW-001` provides a reusable version-two activity with five required
numeric inputs and two named outputs. Its 38 ordinary blocks and 57 wires share
one Delay. Users can inspect and edit the generated graph, wire instances,
simulate live endpoint changes, deliberately save revisions and exchange the
original source using existing activity and interchange workflows.

This is an airflow request for an appropriately engineered downstream airflow
control stage. It does not produce a percent damper command, select a physical
output, measure outdoor airflow or establish a VAV primary-air minimum.

## Primary source and authored substitutions

The primary reference is Johnson Controls **Controller Tool Help 18.0**,
LIT-12011147, dated 2025-10-06, actual PDF pages 736–737, Tables 350–351.
The original PDF SHA256 is
`68935362c85cb1879dc033cc701115e8ea7c4ecb26748f21a9ceaf0454f82903`.
The corresponding [official manual](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/18.0)
describes five live inputs, an editable control activity, endpoint conditions
and last-reliable-value behavior. The application table names AHU mixed-air
single-duct applications.

The source uses a position-looking present-value name and description while
declaring its output and flow endpoints in **cfm**. This template preserves the
flow interpretation. The separately described percent-position reset is not
substituted for it. Eight applicable original edition passages agree on the
800/1000 ppm and 425/825 cfm defaults; those passages remain reference evidence,
not a claim that all editions share an identified native algorithm.

The source does not define a numerical in-band curve, invalid endpoint policy,
complete startup rule or input reliability granularity. This implementation
explicitly authors a bounded linear curve, a configuration diagnostic and a
committed hold policy. Existing whole-scan rollback does not reproduce native
connection/default/module-reliability mechanics. Native JCI algorithms, package
and release bindings, CAF compilation/transfer and physical deployment remain
unfinished under the broad partial criterion `MF-74ca5999ab`.

## Required live ports and defaults

| Input | Type and unit | cfm-profile default |
|---|---|---:|
| `co2` | number, ppm | 800.0 |
| `co2_reset_a` | number, ppm | 800.0 |
| `co2_reset_b` | number, ppm | 1000.0 |
| `flow_low` | number, chosen flow unit | 425.0 |
| `flow_high` | number, chosen flow unit | 825.0 |

Each input remains required when an activity is instantiated. Definition
defaults support standalone simulation and do not create implicit instance
wires. All five values can change through the ordinary runtime inputs.

| Output | Type and unit | Meaning |
|---|---|---|
| `minimum_airflow` | number, chosen flow unit | Selected committed airflow request |
| `reset_configuration_valid` | Boolean | Endpoint configuration accepted on the last successful scan |

The diagnostic is not current sensor quality, module reliability, plant enable,
occupancy or proof of ventilation. A successful invalid configuration commits
`false`; a failed transaction retains the preceding diagnostic, which can be
`true` with positive airflow.

Construction choices are `flow_unit` (`cfm` or `L/s`) and the five typed numeric
defaults: `co2_default`, `co2_reset_a_default`, `co2_reset_b_default`,
`flow_low_default`, `flow_high_default`. Defaults must be finite and have
ordered CO2 endpoints and nondecreasing flow endpoints. Strict numeric fields
reject Booleans and strings. Integer JSON numbers deliberately become typed
floats. Signed zero and scientific values remain in the source; opaque parent
parameters and metadata are not number-projected.

## Runtime curve, invalid configurations and memory

The authored endpoint domain is 0–1,000,000 ppm for A and B, and
0–1,000,000 L/s equivalent for L and H. The cfm cap is exactly the existing
binary64 computation `1000000 / 0.4719474432`. These are authored domain bounds,
not manufacturer module limits or a physical safety envelope.

The graph compares each original endpoint with a safe clamped copy. It requires
`B > A` and `H >= L`. A flat flow pair is valid. Zero or reversed CO2 spans,
descending flow pairs and out-of-domain endpoint values are invalid. A finite
portable measured CO2 sample can lie outside the band; it is saturated before
subtraction.

Using safe copies A, B, L and H:

```text
denominator = (B > A) ? (B - A) : 1 ppm
sample = max(A, min(B, co2))
fraction = clamp((sample - A) / denominator, 0, 1)
candidate = max(L, min(H, L + fraction * (H - L)))
selected = configuration_valid ? candidate : previous_valid_flow
next previous_valid_flow = selected
```

All evaluated dependencies remain bounded even for an invalid configuration.
Raw extreme endpoint inputs are clamped before arithmetic. The safe denominator
uses one ppm for a nonpositive span. The ordinary engine evaluates dependencies;
this graph does not rely on a Switch suppressing an unsafe branch. No epsilon,
new Divide guard, core arithmetic rule or compiler option is introduced. The
final Min/Max keeps a valid candidate between its admitted flow endpoints even
if intermediate rounding adds a small increment.

With documented cfm defaults, samples 700, 800, 900, 1000 and 1200 ppm request
425, 425, 625, 825 and 825 cfm. Good-quality invalid endpoints retain the prior
selected airflow and publish false configuration-valid. Before any valid
configuration, a first successful invalid scan selects zero in the chosen flow
unit. Repair resumes calculation immediately. No reset input, enable, timer or
ventilation guarantee is invented.

Bad quality, type, nonfinite input, clock or arithmetic failure follows existing
whole-transaction rollback: time, memory and all outputs retain the preceding
transaction. Before any successful scan, existing Python empty outputs and
native zero observations remain distinct. Neither is preseeded into a physical
controller. Only the unforced internal selected flow feeds Delay. Both public
output aliases are terminal, so a portable terminal force does not rewrite this
graph's held airflow. This is graph-specific, not a general activity isolation
or native internal-port force claim. Deliberate forces and manual edits can
leave authored bounds.

## Flow units and finite-width qualifications

The existing conversion factor is `CFM_TO_LPS = 0.4719474432`. Metric defaults
are derived from 425/825 cfm with that factor; no unrelated rounded US/SI pair
is treated as an exact conversion. Only the two flow defaults and graph flow
units change. CO2 values, the chosen source and parent clock remain unchanged.
Positive scaling retains typed negative zero. Conversion revalidates the target
choices and refuses a nonzero endpoint becoming zero or a previously nonflat
pair collapsing to equal values. Bounds and tolerances are never widened.

For example, the smallest nonzero binary64 cfm value underflows when multiplied
by the factor. The distinct cfm pair `1.063` and `1.0630000000000002` maps to one
binary64 L/s value. The guarded units endpoint refuses both operations, leaving
the old draft available. Exact round trips and arbitrary cross-width trajectories
are not promised.

“Any finite measured CO2” describes the portable calculation domain. The
unchanged NativeIEC host rejects inputs outside ±3e38 and nonzero inputs that
round to REAL zero before submitting a native scan. The generated graph does
not bypass those admission rules. Native REAL rounding can also coalesce two
otherwise valid CO2 endpoints. The native graph then selects its safe fallback
and holds flow with false validity while portable arithmetic can still calculate
a true-valid result. This is recorded as an expected numeric boundary, not
reported as semantic identity or concealed by a tolerance change. Adjacent
representable near-min-normal endpoints and a smallest-subnormal internal span
are included in representative execution evidence; they do not prove all
finite-width or physical configurations.

## Source-bound API and deliberate adoption

The API prefix is `/api/activities/templates/co2-minimum-flow`:

| Method and suffix | Behavior |
|---|---|
| `GET /catalog` | Copied criteria, profile hash, typed schemas, cfm/derived metric defaults and flow caps |
| `POST /preview` | `{program, choices}`; validate the reusable definition and supplied activity2 parent without saving |
| `POST /export` | Same request plus `format: review` or `bundle`; original canonical bytes, filename and `X-File-SHA256` |
| `POST /import` | Same request plus current `profile_sha256` and `reviewed_parent_sha256`; recheck before the unchanged activity2 merge |
| `POST /units` | `{choices, flow_unit, profile_sha256}`; source and converted choices with their hashes, or a refusal |

Authenticated mutation routes use the existing application session. Requests
require an explicit version-two parent; version-one libraries use the existing
deliberate migration workflow. Unfinished ordinary parent graphs remain allowed.
Public helpers freshly revalidate already-typed mutable request objects and
choices; in-place mutation cannot bypass local constraints.

Preview preserves two exact Program descriptor paths: `program` and
`bundle.library.definitions[0].program`. The report binds choices, profile,
definition, Program, archive and actual validated parent identity, revision,
canonical digest and declared scan. Parent binding stays outside the reusable
definition, so repreview after importing unchanged choices has the same reusable
definition/archive identity. Conflicting same-ID canonical source refuses instead
of replacing an existing definition. Opaque prior parent source remains intact.

This template has no timing parameter or separate clock. A parent scan of
0.5 or 3.0 seconds is valid; the definition's ordinary `1.0` metadata does not
create an independent scan or a fixed-scan admission gate. Reviewed source binding
is stateless provenance, not a persisted review, server compare-and-swap,
authentication, field permission or physical identity proof. The template API
does not instantiate, autosave a revision, open field networking or acquire a
power lease. Users separately adopt, instantiate, wire, edit, simulate and save.

## Verification scope

Focused core and actual local HTTP checks cover all live ports, documented
endpoints and authored midpoint, flat bands, bounded extreme samples, invalid
configuration startup/hold/repair, quality rollback, shared-state forces and
independent instances. They also cover strict/mutated typed choices, both flow
units and real conversion refusals, unchanged parent atoms, explicit source
descriptors, original review/archive byte headers, deliberate activity edits,
revision save/reopen and four interchange formats.

Representative unchanged MatIEC/native C execution retains the actual returned
compiler/symbol tables, editable and expanded Programs, ST, generated C, host,
executable, decoded observations and worker reaping. The coalesced-endpoint
reference mismatch is explicitly expected and retained. Host range/underflow
refusals do not count as submitted native scans. Original numeric profiles,
deadlines, SDK files and tolerances remain unchanged.

There is no native JCI activity identity, Enum/reliability/application-tree
binding, controller package, CAF compile/download or native internal-port force
acceptance. Physical sensor calibration, measured OA flow, downstream equipment,
ventilation sizing/population/area calculations, G36/Title 24 compliance and
field/Bluetooth commissioning remain separate unfinished work.


## Web workflow

In a deliberately initialized or migrated version-2 activity library, the **CO₂ minimum-airflow template** card exposes five standalone numeric defaults and an airflow unit. All five ports remain required when an instance is placed. The parent’s actual declared scan is displayed; the card does not impose a separate 1-second clock. The ordinary graph and typed input/output table are visible before import, including the airflow request and last-committed configuration diagnostic.

The unit selector requests the guarded conversion endpoint. It adopts converted airflow defaults only after the response matches the current choices, conversion factor, sign, profile and owned source epoch. CO₂ defaults remain unchanged. A refusal, nonzero-to-zero underflow, endpoint collapse or stale reply leaves the prior unit and draft intact. Newly authored float controls preserve typed negative zero and scientific notation without projecting opaque Program parameters or metadata into JavaScript numbers.

**Preview CO2 minimum airflow** requests one source-preserving review. The card verifies the supported profile, exact parent identity/revision/clock, five input and two output contracts, both original Program descriptors, and the reviewed 38-block/57-wire topology. A deliberate import button adds that reviewed definition to the current library through the existing canonical-conflict service. It does not create an instance, wire ports, save a revision or perform network/controller work. No second confirmation dialog is required for this reversible edit. Adding and wiring an instance, editing its ordinary definition, simulation, interchange export and saving use the existing activity workflows.

Downloads preserve the original preview response Blob and original server-produced review/archive bytes. Review/archive exports must pass their actual byte-SHA header and current reviewed source checks before saving. These digests are server source bindings, not manufacturer authentication or native compatibility evidence. Existing opaque parent values may be re-emitted with different equivalent exponent spelling; the import guard does not emulate Python canonical numbers or claim arbitrary lexical aliases. The server rechecks the supplied canonical parent before merging, while the client binds the response to its owned current source and reviewed definition.

Draft edits, unit conversion, criteria reload, parent changes, explicit discard and unmount retire downloaded-review authority and pending adoption. Late or ABA responses cannot replace the newer editor or trigger a download. The on-card qualifications distinguish invalid good-quality configuration hold from whole-transaction fault rollback, terminal output force from retained internal flow, portable finite samples from unchanged Native IEC admission, and airflow requests from percent damper position or physical ventilation proof.
