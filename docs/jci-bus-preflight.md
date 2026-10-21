# JCI bus address and topology plans

**Connect → JCI bus address and topology plan** reviews offline declarations for
physical FC and SA buses. It does not open an interface, scan a trunk, set an
address, inspect installed wiring or change a controller. The separate
network-number planner concerns internetwork numbering; this feature has no
network-number dependency.

## Author a plan

1. Add each physical bus once. Choose the exact reviewed manual profile and FC or
   SA type. Use an explicit, case-sensitive physical bus key, declare segment
   keys and record inventory coverage. Similar names, IP addresses or network
   numbers do not merge buses. A false bus identity can conceal real conflicts.
2. Add each device **connection** to its bus and segment. The same controller's
   FC and SA interfaces are separate records with separate addresses. Enter the
   exact model, explicit generation, role, MAC, wired/wireless mode, switch128
   interpretation and planned EOL setting. Leave unknown facts unknown.
3. Add cables between two connections on the same bus. Select ordinary terminal
   trunk, ordinary 6-pin SA modular cable, sensor service accessory, FC repeater
   bridge or unknown. Length and straight-through pinout are declarations.
4. Apply editor changes, then review. Applying one editor preserves other
   unapplied editor changes. Review/export stays disabled until all changes are
   applied or cleared. Removing a bus/device requires removing its dependent
   declarations first; records are not silently reassigned.
5. Export plan JSON before leaving Connect. Import reopens it after restart or
   on another computer. Export a separate fresh review with the complete plan,
   source catalog, findings, UTC time and hashes. There is no server-side named
   plan store. Browser unload warns about changed/unapplied content.

Physical bus keys are immutable in the editor after creation, preserving device
references. To change an identity, construct an explicit new plan/file with all
references consistent. Import validation rejects dangling references.

## Reviewed address rules

MAC duplication is checked **within one declared physical bus**, including its
FC repeater segments. The same MAC on different buses is permitted. MAC `255`
is broadcast, not a device address. Blank MAC is `null`, never zero. Integer
bounds are `0..255`; numeric strings, floats and booleans are rejected.

The reviewed manuals distinguish host, manager, tool, display and subordinate
roles. Address `0` is the fixed SA host address; the FC supervisor description
states a default of `0`, so a nondefault FC host remains unresolved rather than
being declared universally illegal. Tool/display reservations are `1` for FIT,
`2` for MAP/CWCVT and the named wireless converter class, and `3` for local
displays. Ordinary manager roles use `4..127`. Subordinate/sensor roles belong on
SA, with model-specific reservations in `198..219`. A reserved range is not a
pool available to arbitrary subordinate devices.

The Metasys R15 FC profile separately asks whether an NCE integral controller
reserves `4`, and whether ZFR1810 coordinators reserve `120..127`. Unknown context
remains unresolved when relevant. These conditions are not inferred for the FX
profile or other wireless generations.

The narrow exact model catalog recognizes:

- `FX-PCG2611-0`, `FX-PCG2621-0`, `FX-PCV1615-0`, `FX-PCV1630-0` as the reviewed
  legacy controller family; `FX-PCX3711-0` and `FX-PCX3721-0` as expansion I/O.
- `MS-VMA1615-0` and `MS-VMA1630-0` as the reviewed legacy VMA family.
- `NSB8BTN040-0` and `NSB8BTN240-0` only with the explicitly declared
  `refreshed-2025-12-08` generation for the reviewed sensor service-port exception
  and `199..206` address profile.
- `TL-CWCVT-0` for the reviewed converter role/address, and `NS-ATV7003-0` for
  the handheld balancing-tool fixed address `198`.

Legacy controller/I/O switch checks require the explicit `legacy-dip128`
generation. Switch128 selects mode; it is never added to the MAC. Its required
setting on the wired device connection differs from wireless operation. The SA
host's fixed address is independent of the controller's upstream FC mode switch.
Sensor address switches are not interpreted as legacy controller wireless mode.

Unknown model suffixes, generations, FIT/display hardware variants, supervisory
host variants, other sensors, CGM/CVM rotary devices, repeaters and wireless
coordinator configurations retain unresolved findings. Role-based address rules
do not establish exact hardware compatibility or manufacturer-authenticated
identity. Selecting an I/O model cannot make it an SA supervisor.

## Graph and EOL scope

The graph detects disconnected components, cycles and ordinary trunk nodes with
more than two cable neighbours. Segment membership is explicit. Ordinary cables
cannot bridge segments. FC repeater bridges need two declared repeater-side
nodes in distinct segments; they are excluded from ordinary segment branch
counts. Exact repeater identity, cascade/loading capacity and electrical behavior
remain unresolved.

SA is a single private segment with one host and no repeaters. Ordinary modular
and screw-terminal trunk connections cannot be mixed. The controller's ordinary
6-pin modular port does not create a multi-device daisy chain. The reviewed
6-pin connection requires straight-through pinout and a maximum 30 m cable;
missing facts remain unresolved.

