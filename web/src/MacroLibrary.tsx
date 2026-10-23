import {
  cloneSource,
  parseSourceDocument,
  projectSourceDocument,
  sourceEqual,
  sourceStringify,
} from "./programSource";
import { sourceApi } from "./api";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowDownToLine,
  ArrowLeft,
  ArrowRight,
  Box,
  Boxes,
  FileUp,
  Layers,
  Plus,
  Search,
  Trash2,
} from "lucide-react";
import { programApi, saveBlob } from "./api";
import type { Program } from "./types";
import "./macro-library.css";
import { Sum8Template } from "./Sum8Template";
import { CancelablePulseTemplate } from "./CancelablePulseTemplate";
import {
  PULSE_BASE,
  type PulseImport,
} from "./cancelablePulseTemplateContract";

type MacroPort = {
  id: string;
  label?: string;
  value_type: "number" | "boolean";
  unit: string;
};

type MacroDefinition = {
  id: string;
  name: string;
  inputs: string[];
  input_contracts: MacroPort[];
  output: "number" | "boolean";
  unit: string;
  node_count: number;
  edge_count: number;
  instances?: number;
  dependencies?: string[];
};

type MacroCatalog = {
  definitions: MacroDefinition[];
  diagnostics?: { severity: string; message: string }[];
};

type Inspection = {
  definition: string;
  program: Program;
};

function portType(port: { value_type: string; unit: string }) {
  return port.value_type + (port.unit ? " · " + port.unit : "");
}

function compact(value: unknown) {
  const text = sourceStringify(value);
  return text && text.length > 180 ? text.slice(0, 177) + "…" : text || "—";
}

function filename(name: string) {
  return (
    (name.replace(/[^a-z0-9_-]+/gi, "-").replace(/^-+|-+$/g, "") ||
      "control-macro") + ".bms-macro.json"
  );
}

