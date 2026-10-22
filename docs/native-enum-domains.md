# Native state domains and offline enum mapping review

This focused profile addresses part of **MF-3fc6a30927**, binary/multistate enum
mapping validation. It adds explicit native BACnet state metadata to the
[point status inspector](native-point-status.md) and a separate offline
operator mapping editor in Connect. Neither workflow changes a controller or
converts/deploys a CAF/CCT program.

## Read native metadata

Select **Read native binary and multistate domain metadata** before inspecting
selected points on one exact Device. The existing direct or explicit routed
plain-IPv4 identity checks, source pinning, finite operation and cancellation
apply. Loading the panel, reopening reports or leaving this option off performs
no additional metadata reads. There is no discovery, polling or reference
traversal.

* Binary Input/Output/Value retain Inactive_Text for code **0** and Active_Text
  for code **1**, using native BinaryPV. A code outside 0/1 remains invalid raw
  evidence; no truthiness or Boolean coercion substitutes for it.
* Binary Input/Output also read native Polarity. Reverse polarity never swaps
  the observed codes or labels. Unknown Polarity remains unknown. Standard
  BinaryValue declares no Polarity property in the pinned class, so this
  inspector does not issue that read.
* Multistate Input/Output/Value retain native Unsigned Present_Value and
  Number_Of_States. Numeric validation is **1..N** only when a positive bounded
  native N was actually read. An unresolved count never becomes a guessed
  domain, and State_Text count is not substituted for Number_Of_States.
  Decoder-accepted values beyond the unsigned32 profile stay invalid typed
  evidence; large codes never pass through browser-rounded JSON numbers.
* State_Text uses index 0 for its observed count followed by explicit indexed
  reads. A count mismatch, unsupported/native rejection, decode failure,
  timeout, truncation limit or missing label remains visible. Duplicate or
  blank labels do not merge numeric codes or generate mappings.

The default label-index limit is 32 per point, explicitly adjustable to 1..256.
Native metadata uses a maximum 256 bytes per canonically escaped JSON label;
larger labels remain untruncated in their original property evidence while the
compact metadata label is unavailable. All underlying native property/tag/wire
bounds remain in force. The operation still permits 16 points, 512 requests,
15 seconds total, 1 second per property and a 2 MiB report; high label limits
can exhaust that finite budget and produce partial results. A 384 KiB report
reserve covers bounded metadata duplication when the option is selected.
No automatic continuation or retry occurs.

Native metadata and completed State_Text indexes survive a cancelled partial
inspection in the retained report. Reports remain session memory only; exact
point-evidence export preserves original identities, per-property outcomes,
native types, code/label/polarity evidence and the canonical report hash.
Sequential reads are not an atomic state-domain guarantee. Native object labels
do not establish a JCI Enum Set ID, electrical wiring behavior or portable enum
binding.

## Review an operator mapping

The **Enum mapping review** panel works offline. Enter a source and target
namespace/domain ID, unique state IDs, strict integer codes and known or unknown
labels. A declared integer domain accepts codes -2,147,483,648..4,294,967,295;
the optional BACnet numeric rules additionally require exactly 0/1 or the
complete declared 1..N range. These remain operator declarations, not a binding
to a read native point. State/domain identity is retained exactly; blank IDs,
Boolean, floating-point and string code coercion are refused.

Enter every source-to-target code row explicitly. Label similarity never fills
or changes rows. A blank target remains unmapped. Review reports:

* incomplete/duplicate domain codes or state IDs, unknown source/target codes,
  duplicate source rows and all missing deterministic mappings;
* target codes unreachable from the source, separately from source totality;
  optional full target coverage is an explicit policy;
* many-to-one information loss. It is invalid by default and requires an
  explicit lossy policy plus nonblank rationale; no meaning is silently merged;
* known input-code probes, unmapped/unknown source values and explicit unknown
  probes (`?`). Unknown inputs never acquire a default numeric code.

Invalid domain declarations produce no resolved state-ID mapping evidence or
successful probes. Ambiguous IDs/codes never select the first matching state as
though its identity were established.

Domains and mapping rows are bounded to 256 each, with up to 256 probes. Large
native-looking 1..N declarations are checked with bounded arithmetic and a
32-code missing sample, not a loop over billions of states. Detailed findings
reserve 96 error and 32 warning slots, with full severity/code counts and an
omission count; a flood of label warnings cannot hide a later error. Canonical
source plans are bounded to 2 MiB and reports to 4 MiB.

Review exports preserve the normalized operator source plan, code and state IDs,
labels, datatype rule, policy/rationale, probes, findings and profile rules.
Separate SHA-256 seals identify the source plan, rule profile and full review.
Both exports recompute the current review and require its expected seal. Draft
changes and navigation discard delayed replies/downloads. The browser saves
the exact authenticated HTTP response bytes.

Export a reviewed plan to reopen it later. Import accepts strict UTF-8 JSON with
no duplicate keys, nonfinite constants, unknown fields or unbounded input; the
imported declaration requires another explicit review. Original input bytes
and normalized source have separate hashes. Nothing is auto-saved, applied,
bound to a native object or restored as a network operation after restart.

To independently verify an exported review, remove only `review_sha256`, then
hash UTF-8 Python `json.dumps(body, sort_keys=True, separators=(",", ":"),
allow_nan=False)`. The other seals hash `source_plan` and `profile_rules` in the
same canonical form. A valid declared table does not prove semantic equivalence,
native/portable binding or executable conversion.

## Source criteria and remaining scope

Primary reviewed manual: Johnson Controls
[Controller Tool Help 18.0, LIT-12011147](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/18.0),
PDF pages 1580–1581, Table 1313, local reference DOC-68935362c85c.
Its binary-to-multistate table relates **named Enum Sets**. It does not provide
the numeric BACnet or portable codes needed to execute a conversion. Some
listed target sets contain an extra state, so a two-state source does not imply
bijective coverage of a target. This feature does not invent numeric codes or
copy a proprietary mapping table into the app.

The pinned BACpypes3 0.0.110 primary `object.py`, `basetypes.py` and
`primitivedata.py` supply the exact standard object/property datatypes used in
native reads. Existing local CAF hardware-definition Enum Set parsing remains
separate from this operator declaration schema.

This completes **COMM-ENUM-001** as a bounded read/review profile; broader
MF-3fc6a30927 remains partial. Verified JCI Enum Set identities and native code
bindings, cross-format executable lowering, native program compiler/transfer,
other transports, controller firmware acceptance and semantic equivalence
remain separate work. Independent real direct/routed UDP, API and browser
tests use only isolated loopback peers. No field device, physical MS/TP trunk,
BTCVT adapter or manufacturer-specific program service was contacted.
