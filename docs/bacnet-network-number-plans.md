# BACnet network-number engineering plans

**Connect → Network-number engineering plan** reviews an offline inventory of
operator-declared BACnet network attachments. No interface opens, address resolves,
network scan runs or controller changes occur. The feature does not select an
available number or renumber equipment.

## Declare identity before comparing numbers

Each attachment has a required **internetwork/domain key** and an optional
**physical-network key**. These exact, case-sensitive keys state topology chosen
by the operator. They are not generated from network numbers, router addresses,
IP subnet masks, discovery responses or device instances.

A physical-network key represents one numbered BACnet network. Such a network can
include multiple physical segments connected by bridges/repeaters, or BACnet/IP
participants on multiple IP subnets. Give an engine integration and its
corresponding router side the same domain and physical-network keys. Distinct
actual networks require distinct keys. Leave the physical key blank if this
relationship is unknown.

For example, two router ports declared on `domain-a` / `backbone` with number
`1001` are consistent. Two distinct declared networks `backbone` and `remote-bus`
in `domain-a` cannot both use `1001`. A separate, unrelated internetwork
`domain-b` can reuse that number. The planner never combines domains or networks
because endpoint strings look similar. If separate internetworks will later be
joined, update their domain declarations and review the combined inventory.

## Workflow

1. Open the panel, name the plan and record its engineering context.
2. Add network attachments. Enter their domain, known physical-network key,
   configured/planned number, medium and role. Optional endpoint and port keys
   identify an operator-declared configuration endpoint; they are not connection
   instructions. Engine integrations can use their integration/trunk identifiers.
3. Select **Generic BACnet numbering** or the explicitly scoped **JCI Release 15
   Remote Field Bus** policy. State whether that assignment is new, existing or
   unknown. Choosing a brand or medium does not select a release policy.
4. Apply each attachment editor change to the plan. Edit/remove existing rows as
   needed. Unapplied edits disable review/export and remain visibly separate.
5. Declare inventory coverage only after including the intended networks. For the
   R15 site-wide comparison, include remote buses, local trunks and BACnet/IP
   networks in the same declared domain. The checkbox records an assertion; it
   does not verify inventory completeness or merge unrelated domains.
6. Run **Review network numbers**. Findings identify their domain and exact
   attachment records. Edit declarations and run a fresh review.
7. Export the plan JSON before leaving Connect. Import reopens that portable plan
   after a reload or on another computer. Export a separate review JSON to retain
   its complete submitted plan, source bibliography, findings, time and hashes.

Drafts stay in the current Connect view; this feature does not keep server-side
named plans or silently recover a draft after navigation. Unsaved changes trigger
a browser unload warning. New/import operations ask before replacing changed
content. They do not alter the current draft when validation fails.

## Findings and limits

| Finding                                              | Meaning within the submitted declarations                                                                                                          |
| ---------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| `number-on-distinct-networks`                        | One domain and number identify distinct declared physical networks.                                                                                |
| `network-number-mismatch`                            | The same declared physical network has inconsistent numbers, including engine/router-side mismatches.                                              |
| `endpoint-port-conflict`                             | One declared domain + endpoint + port has conflicting physical-network or number assignments. Different ports/routers on one network remain valid. |
| `physical-medium-mismatch`                           | Attachments with the same explicit network key declare contradictory media.                                                                        |
| `unknown-network-number`, `unknown-physical-network` | A required comparison cannot be established; unknown does not become zero or a new network.                                                        |
| `incomplete-endpoint-port`                           | Only half of an optional endpoint/port pair is known.                                                                                              |
| `route-observation-only`                             | An advertisement alone cannot prove physical identity, medium, configured endpoints or complete inventory.                                         |
| `not-a-physical-network-number`                      | `0` is local addressing context and `65535` is a global destination, not an assigned numbered physical network.                                    |

Assignable numbered networks use integers **1–65534**. The schema also retains
`0` and `65535` so an erroneous existing declaration can be reviewed explicitly;
negative values, values above `65535`, floats, numeric strings and booleans are
rejected. A blank number is JSON `null`, not zero.

The reviewed JCI **Release 15 Remote Field Bus** profile flags `2000` and `65000`
for explicitly **new BACnet/IP or MS/TP** assignments. Existing uses receive a
context note because the manual describes embedded networks using these values.
An unknown existing/new context or unsupported/unknown medium stays incomplete.
These numbers are not universally illegal BACnet values. The restriction is not
applied automatically to generic assignments, other JCI releases or other
manufacturers.

