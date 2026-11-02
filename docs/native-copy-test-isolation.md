# Native copy browser-test isolation

The legacy Boolean-copy and wire-source-copy browser specifications now use the
existing per-test application-server fixture. Each case seeds and checks its own
explicit state directory. The shared Boolean seed helper accepts an optional
directory and retains its previous default for callers outside these two suites.
No production source, interface, limits, retries, assertions or test deadlines
change.

The combined installed qualification for native Enum copies exposed the problem:
102 cases passed before a legacy wire fixture reached 128 active backups in the
runner's shared directory. Fixture creation failed before its UI operations and
three cases did not run. A separate fresh-state wire run passed all 28 cases;
the failed state and traces remain retained locally. Increasing the production
quota would have hidden the test dependency.

The same 106-case group is now exercised together against source and the already
qualified installed package. Each runner's global state is deliberately seeded
with 128 original backups, and a 129th capture is confirmed to be refused before
the browser run. The combined tests must pass while those original runner files
and manifest counts remain unchanged. Their own isolated servers retain the
original production quota.

Coverage includes both copy families, retained backup inspection and the new
Enum copies, source-specific drafts, navigation and stale replies, exact review
and artifact downloads, phone layouts and authored routed controller entry.
These are software tests using loopback protocol peers. They do not establish
site, Bluetooth or manufacturer compiler acceptance.
