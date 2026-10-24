import { projectSourceDocument, sourceEqual } from "./programSource";
export type Data = Record<string, any>;
export const SERIES_BASE = "/series-fan-vav-wizard";
export const SERIES_PROFILE = "studio-occupied-series-fan-vav/1";
export const SERIES_PROFILE_SHA =
  "46bc497336413f1f52944d5d16cec45cd2ba1860800c7d0c566d3a5142a43db9";
export const absoluteFields = [
  "zone_default",
  "heating_setpoint",
  "cooling_setpoint",
];
const differenceFields = ["entry_delta", "release_delta"];
const temperatureGains = [
  "heating_kp",
  "heating_ki",
  "cooling_kp",
  "cooling_ki",
];
const flowFields = [
  "primary_flow_min",
  "primary_flow_max",
  "primary_flow_default",
];
const flowGains = ["flow_kp", "flow_ki"];
const times = ["close_seconds", "proof_seconds", "startup_timeout_seconds"];
const flags = [
  "occupied_default",
  "unit_enable_default",
  "energy_holdoff_default",
  "fan_proven_default",
  "fan_reset_default",
];
const texts = ["project_id", "name", "model", "firmware", "release_mode"];
const fixed = {
  operation: "occupied-only",
  fan: "single-speed-series",
  heating: "proportional-hot-water",
  flow_feedback: "calibrated-primary",
};
export const CFM_TO_LPS = 0.4719474432;
export const object = (value: any): value is Data =>
  value !== null && typeof value === "object" && !Array.isArray(value);
export const hash = (value: any) =>
  typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
export async function blobSha256(blob: Blob) {
  return Array.from(
    new Uint8Array(
      await crypto.subtle.digest("SHA-256", await blob.arrayBuffer()),
    ),
    (byte) => byte.toString(16).padStart(2, "0"),
  ).join("");
}
const keys = (value: Data, expected: string[]) =>
  Object.keys(value).length === expected.length &&
  expected.every((key) => Object.hasOwn(value, key));
