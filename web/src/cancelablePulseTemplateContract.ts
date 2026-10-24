import {
  cloneSource,
  projectSourceDocument,
  sourceEqual,
} from "./programSource";
import type { Program } from "./types";
export type Data = Record<string, any>;
export type PulseChoices = { duration_seconds: number; scan_seconds: number };
export type PulseImport = {
  choices: PulseChoices;
  profile_sha256: string;
  reviewed_parent_sha256: string;
};
export const PULSE_BASE = "/macros/templates/cancelable-pulse";
export const PULSE_PROFILE = "studio-cancelable-pulse-template/1";
export const PULSE_PROFILE_SHA =
  "0ba03fd044f5c7af17cfa21566953da69bb04aab61aa8c402e20b05a3af49b6d";
const object = (value: any): value is Data =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const hash = (value: any) =>
  typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
export async function blobSha256(blob: Blob) {
  return Array.from(
    new Uint8Array(
      await crypto.subtle.digest("SHA-256", await blob.arrayBuffer()),
    ),
    (b) => b.toString(16).padStart(2, "0"),
  ).join("");
}
function profileJSON(value: any): string {
  if (Array.isArray(value)) return "[" + value.map(profileJSON).join(",") + "]";
  if (object(value))
    return (
      "{" +
      Object.keys(value)
        .sort()
        .map((key) => JSON.stringify(key) + ":" + profileJSON(value[key]))
        .join(",") +
      "}"
    );
  if (typeof value === "number" && !Number.isSafeInteger(value))
    throw new Error("Unsupported pulse profile number.");
  return JSON.stringify(value);
}
export function readPulseChoices(duration: string, scan: string): PulseChoices {
  const d = Number(duration),
    h = Number(scan);
  if (
    !duration.trim() ||
    !scan.trim() ||
    !Number.isSafeInteger(d) ||
    d < 1 ||
    d > 86400 ||
    !Number.isSafeInteger(h) ||
    h < 1 ||
    h > 60 ||
    d < h ||
    d % h !== 0
  )
    throw new Error(
      "Pulse duration must be 1–86400 whole seconds and a whole multiple of scan 1–60 seconds, with at least one scan.",
    );
  return { duration_seconds: d, scan_seconds: h };
}
export async function pulseCatalog(value: any) {
  if (
    !object(value) ||
    value.format !== "bms.cancelable-pulse-template-catalog" ||
    value.version !== 1 ||
    value.profile?.profile !== PULSE_PROFILE ||
    value.profile_sha256 !== PULSE_PROFILE_SHA ||
    !sourceEqual(value.defaults, { duration_seconds: 5, scan_seconds: 1 }) ||
    !sourceEqual(value.exports, ["review", "bundle"]) ||
    value.native_compile !== false ||
    value.controller_writes !== false ||
    (await blobSha256(new Blob([profileJSON(value.profile)]))) !==
      PULSE_PROFILE_SHA
  )
    throw new Error(
      "Cancelable pulse catalog uses an unsupported source profile or timing contract.",
    );
  return value;
}
/** Project only the two declared business choices; never rewrite Program atoms. */
function choicesEqual(value: any, choices: PulseChoices) {
  return (
    object(value) &&
    Object.keys(value).length === 2 &&
    sourceEqual(projectSourceDocument(cloneSource(value)), choices)
  );
}
export function pulsePreview(
  value: any,
  choices: PulseChoices,
  parent: Program,
  catalog: Data,
) {
  const program = value?.program,
    bundle = value?.bundle,
    item = bundle?.library?.definitions?.[0],
    provenance = program?.metadata?.cancelable_pulse_template;
  const identifier = `studio-cancelable-pulse-d${choices.duration_seconds}-s${choices.scan_seconds}`;
  if (
    !object(value) ||
    value.format !== "bms.cancelable-pulse-template-preview" ||
    value.version !== 1 ||
    value.profile_sha256 !== catalog.profile_sha256 ||
    !sourceEqual(value.profile, catalog.profile) ||
    !choicesEqual(value.choices, choices) ||
    ![
      value.choices_sha256,
      value.program_sha256,
      value.definition_sha256,
      value.bundle_sha256,
      value.parent_reference?.program_sha256,
    ].every(hash) ||
    !object(value.parent_reference) ||
    value.parent_reference.id !== parent.id ||
    value.parent_reference.revision !== parent.revision ||
    value.parent_reference.scan_seconds !== parent.scan_seconds ||
    choices.scan_seconds !== parent.scan_seconds ||
    value.definition_id !== identifier ||
    !object(program) ||
    program.id !== identifier ||
    program.name !==
      `Cancelable pulse (${choices.duration_seconds}s / ${choices.scan_seconds}s scan)` ||
    program.revision !== 0 ||
    program.scan_seconds !== choices.scan_seconds ||
    !sourceEqual(program.target, {
      family: "universal-runtime",
      model: "",
      firmware: "",
      release_mode: "",
      max_nodes: 2000,
      physical_inputs: null,
      physical_outputs: null,
    }) ||
    program.metadata?.native_deployment_verified !== false ||
    provenance?.profile !== PULSE_PROFILE ||
    provenance.profile_sha256 !== value.profile_sha256 ||
    provenance.choices_sha256 !== value.choices_sha256 ||
    !choicesEqual(provenance.choices, choices) ||
    !sourceEqual(provenance.source, catalog.profile.source) ||
    !sourceEqual(provenance.unimplemented, catalog.profile.gaps) ||
    bundle?.format !== "bms-macro-library/1" ||
    bundle.root !== identifier ||
    bundle.library?.version !== 1 ||
    !Array.isArray(bundle.library.definitions) ||
    bundle.library.definitions.length !== 1 ||
    item.id !== identifier ||
    item.name !== program.name ||
    !sourceEqual(item.program, program) ||
    !Array.isArray(program.nodes) ||
    program.nodes.length !== 6 ||
    new Set(program.nodes.map((n: any) => n.id)).size !== 6 ||
    !Array.isArray(program.edges) ||
    program.edges.length !== 6 ||
    !sourceEqual(value.inputs, [
      {
        id: "request",
        label: "Request",
        value_type: "boolean",
        unit: "",
        required: true,
      },
    ]) ||
    !sourceEqual(value.output, {
      id: "result",
      label: "Pulse",
      value_type: "boolean",
      unit: "",
    }) ||
    !Array.isArray(value.diagnostics) ||
    !value.diagnostics.every(
      (d: any) =>
        object(d) &&
        ["warning", "error"].includes(d.level) &&
        typeof d.code === "string" &&
        typeof d.message === "string",
    ) ||
    value.can_import !==
      !value.diagnostics.some((d: any) => d.level === "error") ||
    value.native_compile !== false ||
    value.controller_writes !== false
  )
    throw new Error(
      "Pulse preview does not match the exact parent clock, choices, source or interface.",
    );
  const specs = [
    ["request", "Input", "Request", { default: false }],
    [
      "elapsed",
      "TimerOn",
      "Continuous request elapsed",
      { seconds: choices.duration_seconds },
    ],
    [
      "expired_previous",
      "Delay",
      "Previous committed expiry",
      { initial: false },
    ],
    ["not_expired", "Not", "Previous scan not expired", {}],
    ["pulse", "And", "Cancelable pulse", {}],
    ["result", "Output", "Pulse", {}],
  ] as const;
  for (const [id, kind, label, params] of specs) {
    const node = program.nodes.find((n: any) => n.id === id);
    if (
      !node ||
      node.kind !== kind ||
      node.label !== label ||
      node.unit !== "" ||
      node.value_type !== "boolean" ||
      !sourceEqual(projectSourceDocument(cloneSource(node.params)), params)
    )
      throw new Error(
        "Pulse ordinary nodes, defaults or declared duration changed.",
      );
  }
  const wires = [
    ["request_elapsed", "request", "elapsed", "in"],
    ["elapsed_memory", "elapsed", "expired_previous", "in"],
    ["memory_inversion", "expired_previous", "not_expired", "in"],
    ["request_pulse", "request", "pulse", "a"],
    ["expiry_pulse", "not_expired", "pulse", "b"],
    ["publish", "pulse", "result", "in"],
  ].map(([id, source, target, target_port]) => ({
    id,
    source,
    target,
    target_port,
    source_port: "out",
  }));
  if (!sourceEqual(program.edges, wires))
    throw new Error("Cancelable pulse fixed six-wire topology changed.");
  return value;
}
export function pulseDescriptors(envelope: any, report: Data) {
  const paths = [
    ["program"],
    ["bundle", "library", "definitions", 0, "program"],
  ];
  if (
    !Array.isArray(envelope.programs) ||
    envelope.programs.length !== 2 ||
    envelope.programs.some(
      (row: any, i: number) =>
        !sourceEqual(row.path, paths[i]) ||
        row.program_id !== report.definition_id ||
        row.revision_text !== "0" ||
        row.canonical_format !== "canonical-json/1" ||
        row.canonical_sha256 !== report.program_sha256,
    )
  )
    throw new Error(
      "Pulse original Program descriptor differs from the reviewed definition.",
    );
}
