# Sensor supply budgeting

**Connect → Hardware survey → Sensor power supply budget** creates an offline
engineering plan for sensor power. It works without a field connection or survey.
It compares explicit AC/DC voltage ranges, shared supply-current budgets,
independently stated terminal limits, and separate steady/startup demands. It does
not allocate controller points, change hardware or send BACnet requests.

## Plan workflow

1. Name the plan. Add each physical supply pool once, with a unique physical
   supply instance name. Select an exact documented profile or **User-declared
   external/custom supply**. An external supply has its own explicit voltage, AC/DC
   domain, current limit and terminals; it is not inferred from controller power.
2. Add all existing and planned powered devices to the appropriate rail and
   terminal. Quantity counts physical powered devices. A combined sensor with two
   signal outputs is one powered load. Mark the load inventory complete only
   after accounting for existing loads sharing that supply.
3. Declare the operating voltage bounds from independent evidence, or leave them
   unknown. A nominal voltage alone is not a guaranteed voltage envelope.
   Manufacturer profile facts are locked. Converting a record to a user-declared
   specification removes its manufacturer provenance.
4. Calculate the budget. Review voltage compatibility, current arithmetic,
   unknown maximum/startup values, shared totals and any explicit terminal limits.
5. Save locally, reopen, edit, save a copy or delete. Export/import the portable
   plan JSON; export a separately calculated report JSON. A saved plan survives
   application restart. Draft changes need a save or export to persist.

A plan can explicitly bind the currently opened hardware survey. Its report ID
and exact sealed content hash are then revalidated on save, reopen, calculation
and import. This records an evidence relationship; it does not establish that the
selected supply profile matches the installed controller. No site observations
are encoded in the application.

## Reviewed manufacturer profiles

Only these exact model suffixes are included. Similar product numbers do not
inherit a rating. The profiles distinguish a shared auxiliary sensor output from
SA/FC bus leads and external 24 VAC power.

