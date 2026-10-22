import { numericToken, executionInput } from "./programSource";
import { sourceApi, programApi } from "./api";
import { useEffect, useMemo, useState } from "react";
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  Controls,
  Handle,
  Position,
  useReactFlow,
  type Connection,
  type NodeChange,
} from "@xyflow/react";
import {
  FlaskConical,
  Play,
  Square,
  SkipForward,
  RefreshCw,
  Plus,
  Check,
  RotateCcw,
  Download,
  Trash2,
} from "lucide-react";
import { api, download, saveBlob } from "./api";
import type { Program } from "./types";

type Operation = Record<string, string>;
const palette = [
  "types::WriteFloat",
  "types::ConstFloat",
  "types::WriteBool",
  "types::ConstBool",
  "math::Add2",
  "math::Sub2",
  "math::Mul2",
  "math::Div2",
  "math::Min",
  "math::Max",
];

function NativeBlock({ data, selected }: any) {
  const binary = data.type.startsWith("math::");
  const ports = binary
    ? ["in1", "in2"]
    : data.type.startsWith("types::Write")
      ? ["in"]
      : [];
  return (
    <div
      className={
        "native-block " +
        (selected ? "selected" : "") +
        (data.pending ? " proposed" : "")
      }
    >
      <b>{data.name}</b>
      <small>{data.type}</small>
      {ports.map((port: string, i: number) => (
        <div className="native-pin" key={port}>
          <Handle
            type="target"
            id={port}
            position={Position.Left}
            style={{ top: 63 + i * 24 }}
          />
          {port}
        </div>
      ))}
      <Handle
        type="source"
        id="out"
        position={Position.Right}
        style={{ top: 43 }}
      />
      <div className="native-result">
        {data.value === "null"
          ? "null / unconnected"
          : (data.value ?? "Pending")}
      </div>
    </div>
  );
}
const nodeTypes = { native: NativeBlock };

function NativeGraph({
  components,
  pending,
  queue,
  selected,
  setSelected,
}: any) {
  const [positions, setPositions] = useState<
    Record<string, { x: number; y: number }>
  >({});
  const flow = useReactFlow();
  const actual = components.filter((c: any) => c.path.startsWith("/online/"));
  const additions = pending
    .filter((op: Operation) => op.op === "add")
    .map((op: Operation) => ({
      path: op.path + "/" + op.name,
      type: op.type,
      properties: [],
      links: [],
      pending: true,
    }));
  const nodes = [...actual, ...additions].map((c: any, i) => ({
    id: c.path,
    type: "native",
    selected: c.path === selected,
    position: positions[c.path] || {
      x: 45 + (i % 3) * 245,
      y: 40 + Math.floor(i / 3) * 185,
    },
    data: {
      name: c.path.split("/").at(-1),
      type: c.type,
      pending: c.pending,
      value: c.properties.find((p: any) => p.name === "out")?.value,
    },
  }));
  const byId = new Map(actual.map((c: any) => [String(c.id), c]));
  const edges: any[] = [];
  actual.forEach((c: any) =>
    c.links.forEach((link: any) => {
      const target: any = byId.get(link.to);
      if (!target) return;
      edges.push({
        id: `${link.from}.${link.from_slot}-${link.to}.${link.to_slot}`,
        source: c.path,
        target: target.path,
        sourceHandle: c.properties.find((p: any) => p.id === link.from_slot)
          ?.name,
        targetHandle: target.properties.find((p: any) => p.id === link.to_slot)
          ?.name,
      });
    }),
  );
  pending
    .filter((p: Operation) => p.op === "link")
    .forEach((p: Operation, i: number) =>
      edges.push({
        id: "pending-" + i,
        source: p.path,
        target: p.target,
        sourceHandle: p.slot,
        targetHandle: p.target_slot,
        animated: true,
        style: { stroke: "#089c87", strokeDasharray: "5 4" },
      }),
    );
  function connect(c: Connection) {
    if (c.source && c.target && c.sourceHandle && c.targetHandle)
      queue([
        {
          op: "link",
          path: c.source,
          slot: c.sourceHandle,
          target: c.target,
          target_slot: c.targetHandle,
        },
      ]);
  }
  return (
    <div
      className="native-canvas"
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        e.preventDefault();
        const type = e.dataTransfer.getData("application/x-native-type");
        if (!palette.includes(type)) return;
        const name = "b" + Date.now().toString(36).slice(-5);
        const path = "/online/" + name;
        setPositions((p) => ({
          ...p,
          [path]: flow.screenToFlowPosition({ x: e.clientX, y: e.clientY }),
        }));
        queue([{ op: "add", path: "/online", type, name }]);
        setSelected(path);
      }}
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onConnect={connect}
        onNodeClick={(_, n) => setSelected(n.id)}
        onPaneClick={() => setSelected(null)}
        onNodesChange={(changes: NodeChange[]) =>
          changes.forEach((c) => {
            if (c.type === "position" && c.position)
              setPositions((p) => ({ ...p, [c.id]: c.position! }));
          })
        }
        onEdgeDoubleClick={(_, edge) => {
          if (!edge.id.startsWith("pending-"))
            queue([
              {
                op: "unlink",
                path: edge.source,
                slot: edge.sourceHandle!,
                target: edge.target,
                target_slot: edge.targetHandle!,
              },
            ]);
        }}
        minZoom={0.3}
        maxZoom={2}
      >
        <Background />
        <Controls />
      </ReactFlow>
      {!nodes.length && (
        <div className="native-canvas-empty">
          Drag a native block here, or add an unused input.
        </div>
      )}
    </div>
  );
}

