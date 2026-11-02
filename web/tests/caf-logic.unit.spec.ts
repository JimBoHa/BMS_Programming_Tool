import { test, expect } from "@playwright/test";
import {
  diagramPorts,
  readablePositions,
  traceRefs,
  wiringProposal,
  nodeHeight,
  CAF_CANVAS_BLOCKS,
  type CafDiagram,
} from "../src/cafLogic";
function diagram(): CafDiagram {
  return {
    ref: "controller",
    class_id: "575",
    class_version: "1.0",
    observed_version: true,
    name: "Authored graph",
    validation: "authored",
    execution_order: [0, 1, 2, 3],
    blocks: Array.from({ length: 4 }, (_, i) => ({
      index: i,
      ref: `block-${i}`,
      bacnet_type: 2,
      instance: i,
      class_id: i < 2 ? "526" : "527",
      class_version: "1.0",
      class_name: "Authored block",
      name: `Block ${i}`,
      execution_index: i,
      layout: { x: "0", y: "0", opaque_code: 19 },
      exposed_ports: [
        { id: 663, name: "O1" },
        { id: 513, name: "I1" },
        { id: 9999, name: "Undirected" },
      ],
    })),
    connections: [
      {
        index: 0,
        raw: [0, 663, 2, 513],
        source_ref: "block-0",
        source_port: 663,
        target_ref: "block-2",
        target_port: 513,
        continuation: { flag: false, text: "" },
      },
      {
        index: 1,
        raw: [1, 663, 3, 513],
        source_ref: "block-1",
        source_port: 663,
        target_ref: "block-3",
        target_port: 513,
        continuation: { flag: true, text: "Recorded label" },
      },
    ],
  };
}
test("port directions come from recorded wires and exact class/version prototypes", () => {
  const d = diagram(),
    ports = diagramPorts(d);
  expect(ports.get("block-0")!.outputs.map((p) => p.id)).toEqual([663]);
  expect(ports.get("block-0")!.inputs).toEqual([]);
  expect(ports.get("block-2")!.inputs.map((p) => p.id)).toEqual([513]);
  d.connections.pop();
  expect(diagramPorts(d).get("block-1")!.outputs[0].observed).toBe(false);
  d.blocks[1].class_version = "2.0";
  expect(diagramPorts(d).get("block-1")!.outputs).toEqual([]);
});
test("readable layout separates overlapping native coordinates and keeps original execution/order bytes", () => {
  const d = diagram(),
    original = JSON.stringify(d),
    ports = diagramPorts(d),
    p = readablePositions(d);
  expect(p["block-2"].x).toBeGreaterThan(p["block-0"].x);
  expect(p["block-1"].y - p["block-0"].y).toBeGreaterThan(
    nodeHeight(ports.get("block-0")!),
  );
  expect(new Set(Object.values(p).map((p) => JSON.stringify(p))).size).toBe(4);
  expect(JSON.stringify(d)).toBe(original);
});
test("feedback tracing terminates and retains all reachable native relationships", () => {
  const d = diagram();
  d.connections.push({
    index: 2,
    raw: [2, 663, 0, 513],
    source_ref: "block-2",
    source_port: 663,
    target_ref: "block-0",
    target_port: 513,
    continuation: { flag: false, text: "" },
  });
  expect([...traceRefs(d, "block-0", "downstream")]).toEqual(["block-2"]);
  expect([...traceRefs(d, "block-0", "upstream")]).toEqual(["block-2"]);
  expect(Object.keys(readablePositions(d))).toHaveLength(4);
});
test("dragging to an occupied input stages one existing source substitution", () => {
  expect(wiringProposal(diagram(), "block-1", 663, "block-2", 513)).toEqual({
    kind: "rewire",
    prototype: 0,
    source: "block-1",
    target: "block-2",
  });
});
test("an unconnected destination uses an observed native interface prototype", () => {
  const d = diagram();
  d.connections.pop();
  expect(wiringProposal(d, "block-1", 663, "block-3", 513)).toEqual({
    kind: "connect",
    prototype: 0,
    source: "block-1",
    target: "block-3",
  });
  expect(() => wiringProposal(d, "block-1", 664, "block-3", 513)).toThrow(
    /prototype/,
  );
  expect(() => wiringProposal(d, "block-3", 663, "block-1", 513)).toThrow(
    /execution order/,
  );
});
test("ambiguous drivers and unsupported root versions never stage a connection", () => {
  const d = diagram();
  d.connections[1].target_ref = "block-2";
  expect(() => wiringProposal(d, "block-1", 663, "block-2", 513)).toThrow(
    /multiple/,
  );
  d.observed_version = false;
  expect(() => wiringProposal(d, "block-1", 663, "block-3", 513)).toThrow(
    /outside this profile/,
  );
});
test("oversized graphs retain their records while declining interactive layout", () => {
  const d = diagram();
  d.blocks = Array(CAF_CANVAS_BLOCKS + 1).fill(d.blocks[0]);
  expect(readablePositions(d)).toEqual({});
  expect(d.blocks).toHaveLength(CAF_CANVAS_BLOCKS + 1);
});
