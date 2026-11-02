export type CafBlock = {
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
export type CafWire = {
  index: number;
  raw: number[];
  source_ref: string;
  source_port: number;
  target_ref: string;
  target_port: number;
  continuation: { flag: boolean; text: string };
};
export type CafDiagram = {
  ref: string;
  class_id: string;
  class_version: string;
  observed_version: boolean;
  name: string;
  blocks: CafBlock[];
  connections: CafWire[];
  execution_order: number[];
  validation: string;
  port_labels?: Record<string, Record<string, string>>;
};
export type CafPort = { id: number; label: string; observed: boolean };
export type CafPorts = { inputs: CafPort[]; outputs: CafPort[] };
export type Position = { x: number; y: number };
export const CAF_CANVAS_BLOCKS = 1500,
  CAF_CANVAS_WIRES = 6000;
export const blockTitle = (b?: CafBlock) =>
  b ? b.name || `${b.class_name} · ${b.index + 1}` : "Unresolved block";
export function portName(diagram: CafDiagram, b: CafBlock, pid: number) {
  const name =
    diagram.port_labels?.[b.class_id]?.[String(pid)] ||
    b.exposed_ports.find((p) => p.id === pid)?.name;
  return name && name !== "Unmapped property" ? name : `Property ${pid}`;
}
const family = (b: CafBlock) => JSON.stringify([b.class_id, b.class_version]);
/** An unconnected exposed port gets direction only from a same-class/version wire prototype. */
export function diagramPorts(diagram: CafDiagram): Map<string, CafPorts> {
  const byRef = new Map(diagram.blocks.map((b) => [b.ref, b]));
  const actual = new Map<
    string,
    { inputs: Set<number>; outputs: Set<number> }
  >();
  const families = new Map<
    string,
    { inputs: Set<number>; outputs: Set<number> }
  >();
  for (const b of diagram.blocks) {
    actual.set(b.ref, { inputs: new Set(), outputs: new Set() });
    if (!families.has(family(b)))
      families.set(family(b), { inputs: new Set(), outputs: new Set() });
  }
  for (const w of diagram.connections) {
    const s = byRef.get(w.source_ref),
      t = byRef.get(w.target_ref);
    if (!s || !t) continue;
    actual.get(s.ref)!.outputs.add(w.source_port);
    actual.get(t.ref)!.inputs.add(w.target_port);
    families.get(family(s))!.outputs.add(w.source_port);
    families.get(family(t))!.inputs.add(w.target_port);
  }
  return new Map(
    diagram.blocks.map((b) => {
      const ports = actual.get(b.ref)!,
        prototypes = families.get(family(b))!;
      const list = (side: "inputs" | "outputs") =>
        [
          ...new Set([
            ...ports[side],
            ...b.exposed_ports
              .filter((p) => prototypes[side].has(p.id))
              .map((p) => p.id),
          ]),
        ]
          .sort((a, z) => a - z)
          .map((id) => ({
            id,
            label: portName(diagram, b, id),
            observed: ports[side].has(id),
          }));
      return [b.ref, { inputs: list("inputs"), outputs: list("outputs") }];
    }),
  );
}
export const nodeHeight = (ports: CafPorts) =>
  76 + Math.max(1, ports.inputs.length, ports.outputs.length) * 26;

/** Iterative SCC condensation keeps feedback loops visible without changing execution order. */
export function readablePositions(
  diagram: CafDiagram,
  ports = diagramPorts(diagram),
): Record<string, Position> {
  if (
    diagram.blocks.length > CAF_CANVAS_BLOCKS ||
    diagram.connections.length > CAF_CANVAS_WIRES
  )
    return {};
  const refs = diagram.blocks.map((b) => b.ref),
    adj = new Map(refs.map((r) => [r, [] as string[]])),
    reverse = new Map(refs.map((r) => [r, [] as string[]]));
  for (const w of diagram.connections)
    if (adj.has(w.source_ref) && adj.has(w.target_ref)) {
      adj.get(w.source_ref)!.push(w.target_ref);
      reverse.get(w.target_ref)!.push(w.source_ref);
    }
  const seen = new Set<string>(),
    finish: string[] = [];
  for (const start of refs) {
    if (seen.has(start)) continue;
    const stack: [string, boolean][] = [[start, false]];
    while (stack.length) {
      const [r, done] = stack.pop()!;
      if (done) {
        finish.push(r);
        continue;
      }
      if (seen.has(r)) continue;
      seen.add(r);
      stack.push([r, true]);
      for (const n of adj.get(r)!) if (!seen.has(n)) stack.push([n, false]);
    }
  }
  const component = new Map<string, number>();
  let count = 0;
  for (const start of finish.reverse()) {
    if (component.has(start)) continue;
    const stack = [start];
    component.set(start, count);
    while (stack.length)
      for (const n of reverse.get(stack.pop()!)!)
        if (!component.has(n)) {
          component.set(n, count);
          stack.push(n);
        }
    count++;
  }
  const links = Array.from({ length: count }, () => new Set<number>()),
    indegree = Array(count).fill(0),
    level = Array(count).fill(0);
  for (const w of diagram.connections) {
    const a = component.get(w.source_ref),
      b = component.get(w.target_ref);
    if (a === undefined || b === undefined || a === b || links[a].has(b))
      continue;
    links[a].add(b);
    indegree[b]++;
  }
  const queue = indegree.flatMap((n, i) => (n === 0 ? [i] : []));
  for (let i = 0; i < queue.length; i++)
    for (const n of links[queue[i]]) {
      level[n] = Math.max(level[n], level[queue[i]] + 1);
      if (--indegree[n] === 0) queue.push(n);
    }
  const rows = new Map<number, number>(),
    positions: Record<string, Position> = {};
  for (const b of [...diagram.blocks].sort(
    (a, z) => a.execution_index - z.execution_index || a.index - z.index,
  )) {
    const column = level[component.get(b.ref)!],
      y = rows.get(column) ?? 24;
    positions[b.ref] = { x: 24 + column * 364, y };
    rows.set(column, y + nodeHeight(ports.get(b.ref)!) + 40);
  }
  return positions;
}
export function traceRefs(
  diagram: CafDiagram,
  selected: string,
  direction: "upstream" | "downstream",
) {
  const result = new Set<string>(),
    adjacency = new Map<string, string[]>();
  for (const w of diagram.connections) {
    const a = direction === "upstream" ? w.target_ref : w.source_ref,
      b = direction === "upstream" ? w.source_ref : w.target_ref;
    const neighbors = adjacency.get(a);
    if (neighbors) neighbors.push(b);
    else adjacency.set(a, [b]);
  }
  const queue = selected ? [selected] : [];
  for (let i = 0; i < queue.length; i++)
    for (const n of adjacency.get(queue[i]) || [])
      if (n !== selected && !result.has(n)) {
        result.add(n);
        queue.push(n);
      }
  return result;
}
export type WiringProposal = {
  kind: "rewire" | "connect";
  prototype: number;
  source: string;
  target: string;
};
/** A gesture only selects a guarded local proposal. The server still validates opaque configuration. */
export function wiringProposal(
  d: CafDiagram,
  source: string,
  sourcePort: number,
  target: string,
  targetPort: number,
): WiringProposal {
  const s = d.blocks.find((b) => b.ref === source),
    t = d.blocks.find((b) => b.ref === target);
  if (!d.observed_version || !s || !t || s.execution_index >= t.execution_index)
    throw Error(
      "Choose existing blocks in native execution order; feedback authoring is outside this profile.",
    );
  const occupied = d.connections.filter(
    (w) => w.target_ref === target && w.target_port === targetPort,
  );
  if (occupied.length > 1)
    throw Error(
      "This input has multiple recorded drivers. Inspect its original connections first.",
    );
  if (occupied.length) {
    const w = occupied[0],
      old = d.blocks.find((b) => b.ref === w.source_ref)!;
    if (w.source_ref === source && w.source_port === sourcePort)
      throw Error("These ports are already connected.");
    if (
      sourcePort !== w.source_port ||
      family(s) !== family(old) ||
      !d.connections.some(
        (w) => w.source_ref === source && w.source_port === sourcePort,
      )
    )
      throw Error(
        "This source has no matching observed native interface for that connection.",
      );
    return { kind: "rewire", prototype: w.index, source, target };
  }
  const prototype = d.connections.find(
    (w) =>
      w.source_port === sourcePort &&
      w.target_port === targetPort &&
      family(d.blocks.find((b) => b.ref === w.source_ref)!) === family(s) &&
      family(d.blocks.find((b) => b.ref === w.target_ref)!) === family(t),
  );
  if (!prototype)
    throw Error(
      "No same-class native connection prototype supports these ports. No connection was created.",
    );
  return { kind: "connect", prototype: prototype.index, source, target };
}
