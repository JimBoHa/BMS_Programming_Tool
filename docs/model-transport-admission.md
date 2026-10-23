# Optional model-qualified hardware reads

The hardware workbench can qualify a survey against three complete JCI part numbers: `MS-FAC4911-0`, `MS-FAC2611-0`, and `MS-FAC3613-0`. This adds an optional transport check before an existing read. Generic hardware surveys, imported survey reports, their profile and seals, address validation, and ordinary mixed-network connections retain their existing behavior.

The source is *Metasys System Field Equipment Controllers and Related Products Product Bulletin*, LIT-12011042, edition 13.0, original PDF SHA-256 `3a65a6ffe84c8e453d814af07470638fd7a1b12965df52e859580a276d2386a3`. PDF 16 lists complete part numbers; PDF 22–24 describes their communications and terminations. [Official manual](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Metasys-System-Field-Equipment-Controllers-and-Related-Products-Product-Bulletin/13.0).

The FAC4911 part supports BACnet/IP or BACnet/SC on Ethernet and has an SA sensor port. It has no documented FC MS/TP interface. The other two parts support MS/TP or N2 on FC, with a separate SA bus. These are documented capabilities, not observations of the selected protocol. A six-pin sensor port does not establish an FC connection or arbitrary converter compatibility. Shortened native model text, a family prefix, a different suffix, or a case change does not select an exact part automatically.

Studio implements plain IPv4 and direct MS/TP adapters. BACnet/SC and N2 adapters remain unavailable. The first model-qualified profile admits direct IPv4 for the declared IP model, or direct MS/TP and an explicitly pinned IPv4-router/DNET:MAC path for a declared MS/TP model. A router's IP endpoint is distinct from its downstream controller's native transport. Generic routed addresses may have one through eight octets; this optional MS/TP profile qualifies one-octet remote MACs only. Other routed IP, bridge and proxy arrangements remain unresolved by this profile. Existing generic routed paths are not narrowed.

The declared model and current protocol are required for this optional workflow. Unknown identities or protocols produce a nonadmitted, unresolved decision. Unsupported profiles, unavailable adapters, incompatible paths and a missing or mismatched open interface also refuse a qualified read before it is queued. No connection, discovery, protocol toggle, write or power lease occurs during the pure review.

`GET /api/bacnet/hardware/model-transport/profile` supplies the separately hashed `studio-jci-model-target-transport/1` profile and schemas. Token-protected `POST /api/bacnet/hardware/model-transport/review` accepts:

```json
{
  "qualification": {
    "profile_sha256": "<current supported profile hash>",
    "model": "MS-FAC2611-0",
    "current_protocol": "bacnet-mstp"
  },
  "target": {
    "transport": "bacnet-ip",
    "address": "3001:7",
    "device": "device,123",
    "router": "192.0.2.10:47808",
    "dnet": 3001
  }
}
```

Here `transport:bacnet-ip` describes the client's existing IPv4 path through an explicit router; `current_protocol:bacnet-mstp` describes the operator-declared native controller link. Neither value is inferred from the other. The current open interface/configuration is captured separately. A review is a local snapshot, not a reusable command token or authorization to open a field interface.

Add the same `qualification` object as optional `model_qualification` on the existing `POST /api/bacnet/hardware/survey` request. Omit that field to use the original generic survey. The server recomputes the qualified decision before queuing the read and again before the worker runs. Pure preview also reuses the original serial-interface identity check, including refusal of the client's own station, so it does not claim admission for a target the existing reader would reject. The original survey guard still checks interface/configuration under the normal read path before its first request. No property, deadline, request pacing, fallback, source filtering, lock or cancellation rule is changed.

Only the owned workbench job receives `model_transport_admission` and `model_transport_observation`. Existing job GET/export retains these fields across restart. The underlying saved survey and its schema remain unchanged; imported survey contents cannot become admission authority. Declared capability/current protocol, implemented adapter, target/interface snapshot, and raw native Device/model/vendor/firmware observations remain separate.

An observation reports exact text match, missing text, or different unresolved text. A shortened native `Model_Name` is not promoted to a complete part number. An exact self-reported text match is not manufacturer authentication or physical identity proof. A persisted admitted snapshot describes the earlier decision; starting another qualified read always requires a fresh server decision against the active interface.

This transport-only profile does not add manufacturer-specific MAC limits to the existing address validators. Edition 13 documents controller-specific MS/TP/N2 address ranges; later modernization guidance differs for some N2 ranges and setup. Those facts do not authorize a protocol change. Engine support for FAC4911 has a firmware 9.0-or-later footnote and further engine limitations; this read profile establishes no native engineering or deployment compatibility.

Core/API and local UDP checks cover exact and unknown identities, explicit protocols, direct and routed paths, refusal before reads, changed interface admission, raw identity retention, original generic reports, job export/restart and unchanged generic workflows. The router test retains original UDP BVLC/NPDU/APDU frames from an authored loopback proxy and native BACnet service peer. It emulates the routed link; it is not a physical MS/TP or controller acceptance test.

`COMM-MODEL-001` is the bounded optional model/path admission feature. Broad `MF-be5f1e078a` remains partial. Other models, verified native aliases, SC/N2 clients, routed-IP/proxy profiles, firmware switching, BTCVT/SA electrical and bus compatibility, JCI native packages/compiler/CAF transfer, and physical commissioning remain separate gaps. No native JCI or physical acceptance follows from an admitted read.

## Web workflow

Connect → Hardware and input survey retains the ordinary generic workflow by default. Select **Qualify this hardware read by exact model and protocol** to open the optional workflow, then explicitly load the source profile. Enter a complete part number, including an unknown one when appropriate, and declare the currently selected native protocol. Documented model capability, the operator's protocol declaration and the implemented adapter are displayed separately. The three exact catalog models are suggestions, not observations or automatic model aliases. SC, N2 and unknown modes remain visible as unavailable or unresolved.

**Preview model-qualified target** reads local metadata only. The browser binds the supported profile and its content hash to the current declaration, exact selected target and open interface snapshot. A changed model, protocol, target, interface, refreshed profile, explicit discard or navigation retires current preview authority; delayed responses cannot restore it. A qualified survey remains disabled until a matching admitted preview exists. Starting it sends the current declaration to the existing backend survey, which independently recomputes admission before queueing and before the owned worker reads. No connection, scan or protocol switch occurs on opening this optional panel. A routed controller's native MS/TP link remains distinct from its IP router endpoint and DNET:MAC path.

Owned job details show the historical declaration/capability/path separately from raw native identity observations, including exact text match versus different unresolved text. These observations never enable another read and never authenticate installed hardware. Existing saved hardware survey schema, profile and seals remain separate. The existing job JSON download preserves the original server response Blob, including job-only qualification evidence; it does not reconstruct the file from browser numbers or replace a survey report. No native JCI compilation, application transfer or physical acceptance is added.
