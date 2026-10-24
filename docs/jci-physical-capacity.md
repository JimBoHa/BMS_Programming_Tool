# Exact JCI physical capacity matrix

Connect → Hardware survey → **Exact physical capacity matrix** opens a local
catalog only when requested. Select a reviewed exact product or enter an unknown
model explicitly. Declare signal families and integer quantities, then review
whole-device physical count fit. This does not connect to a controller.

The first profile contains 32 explicitly selected products: all 24 ordinary
PCX/CH-PCX/IOM ordering variants in the reviewed expansion tables, four PCG
controllers and four existing legacy PCV/VMA profiles. It is not every JCI
product or generation. Prefixes, missing suffixes, regional substitutions,
smoke-control suffixes and other variants do not inherit a profile. Matching
normalizes only outer whitespace and case; original supplied model text remains
in the review.

## Physical pools and scope

A universal input is one physical input with alternative voltage, current,
resistive or maintained-contact modes where documented. Legacy VAV universal
inputs in this profile omit current mode. Universal outputs share voltage,
current and FET modes. Configurable outputs share voltage and triac modes;
they do not acquire current mode. Relay contacts belong to one relay output.
An integer max-flow calculation finds a possible pool-count distribution,
including overlapping UI/BI contact and BO/CO triac demand. A greedy assignment
could incorrectly consume all universal channels before considering dedicated
ones. The result exposes unmatched demand and an illustrative count witness.

**A count witness is not a terminal assignment.** Every catalog pool retains
`terminal_identifiers: null` and numbering status
`not-established-by-this-count-profile`. Terminal numbering requires independent
model-specific wiring evidence. Existing narrow survey input numbering and CAF
terminal-edit profiles remain unchanged. Integrated VAV pressure sensing and
actuators are listed separately; they are not spare external channels.

Counts describe an entire model. The calculation does not subtract occupied
survey points or promise spare wiring. It does not approve loads, voltage
references, source/sink behavior, resistance curves, pulse duty/frequency, power,
jumpers, relays, network topology, controller/expansion-host compatibility,
firmware, a native hardware definition or a CAF allocation. `count-mode-fit`
means only that declared signal-family quantities fit documented physical pools.
Unresolved source conflicts remain visible even when counts fit. An unlisted mode
is unreviewed by this profile, not proof of physical impossibility. The reviewed
UI rows list maintained-contact mode; pulse-counter matching is limited to
dedicated BI rows, without a frequency or duty-cycle approval.

The count matrix retains these primary-source conflicts rather than choosing
an electrical rating:

- FX -2 relay rows say 24 VAC in the detailed bulletin matrix but 240 VAC in
  ordering information. No relay load/rating approval is provided.
- Abbreviated PCX/IOM ordering descriptions call relay outputs BO. Detailed
  point-type matrices distinguish UO and RO. The catalog records the detailed
  physical pools and keeps the conflicting wording; it does not add extra BOs.
- PCX3731 technical specifications say external output power only, while the
  same guide’s wiring/jumper sections describe internal/external selection. Exact
  variant and power-source settings remain unresolved.
- Generic FX binary-input tables state 100 Hz, while the reviewed PCX wiring
  requirements state 50 Hz with timing/duty conditions. Pulse family matching
  does not approve either frequency.

CH-PCX3733-0 and MS-IOM3733-0 retain the external low-voltage output-power
requirement. Regional availability and electrical approvals are not inferred.

## Source binding and evidence

A current stored hardware survey can be selected explicitly by original report
ID, content SHA-256 and base/SA host. The backend reloads that local immutable
report, verifies its hash, requires exactly one selected SA module when relevant,
and matches its explicit Device/configured model evidence to the requested
model. Imported/configured evidence does not verify a physical label. Existing
survey conflicts and unresolved corroboration remain in the capacity evidence.
No original survey field, hash, occupancy decision or native source is rewritten.
Deleting the report, using a stale hash or choosing a different model/host
refuses a new bound review. An offline model declaration remains available.

Changing model, demand, selected survey/host or catalog invalidates a displayed
review and its export. Late responses after edits, replacement or navigation do
not become current evidence. Malformed/mixed-version catalog and review
responses show an error while preserving the draft. The UI exports the original
HTTP response Blob, not a browser JSON reserialization.

API:

- `GET /api/hardware-capacity/catalog`: local facts, limits, sources and catalog seal.
- `POST /api/hardware-capacity/review`: explicit catalog SHA, model, demand rows
  and optional survey reference. Requires the ordinary authenticated local
  session. No field operations or writable protocol adapter are called.