export function NativeSimulator({
  program,
  onSaved,
}: {
  program: Program;
  onSaved: (program: Program) => void;
}) {
  const [status, setStatus] = useState<any>({
    running: false,
    history: [],
    backups: [],
  });
  const [components, setComponents] = useState<any[]>([]);
  const [inputs, setInputs] = useState<Record<string, any>>({});
  const [qualities, setQualities] = useState<Record<string, string>>({});
  const [pending, setPending] = useState<Operation[]>([]);
  const [plan, setPlan] = useState<any>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [clock, setClock] = useState("");
  const [newValue, setNewValue] = useState("0");
  const [nativeSlot, setNativeSlot] = useState("in");
  async function refresh() {
    const s = await sourceApi("/native/status");
    setStatus(s);
    if (s.running) setComponents((await api("/native/inventory")).components);
    else setComponents([]);
  }
  useEffect(() => {
    refresh().catch((e) => setError(String(e)));
  }, [program.id, program.revision]);
  async function action(work: () => Promise<any>) {
    setBusy(true);
    setError("");
    try {
      await work();
    } catch (e) {
      setError(String(e));
    } finally {
      try {
        await refresh();
      } catch (e) {
        setError((previous) => previous || String(e));
      }
      setBusy(false);
    }
  }
  function queue(ops: Operation[]) {
    setPending((p) => [...p, ...ops]);
    setPlan(null);
  }
  const loaded = status.program as Program | undefined;
  const inputNodes = useMemo(
    () => loaded?.nodes.filter((n) => n.kind === "Input") || [],
    [loaded],
  );
  const current = components.find((c) => c.path === selected);
  const selectedType =
    current?.type ||
    pending.find(
      (op) => op.op === "add" && op.path + "/" + op.name === selected,
    )?.type;
  const editableProperties = current
    ? current.properties.filter(
        (p: any) => p.config === "true" && p.name !== "meta",
      )
    : selectedType?.startsWith("types::Const")
      ? [{ name: "out" }]
      : selectedType?.startsWith("types::Write")
        ? [{ name: "in" }]
        : [];
  const editableSlot = editableProperties.some(
    (p: any) => p.name === nativeSlot,
  )
    ? nativeSlot
    : editableProperties[0]?.name;
  const rows = status.history || [];
  return (
    <div className="workspace-page native-workspace">
      <div className="page-intro">
        <div>
          <span className="eyebrow">COMPILED CONTROLLER TESTING</span>
          <h1>Native simulator</h1>
          <p>
            Runs compiled Sedona code in its own controller process. I/O here is
            virtual.
          </p>
        </div>
        <FlaskConical size={32} />
      </div>
      <section className="card">
        <div className="card-body">
          <div className="native-toolbar">
            <div>
              <b>{status.running ? loaded?.name : program.name}</b>
              <small>
                {status.running ? status.address : "Simulator stopped"}
              </small>
              {status.source_generator && (
                <>
                  <small>
                    Literal profile: <code>{status.source_generator.id}</code>
                  </small>
                  <details>
                    <summary>Literal rules SHA-256</summary>
                    <code>{status.source_generator.rules_sha256}</code>
                  </details>
                </>
              )}
            </div>
            <button
              className="primary"
              disabled={busy || status.available === false}
              onClick={() =>
                action(async () => {
                  await sourceApi("/native/start", { program });
                  setInputs({});
                  setQualities({});
                  setPending([]);
                  setPlan(null);
                })
              }
            >
              <Play size={15} /> Compile and start
            </button>
            <button
              disabled={busy || !status.running}
              onClick={() =>
                action(async () => {
                  await api("/native/stop", {});
                  setPending([]);
                  setPlan(null);
                })
              }
            >
              <Square size={15} /> Stop native simulator
            </button>
            <button
              disabled={busy || !status.running}
              onClick={() =>
                action(async () => {
                  const saved = await sourceApi("/native/save", {
                    expected_revision: status.program.revision,
                  });
                  onSaved(saved);
                })
              }
            >
              Save native revision
            </button>
            <button
              disabled={busy || !status.running}
              onClick={() =>
                action(async () => {
                  await download(
                    "/native/export",
                    { format: "sedona" },
                    status.program.id + ".sedona.zip",
                  );
                })
              }
            >
              <Download size={15} /> Export native application
            </button>
            <button disabled={busy} onClick={() => action(refresh)}>
              <RefreshCw size={15} /> Refresh native values
            </button>
          </div>
          <p className="help-text">
            The generated kit and SCode image target this experimental Unix
            Sedona simulator. FX/VMA, ALC, Spyder and Niagara require their own
            native adapters. A Sedona export does not run on those controllers.
          </p>
          {status.available === false && (
            <p className="inline-error">
              Native toolchain unavailable. See scripts/setup_sedona.py.
            </p>
          )}
        </div>
      </section>
      {error && (
        <div className="inline-error" role="alert">
          {error}
        </div>
      )}
      {status.running && (
        <>
          <div className="two-column">
            <section className="card">
              <div className="card-header">
                <h3>Native scan inputs</h3>
                <span className="pill">{status.time.toFixed(2)} s</span>
              </div>
              <div className="card-body form-grid">
                {inputNodes.map((n) => (
                  <div key={n.id}>
                    <label>
                      {n.label || n.id}
                      {n.value_type === "boolean" ? (
                        <input
                          type="checkbox"
                          aria-label={"Native input " + n.id}
                          checked={inputs[n.id] ?? n.params.default ?? false}
                          onChange={(e) =>
                            setInputs({ ...inputs, [n.id]: e.target.checked })
                          }
                        />
                      ) : (
                        <input
                          type="number"
                          aria-label={"Native input " + n.id}
                          value={numericToken(
                            inputs[n.id] ?? n.params.default ?? 0,
                          )}
                          onChange={(e) =>
                            executionInput(e, (value) =>
                              setInputs({ ...inputs, [n.id]: value }),
                            )
                          }
                        />
                      )}
                    </label>
                    <select
                      aria-label={"Native quality " + n.id}
                      value={qualities[n.id] || "good"}
                      onChange={(e) =>
                        setQualities({ ...qualities, [n.id]: e.target.value })
                      }
                    >
                      <option value="good">Good quality</option>
                      <option value="open-circuit">Open circuit</option>
                      <option value="stale">Stale</option>
                    </select>
                  </div>
                ))}
                <label className="full">
                  Scan clock (UTC, optional)
                  <input
                    type="datetime-local"
                    aria-label="Native scan clock"
                    value={clock}
                    onChange={(e) => setClock(e.target.value)}
                  />
                </label>
                <button
                  className="primary full"
                  disabled={busy}
                  onClick={() =>
                    action(async () => {
                      const values = Object.fromEntries(
                        inputNodes.map((n) => [
                          n.id,
                          {
                            value: inputs[n.id] ?? n.params.default ?? 0,
                            quality: qualities[n.id] || "good",
                          },
                        ]),
                      );
                      const result = await programApi("/native/step", {
                        inputs: values,
                        ...(clock ? { clock: clock + "Z" } : {}),
                      });
                      if (!result.matches_reference)
                        setError(
                          "Native output differs from the graph reference. Inspect the trace before proceeding.",
                        );
                    })
                  }
                >
                  <SkipForward size={15} /> Step native controller
                </button>
              </div>
            </section>
            <section className="card">
              <div className="card-header">
                <h3>Execution evidence</h3>
                <button
                  disabled={!rows.length}
                  onClick={() =>
                    saveBlob(
                      new Blob(
                        [
                          JSON.stringify(
                            {
                              execution: status.kind,
                              program: loaded?.id,
                              trace: rows,
                            },
                            null,
                            2,
                          ),
                        ],
                        { type: "application/json" },
                      ),
                      "native-controller-trace.json",
                    )
                  }
                >
                  <Download size={15} /> Save native trace
                </button>
              </div>
              <div className="native-trace">
                <table>
                  <thead>
                    <tr>
                      <th>Time</th>
                      <th>Native outputs</th>
                      <th>Fault</th>
                      <th>Reference</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.slice(-20).map((r: any, i: number) => (
                      <tr key={i}>
                        <td>{r.time.toFixed(2)} s</td>
                        <td>{JSON.stringify(r.outputs)}</td>
                        <td title={r.fault_detail || ""}>
                          {r.fault ? "Fault; outputs held" : "Good"}
                        </td>
                        <td>{r.matches_reference ? "Match" : "Mismatch"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="help-text">
                Outputs above come from the native VM through Sox. Reference
                checks compare the main control graph. Added native branches use
                native value/link readback.
              </p>
            </section>
          </div>
          <section className="card">
            <div className="card-header">
              <div>
                <h3>Online native programming</h3>
                <small>
                  Changes stay inside this simulator’s /online folder. Pin wires
                  use real native property links.
                </small>
              </div>
              <button
                disabled={
                  busy ||
                  components.some((c) => c.path === "/online/sensor") ||
                  pending.some((p) => p.name === "sensor")
                }
                onClick={() =>
                  queue([
                    {
                      op: "add",
                      path: "/online",
                      name: "sensor",
                      type: "types::WriteFloat",
                    },
                    {
                      op: "write",
                      path: "/online/sensor",
                      slot: "in",
                      value: "null",
                    },
                  ])
                }
              >
                <Plus size={15} /> Add unused input
              </button>
            </div>
            <div className="native-palette">
              {palette.map((type) => (
                <button
                  draggable
                  key={type}
                  disabled={busy}
                  onDragStart={(e) =>
                    e.dataTransfer.setData("application/x-native-type", type)
                  }
                  onClick={() =>
                    queue([
                      {
                        op: "add",
                        path: "/online",
                        name: "b" + Date.now().toString(36).slice(-5),
                        type,
                      },
                    ])
                  }
                >
                  {type}
                </button>
              ))}
            </div>
            <ReactFlowProvider>
              <NativeGraph
                components={components}
                pending={pending}
                queue={queue}
                selected={selected}
                setSelected={setSelected}
              />
            </ReactFlowProvider>
            {selected && (
              <div className="native-property-strip">
                <b>{selected}</b>
                <label>
                  Property
                  <select
                    aria-label="Native property"
                    value={editableSlot || ""}
                    disabled={busy || !editableProperties.length}
                    onChange={(e) => setNativeSlot(e.target.value)}
                  >
                    {editableProperties.map((p: any) => (
                      <option key={p.name}>{p.name}</option>
                    ))}
                  </select>
                </label>
                <label>
                  Value
                  <input
                    aria-label="Native property value"
                    value={newValue}
                    disabled={busy || !editableSlot}
                    onChange={(e) => setNewValue(e.target.value)}
                  />
                </label>
                <button
                  disabled={busy || !editableSlot}
                  onClick={() =>
                    queue([
                      {
                        op: "write",
                        path: selected,
                        slot: editableSlot,
                        value: newValue,
                      },
                    ])
                  }
                >
                  Queue property edit
                </button>
                {!editableProperties.length && (
                  <small>
                    Wire a constant or writable point to set runtime inputs.
                  </small>
                )}
                <button
                  disabled={busy}
                  onClick={() => queue([{ op: "delete", path: selected }])}
                >
                  <Trash2 size={15} /> Queue removal
                </button>
              </div>
            )}
            <div className="card-body">
              <div className="native-toolbar">
                <b>{pending.length} proposed operations</b>
                <button
                  disabled={busy || !pending.length}
                  onClick={() =>
                    action(async () =>
                      setPlan(
                        await api("/native/plan", { operations: pending }),
                      ),
                    )
                  }
                >
                  Preview native change
                </button>
                <button
                  className="primary"
                  disabled={busy || !plan}
                  onClick={() =>
                    action(async () => {
                      await api("/native/apply", { token: plan.token });
                      setPending([]);
                      setPlan(null);
                    })
                  }
                >
                  <Check size={15} /> Apply native change
                </button>
                <button
                  disabled={busy || !pending.length}
                  onClick={() => {
                    setPending([]);
                    setPlan(null);
                  }}
                >
                  Clear proposals
                </button>
                <button
                  disabled={busy || !status.backups.length}
                  onClick={() =>
                    action(async () => {
                      await api("/native/rollback", {
                        backup_id: status.backups.at(-1).id,
                        expected_generation: status.generation,
                      });
                      setPending([]);
                      setPlan(null);
                      setSelected(null);
                    })
                  }
                >
                  <RotateCcw size={15} /> Roll back native change
                </button>
              </div>
              {plan && (
                <p className="native-preview">
                  Preflight passed on a separate native VM. Apply uses a saved
                  configuration and compensating rollback.
                </p>
              )}
              {!!pending.length && (
                <details>
                  <summary>Proposed native operations</summary>
                  <pre>{JSON.stringify(pending, null, 2)}</pre>
                </details>
              )}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
