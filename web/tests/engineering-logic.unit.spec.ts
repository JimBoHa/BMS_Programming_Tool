import { test, expect } from "@playwright/test";
import {
  functionView,
  logicSize,
  controllerLogicDiagram,
  engineeringPositions,
} from "../src/engineeringLogic";
import {
  diagramPorts,
  readablePositions,
  portName,
  type CafBlock,
} from "../src/cafLogic";

const block = (cid: string, name: string): CafBlock => ({
  index: 0,
  ref: "test/1",
  bacnet_type: 2,
  instance: 1,
  class_id: cid,
  class_version: "1.0",
  class_name: name,
  name,
  execution_index: 0,
  layout: { x: "50000", y: "0", opaque_code: 0 },
  exposed_ports: [],
});

test("readable input terminals follow destination pin order without changing execution order", () => {
  const d = controllerLogicDiagram({
    ref: "fixture/root",
    name: "PID",
    execution_order: [0, 1, 2],
    blocks: [
      {
        index: 0,
        ref: "temperature",
        class_id: 526,
        class_name: "Input Float Block",
        name: "Temperature",
      },
      {
        index: 1,
        ref: "setpoint",
        class_id: 526,
        class_name: "Input Float Block",
        name: "Setpoint",
      },
      { index: 2, ref: "pid", class_id: 252, class_name: "PID", name: "PID" },
    ],
    connections: [
      {
        index: 0,
        source_ref: "temperature",
        source_port: 663,
        target_ref: "pid",
        target_port: 695,
      },
      {
        index: 1,
        source_ref: "setpoint",
        source_port: 663,
        target_ref: "pid",
        target_port: 108,
      },
    ],
  });
  const original = JSON.stringify(d),
    ports = diagramPorts(d),
    positions = engineeringPositions(d, ports);
  expect(positions.setpoint.y).toBeLessThan(positions.temperature.y);
  expect(
    positions.setpoint.y +
      logicSize(d.blocks[1], ports.get("setpoint")!).height +
      16,
  ).toBeLessThanOrEqual(positions.temperature.y);
  expect(positions.setpoint.y + 27).toBe(positions.pid.y + 99.5);
  expect(positions.pid.x).toBeGreaterThan(positions.setpoint.x + 210);
  expect(JSON.stringify(d)).toBe(original);
});
const p = { id: 85, label: "Present Value", observed: true };
test("functions use recorded class and Setup labels while unknown operators remain generic", () => {
  expect(
    functionView(block("252", "PID"), { inputs: [p], outputs: [p] }).symbol,
  ).toBe("PID");
  expect(
    functionView(block("559", "Boolean Primitive"), {
      inputs: [p],
      outputs: [p],
    }).symbol,
  ).toBe("BOOL");
  expect(
    functionView(
      {
        ...block("561", "Math Primitive"),
        operator: { text: "+", source: "Setup reference" },
      },
      { inputs: [p], outputs: [p] },
    ).symbol,
  ).toBe("+");
  expect(
    functionView(block("65000", "Unknown native class"), {
      inputs: [p],
      outputs: [p],
    }).symbol,
  ).toBe("Unknown native class");
  expect(
    functionView(block("526", "Input Float Block"), {
      inputs: [],
      outputs: [p],
    }).kind,
  ).toBe("input");
  expect(
    functionView(block("527", "Output Float Block"), {
      inputs: [p],
      outputs: [],
    }).kind,
  ).toBe("output");
});
test("native display preserves source order, wiring and unknown versions without enabling CAF edits", () => {
  const raw = {
    ref: "fixture/root",
    name: "PID",
    execution_order: [1, 0],
    native_layout: true,
    port_labels: { "252": { "695": "Process Variable" } },
    blocks: [
      {
        index: 0,
        ref: "fixture/root.2_1",
        class_id: 252,
        class_name: "PID",
        name: "Cooling loop",
        object: "252,1",
        layout: { x: 99999, y: 99999 },
        pin_labels: { "695": "Zone temperature" },
      },
      {
        index: 1,
        ref: "fixture/root.2_2",
        class_id: 526,
        class_name: "Input Float Block",
        name: "Zone temperature",
        object: "analog-value,2",
        layout: { x: 99999, y: 99999 },
      },
    ],
    connections: [
      {
        index: 0,
        source_ref: "fixture/root.2_2",
        source_port: 663,
        target_ref: "fixture/root.2_1",
        target_port: 695,
      },
    ],
  };
  const original = JSON.stringify(raw),
    d = controllerLogicDiagram(raw),
    ports = diagramPorts(d);
  expect(d.observed_version).toBe(false);
  expect(d.blocks.map((b) => b.execution_index)).toEqual([1, 0]);
  expect(d.blocks[0].class_version).toBe("unreported");
  expect(d.connections[0].raw).toEqual([1, 663, 0, 695]);
  expect(portName(d, d.blocks[0], 695)).toBe("Zone temperature");
  const positions = readablePositions(d, ports, logicSize);
  expect(positions[d.blocks[0].ref].x).toBeGreaterThan(
    positions[d.blocks[1].ref].x +
      logicSize(d.blocks[1], ports.get(d.blocks[1].ref)!).width,
  );
  expect(JSON.stringify(raw)).toBe(original);
});
