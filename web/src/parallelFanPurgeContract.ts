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
export const PURGE_BASE = "/activities/templates/parallel-fan-purge";
export const PURGE_PROFILE = "studio-parallel-fan-purge-template/1";
export const PURGE_PROFILE_SHA =
  "4b96936ccf6b42229b380de34b3b5b34c26a4adb3df6408fc861e940247f5af3";
export const PURGE_FIELDS = [
  "heating_percent_command_default",
  "cooling_percent_command_default",
  "fan_on_threshold_default",
  "fan_off_threshold_default",
  "heating_purge_duration_default",
] as const;
export type PurgeField = (typeof PURGE_FIELDS)[number];
export type PurgeDraft = Record<PurgeField, string>;
export type PurgeChoices = Record<PurgeField, SourceNumber> & {
  scan_seconds: number;
};
export type PurgeImport = {
  choices: PurgeChoices;
  profile_sha256: string;
  reviewed_parent_sha256: string;
};
export const PURGE_DEFAULT_DRAFT: PurgeDraft = {
  heating_percent_command_default: "0.0",
  cooling_percent_command_default: "0.0",
  fan_on_threshold_default: "5.0",
  fan_off_threshold_default: "0.1",
  heating_purge_duration_default: "120.0",
};
export const PURGE_LABELS: Record<PurgeField, string> = {
  heating_percent_command_default: "Heating command default",
  cooling_percent_command_default: "Cooling command default",
  fan_on_threshold_default: "Fan-on threshold default",
  fan_off_threshold_default: "Fan-off threshold default",
  heating_purge_duration_default: "Heating purge seconds default",
};
const scalar = (v: any) => Number(numericToken(v));
/** Numeric projection is confined to newly authored controls and declared DTO copies. */
export function readPurgeChoices(
  draft: PurgeDraft,
  scan: string,
): PurgeChoices {
  const text = scan.trim(),
    h = Number(text);
  if (!/^\d+$/.test(text) || !Number.isSafeInteger(h) || h < 1 || h > 60)
    throw new Error(
      "Declared purge scan must be a whole number from 1 to 60 seconds.",
    );
  const choices = { scan_seconds: h } as PurgeChoices;
  for (const field of PURGE_FIELDS) {
    const text = draft[field].trim();
    let token: SourceNumber;
    try {
      token = sourceNumber(text);
    } catch {
      throw new Error(PURGE_LABELS[field] + ": enter a finite JSON number.");
    }
    if (!Number.isFinite(scalar(token)))
      throw new Error(PURGE_LABELS[field] + ": enter a finite JSON number.");
    choices[field] = /[.eE]/.test(text) ? token : sourceNumber(text + ".0");
  }
  const heat = scalar(choices.heating_percent_command_default),
    cool = scalar(choices.cooling_percent_command_default),
    on = scalar(choices.fan_on_threshold_default),
    off = scalar(choices.fan_off_threshold_default),
    duration = scalar(choices.heating_purge_duration_default);
  if (heat < 0 || heat > 100 || cool < 0 || cool > 100)
    throw new Error(
      "Heating and cooling command defaults must be inside 0–100%.",
    );
  if (!(0 < off && off < on && on < 100))
    throw new Error(
      "Fan thresholds require 0 < off < on < 100; no epsilon is added.",
    );
  if (duration < 0 || duration > 86400)
    throw new Error("Heating purge duration must be inside 0–86400 seconds.");
  return choices;
}
function choicesEqual(value: any, expected: PurgeChoices) {
  if (!object(value) || Object.keys(value).length !== 6) return false;
  const declared = projectSourceDocument(cloneSource(value));
  return (
    declared.scan_seconds === expected.scan_seconds &&
    PURGE_FIELDS.every((field) =>
      Object.is(declared[field], scalar(expected[field])),
    )
  );
}
export async function purgeCatalog(value: any) {
  if (
    !object(value) ||
    value.format !== "bms.parallel-fan-purge-template-catalog" ||
    value.version !== 1 ||
    value.profile?.profile !== PURGE_PROFILE ||
    value.profile_sha256 !== PURGE_PROFILE_SHA ||
    (await manifestSha256(value.profile)) !== PURGE_PROFILE_SHA ||
    !sourceEqual(value.defaults, {
      scan_seconds: 1,
      heating_percent_command_default: 0,
      cooling_percent_command_default: 0,
      fan_on_threshold_default: 5,
      fan_off_threshold_default: 0.1,
      heating_purge_duration_default: 120,
    }) ||
    !sourceEqual(value.exports, ["review", "bundle"]) ||
    value.native_compile !== false ||
    value.controller_writes !== false
  )
    throw new Error(
      "Parallel fan purge uses an unsupported source profile, threshold domain or clock contract.",
    );
  return value;
}
export function purgePreview(
  value: any,
  choices: PurgeChoices,
  parent: Program,
  catalog: Data,
) {
  const program = value?.program,
    bundle = value?.bundle,
    item = bundle?.library?.definitions?.[0],
    provenance = program?.metadata?.parallel_fan_purge_template,
    id = value?.definition_id;
  if (
    !object(value) ||
    value.format !== "bms.parallel-fan-purge-template-preview" ||
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
    value.parent_reference?.id !== parent.id ||
    value.parent_reference.revision !== parent.revision ||
    value.parent_reference.scan_seconds !== parent.scan_seconds ||
    parent.scan_seconds !== choices.scan_seconds ||
    libraryVersion(parent) !== 2 ||
    typeof id !== "string" ||
    !/^parallel_fan_purge_[a-f0-9]{24}$/.test(id) ||
    !object(program) ||
    program.id !== id ||
    program.name !== "Authored parallel fan thermal request and purge" ||
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
    provenance?.profile !== PURGE_PROFILE ||
    provenance.profile_sha256 !== value.profile_sha256 ||
    provenance.choices_sha256 !== value.choices_sha256 ||
    !choicesEqual(provenance.choices, choices) ||
    !isSourceNumber(provenance.choices.scan_seconds) ||
    /[.eE]/.test(numericToken(provenance.choices.scan_seconds)) ||
    !PURGE_FIELDS.every(
      (field) =>
        isSourceNumber(provenance.choices[field]) &&
        /[.eE]/.test(numericToken(provenance.choices[field])),
    ) ||
    !sourceEqual(provenance.source, catalog.profile.source) ||
    !sourceEqual(provenance.unimplemented, catalog.profile.gaps) ||
    bundle?.format !== "bms-macro-library/2" ||
    bundle.root !== id ||
    bundle.library?.version !== 2 ||
    !Array.isArray(bundle.library.definitions) ||
    bundle.library.definitions.length !== 1 ||
    item.id !== id ||
    item.name !== program.name ||
    !sourceEqual(item.program, program) ||
    !Array.isArray(program.nodes) ||
    program.nodes.length !== 51 ||
    new Set(program.nodes.map((n: Data) => n.id)).size !== 51 ||
    !Array.isArray(program.edges) ||
    program.edges.length !== 73 ||
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
      "Parallel fan purge preview differs from the current parent clock, source, choices, profile or shared graph.",
    );
  const inputs = [
    [
      "heating_percent_command",
      "Heating percent command",
      "%",
      "heating_percent_command_default",
    ],
    [
      "cooling_percent_command",
      "Cooling percent command",
      "%",
      "cooling_percent_command_default",
    ],
    ["fan_on_threshold", "Fan on threshold", "%", "fan_on_threshold_default"],
    [
      "fan_off_threshold",
      "Fan off threshold",
      "%",
      "fan_off_threshold_default",
    ],
    [
      "heating_purge_duration",
      "Heating below-off purge duration",
      "s",
      "heating_purge_duration_default",
    ],
  ] as const;
  const outputs = [
    {
      id: "fan_request",
      label: "Parallel fan logical request",
      value_type: "boolean",
      unit: "",
    },
    {
      id: "request_configuration_valid",
      label: "Last committed request configuration valid",
      value_type: "boolean",
      unit: "",
    },
  ];
  if (
    !sourceEqual(
      value.inputs,
      inputs.map(([id, label, unit]) => ({
        id,
        label,
        unit,
        value_type: "number",
        required: true,
      })),
    ) ||
    !sourceEqual(value.outputs, outputs)
  )
    throw new Error("Parallel fan purge live input/output contracts changed.");
  for (const [id, label, unit, field] of inputs) {
    const node = program.nodes.find((n: Data) => n.id === id);
    if (
      !node ||
      node.kind !== "Input" ||
      node.label !== label ||
      node.unit !== unit ||
      node.value_type !== "number" ||
      !sourceEqual(projectSourceDocument(cloneSource(node.params)), {
        default: scalar(choices[field]),
      }) ||
      !isSourceNumber(node.params.default) ||
      !/[.eE]/.test(numericToken(node.params.default))
    )
      throw new Error(
        "Parallel fan purge input default lost its reviewed value, sign or typed-float source.",
      );
  }
  const graph: [string, string, string, Data][] = [
    [
      "heat_safe",
      "Clamp",
      "%",
      {
        min: 0,
        max: 100,
      },
    ],
    [
      "cool_safe",
      "Clamp",
      "%",
      {
        min: 0,
        max: 100,
      },
    ],
    [
      "on_safe",
      "Clamp",
      "%",
      {
        min: 0,
        max: 100,
      },
    ],
    [
      "off_safe",
      "Clamp",
      "%",
      {
        min: 0,
        max: 100,
      },
    ],
    [
      "duration_safe",
      "Clamp",
      "s",
      {
        min: 0,
        max: 86400,
      },
    ],
    ["heat_in_range", "Equal", "", {}],
    ["cool_in_range", "Equal", "", {}],
    ["on_in_range", "Equal", "", {}],
    ["off_in_range", "Equal", "", {}],
    ["duration_in_range", "Equal", "", {}],
    [
      "zero_percent",
      "Constant",
      "%",
      {
        value: 0,
      },
    ],
    [
      "hundred_percent",
      "Constant",
      "%",
      {
        value: 100,
      },
    ],
    [
      "zero_seconds",
      "Constant",
      "s",
      {
        value: 0,
      },
    ],
    [
      "scan_step",
      "Constant",
      "s",
      {
        value: choices.scan_seconds,
      },
    ],
    ["threshold_order", "Greater", "", {}],
    ["off_positive", "Greater", "", {}],
    ["on_below_ceiling", "Less", "", {}],
    ["commands_in_range", "And", "", {}],
    ["thresholds_in_range", "And", "", {}],
    ["percent_ranges_valid", "And", "", {}],
    ["all_ranges_valid", "And", "", {}],
    ["threshold_order_valid", "And", "", {}],
    ["threshold_domain_valid", "And", "", {}],
    ["request_config_ok", "And", "", {}],
    ["heat_below_off", "Less", "", {}],
    ["cool_below_off", "Less", "", {}],
    ["heat_start", "Greater", "", {}],
    ["cool_start", "Greater", "", {}],
    ["thermal_start", "Or", "", {}],
    [
      "previous_request",
      "Delay",
      "",
      {
        initial: false,
      },
    ],
    [
      "previous_elapsed",
      "Delay",
      "s",
      {
        initial: 0,
      },
    ],
    [
      "bounded_previous_elapsed",
      "Clamp",
      "s",
      {
        min: 0,
        max: 86400,
      },
    ],
    ["incremented_elapsed", "Add", "s", {}],
    [
      "capped_elapsed",
      "Clamp",
      "s",
      {
        min: 0,
        max: 86400,
      },
    ],
    ["elapsed_permission", "And", "", {}],
    ["next_elapsed", "Switch", "s", {}],
    ["purge_not_satisfied", "Less", "", {}],
    ["purge_satisfied", "Not", "", {}],
    ["both_commands_low", "And", "", {}],
    ["release_request", "And", "", {}],
    ["not_release_request", "Not", "", {}],
    ["held_request", "And", "", {}],
    ["candidate_request", "Or", "", {}],
    ["selected_request", "Switch", "", {}],
  ];
  for (const [id, kind, unit, params] of graph) {
    const node = program.nodes.find((n: Data) => n.id === id),
      type =
        ["Equal", "Greater", "Less", "And", "Or", "Not"].includes(kind) ||
        ["previous_request", "selected_request"].includes(id)
          ? "boolean"
          : "number";
    if (
      !node ||
      node.kind !== kind ||
      node.unit !== unit ||
      node.value_type !== type ||
      node.label !== id[0].toUpperCase() + id.slice(1).replaceAll("_", " ") ||
      !sourceEqual(projectSourceDocument(cloneSource(node.params)), params)
    )
      throw new Error(
        "Parallel fan purge safe graph, scan step or shared memory changed.",
      );
  }
  for (const port of outputs) {
    const node = program.nodes.find((n: Data) => n.id === port.id);
    if (
      !node ||
      node.kind !== "Output" ||
      node.label !== port.label ||
      node.value_type !== "boolean" ||
      node.unit !== "" ||
      !sourceEqual(node.params, {})
    )
      throw new Error("Parallel fan purge terminal Boolean output changed.");
  }
  const wires: [string, string, string][] = [
    ["heating_percent_command", "heat_safe", "in"],
    ["heating_percent_command", "heat_in_range", "a"],
    ["heat_safe", "heat_in_range", "b"],
    ["cooling_percent_command", "cool_safe", "in"],
    ["cooling_percent_command", "cool_in_range", "a"],
    ["cool_safe", "cool_in_range", "b"],
    ["fan_on_threshold", "on_safe", "in"],
    ["fan_on_threshold", "on_in_range", "a"],
    ["on_safe", "on_in_range", "b"],
    ["fan_off_threshold", "off_safe", "in"],
    ["fan_off_threshold", "off_in_range", "a"],
    ["off_safe", "off_in_range", "b"],
    ["heating_purge_duration", "duration_safe", "in"],
    ["heating_purge_duration", "duration_in_range", "a"],
    ["duration_safe", "duration_in_range", "b"],
    ["on_safe", "threshold_order", "a"],
    ["off_safe", "threshold_order", "b"],
    ["off_safe", "off_positive", "a"],
    ["zero_percent", "off_positive", "b"],
    ["on_safe", "on_below_ceiling", "a"],
    ["hundred_percent", "on_below_ceiling", "b"],
    ["heat_in_range", "commands_in_range", "a"],
    ["cool_in_range", "commands_in_range", "b"],
    ["on_in_range", "thresholds_in_range", "a"],
    ["off_in_range", "thresholds_in_range", "b"],
    ["commands_in_range", "percent_ranges_valid", "a"],
    ["thresholds_in_range", "percent_ranges_valid", "b"],
    ["percent_ranges_valid", "all_ranges_valid", "a"],
    ["duration_in_range", "all_ranges_valid", "b"],
    ["threshold_order", "threshold_order_valid", "a"],
    ["off_positive", "threshold_order_valid", "b"],
    ["threshold_order_valid", "threshold_domain_valid", "a"],
    ["on_below_ceiling", "threshold_domain_valid", "b"],
    ["all_ranges_valid", "request_config_ok", "a"],
    ["threshold_domain_valid", "request_config_ok", "b"],
    ["heat_safe", "heat_below_off", "a"],
    ["off_safe", "heat_below_off", "b"],
    ["cool_safe", "cool_below_off", "a"],
    ["off_safe", "cool_below_off", "b"],
    ["heat_safe", "heat_start", "a"],
    ["on_safe", "heat_start", "b"],
    ["cool_safe", "cool_start", "a"],
    ["on_safe", "cool_start", "b"],
    ["heat_start", "thermal_start", "a"],
    ["cool_start", "thermal_start", "b"],
    ["previous_elapsed", "bounded_previous_elapsed", "in"],
    ["bounded_previous_elapsed", "incremented_elapsed", "a"],
    ["scan_step", "incremented_elapsed", "b"],
    ["incremented_elapsed", "capped_elapsed", "in"],
    ["request_config_ok", "elapsed_permission", "a"],
    ["heat_below_off", "elapsed_permission", "b"],
    ["elapsed_permission", "next_elapsed", "select"],
    ["capped_elapsed", "next_elapsed", "on"],
    ["zero_seconds", "next_elapsed", "off"],
    ["next_elapsed", "purge_not_satisfied", "a"],
    ["duration_safe", "purge_not_satisfied", "b"],
    ["purge_not_satisfied", "purge_satisfied", "in"],
    ["heat_below_off", "both_commands_low", "a"],
    ["cool_below_off", "both_commands_low", "b"],
    ["both_commands_low", "release_request", "a"],
    ["purge_satisfied", "release_request", "b"],
    ["release_request", "not_release_request", "in"],
    ["previous_request", "held_request", "a"],
    ["not_release_request", "held_request", "b"],
    ["thermal_start", "candidate_request", "a"],
    ["held_request", "candidate_request", "b"],
    ["request_config_ok", "selected_request", "select"],
    ["candidate_request", "selected_request", "on"],
    ["previous_request", "selected_request", "off"],
    ["selected_request", "previous_request", "in"],
    ["next_elapsed", "previous_elapsed", "in"],
    ["selected_request", "fan_request", "in"],
    ["request_config_ok", "request_configuration_valid", "in"],
  ];
  const edges = wires.map(([source, target, target_port], i) => ({
    id: `wire${i}`,
    source,
    target,
    target_port,
    source_port: "out",
  }));
  if (!sourceEqual(program.edges, edges))
    throw new Error("Parallel fan purge 73-wire safe topology changed.");
  return value;
}
export function purgeDescriptors(envelope: Data, report: Data) {
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
      "Parallel fan purge original Program descriptors differ from the reviewed definition.",
    );
}
