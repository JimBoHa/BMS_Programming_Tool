import { useEffect, useState } from "react";
import {
  Play,
  Pause,
  SkipForward,
  RotateCcw,
  Download,
  AlertCircle,
  Activity,
  Trash2,
  Copy,
  Settings2,
} from "lucide-react";
import type { Block, BmsNode, Program, Scan } from "./types";
import { showValue } from "./types";
import { api, saveBlob } from "./api";

export function Inspector({
  node,
  block,
  onEdit,
  onDelete,
  onDuplicate,
  program,
  onSelect,
  forces,
  onForceChange,
  last,
}: {
  node?: BmsNode;
  block?: Block;
  onEdit: (node: BmsNode) => void;
  onDelete: () => void;
  onDuplicate: () => void;
  program: Program;
  onSelect: (id: string) => void;
  forces: Record<string, number | boolean>;
  onForceChange: (forces: Record<string, number | boolean>) => void;
  last?: Scan;
}) {
  if (!node || !block)
    return (
      <aside className="inspector">
        <div className="panel-heading">
          <Settings2 size={16} /> PROPERTIES
        </div>
        <div className="inspector-empty">
          Select a block to configure its properties and engineering units.
        </div>
        <div className="tip">
          <b>Wiring tips</b>
          <p>
            Connect an output pin to a named input pin. Every required input
            needs one source.
          </p>
          <p>Use one-scan memory to close a feedback loop.</p>
        </div>
      </aside>
    );
  const p = { ...block.parameters, ...node.params };
  function param(key: string, value: any) {
    if (node) {
      let unit = node.unit;
      if (key === "unit" && node.kind === "TemperatureDifference")
        unit =
          { degF: "delta-degF", degC: "delta-degC", K: "delta-K" }[
            value as "degF" | "degC" | "K"
          ] || node.unit;
      if (key === "unit" && node.kind === "TemperatureOffset") unit = value;
      if (key === "to" && node.kind === "DeltaConvert") unit = value;
      onEdit({ ...node, unit, params: { ...node.params, [key]: value } });
    }
  }
  return (
    <aside className="inspector">
      <div className="panel-heading">
        <Settings2 size={16} /> BLOCK PROPERTIES
      </div>
      <div className="inspector-body">
        <span className="pill">{block.category}</span>
        <h3>{block.title}</h3>
        <label>
          Label
          <input
            value={node.label}
            onChange={(e) => onEdit({ ...node, label: e.target.value })}
          />
        </label>
        <label>
          Identifier
          <input value={node.id} readOnly className="mono" />
        </label>
        {["Input", "Output", "Constant", "Delay", "Switch"].includes(
          node.kind,
        ) && (
          <label>
            Value type
            <select
              value={node.value_type}
              onChange={(e) => {
                const value_type = e.target.value as "number" | "boolean";
                const params = { ...node.params };
                for (const k of ["value", "default", "initial"])
                  if (k in block.parameters)
                    params[k] = value_type === "boolean" ? false : 0;
                onEdit({
                  ...node,
                  value_type,
                  params,
                  unit: value_type === "boolean" ? "" : node.unit,
                });
              }}
            >
              <option value="number">Number</option>
              <option value="boolean">Boolean</option>
            </select>
          </label>
        )}
        <label>
          Engineering units
          <input
            placeholder="e.g. degF, delta-degF, %, cfm"
            value={node.unit}
            onChange={(e) => onEdit({ ...node, unit: e.target.value })}
          />
        </label>
        <div className="small-heading">PARAMETERS</div>
        {Object.entries(p).map(([key, value]) => (
          <label key={key}>
            {key.replaceAll("_", " ")}
            {typeof value === "boolean" ? (
              <input
                type="checkbox"
                checked={value}
                onChange={(e) => param(key, e.target.checked)}
              />
            ) : Array.isArray(value) && key === "exceptions" ? (
              <JsonParameter value={value} onChange={(v) => param(key, v)} />
            ) : Array.isArray(value) ? (
              <input
                value={value.join(",")}
                onChange={(e) =>
                  param(
                    key,
                    e.target.value.split(",").filter(Boolean).map(Number),
                  )
                }
              />
            ) : (
              <input
                type={typeof value === "number" ? "number" : "text"}
                step="any"
                value={value}
                onChange={(e) =>
                  param(
                    key,
                    typeof value === "number"
                      ? Number(e.target.value)
                      : e.target.value,
                  )
                }
              />
            )}
          </label>
        ))}
        {block.help && <p className="help-text">{block.help}</p>}
        <div className="button-row">
          <button onClick={onDuplicate}>
            <Copy size={14} /> Duplicate
          </button>
          <button className="danger" onClick={onDelete}>
            <Trash2 size={14} /> Delete
          </button>
        </div>
        <ForceEditor
          key={node.id + ":" + node.value_type}
          node={node}
          block={block}
          forces={forces}
          onChange={onForceChange}
          last={last}
        />
        <DependencyView program={program} node={node.id} onSelect={onSelect} />
      </div>
    </aside>
  );
}