export function choicesValid(value: any) {
  if (
    !object(value) ||
    !keys(value, [
      ...texts,
      ...absoluteFields,
      ...differenceFields,
      ...temperatureGains,
      ...flowFields,
      ...flowGains,
      ...times,
      ...flags,
      ...Object.keys(fixed),
      "family",
      "temperature_unit",
      "flow_unit",
      "scan_seconds",
    ]) ||
    !texts.every((key) => typeof value[key] === "string") ||
    !/^[A-Za-z][A-Za-z0-9_-]{0,79}$/.test(value.project_id) ||
    !value.name.trim() ||
    value.name.length > 200 ||
    ["model", "firmware", "release_mode"].some(
      (key) => value[key].length > 80,
    ) ||
    !Object.entries(fixed).every(
      ([key, expected]) => value[key] === expected,
    ) ||
    !["universal-runtime", "johnson-fx", "johnson-metasys"].includes(
      value.family,
    ) ||
    !["degF", "degC"].includes(value.temperature_unit) ||
    !["cfm", "L/s"].includes(value.flow_unit) ||
    ![
      ...absoluteFields,
      ...differenceFields,
      ...temperatureGains,
      ...flowFields,
      ...flowGains,
    ].every((key) => Number.isFinite(value[key])) ||
    !flags.every((key) => typeof value[key] === "boolean") ||
    !Number.isSafeInteger(value.scan_seconds) ||
    value.scan_seconds < 1 ||
    value.scan_seconds > 60 ||
    !times.every(
      (key) =>
        Number.isSafeInteger(value[key]) &&
        value[key] >= 1 &&
        value[key] <= 3600 &&
        value[key] % value.scan_seconds === 0,
    ) ||
    value.startup_timeout_seconds < value.proof_seconds ||
    value.heating_setpoint >= value.cooling_setpoint ||
    value.entry_delta <= value.release_delta ||
    value.release_delta < 0 ||
    value.primary_flow_min >= value.primary_flow_max
  )
    return false;
  const ratio = value.temperature_unit === "degF" ? 5 / 9 : 1,
    flow = value.flow_unit === "cfm" ? CFM_TO_LPS : 1;
  return (
    absoluteFields.every((key) => {
      const c =
        value.temperature_unit === "degC"
          ? value[key]
          : ((value[key] - 32) * 5) / 9;
      return c >= -50 && c <= 100;
    }) &&
    differenceFields.every(
      (key) => value[key] >= 0 && value[key] * ratio <= 100,
    ) &&
    temperatureGains.every(
      (key) =>
        value[key] >= 0 &&
        value[key] <= 1800000 &&
        value[key] / ratio <= 1800000,
    ) &&
    flowFields.every(
      (key) =>
        value[key] >= 0 &&
        value[key] <= 3000000 &&
        value[key] * flow <= 1000000,
    ) &&
    flowGains.every(
      (key) =>
        value[key] >= 0 &&
        value[key] <= 3000000 &&
        value[key] / flow <= 3000000,
    )
  );
}
const profileLimits = {
  temperature_celsius: [-50, 100],
  temperature_difference_celsius: [0, 100],
  primary_flow_lps: [0, 1000000],
  temperature_gain_per_celsius: [0, 1800000],
  flow_gain_per_lps: [0, 3000000],
  scan_seconds: [1, 60],
  timing_seconds: [1, 3600],
  generated_nodes: 256,
};
// This profile contains only integer numbers. Hash its exact bounded plain DTO,
// without normalizing or reserializing any Program/source numeric atom.
function profileCanonical(value: any): string {
  if (Array.isArray(value))
    return "[" + value.map(profileCanonical).join(",") + "]";
  if (object(value))
    return (
      "{" +
      Object.keys(value)
        .sort()
        .map((key) => JSON.stringify(key) + ":" + profileCanonical(value[key]))
        .join(",") +
      "}"
    );
  if (typeof value === "number" && !Number.isSafeInteger(value))
    throw new Error("Unsupported source profile number.");
  return JSON.stringify(value);
}
export async function catalogResult(value: any) {
  if (
    !object(value) ||
    value.format !== "bms.series-fan-vav-wizard-catalog" ||
    value.version !== 1 ||
    value.profile?.profile !== SERIES_PROFILE ||
    value.profile_sha256 !== SERIES_PROFILE_SHA ||
    value.profile.source?.document !== "LIT-12011147" ||
    value.profile.source.edition !== "18.0" ||
    value.profile.source.sha256 !==
      "68935362c85cb1879dc033cc701115e8ea7c4ecb26748f21a9ceaf0454f82903" ||
    typeof value.profile.source.url !== "string" ||
    !value.profile.source.url.startsWith("https://docs.johnsoncontrols.com/") ||
    !Array.isArray(value.profile.source.pdf_pages) ||
    !value.profile.source.pdf_pages.every(
      (p: any) => Number.isSafeInteger(p) && p > 0,
    ) ||
    !object(value.profile.semantics) ||
    !Object.values(value.profile.semantics).every(
      (v) => typeof v === "string",
    ) ||
    !Array.isArray(value.profile.gaps) ||
    !value.profile.gaps.every((v: any) => typeof v === "string") ||
    !sourceEqual(value.limits, profileLimits) ||
    !sourceEqual(value.profile.limits, value.limits) ||
    !choicesValid(value.defaults) ||
    (await blobSha256(new Blob([profileCanonical(value.profile)]))) !==
      SERIES_PROFILE_SHA
  )
    throw new Error(
      "Series-fan VAV catalog is malformed or uses an unsupported source profile.",
    );
  return value;
}
function manifest(rows: any, program: Data, kind: "Input" | "Output") {
  const nodes = program.nodes.filter((n: any) => n.kind === kind);
  return (
    Array.isArray(rows) &&
    rows.length === nodes.length &&
    rows.length <= 32 &&
    new Set(rows.map((r: any) => r?.id)).size === rows.length &&
    rows.every((r: any) => {
      const n = nodes.find((n: any) => n.id === r?.id);
      return (
        object(r) &&
        keys(r, [
          "id",
          "label",
          "value_type",
          "unit",
          ...(kind === "Input" ? ["default"] : []),
        ]) &&
        n &&
        r.label === n.label &&
        r.value_type === n.value_type &&
        r.unit === n.unit &&
        ["number", "boolean"].includes(r.value_type) &&
        (kind === "Output" ||
          sourceEqual(r.default, projectSourceDocument(n.params.default)))
      );
    })
  );
}
export function previewResult(value: any, choices: Data, catalog: Data) {
  const program = value?.program,
    provenance = program?.metadata?.series_fan_vav_wizard;
  if (
    !object(value) ||
    value.format !== "bms.series-fan-vav-wizard-preview" ||
    value.version !== 1 ||
    value.profile_sha256 !== catalog.profile_sha256 ||
    !sourceEqual(value.profile, catalog.profile) ||
    !choicesValid(value.choices) ||
    !sourceEqual(value.choices, choices) ||
    !hash(value.choices_sha256) ||
    !hash(value.program_sha256) ||
    !object(program) ||
    program.id !== choices.project_id ||
    program.name !== choices.name ||
    program.scan_seconds !== choices.scan_seconds ||
    !sourceEqual(program.target, {
      family: choices.family,
      model: choices.model,
      firmware: choices.firmware,
      release_mode: choices.release_mode,
      max_nodes: 2000,
      physical_inputs: null,
      physical_outputs: null,
    }) ||
    provenance?.profile !== SERIES_PROFILE ||
    provenance.profile_sha256 !== value.profile_sha256 ||
    provenance.choices_sha256 !== value.choices_sha256 ||
    // Choice/default DTOs have bounded semantic numbers. Preserve the Program
    // token tree; only project these declared DTO copies for comparison.
    !sourceEqual(projectSourceDocument(provenance.choices), choices) ||
    !sourceEqual(provenance.source, catalog.profile.source) ||
    !sourceEqual(provenance.unimplemented, catalog.profile.gaps) ||
    !sourceEqual(projectSourceDocument(provenance.inputs), value.inputs) ||
    !sourceEqual(provenance.outputs, value.outputs) ||
    !sourceEqual(provenance.inactive_choices, value.inactive_choices) ||
    program.metadata.application !== "occupied-series-fan-vav" ||
    program.metadata.native_deployment_verified !== false ||
    !Array.isArray(program.nodes) ||
    program.nodes.length > 256 ||
    new Set(program.nodes.map((n: any) => n.id)).size !==
      program.nodes.length ||
    !Array.isArray(program.edges) ||
    program.edges.length > 8000 ||
    !manifest(value.inputs, program, "Input") ||
    !manifest(value.outputs, program, "Output") ||
    !Array.isArray(value.diagnostics) ||
    !value.diagnostics.every(
      (r: any) =>
        object(r) &&
        ["warning", "error"].includes(r.level) &&
        typeof r.code === "string" &&
        typeof r.message === "string",
    ) ||
    !Array.isArray(value.inactive_choices) ||
    !value.inactive_choices.every((r: any) => typeof r === "string") ||
    typeof value.can_create !== "boolean" ||
    value.native_compile !== false ||
    value.controller_writes !== false
  )
    throw new Error(
      "Series-fan VAV preview does not match these exact choices, ordinary graph, interfaces or source profile.",
    );
  const expectedInputs: Record<string, [string, string, any]> = {
    occupied: ["boolean", "", choices.occupied_default],
    unit_enable: ["boolean", "", choices.unit_enable_default],
    energy_holdoff: ["boolean", "", choices.energy_holdoff_default],
    fan_proven: ["boolean", "", choices.fan_proven_default],
    fan_reset: ["boolean", "", choices.fan_reset_default],
    zone_temperature: [
      "number",
      choices.temperature_unit,
      choices.zone_default,
    ],
    heating_setpoint: [
      "number",
      choices.temperature_unit,
      choices.heating_setpoint,
    ],
    cooling_setpoint: [
      "number",
      choices.temperature_unit,
      choices.cooling_setpoint,
    ],
    primary_airflow: [
      "number",
      choices.flow_unit,
      choices.primary_flow_default,
    ],
  };
  const expectedOutputs: Record<string, [string, string]> = Object.fromEntries([
    ...[
      "raw_run_request",
      "setpoints_valid",
      "zone_range_valid",
      "primary_flow_valid",
      "control_permitted",
      "close_phase",
      "close_complete",
      "fan_starting",
      "fan_ready",
      "fan_fault",
      "reset_accepted",
      "fan_enable",
      "fan_proof_stable",
      "startup_deadline_reached",
      "heating_active",
      "cooling_active",
    ].map((id) => [id, ["boolean", ""]]),
    ...["series_state", "thermal_state"].map((id) => [id, ["number", ""]]),
    ...[
      "zone_cooling_demand",
      "zone_heating_demand",
      "primary_damper",
      "reheat_valve",
    ].map((id) => [id, ["number", "%"]]),
    ...["primary_flow_target", "primary_flow_measured"].map((id) => [
      id,
      ["number", choices.flow_unit],
    ]),
  ]);
  if (
    value.inputs.length !== Object.keys(expectedInputs).length ||
    value.inputs.some(
      (r: any) =>
        !Object.hasOwn(expectedInputs, r.id) ||
        !sourceEqual([r.value_type, r.unit, r.default], expectedInputs[r.id]),
    ) ||
    value.outputs.length !== Object.keys(expectedOutputs).length ||
    value.outputs.some(
      (r: any) =>
        !Object.hasOwn(expectedOutputs, r.id) ||
        !sourceEqual([r.value_type, r.unit], expectedOutputs[r.id]),
    ) ||
    value.can_create !==
      !value.diagnostics.some((r: any) => r.level === "error")
  )
    throw new Error(
      "Series-fan VAV input/output choices, declared units/defaults or graph eligibility are inconsistent.",
    );
  return value;
}
export function unitResult(
  value: any,
  original: Data,
  temperature_unit: string,
  flow_unit: string,
  catalog: Data,
) {
  if (
    !object(value) ||
    value.profile_sha256 !== catalog.profile_sha256 ||
    !hash(value.choices_sha256) ||
    !hash(value.source_choices_sha256) ||
    !sourceEqual(value.source_choices, original) ||
    !choicesValid(value.choices) ||
    value.choices.temperature_unit !== temperature_unit ||
    value.choices.flow_unit !== flow_unit
  )
    throw new Error(
      "Series-fan VAV unit conversion belongs to another source draft/profile.",
    );
  const expected = structuredClone(original);
  if (temperature_unit !== original.temperature_unit) {
    const ratio = temperature_unit === "degC" ? 5 / 9 : 9 / 5;
    for (const key of absoluteFields)
      expected[key] =
        temperature_unit === "degC"
          ? ((expected[key] - 32) * 5) / 9
          : (expected[key] * 9) / 5 + 32;
    for (const key of differenceFields) expected[key] *= ratio;
    for (const key of temperatureGains) expected[key] /= ratio;
  }
  if (flow_unit !== original.flow_unit) {
    const ratio = flow_unit === "L/s" ? CFM_TO_LPS : 1 / CFM_TO_LPS;
    for (const key of flowFields) expected[key] *= ratio;
    for (const key of flowGains) expected[key] /= ratio;
  }
  expected.temperature_unit = temperature_unit;
  expected.flow_unit = flow_unit;
  // Match converter binary64 operation order only for the bounded choice DTO.
  // Never project or normalize the actual Program tree or native observations.
  if (
    !keys(value.choices, Object.keys(expected)) ||
    !Object.keys(expected).every((key) => expected[key] === value.choices[key])
  )
    throw new Error(
      "Series-fan VAV conversion changed identity/flags/timing or failed coupled absolute/delta/inverse-gain/flow conversion.",
    );
  return value.choices;
}
