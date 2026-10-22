import { sourceStringify } from "./programSource";
import { useEffect, useRef, useState } from "react";
import { Cpu, Play, Pause, ShieldCheck, RotateCcw } from "lucide-react";
import { programApi } from "./api";
import type { Program } from "./types";
import { showValue } from "./types";

export function RuntimePanel({
  program,
  inputs,
}: {
  program: Program;
  inputs: Record<string, any>;
}) {
  const [status, setStatus] = useState<any>(null),
    [plan, setPlan] = useState<any>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const mounted = useRef(false),
    active = useRef(false),
    statusEpoch = useRef(0),
    planEpoch = useRef(0);
  const key = sourceStringify({ program, inputs });
  const latest = useRef(key);
  latest.current = key;
  const currentPlan =
    plan?.key === key &&
    (!status || plan.result.generation === status.generation)
      ? plan.result
      : null;
  async function refresh() {
    const epoch = ++statusEpoch.current;
    const next = await programApi("/runtime");
    if (mounted.current && epoch === statusEpoch.current) setStatus(next);
  }
  useEffect(() => {
    mounted.current = true;
    let live = true;
    const update = () =>
      refresh().catch((e) => {
        if (live) setError(e.message);
      });
    update();
    const timer = setInterval(update, 1000);
    return () => {
      live = false;
      mounted.current = false;
      statusEpoch.current++;
      planEpoch.current++;
      clearInterval(timer);
    };
  }, []);
  useEffect(() => {
    planEpoch.current++;
    setPlan(null);
  }, [key]);
  async function action(fn: () => Promise<any>) {
    if (active.current) return;
    active.current = true;
    setBusy(true);
    setError("");
    statusEpoch.current++;
    try {
      await fn();
      if (mounted.current) await refresh();
    } catch (e) {
      if (mounted.current) setError(String(e));
    } finally {
      active.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  function preview() {
    if (active.current) return;
    const epoch = ++planEpoch.current;
    const snapshot = key;
    setPlan(null);
    action(async () => {
      const result = await programApi("/runtime/plan", { program, inputs });
      if (
        !mounted.current ||
        epoch !== planEpoch.current ||
        latest.current !== snapshot
      ) {
        if (mounted.current)
          setError(
            "Proposed application changed while previewing. Preview the current draft again.",
          );
        return;
      }
      setPlan({ key: snapshot, result });
    });
  }
  return (
    <div className="workspace-page">
      <div className="page-intro">
        <div>
          <span className="eyebrow">ONLINE APPLICATION CHANGES</span>
          <h1>Runtime</h1>
          <p>
            Validate, apply, and roll back graph revisions in the BMS Studio
            sandbox runtime.
          </p>
        </div>
        <Cpu size={34} />
      </div>
      <div className="notice">
        <ShieldCheck size={22} />
        <div>
          <b>Target: local sandbox runtime</b>
          <p>
            This runtime executes our graph format. JCI, ALC, Honeywell and
            Niagara field application downloads require their native compiler
            and download adapter. No field outputs are bound here.
          </p>
        </div>
      </div>
      <div className="stat-grid">
        <div>
          <small>ACTIVE PROGRAM</small>
          <strong>{status?.program?.name || "None deployed"}</strong>
        </div>
        <div>
          <small>GENERATION</small>
          <strong>{status?.generation ?? 0}</strong>
        </div>
        <div>
          <small>SCAN TIME</small>
          <strong>{status?.snapshot?.time.toFixed(1) || "0.0"} s</strong>
        </div>
        <div>
          <small>STATUS</small>
          <strong>{status?.control.running ? "Running" : "Stopped"}</strong>
        </div>
      </div>
      <div className="two-column">
        <section className="card">
          <div className="card-header">
            <h3>Proposed application</h3>
            <span className="pill">{program.nodes.length} blocks</span>
          </div>
          <div className="card-body">
            <h2>{program.name}</h2>
            <p>{program.description}</p>
            <button className="primary" disabled={busy} onClick={preview}>
              Validate and preview deployment
            </button>
            {currentPlan && (
              <>
                <div className="diff-summary">
                  <span>+{currentPlan.diff.added.length} added</span>
                  <span>−{currentPlan.diff.removed.length} removed</span>
                  <span>{currentPlan.diff.changed.length} changed</span>
                  <span>
                    {currentPlan.diff.wiring_changed
                      ? "Wiring changed"
                      : "Wiring unchanged"}
                  </span>
                </div>
                <pre className="result">
                  {JSON.stringify(currentPlan.preflight_outputs, null, 2)}
                </pre>
                <button
                  className="primary"
                  disabled={busy}
                  onClick={() =>
                    action(async () => {
                      if (latest.current !== key) return;
                      setPlan(null);
                      await programApi("/runtime/apply", {
                        token: currentPlan.token,
                      });
                    })
                  }
                >
                  Apply to sandbox runtime
                </button>
              </>
            )}
          </div>
        </section>
        <section className="card">
          <div className="card-header">
            <h3>Running application</h3>
            <button
              disabled={busy || !status?.program}
              onClick={() =>
                action(() =>
                  programApi("/runtime/control", {
                    running: !status?.control.running,
                    inputs,
                  }),
                )
              }
            >
              {status?.control.running ? (
                <Pause size={15} />
              ) : (
                <Play size={15} />
              )}{" "}
              {status?.control.running ? "Stop" : "Start"}
            </button>
          </div>
          <div className="card-body">
            {!status?.program ? (
              <p>Deploy a graph to start the local runtime.</p>
            ) : (
              <>
                <p className="mono hash">{status.snapshot.program_hash}</p>
                <div className="output-grid">
                  {Object.entries(status.snapshot.outputs).map(
                    ([id, value]) => (
                      <div key={id}>
                        <small>{id}</small>
                        <strong>{showValue(value)}</strong>
                      </div>
                    ),
                  )}
                </div>
                <p className="help-text">
                  Unchanged compatible control blocks retain state across online
                  edits. Changed control laws or wiring reset affected state.
                  Each successful change keeps a rollback snapshot.
                </p>
                {status.control.error && (
                  <p className="inline-error">{status.control.error}</p>
                )}
              </>
            )}
          </div>
        </section>
      </div>
      <section className="card">
        <div className="card-header">
          <h3>Application backups</h3>
        </div>
        {status?.backups?.length ? (
          <table>
            <thead>
              <tr>
                <th>Program</th>
                <th>Original generation</th>
                <th>Restore</th>
              </tr>
            </thead>
            <tbody>
              {status.backups.map((b: any) => (
                <tr key={b.id}>
                  <td>{b.name}</td>
                  <td>{b.generation}</td>
                  <td>
                    <button
                      disabled={busy}
                      onClick={() =>
                        action(() =>
                          programApi("/runtime/rollback", {
                            backup_id: b.id,
                            expected_generation: status.generation,
                          }),
                        )
                      }
                    >
                      <RotateCcw size={14} /> Roll back
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="empty-panel">
            Backups appear when a running application is replaced.
          </div>
        )}
      </section>
      {error && (
        <div className="inline-error" role="alert">
          {error}
        </div>
      )}
    </div>
  );
}
