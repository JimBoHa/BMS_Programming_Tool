import { useEffect, useMemo, useRef, useState } from "react";
import { Download, GitBranch, RefreshCw } from "lucide-react";
import { api, download } from "./api";
import "./caf-graph.css";

type DiagramSummary = {
  ref: string;
  class_id: string;
  name: string;
  blocks: number;
  connections: number;
  observed_version: boolean;
};
type GraphInventory = {
  diagrams: DiagramSummary[];
  errors: { ref: string; error: string }[];
  validation: string;
};
type NativeBlock = {
  index: number;
  ref: string;
  bacnet_type: number;
  instance: number;
  class_id: string;
  class_version: string;
  class_name: string;
  name: string;
  execution_index: number;
  layout: { x: string; y: string; opaque_code: number };
  exposed_ports: { id: number; name: string }[];
};
type NativeWire = {
  index: number;
  raw: number[];
  source_ref: string;
  source_port: number;
  target_ref: string;
  target_port: number;
  continuation: { flag: boolean; text: string };
};
type NativeDiagram = {
  ref: string;
  class_id: string;
  class_version: string;
  observed_version: boolean;
  name: string;
  blocks: NativeBlock[];
  connections: NativeWire[];
  execution_order: number[];
  validation: string;
};

function blockTitle(block?: NativeBlock) {
  return block
    ? block.name || `${block.ref.split(".").at(-1)} · ${block.class_name}`
    : "Unresolved block";
}

function editedFilename(filename: string, action = "rewired") {
  const basename = filename.split(/[\\/]/).at(-1) || "program.caf";
  return basename.replace(/(?:\.caf)?(?:\.xml)?$/i, "") + `-${action}.caf`;
}

