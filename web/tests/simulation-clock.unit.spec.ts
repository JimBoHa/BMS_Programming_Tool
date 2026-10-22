import { test, expect } from "@playwright/test";
import { SimulationClock, MAX_BATCH } from "../src/simulationClock";

test("fixed scans, selected speed and measured achieved rate use monotonic elapsed time", () => {
  const c = new SimulationClock(0.25, 5, 10);
  c.resume(1000);
  expect(c.reserve(1049)).toBeNull();
  const first = c.reserve(1050)!;
  expect(first.steps).toBe(1);
  expect(c.reserve(1080)).toBeNull(); // one admitted batch, regardless of elapsed credit
  c.finish(first, 1, 1100);
  expect(c.snapshot().simulatedSeconds).toBe(0.25);
  expect(c.snapshot().achievedSpeed).toBe(2.5);
  expect(c.snapshot().requestedSpeed).toBe(5);
  const next = c.reserve(1100)!;
  expect(next.steps).toBe(1);
  c.finish(next, 1, 1100);
  expect(c.snapshot().achievedSpeed).toBe(5);
});
test("pause drains admitted commits, freezes clock, resumes without paused-time or stale-credit catch-up", () => {
  const c = new SimulationClock(1, 10, 10);
  c.resume(0);
  const ticket = c.reserve(100)!;
  c.pause(110);
  expect(c.snapshot().status).toBe("pausing");
  expect(c.reserve(1000)).toBeNull();
  c.finish(ticket, 1, 1000);
  expect(c.snapshot().status).toBe("paused");
  expect(c.snapshot().completedScans).toBe(1);
  const seconds = c.snapshot().activeSeconds;
  expect(c.reserve(90000)).toBeNull();
  expect(c.snapshot().activeSeconds).toBe(seconds);
  c.resume(100000);
  expect(c.reserve(100099)).toBeNull();
  expect(c.reserve(100100)!.steps).toBe(1);
});
for (const reason of [
  "Paused because this browser page is hidden.",
  "Paused on workspace navigation.",
  "Paused by operator.",
])
  test(`successful admitted completion retains its explicit pause cause: ${reason}`, () => {
    const c = new SimulationClock(1, 10, 10);
    c.resume(0);
    const ticket = c.reserve(100)!;
    c.pause(110, reason);
    expect(c.snapshot().status).toBe("pausing");
    expect(c.snapshot().reason).toContain(reason);
    expect(c.snapshot().reason).toContain("Waiting for the admitted batch");
    c.finish(ticket, 1, 150);
    expect(c.snapshot()).toMatchObject({
      status: "paused",
      completedScans: 1,
      pendingScans: 0,
    });
    expect(c.snapshot().reason).toContain(reason);
    expect(c.snapshot().reason).not.toContain("Waiting");
    expect(c.snapshot().reason).toContain("final admitted batch is displayed");
    c.resume(200);
    expect(c.snapshot().reason).not.toContain(reason);
  });
for (const outcome of ["fault", "complete"] as const)
  test(`pending pause retains ${outcome} precedence over its pause cause`, () => {
    const c = new SimulationClock(1, 10, outcome === "complete" ? 1 : 10);
    c.resume(0);
    const ticket = c.reserve(100)!;
    c.pause(110, "Paused because this browser page is hidden.");
    c.finish(ticket, 1, 150, outcome === "fault" ? "native scan failed" : "");
    expect(c.snapshot().status).toBe(outcome);
    expect(c.snapshot().reason).toContain(
      outcome === "fault" ? "native scan failed" : "Run budget reached",
    );
    expect(c.snapshot().reason).not.toContain("hidden");
  });
