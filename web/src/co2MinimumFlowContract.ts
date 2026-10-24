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
export type FlowUnit = "cfm" | "L/s";
export const CO2_FIELDS = [
  "co2_default",
  "co2_reset_a_default",
  "co2_reset_b_default",
  "flow_low_default",
  "flow_high_default",
] as const;
export type CO2Field = (typeof CO2_FIELDS)[number];
export type CO2Draft = Record<CO2Field, string>;
export type CO2Choices = Record<CO2Field, SourceNumber> & {
  flow_unit: FlowUnit;
};
export type CO2Import = {
  choices: CO2Choices;
  profile_sha256: string;
  reviewed_parent_sha256: string;
};
export const CO2_BASE = "/activities/templates/co2-minimum-flow";
export const CO2_PROFILE = "studio-co2-minimum-flow-template/1";
export const CO2_PROFILE_SHA =
  "9ccd226d982b55fbac68d00e445a484e6ec2b9e7bfa1d0eafc3921a320adb081";
export const CFM_TO_LPS = 0.4719474432;
export const flowCap = (unit: FlowUnit) =>
  unit === "cfm" ? 1000000 / CFM_TO_LPS : 1000000;
const scalar = (value: any) => Number(numericToken(value));

/** Only newly authored, declared float controls cross this numeric boundary. */
export function readCO2Choices(unit: FlowUnit, draft: CO2Draft): CO2Choices {
  if (!["cfm", "L/s"].includes(unit))
    throw new Error("Choose cfm or L/s for the airflow ports.");
  const choices = { flow_unit: unit } as CO2Choices;
  for (const field of CO2_FIELDS) {
    const text = draft[field].trim();
    let token: SourceNumber;
    try {
      token = sourceNumber(text);
    } catch {
      throw new Error(`${field}: enter a finite JSON number.`);
    }
    if (!Number.isFinite(scalar(token)))
      throw new Error(`${field}: enter a finite JSON number.`);
    choices[field] = /[.eE]/.test(text) ? token : sourceNumber(text + ".0");
  }
  const a = scalar(choices.co2_reset_a_default),
    b = scalar(choices.co2_reset_b_default),
    low = scalar(choices.flow_low_default),
    high = scalar(choices.flow_high_default);
  if (a < 0 || b > 1000000 || !(b > a))
    throw new Error(
      "CO2 Reset A/B defaults must be ordered inside 0–1000000 ppm, with B greater than A.",
    );
  if (low < 0 || high < low || high > flowCap(unit))
    throw new Error(
      "Airflow defaults must be nonnegative and ordered inside the 1000000 L/s equivalent domain.",
    );
  return choices;
}
export function co2Draft(choices: Data): CO2Draft {
  return Object.fromEntries(
    CO2_FIELDS.map((field) => [field, numericToken(choices[field])]),
  ) as CO2Draft;
}
function choicesEqual(value: any, expected: CO2Choices) {
  if (
    !object(value) ||
    Object.keys(value).length !== 6 ||
    value.flow_unit !== expected.flow_unit
  )
    return false;
  const declared = projectSourceDocument(cloneSource(value));
  return CO2_FIELDS.every((field) =>
    Object.is(declared[field], scalar(expected[field])),
  );
}
export async function co2Catalog(value: any) {
  const defaults = {
    flow_unit: "cfm",
    co2_default: 800,
    co2_reset_a_default: 800,
    co2_reset_b_default: 1000,
    flow_low_default: 425,
    flow_high_default: 825,
  };
  if (
    !object(value) ||
    value.format !== "bms.co2-minimum-flow-template-catalog" ||
    value.version !== 1 ||
    value.profile?.profile !== CO2_PROFILE ||
    value.profile_sha256 !== CO2_PROFILE_SHA ||
    (await manifestSha256(value.profile)) !== CO2_PROFILE_SHA ||
    !sourceEqual(value.defaults, defaults) ||
    !sourceEqual(value.defaults_by_unit?.cfm, defaults) ||
    !sourceEqual(value.defaults_by_unit?.["L/s"], {
      ...defaults,
      flow_unit: "L/s",
      flow_low_default: 425 * CFM_TO_LPS,
      flow_high_default: 825 * CFM_TO_LPS,
    }) ||
    !sourceEqual(value.flow_caps, {
      cfm: flowCap("cfm"),
      "L/s": flowCap("L/s"),
    }) ||
    !sourceEqual(value.exports, ["review", "bundle"]) ||
    value.native_compile !== false ||
    value.controller_writes !== false
  )
    throw new Error(
      "CO2 airflow template uses an unsupported source profile, unit conversion or port contract.",
    );
  return value;
}

