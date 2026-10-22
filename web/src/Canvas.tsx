import {
  CanvasMeasurements,
  type MeasurementOwner,
} from "./canvasMeasurements";
import {
  memo,
  useId,
  useLayoutEffect,
  useReducer,
  useRef,
  useCallback,
  type DragEvent,
} from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  useReactFlow,
  useUpdateNodeInternals,
  type Node,
  type NodeProps,
  type NodeChange,
  type Connection,
} from "@xyflow/react";
import { CircuitBoard } from "lucide-react";
import type { Block, BmsNode, Program, Scan } from "./types";
import { showValue } from "./types";
type ControlNode = Node<
  {
    block: BmsNode;
    spec: Block;
    value: unknown;
    invalid: boolean;
    forced: boolean;
    owner: MeasurementOwner;
    measure: (owner: MeasurementOwner, element: HTMLElement) => void;
  },
  "control"
>;
const ControlBlock = memo(function ControlBlock({
  data,
  selected,
}: NodeProps<ControlNode>) {
  const { block, spec, value, invalid, forced, owner, measure } = data;
  const element = useRef<HTMLDivElement>(null);
  const updateInternals = useUpdateNodeInternals();
  useLayoutEffect(() => {
    const wrapper = element.current?.closest<HTMLElement>(".react-flow__node");
    if (wrapper) measure(owner, wrapper);
  });
  // Replaced nodes/ports need current handle geometry even when their box size is unchanged.
  useLayoutEffect(() => {
    updateInternals(block.id);
  }, [owner, block.id, updateInternals]);
  return (
    <div
      ref={element}
      className={`control-node category-${spec.category.toLowerCase().replace("/", "")} ${selected ? "selected" : ""} ${invalid ? "invalid" : ""} ${forced ? "forced" : ""}`}
      style={{ minHeight: Math.max(108, spec.inputs.length * 29 + 55) }}
    >
      <div className="node-header">
        <span className="node-indicator" />
        <span>{spec.title}</span>
        {forced && <b className="force-badge">FORCED</b>}
        <small>{block.unit}</small>
      </div>
      <strong className="node-label">{block.label || block.id}</strong>
      <div className="node-ports">
        {spec.inputs.map((port, i) => (
          <div className="input-port" style={{ top: 73 + i * 29 }} key={port}>
            <Handle type="target" position={Position.Left} id={port} />
            <span>{port}</span>
          </div>
        ))}
      </div>
      <div className="output-port" style={{ top: 73 }}>
        <span>{showValue(value)}</span>
        <Handle type="source" position={Position.Right} id="out" />
      </div>
      {block.kind === "Constant" && (
        <small className="constant-value">
          {showValue(block.params.value)}
        </small>
      )}
    </div>
  );
});
const nodeTypes = { control: ControlBlock };
export function Canvas({
  program,
  blocks,
  last,
  issues,
  selected,
  onSelect,
  onChange,
  onBeginDrag,
  onConnect,
  onAdd,
  onRemoveWire,
}: {
  program: Program;
  blocks: Block[];
  last?: Scan;
  issues: any[];
  selected: string[];
  onSelect: (id: string | null) => void;
  onChange: (changes: NodeChange[]) => void;
  onBeginDrag: () => void;
  onConnect: (c: Connection) => void;
  onAdd: (kind: string, x: number, y: number) => void;
  onRemoveWire: (id: string) => void;
}) {
  const flow = useReactFlow();
  const canvasId = useId();
  const cache = useRef<CanvasMeasurements | null>(null);
  if (!cache.current) cache.current = new CanvasMeasurements(canvasId);
  const [, changedGeometry] = useReducer((value: number) => value + 1, 0);
  const measure = useCallback(
    (owner: MeasurementOwner, element: HTMLElement) => {
      if (cache.current!.measure(owner, element)) changedGeometry();
    },
    [],
  );
  const described = program.nodes.map((n) => {
    const spec = blocks.find(
      (b) =>
        b.kind === n.kind &&
        (b.kind !== "Macro" || b.parameters.definition === n.params.definition),
    ) || {
      kind: n.kind,
      title: n.kind,
      category: "unknown",
      inputs: [],
      output: "number",
      parameters: {},
      help: "Unknown block",
      stateful: false,
    };
    return {
      n,
      spec,
      shape: JSON.stringify([
        n.kind,
        n.value_type,
        spec.inputs,
        spec.output,
        spec.category,
      ]),
    };
  });
  const owners = cache.current.prepare(
    program.id,
    described.map(({ n, shape }) => ({ id: n.id, shape })),
  );
  const nodes: ControlNode[] = described.map(({ n, spec }) => {
    const owner = owners.get(n.id)!;
    return {
      id: n.id,
      type: "control",
      position: { x: n.x, y: n.y },
      selected: selected.includes(n.id),
      measured: cache.current!.get(owner),
      data: {
        block: n,
        spec,
        value: last?.values[n.id],
        invalid: issues.some((d) => d.node === n.id && d.level === "error"),
        forced: !!last?.forces && Object.hasOwn(last.forces, n.id),
        owner,
        measure,
      },
    };
  });
  const edges = program.edges.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    sourceHandle: e.source_port,
    targetHandle: e.target_port,
    animated: !!last,
    style: { stroke: "#679294", strokeWidth: 1.7 },
  }));
  function drop(event: DragEvent) {
    event.preventDefault();
    const kind = event.dataTransfer.getData("application/bms-kind");
    if (kind) {
      const p = flow.screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      });
      onAdd(kind, p.x, p.y);
    }
  }
  return (
    <div
      className="canvas"
      data-canvas-owner={canvasId}
      onDrop={drop}
      onDragOver={(e) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = "copy";
      }}
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onChange}
        onPaneClick={() => onSelect(null)}
        onNodeDragStart={onBeginDrag}
        onEdgeDoubleClick={(_, e) => onRemoveWire(e.id)}
        onConnect={onConnect}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.2}
        maxZoom={2}
        deleteKeyCode={null}
        multiSelectionKeyCode={["Meta", "Control", "Shift"]}
        proOptions={{ hideAttribution: false }}
      >
        <Background gap={20} size={1} color="#cad4d9" />
        <Controls showInteractive={false} />
        <MiniMap nodeColor="#80b5af" maskColor="#eef3f4a0" pannable zoomable />
      </ReactFlow>
      {!program.nodes.length && (
        <div className="canvas-empty">
          <CircuitBoard size={44} />
          <h2>Build a control sequence</h2>
          <p>Drag blocks here, then connect output pins to input pins.</p>
          <p>Or choose a VAV example from the template menu.</p>
        </div>
      )}
      <div className="canvas-label">
        CONTROL WIRESHEET{" "}
        <span>
          {program.target.family === "universal-runtime"
            ? "BMS runtime"
            : program.target.model || program.target.family}
        </span>
      </div>
    </div>
  );
}
