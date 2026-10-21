# JCI physical input surveys and spare-terminal planning

**Connect → Hardware survey** builds a fresh, bounded, read-only inventory for an
explicit BACnet/IP controller, an explicit IP router plus DNET/MAC address, or an
already-open direct serial MS/TP interface with a selected local MAC/Device.
Nothing in the application preloads a particular site's survey results.

The survey verifies the Device identity, reads the indexed Object_List, and
reads exposed analog, binary, and multistate inputs. Input rows retain names,
descriptions, values, units, reliability, status flags, out-of-service state,
terminal labels and property-level errors. JCI property reads additionally retain
slot, raw setup and SA-bus host evidence. Responses must match the requested
source, invoke ID, object, property and array index. Unsupported metadata stays
unknown; a binary object on a universal terminal still occupies that terminal.

## Browser workflow

1. Open a BACnet/IP or direct serial MS/TP connection, then enter the exact
   address and Device instance in the hardware panel or select an IP discovery result. Routed targets
   require both the literal IP router and its DNET. Survey requests may use an
   explicit route without changing the engineering connection's configuration.
2. Choose object, input and operation-time limits. Start the survey, inspect
   progress, or cancel. Partial and cancelled evidence remains clearly labelled.
3. Filter inputs by host, type or search text. Download the saved JSON report or
   CSV input table. Saved evidence and jobs can be reopened or removed.
4. Optionally import a local native CAF/MOI archive, reuse a previously saved
   complete stream-access BACnet File capture, or explicitly read an existing
   advertised Archive .moi File object. Compare native configured modules and
   assignments with the surveyed controller.
5. Review candidate spare terminals. A relocation review can describe moving an
   identified binary input from a universal input to a documented spare dedicated
   binary input. A sensor plan can use separate candidate universal inputs, or
   conditionally use the input freed by that proposed move. Plans include endpoint
   scaling, low/middle/high checks, report hashes and required engineering checks.

Imports are explicitly labelled as supplied evidence. Candidate occupancy is
recomputed rather than trusting imported availability claims. Native-only
assigned inputs found during a corroborated archive comparison remain occupied,
even when not exposed through the BACnet Object_List.

## Scope and model coverage

Exact documented capacity profiles currently cover FX-PCG2611-0, FX-PCX3711-0 and
FX-PCX3721-0, including the supported PCX model spelling without the `-0` suffix.
Unknown models remain visible but do not acquire guessed capacities. The same
survey can retain standard input metadata for other JCI FX/Metasys controllers;
this does not establish their spare-terminal capacity. In particular, this
feature does not claim complete PCV/VMA1630/1615 hardware support.

Native inspection recognizes a bounded subset of MOI BACnet-tagged hardware
records and existing CAF XML scalar records. It preserves the original source
bytes and hashes; it does not create new native objects. Model/terminal/name/setup
conflicts, missing corroboration, ambiguous assignments and incomplete inventories
withhold usable spare-terminal claims. An existing archive is an opaque file copy,
not an atomic whole-controller backup or editable reconstructed application.

A candidate means no assignment was found in the reviewed configuration. It does
not prove an unwired physical terminal. Confirm installed labels, all native
assignments, electrical compatibility, power/common references and actual wiring
before engineering a change. Real hardware/electrical limits still apply.

Relocation and sensor plans perform no controller writes, native compilation,
program download, live reassignment, activation or rewiring. Those actions still
need a verified manufacturer-compatible authoring/transfer path and physical
commissioning. Direct serial MS/TP now has an [explicit read-only survey/archive
profile](jci-direct-serial-survey.md); BTCVT remains outside that profile. No field
connection opens on import, page load or server restart.

## Bounds and persistence

- One active hardware job; defaults of 512 objects, 256 inputs and 45 seconds.
  Request maxima are 4,096 objects, 1,024 inputs and 180 seconds. Property timeout
  is 0.05–1.5 seconds. Reads are paced and use only explicit properties.
- Archive source: 2 MiB maximum; expanded native content: 8 MiB maximum; bounded
  record counts, gzip decoding and CAF container/XML inspection. Existing
  controller archive reads also enforce stable identity, advertised File
  membership, metadata, offsets, lengths, EOF and a 240-second time budget.
- Retention: 32 reports, 16 archives, 32 jobs, 128 MiB total evidence storage.
  Remove older items explicitly when a retention limit is reached.
- Evidence uses private local files, canonical JSON SHA-256 integrity wrappers,
  atomic replacement and exact-source hashes. Interrupted jobs do not resume
  field traffic after restart. CSV exports escape formula-leading text.
- State-changing local API requests use the existing Studio token protection.
  These requests manage local jobs/artifacts only; field reads remain read-only.

## API surface

All routes are under `/api/bacnet/hardware`:

| Route                                                                 | Purpose                                                         |
| --------------------------------------------------------------------- | --------------------------------------------------------------- |
| `GET /status`                                                         | Limits and saved reports, archives, jobs and available captures |
| `POST /survey`                                                        | Start an explicitly addressed bounded survey                    |
| `GET /jobs/{id}`; `POST /jobs/{id}/cancel`                            | Read progress or cancel the owned job                           |
| `GET /jobs/{id}/export`                                               | Export exact job evidence                                       |
| `POST /import-report`                                                 | Validate and save supplied survey JSON                          |
| `GET /reports/{id}`; `GET /reports/{id}/export?format=json\|csv`      | Reopen or export a report                                       |
| `POST /archive`; `POST /archive/capture`                              | Analyze local native bytes or a saved capture                   |
| `POST /read-archive`                                                  | Read an existing advertised Archive .moi File object            |
| `GET /archives/{id}`; `GET /archives/{id}/export?format=json\|source` | Reopen analysis or export evidence/original bytes               |
| `POST /enrich`                                                        | Correlate a saved survey with archive assignments               |
| `POST /relocation`; `POST /sensor-plan`                               | Generate review-only engineering plans                          |
| `DELETE /{reports\|archives\|jobs}/{id}`                              | Remove a saved item; active jobs must be cancelled first        |

## Validation

Authored native fragments and isolated UDP BACnet peers exercise production reads,
archive copying, identity/source/membership checks, partial data, cancellation and
no-write boundaries. Browser tests intercept all hardware traffic and cover routed
targets, stale-result isolation, retry, persistence, imports, filters, exports and
engineering plans. There are no private site fixtures or field acceptance claims.

```sh
.venv/bin/python -m pytest tests/test_hardware_survey.py tests/test_hardware_workbench_api.py
cd web
npm run build
npx playwright test tests/hardware-survey.spec.ts
```
