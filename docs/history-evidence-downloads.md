# Original history evidence downloads

The Device history workspace downloads the original JSON response bytes for
single Trend Log, Trend Log Multiple and Event Log reads and reopened local
captures. The parsed display report and its downloadable Blob come from the
same HTTP response and are stored together. Export performs no new field read
or capture lookup.

This matters because JavaScript parses JSON numbers into one numeric type.
Rebuilding a Python response with `JSON.stringify` changes `2.0` to `2`,
`-0.0` to `0`, and can change exponent notation or large decimal spellings.
Such a rebuilt report can fail its original SHA-256 seal, even when its browser
display looks similar. Native BACnet Real values are already rounded to their
wire precision; the download preserves that actual evidence without inventing
precision, normalizing it again, or generating a replacement seal.

Trend Log Multiple and Event Log retain their existing `evidence_sha256`.
Recompute it with SHA-256 over Python JSON encoded with `sort_keys=True`,
`separators=(",", ":")`, `allow_nan=False`, excluding only that seal field.
The existing capture summary hash covers the full report using the same JSON
settings. Single Trend Log retains that capture summary contract. No report,
capture format, stored seal, or native source bytes are migrated.

Read/load responses must identify the expected profile and source kind, a
bounded report, consistent request/target object identity, and the exact requested
capture ID when reopening. Single Trend Log read addresses must match the exact
submitted address; multi-channel and Event Log read operation IDs must match the
submitted operation. A malformed
JSON response, HTTP error, unrelated profile, wrapper, or different capture
cannot replace the displayed evidence. Query edits and capture selection clear
the prior document; a new read/load also clears it before waiting. Existing
generation and unmount guards reject late responses. Exports are disabled while
an operation runs and check that the owning panel remains visible and mounted.
Cancelled native reads can still download their completed partial evidence.

Display values and CSV are formatted views. JSON is the retained evidence
artifact. Saving a capture retains the server's existing immutable report; an
offline reopen reads that verified capture and retains the new load response
without contacting the controller.

Validation uses independently authored real UDP BACnet peers with integral Real
values, signed zero, small and large magnitudes, plus native Event Log values.
Python independently checks actual browser files against the original HTTP
bytes, evidence seals and saved-capture summary hashes. API tests check restart
and offline reopen. Browser tests cover partial cancellation, malformed/error
responses, wrong capture identity, query/capture invalidation and navigation.

The ordinary workspace Suspense boundary is keyed by the selected tab. Leaving
Device history therefore retires its component immediately, including when the
next workspace's JavaScript module is still loading. Without that key, React can
hide and retain the previous workspace; returning before the next module loads
can revive a pending capture and its download. The intentionally retained CAF
and CAF simulation workspaces use their separate existing boundaries.

Three deterministic regressions hold both an actual capture response and the
next workspace module, finish the capture while the loading fallback is visible,
then return before releasing the module. Each history profile must start without
the previous capture or export. These pass on Chromium and WebKit with pinned
React 19.1.1. This follows React's documented
[Suspense boundary reset on navigation](https://react.dev/reference/react/Suspense#resetting-suspense-boundaries-on-navigation).

These checks establish local serialization and capture integrity. Physical
controller support, native JCI application transfer and proprietary historian
formats retain their existing limitations.
