import { memo, useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position as Side,
  ReactFlow,
  ReactFlowProvider,
  applyNodeChanges,
  useReactFlow,
  type Connection,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import { api } from "./api";
import { ResponsivePanel } from "./ResponsivePanel";
import {
  CAF_CANVAS_BLOCKS,
  CAF_CANVAS_WIRES,
  blockTitle,
  diagramPorts,
  nodeHeight,
  readablePositions,
  traceRefs,
  type CafBlock,
  type CafDiagram,
  type CafPorts,
  type Position,
  type WiringProposal,
  wiringProposal,
} from "./cafLogic";
import "@xyflow/react/dist/style.css";
import "./caf-logic.css";

type View = {
  layout: "readable" | "recorded";
  positions: Record<string, Position>;
  selected: string;
};
const retained = new Map<string, View>();
type LogicNode = Node<
  { block: CafBlock; ports: CafPorts; module: boolean; trace: string },
  "cafLogic"
>;
const LogicBlock = memo(function LogicBlock({
  data,
  selected,
}: NodeProps<LogicNode>) {
  return (
    <div
      className={`caf-logic-node ${selected ? "is-selected" : ""} ${data.trace}`}
      style={{ height: nodeHeight(data.ports) }}
    >
      <div className="caf-logic-node-heading">
        <span title={data.block.class_name}>{data.block.class_name}</span>
        <small title="Original execution order">
          Seq {data.block.execution_index + 1}
        </small>
      </div>
      <strong className="caf-logic-node-name" title={blockTitle(data.block)}>
        {blockTitle(data.block)}
        {data.module ? " ↳" : ""}
      </strong>
      {(["inputs", "outputs"] as const).map((side) =>
        data.ports[side].map((p, index) => (
          <div
            key={`${side}:${p.id}`}
            className={`caf-logic-port ${side} ${p.observed ? "" : "prototype-port"}`}
            style={{ top: 72 + index * 26 }}
            title={`${p.label} · native property ${p.id} · ${p.observed ? "recorded wire" : "exposed port; direction observed on same class/version"}`}
          >
            <Handle
              type={side === "inputs" ? "target" : "source"}
              position={side === "inputs" ? Side.Left : Side.Right}
              id={`${side === "inputs" ? "in" : "out"}:${p.id}`}
              aria-label={`${side === "inputs" ? "Input" : "Output"} ${p.id} on ${blockTitle(data.block)}`}
            />
            <span>
              {p.label}
              <small>{p.id}</small>
            </span>
          </div>
        )),
      )}
    </div>
  );
});
const nodeTypes = { cafLogic: LogicBlock };
type Props = {
  archive: string;
  diagram: CafDiagram;
  selectedWire: number;
  moduleRefs: Set<string>;
  onSelectWire: (index: number) => void;
  onOpenModule: (ref: string) => void;
  onInspectObject?: (block: CafBlock) => void;
  onPropose: (proposal: WiringProposal) => boolean;
  proposal?: {
    kind: string;
    source: string;
    target: string;
    sourcePort: number;
    targetPort: number;
  } | null;
};
export function CafLogicCanvas(props: Props) {
  return (
    <ReactFlowProvider key={JSON.stringify([props.archive, props.diagram.ref])}>
      <LogicWorkspace {...props} />
    </ReactFlowProvider>
  );
}
function LogicWorkspace({
  archive,
  diagram,
  selectedWire,
  moduleRefs,
  onSelectWire,
  onOpenModule,
  onInspectObject,
  onPropose,
  proposal,
}: Props) {
  const owner = JSON.stringify([archive, diagram.ref]),
    initial = retained.get(owner);
  const [layout, setLayout] = useState<View["layout"]>(
    initial?.layout || "readable",
  );
  const [selected, setSelected] = useState(initial?.selected || ""),
    [query, setQuery] = useState("");
  const [trace, setTrace] = useState<
    "both" | "upstream" | "downstream" | "none"
  >("both");
  const [revision, setRevision] = useState(0);
  const [viewError, setViewError] = useState("");
  const [error, setError] = useState(""),
    [properties, setProperties] = useState<any[]>([]),
    [loading, setLoading] = useState(false);
  const positions = useRef<Record<string, Position>>({
    ...(initial?.positions || {}),
  });
  const ports = useMemo(() => diagramPorts(diagram), [diagram]);
  const readable = useMemo(
    () => readablePositions(diagram, ports),
    [diagram, ports],
  );
  const up = useMemo(
    () => traceRefs(diagram, selected, "upstream"),
    [diagram, selected],
  );
  const down = useMemo(
    () => traceRefs(diagram, selected, "downstream"),
    [diagram, selected],
  );
  const flow = useReactFlow<LogicNode>();
  const [nodes, setNodes] = useState<LogicNode[]>([]);
  const persist = (selection = selected) => {
    if (!retained.has(owner) && retained.size >= 32) {
      setViewError(
        "32 view layouts are retained. Reset an earlier layout before retaining another. No earlier layout was discarded.",
      );
      return;
    }
    retained.set(owner, {
      layout,
      positions: { ...positions.current },
      selected: selection,
    });
  };
  const node = diagram.blocks.find((b) => b.ref === selected);
  const wire = diagram.connections.find((w) => w.index === selectedWire);
  const bounded =
    diagram.blocks.length <= CAF_CANVAS_BLOCKS &&
    diagram.connections.length <= CAF_CANVAS_WIRES;
  useEffect(() => {
    if (!bounded) return;
    setNodes((current) => {
      const previous = new Map(current.map((n) => [n.id, n]));
      return diagram.blocks.map((b) => ({
        // Retain measured dimensions across selection/trace updates. Dropping
        // them briefly hides nodes while React Flow measures them again, which
        // can send the second click of a double-click to the empty canvas.
        ...previous.get(b.ref),
        id: b.ref,
        type: "cafLogic",
        selected: b.ref === selected,
        position:
          positions.current[b.ref] ||
          (layout === "readable"
            ? readable[b.ref]
            : { x: Number(b.layout.x) * 4, y: Number(b.layout.y) * 2 }),
        data: {
          block: b,
          ports: ports.get(b.ref)!,
          module: moduleRefs.has(b.ref),
          trace:
            selected &&
            (((trace === "both" || trace === "upstream") && up.has(b.ref)) ||
              ((trace === "both" || trace === "downstream") && down.has(b.ref)))
              ? "in-trace"
              : selected && trace !== "none" && b.ref !== selected
                ? "outside-trace"
                : "",
        },
      }));
    });
  }, [
    diagram,
    layout,
    selected,
    ports,
    readable,
    up,
    down,
    trace,
    moduleRefs,
    bounded,
    revision,
  ]);
  useEffect(() => {
    let active = true;
    setProperties([]);
    setLoading(!!selected);
    setError("");
    if (selected)
      void api(`/caf/${archive}/properties?ref=${encodeURIComponent(selected)}`)
        .then((r) => {
          if (active) setProperties(r);
        })
        .catch((e) => {
          if (active) setError(String(e));
        })
        .finally(() => {
          if (active) setLoading(false);
        });
    return () => {
      active = false;
    };
  }, [archive, selected]);
  function select(ref: string, focus = false) {
    setSelected(ref);
    persist(ref);
    const item = flow.getNode(ref);
    if (focus && item)
      void flow.setCenter(
        item.position.x + 141,
        item.position.y + nodeHeight(item.data.ports) / 2,
        { zoom: 1.2, duration: 200 },
      );
  }
  if (!bounded)
    return (
      <p role="status">
        This diagram exceeds the interactive view budget ({CAF_CANVAS_BLOCKS}{" "}
        blocks / {CAF_CANVAS_WIRES} wires). Its complete native records remain
        in the connection table. Open a smaller module for graphical inspection.
      </p>
    );
  const edges = diagram.connections.map((w) => {
    const traced =
      selected &&
      trace !== "none" &&
      (((trace === "both" || trace === "upstream") &&
        (w.target_ref === selected || up.has(w.target_ref)) &&
        up.has(w.source_ref)) ||
        ((trace === "both" || trace === "downstream") &&
          (w.source_ref === selected || down.has(w.source_ref)) &&
          down.has(w.target_ref)));
    const active = !selected && w.index === selectedWire;
    return {
      id: `wire:${w.index}`,
      source: w.source_ref,
      target: w.target_ref,
      sourceHandle: `out:${w.source_port}`,
      targetHandle: `in:${w.target_port}`,
      type: "smoothstep",
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: active || traced ? "#087d80" : "#89999f",
      },
      style: {
        stroke: active || traced ? "#087d80" : "#89999f",
        strokeWidth: active || traced ? 2.5 : 1.2,
        opacity: selected && trace !== "none" && !traced ? 0.18 : 0.9,
        strokeDasharray: w.continuation.flag ? "5 3" : undefined,
      },
      interactionWidth: 18,
      label: active
        ? `#${w.index} · ${w.source_port} → ${w.target_port}`
        : undefined,
      ariaLabel: `Native connection ${w.index}, property ${w.source_port} to ${w.target_port}`,
    };
  });
  const draftEdges = proposal
    ? [
        {
          id: "local-proposal",
          source: proposal.source,
          target: proposal.target,
          sourceHandle: `out:${proposal.sourcePort}`,
          targetHandle: `in:${proposal.targetPort}`,
          type: "smoothstep",
          style: { stroke: "#b56d18", strokeWidth: 3, strokeDasharray: "7 5" },
          label: "Local proposal",
          markerEnd: { type: MarkerType.ArrowClosed, color: "#b56d18" },
        },
      ]
    : [];
  function connect(c: Connection) {
    try {
      if (
        !/^out:\d+$/.test(c.sourceHandle || "") ||
        !/^in:\d+$/.test(c.targetHandle || "")
      )
        throw Error("Choose explicit native output and input handles.");
      const p = wiringProposal(
        diagram,
        c.source,
        Number(c.sourceHandle!.split(":")[1]),
        c.target,
        Number(c.targetHandle!.split(":")[1]),
      );
      if (onPropose(p)) {
        setError("");
        setSelected("");
      }
    } catch (e) {
      setError(String(e));
    }
  }
  const matches = diagram.blocks.filter((b) =>
    [blockTitle(b), b.class_name, b.ref]
      .join(" ")
      .toLowerCase()
      .includes(query.toLowerCase()),
  );
  const duplicates =
    new Set(diagram.blocks.map((b) => `${b.layout.x},${b.layout.y}`)).size <
    diagram.blocks.length;
  return (
    <section
      className="caf-logic-workspace"
      aria-label="CAF graphical logic workspace"
    >
      <div className="caf-logic-toolbar">
        <label>
          Diagram layout
          <select
            aria-label="CAF diagram layout"
            value={layout}
            onChange={(e) => {
              positions.current = {};
              setLayout(e.target.value as View["layout"]);
              retained.delete(owner);
            }}
          >
            <option value="readable">Readable signal flow</option>
            <option value="recorded">Recorded CAF coordinates</option>
          </select>
        </label>
        <button
          onClick={() => void flow.fitView({ padding: 0.15, maxZoom: 1 })}
        >
          Fit diagram
        </button>
        <button
          disabled={!selected}
          onClick={() => selected && select(selected, true)}
        >
          Focus selected block
        </button>
        <button
          onClick={() => {
            positions.current = {};
            retained.delete(owner);
            setLayout("readable");
            setSelected("");
            setViewError("");
            setRevision((n) => n + 1);
          }}
        >
          Reset view positions
        </button>
        <label>
          Trace signal
          <select
            aria-label="CAF signal trace"
            value={trace}
            onChange={(e) => setTrace(e.target.value as typeof trace)}
          >
            <option value="both">Inputs and outputs</option>
            <option value="upstream">Inputs upstream</option>
            <option value="downstream">Outputs downstream</option>
            <option value="none">All connections</option>
          </select>
        </label>
      </div>
      <p className="caf-logic-source">
        Local CAF · drag blocks to arrange this view; positions do not edit the
        archive or execution order. Drag named ports to propose a guarded
        connection. Double-click a module to open its logic.
      </p>
      {layout === "recorded" && duplicates && (
        <p role="status">
          Some recorded coordinates overlap. Readable signal flow separates
          these blocks.
        </p>
      )}
      {(error || viewError) && (
        <p role="alert" className="inline-error">
          {error || viewError}
        </p>
      )}
      <div className="caf-logic-grid">
        <aside className="caf-logic-finder" aria-label="CAF block finder">
          <label>
            Find a logic block
            <input
              type="search"
              aria-label="Find CAF logic block"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
          <small>{matches.length} blocks · original execution order</small>
          <div>
            {[...matches]
              .sort((a, b) => a.execution_index - b.execution_index)
              .map((b) => (
                <button
                  key={b.ref}
                  aria-pressed={selected === b.ref}
                  onClick={() => select(b.ref, true)}
                >
                  <strong>{blockTitle(b)}</strong>
                  <small>
                    {b.class_name} · Seq {b.execution_index + 1}
                    {moduleRefs.has(b.ref) ? " · Module ↳" : ""}
                  </small>
                </button>
              ))}
          </div>
        </aside>
        <div className="caf-logic-canvas" aria-label="CAF native block diagram">
          {bounded ? (
            <ReactFlow
              nodes={nodes}
              edges={[...edges, ...draftEdges]}
              nodeTypes={nodeTypes}
              minZoom={0.02}
              maxZoom={2.5}
              fitView
              fitViewOptions={{ padding: 0.15, maxZoom: 1 }}
              nodesDraggable
              nodesConnectable={diagram.observed_version}
              edgesFocusable
              deleteKeyCode={null}
              selectionOnDrag
              onNodesChange={(changes) =>
                setNodes((current) => applyNodeChanges(changes, current))
              }
              onNodeClick={(_, b) => select(b.id)}
              onNodeDoubleClick={(_, b) =>
                moduleRefs.has(b.id) && onOpenModule(b.id)
              }
              onNodeDragStop={(_, b) => {
                positions.current[b.id] = { ...b.position };
                persist();
              }}
              onEdgeClick={(_, e) => {
                if (e.id.startsWith("wire:")) {
                  setSelected("");
                  onSelectWire(Number(e.id.split(":")[1]));
                }
              }}
              onConnect={connect}
              onPaneClick={() => setSelected("")}
              proOptions={{ hideAttribution: true }}
            >
              <Background gap={20} />
              <MiniMap
                pannable
                zoomable
                nodeColor={(n) => (n.id === selected ? "#087d80" : "#9dbfbe")}
              />
              <Controls showInteractive={false} />
            </ReactFlow>
          ) : (
            <p>
              This diagram exceeds the interactive view budget (
              {CAF_CANVAS_BLOCKS} blocks / {CAF_CANVAS_WIRES} wires). Its
              complete native records remain in the connection table. Open a
              smaller module for graphical inspection.
            </p>
          )}
        </div>
        <ResponsivePanel
          name="CAF logic inspector"
          panel="inspector"
          side="right"
          triggerText="Logic inspector"
          triggerLabel="Open CAF logic inspector"
          closeLabel="Close CAF logic inspector"
          retireKey={owner}
          openSignal={selected || `wire:${selectedWire}`}
          context="Local CAF configuration"
        >
          {node ? (
            <section aria-label="CAF selected logic block">
              <h4>{blockTitle(node)}</h4>
              <p>
                {node.class_name} · Class {node.class_id}, version{" "}
                {node.class_version}
              </p>
              <p>
                Execution order {node.execution_index + 1} · BACnet type{" "}
                {node.bacnet_type}, instance {node.instance}
              </p>
              <code>{node.ref}</code>
              {moduleRefs.has(node.ref) && (
                <button onClick={() => onOpenModule(node.ref)}>
                  Open module logic
                </button>
              )}
              {onInspectObject && (
                <button onClick={() => onInspectObject(node)}>
                  Edit object properties
                </button>
              )}
              <p>Stored CAF values. Live controller values are separate.</p>
              {loading && <p role="status">Reading stored block properties…</p>}
              <table>
                <thead>
                  <tr>
                    <th>Property</th>
                    <th>Stored value</th>
                  </tr>
                </thead>
                <tbody>
                  {properties
                    .filter((p) => p.scalar)
                    .slice(0, 64)
                    .map((p, i) => (
                      <tr key={p.id + ":" + i}>
                        <td>
                          {p.name} ({p.id})<small>{p.kind}</small>
                        </td>
                        <td>{p.scalar.text}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
              <details>
                <summary>Port evidence and recorded coordinates</summary>
                <pre>
                  {JSON.stringify(
                    {
                      ports: ports.get(node.ref),
                      recorded_layout: node.layout,
                    },
                    null,
                    2,
                  )}
                </pre>
              </details>
            </section>
          ) : wire ? (
            <section aria-label="CAF selected logic connection">
              <h4>Connection #{wire.index}</h4>
              <p>
                {blockTitle(
                  diagram.blocks.find((b) => b.ref === wire.source_ref),
                )}{" "}
                · {wire.source_port}
              </p>
              <p>
                →{" "}
                {blockTitle(
                  diagram.blocks.find((b) => b.ref === wire.target_ref),
                )}{" "}
                · {wire.target_port}
              </p>
              <p>
                {wire.continuation.flag
                  ? "Recorded continuation"
                  : "Direct recorded connection"}
                : {wire.continuation.text || "No continuation label"}
              </p>
              <code>{JSON.stringify(wire.raw)}</code>
            </section>
          ) : (
            <p>Select a block or connection.</p>
          )}
        </ResponsivePanel>
      </div>
    </section>
  );
}
