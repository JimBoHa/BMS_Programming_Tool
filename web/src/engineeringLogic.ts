import {
  blockTitle,
  diagramPorts,
  readablePositions,
  type CafBlock,
  type CafDiagram,
  type CafPorts,
} from "./cafLogic";

export type LiveLogicValue = {
  source: string;
  ref: string;
  text: string;
  at: string;
  error?: string;
};

/** Functional symbols follow recorded class/Setup metadata, never controller model. */
export function functionView(b: CafBlock, ports: CafPorts) {
  const cid = String(b.class_id),
    name = b.class_name.toLowerCase();
  const input =
    ["526", "528", "530", "556"].includes(cid) || /^input .*block$/.test(name);
  const output =
    ["527", "529", "531", "555"].includes(cid) || /^output .*block$/.test(name);
  const constant = /constant/.test(name);
  if (
    (input || constant) &&
    ports.inputs.length === 0 &&
    ports.outputs.length <= 1
  )
    return {
      kind: constant ? "constant" : "input",
      symbol: constant ? "CONST" : "IN",
      title: blockTitle(b),
      terminal: true,
    };
  if (output && ports.outputs.length === 0 && ports.inputs.length <= 1)
    return {
      kind: "output",
      symbol: "OUT",
      title: blockTitle(b),
      terminal: true,
    };
  const symbol =
    b.operator?.text ||
    (
      {
        "252": "PID",
        "582": "PID PRE",
        "562": "MUX",
        "558": "TIMER",
        "559": "BOOL",
        "560": "CMP",
        "561": "CALC",
        "541": "FSM",
        "538": "LAST",
        "571": "SEQ",
        "536": "MODULE",
        "575": "PROGRAM",
      } as Record<string, string>
    )[cid] ||
    b.class_name.replace(/ Primitive$| Block$/g, "");
  return {
    kind: ["536", "575"].includes(cid) ? "module" : "function",
    symbol,
    title: blockTitle(b),
    terminal: false,
  };
}

export function logicSize(b: CafBlock, ports: CafPorts) {
  return functionView(b, ports).terminal
    ? { width: 210, height: 54 }
    : {
        width: 336,
        height:
          94 + Math.max(1, ports.inputs.length, ports.outputs.length) * 27,
      };
}

/** Order siblings by the named destination pins, reducing crossed input wires. */
export function engineeringPositions(d: CafDiagram, ports = diagramPorts(d)) {
  const result = readablePositions(d, ports, logicSize);
  const columns = new Map<number, CafBlock[]>();
  for (const b of d.blocks) {
    if (!result[b.ref]) return result;
    const column = result[b.ref].x;
    const rows = columns.get(column) || [];
    rows.push(b);
    columns.set(column, rows);
  }
  const outgoing = new Map<string, typeof d.connections>();
  for (const w of d.connections) {
    const rows = outgoing.get(w.source_ref) || [];
    rows.push(w);
    outgoing.set(w.source_ref, rows);
  }
  const pinY = (b: CafBlock, pid: number) => {
    const p = ports.get(b.ref)!;
    return functionView(b, p).terminal
      ? logicSize(b, p).height / 2
      : 99.5 +
          Math.max(
            0,
            p.inputs.findIndex((p) => p.id === pid),
          ) *
            27;
  };
  const blocks = new Map(d.blocks.map((b) => [b.ref, b]));
  for (const x of [...columns.keys()].sort((a, b) => b - a)) {
    const score = (b: CafBlock) => {
      const targets = (outgoing.get(b.ref) || [])
        .filter((w) => result[w.target_ref]?.x > x)
        .map(
          (w) =>
            result[w.target_ref].y +
            pinY(blocks.get(w.target_ref)!, w.target_port),
        );
      return targets.length
        ? targets.reduce((a, b) => a + b, 0) / targets.length
        : result[b.ref].y;
    };
    let y = 24;
    for (const b of columns
      .get(x)!
      .sort(
        (a, b) => score(a) - score(b) || a.execution_index - b.execution_index,
      )) {
      result[b.ref] = { x, y };
      y +=
        logicSize(b, ports.get(b.ref)!).height +
        (functionView(b, ports.get(b.ref)!).terminal ? 16 : 40);
    }
  }
  // Align signal terminals with their actual function pins. Their labels need
  // more vertical space than adjacent function pins, so keep that spacing while
  // avoiding a shared vertical bend between unrelated inputs.
  for (const x of [...columns.keys()].sort((a, b) => b - a)) {
    const rows = columns.get(x)!;
    if (!rows.every((b) => functionView(b, ports.get(b.ref)!).terminal))
      continue;
    let next = 24;
    for (const b of [...rows].sort(
      (a, b) => result[a.ref].y - result[b.ref].y,
    )) {
      const destinations = (outgoing.get(b.ref) || []).map(
        (w) =>
          result[w.target_ref].y +
          pinY(blocks.get(w.target_ref)!, w.target_port),
      );
      const sources = d.connections
        .filter((w) => w.target_ref === b.ref)
        .map((w) => {
          const source = blocks.get(w.source_ref)!,
            p = ports.get(source.ref)!;
          return (
            result[source.ref].y +
            (functionView(source, p).terminal
              ? logicSize(source, p).height / 2
              : 99.5 +
                Math.max(
                  0,
                  p.outputs.findIndex((p) => p.id === w.source_port),
                ) *
                  27)
          );
        });
      const points = destinations.length ? destinations : sources;
      const preferred = points.length
        ? Math.min(...points) - logicSize(b, ports.get(b.ref)!).height / 2
        : result[b.ref].y;
      result[b.ref].y = Math.max(next, preferred);
      next = result[b.ref].y + logicSize(b, ports.get(b.ref)!).height + 16;
    }
  }
  return result;
}

/** Adapt a read-only native graph to the same display as a CAF; grants no wiring support. */
export function controllerLogicDiagram(raw: Record<string, any>): CafDiagram {
  const rank = new Map<number, number>(
    raw.execution_order.map((index: number, order: number) => [index, order]),
  );
  const refs = new Map<string, number>(
    raw.blocks.map((b: any) => [b.ref, b.index]),
  );
  return {
    ref: raw.ref,
    name: raw.name,
    class_id: "native",
    class_version: "unreported",
    observed_version: false,
    execution_order: [...raw.execution_order],
    validation: "Read-only controller file snapshot",
    port_labels: raw.port_labels || {},
    blocks: raw.blocks.map((b: any) => ({
      index: b.index,
      ref: b.ref,
      name: b.name,
      class_id: String(b.class_id),
      class_name: b.class_name,
      class_version: "unreported",
      bacnet_type: -1,
      instance: Number(String(b.object || "").split(",")[1]) || 0,
      execution_index: rank.get(b.index) ?? b.index,
      layout: {
        x: String(b.layout?.x ?? 0),
        y: String(b.layout?.y ?? 0),
        opaque_code: 0,
      },
      // Native graph captures only establish directions for recorded wires.
      exposed_ports: [],
      pin_labels: b.pin_labels || {},
      stored_value: b.stored_value,
      operator: b.operator,
    })),
    connections: raw.connections.map((w: any) => ({
      ...w,
      raw: [
        refs.get(w.source_ref)!,
        w.source_port,
        refs.get(w.target_ref)!,
        w.target_port,
      ],
      continuation: { flag: false, text: "" },
    })),
  };
}
