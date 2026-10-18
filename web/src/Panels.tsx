import { useState } from "react";
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
}: {
  node?: BmsNode;
  block?: Block;
  onEdit: (node: BmsNode) => void;
  onDelete: () => void;
  onDuplicate: () => void;
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
    if (node) onEdit({ ...node, params: { ...node.params, [key]: value } });
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
            placeholder="e.g. degF, %, cfm"
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
      </div>
    </aside>
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
}) {
  const [expanded, setExpanded] = useState(false);
  const [events, setEvents] = useState(
    '[{"time":0,"inputs":{"zone":74}},{"time":30,"inputs":{"zone":66}},{"time":60,"inputs":{"zone":76}}]',
  );
  const [scenarioError, setScenarioError] = useState("");
  function csv() {
    const columns = program.nodes.map((n) => n.id);
    const quote = (v: any) => '"' + String(v ?? "").replaceAll('"', '""') + '"';
    const text = [
      ["seconds", ...columns].map(quote).join(","),
      ...history.map((r) =>
        [r.time, ...columns.map((c) => r.values[c])].map(quote).join(","),
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
        </div>
      </div>
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
            Timed input events (JSON). Times are simulation seconds.
            <textarea
              value={events}
              onChange={(e) => setEvents(e.target.value)}
            />
          </label>
          <button
            onClick={async () => {
              try {
                setRunning(false);
                const r = await api("/simulation/scenario", {
                  program,
                  events: JSON.parse(events),
                  duration: 90,
                });
                onScenario(r.history);
                setScenarioError("");
              } catch (e) {
                setScenarioError(String(e));
              }
            }}
          >
            Run 90-second scenario
          </button>
          {scenarioError && <p className="inline-error">{scenarioError}</p>}
        </div>
      )}
    </section>
  );
}
