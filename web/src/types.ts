import { markProgram } from "./programSource";
export type Block = {
  kind: string;
  title: string;
  category: string;
  inputs: string[];
  output: string;
  parameters: Record<string, any>;
  help: string;
  stateful: boolean;
  unit?: string;
};
export type BmsNode = {
  id: string;
  kind: string;
  label: string;
  x: number;
  y: number;
  params: Record<string, any>;
  unit: string;
  value_type: "number" | "boolean";
};
export type BmsEdge = {
  id: string;
  source: string;
  target: string;
  source_port: string;
  target_port: string;
};
export type Program = {
  schema_version: 1;
  id: string;
  name: string;
  description: string;
  revision: number;
  scan_seconds: number;
  target: {
    family: string;
    model: string;
    firmware: string;
    release_mode: string;
    max_nodes: number;
    physical_inputs: number | null;
    physical_outputs: number | null;
  };
  nodes: BmsNode[];
  edges: BmsEdge[];
  metadata: Record<string, any>;
};
export type Scan = {
  time: number;
  clock: string;
  values: Record<string, number | boolean>;
  outputs: Record<string, number | boolean>;
  alarms: { node: string; message: string }[];
  forces?: Record<string, number | boolean>;
  computed?: Record<string, number | boolean>;
};
export const blankProgram = (): Program =>
  markProgram({
    schema_version: 1,
    id: "project-" + Date.now().toString(36),
    name: "New control program",
    description: "",
    revision: 0,
    scan_seconds: 1,
    target: {
      family: "universal-runtime",
      model: "",
      firmware: "",
      release_mode: "",
      max_nodes: 2000,
      physical_inputs: null,
      physical_outputs: null,
    },
    nodes: [],
    edges: [],
    metadata: {},
  });
export const showValue = (value: unknown) =>
  typeof value === "number"
    ? Object.is(value, -0)
      ? "-0.0"
      : Number.isInteger(value) && !Number.isSafeInteger(value)
        ? BigInt(value).toString()
        : Number(value.toFixed(3)).toString()
    : typeof value === "boolean"
      ? value
        ? "TRUE"
        : "FALSE"
      : value == null
        ? "—"
        : String(value);