test("batches and total scan budget remain bounded at100x", () => {
  const c = new SimulationClock(0.001, 100, 201);
  c.resume(0);
  const one = c.reserve(10)!;
  expect(one.steps).toBe(MAX_BATCH);
  c.finish(one, 100, 10);
  const two = c.reserve(10)!;
  expect(two.steps).toBe(100);
  c.finish(two, 100, 10);
  const three = c.reserve(10)!;
  expect(three.steps).toBe(1);
  c.finish(three, 1, 10);
  expect(c.snapshot().status).toBe("complete");
  expect(c.snapshot().remainingScans).toBe(0);
  expect(c.reserve(11)).toBeNull();
  expect(() => c.resume(12)).toThrow(/budget/);
});
test("long scan intervals wait instead of tripping short generic lag limit", () => {
  const c = new SimulationClock(60, 1, 10);
  c.resume(0);
  expect(c.reserve(59000)).toBeNull();
  expect(c.reserve(60000)!.steps).toBe(1);
});
test("CPU/network lag pauses explicitly rather than silently dropping or replaying unlimited credit", () => {
  const c = new SimulationClock(1, 100, 1000);
  c.resume(0);
  expect(c.reserve(6000)).toBeNull();
  expect(c.snapshot().status).toBe("paused");
  expect(c.snapshot().reason).toMatch(/lag limit/);
  expect(c.snapshot().completedScans).toBe(0);
  c.resume(7000);
  expect(c.reserve(7000)).toBeNull();
});
test("partial committed batches retain exact count and stop on fault", () => {
  const c = new SimulationClock(1, 10, 10);
  c.resume(0);
  const ticket = c.reserve(300)!;
  expect(ticket.steps).toBe(3);
  c.finish(ticket, 1, 310, "division by zero");
  expect(c.snapshot().completedScans).toBe(1);
  expect(c.snapshot().status).toBe("fault");
  expect(c.reserve(1000)).toBeNull();
});
test("wrong/duplicate completion and impossible counts never alter committed accounting", () => {
  const c = new SimulationClock(1, 10, 10);
  c.resume(0);
  const ticket = c.reserve(100)!;
  for (const wrong of [-1, 0.5, 2, NaN])
    expect(() => c.finish(ticket, wrong, 100)).toThrow(/completion/);
  expect(() => c.finish({ ...ticket, id: 99 }, 1, 100)).toThrow(/completion/);
  expect(c.snapshot().completedScans).toBe(0);
  c.finish(ticket, 1, 100);
  expect(() => c.finish(ticket, 1, 100)).toThrow(/completion/);
  expect(c.snapshot().completedScans).toBe(1);
});
test("monotonic rollback and nonfinite clocks are rejected", () => {
  const c = new SimulationClock(1, 1, 10);
  c.resume(100);
  expect(() => c.reserve(99)).toThrow(/monotonic/);
  expect(() => c.reserve(Infinity)).toThrow(/monotonic/);
  c.pause(110);
  expect(() => c.resume(109)).toThrow(/monotonic/);
});
for (const args of [
  [0, 1, 1],
  [61, 1, 1],
  [NaN, 1, 1],
  [1, 3, 1],
  [1, Infinity, 1],
  [1, 1, 0],
  [1, 1, 1.5],
  [1, 1, 10001],
  [60, 1, 1441],
])
  test(`reject invalid finite pacing settings ${args}`, () =>
    expect(
      () => new SimulationClock(...(args as [number, number, number])),
    ).toThrow(/supported speed/));
test("one-hour active budget ends even with scan budget remaining", () => {
  const c = new SimulationClock(60, 100, 1440);
  c.resume(0);
  expect(c.reserve(3600000)).toBeNull();
  expect(c.snapshot().status).toBe("complete");
  expect(c.snapshot().reason).toMatch(/wall-time/);
});

test("tiny positive scan duration receives no absolute epsilon credit at zero elapsed time", () => {
  const c = new SimulationClock(1e-12, 1, 10);
  c.resume(0);
  expect(c.reserve(0)).toBeNull();
  const next = c.reserve(1e-9)!;
  expect(next.steps).toBe(1);
});
