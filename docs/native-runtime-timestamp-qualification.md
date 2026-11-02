# Native runtime timestamp qualification

This integration begins at `f65f4f88` and retains original PR #179 commit
`4d1da844` as an ancestor. Its compiler/runtime changes remain unchanged. The
additional work qualifies the complete transfer, review notice and native test
fixture without changing production guards or request deadlines.

The previous merger injects an Unsigned property 16 with value 1700000000 into
the authored binary record. The corrected merger retains that epoch only in
original-storage evidence, leaves the application timestamp absent and still
merges count 1234, elapsed time 5678 and the other seven settings. A comparison
against the exact previous merger source reproduces that schema difference
without controller traffic.

Qualification includes 238 focused backend tests and 22 Chromium/WebKit checks
without retries. New actual UDP instance and name transfers verify all nine
application settings, the omitted timestamp, original backup bytes, one restore
and explicit readback without another restore. The browser peer also carries a
binary timestamp slot alongside its point and live-flow fixtures; the actual
preview displays the retained-runtime notice. Point inventory tables retain their
explicit authored HTTP surface. These are software peers, not physical devices.

The first backend run passed 218 cases and stopped when client and simulated
controller both selected UDP port 53067. The existing self-target guard refused
the operation before capture; the retained database has zero transfer intents
and events. The fixture selected free ports independently during asynchronous
setup. The corrected allocator explicitly excludes the peer port and keeps any
rejected socket bound while selecting a different candidate. A deterministic
collision case checks that behavior and socket cleanup. Production self-target
protection, request/review deadlines and retry policy remain intact. Original
failure state, JUnit and log remain retained; this does not attribute older
separately recorded timeout failures to that collision.

All 40 styles and three public metadata documents remain exact. Of 508 prior
test/support files, 504 remain byte-identical; the four reviewed exceptions add
timestamp cases, distinct test-port allocation, authored peer data and the notice
assertion. Original dirty checkout files retain their saved hashes. Broader
timestamp encodings and physical acceptance remain unqualified; an already
present unqualified application timestamp still refuses compilation. Preserving
an original epoch does not restore the controller's historical runtime event time.
