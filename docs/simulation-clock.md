# Paced portable-graph simulation

**Run** now paces ordinary Studio graph scans against the browser's monotonic clock. Requested speeds are 1×, 2×, 5×, 10×, 20×, 50× and 100× real time. The default is an explicit 1×. Each scan still uses the project's unchanged `scan_seconds`; acceleration changes how many scans are requested, never the control-law timestep. Manual **Step**, saved graphs, revisions, forces and deterministic scenario execution retain their scan semantics.

The control bar distinguishes requested speed from achieved confirmed simulated seconds per active wall second. It shows confirmed committed scans, remaining scan budget, admitted pending scans and simulated-time lag. A speed selection is a request, not a host performance guarantee. CPU load, graph size, network latency to the local API and browser scheduling can reduce achieved speed.

## Bounds and pacing

- There is at most one admitted HTTP scan request at a time. A batch contains at most 100 scans, subject to available monotonic-time credit. The UI scheduler checks at 50 ms intervals; that refresh interval is not the simulation timestep.
- Each run window has a declared 1–10,000 scan budget, no more than 86,400 simulated seconds, and at most one hour of active monotonic wall time. Completing a budget stops automatically. Pressing Run after completion starts a fresh pacing window while retaining the graph engine's state and simulated UTC. Reset starts a fresh engine session.
- A lag of more than five wall seconds pauses scheduling; long fixed scan intervals receive a limit of twice their expected scan interval instead. No unlimited catch-up loop or silently altered timestep is used. Explicit resume discards unexecuted wall-time credit and retains confirmed graph state.
- Requested speed/budget are UI controls, not serialized program logic, and remain disabled while a batch/run is active. Inputs, internal holds and the recording checkbox are sampled for the next admitted batch. Changing a value while a batch is already admitted cannot alter that batch's captured selections. A scenario result applies its final force map only if the operator has not changed the current force selection while that request was pending.

## Pause, editing and navigation

Pause immediately prevents another batch from being admitted. If a request is pending, the status says **pausing** until its response is received; its confirmed committed scans and history are displayed before the clock freezes. Resume retains engine state and the remaining run budget. Paused time never creates catch-up credit.

After a successful pending batch finishes, the paused status retains its explicit cause (operator, hidden page or workspace navigation) and replaces the waiting notice with a completed-batch notice. A scan fault or exhausted run budget still takes precedence. Resuming starts a new running status without carrying the previous pause cause forward.

Opening a dialog alone does not pause or resume the clock. Editing the source graph stops pacing and resets that graph's simulation, matching the existing editor policy; it does not secretly resume after the edit. Leaving the Program workspace or hiding the browser page pauses explicitly. Returning requires Run. Reset, source changes and unmount retire pending display responses; new scans wait for an outstanding request to settle. Scenario requests share the same admission owner: pending scenarios block Run, Step and another scenario until their exact request settles. Reset/source edits retire late scenario display results without releasing that gate early. A scenario computes an independent finite history; a failed scenario response preserves the known main engine/history and does not imply a stateful step committed.

A retired request may already have committed to its old in-memory server session. Its result cannot revive the reset editor, and the new engine session starts independently. Old sessions retain the existing bounded expiry policy; reset does not assert cancellation or rollback of already admitted work.

Manual Step retires the pacing window and executes exactly one ordinary scan. It can explicitly recover a confirmed sensor/scan fault while retaining the known session's prior committed state. A new Run then starts a fresh pacing window. This is local graph execution, without controller I/O or autonomous server run jobs.

## Fault and receipt semantics

The bounded optional `operation_id` request field is a 32-character lowercase hexadecimal correlation identity. The step response echoes it, requested/completed scan counts, actual timestep and program ID/revision. It is **not an idempotency key**, retry permission or a native controller receipt. The browser pairs it with its exact source/reset generation and known session. Mismatched receipts and failed HTTP outcomes latch the run/step controls until explicit Reset or a source reset. They do not prove that zero scans executed, and are never automatically retried. Even Reset cannot undo an already admitted old-session scan.

Legacy callers without `operation_id` keep their first-scan validation-error HTTP 422 behavior. Opt-in callers receive a confirmed zero-commit scan-error receipt when the first attempted scan faults: `completed_steps=0`, `last=null`, unchanged snapshot/history, and the existing known session retained. A newly created zero-commit session is discarded and returns `session=null`, with no observation source. If a later scan in a batch faults, only earlier successful scans count, and their exact history, UTC, state and optional observation records remain. The failed scan's candidate inputs, forces, UTC and state do not commit. All scan errors stop paced Run and require explicit recovery; partial batches are never replayed automatically. Recording failures are separate from successfully executed scans and also stop pacing for review.

The optional **Next scan UTC clock** belongs to simulation time, not the host monotonic clock. Apply it using Step before Run. A failed scan does not consume that pending UTC value. Subsequent scans advance UTC by the unchanged project timestep. Pausing and resuming do not substitute the host's current calendar time.

## Source and scope

Controller Tool Help 18.0, LIT-12011147, PDF pages 266–271 describes 1–10× acceleration, elapsed time, manual pause/run/single-step, dialog/edit pauses and separate refresh intervals. Reviewed PDF SHA-256: `68935362c85cb1879dc033cc701115e8ea7c4ecb26748f21a9ceaf0454f82903`. [Official Help](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/18.0).

This implements an explicit portable-graph pacing and pause policy inspired by those functions. It does not execute native CAF logic, emulate JCI firmware, validate physical actuator stroke times or open field interfaces. Native CCT/PCT pause/speed equivalence and break-condition authoring remain separate gaps. The graph trace retains its existing bounded history; CSV exports retained rows rather than asserting that every scan in a long run is still present. No hard real-time performance or Title 24/Guideline 36 certification is claimed.

## Verification

Authored pure-controller tests use hand-selected monotonic timestamps to verify speed/credit arithmetic, fixed scans, achieved rate, bounded batches/budgets, partial commits, pending pause, no paused-time catch-up, lag, long scan intervals, bad clocks and duplicate/wrong completions. Production API tests verify timer thresholds, retained state/quality/forces/UTC, optional receipt identity, partial and zero-commit faults, observation-source cleanup, legacy behavior and closed field interfaces. Actual browser/API workflows test paced execution and independently parsed CSV values/timestamps, pause/resume, delayed admitted replies after pause/reset/source changes, navigation, explicit UTC, known-fault recovery, delayed scenario admission/reset/source/failure races and uncertain-response locks. Visibility-handler tests explicitly dispatch visibility events; they do not certify every operating system's background-tab scheduling.
