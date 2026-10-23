import { projectSourceDocument, sourceEqual } from "./programSource";
export type Data = Record<string, any>;
export const UV_BASE = "/unit-ventilator-cycle3-wizard";
export const UV_PROFILE = "studio-occupied-uv-cycle3/1";
export const UV_PROFILE_SHA =
  "b03a33754a36e435526e70d61ad18859b0a9acabf478781e4f634866aa1106ae";
export const absoluteFields = [
  "zone_default",
  "mixed_air_default",
  "heating_setpoint",
  "cooling_setpoint",
  "mixed_air_setpoint",
];
const differenceFields = ["entry_delta", "release_delta"];
const temperatureGains = [
  "heating_kp",
  "heating_ki",
  "cooling_kp",
  "cooling_ki",
  "mixed_air_kp",
  "mixed_air_ki",
  "zone_limit_kp",
  "zone_limit_ki",
];
const times = ["proof_seconds", "startup_timeout_seconds"];
const flags = [
  "occupied_default",
  "unit_enable_default",
  "energy_holdoff_default",
  "airflow_proven_default",
  "fan_reset_default",
  "condensate_alarm_default",
  "heating_available_default",
  "cooling_available_default",
];
const texts = ["project_id", "name", "model", "firmware", "release_mode"];
const fixed = {
  operation: "occupied-only",
  fan: "single-speed",
  cycle: "authored-cycle-3",
  coils: "separate-proportional-hydronic",
  mixing_action: "cold-outdoor-only",
};
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
      ...times,
      ...flags,
      ...Object.keys(fixed),
      "family",
      "temperature_unit",
      "condensate_policy",
      "minimum_outdoor_position",
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
    !["disable-cooling", "shutdown-unit"].includes(value.condensate_policy) ||
    !Number.isFinite(value.minimum_outdoor_position) ||
    value.minimum_outdoor_position < 0 ||
    value.minimum_outdoor_position > 100 ||
    ![...absoluteFields, ...differenceFields, ...temperatureGains].every(
      (key) => Number.isFinite(value[key]),
    ) ||
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
    value.release_delta < 0
  )
    return false;
  const ratio = value.temperature_unit === "degF" ? 5 / 9 : 1;
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
    )
  );
}
const profileLimits = {
  temperature_celsius: [-50, 100],
  difference_celsius: [0, 100],
  gain_per_celsius: [0, 1800000],
  percent: [0, 100],
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
    value.format !== "bms.unit-ventilator-cycle3-wizard-catalog" ||
    value.version !== 1 ||
    value.profile?.profile !== UV_PROFILE ||
    value.profile_sha256 !== UV_PROFILE_SHA ||
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
    !object(value.defaults) ||
    value.defaults.condensate_policy !== "" ||
    !choicesValid({
      ...value.defaults,
      condensate_policy: "disable-cooling",
    }) ||
    (await blobSha256(new Blob([profileCanonical(value.profile)]))) !==
      UV_PROFILE_SHA
  )
    throw new Error(
      "Unit ventilator Cycle III catalog is malformed or uses an unsupported source profile.",
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
    provenance = program?.metadata?.unit_ventilator_cycle3_wizard;
  if (
    !object(value) ||
    value.format !== "bms.unit-ventilator-cycle3-wizard-preview" ||
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
    provenance?.profile !== UV_PROFILE ||
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
    program.metadata.application !== "occupied-uv-cycle3" ||
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
      "Unit ventilator Cycle III preview does not match these exact choices, ordinary graph, interfaces or source profile.",
    );
  const expectedInputs: Record<string, [string, string, any]> = {
    occupied: ["boolean", "", choices.occupied_default],
    unit_enable: ["boolean", "", choices.unit_enable_default],
    energy_holdoff: ["boolean", "", choices.energy_holdoff_default],
    airflow_proven: ["boolean", "", choices.airflow_proven_default],
    fan_reset: ["boolean", "", choices.fan_reset_default],
    condensate_alarm: ["boolean", "", choices.condensate_alarm_default],
    heating_available: ["boolean", "", choices.heating_available_default],
    cooling_available: ["boolean", "", choices.cooling_available_default],
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
    mixed_air_temperature: [
      "number",
      choices.temperature_unit,
      choices.mixed_air_default,
    ],
    mixed_air_setpoint: [
      "number",
      choices.temperature_unit,
      choices.mixed_air_setpoint,
    ],
  };
  const expectedOutputs: Record<string, [string, string]> = Object.fromEntries([
    ...[
      "raw_run_request",
      "setpoints_valid",
      "temperature_range_valid",
      "control_permitted",
      "fan_starting",
      "fan_ready",
      "fan_fault",
      "reset_accepted",
      "fan_enable",
      "fan_proof_stable",
      "startup_deadline_reached",
      "heating_requested",
      "cooling_requested",
      "heating_active",
      "cooling_active",
      "zone_limit_active",
      "zone_limit_restricting",
      "condensate_inhibits_cooling",
      "condensate_shutdown",
    ].map((id) => [id, ["boolean", ""]]),
    ...["unit_state", "thermal_state"].map((id) => [id, ["number", ""]]),
    ...[
      "heating_demand",
      "cooling_demand",
      "mixed_air_damper_demand",
      "zone_limit_correction",
      "zone_limit_allowed",
      "outdoor_damper",
      "heating_valve",
      "cooling_valve",
    ].map((id) => [id, ["number", "%"]]),
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
      "Unit ventilator Cycle III input/output choices, declared units/defaults or graph eligibility are inconsistent.",
    );
  return value;
}
export function unitResult(
  value: any,
  original: Data,
  temperature_unit: string,
  catalog: Data,
) {
  if (
    !object(value) ||
    value.profile_sha256 !== catalog.profile_sha256 ||
    !hash(value.choices_sha256) ||
    !hash(value.source_choices_sha256) ||
    !sourceEqual(value.source_choices, original) ||
    !choicesValid(value.choices) ||
    value.choices.temperature_unit !== temperature_unit
  )
    throw new Error(
      "Unit ventilator Cycle III unit conversion belongs to another source draft/profile.",
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
  expected.temperature_unit = temperature_unit;
  // Match converter binary64 operation order only for the bounded choice DTO.
  // Never project or normalize the actual Program tree or native observations.
  if (
    !keys(value.choices, Object.keys(expected)) ||
    !Object.keys(expected).every((key) =>
      Object.is(expected[key], value.choices[key]),
    )
  )
    throw new Error(
      "Unit ventilator Cycle III conversion changed identity/flags/timing or failed coupled absolute/delta/inverse-gain conversion.",
    );
  return value.choices;
}
