# Original application readback qualification

This integration begins at `7eaf0efb` and retains PR #181 source `ed25361a` as an
ancestor. Original-image recognition, source/identity/status/settings checks and
append-only recovery proof remain unchanged from that feature.

Additional UI ownership keeps newer local work when an older receipt is read
back. A recovered result retires only its matching source capture and does not
claim the proposed change was applied. Native identity fields clear only for a
matching completed proposal; an unrelated capture, name or instance draft stays
available. The failed intent and result remain immutable alongside the distinct
`recovered_original` observation.

The focused backend run passes 244 tests, including original name/instance/point
recovery, partial-image/settings/status refusals, persistence, native timestamp
preservation and existing transfer profiles. Browser tests use actual authored
UDP backup/transfer/readback and an explicit authored point-table HTTP surface.
A peer command models recovery performed by another tool; the application then
reads it back. It sends no recovery application or extra restore. New cases cover
point names, controller names and instances, with a second older-receipt readback
after a newer capture/proposal is prepared.

The original UI reproducibly removed the newer point's source fields during that
second readback. Its failing trace/state remain retained. A first native identity
test also stalled before Apply on a whitespace-sensitive checkbox label; the
fixture now selects the established exact accessible checkbox role/name. The
original failed results remain retained, without changing deadlines or retries.

All 40 styles and three public metadata documents remain exact. Of 509 prior
test/support files, 507 remain unchanged; the authored peer and browser fixture
gain explicit recovery scenarios. Original dirty files retain their saved hashes.
These software checks do not independently establish the original author's
private field result, physical performance or a general restore capability.
Older separately recorded timeout and empty-response-accessor observations remain
unexplained.