export function co2Units(
  value: any,
  previous: CO2Choices,
  target: FlowUnit,
  catalog: Data,
) {
  if (
    !object(value) ||
    value.format !== "bms.co2-minimum-flow-template-units" ||
    value.version !== 1 ||
    value.profile_sha256 !== catalog.profile_sha256 ||
    !hash(value.source_choices_sha256) ||
    !hash(value.choices_sha256) ||
    !choicesEqual(value.source_choices, previous) ||
    value.choices?.flow_unit !== target
  )
    throw new Error(
      "Unit conversion does not match the original CO2 reset choices or current profile.",
    );
  const factor =
    previous.flow_unit === target
      ? 1
      : target === "L/s"
        ? CFM_TO_LPS
        : 1 / CFM_TO_LPS;
  const expected = { ...previous, flow_unit: target };
  for (const field of ["flow_low_default", "flow_high_default"] as const) {
    const before = scalar(previous[field]),
      converted = before * factor;
    if (before !== 0 && converted === 0)
      throw new Error("Flow conversion would erase a nonzero endpoint.");
    expected[field] = sourceNumber(
      Object.is(converted, -0) ? "-0.0" : String(converted),
    );
  }
  if (!choicesEqual(value.choices, expected))
    throw new Error(
      "Flow conversion changed an unrelated default, sign or expected converted endpoint.",
    );
  const result = readCO2Choices(target, co2Draft(value.choices));
  if (
    scalar(previous.flow_high_default) > scalar(previous.flow_low_default) &&
    scalar(result.flow_high_default) === scalar(result.flow_low_default)
  )
    throw new Error("Flow conversion would collapse a nonflat endpoint pair.");
  return value;
}

