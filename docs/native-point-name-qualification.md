# Native point-name integration qualification

This review starts from `a39d7770` and preserves the original point-name feature
commit `4b357e73` as an ancestor. It retains the controller-centered point
Configuration workflow and the existing compiler, native transfer, saved-setting
preservation and published-name verification contracts.

The additional integration binds previews to the requesting operation and exact
source/edit, binds Apply receipts to that operation and review, and binds
readback/export to the selected original receipt. Earlier retained readback
cannot clear newer unfinished work. Visibility and task transitions retire write
authority and late downloads. A 32-source workspace limit refuses new work
instead of evicting another point's draft; explicit discard leaves durable
backups and transfer history intact.

Software qualification completed:

- 216 focused backend tests covering parameters, native preservation, transfer,
  point names, API guards, actual UDP startup and logical-root recovery.
- 22 browser checks across Chromium and WebKit, with no retries. Authored UDP
  peers perform the native transfer and readback; point inventory/property tables
  use an explicit authored HTTP surface. These are simulated controllers.
- Substituted operation, capture, snapshot, record and profile responses are
  refused. An uncertain published-name result retains its draft and is resolved
  through explicit readback without another application transfer.
- Late exports produce no download after navigation. A current export retains
  the original response bytes. Desktop and phone screenshots and overflow checks
  retain the existing layout.
- Production TypeScript/Vite build, Ruff and diff checks pass. All 40 prior styles
  and three public metadata files remain exact. Of 503 prior test/support files,
  502 remain exact; only the authored native peer gains the point-name profile
  and explicit publication/readback control. The original checkout's 31 dirty
  files, status and diff retain their saved hashes.

The original UI reproducibly accepted a substituted Apply operation and cleared
the draft; its failing trace is retained privately. The first new negative test
checked before the native response finished; it was corrected to await that
response before judging ownership. A later first combined browser run passed all
11 Chromium cases but correctly blocked WebKit after the final uncertainty case
left its intent unresolved. That fixture now resolves its owned intent through
real readback before ending. The original logs, state and traces remain retained;
neither production protection nor request deadlines were relaxed.

These focused checks do not explain earlier separately retained BACnet timeout
failures, qualify physical controllers/BTCVT, or complete arbitrary native logic
and hardware authoring. See [the point-name scope](native-point-names.md) and
[the existing validation record](software-validation-2026-11-01.md).
