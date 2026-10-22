import { sourceStringify, numericToken } from "./programSource";
import { executionNumber, executionInput } from "./programSource";
import { sourceApi } from "./api";
import { cloneSource } from "./programSource";
import { useEffect, useRef, useState } from "react";
import {
  Download,
  Layers,
  Pause,
  Play,
  Plus,
  RotateCcw,
  SkipForward,
  Trash2,
  Upload,
} from "lucide-react";
import { programApi, programDownload, saveBlob } from "./api";
import { showValue, type Program } from "./types";

type Instance = { alias: string; program: Program };
type Link = {
  source_program: string;
  source_output: string;
  target_program: string;
  target_input: string;
  initial: number | boolean;
};
type Definition = {
  format: "bms-simulation-workspace/1";
  name: string;
  programs: Instance[];
  links: Link[];
};

export function SystemSimulation({ program }: { program: Program }) {
  const [definition, setDefinition] = useState<Definition>({
    format: "bms-simulation-workspace/1",
    name: "Shared-signal simulation",
    programs: [],
    links: [],
  });
  const [status, setStatus] = useState<any>(null);
  const [projects, setProjects] = useState<any[]>([]);
  const [sessions, setSessions] = useState<any[]>([]);
  const [inputs, setInputs] = useState<Record<string, Record<string, any>>>({});
  const [running, setRunning] = useState(false);
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(true);
  const [error, setError] = useState("");
  const [clock, setClock] = useState("");
  const [source, setSource] = useState("");
  const [target, setTarget] = useState("");
  const [initial, setInitial] = useState("0");
  const active = useRef(false);
  const importFile = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let live = true;
    Promise.all([programApi("/projects"), programApi("/groups")])
      .then(async ([projects, groups]) => {
        if (!live) return;
        setProjects(projects);
        setSessions(groups);
        if (groups.length) {
          const recovered = await sourceApi("/groups/" + groups[0].session);
          if (live) adopt(recovered);
        }
      })
      .catch((e) => {
        if (live) setError(String(e));
      });
    return () => {
      live = false;
    };
  }, []);

  function edit(next: Definition) {
    setDefinition(next);
    setDirty(true);
    setRunning(false);
  }
  function adopt(next: any) {
    setStatus(next);
    setDefinition(next.definition);
    const restored = Object.fromEntries(
      Object.entries(next.external_inputs || {}).map(([alias, values]) => [
        alias,
        Object.fromEntries(
          Object.entries(values as Record<string, any>).map(([id, value]) => [
            id,
            value !== null && typeof value === "object"
              ? value
              : { value, quality: "good" },
          ]),
        ),
      ]),
    );
    setInputs(restored);
    setClock("");
    setRunning(false);
    setDirty(false);
  }
  async function action(work: () => Promise<any>) {
    if (active.current) return;
    active.current = true;
    setBusy(true);
    setError("");
    try {
      await work();
    } catch (e) {
      setError(String(e));
      setRunning(false);
      if (status?.session) {
        try {
          setStatus(await sourceApi("/groups/" + status.session));
        } catch {}
      }
    } finally {
      try {
        setSessions(await programApi("/groups"));
      } catch {}
      active.current = false;
      setBusy(false);
    }
  }
  async function step(steps = 1) {
    await action(async () =>
      setStatus(
        await sourceApi("/groups/step", {
          session: status.session,
          inputs,
          steps,
          ...(clock ? { clock: clock + "Z" } : {}),
        }),
      ),
    );
  }
  useEffect(() => {
    if (!running || !status?.session || dirty) return;
    const timer = setInterval(() => step(), 500);
    return () => clearInterval(timer);
  }, [running, status?.session, inputs, clock, dirty]);

  function add(p: Program) {
    let index = 1;
    while (definition.programs.some((p) => p.alias === "p" + index)) index++;
    edit({
      ...definition,
      programs: [
        ...definition.programs,
        { alias: "p" + index, program: cloneSource(p) },
      ],
    });
  }
  const outputs = definition.programs.flatMap((p) =>
    p.program.nodes
      .filter((n) => n.kind === "Output")
      .map((n) => ({ key: p.alias + "." + n.id, alias: p.alias, node: n })),
  );
  const destinations = definition.programs.flatMap((p) =>
    p.program.nodes
      .filter((n) => n.kind === "Input")
      .map((n) => ({ key: p.alias + "." + n.id, alias: p.alias, node: n })),
  );
  const ready = status && !dirty;
  const rows = status?.history || [];
  useEffect(() => {
    function save() {
      if (!ready) {
        setError(
          "Start the group to validate this workspace before exporting it.",
        );
        return;
      }
      action(async () => {
        await programDownload(
          "/groups/export",
          { session: status.session },
          "simulation.bms-workspace.json",
        );
      });
    }
    window.addEventListener("studio:save-workspace", save);
    return () => window.removeEventListener("studio:save-workspace", save);
  }, [status?.session, dirty]);

  return (
    <div className="workspace-page system-simulation">
      <div className="page-intro">
        <div>
          <span className="eyebrow">SHARED-SIGNAL TESTING</span>
          <h1>System simulation</h1>
          <p>
            Run several control graphs together with typed signal links and a
            common clock.
          </p>
        </div>
        <Layers size={32} />
      </div>
      <section className="card">
        <div className="card-body">
          <div className="button-row wrap">
            <button
              className="primary"
              disabled={busy || definition.programs.length < 2}
              onClick={() =>
                action(async () =>
                  adopt(
                    await sourceApi("/groups/start", {
                      definition,
                      replace: status?.session,
                    }),
                  ),
                )
              }
            >
              <Play size={15} /> Start group
            </button>
            <button
              disabled={busy}
              onClick={() =>
                action(async () => {
                  const demo = await sourceApi("/groups/demo");
                  adopt(
                    await sourceApi("/groups/start", {
                      definition: demo,
                      replace: status?.session,
                    }),
                  );
                })
              }
            >
              Load shared-signal demo
            </button>
            <button
              disabled={busy || !ready}
              onClick={() =>
                action(async () => {
                  adopt(
                    await sourceApi("/groups/reset", {
                      session: status.session,
                    }),
                  );
                })
              }
            >
              <RotateCcw size={15} /> Reset group
            </button>
            <button
              disabled={busy || !ready}
              onClick={() =>
                action(async () => {
                  await programDownload(
                    "/groups/export",
                    { session: status.session },
                    "simulation.bms-workspace.json",
                  );
                })
              }
            >
              <Download size={15} /> Save workspace
            </button>
            <button
              disabled={busy || !status}
              onClick={() =>
                action(async () => {
                  await programApi("/groups/close", {
                    session: status.session,
                  });
                  setStatus(null);
                  setDirty(true);
                  setRunning(false);
                })
              }
            >
              Close group
            </button>
            <select
              aria-label="Open simulation session"
              value=""
              disabled={busy}
              onChange={(e) => {
                const session = e.target.value;
                if (session)
                  action(async () =>
                    adopt(await sourceApi("/groups/" + session)),
                  );
              }}
            >
              <option value="">Open session…</option>
              {sessions.map((s) => (
                <option key={s.session} value={s.session}>
                  {s.name} · {s.time.toFixed(1)} s
                </option>
              ))}
            </select>
            <button disabled={busy} onClick={() => importFile.current?.click()}>
              <Upload size={15} /> Open workspace
            </button>
            <input
              ref={importFile}
              hidden
              type="file"
              accept=".bms-workspace.json"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (!file) return;
                const data = new FormData();
                data.append("file", file);
                action(async () =>
                  adopt(
                    await sourceApi(
                      "/groups/import" +
                        (status?.session
                          ? "?replace=" + encodeURIComponent(status.session)
                          : ""),
                      data,
                    ),
                  ),
                );
                e.target.value = "";
              }}
            />
          </div>
          <p className="help-text">
            Every link reads the preceding cycle’s output. Cyclic links
            therefore have an explicit one-cycle delay. Every program commits
            together; a failed cycle holds all prior states and outputs. A
            multi-cycle request keeps any earlier successful cycles.
          </p>
          {dirty && status && (
            <p className="notice">
              Configuration changed. Start a new group to test the edited
              definition.
            </p>
          )}
          {error && (
            <p className="inline-error" role="alert">
              {error}
            </p>
          )}
        </div>
      </section>

      <section className="card">
        <div className="card-header">
          <h3>Program instances</h3>
          <div className="button-row">
            <button
              disabled={busy || definition.programs.length >= 16}
              onClick={() => add(program)}
            >
              <Plus size={15} /> Add current program
            </button>
            <select
              aria-label="Add saved program to group"
              value=""
              disabled={busy || definition.programs.length >= 16}
              onChange={(e) => {
                const id = e.target.value;
                if (id)
                  action(async () => add(await sourceApi("/projects/" + id)));
              }}
            >
              <option value="">Add saved project…</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} · r{p.revision}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="card-body form-grid">
          <label className="full">
            Workspace name
            <input
              aria-label="Simulation workspace name"
              value={definition.name}
              onChange={(e) => edit({ ...definition, name: e.target.value })}
            />
          </label>
        </div>
        <table className="group-programs">
          <thead>
            <tr>
              <th>Instance alias</th>
              <th>Source revision</th>
              <th>Scan</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {definition.programs.map((p, i) => (
              <tr key={i}>
                <td>
                  <input
                    aria-label={"Program alias " + i}
                    value={p.alias}
                    onChange={(e) => {
                      const alias = e.target.value;
                      edit({
                        ...definition,
                        programs: definition.programs.map((item, j) =>
                          j === i ? { ...item, alias } : item,
                        ),
                        links: definition.links.map((l) => ({
                          ...l,
                          source_program:
                            l.source_program === p.alias
                              ? alias
                              : l.source_program,
                          target_program:
                            l.target_program === p.alias
                              ? alias
                              : l.target_program,
                        })),
                      });
                    }}
                  />
                </td>
                <td>
                  <b>{p.program.name}</b>
                  <small>
                    {p.program.id} · r{p.program.revision}
                  </small>
                </td>
                <td>{p.program.scan_seconds} s</td>
                <td>
                  <button
                    aria-label={"Remove program " + p.alias}
                    disabled={busy}
                    onClick={() =>
                      edit({
                        ...definition,
                        programs: definition.programs.filter((_, j) => i !== j),
                        links: definition.links.filter(
                          (l) =>
                            l.source_program !== p.alias &&
                            l.target_program !== p.alias,
                        ),
                      })
                    }
                  >
                    <Trash2 size={15} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="card">
        <div className="card-header">
          <h3>Shared signals</h3>
          <span className="pill">1 cycle delay</span>
        </div>
        <div className="card-body">
          <div className="group-link-form">
            <label>
              Source output
              <select
                aria-label="Shared signal source"
                value={source}
                onChange={(e) => setSource(e.target.value)}
              >
                <option value="">Choose output…</option>
                {outputs.map((p) => (
                  <option key={p.key} value={p.key}>
                    {p.key} · {p.node.value_type} {p.node.unit}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Destination input
              <select
                aria-label="Shared signal destination"
                value={target}
                onChange={(e) => setTarget(e.target.value)}
              >
                <option value="">Choose input…</option>
                {destinations.map((p) => (
                  <option key={p.key} value={p.key}>
                    {p.key} · {p.node.value_type} {p.node.unit}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Initial value
              <input
                aria-label="Shared signal initial value"
                value={initial}
                onChange={(e) => setInitial(e.target.value)}
                placeholder="0, true or false"
              />
            </label>
            <button
              disabled={busy || !source || !target}
              onClick={() => {
                const s = outputs.find((p) => p.key === source),
                  t = destinations.find((p) => p.key === target);
                if (!s || !t) return;
                let value: number | boolean;
                try {
                  value =
                    initial === "true"
                      ? true
                      : initial === "false"
                        ? false
                        : executionNumber(initial);
                } catch (error) {
                  setError(String(error));
                  return;
                }
                if (typeof value === "number" && !Number.isFinite(value)) {
                  setError(
                    "Enter a finite number, true or false for the initial signal value.",
                  );
                  return;
                }
                edit({
                  ...definition,
                  links: [
                    ...definition.links,
                    {
                      source_program: s.alias,
                      source_output: s.node.id,
                      target_program: t.alias,
                      target_input: t.node.id,
                      initial: value,
                    },
                  ],
                });
              }}
            >
              Add shared signal
            </button>
          </div>
          <div className="group-links">
            {definition.links.map((l, i) => (
              <div key={i}>
                <code>
                  {l.source_program}.{l.source_output}
                </code>
                <span>feeds</span>
                <code>
                  {l.target_program}.{l.target_input}
                </code>
                <small>initial {showValue(l.initial)}</small>
                <button
                  aria-label={"Remove shared signal " + i}
                  disabled={busy}
                  onClick={() =>
                    edit({
                      ...definition,
                      links: definition.links.filter((_, j) => j !== i),
                    })
                  }
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </div>
        </div>
      </section>

      {status && (
        <>
          <section className="card">
            <div className="card-header">
              <h3>Group inputs and clock</h3>
              <b className="group-elapsed">{status.time.toFixed(1)} s</b>
            </div>
            <div className="card-body">
              <div className="group-inputs">
                {status.definition.programs.map((p: Instance) => (
                  <fieldset key={p.alias}>
                    <legend>
                      {p.alias} · {p.program.name}
                    </legend>
                    {p.program.nodes
                      .filter((n) => n.kind === "Input")
                      .map((n) => {
                        const linked = status.definition.links.find(
                          (l: Link) =>
                            l.target_program === p.alias &&
                            l.target_input === n.id,
                        );
                        const value = inputs[p.alias]?.[n.id] || {
                          value:
                            n.params.default ??
                            (n.value_type === "boolean" ? false : 0),
                          quality: "good",
                        };
                        const update = (next: any) =>
                          setInputs((old) => ({
                            ...old,
                            [p.alias]: { ...old[p.alias], [n.id]: next },
                          }));
                        return (
                          <div key={n.id} className="group-input">
                            <label>
                              {n.label || n.id} {n.unit}
                              {linked ? (
                                <small>
                                  Linked from {linked.source_program}.
                                  {linked.source_output}
                                </small>
                              ) : n.value_type === "boolean" ? (
                                <input
                                  type="checkbox"
                                  aria-label={
                                    "Group input " + p.alias + "." + n.id
                                  }
                                  checked={value.value}
                                  disabled={!ready}
                                  onChange={(e) =>
                                    update({
                                      ...value,
                                      value: e.target.checked,
                                    })
                                  }
                                />
                              ) : (
                                <input
                                  type="number"
                                  aria-label={
                                    "Group input " + p.alias + "." + n.id
                                  }
                                  value={numericToken(value.value)}
                                  disabled={!ready}
                                  onChange={(e) =>
                                    executionInput(e, (next) =>
                                      update({ ...value, value: next }),
                                    )
                                  }
                                />
                              )}
                            </label>
                            {!linked && (
                              <select
                                aria-label={
                                  "Group quality " + p.alias + "." + n.id
                                }
                                value={value.quality}
                                disabled={!ready}
                                onChange={(e) =>
                                  update({ ...value, quality: e.target.value })
                                }
                              >
                                <option value="good">Good quality</option>
                                <option value="open-circuit">
                                  Open circuit
                                </option>
                                <option value="stale">Stale</option>
                              </select>
                            )}
                          </div>
                        );
                      })}
                  </fieldset>
                ))}
              </div>
              <label>
                Explicit cycle clock (UTC, single cycle)
                <input
                  type="datetime-local"
                  aria-label="Group cycle clock"
                  value={clock}
                  disabled={!ready || running}
                  onChange={(e) => setClock(e.target.value)}
                />
              </label>
              <div className="button-row wrap">
                <button
                  className="primary"
                  disabled={busy || !ready || running}
                  onClick={() => step()}
                >
                  <SkipForward size={15} /> Step group
                </button>
                <button
                  disabled={busy || !ready || running || !!clock}
                  onClick={() => step(10)}
                >
                  Run 10 group cycles
                </button>
                <button
                  disabled={!ready || !!clock}
                  onClick={() => setRunning(!running)}
                >
                  {running ? <Pause size={15} /> : <Play size={15} />}
                  {running ? "Pause group" : "Run group"}
                </button>
                <button
                  disabled={!rows.length}
                  onClick={() =>
                    saveBlob(
                      new Blob(
                        [
                          sourceStringify(
                            {
                              execution: status.execution,
                              definition: status.definition,
                              trace: rows,
                              failures: status.failures,
                            },
                            2,
                          ),
                        ],
                        { type: "application/json" },
                      ),
                      "group-simulation-trace.json",
                    )
                  }
                >
                  <Download size={15} /> Save group trace
                </button>
              </div>
            </div>
          </section>
          <section className="card">
            <div className="card-header">
              <h3>Shared-signal trace</h3>
              <small>
                {rows.length} retained cycles · {status.failures.length}{" "}
                recorded faults
              </small>
            </div>
            <div className="group-trace">
              <table>
                <thead>
                  <tr>
                    <th>Time</th>
                    {status.definition.programs.map((p: Instance) => (
                      <th key={p.alias}>{p.alias} outputs</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.slice(-30).map((row: any, i: number) => (
                    <tr key={i}>
                      <td>{row.time.toFixed(1)} s</td>
                      {status.definition.programs.map((p: Instance) => (
                        <td key={p.alias}>
                          <code>
                            {JSON.stringify(row.programs[p.alias].outputs)}
                          </code>
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
      <p className="help-text">
        This workspace simulates our control graphs. It does not emulate
        proprietary firmware, physical communication timing or equipment
        dynamics.
      </p>
    </div>
  );
}