A review is `conflicts` when an error exists, `incomplete` when an unknown or
coverage gap remains, and otherwise `no-conflicts-in-declarations`. The last
status does not authenticate topology, certify a network or prove a number is
available outside the submitted declarations. Incorrect domain/network keys can
hide or invent conflicts. Source hashes identify reviewed materials; they do not
authenticate operator data or installed manufacturer hardware.

## Exact sources and portable evidence

The source profile records document identities, reviewed sections, artifact kind,
URLs and PDF-byte hashes:

| Primary source                                                                                                                                     | Reviewed sections                     | SHA-256                                                            |
| -------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------- | ------------------------------------------------------------------ |
| [ASHRAE 135-1995 errata, 1999-09-07](https://bacnet.org/wp-content/uploads/sites/4/2022/08/135-1995-Errata-9-7-1999.pdf)                           | 6.2.2.1, PDF page 3                   | `5e0c5a707ba360fe10d1d72396088aec34688118974b4d3739788fec52ad2c8e` |
| [NISTIR 6392, November 1999](https://bacnet.org/wp-content/uploads/sites/4/2022/06/NISTIR-6392.pdf)                                                | 6.1, 6.4, 6.6.2; PDF pages 26, 35, 39 | `2e15fa8a34e1f36a93deb848a775664c83e1c0254b862af09768ad464319f80f` |
| [JCI LIT-12011034 Release 15.0, 2026-09-29](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/MS/TP-Communications-Bus-Technical-Bulletin/15.0) | PDF pages 10, 12–13                   | `18c323a65edec4fe29120bab29d38303bf57e9b21fe1b1a108eb597c077aee37` |

The [CEG installation settings](https://docs.johnsoncontrols.com/bas/r/Johnson-Controls/en-US/CEG-Installation-Guide/C/Operation/BACnet-MS/TP-settings)
and [CWCVT 1.1 BACnet settings](https://docs.johnsoncontrols.com/bas/r/Johnson-Controls/en-US/CWCVT-Wireless-MS/TP-Converter-User-Guide/1.1/Detailed-procedures/Viewing-settings-and-diagnostics-from-a-browser/BACnet-settings)
also confirm their configurable network-number range as 1–65534. These device
settings do not broaden the R15 reservation profile.

A plan uses `bms.bacnet-network-number-plan`, version 1, with the exact reviewed
source-profile SHA-256. Import, validation, review and export reject stale profile
hashes. There is no automatic migration or silent source rebinding. Review the
current sources and construct a current plan explicitly when the profile changes.
Unknown JSON fields and unsupported versions are rejected.

A review uses `bms.bacnet-network-number-review`, version 1. `plan_sha256` covers
the normalized submitted plan. `content_sha256` covers the complete review except
that hash field itself. Both use UTF-8 JSON with recursively sorted object keys,
compact separators, Unicode characters retained and nonfinite numbers forbidden.
Attachment order remains significant. Findings retain exact record IDs; their
stable IDs hash the individual finding content. Reports are separate evidence
files, not importable plans or instructions to configure equipment.

Limits are 512 attachment records, 2 MiB per plan, 80-character ASCII identity
keys, 160-character names, 2000 characters of notes per attachment and 4000 plan
note characters. The submitted record count, string lengths and numeric domain
bound review work. No source documents or private field data are committed.

Editing the plan or attachment editor invalidates its displayed review. Imports
also clear prior reviews. Pending responses cannot replace newer edits/imports;
closing or unmounting the panel suppresses delayed downloads. Review exports run
a fresh source-checked calculation rather than downloading a stale table.

## API and checks

| Route                                    | Operation                                                  |
| ---------------------------------------- | ---------------------------------------------------------- |
| `GET /api/network-number-plan/catalog`   | Reviewed source profile and empty plan                     |
| `POST /api/network-number-plan/validate` | Validate `{ "plan": ... }` and return normalized plan/hash |
| `POST /api/network-number-plan/review`   | Review the exact guarded plan and return sealed evidence   |

POSTs inherit the session-token, origin and loopback protections. No route takes
a field connection, credentials, scan range or apply flag.

```sh
.venv/bin/python -m pytest tests/test_network_number_plan.py
cd web
npx playwright test tests/network-number-plan.spec.ts
```

Authored tests cover numeric boundaries, domain separation, shared physical
networks through multiple routers, engine/router and endpoint-port conflicts,
unknowns, route-only evidence, R15 scoping, finite bounds, token guards, exact
hashes, real API JSON reopen and delayed/stale browser responses. They perform no
field operations.