function JsonParameter({
  value,
  onChange,
}: {
  value: unknown[];
  onChange: (v: unknown[]) => void;
}) {
  const [text, setText] = useState(JSON.stringify(value, null, 2));
  const [error, setError] = useState("");
  useEffect(() => {
    setText(JSON.stringify(value, null, 2));
    setError("");
  }, [JSON.stringify(value)]);
  return (
    <>
      <textarea
        aria-label="Calendar exception JSON"
        rows={7}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <button
        type="button"
        onClick={() => {
          try {
            const parsed = JSON.parse(text);
            if (!Array.isArray(parsed))
              throw new Error("Use a JSON array of date exceptions.");
            onChange(parsed);
            setError("");
          } catch (e) {
            setError(String(e));
          }
        }}
      >
        Apply calendar exceptions
      </button>
      {error && <span className="inline-error">{error}</span>}
    </>
  );
}

function ForceEditor({
  node,
  block,
  forces,
  onChange,
  last,
}: {
  node: BmsNode;
  block: Block;
  forces: Record<string, number | boolean>;
  onChange: (forces: Record<string, number | boolean>) => void;
  last?: Scan;
}) {
  const boolean =
    ["Input", "Constant"].includes(node.kind) || block.output === "same"
      ? node.value_type === "boolean"
      : block.output === "boolean";
  const initial =
    forces[node.id] ??
    last?.values[node.id] ??
    node.params.value ??
    node.params.default ??
    (boolean ? false : 0);
  const [value, setValue] = useState(String(initial));
  const [error, setError] = useState("");
  const requested = Object.hasOwn(forces, node.id);
  const applied = !!last?.forces && Object.hasOwn(last.forces, node.id);
  return (
    <div className="simulation-force">
      <div className="small-heading">SIMULATION FORCE</div>
      <label>
        Held output value
        {boolean ? (
          <select
            aria-label="Simulation force value"
            value={value}
            onChange={(e) => setValue(e.target.value)}
          >
            <option value="true">TRUE</option>
            <option value="false">FALSE</option>
          </select>
        ) : (
          <input
            type="number"
            step="any"
            aria-label="Simulation force value"
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
        )}
      </label>
      <button
        onClick={() => {
          const next = boolean ? value === "true" : Number(value);
          if (
            typeof next === "number" &&
            (!value.trim() || !Number.isFinite(next))
          ) {
            setError("Enter a finite force value.");
            return;
          }
          setError("");
          onChange({ ...forces, [node.id]: next });
        }}
      >
        Hold simulation value
      </button>
      <button
        disabled={!requested}
        onClick={() => {
          const next = { ...forces };
          delete next[node.id];
          onChange(next);
        }}
      >
        Release simulation force
      </button>
      {error && <p className="inline-error">{error}</p>}
      <p className="force-status">
        Next scan: {requested ? showValue(forces[node.id]) : "automatic"}. Last
        completed scan:{" "}
        {applied ? showValue(last?.forces?.[node.id]) : "automatic"}.
      </p>
      <p className="help-text">
        Applies after the block computes. Internal state continues; source
        faults still stop the scan. Changes apply on the next successful scan
        and stay inside this graph simulation.
      </p>
    </div>
  );
}

function DependencyView({
  program,
  node,
  onSelect,
}: {
  program: Program;
  node: string;
  onSelect: (id: string) => void;
}) {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    setData(null);
    setError("");
    const timer = setTimeout(() => {
      api("/dependencies", { program, node })
        .then((result) => {
          if (live) setData(result);
        })
        .catch((e) => {
          if (live) setError(String(e));
        });
    }, 150);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [program, node]);
  return (
    <div className="dependency-view">
      <div className="small-heading">DEPENDENCIES AND EDIT IMPACT</div>
      {error && <p className="inline-error">{error}</p>}
      {data ? (
        <>
          <small>
            {data.incoming.length} direct sources · {data.outgoing.length}{" "}
            direct consumers
          </small>
          <p>
            {data.affected_outputs.length} affected{" "}
            {data.affected_outputs.length === 1 ? "output" : "outputs"}
          </p>
          {data.affected_outputs.map((n: any) => (
            <button key={n.id} onClick={() => onSelect(n.id)}>
              Trace {n.label || n.id}
            </button>
          ))}
          <details>
            <summary>Upstream blocks ({data.upstream.length})</summary>
            {data.upstream.map((n: any) => (
              <button key={n.id} onClick={() => onSelect(n.id)}>
                {n.label || n.id} <small>{n.kind}</small>
              </button>
            ))}
          </details>
          <details>
            <summary>Downstream blocks ({data.downstream.length})</summary>
            {data.downstream.map((n: any) => (
              <button key={n.id} onClick={() => onSelect(n.id)}>
                {n.label || n.id} <small>{n.kind}</small>
              </button>
            ))}
          </details>
          {data.feedback_boundaries.length > 0 && (
            <p className="help-text">
              {data.feedback_boundaries.length} feedback{" "}
              {data.feedback_boundaries.length === 1
                ? "boundary crosses"
                : "boundaries cross"}{" "}
              a previous-scan memory block. Effects can continue on later scans.
            </p>
          )}
          {data.scan_index === null && (
            <p className="inline-error">
              Combinational cycle prevents an execution order.
            </p>
          )}
          {data.native_extension_present && (
            <p className="help-text">
              This traces the core graph. Inspect added native branches in
              Native sim.
            </p>
          )}
        </>
      ) : (
        !error && <small>Tracing connections…</small>
      )}
    </div>
  );
}

