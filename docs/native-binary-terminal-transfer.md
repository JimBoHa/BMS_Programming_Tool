# Existing local binary terminal transfer

`FMT-NATIVE-BINARY-TERMINAL-001` adds explicit input action `binary-terminal` and
operation profile `native-local-universal-input-transfer/3`. It moves one existing
class-242 local universal binary input to a captured free universal terminal on
the same controller. It uses encoding-preserving local compiler profile 3.
Allocation, electrical configuration, polarity changes, dedicated BI terminals,
integral sensors, SA/IOM/cross-host moves and general native compilation remain
outside this profile.

## Observed configuration and compilation

The selected binary record requires the observed typed properties: Reference,
Active Text, Description, Device Type, Inactive Text, Object Identifier, Slot,
States Text index and Name. Optional Polarity and Unsigned32 COS Count/Elapsed
Active Time fields are admitted independently. Unknown/missing properties,
ambiguous host/occupancy, malformed multi-value framing and unsupported datatypes
have no configuration guard or field authority. They are not converted into an
analog scaling configuration. Polarity is retained as normal/reverse; the States
Text enumeration is retained as an index, without inventing electrical meaning.

The guard binds controller/root/format identity and all non-counter native
properties, including the previous terminal and recorded charset. Counters remain
historical values and may advance without changing the configuration guard.
Fresh compilation retains their actual current saved values. The candidate is
reopened after reapplying retained saved settings; any saved override that would
undo the requested binding prevents compilation before a field review or intent.

Only the existing Slot and Device Type payloads change. Charset, payload/tag
widths, other merged bytes, graph, identities and framing remain protected by
the existing independent compiler readback. Other input actions and their
operation/compiler profiles retain their previous contracts.

## API and field gates

`POST /api/bacnet/controller/native-application/input/binary-terminal/source`
inspects an immutable identity-matched retained capture. It verifies the exact
root name/model/instance and vendor 5, returns actual binary candidates and free
slots, and marks counter values historical. It performs no controller query.
The existing input copy preview/export routes accept the explicit typed action;
copies remain local and require the recomputed exact review seal before export.

The existing `/input/preview`, `/input/apply` and readback routes provide the
separately confirmed field path. Input preview uses the binary source and exact
published binary Object Identifier, name/description, Device Type, Slot, state
labels/index and optional polarity. Each reply must match the exact requested
object/property and route. A missing/unreadable/mismatched required publication
cannot create a review. Published runtime counters are not compared to a frozen
configuration value.

Apply retains all three typed confirmations, one-use review, exact target,
interface/identity/credentials, fresh source/directory, configuration/free-slot
guards, full native transfer and complete image/published readback. Profile,
action and compiler proof must pair exactly; cached body/options changes,
including numeric aliases, cannot promote/demote the review. Readback rechecks
the same explicit version pairing. Current saved binary configuration is typed
again before existing runtime-counter exceptions are accepted. A lost restore
acknowledgement or post-transfer publication mismatch retains uncertainty and
original evidence; reconciliation never repeats the download.

This delivery is a backend/API slice. Contextual binary controls, independent
recorded binary metadata/recovery and capability reporting are separate work.
Generic recorded receipts and original evidence remain available; older analog
terminal metadata does not claim to interpret binary profile 3.

## Verification and limits

Authored schemas cover ASCII/UCS-2, plain/gzip images, literal whole-image
preservation, counter changes, stale configuration, missing/unknown properties,
typed source/copy HTTP and zero-network local operations. Owned direct/routed UDP
controllers exercise full transfer and publication, every confirmation,
profile/compiler/body/options substitution, fresh/post-transfer counter advances,
saved-binding overrides and uncertain outcomes without replay.

Read-only retained VMA checks qualify actual binary guards, compiled profile 3
and native preservation; private source bytes and names stay outside Git. These
checks and the simulated field exchanges do not establish physical wiring,
binary electrical behavior, CCT/BTCVT acceptance or live-site controller approval.
No live-site, VM or Bluetooth operation belongs to this qualification.