A separate exception recognizes one **refreshed NS8000 sensor access-port to
TL-CWCVT-0 accessory leaf**, with explicit matching model/generation/roles. It is
not counted as an ordinary trunk branch or mixed trunk connector. Multiple
accessories or downstream chaining through that service leaf fail the exception.
Unreviewed claimed service stubs remain unresolved; they are not silently
approved or treated as proven ordinary trunk branches. Arbitrary RJ45/RJ12
adapters and the sensor's controller-programming/balancing functions are not
validated by the presence of an access port.

FC EOL declarations are compared with each ordinary segment's endpoints and
interior nodes. SA host fixed-ON termination is the documented minimum; the
host-only arrangement is retained as acceptable, with two ends preferred.
Unverified interior SA termination needs exact device/wiring review. The feature
does not measure termination resistance, shields, bias, power, wire gauge,
length, noise or bus timing.

Results separate **address**, **topology** and **engineering coverage**. They can
show no address/graph conflicts while overall status remains incomplete. Device
counts are reported, but exact host/device/COV limits, total cable specifications
and power/loading budgets remain unresolved in this profile. A clean declaration
graph is not wiring or electrical certification. Unknown manual profiles do not
receive release-specific topology approval. Metasys R15 and FX segment limits
are separate: the FX2024 bulletin describes three segments on page 8, but page 14
also lists FX80 with 32 segments beside a two-cascaded-repeater/three-segment
statement. More than three FX segments therefore remains unresolved pending
exact host/repeater documentation; neither a universal three-segment limit nor
approval for 32 segments is inferred.

## Sources and evidence

| Reviewed primary artifact                                                                                                                              | Sections                       | SHA-256                                                            |
| ------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------ | ------------------------------------------------------------------ |
| [Metasys LIT-12011034 Release 15.0, 2026-09-29](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/MS/TP-Communications-Bus-Technical-Bulletin/15.0) | PDF 18–21, 23–26, 29–32, 39–40 | `18c323a65edec4fe29120bab29d38303bf57e9b21fe1b1a108eb597c077aee37` |
| [FX LIT-12011670, 2024-12-11](https://docs.johnsoncontrols.com/bas/r/Facility-Explorer/en-US/FX-MS/TP-Communications-Bus-Technical-Bulletin)           | PDF 10–12, 14–22, 25–28        | `30b55a915954c78a05ecea598ce1890494629ff78451660a2f440785774c2605` |

The FX cover date was read directly; a legacy download filename says 2022-09-07
but contains these same 2024-12-11 PDF bytes. The profiles do not infer other
releases from filenames.

The supplemental [NS8000 refreshed bulletin](https://docs.johnsoncontrols.com/bas/r/Johnson-Controls/en-US/NS8000-Series-Network-Sensors-Product-Bulletin-Refreshed-Models/Overview),
its technical specifications/selection charts (2025-12-08), and the
[handheld balancing-tool specification](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Handheld-VAV-Balancing-Tool-Catalog-Page/Handheld-VAV-Balancing-Tool/Handheld-VAV-Balancing-Tool-Technical-Specifications)
(2018-06-01) were reviewed through primary publisher extraction. The combined
reviewed capture hash is
`89688cc647251a30cf3170bb760c0b1a2c5882100e3ed86a965882e3b351a9f8`.
This is an extraction-capture hash, **not PDF bytes**. Proprietary source documents
and captures stay outside Git.

Plans use `bms.jci-bus-plan`, version 1, with an exact source/model catalog hash.
Stale catalogs, unsupported versions, nonfinite numbers, extra fields, duplicate
IDs/links, self-links and inconsistent references are rejected. Limits are 32
buses, 16 declared segment keys per bus, 256 device connections, 512 links and
2 MiB per plan. Identity keys are bounded at 80 ASCII characters. Cable parser
bounds are not supported engineering ratings.

Reviews use `bms.jci-bus-review`, version 1. Canonical UTF-8 JSON retains Unicode,
sorts object keys and uses compact separators with nonfinite values forbidden.
`plan_sha256` covers the normalized plan; `content_sha256` covers the review
except its own hash field. Array order is retained. Hashes identify declarations
and reviewed artifacts, not physical truth or manufacturer authenticity.

Editing any plan/editor field invalidates the review. Delayed validation/review
responses cannot replace newer input; newer imports supersede old requests.
Closing/unmounting suppresses delayed downloads. Review export recalculates from
the current exact source-checked plan.

The API provides `GET /api/bus-preflight/catalog`,
`POST /api/bus-preflight/validate`, `POST /api/bus-preflight/review`, and the
`/export-plan` and `/export-review` POSTs. Exports preserve authoritative server
JSON bytes, including integral float spelling such as `2.0`; client-side parsing
and reserialization would invalidate the content seal. POSTs accept
`{ "plan": ... }` under the normal session-token, origin and loopback guards.
There is no apply/scan/write endpoint.

```sh
.venv/bin/python -m pytest tests/test_bus_preflight.py
cd web
npx playwright test tests/bus-preflight.spec.ts
```
