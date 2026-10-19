import { useCallback, useEffect, useRef, useState } from "react";
import { useReactFlow, type Connection, type NodeChange } from "@xyflow/react";
import {
  CircuitBoard,
  Workflow,
  FileArchive,
  Network,
  Cpu,
  BookOpen,
  Save,
  FolderOpen,
  Undo2,
  Redo2,
  Download,
  Upload,
  Plus,
  Search,
  Settings2,
  CheckCircle2,
  AlertTriangle,
  Maximize,
  X,
  FlaskConical,
} from "lucide-react";
import { api, download, initSession } from "./api";
import {
  blankProgram,
  type Block,
  type BmsNode,
  type Program,
  type Scan,
} from "./types";
import { Canvas } from "./Canvas";
import { Inspector, SimulationPanel } from "./Panels";
import { NativeCaf } from "./NativeCaf";
import { Connections } from "./Connections";
import { RuntimePanel } from "./Runtime";
import { Resources } from "./Resources";
import { NativeSimulator } from "./NativeSimulator";

export function App() {
  const [tab, setTab] = useState("editor"),
    [program, setProgram] = useState<Program>(blankProgram),
    [blocks, setBlocks] = useState<Block[]>([]),
    [templates, setTemplates] = useState<Program[]>([]),
    [projects, setProjects] = useState<any[]>([]),
    [issues, setIssues] = useState<any[]>([]),
    [selected, setSelected] = useState<string | null>(null),
    [search, setSearch] = useState(""),
    [format, setFormat] = useState("json"),
    [history, setHistory] = useState<Scan[]>([]),
    [inputs, setInputs] = useState<Record<string, any>>({}),
    [running, setRunning] = useState(false),
    [simError, setSimError] = useState(""),
    [message, setMessage] = useState(""),
    [ready, setReady] = useState(false),
    [settings, setSettings] = useState(false),
    [versions, setVersions] = useState<any[]>([]),
    [showIssues, setShowIssues] = useState(false),
    [undoStack, setUndoStack] = useState<Program[]>([]),
    [redoStack, setRedoStack] = useState<Program[]>([]);
  const latestProgram = useRef(program);
  latestProgram.current = program;
  const session = useRef<string | null>(null),
    busy = useRef(false),
    importInput = useRef<HTMLInputElement>(null);
  const flow = useReactFlow();
  useEffect(() => {
    let live = true;
    initSession()
      .then(() =>
        Promise.all([api("/blocks"), api("/templates"), api("/projects")]),
      )
      .then(([b, t, p]) => {
        if (!live) return;
        setBlocks(b);
        setTemplates(t);
        setProjects(p);
        let initial = t[0];
        try {
          const saved = localStorage.getItem("bms-studio-draft-v1");
          if (saved) {
            const parsed = JSON.parse(saved);
            if (
              parsed.schema_version === 1 &&
              Array.isArray(parsed.nodes) &&
              Array.isArray(parsed.edges)
            )
              initial = parsed;
          }
        } catch {}
        setProgram(initial);
        setReady(true);
      })
      .catch((e) => setMessage(e.message));
    return () => {
      live = false;
    };
  }, []);
  useEffect(() => {
    if (!ready) return;
    setRunning(false);
    session.current = null;
    setHistory([]);
    setSimError("");
    const timer = setTimeout(() => {
      localStorage.setItem("bms-studio-draft-v1", JSON.stringify(program));
      api("/validate", program)
        .then((r) => setIssues(r.issues))
        .catch((e) => setMessage(e.message));
    }, 200);
    return () => clearTimeout(timer);
  }, [program, ready]);
  const remember = useCallback(() => {
    setUndoStack((s) => [...s.slice(-49), structuredClone(program)]);
    setRedoStack([]);
  }, [program]);
  function change(p: Program, record = true) {
    if (record) remember();
    setProgram(p);
    setMessage("");
  }
  function undo() {
    if (!undoStack.length) return;
    setRedoStack((s) => [...s, structuredClone(program)]);
    setProgram(undoStack.at(-1)!);
    setUndoStack((s) => s.slice(0, -1));
  }
  function redo() {
    if (!redoStack.length) return;
    setUndoStack((s) => [...s, structuredClone(program)]);
    setProgram(redoStack.at(-1)!);
    setRedoStack((s) => s.slice(0, -1));
  }
  async function save() {
    try {
      const native = tab === "native" ? await api("/native/status") : null;
      const p = native?.running
        ? await api("/native/save", {
            expected_revision: native.program.revision,
          })
        : await api("/projects", {
            program,
            expected_revision: program.revision,
          });
      setProgram(p);
      setProjects(await api("/projects"));
      setVersions(await api(`/projects/${p.id}/versions`));
      setMessage(
        `Saved ${native?.running ? "native " : ""}revision ${p.revision} locally.`,
      );
    } catch (e) {
      setMessage(String(e));
    }
  }
  const step = useCallback(async () => {
    if (busy.current) return;
    busy.current = true;
    try {
      const r = await api("/simulation/step", {
        program,
        inputs,
        session: session.current,
      });
      if (latestProgram.current !== program) return;
      session.current = r.session;
      setHistory(r.history);
      setSimError("");
    } catch (e) {
      setSimError(String(e));
      setRunning(false);
    } finally {
      busy.current = false;
    }
  }, [program, inputs]);
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(step, 500);
    return () => clearInterval(timer);
  }, [running, step]);
  useEffect(() => {
    function keyboard(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "s") {
        e.preventDefault();
        save();
        return;
      }
      if (tab !== "editor") return;
      if (
        ["INPUT", "SELECT", "TEXTAREA"].includes(
          (e.target as HTMLElement).tagName,
        )
      )
        return;
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z") {
        e.preventDefault();
        e.shiftKey ? redo() : undo();
      }
      if (e.key === "Delete" && selected) {
        e.preventDefault();
        remove();
      }
    }
    window.addEventListener("keydown", keyboard);
    return () => window.removeEventListener("keydown", keyboard);
  });
  function add(kind: string, x?: number, y?: number) {
    const b = blocks.find((b) => b.kind === kind);
    if (!b) return;
    const n: BmsNode = {
      id: kind.toLowerCase() + "_" + Date.now().toString(36),
      kind,
      label: b.title,
      x: x ?? 100 + (program.nodes.length % 4) * 240,
      y: y ?? 100 + Math.floor(program.nodes.length / 4) * 180,
      params: structuredClone(b.parameters),
      unit: "",
      value_type: b.output === "boolean" ? "boolean" : "number",
    };
    change({ ...program, nodes: [...program.nodes, n] });
    setSelected(n.id);
  }
  function edit(n: BmsNode) {
    change({
      ...program,
      nodes: program.nodes.map((old) => (old.id === n.id ? n : old)),
    });
  }
  function remove() {
    if (!selected) return;
    change({
      ...program,
      nodes: program.nodes.filter((n) => n.id !== selected),
      edges: program.edges.filter(
        (e) => e.source !== selected && e.target !== selected,
      ),
    });
    setSelected(null);
  }
  function duplicate() {
    const n = program.nodes.find((n) => n.id === selected);
    if (!n) return;
    const copy = {
      ...structuredClone(n),
      id: n.kind.toLowerCase() + "_" + Date.now().toString(36),
      label: n.label + " copy",
      x: n.x + 50,
      y: n.y + 100,
    };
    change({ ...program, nodes: [...program.nodes, copy] });
    setSelected(copy.id);
  }
  function connect(c: Connection) {
    if (!c.source || !c.target || !c.targetHandle) return;
    change({
      ...program,
      edges: [
        ...program.edges,
        {
          id: "wire_" + Date.now().toString(36),
          source: c.source,
          target: c.target,
          source_port: c.sourceHandle || "out",
          target_port: c.targetHandle,
        },
      ],
    });
  }
  function nodeChanges(changes: NodeChange[]) {
    if (!changes.some((c) => c.type === "position" && c.position)) return;
    setProgram((current) => {
      let moved = false;
      const nodes = current.nodes.map((n) => {
        const p = changes.find((c) => c.type === "position" && c.id === n.id);
        if (
          p &&
          p.type === "position" &&
          p.position &&
          (n.x !== p.position.x || n.y !== p.position.y)
        ) {
          moved = true;
          return { ...n, x: p.position.x, y: p.position.y };
        }
        return n;
      });
      return moved ? { ...current, nodes } : current;
    });
  }
  async function loadProject(id: string, revision?: number) {
    try {
      change(
        await api(`/projects/${id}${revision ? "?revision=" + revision : ""}`),
      );
      setVersions(await api(`/projects/${id}/versions`));
      setSelected(null);
    } catch (e) {
      setMessage(String(e));
    }
  }
  async function importProgram(file?: File) {
    if (!file) return;
    try {
      const f = new FormData();
      f.append("file", file);
      const imported = await api("/import", f);
      change({
        ...imported,
        id: imported.id.slice(0, 50) + "-import-" + Date.now().toString(36),
        revision: 0,
      });
      setSelected(null);
      setVersions([]);
      if (imported.metadata?.conversion?.review_required) setSettings(true);
      setMessage("Imported as a new local project.");
    } catch (e) {
      setMessage(String(e));
    }
  }
  const active = program.nodes.find((n) => n.id === selected),
    errors = issues.filter((d) => d.level === "error"),
    palette = blocks.filter((b) =>
      (b.title + " " + b.kind + " " + b.category)
        .toLowerCase()
        .includes(search.toLowerCase()),
    );
  const tabs = [
    { id: "editor", title: "Program", icon: Workflow },
    { id: "caf", title: "CAF files", icon: FileArchive },
    { id: "connections", title: "Connect", icon: Network },
    { id: "runtime", title: "Runtime", icon: Cpu },
    { id: "native", title: "Native sim", icon: FlaskConical },
    { id: "resources", title: "Reference", icon: BookOpen },
  ];
  if (!ready)
    return (
      <div className="loading">
        <CircuitBoard size={38} />
        <h2>BMS Studio</h2>
        <p>{message || "Opening local workspace…"}</p>
      </div>
    );
  return (
    <div className="app">
      <header className="app-header">
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setTab("editor");
          }}
        >
          <CircuitBoard size={27} />
          <span>
            BMS <b>Studio</b>
            <small>CONTROLLER PROGRAMMING</small>
          </span>
        </a>
        <div className="project-title">
          <input
            aria-label="Program name"
            value={program.name}
            onChange={(e) => change({ ...program, name: e.target.value })}
          />
          <span className="pill">LOCAL WORKSPACE</span>
        </div>
        <button className="save-button primary" onClick={save}>
          <Save size={15} /> Save revision
        </button>
      </header>
      <div className="app-body">
        <nav className="nav-rail" aria-label="Workspaces">
          {tabs.map((t) => (
            <button
              key={t.id}
              className={tab === t.id ? "active" : ""}
              onClick={() => setTab(t.id)}
              title={t.title}
            >
              <t.icon size={21} />
              <span>{t.title}</span>
            </button>
          ))}
          <div className="rail-bottom">
            <span className="status-dot on" />
            <small>LOCAL</small>
          </div>
        </nav>
        <main>
          {tab === "editor" ? (
            <>
              <div className="editor-toolbar">
                <div className="button-row">
                  <button
                    title="New program"
                    aria-label="New program"
                    onClick={() => {
                      change(blankProgram());
                      setSelected(null);
                      setVersions([]);
                    }}
                  >
                    <Plus size={15} /> New
                  </button>
                  <select
                    aria-label="Open saved project"
                    value=""
                    onChange={(e) => loadProject(e.target.value)}
                  >
                    <option value="">Open project…</option>
                    {projects.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name} · r{p.revision}
                      </option>
                    ))}
                  </select>
                  <select
                    aria-label="Choose VAV template"
                    value=""
                    onChange={(e) => {
                      const p = templates.find((p) => p.id === e.target.value);
                      if (p) {
                        change({
                          ...structuredClone(p),
                          id: p.id + "-" + Date.now().toString(36),
                        });
                        setSelected(null);
                        setVersions([]);
                        setInputs({});
                        setTimeout(() => flow.fitView({ padding: 0.2 }), 100);
                      }
                    }}
                  >
                    <option value="">VAV templates…</option>
                    {templates.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                  <span className="toolbar-divider" />
                  <button
                    title="Undo"
                    disabled={!undoStack.length}
                    onClick={undo}
                  >
                    <Undo2 size={15} />
                  </button>
                  <button
                    title="Redo"
                    disabled={!redoStack.length}
                    onClick={redo}
                  >
                    <Redo2 size={15} />
                  </button>
                  <button
                    title="Fit view"
                    onClick={() => flow.fitView({ padding: 0.2 })}
                  >
                    <Maximize size={15} />
                  </button>
                  <button
                    title="Program settings"
                    onClick={() => {
                      setSettings(true);
                      api(`/projects/${program.id}/versions`)
                        .then(setVersions)
                        .catch(() => {});
                    }}
                  >
                    <Settings2 size={15} />
                  </button>
                </div>
                <div className="button-row">
                  <button onClick={() => importInput.current?.click()}>
                    <Upload size={15} /> Import
                  </button>
                  <input
                    hidden
                    type="file"
                    accept=".json,.st,.xml,.graphml,.sedona.zip,.sax,.sab"
                    ref={importInput}
                    onChange={(e) => {
                      importProgram(e.target.files?.[0]);
                      e.target.value = "";
                    }}
                  />
                  <select
                    aria-label="Export format"
                    value={format}
                    onChange={(e) => setFormat(e.target.value)}
                  >
                    <option value="json">BMS project</option>
                    <option value="st">Structured Text</option>
                    <option value="plcopen">PLCopen XML</option>
                    <option value="graphml">GraphML</option>
                    <option value="sedona">Native Sedona bundle</option>
                    <option value="sedona-sax">
                      Sedona SAX (kit required)
                    </option>
                    <option value="sedona-sab">
                      Sedona SAB (kit required)
                    </option>
                  </select>
                  <button
                    onClick={async () => {
                      try {
                        await download(
                          "/export",
                          { program, format },
                          program.id +
                            "." +
                            {
                              json: "bms.json",
                              st: "st",
                              plcopen: "xml",
                              graphml: "graphml",
                              sedona: "sedona.zip",
                              "sedona-sax": "sax",
                              "sedona-sab": "sab",
                            }[format],
                        );
                        setMessage(
                          "Exported " +
                            format +
                            ". Native vendor compilation is a separate step.",
                        );
                      } catch (e) {
                        setMessage(String(e));
                      }
                    }}
                  >
                    <Download size={15} /> Export
                  </button>
                </div>
              </div>
              <div className="editor-layout">
                <aside className="palette">
                  <div className="panel-heading">
                    <Workflow size={16} /> BLOCK LIBRARY{" "}
                    <span>{blocks.length}</span>
                  </div>
                  <div className="search">
                    <Search size={15} />
                    <input
                      aria-label="Search blocks"
                      placeholder="Search blocks…"
                      value={search}
                      onChange={(e) => setSearch(e.target.value)}
                    />
                  </div>
                  <div className="palette-scroll">
                    {["I/O", "Math", "Logic", "Control", "Supervision"].map(
                      (category) => (
                        <div className="palette-group" key={category}>
                          <div className="small-heading">{category}</div>
                          {palette
                            .filter((b) => b.category === category)
                            .map((b) => (
                              <button
                                className="palette-block"
                                key={b.kind}
                                draggable
                                onDragStart={(e) => {
                                  e.dataTransfer.setData(
                                    "application/bms-kind",
                                    b.kind,
                                  );
                                  e.dataTransfer.effectAllowed = "copy";
                                }}
                                onClick={() => add(b.kind)}
                                title={b.help || b.title}
                              >
                                <span
                                  className={
                                    "block-mark category-" +
                                    category.toLowerCase().replace("/", "")
                                  }
                                >
                                  {b.stateful
                                    ? "↻"
                                    : b.kind === "Input"
                                      ? "I"
                                      : b.kind === "Output"
                                        ? "O"
                                        : b.title.slice(0, 1)}
                                </span>
                                <span>
                                  {b.title}
                                  <small>
                                    {b.inputs.length
                                      ? b.inputs.length + " inputs"
                                      : "source"}
                                  </small>
                                </span>
                                <Plus size={13} />
                              </button>
                            ))}
                        </div>
                      ),
                    )}
                  </div>
                  <div className="palette-footer">
                    Drag a block onto the wiresheet.
                    <br />
                    Click a block to add it.
                  </div>
                </aside>
                <div className="editor-center">
                  <Canvas
                    program={program}
                    blocks={blocks}
                    last={history.at(-1)}
                    issues={issues}
                    selected={selected}
                    onSelect={setSelected}
                    onChange={nodeChanges}
                    onBeginDrag={remember}
                    onConnect={connect}
                    onAdd={add}
                    onRemoveWire={(id) =>
                      change({
                        ...program,
                        edges: program.edges.filter((e) => e.id !== id),
                      })
                    }
                  />
                  <SimulationPanel
                    program={program}
                    history={history}
                    inputs={inputs}
                    setInputs={setInputs}
                    running={running}
                    setRunning={setRunning}
                    onStep={step}
                    onReset={() => {
                      session.current = null;
                      setHistory([]);
                      setRunning(false);
                      setSimError("");
                    }}
                    onScenario={(h) => {
                      session.current = null;
                      setHistory(h);
                    }}
                    error={simError}
                  />
                </div>
                <Inspector
                  node={active}
                  block={blocks.find((b) => b.kind === active?.kind)}
                  onEdit={edit}
                  onDelete={remove}
                  onDuplicate={duplicate}
                />
              </div>
              <div className="validation-bar">
                <button
                  className={
                    errors.length ? "validation-error" : "validation-ok"
                  }
                  onClick={() => setShowIssues(!showIssues)}
                >
                  {errors.length ? (
                    <AlertTriangle size={14} />
                  ) : (
                    <CheckCircle2 size={14} />
                  )}{" "}
                  {errors.length
                    ? errors.length + " graph errors"
                    : "Graph checks passed"}{" "}
                  <span>
                    {issues.filter((d) => d.level === "warning").length} notices
                  </span>
                </button>
                <span>
                  {program.nodes.length} blocks · {program.edges.length} wires ·{" "}
                  {program.scan_seconds}s scan · r{program.revision}
                </span>
              </div>
              {showIssues && (
                <div className="diagnostics">
                  {issues.length ? (
                    issues.map((d, i) => (
                      <button key={i} onClick={() => setSelected(d.node)}>
                        <span
                          className={
                            "pill " + (d.level === "error" ? "pending" : "")
                          }
                        >
                          {d.level}
                        </span>
                        <b>{d.node || "Program"}</b>
                        {d.message}
                      </button>
                    ))
                  ) : (
                    <p>
                      All graph checks passed. This checks our graph semantics,
                      not native firmware compatibility.
                    </p>
                  )}
                </div>
              )}
            </>
          ) : tab === "caf" ? (
            <NativeCaf />
          ) : tab === "connections" ? (
            <Connections />
          ) : tab === "runtime" ? (
            <RuntimePanel program={program} inputs={inputs} />
          ) : tab === "native" ? (
            <NativeSimulator
              program={program}
              onSaved={(p) => {
                setProgram(p);
                api("/projects")
                  .then(setProjects)
                  .catch((e) => setMessage(String(e)));
                setMessage(`Saved native revision ${p.revision} locally.`);
              }}
            />
          ) : (
            <Resources />
          )}
        </main>
      </div>
      <footer className="app-footer">
        <span>
          <span className="status-dot on" /> Data stays on this computer
        </span>
        <span>
          BMS Studio 0.1 · Development build · Native vendor adapters pending
        </span>
      </footer>
      {message && (
        <div className="toast" role="status">
          <span>{message}</span>
          <button aria-label="Dismiss message" onClick={() => setMessage("")}>
            <X size={16} />
          </button>
        </div>
      )}
      {settings && (
        <div className="modal-backdrop">
          <div className="modal">
            <div className="card-header">
              <h2>Program settings</h2>
              <button
                aria-label="Close settings"
                onClick={() => setSettings(false)}
              >
                <X size={18} />
              </button>
            </div>
            <div className="card-body">
              <label>
                Project identifier
                <input
                  value={program.id}
                  onChange={(e) =>
                    change({ ...program, id: e.target.value, revision: 0 })
                  }
                />
              </label>
              <label>
                Description
                <textarea
                  value={program.description}
                  onChange={(e) =>
                    change({ ...program, description: e.target.value })
                  }
                />
              </label>
              <div className="form-grid">
                <label>
                  Scan interval (seconds)
                  <input
                    type="number"
                    min={0.01}
                    max={60}
                    step={0.01}
                    value={program.scan_seconds}
                    onChange={(e) =>
                      change({
                        ...program,
                        scan_seconds: Number(e.target.value),
                      })
                    }
                  />
                </label>
                <label>
                  Target family
                  <select
                    value={program.target.family}
                    onChange={(e) =>
                      change({
                        ...program,
                        target: { ...program.target, family: e.target.value },
                      })
                    }
                  >
                    <option value="universal-runtime">
                      BMS Studio runtime
                    </option>
                    <option value="johnson-fx">Johnson Controls FX</option>
                    <option value="johnson-metasys">
                      Johnson Controls Metasys
                    </option>
                  </select>
                </label>
                <label>
                  Controller model
                  <input
                    value={program.target.model}
                    onChange={(e) =>
                      change({
                        ...program,
                        target: { ...program.target, model: e.target.value },
                      })
                    }
                  />
                </label>
                <label>
                  Firmware
                  <input
                    value={program.target.firmware}
                    onChange={(e) =>
                      change({
                        ...program,
                        target: { ...program.target, firmware: e.target.value },
                      })
                    }
                  />
                </label>
                <label>
                  CAF release mode
                  <input
                    value={program.target.release_mode}
                    onChange={(e) =>
                      change({
                        ...program,
                        target: {
                          ...program.target,
                          release_mode: e.target.value,
                        },
                      })
                    }
                  />
                </label>
              </div>
              <p className="help-text">
                Selecting a vendor records the target; it does not supply a
                native compiler or certify the graph.
              </p>
              <h3>Saved revisions</h3>
              {program.metadata?.conversion && (
                <details open className="conversion-report">
                  <summary>Native conversion report · review required</summary>
                  <pre>
                    {JSON.stringify(program.metadata.conversion, null, 2)}
                  </pre>
                </details>
              )}
              {versions.map((v) => (
                <button
                  className="version-row"
                  key={v.revision}
                  onClick={() => loadProject(program.id, v.revision)}
                >
                  Revision {v.revision}
                  <small>{v.created}</small>
                  <FolderOpen size={14} />
                </button>
              ))}
              {!versions.length && <p>No saved revisions for this project.</p>}
              <button className="primary" onClick={() => setSettings(false)}>
                Done
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