export function CafGraphPanel({
  id,
  filename,
  disabled = false,
  scalarChangeCount = 0,
  onDirtyChange,
}: {
  id: string;
  filename: string;
  disabled?: boolean;
  scalarChangeCount?: number;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const [inventory, setInventory] = useState<GraphInventory | null>(null);
  const [diagramRef, setDiagramRef] = useState("");
  const [diagram, setDiagram] = useState<NativeDiagram | null>(null);
  const [wireIndex, setWireIndex] = useState(0);
  const [sourceRef, setSourceRef] = useState("");
  const [connectionSourceRef, setConnectionSourceRef] = useState("");
  const [connectionTargetRef, setConnectionTargetRef] = useState("");
  const [loadingIndex, setLoadingIndex] = useState(false);
  const [loadingGraph, setLoadingGraph] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState("");
  const [exported, setExported] = useState("");
  const [refresh, setRefresh] = useState(0);
  const mounted = useRef(false);
  const exportRequest = useRef(0);
  const activeArchive = useRef(id);
  activeArchive.current = id;
  const savedProposals = useRef(new Set<string>());

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      exportRequest.current++;
    };
  }, []);

  useEffect(() => {
    let active = true;
    setLoadingIndex(true);
    setInventory(null);
    setDiagramRef("");
    setDiagram(null);
    setSourceRef("");
    setConnectionSourceRef("");
    setConnectionTargetRef("");
    setError("");
    setExported("");
    savedProposals.current.clear();
    exportRequest.current++;
    api(`/caf/${id}/graphs`)
      .then((result: GraphInventory) => {
        if (!active) return;
        setInventory(result);
        setDiagramRef(result.diagrams[0]?.ref || "");
      })
      .catch((e) => {
        if (active) setError(e.message);
      })
      .finally(() => {
        if (active) setLoadingIndex(false);
      });
    return () => {
      active = false;
    };
  }, [id, refresh]);

  useEffect(() => {
    let active = true;
    setDiagram(null);
    setWireIndex(0);
    setSourceRef("");
    setConnectionSourceRef("");
    setConnectionTargetRef("");
    if (!diagramRef) {
      setLoadingGraph(false);
      return;
    }
    setLoadingGraph(true);
    setError("");
    api(`/caf/${id}/graph?ref=${encodeURIComponent(diagramRef)}`)
      .then((result: NativeDiagram) => {
        if (active) setDiagram(result);
      })
      .catch((e) => {
        if (active) setError(e.message);
      })
      .finally(() => {
        if (active) setLoadingGraph(false);
      });
    return () => {
      active = false;
    };
  }, [id, diagramRef]);

  const blockByRef = useMemo(
    () => new Map(diagram?.blocks.map((block) => [block.ref, block]) || []),
    [diagram],
  );
  const wire = diagram?.connections.find((item) => item.index === wireIndex);
  const currentSource = wire ? blockByRef.get(wire.source_ref) : undefined;
  const destination = wire ? blockByRef.get(wire.target_ref) : undefined;
  const sources = useMemo(() => {
    if (!diagram || !wire || !currentSource || !destination) return [];
    return diagram.blocks.filter(
      (block) =>
        block.ref !== currentSource.ref &&
        block.class_id === currentSource.class_id &&
        block.class_version === currentSource.class_version &&
        block.execution_index < destination.execution_index &&
        diagram.connections.some(
          (connection) =>
            connection.source_ref === block.ref &&
            connection.source_port === wire.source_port,
        ),
    );
  }, [diagram, wire, currentSource, destination]);
  const proposedSource = sources.find((item) => item.ref === sourceRef);
  const proposed =
    wire && proposedSource
      ? [proposedSource.index, ...wire.raw.slice(1)]
      : null;
  const connectionSource = blockByRef.get(connectionSourceRef) || currentSource;
  const connectionSources =
    diagram?.blocks.filter(
      (block) =>
        block.class_id === currentSource?.class_id &&
        block.class_version === currentSource?.class_version,
    ) || [];
  const connectionTargets =
    diagram?.blocks.filter(
      (block) =>
        block.class_id === destination?.class_id &&
        block.class_version === destination?.class_version &&
        connectionSource &&
        block.execution_index > connectionSource.execution_index &&
        !diagram.connections.some(
          (item) =>
            item.target_ref === block.ref &&
            item.target_port === wire?.target_port,
        ),
    ) || [];
  const connectionTarget = connectionTargets.find(
    (block) => block.ref === connectionTargetRef,
  );
  const connectionTuple =
    wire && connectionSource && connectionTarget
      ? [
          connectionSource.index,
          wire.source_port,
          connectionTarget.index,
          wire.target_port,
        ]
      : null;
  const rewireKey = proposed
    ? JSON.stringify(["rewire", id, diagramRef, wireIndex, proposed])
    : "";
  const connectionKey = connectionTuple
    ? JSON.stringify(["connect", id, diagramRef, wireIndex, connectionTuple])
    : "";
  const dirty = Boolean(
    (rewireKey && !savedProposals.current.has(rewireKey)) ||
      (connectionKey && !savedProposals.current.has(connectionKey)),
  );
  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);
  useEffect(() => () => onDirtyChange?.(false), [onDirtyChange]);

  function discardProposals() {
    return (
      !dirty ||
      window.confirm(
        "Discard unexported native CAF connection proposals? Cancel to keep the proposal or export its copy first.",
      )
    );
  }

  function selectWire(index: number) {
    if (disabled || exporting || index === wireIndex || !discardProposals())
      return;
    setWireIndex(index);
    setSourceRef("");
    setConnectionSourceRef("");
    setConnectionTargetRef("");
    setError("");
  }

  async function exportRewire() {
    if (!diagram || !wire || !proposedSource || exporting || disabled) return;
    const request = ++exportRequest.current;
    const archive = id;
    const key = rewireKey;
    const current = () =>
      mounted.current &&
      request === exportRequest.current &&
      activeArchive.current === archive;
    setExporting(true);
    setError("");
    try {
      const name = editedFilename(filename);
      const saved = await download(
        `/caf/${id}/rewire`,
        {
          changes: [
            {
              diagram_ref: diagram.ref,
              wire_index: wire.index,
              old: wire.raw,
              source_ref: proposedSource.ref,
            },
          ],
        },
        name,
        current,
      );
      if (!saved || !current()) return;
      savedProposals.current.add(key);
      setExported(
        `Browser download requested for ${name}: connection #${wire.index}, ${JSON.stringify(wire.raw)} to ${JSON.stringify(proposed)}. This view still shows the original archive. Open the downloaded copy to inspect the changed records.`,
      );
    } catch (e) {
      if (current()) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (current()) setExporting(false);
    }
  }

  async function exportConnection() {
    if (
      !diagram ||
      !wire ||
      !connectionSource ||
      !connectionTarget ||
      exporting ||
      disabled
    )
      return;
    const request = ++exportRequest.current;
    const archive = id;
    const key = connectionKey;
    const current = () =>
      mounted.current &&
      request === exportRequest.current &&
      activeArchive.current === archive;
    setExporting(true);
    setError("");
    try {
      const name = editedFilename(filename, "connected");
      const saved = await download(
        `/caf/${id}/connect`,
        {
          changes: [
            {
              diagram_ref: diagram.ref,
              prototype_diagram_ref: diagram.ref,
              prototype_wire_index: wire.index,
              prototype_old: wire.raw,
              source_ref: connectionSource.ref,
              target_ref: connectionTarget.ref,
              old_connection_count: diagram.connections.length,
            },
          ],
        },
        name,
        current,
      );
      if (!saved || !current()) return;
      savedProposals.current.add(key);
      setExported(
        `Browser download requested for ${name}: added native connection ${JSON.stringify(connectionTuple)}. This view still shows the original archive. Open the downloaded copy to inspect the added native connection.`,
      );
    } catch (e) {
      if (current()) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (current()) setExporting(false);
    }
  }

  return (
    <section className="card caf-native-graph" aria-label="Native CAF graph">
      <div className="card-header">
        <h3>
          <GitBranch size={17} /> Native CAF diagrams
        </h3>
        <button
          aria-label="Reload native CAF diagrams"
          disabled={disabled || loadingIndex || loadingGraph || exporting}
          onClick={() => {
            if (discardProposals()) setRefresh((value) => value + 1);
          }}
        >
          <RefreshCw size={14} /> Reload
        </button>
      </div>
      <div className="caf-graph-body">
        <p className="caf-graph-scope">
          Inspect native block, connection and execution-order records. Property
          IDs remain native IDs; unknown fields retain their original meaning.
          Exported changes are uncompiled. CCT/PCT acceptance and controller
          execution remain unverified.
        </p>
        {scalarChangeCount > 0 && (
          <p className="caf-graph-help" role="note">
            Native connection copies use the original archive and exclude the{" "}
            {scalarChangeCount} scalar edit{scalarChangeCount === 1 ? "" : "s"}{" "}
            displayed below. To combine changes, export and open the
            scalar-edited copy first.
          </p>
        )}
        {loadingIndex && <p role="status">Reading native diagrams…</p>}
        {inventory && (
          <>
            <div className="caf-graph-selector">
              <label>
                Native diagram
                <select
                  aria-label="Native CAF diagram"
                  value={diagramRef}
                  disabled={disabled || !inventory.diagrams.length || exporting}
                  onChange={(event) => {
                    if (event.target.value === diagramRef || discardProposals())
                      setDiagramRef(event.target.value);
                  }}
                >
                  {!inventory.diagrams.length && (
                    <option value="">No recognized diagrams</option>
                  )}
                  {inventory.diagrams.map((item) => (
                    <option value={item.ref} key={item.ref}>
                      {item.name || item.ref} · {item.blocks} blocks ·{" "}
                      {item.connections} connections
                    </option>
                  ))}
                </select>
              </label>
              <small>
                {inventory.diagrams.length} inspected diagrams ·{" "}
                {inventory.errors.length} unreadable diagrams
              </small>
            </div>
            {inventory.errors.length > 0 && (
              <details className="caf-graph-errors">
                <summary>Inspect unsupported diagram records</summary>
                {inventory.errors.map((item) => (
                  <p key={item.ref}>
                    <code>{item.ref}</code>: {item.error}
                  </p>
                ))}
              </details>
            )}
            {!inventory.diagrams.length && !inventory.errors.length && (
              <p>
                This archive contains no recognized Control Activity or Control
                Sequence diagrams. Its object inventory remains available below.
              </p>
            )}
          </>
        )}
        {loadingGraph && <p role="status">Reading selected native graph…</p>}
        {diagram && (
          <>
            <div className="caf-graph-summary">
              <span>
                Class {diagram.class_id} · version {diagram.class_version}
              </span>
              <span>
                {diagram.blocks.length} blocks · {diagram.connections.length}{" "}
                connections
              </span>
              <code>{diagram.ref}</code>
            </div>
            <div className="caf-graph-columns">
              <section
                className="caf-graph-table"
                aria-label="Native connections"
              >
                <h4>Connections · property 3118</h4>
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Record</th>
                        <th>Source · property</th>
                        <th>Destination · property</th>
                      </tr>
                    </thead>
                    <tbody>
                      {diagram.connections.map((item) => (
                        <tr
                          key={item.index}
                          className={
                            item.index === wireIndex ? "active-row" : ""
                          }
                        >
                          <td>
                            <button
                              aria-label={`Select native connection ${item.index}`}
                              aria-pressed={item.index === wireIndex}
                              disabled={disabled || exporting}
                              onClick={() => selectWire(item.index)}
                            >
                              #{item.index}
                            </button>
                          </td>
                          <td>
                            <b>{blockTitle(blockByRef.get(item.source_ref))}</b>
                            <small>Property {item.source_port}</small>
                          </td>
                          <td>
                            <b>{blockTitle(blockByRef.get(item.target_ref))}</b>
                            <small>Property {item.target_port}</small>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {!diagram.connections.length && (
                  <p>This diagram contains no connection records.</p>
                )}
              </section>
              <section
                className="caf-source-rewire"
                aria-label="Native source rewire"
              >
                <h4>Change an existing connection source</h4>
                {wire && currentSource && destination ? (
                  <>
                    <dl>
                      <div>
                        <dt>Connection</dt>
                        <dd>#{wire.index}</dd>
                      </div>
                      <div>
                        <dt>Current source</dt>
                        <dd>
                          {blockTitle(currentSource)} · property{" "}
                          {wire.source_port}
                        </dd>
                      </div>
                      <div>
                        <dt>Destination</dt>
                        <dd>
                          {blockTitle(destination)} · property{" "}
                          {wire.target_port}
                        </dd>
                      </div>
                      <div>
                        <dt>Continuation</dt>
                        <dd>
                          {wire.continuation.flag ? "true" : "false"} ·{" "}
                          {wire.continuation.text || "(empty text)"}
                        </dd>
                      </div>
                    </dl>
                    <label>
                      Replacement source
                      <select
                        aria-label="Native replacement source"
                        value={sourceRef}
                        disabled={
                          !sources.length ||
                          disabled ||
                          exporting ||
                          !diagram.observed_version
                        }
                        onChange={(event) => {
                          setSourceRef(event.target.value);
                          setError("");
                        }}
                      >
                        <option value="">
                          {sources.length
                            ? "Select existing source…"
                            : "No matching visible source"}
                        </option>
                        {sources.map((block) => (
                          <option key={block.ref} value={block.ref}>
                            {blockTitle(block)} · block index {block.index}
                          </option>
                        ))}
                      </select>
                    </label>
                    <p className="caf-graph-help">
                      Choices already use property {wire.source_port}, share the
                      source class/version and execute before this destination.
                      Export also checks opaque configuration, the original
                      tuple and feedback paths. A mismatch rejects the edit with
                      its reason.
                    </p>
                    <div
                      className="caf-rewire-review"
                      aria-label="Native rewire review"
                    >
                      <small>Existing tuple</small>
                      <code>{JSON.stringify(wire.raw)}</code>
                      <small>Proposed tuple</small>
                      <code>
                        {proposed
                          ? JSON.stringify(proposed)
                          : "Choose a source"}
                      </code>
                      <small>
                        Tuple: source block index, source property, destination
                        block index, destination property.
                      </small>
                    </div>
                    <button
                      className="primary"
                      disabled={
                        !proposed ||
                        disabled ||
                        exporting ||
                        !diagram.observed_version
                      }
                      onClick={exportRewire}
                    >
                      <Download size={15} />
                      {exporting
                        ? "Checking native records…"
                        : "Check and export native CAF rewire"}
                    </button>
                    {!diagram.observed_version && (
                      <p className="caf-graph-help">
                        Rewiring requires observed class version 1.0. This
                        diagram can be inspected only.
                      </p>
                    )}
                    <p className="caf-graph-help">
                      The export changes one source index in a separate native
                      CAF copy. Block identities, property IDs and all other XML
                      bytes are preserved. Scalar edits elsewhere in this page
                      are separate exports.
                    </p>
                  </>
                ) : (
                  <p>Select an existing connection to review its source.</p>
                )}
              </section>
            </div>
            {wire && currentSource && destination && (
              <details className="caf-connection-create">
                <summary>Add native connection between existing blocks</summary>
                <p className="caf-graph-help">
                  Connection #{wire.index} supplies the observed
                  source/destination interface prototype. The new connection
                  uses property {wire.source_port} to property{" "}
                  {wire.target_port}. Both endpoint configurations must match
                  the prototype; the destination property must be unused.
                </p>
                <div className="caf-connection-endpoints">
                  <label>
                    New connection source
                    <select
                      aria-label="Native new connection source"
                      value={connectionSource?.ref || ""}
                      disabled={
                        disabled || exporting || !diagram.observed_version
                      }
                      onChange={(event) => {
                        setConnectionSourceRef(event.target.value);
                        setConnectionTargetRef("");
                        setError("");
                      }}
                    >
                      {connectionSources.map((block) => (
                        <option key={block.ref} value={block.ref}>
                          {blockTitle(block)} · block index {block.index}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    New connection destination
                    <select
                      aria-label="Native new connection destination"
                      value={connectionTargetRef}
                      disabled={
                        exporting ||
                        disabled ||
                        !diagram.observed_version ||
                        !connectionTargets.length
                      }
                      onChange={(event) => {
                        setConnectionTargetRef(event.target.value);
                        setError("");
                      }}
                    >
                      <option value="">
                        {connectionTargets.length
                          ? "Select unused destination…"
                          : "No matching unused destination"}
                      </option>
                      {connectionTargets.map((block) => (
                        <option key={block.ref} value={block.ref}>
                          {blockTitle(block)} · block index {block.index}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <div
                  className="caf-rewire-review"
                  aria-label="Native new connection review"
                >
                  <small>Prototype tuple</small>
                  <code>{JSON.stringify(wire.raw)}</code>
                  <small>New tuple</small>
                  <code>
                    {connectionTuple
                      ? JSON.stringify(connectionTuple)
                      : "Choose a destination"}
                  </code>
                  <small>
                    Append to {diagram.connections.length} existing connection
                    records. Existing records and block identities stay intact.
                    The new continuation record starts with false and empty
                    text.
                  </small>
                </div>
                <button
                  className="primary"
                  disabled={
                    !connectionTuple ||
                    disabled ||
                    exporting ||
                    !diagram.observed_version
                  }
                  onClick={exportConnection}
                >
                  <Download size={15} /> Check and export new native CAF
                  connection
                </button>
                <p className="caf-graph-help">
                  Export checks the exact prototype and current record count,
                  native endpoint configuration, execution order and feedback.
                  Controller resource capacity and CCT/PCT acceptance remain
                  unverified. The new connection is a separate CAF export.
                </p>
              </details>
            )}
            <details className="caf-graph-blocks">
              <summary>
                Inspect {diagram.blocks.length} native blocks and execution
                order
              </summary>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Block / execution index</th>
                      <th>Name / reference</th>
                      <th>Class / BACnet identity</th>
                      <th>Exposed property IDs</th>
                    </tr>
                  </thead>
                  <tbody>
                    {diagram.blocks.map((block) => (
                      <tr key={block.ref}>
                        <td className="mono">
                          {block.index} / {block.execution_index}
                        </td>
                        <td>
                          <b>{blockTitle(block)}</b>
                          <small className="mono">{block.ref}</small>
                        </td>
                        <td>
                          Class {block.class_id} · v{block.class_version}
                          <small>
                            BACnet type {block.bacnet_type}, instance{" "}
                            {block.instance}
                          </small>
                        </td>
                        <td className="mono">
                          {block.exposed_ports
                            .map((port) => port.id)
                            .join(", ") || "Not listed"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          </>
        )}
        {error && (
          <div className="inline-error" role="alert">
            {error}
          </div>
        )}
        {exported && (
          <p className="caf-graph-exported" role="status">
            {exported}
          </p>
        )}
      </div>
    </section>
  );
}
