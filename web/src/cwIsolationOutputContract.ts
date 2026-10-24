import {
  cloneSource,
  isSourceNumber,
  numericToken,
  projectSourceDocument,
  sourceEqual,
  sourceNumber,
  type SourceNumber,
} from "./programSource";
import {
  hash,
  libraryVersion,
  manifestSha256,
  object,
} from "./activityContracts";
import type { Program } from "./types";

export type Data = Record<string, any>;
export type CWChoices = {
  minimum_command: SourceNumber;
  stroke_seconds: number;
  scan_seconds: number;
};
export type CWImport = {
  choices: CWChoices;
  profile_sha256: string;
  reviewed_parent_sha256: string;
};
export const CW_BASE = "/activities/templates/cw-iso-output";
export const CW_PROFILE = "studio-cw-iso-output-template/1";
// Versioned authored source contract; refresh only after the backend freezes.
export const CW_PROFILE_SHA =
  "9381bea24e1dd82696e8473ddb4c02eafe3006a09e332ef3cc42b18d0836ca07";

/** A new typed-float form value; this never rewrites an existing Program atom. */
export function readCWChoices(
  minimum: string,
  stroke: string,
  scan: string,
): CWChoices {
  const text = minimum.trim(),
    token = sourceNumber(text),
    m = Number(token.token),
    t = Number(stroke),
    h = Number(scan);
  if (
    !text ||
    !Number.isFinite(m) ||
    m < 0 ||
    m > 100 ||
    !stroke.trim() ||
    !scan.trim() ||
    !Number.isSafeInteger(t) ||
    t < 1 ||
    t > 86400 ||
    !Number.isSafeInteger(h) ||
    h < 1 ||
    h > 60 ||
    t < h ||
    t % h !== 0
  )
    throw new Error(
      "Minimum must be a finite JSON number from 0 to 100%. Stroke must be 1–86400 whole seconds and a whole multiple of scan 1–60 seconds, with at least one scan.",
    );
  return {
    // Declare this authored field as a float, including integer-form -0.
    minimum_command: /[.eE]/.test(text) ? token : sourceNumber(text + ".0"),
    stroke_seconds: t,
    scan_seconds: h,
  };
}

function choicesEqual(value: any, choices: CWChoices) {
  if (!object(value) || Object.keys(value).length !== 3) return false;
  const declared = projectSourceDocument(cloneSource(value));
  return (
    Object.is(
      declared.minimum_command,
      Number(choices.minimum_command.token),
    ) &&
    declared.stroke_seconds === choices.stroke_seconds &&
    declared.scan_seconds === choices.scan_seconds
  );
}

export async function cwCatalog(value: any) {
  if (
    !object(value) ||
    value.format !== "bms.cw-iso-output-template-catalog" ||
    value.version !== 1 ||
    value.profile?.profile !== CW_PROFILE ||
    value.profile_sha256 !== CW_PROFILE_SHA ||
    (await manifestSha256(value.profile)) !== CW_PROFILE_SHA ||
    !sourceEqual(value.defaults, {
      minimum_command: 0,
      stroke_seconds: 60,
      scan_seconds: 1,
    }) ||
    !sourceEqual(value.exports, ["review", "bundle"]) ||
    value.native_compile !== false ||
    value.controller_writes !== false
  )
    throw new Error(
      "CW isolation template uses an unsupported source profile or fixed-scan contract.",
    );
  return value;
}

