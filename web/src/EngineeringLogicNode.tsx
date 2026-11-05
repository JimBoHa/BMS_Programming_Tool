import { memo } from "react";
import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { blockTitle, type CafBlock, type CafPorts } from "./cafLogic";
import {
  functionView,
  logicSize,
  type LiveLogicValue,
} from "./engineeringLogic";

export type EngineeringNode = Node<
  {
    block: CafBlock;
    ports: CafPorts;
    module: boolean;
    trace: string;
    live?: LiveLogicValue;
    fanout: Record<number, number>;
  },
  "engineeringLogic"
>;

export const EngineeringLogicNode = memo(function EngineeringLogicNode({
  data,
  selected,
  isConnectable,
}: NodeProps<EngineeringNode>) {
  const { block, ports } = data,
    view = functionView(block, ports),
    size = logicSize(block, ports);
  const value = data.live
    ? `${data.live.error ? "Last read" : "Live"} ${data.live.text}`
    : block.stored_value
      ? `Stored ${block.stored_value.text}`
      : "";
  const pin = (
    side: "inputs" | "outputs",
    p: CafPorts["inputs"][number],
    index: number,
  ) => (
    <div
      key={`${side}:${p.id}`}
      className={`caf-logic-port ${side} ${p.observed ? "" : "prototype-port"}`}
      style={{ top: view.terminal ? "50%" : 88 + index * 27 }}
      title={`${p.label} · native property ${p.id} · ${p.observed ? "recorded connection" : "exposed port; direction observed on same class/version"}`}
    >
      <Handle
        isConnectable={isConnectable}
        type={side === "inputs" ? "target" : "source"}
        position={side === "inputs" ? Position.Left : Position.Right}
        id={`${side === "inputs" ? "in" : "out"}:${p.id}`}
        aria-label={`${side === "inputs" ? "Input" : "Output"} ${p.id} on ${blockTitle(block)}`}
      />
      {!view.terminal && <span className="logic-pin-tag">{p.label}</span>}
      {side === "outputs" && data.fanout[p.id] > 1 && (
        <i
          className="logic-junction"
          title={`${data.fanout[p.id]} recorded destinations`}
        />
      )}
    </div>
  );
  return (
    <div
      className={`caf-logic-node engineering-node ${view.kind} ${view.terminal ? "terminal" : ""} ${selected ? "is-selected" : ""} ${data.trace}`}
      style={{ width: size.width, height: size.height }}
      data-function={view.symbol}
    >
      <div className="caf-logic-node-heading">
        <b
          className="logic-function"
          title={block.operator?.source || block.class_name}
        >
          {view.symbol}
        </b>
        <small title="Original execution order">
          {block.execution_index + 1}
          {data.module ? " ↳" : ""}
        </small>
      </div>
      <strong className="caf-logic-node-name" title={view.title}>
        {view.title}
      </strong>
      <div
        className={`logic-value ${data.live ? (data.live.error ? "last-read" : "live") : "stored"}`}
        title={
          data.live
            ? `Read ${data.live.at}${data.live.error ? ` · ${data.live.error}` : ""}`
            : block.stored_value
              ? `Stored ${block.stored_value.datatype}; not a live measurement`
              : "No value read"
        }
      >
        {value ||
          (data.module ? "Double-click to open logic" : block.class_name)}
      </div>
      {ports.inputs.map((p, i) => pin("inputs", p, i))}
      {ports.outputs.map((p, i) => pin("outputs", p, i))}
    </div>
  );
});