Requests permit at most 32 unique demand rows, quantity 1–64 per row and 1,024
total declared channels. Booleans and noninteger quantities are rejected.
Reviews are stateless; save the authoritative JSON explicitly. The content seal
is SHA-256 over UTF-8 JSON with sorted keys, compact separators, no NaN and
`ensure_ascii=False`, excluding `content_sha256`. It binds content, not authorship
or manufacturer acceptance. Catalog hashes bind the precise source/fact profile.

## Reviewed primary documents

The catalog contains bibliographic facts and reviewed hashes; proprietary PDFs
and publisher extracts remain outside the repository.

| Source | Revision/date and reviewed sections | Reviewed artifact SHA-256 |
| --- | --- | --- |
| [FX product bulletin, LIT-12011657](https://docs.johnsoncontrols.com/bas/r/Facility-Explorer/en-US/FX-PC-Series-Programmable-Controllers-and-Related-Products-Product-Bulletin) | 2024-03-07; PDF 8 Table 2, 10–11 Table 5, 14–15 Tables 7/9/10, 24 Table 15 | `733063dc209b19212100a4957e3e7c05e00484b31b4886f8aeb5d4b65e2fa8af` |
| [Metasys product bulletin, LIT-12011042](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Metasys-System-Field-Equipment-Controllers-and-Related-Products-Product-Bulletin/13.0) | 13.0, 2023-09-06; PDF 11–12 Table 5, 18–19 Table 13 | `3a65a6ffe84c8e453d814af07470638fd7a1b12965df52e859580a276d2386a3` |
| [FX VAV installation, 24-10143-357](https://docs.johnsoncontrols.com/bas/r/Facility-Explorer/en-US/FX-PCV1615/1626/1628/1630-Programmable-VAV-Box-Controllers-Installation-Instructions/H) | H, 2019-03-22; PDF 6 terminal functions, 27 Table 10; family -x counts, selected existing legacy -0 applicability only | `0247275ca05080ab30ff5ee10e046f3d4877e2629ca0079262e9e0f610addd36` |
| [VMA installation, 24-10143-217](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/VMA1615/1626/1628/1630-VAV-Controllers-Installation-Guide/K) | K, 2019-10-18; PDF 2 terminal functions, 19 Table 10; family -x counts restricted to selected existing legacy -0 profiles | `789139c207dd93409c8b17fe6645772ed1365a4912ed1e5589d1db0a38f2c5ca` |
| [FX PCX37 installation, 24-10144-114](https://docs.johnsoncontrols.com/bas/r/Facility-Explorer/en-US/FX-PCX37-Expansion-Input/Output-Module-Installation-Instructions/G/I/O-wiring-ratings-and-requirements-table), [PCX17/27 installation, 24-10144-106](https://docs.johnsoncontrols.com/bas/r/Facility-Explorer/en-US/FX-PCX17-and-FX-PCX27-Expansion-Input/Output-Module-Installation-Instructions/G/Terminal-wiring-guidelines-functions-ratings-and-requirements/Wiring-ratings-and-requirements-table) | G, 2019-03-22; wiring requirements. Hash identifies a combined publisher text-extraction capture made 2026-10-22, **not PDF bytes** | `acedaece5e47a9fc812bd090c5ddfd300997f3e73afeb35f55a11c720819329c` |
| [FX PCX3721 installation, 24-10144-203](https://docs.johnsoncontrols.com/bas/r/Facility-Explorer/en-US/FX-PCX3721-Expansion-Input/Output-Module-Installation-Instructions/F/Wiring/Terminal-wiring-guidelines-functions-ratings-and-requirements/I/O-terminal-blocks-ratings-and-requirements), [PCX3731 installation, 24-10144-181](https://docs.johnsoncontrols.com/bas/r/Facility-Explorer/en-US/FX-PCX3731-Input/Output-Module-Installation-Instructions/E/I/O-wiring-ratings-and-requirements) | F / E, 2019-03-22; binary terminal requirements, PCX3731 technical specifications and power-source jumper section. Combined publisher text-extraction capture made 2026-10-22, **not PDF bytes** | `245ce0d4bf66e1e26ad2e785d15cf912aead09d4bbb9903ae280bf46b9bfe9e3` |

The existing model-specific input survey, sensor-supply planner, bus preflight
and observed native CAF terminal editor remain separate features. Their narrower
supported models, hashes and safety conditions are not expanded by this catalog.