export function Trend({
  history,
  program,
}: {
  history: Scan[];
  program: Program;
}) {
  const outputs = program.nodes.filter((n) => n.kind === "Output");
  const colors = ["#0d9488", "#e98d43", "#7c74d6", "#e35b75"];
  if (history.length < 1)
    return (
      <div className="trend-empty">
        <Activity size={22} />
        <span>Run simulation to trace outputs.</span>
      </div>
    );
  const rows = history.slice(-180);
  const start = rows[0].time;
  const end = rows.at(-1)!.time;
  return (
    <div className="trend">
      <svg
        viewBox="0 0 700 130"
        role="img"
        aria-label="Simulation output trends"
        preserveAspectRatio="none"
      >
        {[15, 45, 75, 105].map((y) => (
          <line key={y} x1={0} x2={700} y1={y} y2={y} stroke="#e4ebee" />
        ))}
        {outputs.map((n, i) => {
          const values = rows.map((r) => Number(r.outputs[n.id] ?? 0));
          const min = Math.min(0, ...values),
            max = Math.max(1, ...values);
          return (
            <polyline
              key={n.id}
              fill="none"
              stroke={colors[i % 4]}
              strokeWidth={2}
              points={rows
                .map(
                  (r, j) =>
                    `${((r.time - start) / (end - start || 1)) * 690 + 5},${110 - ((values[j] - min) / (max - min || 1)) * 95}`,
                )
                .join(" ")}
            />
          );
        })}
      </svg>
      <div className="trend-legend">
        {outputs.map((n, i) => (
          <span key={n.id}>
            <i style={{ background: colors[i % 4] }} />
            {n.label || n.id}: {showValue(rows.at(-1)?.outputs[n.id])} {n.unit}
          </span>
        ))}
        <small>
          {start.toFixed(0)}–{end.toFixed(0)} s · per-series scale
        </small>
      </div>
    </div>
  );
}