| Exact model                | Reviewed power fact                                                                     | Reference                                                                                                                                                                                                                                                                                                  |
| -------------------------- | --------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| FX-PCG2611-0, FX-PCG2621-0 | Universal +15 VDC active-input sensor supply, 100 mA shared total                       | [24-10143-160, Rev G, 2024-01-05, PDF page 13](https://docs.johnsoncontrols.com/bas/r/Facility-Explorer/en-US/FX-PCG26-General-Purpose-Programmable-Controller-Installation-Guide/G/Terminal-wiring-guidelines-functions-ratings-and-requirements/Input/Output-Terminal-Blocks-ratings-and-requirements)   |
| FX-PCX3711-0               | Universal +15 VDC active-input sensor supply, 100 mA shared total                       | [24-10144-114, Rev G, 2019-03-22, I/O ratings](https://docs.johnsoncontrols.com/bas/r/Facility-Explorer/en-US/FX-PCX37-Expansion-Input/Output-Module-Installation-Instructions/G/I/O-wiring-ratings-and-requirements-table)                                                                                |
| FX-PCV1615-0, FX-PCV1630-0 | Universal +15 VDC active-input sensor supply, 35 mA shared total                        | [24-10143-357, Rev H, 2019-03-22, PDF page 14](https://docs.johnsoncontrols.com/bas/r/Facility-Explorer/en-US/FX-PCV1615/1626/1628/1630-Programmable-VAV-Box-Controllers-Installation-Instructions/H/Input-and-Output-wiring-guidelines-tables)                                                            |
| MS-VMA1615-0, MS-VMA1630-0 | Universal +15 VDC active-input sensor supply, 35 mA shared total                        | [24-10143-217, Rev K, 2019-10-18, PDF page 8](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/VMA1615/1626/1628/1630-VAV-Controllers-Installation-Guide/K/Terminal-wiring-guidelines-functions-ratings-and-requirements/Input-and-Output-wiring-guidelines-tables)                                    |
| FX-PCX3721-0               | SA PWR is a connection to supervisor-supplied power; it is not a local auxiliary source | [24-10144-203, Rev F, 2019-03-22, bus/supply terminals](https://docs.johnsoncontrols.com/bas/r/Facility-Explorer/en-US/FX-PCX3721-Expansion-Input/Output-Module-Installation-Instructions/F/Cable-and-wire-length-guidelines/Communications-bus-and-supply-power-terminal-blocks-ratings-and-requirements) |

These auxiliary profiles do not establish separate per-terminal current ratings,
output-voltage tolerance or startup allowances. A terminal with no stated limit
is labelled unknown, not unlimited. Only stated terminal limits and the shared
pool limit are checked. The PCX3721 pass-through profile is always incompatible
as an independently available power source; no auxiliary rating is guessed.

The [Belimo 22UTH-510X primary technical data sheet](https://www.belimo.com/mam/general-documents/datasheets/en-us/belimo_22UTH-510X_datasheet_en-us.pdf),
reviewed in its 2026-08-26 revision, specifies AC 21.6–26.4 V, DC 13.5–26.4 V,
0.8 VA on AC and 0.4 W on DC. It describes one combined humidity/temperature
sensor. The consumption figures are not explicitly labelled maximum, typical or
startup. The catalog retains them as **published-unspecified** and leaves startup
unknown. Selecting a 0–5 V signal output does not change the sensor's power-input
requirements.

For example, the published 0.4 W produces a **nominal estimate** of 26.667 mA at
15 VDC. Two such devices produce a 53.333 mA subtotal and exceed a 35 mA pool.
One device remaining below that pool is still an incomplete plan: maximum and
startup demand, supply tolerance, all existing loads and installed wiring remain
separate questions.

## Arithmetic and result meanings

- Explicit mA values are added directly. DC watts and AC volt-amperes are divided
  by the lowest declared supply voltage, or by nominal voltage as an estimate
  when the operating range is unknown. AC watts without power factor, AC/DC
  mismatches and W/VA mismatches are not silently converted.
- A stated typical, user-estimated or published-unspecified demand remains an
  estimate. A computed current is an established maximum only when the demand is
  explicitly maximum and any voltage needed for the conversion is bounded.
  Unknown values are counted as unknown physical devices, never zero demand.
- The complete declared supply envelope must fit the load's supported range. A
  nominal voltage that fits with an unknown envelope remains unverified. A
  wrong supply domain or incompatible voltage range is **incompatible**.
- A known subtotal above a stated shared or terminal limit is **over-budget**,
  even if other loads are unknown. Startup is compared with the same stated
  current ceiling; no short-term overload allowance is assumed.
- Missing current limits, incomplete load coverage, unknown voltage tolerance or
  maximum/startup demand produce **incomplete**. **Within-declared-limits** means
  only that the supplied bounded engineering declarations fit the stated shared
  and any separately declared terminal limits. It is not wiring approval or a
  manufacturer certification.

## Provenance, storage and boundaries

Every documented profile contains its exact model, document revision, source
URL, reviewed artifact kind and SHA-256. Its profile hash also covers the locked
specification and bibliography. Each plan carries the exact catalog hash and
selected profile hashes. A changed catalog, forged profile, changed locked fact,
missing survey or mismatched survey hash is rejected without rewriting the
source evidence.

Reviewed PDF hashes are:

| Document           | SHA-256 of reviewed PDF bytes                                      |
| ------------------ | ------------------------------------------------------------------ |
| 24-10143-160 Rev G | `ec118dc20634d756b1a47af9699445b659d54abe8d824fae90bd54676c51ec4a` |
| 24-10143-357 Rev H | `0247275ca05080ab30ff5ee10e046f3d4877e2629ca0079262e9e0f610addd36` |
| 24-10143-217 Rev K | `789139c207dd93409c8b17fe6645772ed1365a4912ed1e5589d1db0a38f2c5ca` |

PCX and Belimo source facts were reviewed through primary publisher text
extraction. Their source artifact hash is
`0f0712d5892751b2b75a47a7783a46793390394db91e79faf3dc00a17e42d2b7`,
identifying the combined reviewed extraction capture dated 2026-10-21, **not PDF
bytes**. Bibliographic facts and hashes are committed; copyrighted source
manuals and extraction captures stay outside the repository. Current publisher
pages may change independently of the captured reviewed revision.

Plans use `bms.sensor-supply-plan`, version 1; reports use
`bms.sensor-supply-report`, version 1. Unknown properties, nonfinite values,
ambiguous identities and unsupported versions are rejected. Limits are 32 rails,
256 load records, 100 devices per record, 32 terminals per rail, 2 MiB per plan,
and 100 saved plans/32 MiB total. Current/demand values are bounded at 1,000,000;
voltage is bounded to 0.01–1000 V. These parser bounds are not supported hardware
ratings.

Saved records retain content hashes and optimistic revisions. Conflicting saves
require reopening. Stale or corrupt plans appear as unavailable without blocking
other saved plans; explicit revision-guarded deletion remains available. There
is no automatic stale-profile migration. Restore an exact source survey where
appropriate or construct a new plan using reviewed current profiles.

The feature does not establish COM/common reference, grounding, transformer
capacity, wiring polarity, conductor ratings, isolation, jumpers, supply droop,
real inrush, native point allocation or installed-device identity. It performs
no field writes, actual rewiring, native compilation or controller download.

## API and validation

All routes inherit the application's loopback/session protections:

| Route under `/api/sensor-supply` | Operation                                      |
| -------------------------------- | ---------------------------------------------- |
| `GET /catalog`                   | Exact catalog, empty plan and scope            |
| `POST /validate`                 | Validate portable plan and exact source guards |
| `POST /evaluate`                 | Calculate fresh engineering report             |
| `GET /plans`                     | Saved-plan availability/revision list          |
| `POST /save`                     | Create or revision-guarded replace             |
| `GET /plans/{id}`                | Reopen and revalidate                          |
| `DELETE /plans/{id}`             | Explicit revision-guarded deletion             |

Authored tests cover unit arithmetic, maximum/typical/unknown/startup distinctions,
AC/DC and operating-envelope mismatches, shared/terminal limits, physical device
quantities, immutable manufacturer profiles, stale survey/catalog guards,
restart, integrity checks, revision conflicts and atomic storage quotas. Browser
tests use the real local API for profile selection, rail/load editing,
calculation, save/reopen/copy/delete, source-bound import/export and delayed-export
cancellation. None requires a field connection.

```sh
.venv/bin/python -m pytest tests/test_sensor_supply.py tests/test_sensor_supply_api.py
cd web
npx playwright test tests/sensor-supply.spec.ts
```
