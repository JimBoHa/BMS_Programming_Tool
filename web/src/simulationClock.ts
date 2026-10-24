/** Monotonic pacing only; simulation UTC and scan duration belong to Engine. */
export const SPEEDS = [1, 2, 5, 10, 20, 50, 100] as const;
export const MAX_BATCH = 100;
export const MAX_RUN_SCANS = 10000;
export const MAX_ACTIVE_SECONDS = 3600;
export type ClockStatus =
  | "idle"
  | "running"
  | "pausing"
  | "paused"
  | "complete"
  | "fault";
export type Ticket = { readonly id: number; readonly steps: number };
export class SimulationClock {
  status: ClockStatus = "idle";
  reason = "Ready. Run uses fixed scan durations; Step executes one scan.";
  completed = 0;
  activeSeconds = 0;
  private last = 0;
  private baselineSeconds = 0;
  private baselineScans = 0;
  private pauseCause = "";
  private ticket = 0;
  private pending: Ticket | null = null;
  constructor(
    readonly scanSeconds: number,
    readonly speed: number,
    readonly limit: number,
  ) {
    if (
      !Number.isFinite(scanSeconds) ||
      scanSeconds <= 0 ||
      scanSeconds > 60 ||
      !SPEEDS.includes(speed as (typeof SPEEDS)[number]) ||
      !Number.isInteger(limit) ||
      limit < 1 ||
      limit > MAX_RUN_SCANS ||
      limit * scanSeconds > 86400
    )
      throw new Error(
        "Use a supported speed, 1–10000 scans and at most 86400 simulated seconds per run.",
      );
  }
  private advance(now: number) {
    if (!Number.isFinite(now) || now < this.last)
      throw new Error("Host monotonic time moved backwards or is not finite.");
    if (this.status === "running" || this.status === "pausing")
      this.activeSeconds += (now - this.last) / 1000;
    this.last = now;
  }
  resume(now: number) {
    if (this.pending || this.status === "running" || this.status === "pausing")
      throw new Error("Wait for pause and the admitted batch before resuming.");
    if (!Number.isFinite(now) || now < this.last)
      throw new Error("Invalid monotonic time.");
    if (
      this.completed >= this.limit ||
      this.activeSeconds >= MAX_ACTIVE_SECONDS
    )
      throw new Error("This run budget is complete; start a new run window.");
    this.last = now;
    this.baselineSeconds = this.activeSeconds;
    this.baselineScans = this.completed;
    this.status = "running";
    this.pauseCause = "";
    this.reason =
      "Running. Inputs/holds apply to the next admitted batch; dialogs do not pause the clock.";
  }
  pause(
    now: number,
    reason = "Paused by operator. Resume retains scan state and discards unexecuted wall-time credit.",
  ) {
    this.advance(now);
    if (this.status !== "running" && this.status !== "pausing") return;
    this.pauseCause = reason;
    this.status = this.pending ? "pausing" : "paused";
    this.reason = this.pending
      ? reason +
        " Waiting for the admitted batch to finish; its committed result will be displayed."
      : reason;
  }
  reserve(now: number): Ticket | null {
    this.advance(now);
    if (this.status !== "running" || this.pending) return null;
    if (this.activeSeconds >= MAX_ACTIVE_SECONDS) {
      this.status = "complete";
      this.reason = "One-hour active wall-time budget reached.";
      return null;
    }
    const debt =
      (this.activeSeconds - this.baselineSeconds) * this.speed -
      (this.completed - this.baselineScans) * this.scanSeconds;
    // Permit long scan intervals, but never silently catch up after an unbounded stall.
    if (debt / this.speed > Math.max(5, (2 * this.scanSeconds) / this.speed)) {
      this.status = "paused";
      this.reason =
        "Pacing lag limit reached. Resume discards unexecuted wall-time credit; committed scans are retained.";
      return null;
    }
    const steps = Math.min(
      MAX_BATCH,
      this.limit - this.completed,
      Math.floor(debt / this.scanSeconds + 1e-9),
    );
    if (steps <= 0) return null;
    return (this.pending = Object.freeze({ id: ++this.ticket, steps }));
  }
  finish(ticket: Ticket, completed: number, now: number, error = "") {
    if (
      !this.pending ||
      ticket.id !== this.pending.id ||
      ticket.steps !== this.pending.steps ||
      !Number.isInteger(completed) ||
      completed < 0 ||
      completed > ticket.steps
    )
      throw new Error(
        "Batch completion does not match its exact admitted scan count.",
      );
    this.advance(now);
    this.completed += completed;
    this.pending = null;
    if (error || completed !== ticket.steps) {
      this.status = "fault";
      this.reason = error || "Batch ended before all admitted scans completed.";
    } else if (
      this.completed >= this.limit ||
      this.activeSeconds >= MAX_ACTIVE_SECONDS
    ) {
      this.status = "complete";
      this.reason =
        "Run budget reached. Start another run window or reset the simulation.";
    } else if (this.status === "pausing") {
      this.status = "paused";
      this.reason =
        this.pauseCause +
        " The final admitted batch is displayed; resume retains scan state without paused-time catch-up.";
    }
  }
  snapshot() {
    return {
      status: this.status,
      reason: this.reason,
      requestedSpeed: this.speed,
      achievedSpeed:
        this.activeSeconds > 0
          ? (this.completed * this.scanSeconds) / this.activeSeconds
          : 0,
      completedScans: this.completed,
      remainingScans: this.limit - this.completed,
      pendingScans: this.pending?.steps || 0,
      activeSeconds: this.activeSeconds,
      simulatedSeconds: this.completed * this.scanSeconds,
      lagSeconds: Math.max(
        0,
        (this.activeSeconds - this.baselineSeconds) * this.speed -
          (this.completed - this.baselineScans) * this.scanSeconds,
      ),
    };
  }
}
