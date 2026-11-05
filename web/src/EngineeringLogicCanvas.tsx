import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  Background,
  Controls,
  MarkerType,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  applyNodeChanges,
  useReactFlow,
  type Connection,
} from "@xyflow/react";
import { api } from "./api";
import { ResponsivePanel } from "./ResponsivePanel";
import {
  CAF_CANVAS_BLOCKS,
  CAF_CANVAS_WIRES,
  blockTitle,
  diagramPorts,
  traceRefs,
  type CafBlock,
  type CafDiagram,
  type Position,
  type WiringProposal,
  wiringProposal,
} from "./cafLogic";
import "@xyflow/react/dist/style.css";
import "./caf-logic.css";
import "./engineering-logic.css";
import {
  EngineeringLogicNode,
  type EngineeringNode,
} from "./EngineeringLogicNode";
import {
  engineeringPositions,
  logicSize,
  type LiveLogicValue,
} from "./engineeringLogic";

type View = {
  layout: "readable" | "recorded";
  positions: Record<string, Position>;
  selected: string;
};
const retained = new Map<string, View>();
const expandedSources = new Set<string>();
type LogicNode = EngineeringNode;
const nodeTypes = { engineeringLogic: EngineeringLogicNode };
type Props = {
  archive: string;
  diagram: CafDiagram;
  selectedWire: number;
  moduleRefs: Set<string>;
  activityNames?: Record<string, string>;
  onSelectWire: (index: number) => void;
  onOpenModule: (ref: string) => void;
  onInspectObject?: (block: CafBlock) => void;
  onPropose?: (proposal: WiringProposal) => boolean;
  sourceKind?: "caf" | "controller";
  sourceLabel?: string;
  onSelectBlock?: (ref: string) => void;
  selectedBlock?: string;
  inspector?: ReactNode;
  liveValue?: LiveLogicValue;
  proposal?: {
    kind: string;
    source: string;
    target: string;
    sourcePort: number;
    targetPort: number;
  } | null;
};
export function EngineeringLogicCanvas(props: Props) {
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
  activityNames,
  onSelectWire,
  onOpenModule,
  onInspectObject,
  onPropose,
  proposal,
  sourceKind = "caf",
  sourceLabel,
  selectedBlock,
  onSelectBlock,
  inspector,
  liveValue,
}: Props) {
  const prefix = sourceKind === "caf" ? "CAF" : "Controller";
  const editable =
    sourceKind === "caf" && !!onPropose && diagram.observed_version;
  const owner = JSON.stringify([sourceKind, archive, diagram.ref]),
    initial = retained.get(owner);
  const [layout, setLayout] = useState<View["layout"]>(
    initial?.layout || "readable",
  );
  const [selection, setSelection] = useState(initial?.selected || ""),
    [query, setQuery] = useState("");
  const selected = selectedBlock ?? selection;
  const [wireChosen, setWireChosen] = useState(false);
  const previousWire = useRef(selectedWire);
  useEffect(() => {
    if (previousWire.current !== selectedWire) setWireChosen(true);
    previousWire.current = selectedWire;
  }, [selectedWire]);
  const setSelected = (value: string) => {
    setSelection(value);
    onSelectBlock?.(value);
  };
  const [trace, setTrace] = useState<
    "both" | "upstream" | "downstream" | "none"
  >("both");
  const [revision, setRevision] = useState(0);
  const expansionKey = JSON.stringify([sourceKind, archive]);
  const [expanded, updateExpanded] = useState(
    expandedSources.has(expansionKey),
  );
  const setExpanded = (value: boolean) => {
    if (value && expandedSources.size < 32) expandedSources.add(expansionKey);
    if (!value) expandedSources.delete(expansionKey);
    updateExpanded(value);
  };
  const workspace = useRef<HTMLDialogElement>(null);
  const expandButton = useRef<HTMLButtonElement>(null);
  const focusRequest = useRef(0);
  useEffect(
    () => () => {
      focusRequest.current++;
    },
    [],
  );
  useLayoutEffect(() => {
    const element = workspace.current;
    if (!element) return;
    if (expanded) {
      if (element.open && !element.matches(":modal")) element.close();
      if (!element.open) element.showModal();
      element.focus();
    } else {
      const wasModal = element.open && element.matches(":modal");
      if (wasModal) element.close();
      element.setAttribute("open", "");
      if (wasModal) expandButton.current?.focus();
    }
  }, [expanded]);
  const [viewError, setViewError] = useState("");
  const [error, setError] = useState(""),
    [properties, setProperties] = useState<any[]>([]),
    [loading, setLoading] = useState(false);
  const positions = useRef<Record<string, Position>>({
    ...(initial?.positions || {}),
  });
  const ports = useMemo(() => diagramPorts(diagram), [diagram]);
  const readable = useMemo(
    () => engineeringPositions(diagram, ports),
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
  const wire = wireChosen
    ? diagram.connections.find((w) => w.index === selectedWire)
    : undefined;
  const hasInspector = !!node || !!wire;
  const fanout = useMemo(() => {
    const result = new Map<string, Record<number, number>>();
    for (const w of diagram.connections) {
      const counts = result.get(w.source_ref) || {};
      counts[w.source_port] = (counts[w.source_port] || 0) + 1;
      result.set(w.source_ref, counts);
    }
    return result;
  }, [diagram]);
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
        type: "engineeringLogic",
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
          fanout: fanout.get(b.ref) || {},
          live:
            liveValue?.source === archive && liveValue.ref === b.ref
              ? liveValue
              : undefined,
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
    fanout,
    liveValue,
    archive,
  ]);
  useEffect(() => {
    let active = true;
    setProperties([]);
    setLoading(sourceKind === "caf" && !!selected);
    setError("");
    if (selected && sourceKind === "caf")
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
  }, [archive, selected, sourceKind]);
  function select(ref: string, focus = false) {
    setSelected(ref);
    setWireChosen(false);
    persist(ref);
    if (focus) {
      const ticket = ++focusRequest.current;
      // The inspector changes canvas width. Center after that resize, while
      // retiring any focus request belonging to an older view/selection.
      requestAnimationFrame(() =>
        requestAnimationFrame(() => {
          if (ticket !== focusRequest.current) return;
          const item = flow.getNode(ref);
          if (!item) return;
          const size = logicSize(item.data.block, item.data.ports);
          const box =
            workspace.current?.querySelector<HTMLElement>(".caf-logic-canvas");
          const zoom = Math.min(
            1.2,
            ((box?.clientHeight || 660) - 48) / size.height,
            ((box?.clientWidth || 720) - 48) / size.width,
          );
          void flow.setCenter(
            item.position.x + size.width / 2,
            item.position.y + size.height / 2,
            { zoom, duration: 200 },
          );
        }),
      );
    }
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
    const active = wireChosen && !selected && w.index === selectedWire;
    return {
      id: `wire:${w.index}`,
      source: w.source_ref,
      target: w.target_ref,
      sourceHandle: `out:${w.source_port}`,
      targetHandle: `in:${w.target_port}`,
      type: "smoothstep",
      pathOptions: {
        borderRadius: 3,
        stepPosition: 0.35 + (w.index % 5) * 0.075,
      },
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
        ? `#${w.index} · ${ports.get(w.source_ref)?.outputs.find((p) => p.id === w.source_port)?.label || "Output"} → ${ports.get(w.target_ref)?.inputs.find((p) => p.id === w.target_port)?.label || "Input"}`
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
      if (editable && onPropose?.(p)) {
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
    <dialog
      ref={workspace}
      role={expanded ? "dialog" : "region"}
      aria-modal={expanded || undefined}
      onCancel={(event) => {
        event.preventDefault();
        setExpanded(false);
      }}
      tabIndex={-1}
      onKeyDown={(event) => {
        if (expanded) event.stopPropagation();
        if (event.key === "Escape" && expanded) {
          event.preventDefault();
          setExpanded(false);
        }
      }}
      className={`caf-logic-workspace engineering-workspace ${expanded ? "engineering-expanded" : ""}`}
      aria-label={`${prefix} graphical logic workspace`}
    >
      <div className="caf-logic-toolbar">
        <button
          ref={expandButton}
          aria-pressed={expanded}
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? "Close expanded logic view" : "Expand logic view"}
        </button>
        {expanded && moduleRefs.size > 1 && (
          <label>
            Activity
            <select
              aria-label="Logic activity"
              value={diagram.ref}
              onChange={(event) => onOpenModule(event.target.value)}
            >
              {[...moduleRefs].map((ref) => (
                <option key={ref} value={ref}>
                  {activityNames?.[ref] || ref.split(".").at(-1)}
                </option>
              ))}
            </select>
          </label>
        )}
        <label>
          Diagram layout
          <select
            aria-label={`${prefix} diagram layout`}
            value={layout}
            onChange={(e) => {
              positions.current = {};
              setLayout(e.target.value as View["layout"]);
              retained.delete(owner);
            }}
          >
            <option value="readable">Readable signal flow</option>
            <option value="recorded">
              Recorded {sourceKind === "caf" ? "CAF" : "controller"} coordinates
            </option>
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
            aria-label={`${prefix} signal trace`}
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
        {sourceLabel ||
          (sourceKind === "caf"
            ? "Local CAF"
            : "Controller file snapshot")}{" "}
        · drag blocks to arrange this view.
        {editable
          ? " Drag named ports to review a local connection proposal."
          : " Display positions do not change the program."}{" "}
        Double-click a module to open its logic.
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
      <div className="logic-legend">
        <span className="logic-input-key">Input pins</span>
        <span className="logic-output-key">Output pins</span>
        <span>Stored = archive configuration</span>
        <span>Live = separately read controller value</span>
      </div>
      <div
        className={`caf-logic-grid engineering-grid ${hasInspector ? "has-inspector" : ""}`}
      >
        <aside
          className="caf-logic-finder"
          aria-label={`${prefix} block finder`}
        >
          <label>
            Find a logic block
            <input
              type="search"
              aria-label={`Find ${prefix} logic block`}
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
        <div
          className="caf-logic-canvas"
          aria-label={`${prefix} native block diagram`}
        >
          {bounded ? (
            <ReactFlow
              nodes={nodes}
              edges={[...edges, ...draftEdges]}
              nodeTypes={nodeTypes}
              minZoom={0.02}
              maxZoom={2.5}
              fitView
              fitViewOptions={{ padding: 0.15, minZoom: 0.55, maxZoom: 1 }}
              nodesDraggable
              nodesConnectable={editable}
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
                  setWireChosen(true);
                  onSelectWire(Number(e.id.split(":")[1]));
                }
              }}
              onConnect={connect}
              onPaneClick={() => {
                setSelected("");
                setWireChosen(false);
              }}
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
        {hasInspector && (
          <ResponsivePanel
            name={`${prefix} logic inspector`}
            panel="inspector"
            side="right"
            triggerText="Logic inspector"
            triggerLabel={`Open ${prefix} logic inspector`}
            closeLabel={`Close ${prefix} logic inspector`}
            retireKey={owner}
            openSignal={selected || `wire:${selectedWire}`}
            context={
              sourceKind === "caf"
                ? "Local CAF configuration"
                : "Captured controller configuration"
            }
          >
            {node && inspector ? (
              inspector
            ) : node ? (
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
                {loading && (
                  <p role="status">Reading stored block properties…</p>
                )}
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
              <section aria-label={`${prefix} selected logic connection`}>
                <h4>Connection #{wire.index}</h4>
                <p>
                  {blockTitle(
                    diagram.blocks.find((b) => b.ref === wire.source_ref),
                  )}{" "}
                  ·{" "}
                  {
                    ports
                      .get(wire.source_ref)
                      ?.outputs.find((p) => p.id === wire.source_port)?.label
                  }
                </p>
                <p>
                  →{" "}
                  {blockTitle(
                    diagram.blocks.find((b) => b.ref === wire.target_ref),
                  )}{" "}
                  ·{" "}
                  {
                    ports
                      .get(wire.target_ref)
                      ?.inputs.find((p) => p.id === wire.target_port)?.label
                  }
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
        )}
      </div>
    </dialog>
  );
}
