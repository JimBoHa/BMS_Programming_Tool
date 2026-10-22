import { useEffect, useRef, useState } from "react";
import { SimulationClock } from "./simulationClock";
export type BatchResult = {
  completed_steps: number;
  scan_error?: string;
  recording_error?: string;
};
export function useSimulationClock({
  source,
  active,
  scanSeconds,
  blocked,
  batch,
}: {
  source: unknown;
  active: boolean;
  scanSeconds: number;
  blocked: boolean;
  batch: (steps: number) => Promise<BatchResult | undefined>;
}) {
  const [speed, setSpeed] = useState(1),
    [limit, setLimit] = useState(1000);
  const [report, setReport] = useState<ReturnType<
    SimulationClock["snapshot"]
  > | null>(null);
  const clockSource = useRef(source);
  const clock = useRef<SimulationClock | null>(null),
    generation = useRef(0),
    pending = useRef(false);
  const current = useRef({
    source,
    active,
    scanSeconds,
    blocked,
    batch,
    speed,
    limit,
  });
  current.current = {
    source,
    active,
    scanSeconds,
    blocked,
    batch,
    speed,
    limit,
  };
  function publish() {
    setReport(clock.current?.snapshot() || null);
  }
  function retire() {
    generation.current++;
    clock.current = null;
    setReport(null);
  }
  function pause(reason?: string) {
    clock.current?.pause(performance.now(), reason);
    publish();
  }
  function run() {
    const value = current.current;
    if (value.blocked || pending.current || !value.active || document.hidden)
      return;
    try {
      if (clock.current?.status === "fault")
        throw new Error(
          "Run stopped after a fault or unconfirmed response. Reset, or explicitly single-step retained state before starting another run window.",
        );
      if (
        !clock.current ||
        clock.current.status === "complete" ||
        clock.current.speed !== value.speed ||
        clock.current.limit !== value.limit
      )
        clock.current = new SimulationClock(
          value.scanSeconds,
          value.speed,
          value.limit,
        );
      clockSource.current = value.source;
      clock.current.resume(performance.now());
      publish();
    } catch (e) {
      setReport({
        status: "fault",
        reason: String(e),
        requestedSpeed: value.speed,
        achievedSpeed: 0,
        completedScans: 0,
        remainingScans: 0,
        pendingScans: 0,
        activeSeconds: 0,
        simulatedSeconds: 0,
        lagSeconds: 0,
      });
    }
  }
  useEffect(() => {
    retire();
  }, [source]);
  useEffect(() => {
    if (!active)
      pause(
        "Paused on workspace navigation. Return and press Run explicitly; no navigation-time catch-up.",
      );
  }, [active]);
  useEffect(() => {
    const visibility = () => {
      if (document.hidden)
        pause(
          "Paused because this browser page is hidden. Press Run explicitly on return; no hidden-time catch-up.",
        );
    };
    document.addEventListener("visibilitychange", visibility);
    let alive = true;
    const timer = setInterval(async () => {
      const owned = clock.current,
        value = current.current;
      if (
        !alive ||
        !owned ||
        owned.status !== "running" ||
        pending.current ||
        value.blocked ||
        !value.active ||
        document.hidden
      )
        return;
      if (clockSource.current !== value.source) {
        retire();
        return;
      }
      const epoch = generation.current,
        source = value.source;
      let ticket;
      try {
        ticket = owned.reserve(performance.now());
        publish();
      } catch (e) {
        pause(String(e));
        return;
      }
      if (!ticket) return;
      pending.current = true;
      try {
        const result = await value.batch(ticket.steps);
        if (
          !alive ||
          generation.current !== epoch ||
          clock.current !== owned ||
          current.current.source !== source
        )
          return;
        owned.finish(
          ticket,
          result?.completed_steps || 0,
          performance.now(),
          result?.scan_error ||
            result?.recording_error ||
            (!result
              ? "Batch was retired or refused; reset before running again."
              : ""),
        );
        publish();
      } catch (e) {
        if (
          alive &&
          generation.current === epoch &&
          clock.current === owned &&
          current.current.source === source
        ) {
          owned.finish(ticket, 0, performance.now(), String(e));
          publish();
        }
      } finally {
        pending.current = false;
      }
    }, 50);
    return () => {
      alive = false;
      generation.current++;
      clearInterval(timer);
      document.removeEventListener("visibilitychange", visibility);
    };
  }, []);
  const running = report?.status === "running";
  return {
    speed,
    setSpeed,
    limit,
    setLimit,
    report,
    running,
    run,
    pause,
    retire,
  };
}
