# Local CAF input scenarios

The **CAF simulation** workspace now saves named local input scenarios with elapsed-time value and quality events. These scenarios prepare and review repeatable input stimuli. They do not execute native CAF logic, calculate controller outputs, or implement CCT's proprietary simulation engine.

This workflow is separate from the existing [native saved simulation scalar editor](caf-simulation-profiles.md). Its JSON format is `bms.caf-local-input-scenario`, version 1, rather than a claimed native CCT scenario format. Audit item IA-de934811c5 remains incomplete for native JCI execution and native trajectory encoding.

## Manufacturer evidence and limits

The downloaded _Controller Tool Help_, Release 10.2, describes saved simulation startup settings on PDF page 38, setting input startup values and commanding values during simulation on page 258, and startup value/name/units fields on page 262. The local PDF is `Manual_Library/manuals/controller-tool-help-legacy-10.2.pdf`, SHA-256 `2779fa8517bf90a38bb5a214e7bdd40af170cd77a28c06b3715b6ba4f710d4bc`. Current publisher documentation also describes [saved Simulation startup settings](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/16.0.1/User-Interface/User-Interface-Concepts/Modes/Simulation?contentId=dOb1V7YbqtwzPCXG0SvfOg) and [startup inputs disconnected from hardware](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/14.0/Simulating-a-System/Simulating-a-System-Concepts/Simulation-Overview).

These references establish the useful workflow, not an interchangeable native trajectory representation. No verified native trajectory or quality encoding was found. The native graph inspector does not lower CAF algorithms into the portable simulation engine. This implementation therefore previews the input stimuli only and keeps local quality separate from native CAF bytes.

Only existing, editable class-version `1.0` saved simulation records already accepted by `CafSimulationProfile` can become local inputs:

| Native class             | Input scalar | Scope                                        |
| ------------------------ | ------------ | -------------------------------------------- |
| 526, Input Float Block   | `float`      | Existing `simulationProperty id="3113"` only |
| 530, Input Boolean Block | `boolean`    | Existing `simulationProperty id="3113"` only |

Class 527 is an **Output Float Block** and is excluded from local input scenarios, although the separate saved-value editor can edit its supported startup scalar. Enum classes, unknown versions/structures, ordinary properties, and physical channels without a supported saved startup record are excluded. No channel is inferred from a controller model or live point inventory.

## Browser workflow

1. Open a CAF in **CAF simulation**, then use **Local CAF input scenarios** below the native saved-value editor.
2. Enter a name, description, duration and preview interval. Expand the input contract to inspect exact identities, types, initial values and raw native unit metadata.
3. Add input events with elapsed seconds, native scalar text and local quality. Multiple inputs can update at one time. Adding the same input at the same time replaces that sample. Edit or remove samples in the event table.
4. **Save local scenario** persists it in local application data. Reopen saved scenarios, save copies, or delete saved copies. Revisions reject concurrent stale saves/deletes. Unsaved drafts require explicit discard before source replacement and warn before leaving the page.
5. Export/import scenario JSON to move the scenario to another computer. The exact source CAF must also be opened there. Import validates all source and input guards before replacing the draft.
6. **Preview input stimuli** produces a bounded timeline. Select a frame and inspect held values and local qualities. Export preview JSON for a source/profile/scenario-hashed record of the stimuli.
7. Optionally choose an all-good frame and **Export startup CAF at preview time**. This reuses the existing guarded native scalar editor to produce a separate CAF copy. Only supported input scalar leaves change. Output startup values, ordinary properties and source CAF bytes remain unchanged. A frame containing any non-good quality is refused because native quality encoding is unverified. The trajectory and quality metadata are never written into the CAF.

Native copies still need save/reopen/simulation validation in matching authorized CCT/PCT. There is no controller connection, download or live edit in this workflow.

## Source, unit and timing contract

