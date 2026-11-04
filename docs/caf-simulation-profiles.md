# Native CAF saved simulation profiles

The **CAF simulation** workspace edits existing saved simulation values in a separate native CAF copy. It does not execute JCI control logic. It leaves ordinary program properties, native graph wiring, controller identities and unknown fields unchanged.

## Evidence and supported records

Johnson Controls documents [saved startup settings in Simulation mode](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/16.0.1/User-Interface/User-Interface-Concepts/Modes/Simulation?contentId=dOb1V7YbqtwzPCXG0SvfOg) and describes [startup values for inputs disconnected from physical hardware](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/14.0/Simulating-a-System/Simulating-a-System-Concepts/Simulation-Overview). Those manuals explain the workflow; they do not publish the native XML field encoding or establish that this editor's output is accepted by CCT/PCT.

The encoding was independently observed in the seven authorized private CAF examples. Four contain 72 `simulationProperty` records, all with native property identifier `3113`, on signal-block class version `1.0`. The other three contain none. The new folder's files duplicate the earlier sample corpus, so these are seven distinct files, not fourteen. No private CAF content is distributed with this implementation.

| Native class | Scalar representation               | Observed records | Editing                   |
| ------------ | ----------------------------------- | ---------------: | ------------------------- |
| 526, 527     | `float`, no scalar attributes       |               39 | Existing scalar text only |
| 530          | `boolean`, no scalar attributes     |               11 | Existing scalar text only |
| 528, 529     | `enum` with a native set identifier |               22 | Numeric code only in v2; read-only in v1 |

In particular, `simulationProperty id="3113"` and ordinary `property id="3113"` can coexist on an object. They are separate records. This feature changes only the former. Signal-block dictionary names are labels, not independent proof of the field's runtime behavior.

