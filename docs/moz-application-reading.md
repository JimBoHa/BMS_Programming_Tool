# Read recognized applications published as MOZ Files

Program → Controller application can select published `.moi` and `.moz` BACnet
Files whose captured bytes match the installed tagged-MOI reader. Extension
matching is case insensitive. This closes an inconsistency with the existing
connected native backup adapter, which already accepts either File-type label.

The extension admits a File as a candidate; it is not a binary-format contract.
The same bounded tagged-record parser still validates the actual contents,
including supported single-member gzip framing. Unknown, incomplete, trailing or
excessive content remains rejected. No rename, decompression guess or conversion
creates an editable program. The existing native identity/name compiler and its
separate backup/transfer workflow retain their own stricter contracts.

JCI's Controller Tool Help 18.0, LIT-12011147, PDF page 368, names both MOI and MOZ
generation errors in transfer troubleshooting. That passage does not document
binary equivalence; support here is determined by actual recognized contents.

## Acquisition and preservation

The existing source-pinned File service retains the original bytes and metadata
before parsing. An unsupported `.moz` payload therefore leaves a complete opaque
capture available for independent inspection. Parsing neither rewrites the
original nor starts a backup-state session. Standard published-File acquisition
uses reads only.

If several `.moi`/`.moz` candidates are published, the application lists them and
requires an explicit File choice. It does not select by filename ordering,
extension preference, controller model or a claimed newer version. Optional
configuration-files absence still falls back to actual object-list discovery.
Recorded capture reuse retains the exact existing Device, endpoint, route and
connector checks.

## Verification and boundary

Actual UDP checks exercise mixed-case `.MoZ`, optional-property fallback, mixed
File selection, plain/gzip wrong-format rejection with original-byte retention,
and refusal to reuse a capture for another target. Browser checks repeat the
existing blocks/wires/configuration/live-value workflow for MOI and MOZ labels
against independent local File peers, including a changed later sensor value.

`FMT-MOZ-READ-001` records this read-only format-label extension. The wider JCI-02
loss-preserving editable representation remains partial. These authored software
checks do not qualify every vendor MOZ variant, general native logic editing,
application transfer, a complete controller backup or physical acceptance.