export function SimulationPanel({
  program,
  history,
  inputs,
  setInputs,
  running,
  setRunning,
  onStep,
  onReset,
  onScenario,
  error,
  forces,
  onReleaseForces,
  recordHistory,
  setRecordHistory,
  recordingError,
  nextClock,
  setNextClock,
}: {
  program: Program;
  history: Scan[];
  inputs: Record<string, any>;
  setInputs: (v: Record<string, any>) => void;
  running: boolean;
  setRunning: (v: boolean) => void;
  onStep: () => void;
  onReset: () => void;
  onScenario: (h: Scan[]) => void;
  error: string;
  forces: Record<string, number | boolean>;
  onReleaseForces: () => void;
  recordHistory: boolean;
  setRecordHistory: (v: boolean) => void;
  recordingError: string;
  nextClock: string;
  setNextClock: (v: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [events, setEvents] = useState(
    '[{"time":0,"inputs":{"zone":74}},{"time":30,"inputs":{"zone":66}},{"time":60,"inputs":{"zone":76}}]',
  );
  const [scenarioError, setScenarioError] = useState("");
  const [duration, setDuration] = useState(90);
  function csv() {
    const columns = program.nodes.map((n) => n.id);
    const quote = (v: any) => '"' + String(v ?? "").replaceAll('"', '""') + '"';
    const text = [
      ["seconds", "clock", ...columns, "force_overrides", "computed_values"]
        .map(quote)
        .join(","),
      ...history.map((r) =>
        [
          r.time,
          r.clock,
          ...columns.map((c) => r.values[c]),
          JSON.stringify(r.forces || {}),
          JSON.stringify(r.computed || {}),
        ]
          .map(quote)
          .join(","),
      ),
    ].join("\n");
    saveBlob(
      new Blob([text], { type: "text/csv" }),
      program.id + "-simulation.csv",
    );
  }
  return (
    <section className="simulation">
      <div className="simulation-bar">
        <div className="section-title">
          <Activity size={17} />
          <b>Simulation</b>
          <span className={"status-dot " + (running ? "on" : "")} />
          <small>{running ? "RUNNING" : "OFFLINE"}</small>
        </div>
        <div className="button-row">
          <label className="record-toggle">
            <input
              type="checkbox"
              checked={recordHistory}
              onChange={(e) => setRecordHistory(e.target.checked)}
            />
            Persist history
          </label>
          <span className="elapsed">
            {history.at(-1)?.time.toFixed(1) || "0.0"} s
          </span>
          <button
            onClick={() => setRunning(!running)}
            className={running ? "" : "primary"}
            title={running ? "Pause simulation" : "Run simulation"}
          >
            {running ? <Pause size={14} /> : <Play size={14} />}{" "}
            {running ? "Pause" : "Run"}
          </button>
          <button
            onClick={onStep}
            title="Step simulation"
            aria-label="Step simulation"
          >
            <SkipForward size={14} /> Step
          </button>
          <button onClick={onReset} title="Reset simulation">
            <RotateCcw size={14} />
          </button>
          <button
            onClick={csv}
            disabled={!history.length}
            title="Export simulation CSV"
          >
            <Download size={14} />
          </button>
          <button onClick={() => setExpanded(!expanded)}>
            {expanded ? "Hide scenarios" : "Scenarios"}
          </button>
          {!!Object.keys(forces).length && (
            <button onClick={onReleaseForces}>
              Release all forces ({Object.keys(forces).length})
            </button>
          )}
        </div>
      </div>
      {recordingError && (
        <div className="inline-error">
          Scan completed; history recording failed: {recordingError}
        </div>
      )}
      <label className="simulation-clock">
        Next scan UTC clock (optional)
        <input
          type="datetime-local"
          aria-label="Next scan UTC clock"
          value={nextClock}
          onChange={(e) => setNextClock(e.target.value)}
          step="1"
        />
      </label>
      <div className="simulation-content">
        <div className="sim-inputs">
          {program.nodes
            .filter((n) => n.kind === "Input")
            .map((n) => {
              const current = inputs[n.id] ?? n.params.default ?? 0;
              const value =
                typeof current === "object" ? current.value : current;
              const quality =
                typeof current === "object" ? current.quality : "good";
              const change = (v: any, q = quality) =>
                setInputs({
                  ...inputs,
                  [n.id]: q === "good" ? v : { value: v, quality: q },
                });
              return (
                <div className="sim-input" key={n.id}>
                  <label>
                    {n.label || n.id}
                    <b>
                      {showValue(value)} {n.unit}
                    </b>
                  </label>
                  {n.value_type === "boolean" ? (
                    <input
                      aria-label={"Simulate " + n.id}
                      type="checkbox"
                      checked={!!value}
                      onChange={(e) => change(e.target.checked)}
                    />
                  ) : (
                    <input
                      aria-label={"Simulate " + n.id}
                      type="number"
                      step="any"
                      value={value}
                      onChange={(e) => change(Number(e.target.value))}
                    />
                  )}
                  <select
                    aria-label={"Quality " + n.id}
                    value={quality}
                    onChange={(e) => change(value, e.target.value)}
                  >
                    <option value="good">Good quality</option>
                    <option value="open-circuit">Open circuit</option>
                    <option value="stale">Stale</option>
                    <option value="missing">Missing</option>
                  </select>
                </div>
              );
            })}
          {!program.nodes.some((n) => n.kind === "Input") && (
            <small>Add input blocks to inject values.</small>
          )}
        </div>
        <Trend history={history} program={program} />
      </div>
      {error && (
        <div className="inline-error">
          <AlertCircle size={15} />
          {error}
        </div>
      )}
      {expanded && (
        <div className="scenario">
          <label>
            Timed events (JSON). Inputs update existing values; forces replaces
            the override map. Use forces: {"{}"} to release all.
            <textarea
              aria-label="Timed simulation events"
              value={events}
              onChange={(e) => setEvents(e.target.value)}
            />
          </label>
          <label>
            Duration (seconds)
            <input
              type="number"
              min="0.01"
              max="86400"
              aria-label="Scenario duration seconds"
              value={duration}
              onChange={(e) => setDuration(Number(e.target.value))}
            />
          </label>
          <button
            onClick={async () => {
              try {
                setRunning(false);
                const r = await api("/simulation/scenario", {
                  program,
                  events: JSON.parse(events),
                  duration,
                  forces,
                });
                onScenario(r.history);
                setScenarioError("");
              } catch (e) {
                setScenarioError(String(e));
              }
            }}
          >
            Run scenario
          </button>
          {scenarioError && <p className="inline-error">{scenarioError}</p>}
        </div>
      )}
    </section>
  );
}