export function cwPreview(
  value: any,
  choices: CWChoices,
  parent: Program,
  catalog: Data,
) {
  const program = value?.program,
    bundle = value?.bundle,
    item = bundle?.library?.definitions?.[0],
    provenance = program?.metadata?.cw_isolation_output_template,
    identifier = value?.definition_id;
  if (
    !object(value) ||
    value.format !== "bms.cw-iso-output-template-preview" ||
    value.version !== 1 ||
    value.profile_sha256 !== catalog.profile_sha256 ||
    !sourceEqual(value.profile, catalog.profile) ||
    !choicesEqual(value.choices, choices) ||
    ![
      value.choices_sha256,
      value.definition_sha256,
      value.program_sha256,
      value.bundle_sha256,
      value.parent_reference?.program_sha256,
    ].every(hash) ||
    !object(value.parent_reference) ||
    value.parent_reference.id !== parent.id ||
    value.parent_reference.revision !== parent.revision ||
    value.parent_reference.scan_seconds !== parent.scan_seconds ||
    parent.scan_seconds !== choices.scan_seconds ||
    libraryVersion(parent) !== 2 ||
    typeof identifier !== "string" ||
    !/^cw_iso_[a-f0-9]{24}$/.test(identifier) ||
    !object(program) ||
    program.id !== identifier ||
    program.name !== "Authored CW isolation/pump output" ||
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
    provenance?.profile !== CW_PROFILE ||
    provenance.profile_sha256 !== value.profile_sha256 ||
    provenance.choices_sha256 !== value.choices_sha256 ||
    !choicesEqual(provenance.choices, choices) ||
    !isSourceNumber(provenance.choices.minimum_command) ||
    !/[.eE]/.test(numericToken(provenance.choices.minimum_command)) ||
    !sourceEqual(provenance.source, catalog.profile.source) ||
    !sourceEqual(provenance.unimplemented, catalog.profile.gaps) ||
    bundle?.format !== "bms-macro-library/2" ||
    bundle.root !== identifier ||
    bundle.library?.version !== 2 ||
    !Array.isArray(bundle.library.definitions) ||
    bundle.library.definitions.length !== 1 ||
    item.id !== identifier ||
    item.name !== program.name ||
    !sourceEqual(item.program, program) ||
    !Array.isArray(program.nodes) ||
    program.nodes.length !== 13 ||
    new Set(program.nodes.map((n: Data) => n.id)).size !== 13 ||
    !Array.isArray(program.edges) ||
    program.edges.length !== 14 ||
    !sourceEqual(value.inputs, [
      {
        id: "device_enable",
        label: "Logical device enable",
        value_type: "boolean",
        unit: "",
        required: true,
      },
      {
        id: "command",
        label: "Requested percent command",
        value_type: "number",
        unit: "%",
        required: true,
      },
    ]) ||
    !sourceEqual(value.outputs, [
      {
        id: "device_on_off",
        label: "Logical device on/off",
        value_type: "boolean",
        unit: "",
      },
      {
        id: "effective_command",
        label: "Effective percent command",
        value_type: "number",
        unit: "%",
      },
    ]) ||
    !Array.isArray(value.diagnostics) ||
    !value.diagnostics.every(
      (d: Data) =>
        object(d) &&
        ["warning", "error"].includes(d.level) &&
        typeof d.code === "string" &&
        typeof d.message === "string",
    ) ||
    value.can_import !==
      !value.diagnostics.some((d: Data) => d.level === "error") ||
    value.native_compile !== false ||
    value.controller_writes !== false
  )
    throw new Error(
      "CW isolation preview differs from the current parent, choices, profile or two-output interface.",
    );
  const step = (100 * choices.scan_seconds) / choices.stroke_seconds;
  const specs = [
    [
      "device_enable",
      "Input",
      "Logical device enable",
      "boolean",
      "",
      { default: false },
    ],
    [
      "command",
      "Input",
      "Requested percent command",
      "number",
      "%",
      { default: 0 },
    ],
    [
      "minimum",
      "Constant",
      "Enabled target floor",
      "number",
      "%",
      { value: Number(choices.minimum_command.token) },
    ],
    ["zero", "Constant", "Disabled command", "number", "%", { value: 0 }],
    [
      "bounded_command",
      "Clamp",
      "Clamp finite command",
      "number",
      "%",
      { min: 0, max: 100 },
    ],
    ["target", "Max", "Minimum as target floor", "number", "%", {}],
    [
      "previous",
      "Delay",
      "Previous committed selected command",
      "number",
      "%",
      { initial: 0 },
    ],
    ["difference", "Subtract", "Target minus previous", "number", "%", {}],
    [
      "limited_difference",
      "Clamp",
      "Fixed declared-scan increment",
      "number",
      "%",
      { min: -step, max: step },
    ],
    ["candidate", "Add", "Enabled ramp candidate", "number", "%", {}],
    ["selected", "Switch", "Immediate committed disable", "number", "%", {}],
    ["device_on_off", "Output", "Logical device on/off", "boolean", "", {}],
    [
      "effective_command",
      "Output",
      "Effective percent command",
      "number",
      "%",
      {},
    ],
  ] as const;
  for (const [id, kind, label, valueType, unit, params] of specs) {
    const node = program.nodes.find((n: Data) => n.id === id);
    if (
      !node ||
      node.kind !== kind ||
      node.label !== label ||
      node.value_type !== valueType ||
      node.unit !== unit ||
      !sourceEqual(projectSourceDocument(cloneSource(node.params)), params)
    )
      throw new Error(
        "CW isolation ordinary nodes, typed minimum or fixed-scan increment changed.",
      );
    if (
      id === "minimum" &&
      (!isSourceNumber(node.params.value) ||
        !/[.eE]/.test(numericToken(node.params.value)))
    )
      throw new Error(
        "CW isolation minimum lost its typed-float source representation.",
      );
  }
  const wires = [
    ["command", "bounded_command", "in"],
    ["minimum", "target", "a"],
    ["bounded_command", "target", "b"],
    ["target", "difference", "a"],
    ["previous", "difference", "b"],
    ["difference", "limited_difference", "in"],
    ["previous", "candidate", "a"],
    ["limited_difference", "candidate", "b"],
    ["device_enable", "selected", "select"],
    ["candidate", "selected", "on"],
    ["zero", "selected", "off"],
    ["selected", "previous", "in"],
    ["device_enable", "device_on_off", "in"],
    ["selected", "effective_command", "in"],
  ].map(([source, target, target_port], i) => ({
    id: `wire${i}`,
    source,
    target,
    target_port,
    source_port: "out",
  }));
  if (!sourceEqual(program.edges, wires))
    throw new Error(
      "CW isolation shared-state fourteen-wire topology changed.",
    );
  return value;
}

export function cwDescriptors(envelope: Data, report: Data) {
  const paths = [
    ["program"],
    ["bundle", "library", "definitions", 0, "program"],
  ];
  if (
    !Array.isArray(envelope.programs) ||
    envelope.programs.length !== 2 ||
    envelope.programs.some(
      (row: Data, i: number) =>
        !sourceEqual(row.path, paths[i]) ||
        row.program_id !== report.definition_id ||
        row.revision_text !== "0" ||
        row.canonical_format !== "canonical-json/1" ||
        row.canonical_sha256 !== report.program_sha256,
    )
  )
    throw new Error(
      "CW isolation original Program descriptor differs from the reviewed definition.",
    );
}
