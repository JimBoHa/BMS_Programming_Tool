# Native restore and logical-root regression checks

Two authored protocol tests now drop actual UDP property responses after the
single end-restore commit, for both an instance change and a name change. They
exercise the actual readiness observer and identity/status readers. The silence
lasts beyond the former fixed delay and the fixture's short identity fallbacks.
The tests use the production 60-second readiness window and two-second poll
interval, retain the original short request deadlines, and impose an independent
ten-second test ceiling. Neither a controller command nor an application block
may be repeated. Every completed readiness attempt must remain in the receipt.

The same two tests fail on the implementation before readiness support: both
commit ACKs are validated, but identity readback remains unknown during the
silence. Current source and the independently installed package pass both cases.

Four independent native fixtures give the root a literal `8-41` reference while
its assigned Device instance changes from 5136 to 5336. Both compressed and
ordinary archives, and short and extended record framing, are covered. A
previous-instance recovery proposal must remain local, keep that logical
reference, preserve all nine saved settings during inverse compilation, and
leave the original receipt and backup unchanged. No field action is admitted
by a successful local proposal.

These checks preserve regression coverage for the separately implemented
[parameter storage](native-parameter-storage.md),
[previous-instance recovery](native-controller-instance-recovery.md) and
[post-restore readiness](native-restore-readiness.md) contracts. They do not
change a compiler, transfer service, journal, production deadline, dependency,
graphic or interface behavior. Mutation targets are authored loopback peers;
physical manufacturer acceptance and general native authoring remain separate.

The earlier readiness integration recorded an unconfirmed commit ACK before the
new readiness code executed. Its original pending receipt, state and logs remain
retained. A subsequent isolated pass does not explain that observation or count
as a repair. These focused regression checks also do not resolve the older
broader-run BACnet failures or establish a full-suite pass; see the separate
[software validation record](software-validation-2026-11-01.md).