The public OCT [enum export script](https://github.com/thecontrolscompany/oct/blob/c1d76ba7d6a8f17ca089c4671fa3333e4eba43e2/server/src/scripts/exportFdbEnums.ts) identifies its source database as `FDB_Control_10_8___Firmware_12_0`. That source does not verify enum-domain compatibility with these Release Mode 10.1/10.2 CAFs. No domain is inferred from numeric ranges or unrelated enum sets. Version 1 consequently keeps Enum records read-only. Explicit version 2 permits the observed numeric representation without claiming membership, meaning or execution semantics.

## Profile and editing contract

`CafSimulationProfile` in `backend/bms_tool/caf_simulation.py` accepts CAF bytes or an existing `CafArchive`.

- `summary()` reports exact archive SHA-256, native records, per-type counts and read-only reasons.
- `export_profile()` produces `bms.caf-simulation-profile`, version 1 by default, bound to that exact source SHA-256. `CafSimulationProfile(content, profile_version=2)` explicitly adds numeric Enum copies.
- `apply(profile)` returns native CAF bytes and a change report. Every original record must occur once. Only each supported record's `value` field may change; reference, class/version, kind, property identifier, type, attributes, original text and all display/guard metadata must match.

Float replacements require native decimal text, finite float32 range, and no nonzero underflow to zero. Boolean replacements accept `0`, `1`, `false` or `true`. Valid number spellings are retained. New records, unobserved class versions, unknown attributes, opaque scalar markup, unknown types and unsupported XML encodings remain read-only. Empty and unchanged profiles return the original archive bytes exactly.

Profiles are bounded to 10,000 records and 2 MiB of compact serialized JSON, with reserved API/header space. Oversized metadata is rejected explicitly rather than truncating guard identities. The editor uses the CAF parser's actual XML token spans, copies ZIP metadata, reparses the result and verifies changed native values. The browser preserves drafts across workspace tabs, requires explicit discard before replacement/reset, and retires pending open/import/download responses when its workspace is hidden, the document becomes hidden or pagehide occurs. Returning does not revive those responses.

The API uses `GET /api/caf/{id}/simulation`, `GET /api/caf/{id}/simulation/profile`, and `POST /api/caf/{id}/simulation` with `{ "profile": ... }`. GET defaults remain version 1; add canonical `?profile_version=2` to request version 2 inventory or profile. POST explicitly dispatches only a known integer profile version and checks every source/record guard for that version. The response includes `X-Studio-Source-Sha256`, `X-Studio-Simulation-Version` and `X-Studio-Artifact-Sha256`, plus the separately qualified request proof below; the browser verifies these and hashes the actual downloaded bytes. The audit records source hash/change count, and version 2 adds version and unverified Enum scope. The cached source stays unchanged.

## Version 2: saved Enum numeric codes

`FMT-CAF-ENUM-SIMULATION-001` permits existing saved `simulationProperty 3113`
Enum leaves on actual class 528/529, class version 1.0. Empty attributes or only
an original opaque `set` reference are supported. The canonical text is unsigned
base-10 integer `0` through `4294967295`: signs, leading zeroes, decimal/exponent
spelling, labels and non-string JSON values are refused. That is a representation
bound, not an allowed-state domain. Each version 2 Enum record explicitly retains
`enum_semantics_verified: false` and `maximum_code: 4294967295`.

A single observed CDATA wrapper is preserved for this explicit Enum profile.
Split CDATA, comments/child markup in the value, unknown classes, versions,
attributes or noncanonical original text remain read-only. Ordinary Enum default
copies and all version 1 Float/Boolean behavior retain their existing span rules.
Mixed supported Float, Boolean and Enum edits retain unrelated XML and ZIP
metadata, object order, ordinary defaults and original archive bytes on no-op.

The existing Program → Simulate → CAF simulation inputs table opens version 2.
Legacy version 1 imports fetch and validate the exact-source version 1 baseline,
then carry only its permitted Float/Boolean drafts into version 2; all Enums
retain original values. Full metadata, readonly and complete-record guards remain
required. Invalid raw drafts can be exported as JSON for later correction; native
CAF export validates every changed value. No field connection, live operation,
native execution or semantic Enum mapping is added. Local input scenarios still
use their separate version 1 Float/Boolean input contract.

## Local input scenarios

Named, persisted value/quality trajectories now have a separate [local CAF input scenario workflow](caf-local-input-scenarios.md). It previews input stimuli only and uses this existing editor to prepare scalar startup copies from all-good frames. It does not add native CCT execution or encode native trajectories/quality.

## Verification and remaining dependencies

The original version 1 qualification included fifty module tests and two API tests, including all seven private CAFs. They verify 50 editable records, exact ordinary-property retention, enum/opaque preservation, byte-exact no-ops, stale-profile refusal, float bounds, alternate namespace prefixes, misleading XML comments, resource limits and unchanged original files. Three browser tests verify profile import/export, native CAF readback, explicit draft guards and pending-download suppression. The explicit version 2 checks additionally cover both Enum classes, UInt32 boundaries, CDATA, mixed edits, complete guards, source/version/artifact admission, legacy adaptation, lifecycle retirement and installed application parity. All seven authorized private originals are checked read-only; all 22 observed saved Enum leaves are independently copied with ordinary properties retained. No private programs are distributed. These checks validate the archive editor, not execution of JCI algorithms.

Native JCI completion still requires a matching authorized CCT/PCT installation, release-specific Function.xml/FDB definitions, controller packages and an accepted serialization/transfer interface or independently verified equivalent. It also requires independent vendor save/reopen/simulation and target acceptance evidence. See [the native toolchain investigation](jci-native-research-2026-10-19.md).

The existing ALC Integration Builder source depends on licensed WebCTRL/EIKON to generate and compile equipment logic. A complete independent ALC equipment compiler/runtime remains unverified. Honeywell Spyder/CIPer requires its matching Niagara modules, target-specific component/compiler metadata, licensed execution context and loader; generic BOG archive preservation or standard BACnet object access supplies none of those proprietary execution semantics. This saved-JCI-value feature does not remove those target-specific dependencies.


## Request-bound simulation artifacts

`FMT-CAF-SIMULATION-REQUEST-PROOF-001` adds
`X-Studio-Simulation-Request-Sha256` to both version 1 and version 2 exports.
A response for an earlier value proposal can have the same source/version and
an internally correct artifact hash. The browser now refuses that stale reply
before downloading or marking the current draft exported.

The descriptor uses compact UTF-8 JSON with these exact top-level keys in this
order: `entries`, `format`, `source_sha256`, `version`. Each ordered entry contains
`property_id`, `ref`, `value`, in that order. Values retain exact text or null;
record order, Unicode, escapes, numeric spelling and profile version are not
normalized. Only known integer versions, lowercase source SHA-256, bounded record
counts and valid Unicode scalar strings are accepted. The descriptor plus header
reserve stays within the existing 2 MiB limit. No values or metadata are truncated.
The browser and backend independently compute SHA-256 over those exact bytes.

The backend checks the complete original profile, metadata, readonly records and
native ranges before issuing proof. Display metadata stays under those existing
exact-source guards; the request descriptor grants no additional edit authority.
Missing, wrong or earlier-proposal proof preserves the current draft and leaves
it unexported. Current draft ownership and lifecycle retirement remain required.
Legacy scenario consumers can ignore the additive header; ordinary top-level CAF
Save keeps its distinct clicked-snapshot behavior.

The earlier-reply case is reproduced against the retained installed pre-change
application: code `3` accepted a reply containing code `2`. The regression now
refuses that same replay even when source/version/artifact headers are internally
consistent. Authored checks also cover no-op/changed exports, both versions,
reordered/empty profiles, mixed native values, Unicode and escaping, typed bounds,
missing/wrong proof and actual installed UI/module parity. This is request/artifact
correlation for a local copy, not a manufacturer compiler, authenticated signature,
native execution or physical acceptance result.


The browser's scenario startup path now uses the same captured-profile verifier
and separately [checks the chosen input frame](caf-local-input-scenarios.md#selected-frame-startup-copies)
before requesting a copy. Version 1 scenario semantics and version 2 Enum editing
remain separate. Other API consumers keep the additive-header compatibility rule.


[Shared archive attribute preservation](caf-archive-preservation.md) now also
retains recorded zero ZIP attributes for changed version 1/startup copies. Version
2 retains its earlier behavior. Profiles, native values, source/request proof and
byte-exact no-ops remain unchanged; affected edited artifact hashes change with
the corrected metadata.