Every scenario contains the exact archive SHA-256, a semantic input-profile SHA-256, and complete guarded input definitions: exact reference/property identity, class/version, native scalar type, name, initial scalar text, and raw native units metadata. The semantic hash includes the input definitions and local replay semantics. Changing either hash, any input guard, the schema version, or the source archive is rejected. Even a ZIP-metadata-only change creates a different source CAF.

`units_native` preserves an unambiguous scalar ordinary property `117` exactly as parsed, including its type, enum-set attributes and text. It does not guess an enum domain or convert engineering units. Missing, duplicate or opaque unit properties report `unit_status: "unknown"` explicitly. Unknown units are never silently treated as unitless or assigned Fahrenheit/Celsius.

Values remain validated native scalar **text**. Floats must be finite, within float32 range, and must not underflow nonzero to zero. Their spelling is preserved; preview does not interpolate or claim native floating-point execution. Booleans require `0`, `1`, `false` or `true`. Local qualities are exactly `good`, `open-circuit`, `short-circuit`, `unreliable` and `out-of-service`; they annotate stimuli and do not simulate native reliability propagation.

Time is elapsed seconds from zero, independent of wall clock, simulation speed and proprietary scan timing. Initial values come from the source CAF with an explicitly **locally assumed good** quality. Events require strictly increasing times in `[0,duration]`; combine simultaneous changes into one event row. Each event applies inclusively at its time. Omitted inputs retain their preceding value and quality. Preview includes zero, regular interval boundaries strictly below duration, every event time, and duration itself. Decimal interval arithmetic merges a `0.3` event with the corresponding `0.1` interval boundary without binary multiplication creating a second near-identical frame.

## Persistence and resource limits

Scenarios persist in the existing local SQLite state database, with content SHA-256 verification and metadata checks on reopen. Save/delete use optimistic revisions inside a transaction. Invalid saves and quota failures leave the prior saved scenario intact. The audit records operation, source hash, identifier and revision; it does not record scenario values.

The store intentionally does not retain the CAF. After restarting the application, reopen the original source CAF, then select and reopen the saved scenario. Full source/profile validation runs again. A stale or corrupted scenario is rejected rather than silently rebound.

Bounds are 256 supported inputs / 128 KiB input contract, 2 MiB scenario JSON, 2,000 event rows, 2,001 preview frames, a conservative 4 MiB serialized-preview budget, 86,400 seconds duration, and an interval above zero through 60 seconds. A new scenario automatically chooses a wider interval when a large input contract needs it to fit the preview budget. Local storage holds at most 200 scenarios and 64 MiB of compact scenario content; replacement accounting subtracts the previous record size. Unsupported or oversized inputs fail explicitly.

## API and verification

All routes below use `/api/caf/{source_sha256}/local-scenarios`. Source CAFs must already be opened through `/api/caf`.

| Method / suffix         | Function                                                              |
| ----------------------- | --------------------------------------------------------------------- |
| GET                     | Contract, new-scenario template and saved metadata for this exact CAF |
| POST `/validate`        | Validate imported scenario JSON                                       |
| POST `/preview`         | Deterministic input-stimulus frames                                   |
| POST `/startup-profile` | Guarded native saved-value profile for an exact all-good frame time   |
| POST `/save`            | Save with optional identifier and required expected revision          |
| GET `/{scenario_id}`    | Reopen and source-revalidate a saved scenario                         |
| DELETE `/{scenario_id}` | Delete with required expected revision                                |

Mutations require the existing local session token and retain the application's loopback/origin protections. Preview JSON has its own `bms.caf-local-input-preview` format, source/profile/scenario hashes and explicit scope/semantics.

Authored public fixtures cover exact input selection, native unit preservation, source/semantic/input guard rejection, negative/zero values, event boundaries/hold behavior, local quality, malformed/bounded requests, native startup scalar readback, byte-preserved cached sources, SQLite restart/reopen, optimistic conflicts, corruption refusal and atomic quota failures. Browser tests cover complete save/reopen/import/export/preview/startup-copy workflows, faulty-frame refusal, stale revisions, draft retention and hidden-workspace download suppression. The source CAF and field interfaces remain unchanged throughout.
