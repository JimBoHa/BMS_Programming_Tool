# Native property dispatch diagnostics

The shared read-only native property reader retains `request_diagnostics` in each property receipt. Calendar/Schedule inventory, PointStatus and other callers using this reader export those fields with the original report and its evidence seal. Diagnostics add no discovery, queries, retries or background polling.

The receipt records the existing request timeout, local monotonic elapsed milliseconds at the owned native confirmed-service dispatch handoff, its UTC observation time, completion time, total elapsed milliseconds, whether a matching transport candidate was retained, and source-filter rejections during that read. The timeout still includes native preparation. Neither its duration nor the native stack timer is changed by these diagnostics.

A handoff observation means preparation reached the guarded downstream native call. It does not prove a UDP socket transmitted a packet, a router forwarded it, or a controller received it. A matching transport candidate is independently checked by the existing source/object/property/index and native decoding rules before the property becomes accepted evidence. Local elapsed times do not measure device processing latency. Absolute UTC times remain local observations; elapsed values use the event loop's monotonic clock.

The socket/interface pin is checked again at the handoff. Missing replies retain a timeout with the observed handoff and absent receive candidate. Incomplete native Schedule context remains ineligible for offline editing and native preview; diagnostics do not make it complete.

The original frozen15 full regression recorded one missing exception-schedule element while testing the signed primitive domain. Its saved capture confirms the timeout and correct refusal of incomplete context, but contains no actual send/receive trace establishing the cause of that missing reply. That original failure remains preserved and unresolved; new deterministic missing-reply cases and later passing runs do not rewrite it.

## Opt-in point-status phase trace

In **Connect → Native point status**, select **Include diagnostic trace for this read** before inspecting selected points. The checkbox starts no operation. Unchecked reads retain their existing endpoint and response. The opt-in endpoint is `/api/bacnet/point-status/read-diagnostics`; it accepts the same `PointStatusRequest` and calls the same native read exactly once.

The diagnostic endpoint returns `bms.native-read-diagnostic-envelope/1`. Its `core_report_json` is the original UTF-8 body produced by the existing point-status export operation for the resulting report ID. `core_report_sha256` binds those exact bytes. The core report, evidence seal, report cache, property-size limits, request/byte budgets, completeness and eligibility rules receive no diagnostic fields. The export is a local lookup, with no additional controller requests. The original read, export and profile endpoints remain unchanged.

The browser verifies the core-body hash and operation/report association before displaying the pair. **Download original diagnostic bundle** saves the authoritative HTTP response Blob. **Export exact point evidence** saves the exact embedded core bytes. Browser display formatting is separate; neither download reconstructs native numbers or re-seals evidence. Changing the selected interface/source/form, navigating away or reopening another report retires the displayed pair. A diagnostic-rendering failure may return the original core response with `X-Studio-Diagnostics: unavailable`; the browser requires this explicit header and does not retry the read.

### What phases establish

`studio-readproperty-phase-trace/1` observes the request's existing native exchange and scoped multiplexer handler. Events include preparation/wait entry, exact native APDU handoff bytes, downstream call entry/return/error, incoming multiplexer bytes, candidate classification, owned future callback/await phases and exchange/read retirement. Handoff encoding uses the pinned BACpypes3 `ConfirmedRequestPDU.encode`, which creates a new PDU rather than mutating the dispatched request.

Candidate reasons distinguish unsupported/short BVLC, network messages, unrelated APDU/invoke/service/source, matching candidates rejected by their pinned BVLC/next hop/ingress, inspection exceptions and retained matching candidates. An unrelated frame is passed to the original handler. A rejected matching candidate follows the existing suppression policy. Diagnostics never decide protocol acceptance or consume another owner's callback.

These observations are downstream of the actual UDP callback. The pinned SDK creates an asynchronous server-dispatch task there; it may discard a reflected frame or catch an exception before the multiplexer runs. Consequently, this profile is **not all UDP ingress**, socket-transmit proof, physical IP destination, router delivery or device processing latency. Unrelated traffic seen during the request is labelled as such and does not become response evidence. The nominal wait-deadline reference is observed before the existing wait wrapper; it is not the exact native timer firing time. Existing timeout and retry policies stay unchanged. Opt-in observation performs bounded local work and does not promise zero timing overhead.

Each callback closes over its own read span. Request context does not rely on being inherited by an independently scheduled UDP callback. Observer failures are diagnostic only; native handlers retain their original behavior. Spans and the collector retire in `finally`, including cancellation/interface change. Later callbacks cannot append to the frozen trace or revive a transaction. Traffic and callbacks after retirement remain outside visibility.

### Independent limits and storage

A trace has an independent 64 KiB encoded limit, at most 256 events and 32 packet-prefix attempts of 512 bytes. Full-payload hashing has a separate 256 KiB aggregate budget and a maximum eligible packet size of 65,507 bytes. Packet records retain original lengths, prefix/hash completeness and explicit dropped/truncated/omitted counters. Exhaustion clips or drops diagnostics, never native core bytes, properties, reads or eligibility. No existing native report budget is enlarged or borrowed.

The HTTP wrapper has its own bound allowing quoted core JSON plus the independently bounded trace. It can omit diagnostic content or fall back to the unchanged core response; it never truncates or re-seals core evidence. Trace data is request/browser memory only. There is no new persistent library, database, background recorder, polling or automatic recovery. Export a diagnostic bundle before leaving the view; reopening an existing retained point report retrieves its original core evidence only.

### Original failures and validation scope

The original frozen15 missing exception response and the later legacy routed effective-period invoke55 failure remain preserved and unresolved. The invoke55 receipt contained a native handoff timestamp and no matching received candidate, but no failed outbound packet, peer request/error list or late-callback trace. Zero source-filter rejections did not establish zero UDP traffic. This new profile cannot reconstruct that missing evidence or claim a cause/fix.

Verification uses local literal direct/routed UDP peers, original core-export comparisons, exact handoff bytes, dropped/unrelated packets, preparation/observer failures, cancellation/interface change, other-owner preservation, scoped handler retirement and diagnostic-only resource exhaustion. Physical JCI devices, Bluetooth and unrestricted packet capture remain unverified. This is an extension of COMM-DIAG-001, not a new manufacturer diagnostic capability.