export function MacroLibrary({
  program,
  selectedIds,
  onChange,
  onSelect,
  onEditDefinition,
}: {
  program: Program;
  selectedIds: string[];
  onChange: (program: Program) => void;
  onSelect?: (id: string) => void;
  onEditDefinition?: (id: string) => void;
}) {
  const [catalog, setCatalog] = useState<MacroCatalog>({ definitions: [] });
  const [selected, setSelected] = useState("");
  const [query, setQuery] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [inspection, setInspection] = useState<Inspection | null>(null);
  const [trail, setTrail] = useState<string[]>([]);
  const [inspectBusy, setInspectBusy] = useState(false);
  const [position, setPosition] = useState({ x: 320, y: 160 });
  const active = useRef(false);
  const current = useRef(program);
  const inputFile = useRef<HTMLInputElement>(null);
  const catalogRequest = useRef(0);
  const inspectRequest = useRef(0);
  current.current = program;

  const selectedNodes = useMemo(
    () => program.nodes.filter((node) => selectedIds.includes(node.id)),
    [program.nodes, selectedIds],
  );
  const definition = catalog.definitions.find((item) => item.id === selected);
  const byId = new Map(catalog.definitions.map((item) => [item.id, item]));
  const inspectedId = trail[trail.length - 1] || selected;
  const inspectedDefinition = byId.get(inspectedId);

  useEffect(() => {
    let live = true;
    const request = ++catalogRequest.current;
    setLoading(true);
    const timer = setTimeout(() => {
      programApi("/macros/catalog", { program })
        .then((next: MacroCatalog) => {
          if (!live || request !== catalogRequest.current) return;
          setCatalog(next);
          setSelected((old) =>
            next.definitions.some((item) => item.id === old)
              ? old
              : next.definitions[0]?.id || "",
          );
          setTrail((old) =>
            old.every((id) => next.definitions.some((item) => item.id === id))
              ? old
              : [],
          );
        })
        .catch((err) => {
          if (live && request === catalogRequest.current) setError(String(err));
        })
        .finally(() => {
          if (live && request === catalogRequest.current) setLoading(false);
        });
    }, 180);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [program]);

  useEffect(() => {
    let live = true;
    const request = ++inspectRequest.current;
    setInspection(null);
    if (!inspectedId) {
      setInspectBusy(false);
      return;
    }
    setInspectBusy(true);
    sourceApi("/macros/definition", { program, definition: inspectedId })
      .then((next: Program) => {
        if (live && request === inspectRequest.current)
          setInspection({ definition: inspectedId, program: next });
      })
      .catch((err) => {
        if (live && request === inspectRequest.current) setError(String(err));
      })
      .finally(() => {
        if (live && request === inspectRequest.current) setInspectBusy(false);
      });
    return () => {
      live = false;
    };
  }, [program, inspectedId]);

  function choose(id: string) {
    setSelected(id);
    setTrail([]);
    setError("");
    setNotice("");
  }

  async function action(work: (source: Program) => Promise<void>) {
    if (active.current) return;
    active.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await work(current.current);
    } catch (err) {
      setError(String(err));
    } finally {
      active.current = false;
      setBusy(false);
    }
  }

  function adopt(source: Program, next: Program) {
    if (sourceStringify(current.current) !== sourceStringify(source))
      throw new Error(
        "The program changed while this operation ran. Run it again using the current program.",
      );
    onChange(next);
  }

  async function create() {
    await action(async (source) => {
      const next: Program = await sourceApi("/macros/create", {
        program: source,
        selected_ids: selectedNodes.map((node) => node.id),
        name: name.trim(),
      });
      const previous = new Set(source.nodes.map((node) => node.id));
      const added = next.nodes.find((node) => !previous.has(node.id));
      adopt(source, next);
      if (added) onSelect?.(added.id);
      const addedDefinition = added?.params.definition;
      if (typeof addedDefinition === "string") setSelected(addedDefinition);
      setName("");
      setTrail([]);
      setNotice(
        "Selection replaced by a reusable macro instance. Its internal graph is stored in the library.",
      );
    });
  }

  async function instantiate() {
    await action(async (source) => {
      const next: Program = await sourceApi("/macros/instantiate", {
        program: source,
        definition: selected,
        ...position,
      });
      const previous = new Set(source.nodes.map((node) => node.id));
      const added = next.nodes.find((node) => !previous.has(node.id));
      adopt(source, next);
      if (added) onSelect?.(added.id);
      setPosition((old) => ({ x: old.x + 40, y: old.y + 40 }));
      setNotice("Macro instance added to the program.");
    });
  }

  async function exportDefinition() {
    await action(async (source) => {
      const bundle = await sourceApi("/macros/export", {
        program: source,
        definition: selected,
      });
      saveBlob(
        new Blob([sourceStringify(bundle, 2) + "\n"], {
          type: "application/json",
        }),
        filename(definition?.name || selected),
      );
      setNotice("Macro bundle exported with its required definitions.");
    });
  }

  async function importDefinition(file: File) {
    await action(async (source) => {
      if (file.size > 8 * 1024 * 1024)
        throw new Error("Macro bundle exceeds the 8 MiB import limit.");
      let bundle: unknown;
      try {
        bundle = parseSourceDocument(await file.text());
      } catch {
        throw new Error("Choose a valid .bms-macro.json file.");
      }
      const next: Program = await sourceApi("/macros/import", {
        program: source,
        bundle,
      });
      adopt(source, next);
      setTrail([]);
      setNotice("Macro bundle validated and added to this program's library.");
    });
  }

  async function remove() {
    await action(async (source) => {
      const next: Program = await sourceApi("/macros/delete", {
        program: source,
        definition: selected,
      });
      adopt(source, next);
      setTrail([]);
      setNotice("Unused macro definition removed.");
    });
  }

  async function importTemplate(
    bundle: Record<string, any>,
    sourceKey: string,
    definition: string,
    owned: () => boolean,
  ) {
    let imported = false;
    await action(async (source) => {
      if (!owned() || sourceStringify(source) !== sourceKey)
        throw new Error(
          "The current editor changed. Preview the sum template again.",
        );
      const next: Program = await sourceApi("/macros/import", {
        program: source,
        bundle,
      });
      if (!owned()) return;
      adopt(source, next);
      setSelected(definition);
      setTrail([]);
      setNotice(
        "Reviewed sum definition added to this editor. Add an instance separately; no project revision was saved.",
      );
      imported = true;
    });
    return imported;
  }

  async function importPulseTemplate(
    request: PulseImport,
    sourceKey: string,
    definition: string,
    expectedDefinition: Record<string, any>,
    owned: () => boolean,
  ) {
    let imported = false;
    await action(async (source) => {
      if (
        !owned() ||
        sourceStringify(source) !== sourceKey ||
        source.scan_seconds !== request.choices.scan_seconds
      )
        throw new Error(
          "The current editor or clock changed. Preview the pulse template again.",
        );
      const next: Program = await sourceApi(PULSE_BASE + "/import", {
        program: source,
        ...request,
      });
      if (!owned()) return;
      const received = next.metadata?.macros?.definitions?.find(
        (item: any) => item.id === definition,
      );
      if (
        next.id !== source.id ||
        next.revision !== source.revision ||
        next.scan_seconds !== source.scan_seconds ||
        !received ||
        !sourceEqual(
          projectSourceDocument(cloneSource(received)),
          projectSourceDocument(cloneSource(expectedDefinition)),
        )
      )
        throw new Error(
          "Pulse import response differs from the current parent or reviewed definition.",
        );
      adopt(source, next);
      setSelected(definition);
      setTrail([]);
      setNotice(
        "Reviewed pulse definition added at this editor's declared clock. Add an instance separately; no project revision was saved.",
      );
      imported = true;
    });
    return imported;
  }

  const matches = catalog.definitions.filter((item) =>
    (item.name + " " + item.id)
      .toLocaleLowerCase()
      .includes(query.toLocaleLowerCase()),
  );
  const graph =
    inspection?.definition === inspectedId ? inspection.program : null;
  const graphNodes = new Map(graph?.nodes.map((node) => [node.id, node]) || []);

  return (
    <section className="macro-library" aria-label="Reusable macro library">
      <header className="macro-library-header">
        <div>
          <span className="macro-eyebrow">
            <Boxes size={15} /> PROGRAM LIBRARY
          </span>
          <h1>Reusable macros</h1>
          <p>
            Store a connected group of blocks once, then reuse its typed inputs
            and output throughout your program.
          </p>
        </div>
        <div className="button-row">
          <input
            type="file"
            ref={inputFile}
            hidden
            accept=".json,.bms-macro.json,application/json"
            aria-label="Import macro bundle file"
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (file) importDefinition(file);
            }}
          />
          <button disabled={busy} onClick={() => inputFile.current?.click()}>
            <FileUp size={15} /> Import macro
          </button>
          <span className="macro-count">
            {catalog.definitions.length} definition
            {catalog.definitions.length === 1 ? "" : "s"}
          </span>
        </div>
      </header>

      {error && (
        <div className="macro-message macro-error" role="alert">
          {error}
        </div>
      )}
      {notice && (
        <div className="macro-message macro-notice" role="status">
          {notice}
        </div>
      )}
      {catalog.diagnostics?.map((diagnostic, index) => (
        <div className="macro-message macro-error" key={index}>
          {diagnostic.message}
        </div>
      ))}

      <div className="macro-library-layout">
        <aside className="macro-library-sidebar">
          <Sum8Template
            program={program}
            disabled={busy}
            onImport={importTemplate}
          />
          <CancelablePulseTemplate
            program={program}
            disabled={busy}
            onImport={importPulseTemplate}
          />
          <section className="macro-card macro-selection-card">
            <div className="macro-card-heading">
              <Layers size={16} />
              <h2>Create from selection</h2>
            </div>
            <p className="help-text">
              Select blocks in Program, then give this reusable group a name.
              Keep root Input and Output blocks outside the selection. The group
              must have one outgoing result; its boundary inputs become macro
              ports.
            </p>
            <div className="macro-selection-summary">
              <b>{selectedNodes.length}</b> selected block
              {selectedNodes.length === 1 ? "" : "s"}
            </div>
            {selectedNodes.length > 0 && (
              <div
                className="macro-selected-nodes"
                aria-label="Blocks in macro selection"
              >
                {selectedNodes.map((node) => (
                  <span key={node.id}>{node.label || node.id}</span>
                ))}
              </div>
            )}
            <form
              onSubmit={(event) => {
                event.preventDefault();
                create();
              }}
            >
              <label>
                Macro name
                <input
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  maxLength={100}
                  placeholder="Supply reset logic"
                />
              </label>
              <button
                className="primary"
                disabled={
                  busy || loading || !selectedNodes.length || !name.trim()
                }
              >
                <Plus size={15} /> Create macro
              </button>
            </form>
          </section>

          <section className="macro-card macro-definition-list">
            <div className="macro-card-heading">
              <Box size={16} />
              <h2>Definitions</h2>
            </div>
            <label className="macro-search">
              <Search size={15} />
              <input
                aria-label="Search macro definitions"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Find a macro"
              />
            </label>
            <div className="macro-definition-items">
              {matches.map((item) => (
                <button
                  key={item.id}
                  className={
                    item.id === selected
                      ? "macro-definition selected"
                      : "macro-definition"
                  }
                  onClick={() => choose(item.id)}
                  aria-pressed={item.id === selected}
                >
                  <span>
                    <Box size={16} />
                    <b>{item.name}</b>
                  </span>
                  <small>
                    {item.inputs.length} input
                    {item.inputs.length === 1 ? "" : "s"} · {item.node_count}{" "}
                    blocks
                  </small>
                  <small>
                    {portType({ value_type: item.output, unit: item.unit })}
                  </small>
                </button>
              ))}
              {!matches.length && (
                <p className="help-text">
                  {loading
                    ? "Reading macro library…"
                    : query
                      ? "No matching definitions."
                      : "Your reusable definitions will appear here."}
                </p>
              )}
            </div>
          </section>
        </aside>

        <main className="macro-library-detail">
          {definition ? (
            <>
              <section className="macro-card">
                <div className="macro-detail-heading">
                  <div>
                    <span className="macro-eyebrow">REUSABLE DEFINITION</span>
                    <h2>{definition.name}</h2>
                    <small className="mono">{definition.id}</small>
                  </div>
                  <div className="button-row">
                    <button disabled={busy} onClick={exportDefinition}>
                      <ArrowDownToLine size={15} /> Export macro
                    </button>
                    <button
                      className="danger"
                      disabled={busy || !!definition.instances}
                      onClick={remove}
                      title={
                        definition.instances
                          ? "Remove this definition's instances before deleting it."
                          : "Delete this unused definition"
                      }
                    >
                      <Trash2 size={15} /> Delete unused
                    </button>
                  </div>
                </div>
                <div className="macro-stat-row">
                  <span>
                    <b>{definition.node_count}</b> internal blocks
                  </span>
                  <span>
                    <b>{definition.edge_count}</b> internal wires
                  </span>
                  {definition.instances !== undefined && (
                    <span>
                      <b>{definition.instances}</b> instances
                    </span>
                  )}
                  <span>
                    <b>{definition.dependencies?.length || 0}</b> nested
                    definitions
                  </span>
                </div>
                <div className="macro-interface">
                  <div>
                    <h3>Input ports</h3>
                    {definition.input_contracts.length ? (
                      definition.input_contracts.map((port) => (
                        <div className="macro-port" key={port.id}>
                          <b>{port.label || port.id}</b>
                          <code>{port.id}</code>
                          <small>{portType(port)}</small>
                        </div>
                      ))
                    ) : (
                      <p className="help-text">
                        This macro has no external inputs.
                      </p>
                    )}
                  </div>
                  <ArrowRight size={20} className="macro-interface-arrow" />
                  <div>
                    <h3>Output</h3>
                    <div className="macro-port">
                      <b>out</b>
                      <small>
                        {portType({
                          value_type: definition.output,
                          unit: definition.unit,
                        })}
                      </small>
                    </div>
                  </div>
                </div>
                <div className="macro-placement">
                  <label>
                    Canvas X
                    <input
                      type="number"
                      value={position.x}
                      onChange={(event) =>
                        setPosition((old) => ({
                          ...old,
                          x: Number(event.target.value),
                        }))
                      }
                    />
                  </label>
                  <label>
                    Canvas Y
                    <input
                      type="number"
                      value={position.y}
                      onChange={(event) =>
                        setPosition((old) => ({
                          ...old,
                          y: Number(event.target.value),
                        }))
                      }
                    />
                  </label>
                  <button
                    className="primary"
                    disabled={
                      busy ||
                      !Number.isFinite(position.x) ||
                      !Number.isFinite(position.y)
                    }
                    onClick={instantiate}
                  >
                    <Plus size={15} /> Add instance to program
                  </button>
                </div>
              </section>

              <section className="macro-card macro-inspection">
                <div className="macro-detail-heading">
                  <div>
                    <h2>Inside the macro</h2>
                    <p className="help-text">
                      Preview the internal blocks and wires. Open a nested macro
                      to inspect its definition, or edit the graph on the
                      wiresheet.
                    </p>
                  </div>
                  <div className="button-row">
                    {trail.length > 0 && (
                      <button
                        onClick={() => setTrail((old) => old.slice(0, -1))}
                      >
                        <ArrowLeft size={15} /> Up one level
                      </button>
                    )}
                    {onEditDefinition && (
                      <button
                        disabled={busy || inspectBusy || !inspectedDefinition}
                        onClick={() => onEditDefinition(inspectedId)}
                      >
                        <Layers size={15} /> Edit definition on wiresheet
                      </button>
                    )}
                  </div>
                </div>
                <nav className="macro-breadcrumbs" aria-label="Macro hierarchy">
                  <button
                    onClick={() => setTrail([])}
                    aria-current={!trail.length ? "page" : undefined}
                  >
                    {definition.name}
                  </button>
                  {trail.map((id, index) => (
                    <span key={index}>
                      <ArrowRight size={12} />
                      <button
                        onClick={() =>
                          setTrail((old) => old.slice(0, index + 1))
                        }
                        aria-current={
                          index === trail.length - 1 ? "page" : undefined
                        }
                      >
                        {byId.get(id)?.name || id}
                      </button>
                    </span>
                  ))}
                </nav>
                {inspectBusy ? (
                  <p className="help-text">Reading definition…</p>
                ) : graph ? (
                  <>
                    <h3>{inspectedDefinition?.name || graph.name}: blocks</h3>
                    <div className="macro-table-wrap">
                      <table className="macro-table">
                        <thead>
                          <tr>
                            <th>Block</th>
                            <th>Type</th>
                            <th>Value type</th>
                            <th>Parameters</th>
                          </tr>
                        </thead>
                        <tbody>
                          {graph.nodes.map((node) => {
                            const child =
                              node.kind === "Macro" &&
                              typeof node.params.definition === "string"
                                ? byId.get(node.params.definition)
                                : undefined;
                            return (
                              <tr key={node.id}>
                                <td>
                                  <b>{node.label || node.id}</b>
                                  <small>{node.id}</small>
                                </td>
                                <td>
                                  {child ? (
                                    <button
                                      className="macro-nested-link"
                                      onClick={() =>
                                        setTrail((old) => [...old, child.id])
                                      }
                                    >
                                      <Box size={13} />
                                      {child.name}
                                      <ArrowRight size={13} />
                                    </button>
                                  ) : (
                                    node.kind
                                  )}
                                </td>
                                <td>{portType(node)}</td>
                                <td
                                  className="mono"
                                  title={sourceStringify(node.params, 2)}
                                >
                                  {compact(node.params)}
                                </td>
                              </tr>
                            );
                          })}
                          {!graph.nodes.length && (
                            <tr>
                              <td colSpan={4}>No blocks.</td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                    <h3>Wires</h3>
                    <div className="macro-table-wrap">
                      <table className="macro-table">
                        <thead>
                          <tr>
                            <th>Source</th>
                            <th>Port</th>
                            <th>Destination</th>
                            <th>Port</th>
                          </tr>
                        </thead>
                        <tbody>
                          {graph.edges.map((edge) => (
                            <tr key={edge.id}>
                              <td>
                                {graphNodes.get(edge.source)?.label ||
                                  edge.source}
                              </td>
                              <td>
                                <code>{edge.source_port}</code>
                              </td>
                              <td>
                                {graphNodes.get(edge.target)?.label ||
                                  edge.target}
                              </td>
                              <td>
                                <code>{edge.target_port}</code>
                              </td>
                            </tr>
                          ))}
                          {!graph.edges.length && (
                            <tr>
                              <td colSpan={4}>No internal wires.</td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                  </>
                ) : (
                  <p className="help-text">
                    The definition could not be inspected. Review the message
                    above.
                  </p>
                )}
              </section>
            </>
          ) : (
            <div className="macro-empty">
              <Boxes size={42} />
              <h2>Build your own block library</h2>
              <p>
                Select a connected group in Program to create the first macro,
                or import a macro bundle.
              </p>
            </div>
          )}
        </main>
      </div>
    </section>
  );
}