export function co2Preview(
  value: any,
  choices: CO2Choices,
  parent: Program,
  catalog: Data,
) {
  const program = value?.program,
    bundle = value?.bundle,
    item = bundle?.library?.definitions?.[0],
    provenance = program?.metadata?.co2_minimum_flow_template,
    id = value?.definition_id;
  if (
    !object(value) ||
    value.format !== "bms.co2-minimum-flow-template-preview" ||
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
    libraryVersion(parent) !== 2 ||
    typeof id !== "string" ||
    !/^co2_min_flow_[a-f0-9]{24}$/.test(id) ||
    !object(program) ||
    program.id !== id ||
    program.name !== "Authored CO2 minimum-airflow reset" ||
    program.revision !== 0 ||
    program.scan_seconds !== 1 ||
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
    provenance?.profile !== CO2_PROFILE ||
    provenance.profile_sha256 !== value.profile_sha256 ||
    provenance.choices_sha256 !== value.choices_sha256 ||
    !choicesEqual(provenance.choices, choices) ||
    !CO2_FIELDS.every(
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
    program.nodes.length !== 38 ||
    new Set(program.nodes.map((n: Data) => n.id)).size !== 38 ||
    !Array.isArray(program.edges) ||
    program.edges.length !== 57 ||
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
      "CO2 reset preview differs from the current parent source, choices, profile or shared graph.",
    );
  const inputs = [
    ["co2", "Measured CO2", "ppm", "co2_default"],
    ["co2_reset_a", "CO2 Reset A", "ppm", "co2_reset_a_default"],
    ["co2_reset_b", "CO2 Reset B", "ppm", "co2_reset_b_default"],
    ["flow_low", "Low minimum airflow", choices.flow_unit, "flow_low_default"],
    [
      "flow_high",
      "High minimum airflow",
      choices.flow_unit,
      "flow_high_default",
    ],
  ] as const;
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
    !sourceEqual(value.outputs, [
      {
        id: "minimum_airflow",
        label: "Minimum airflow request",
        value_type: "number",
        unit: choices.flow_unit,
      },
      {
        id: "reset_configuration_valid",
        label: "Last committed reset configuration valid",
        value_type: "boolean",
        unit: "",
      },
    ])
  )
    throw new Error(
      "CO2 reset live ports changed their airflow units, types or roles.",
    );
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
        "CO2 reset input defaults lost their reviewed value, sign or typed-float source.",
      );
  }
  const unit = choices.flow_unit,
    cap = flowCap(unit);
  const arithmetic: [string, string, string, Data][] = [
    ["a_safe", "Clamp", "ppm", { min: 0, max: 1000000 }],
    ["b_safe", "Clamp", "ppm", { min: 0, max: 1000000 }],
    ["low_safe", "Clamp", unit, { min: 0, max: cap }],
    ["high_safe", "Clamp", unit, { min: 0, max: cap }],
    ...["a_in_range", "b_in_range", "low_in_range", "high_in_range"].map(
      (id) => [id, "Equal", "", {}] as [string, string, string, Data],
    ),
    ["ordered_co2", "Greater", "", {}],
    ["descending_flow", "Less", "", {}],
    ["ordered_flow", "Not", "", {}],
    ...[
      "bands_in_range",
      "flows_in_range",
      "ranges_valid",
      "orders_valid",
      "reset_config_ok",
    ].map((id) => [id, "And", "", {}] as [string, string, string, Data]),
    ["fallback_span", "Constant", "ppm", { value: 1 }],
    ["co2_span", "Subtract", "ppm", {}],
    ["denominator", "Switch", "ppm", {}],
    ["co2_upper", "Min", "ppm", {}],
    ["co2_bounded", "Max", "ppm", {}],
    ["above_lower", "Subtract", "ppm", {}],
    ["fraction", "Divide", "", {}],
    ["bounded_fraction", "Clamp", "", { min: 0, max: 1 }],
    ["flow_span", "Subtract", unit, {}],
    ["scaled_span", "Multiply", unit, {}],
    ["raw_candidate", "Add", unit, {}],
    ["candidate_upper", "Min", unit, {}],
    ["bounded_candidate", "Max", unit, {}],
    ["previous_valid_flow", "Delay", unit, { initial: 0 }],
    ["selected_flow", "Switch", unit, {}],
  ];
  for (const [id, kind, unit, params] of arithmetic) {
    const node = program.nodes.find((n: Data) => n.id === id),
      type = ["Equal", "Greater", "Less", "Not", "And"].includes(kind)
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
        "CO2 reset safe arithmetic, bounds or retained-flow topology changed.",
      );
  }
  for (const port of value.outputs) {
    const node = program.nodes.find((n: Data) => n.id === port.id);
    if (
      !node ||
      node.kind !== "Output" ||
      node.label !== port.label ||
      node.unit !== port.unit ||
      node.value_type !== port.value_type ||
      !sourceEqual(node.params, {})
    )
      throw new Error(
        "CO2 reset terminal output changed its reviewed contract.",
      );
  }
  // Wires are filled from the approved literal topology, never from the response.
  const wires: [string, string, string][] = [
    ["co2_reset_a", "a_safe", "in"],
    ["co2_reset_b", "b_safe", "in"],
    ["flow_low", "low_safe", "in"],
    ["flow_high", "high_safe", "in"],
    ["co2_reset_a", "a_in_range", "a"],
    ["a_safe", "a_in_range", "b"],
    ["co2_reset_b", "b_in_range", "a"],
    ["b_safe", "b_in_range", "b"],
    ["flow_low", "low_in_range", "a"],
    ["low_safe", "low_in_range", "b"],
    ["flow_high", "high_in_range", "a"],
    ["high_safe", "high_in_range", "b"],
    ["b_safe", "ordered_co2", "a"],
    ["a_safe", "ordered_co2", "b"],
    ["high_safe", "descending_flow", "a"],
    ["low_safe", "descending_flow", "b"],
    ["a_in_range", "bands_in_range", "a"],
    ["b_in_range", "bands_in_range", "b"],
    ["low_in_range", "flows_in_range", "a"],
    ["high_in_range", "flows_in_range", "b"],
    ["bands_in_range", "ranges_valid", "a"],
    ["flows_in_range", "ranges_valid", "b"],
    ["ordered_co2", "orders_valid", "a"],
    ["ordered_flow", "orders_valid", "b"],
    ["ranges_valid", "reset_config_ok", "a"],
    ["orders_valid", "reset_config_ok", "b"],
    ["b_safe", "co2_span", "a"],
    ["a_safe", "co2_span", "b"],
    ["co2", "co2_upper", "a"],
    ["b_safe", "co2_upper", "b"],
    ["co2_upper", "co2_bounded", "a"],
    ["a_safe", "co2_bounded", "b"],
    ["co2_bounded", "above_lower", "a"],
    ["a_safe", "above_lower", "b"],
    ["above_lower", "fraction", "a"],
    ["denominator", "fraction", "b"],
    ["high_safe", "flow_span", "a"],
    ["low_safe", "flow_span", "b"],
    ["bounded_fraction", "scaled_span", "a"],
    ["flow_span", "scaled_span", "b"],
    ["low_safe", "raw_candidate", "a"],
    ["scaled_span", "raw_candidate", "b"],
    ["raw_candidate", "candidate_upper", "a"],
    ["high_safe", "candidate_upper", "b"],
    ["candidate_upper", "bounded_candidate", "a"],
    ["low_safe", "bounded_candidate", "b"],
    ["descending_flow", "ordered_flow", "in"],
    ["ordered_co2", "denominator", "select"],
    ["co2_span", "denominator", "on"],
    ["fallback_span", "denominator", "off"],
    ["fraction", "bounded_fraction", "in"],
    ["reset_config_ok", "selected_flow", "select"],
    ["bounded_candidate", "selected_flow", "on"],
    ["previous_valid_flow", "selected_flow", "off"],
    ["selected_flow", "previous_valid_flow", "in"],
    ["selected_flow", "minimum_airflow", "in"],
    ["reset_config_ok", "reset_configuration_valid", "in"],
  ];
  const edges = wires.map(([source, target, target_port], i) => ({
    id: `wire${i}`,
    source,
    target,
    target_port,
    source_port: "out",
  }));
  if (!sourceEqual(program.edges, edges))
    throw new Error(
      "CO2 reset 57-wire topology differs from the reviewed safe graph.",
    );
  return value;
}
export function co2Descriptors(envelope: Data, report: Data) {
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
      "CO2 reset original Program descriptor differs from the reviewed definition.",
    );
}
