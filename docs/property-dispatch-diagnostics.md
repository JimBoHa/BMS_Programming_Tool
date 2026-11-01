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

## Focused Calendar/Schedule trace

In the selected controller's **Schedules → Read diagnostics**, enable **Include one-property Schedule trace**. Explicitly select the Calendar/Schedule in the inventory form, then enter that same object and choose one of the properties read by this inventory. Weekly and exception arrays require one index; index 0 observes the native array count. Other properties use no index. Calendar and Schedule property sets are validated separately. The diagnostic endpoint `/api/bacnet/schedules/read-diagnostics` accepts the unchanged inventory request nested under `request` and an explicit `trace_focus` with `object_id`, `property` and `array_index`.

This runs the ordinary inventory exactly once. Only the chosen property obtains phase observations; earlier inventory reads cannot exhaust its 256-event/64 KiB independent trace. No discovery, follow-up query, retry, background recording or native timeout change is added. If an earlier identity check fails, cancellation precedes that property or the selected array index does not exist, the trace contains zero observed reads. This does not establish that the property was absent or that a packet was sent. The core report's request count still describes the whole inventory, while the trace count describes only matching observed reads.

The original core report, seal, cache, property sizes and edit eligibility remain unchanged. The envelope includes its explicit focus and exact original export bytes with SHA256. **Download original Schedule diagnostic bundle** saves the original envelope Blob; **Export exact schedule evidence** saves its exact embedded core bytes. The browser checks focus, report/operation association, full target/route and byte digest before accepting the pair. Form, selected controller or interface changes retire displayed results and pending downloads before paint, including a return to the same target. Reopening a retained report retrieves core evidence only; traces remain transient until explicitly downloaded. A diagnostic rendering failure returns the unchanged core body with the explicit unavailable header and no repeated read.

### Optional owned UDP callback observations

Enable **Include owned UDP callback observations** under the one-property Schedule trace to request this additional view. It defaults off. The same diagnostic endpoint accepts the strict optional Boolean `include_udp_ingress`; the envelope binds that requested scope, and available trace metadata records `udp_ingress_requested`. A requested scope does not guarantee a retained observation: inspect the trace state, events and gap counters. Source/form/interface changes invalidate this pair and its downloads as before.

The existing ready local IPv4 provenance owner accepts at most eight simultaneous request observers. It retains its original callback and native frame/context handling. No additional socket is opened, no query is sent and no native acceptance, source check, timeout or retry rule is changed. The registration applies only while the chosen property owns its wire span. The PointStatus endpoint and ordinary read paths leave this optional observation disabled.

`owned_udp_callback_enter` records bytes at that owned local socket's UDP callback, before the pinned SDK creates its asynchronous native server-dispatch task. Events contain observed peer/local endpoints, original datagram length, bounded prefix and separately bounded full-payload hash where available. Unrelated and malformed datagrams can appear. Temporal presence is not a matching transaction response; the original native source/object/property/index validation remains authoritative. A reflected local datagram can now be observed even when the native server discards it before the multiplexer. The local tests demonstrate this exact pinned SDK behavior with actual UDP packets.

This is one owned local callback during one request span, not all host/network UDP, packet capture at the physical interface, physical IP destination, socket transmission, router delivery or device processing latency. The separate POSIX broadcast socket is outside this observation. Seeing an ingress event without a later matching candidate does not alone locate a native failure. Earlier historical captures cannot be reconstructed. Shared-socket tests emulate the pinned Windows contract locally; they do not constitute physical Windows or controller acceptance.

The existing trace bounds are unchanged: 64 KiB, 256 events, 32 packet-prefix attempts of 512 bytes and a 256 KiB aggregate full-payload hash budget. Optional UDP events share those diagnostic bounds; they never consume native property/report budgets. Exhaustion clips diagnostics and retains gap counters. Observer setup/callback/cleanup failures are diagnostic gaps; unavailable listener capacity leaves the normal native read running. Cancellation, interface close and normal retirement remove only the owned registration. Another active observer remains registered, and retired spans/collectors cannot accumulate later packets. The bounded work can affect observation timing; zero overhead is not promised.

### Integration with native editing

The focused Schedule and optional owned-UDP observations coexist with the native
archive/effective compiler and guarded Real/Boolean/default/wire transfer paths.
The Schedule request alone owns its observer registration. Ordinary native reads
leave it disabled; neither the optional registration nor a diagnostic envelope
grants a transfer capability, changes saved-value preservation or authorizes a
restore. Source-bound Program drafts and durable recovery receipts remain owned
by their existing workflows. Integration is qualified with authored peers and
browser tests, without site or Bluetooth traffic.

### Source41 reference failure remains unresolved

Source41 (`191254f47274d36fe9fb47a635c3f97c23c7119d`) recorded 4,888 passes, one failure and one intentional skip. The failed signed primitive case lacked `schedule,1 / list-of-object-property-references` (property 54, no index), invoke 13. Its preserved original capture SHA256 is `3c1c90f1f8b6be79cde7bc0930c20ea952c61222814bf83096f193e6206d6f81`. It recorded a handoff after 0.122834 ms, completion after 212.815042 ms under the unchanged 0.2 second request bound, no matching candidate and no source-filter rejections. The other 27 property reads succeeded. Those observations do not establish socket transmission, peer receipt, all UDP arrivals, host-load cause or a native stack defect.

The current-main signed case passes with its original 0.2 second bound; this is a new baseline observation, not a cause or repair of the historical failure. New direct/routed authored-peer cases deliberately drop that exact reference reply and confirm incomplete capture, unchanged source bytes and refusal of editing. Focused handoff/callback evidence now makes a future occurrence more inspectable. The frozen15 exception failure, Source41 reference failure, later invoke 55 failure and historical String Schedule restart failure retain their distinct unresolved causes. Native routed-transfer time budgets do not explain or repair these Schedule reads.

The broader regression during this addition retained 376 passes and one fixture setup error in the existing weekly-write suite. Its untraced acquisition lacked `schedule,1 / exception-schedule[1]`, invoke 21, under the original 100 ms bound (110.57625 ms observed completion). The peer recorded that request without an exception, but no matching candidate was retained. No write occurred. The saved original failure SHA256 is `8798bf202884c485ddfbb78fbea66f6f94cfb4e2778a026cb7230299015112f1`. The new focus-filter branch was not reached because no trace collector was enabled. This does not explain the missing reply; the cause remains open under `IDEA-SCHED-ACQUISITION-DIAGNOSTIC-002`. New diagnostic-case success must not be described as a completely passing broader regression.
