import { projectSourceDocument, sourceEqual } from "./programSource";
export type Data = Record<string, any>;
export const AHU_BASE = "/masd-ahu-wizard";
export const AHU_PROFILE = "studio-masd-ahu/1";
export const AHU_PROFILE_SHA =
  "d72ba0e20b94b341a4c75d426d5b9f888a80494d5dd0472654d35d23e6e450d5";
export const absoluteFields = ["sat_default", "sat_setpoint"];
export const differenceFields = [
  "temperature_band",
  "entry_delta",
  "release_delta",
];
export const gainFields = [
  "heating_kp",
  "heating_ki",
  "cooling_kp",
  "cooling_ki",
];
export const timingFields = [
  "proof_seconds",
  "stabilize_seconds",
  "startup_timeout_seconds",
  "recovery_timeout_seconds",
  "release_seconds",
  "scan_seconds",
];
export const defaultFlags = [
  "occupied_default",
  "unit_enable_default",
  "energy_holdoff_default",
  "fan_proven_default",
  "fan_reset_default",
];
export const variableFields = [
  "pressure_default_pa",
  "setpoint_pa",
  "minimum_percent",
  "startup_percent",
  "maximum_percent",
  "kp",
  "ki",
];
export const economizerNumbers = [
  "oa_default",
  "enable_below",
  "disable_above",
  "kp",
  "ki",
  "assist_seconds",
  "high_threshold_percent",
];
const nullableEconomizer = [
  "ra_default",
  "differential_on",
  "differential_off",
];
const texts = ["project_id", "name", "model", "firmware", "release_mode"];
const numbers = [
  ...absoluteFields,
  ...differenceFields,
  ...gainFields,
  "minimum_oa_percent",
  "low_threshold_percent",
];
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
function variable(value: any) {
  return (
    object(value) &&
    keys(value, variableFields) &&
    variableFields.every((key) => Number.isFinite(value[key]))
  );
}
function economizer(value: any, mode: string) {
  return mode === "off"
    ? value === null
    : object(value) &&
        keys(value, [
          ...economizerNumbers,
          ...nullableEconomizer,
          "enable_default",
        ]) &&
        economizerNumbers.every((key) => Number.isFinite(value[key])) &&
        Number.isSafeInteger(value.assist_seconds) &&
        typeof value.enable_default === "boolean" &&
        nullableEconomizer.every((key) =>
          mode === "differential-drybulb"
            ? Number.isFinite(value[key])
            : value[key] === null,
        );
}
export function choicesValid(value: any, unfinished = false) {
  return (
    object(value) &&
    keys(value, [
      ...texts,
      ...numbers,
      ...timingFields,
      ...defaultFlags,
      "family",
      "temperature_unit",
      "fan",
      "variable_fan",
      "economizer",
      "economizer_control",
    ]) &&
    texts.every((key) => typeof value[key] === "string") &&
    numbers.every((key) => Number.isFinite(value[key])) &&
    timingFields.every((key) => Number.isSafeInteger(value[key])) &&
    defaultFlags.every((key) => typeof value[key] === "boolean") &&
    ["universal-runtime", "johnson-fx", "johnson-metasys"].includes(
      value.family,
    ) &&
    ["degF", "degC"].includes(value.temperature_unit) &&
    ["constant-speed", "variable-speed", ...(unfinished ? [""] : [])].includes(
      value.fan,
    ) &&
    (value.fan === "variable-speed"
      ? variable(value.variable_fan)
      : value.variable_fan === null) &&
    [
      "off",
      "fixed-drybulb",
      "differential-drybulb",
      ...(unfinished ? [""] : []),
    ].includes(value.economizer) &&
    (value.economizer === ""
      ? value.economizer_control === null
      : economizer(value.economizer_control, value.economizer))
  );
}
export function catalogResult(value: any) {
  if (
    !object(value) ||
    value.format !== "bms.masd-ahu-wizard-catalog" ||
    value.version !== 1 ||
    value.profile?.profile !== AHU_PROFILE ||
    value.profile_sha256 !== AHU_PROFILE_SHA ||
    value.profile.source?.document !== "LIT-12011147" ||
    value.profile.source?.edition !== "18.0" ||
    value.profile.source?.sha256 !==
      "68935362c85cb1879dc033cc701115e8ea7c4ecb26748f21a9ceaf0454f82903" ||
    typeof value.profile.source?.url !== "string" ||
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
    !sourceEqual(value.profile.limits, value.limits) ||
    value.limits.generated_nodes !== 320 ||
    !sourceEqual(value.limits.scan_seconds, [1, 60]) ||
    !sourceEqual(value.limits.timing_seconds, [1, 3600]) ||
    !choicesValid(value.defaults, true) ||
    value.defaults.fan !== "" ||
    value.defaults.economizer !== ""
  )
    throw new Error(
      "AHU catalog is malformed or uses an unsupported source profile.",
    );
  for (const unit of ["degF", "degC"]) {
    const branches = value.branch_defaults?.[unit];
    if (
      !variable(branches?.variable_fan) ||
      !object(branches.economizers) ||
      !keys(branches.economizers, [
        "off",
        "fixed-drybulb",
        "differential-drybulb",
      ]) ||
      !["off", "fixed-drybulb", "differential-drybulb"].every((mode) =>
        economizer(branches.economizers[mode], mode),
      )
    )
      throw new Error(
        "AHU branch defaults are missing their exact unit-qualified options.",
      );
  }
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
    provenance = program?.metadata?.masd_ahu_wizard;
  if (
    !object(value) ||
    value.format !== "bms.masd-ahu-wizard-preview" ||
    value.version !== 1 ||
    value.profile_sha256 !== catalog.profile_sha256 ||
    !sourceEqual(value.profile, catalog.profile) ||
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
    provenance?.profile !== AHU_PROFILE ||
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
    program.metadata.native_deployment_verified !== false ||
    !Array.isArray(program.nodes) ||
    program.nodes.length > 320 ||
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
      "AHU preview does not match these exact choices, ordinary graph, interfaces or source profile.",
    );
  const expectedInputs: Record<string, [string, string, any]> = {
    occupied: ["boolean", "", choices.occupied_default],
    unit_enable: ["boolean", "", choices.unit_enable_default],
    energy_holdoff: ["boolean", "", choices.energy_holdoff_default],
    fan_proven: ["boolean", "", choices.fan_proven_default],
    fan_reset: ["boolean", "", choices.fan_reset_default],
    sat: ["number", choices.temperature_unit, choices.sat_default],
    sat_setpoint: ["number", choices.temperature_unit, choices.sat_setpoint],
  };
  if (choices.variable_fan) {
    expectedInputs.duct_pressure = [
      "number",
      "Pa",
      choices.variable_fan.pressure_default_pa,
    ];
    expectedInputs.duct_pressure_setpoint = [
      "number",
      "Pa",
      choices.variable_fan.setpoint_pa,
    ];
  }
  if (choices.economizer_control) {
    expectedInputs.outdoor_temperature = [
      "number",
      choices.temperature_unit,
      choices.economizer_control.oa_default,
    ];
    expectedInputs.economizer_enable = [
      "boolean",
      "",
      choices.economizer_control.enable_default,
    ];
    if (choices.economizer === "differential-drybulb")
      expectedInputs.return_temperature = [
        "number",
        choices.temperature_unit,
        choices.economizer_control.ra_default,
      ];
  }
  const expectedOutputs: Record<string, [string, string]> = Object.fromEntries(
    [
      "control_permitted",
      "fan_enable",
      "fan_ready",
      "fan_fault",
      "economizer_available",
      "heating_active_output",
      "mechanical_cooling_active",
      "economizer_active_output",
    ].map((id) => [id, ["boolean", ""]]),
  );
  for (const id of [
    "heating_valve",
    "cooling_valve",
    "mixing_damper",
    ...(choices.variable_fan ? ["fan_speed"] : []),
  ])
    expectedOutputs[id] = ["number", "%"];
  expectedOutputs.ahu_state = ["number", ""];
  if (
    value.inputs.length !== Object.keys(expectedInputs).length ||
    value.inputs.some(
      (r: any) =>
        !expectedInputs[r.id] ||
        !sourceEqual([r.value_type, r.unit, r.default], expectedInputs[r.id]),
    ) ||
    value.outputs.length !== Object.keys(expectedOutputs).length ||
    value.outputs.some(
      (r: any) =>
        !expectedOutputs[r.id] ||
        !sourceEqual([r.value_type, r.unit], expectedOutputs[r.id]),
    ) ||
    value.can_create !==
      !value.diagnostics.some((r: any) => r.level === "error")
  )
    throw new Error(
      "AHU input/output choices, declared units/defaults or graph eligibility are inconsistent.",
    );
  return value;
}
export function unitResult(
  value: any,
  original: Data,
  unit: string,
  catalog: Data,
) {
  if (
    !object(value) ||
    value.profile_sha256 !== catalog.profile_sha256 ||
    !hash(value.choices_sha256) ||
    !hash(value.source_choices_sha256) ||
    !sourceEqual(value.source_choices, original) ||
    !choicesValid(value.choices) ||
    value.choices.temperature_unit !== unit
  )
    throw new Error(
      "AHU unit conversion belongs to another source draft/profile.",
    );
  const expected = structuredClone(original),
    ratio = unit === "degC" ? 5 / 9 : 9 / 5,
    absolute = (v: number) =>
      unit === "degC" ? ((v - 32) * 5) / 9 : (v * 9) / 5 + 32;
  if (unit !== original.temperature_unit) {
    for (const key of absoluteFields) expected[key] = absolute(expected[key]);
    for (const key of differenceFields) expected[key] *= ratio;
    for (const key of gainFields) expected[key] /= ratio;
    if (expected.economizer_control) {
      const e = expected.economizer_control;
      for (const key of [
        "oa_default",
        "ra_default",
        "enable_below",
        "disable_above",
      ])
        if (e[key] !== null) e[key] = absolute(e[key]);
      for (const key of ["differential_on", "differential_off"])
        if (e[key] !== null) e[key] *= ratio;
      for (const key of ["kp", "ki"]) e[key] /= ratio;
    }
  }
  expected.temperature_unit = unit;
  function equal(a: any, b: any): boolean {
    if (typeof a === "number" && typeof b === "number")
      return Math.abs(a - b) <= 1e-10 * Math.max(1, Math.abs(a));
    if (Array.isArray(a))
      return (
        Array.isArray(b) &&
        a.length === b.length &&
        a.every((v, i) => equal(v, b[i]))
      );
    if (object(a))
      return (
        object(b) &&
        keys(b, Object.keys(a)) &&
        Object.keys(a).every((k) => equal(a[k], b[k]))
      );
    return a === b;
  }
  if (!equal(expected, value.choices))
    throw new Error(
      "AHU conversion changed Pa, percent, seconds, flags or failed coupled absolute/delta/inverse-gain conversion.",
    );
  return value.choices;
}
