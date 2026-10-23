# Native property dispatch diagnostics

The shared read-only native property reader retains `request_diagnostics` in each property receipt. Calendar/Schedule inventory, PointStatus and other callers using this reader export those fields with the original report and its evidence seal. Diagnostics add no discovery, queries, retries or background polling.

The receipt records the existing request timeout, local monotonic elapsed milliseconds at the owned native confirmed-service dispatch handoff, its UTC observation time, completion time, total elapsed milliseconds, whether a matching transport candidate was retained, and source-filter rejections during that read. The timeout still includes native preparation. Neither its duration nor the native stack timer is changed by these diagnostics.

A handoff observation means preparation reached the guarded downstream native call. It does not prove a UDP socket transmitted a packet, a router forwarded it, or a controller received it. A matching transport candidate is independently checked by the existing source/object/property/index and native decoding rules before the property becomes accepted evidence. Local elapsed times do not measure device processing latency. Absolute UTC times remain local observations; elapsed values use the event loop's monotonic clock.

The socket/interface pin is checked again at the handoff. Missing replies retain a timeout with the observed handoff and absent receive candidate. Incomplete native Schedule context remains ineligible for offline editing and native preview; diagnostics do not make it complete.

The original frozen15 full regression recorded one missing exception-schedule element while testing the signed primitive domain. Its saved capture confirms the timeout and correct refusal of incomplete context, but contains no actual send/receive trace establishing the cause of that missing reply. That original failure remains preserved and unresolved; new deterministic missing-reply cases and later passing runs do not rewrite it.
