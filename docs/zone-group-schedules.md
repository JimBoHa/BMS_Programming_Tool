# Portable weekly zone-group occupancy

Open **Equipment wizard → Zone-group schedules** to create a separate portable occupancy Program for one explicitly labelled AHU and one to eight named Zone Groups. Each group requires an explicit IANA timezone, unique start weekdays (Monday0 through Sunday6), and **window**, **all-day**, or **disabled** mode. The logical outputs have no native BACnet object, occupancy enum, zone/controller or Global Data binding.

## Occupied and earlier windows

Window mode uses half-open `[start,end)` intervals. An overnight interval belongs to its selected **start** weekday. Equal start/end is empty, even with a positive pre-lead. All-day explicitly means24 local hours; disabled or an empty weekday selection is empty. Start/end fields are retained but inactive in all-day/disabled mode.

The authored **pre-or-occupied** interval starts the declared lead earlier and retains the original occupied end: `[start−lead,end)`. Lead is a strict integer from0 to1,440 wall-clock minutes, default180. It does not shift closing earlier. Overlapping expansions merge across the cyclic local week, including Sunday/Monday wrap and intervals longer than24 hours. Occupied intervals merge separately. **Pre-only** is the expanded union AND NOT the occupied union; subtracting each individual window separately could incorrectly label an already occupied interval as pre-only.

The generator lowers these unions into existing Boolean Schedule/Or blocks. Each full local day becomes `00:00–12:00` plus `12:00–00:00` on that start weekday; equal-time Schedule nodes never stand in for24 hours. Full-week occupancy therefore works without changing the original Schedule block's empty-window behavior. The finite10,080-minute representation is exact at the existing runtime's minute resolution; end instants remain excluded.

Each group exposes three Outputs: scheduled occupied, pre-or-occupied and pre-only. `ahu_occupied` is OR of the **original occupied** group outputs. An early pre-only interval does not itself set AHU occupied or issue a warmup/physical AHU command. All operations happen inside one graph scan. If these outputs are subsequently linked to other Programs through System simulation, its existing explicit previous-cycle link delay and initial-value rules still apply; a failed group cycle rolls back all participants.

## Local clocks and limits

Lead is a local wall-clock expansion, not a timer or guaranteed elapsed duration. In Los Angeles, a Sunday03:30 occupied start expanded to00:30 has two elapsed hours of lead across the2026 spring transition and four across the autumn transition. Missing spring minutes never occur. A01:15–01:45 autumn window runs during both folds, with a real-time off gap between those windows. The existing Schedule evaluator supplies this pointwise behavior.

The preview can evaluate up to128 explicit UTC instants, written with `Z` or `+00:00`. These rows expose actual generated graph outputs. They do not calculate time-to-occupancy or validate native controller clock configuration. Dated exceptions are explicitly refused by this foundation; no exception or holiday shift policy is guessed.

Named-zone ST/PLCopen source requires host-supplied calendar and validity bindings. The independent host IEC verifier supplies them; standalone autonomous PLC/controller calendar behavior is not established. Native CAF/SCT application generation, native occupancy MV codes, zone/AHU associations, supervisory Global Data objects, warmup/cooldown/countdown operating modes, hardware deployment and full G36/Title24 compliance remain outside this profile.

## Evidence and workflow

The new profile is `studio-weekly-zone-group-occupancy/1`. Preview records the exact source/profile/choice/Program hashes, declared labels and clocks, generated local windows and counts, logical output identities, validation findings and unsupported features. Exported review JSON retains authoritative server bytes and an `X-File-SHA256` header. These hashes establish content identity, not manufacturer authenticity or certification.

Preview before creating a separate editable Program. Choice, current-editor or profile changes retire preview authority; replacing existing editor contents requires confirmation. Use normal simulation, graph editing, revision save/reopen and JSON/ST/PLCopen/GraphML interchange afterward. Later manual edits do not silently rewrite the original generation evidence. No field interface opens, native objects are created, or controllers are queried by this workflow. Existing calendar, Program canonicalization, source export profiles and saved graphs remain unchanged.

Bounds are eight groups, seven unique weekdays per group,1,000 generated nodes and128 evaluation clocks. Labels must be visible printable text; IDs, times, zones, Boolean-vs-integer types, scan periods and work limits are validated. The API has no implicit saves or retained draft library; ordinary project revision storage is available after creation.

## Primary criteria and verification

JCI **Guideline36 Sample Archive Application Note**, LIT-12014121, edition15, PDF28–30 (actual schedule table/checklist on30) describes a Schedule and earlier Pre-Schedule per Zone Group, default180-minute Offset AV, zone-only schedule associations and AHU occupancy when a group becomes occupied. Original PDF SHA256: `6ba1a3963dc71de99a7a5192a7c1aa61487e0150d3902e34fc5a5bc34dd7e422`. [Official application note](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Guideline-36-Sample-Archive-Application-Note/15).

The note qualifies that workflow. It does not specify the full-day, DST, overlap, end-retention or exception algorithms. The explicit end-preserving wall-clock union above is authored Studio behavior, not recovered native G36 encoding. Scoped SCHED-COORD-001 is implemented; broad MF-43cb984ef4 remains partial.

Independent finite interval tests check every minute of complete weeks against an absolute-interval oracle and the core evaluator, plus wrap, empty/full-day/full-week, overlap subtraction, AHU truth tables and DST boundaries. Actual MatIEC/Clang execution tests generated compositions with host calendar bindings and transactional invalid-binding faults. HTTP/browser tests cover strict requests, source transport, exact downloaded evidence, guarded preview/create, simulation, revision save/reopen and closed field networking. Host execution does not establish physical JCI acceptance.
