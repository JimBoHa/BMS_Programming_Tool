import { projectSourceDocument, sourceEqual } from "./programSource";
export type Data = Record<string, any>;
export const ZONE_BASE = "/zone-setpoint-wizard";
export const ZONE_PROFILE = "studio-zone-effective-setpoints/1";
export const ZONE_PROFILE_SHA =
  "797312f91899f7c9605258fe3ab93e0c657775e7f87c10b41b00d677c10c384c";
export const absoluteFields = [
  "occupied_heating_setpoint",
  "occupied_cooling_setpoint",
  "unoccupied_heating_setpoint",
  "unoccupied_cooling_setpoint",
];
const texts = ["project_id", "name", "model", "firmware", "release_mode"];
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
function population(value: any, mode: string) {
  return mode === "off" || mode === ""
    ? value === null
    : object(value) &&
        keys(value, [
          "offset",
          "entry_seconds",
          "release_seconds",
          "populated_default",
        ]) &&
        Number.isFinite(value.offset) &&
        value.offset > 0 &&
        value.offset <= 180 &&
        ["entry_seconds", "release_seconds"].every(
          (key) =>
            Number.isSafeInteger(value[key]) &&
            value[key] >= 1 &&
            value[key] <= 3600,
        ) &&
        typeof value.populated_default === "boolean";
}
function windowPair(value: any, mode: string) {
  return mode === "off" || mode === ""
    ? value === null
    : object(value) &&
        keys(value, ["heating_setpoint", "cooling_setpoint", "open_default"]) &&
        Number.isFinite(value.heating_setpoint) &&
        Number.isFinite(value.cooling_setpoint) &&
        value.heating_setpoint < value.cooling_setpoint &&
        typeof value.open_default === "boolean";
}
export function choicesValid(value: any, unfinished = false) {
  if (
    !object(value) ||
    !keys(value, [
      ...texts,
      ...absoluteFields,
      "family",
      "temperature_unit",
      "population",
      "population_control",
      "window",
      "window_control",
      "scheduled_occupied_default",
      "scan_seconds",
    ]) ||
    !texts.every((key) => typeof value[key] === "string") ||
    !absoluteFields.every((key) => Number.isFinite(value[key])) ||
    !["universal-runtime", "johnson-fx", "johnson-metasys"].includes(
      value.family,
    ) ||
    !["degF", "degC"].includes(value.temperature_unit) ||
    !["off", "timed-offset", ...(unfinished ? [""] : [])].includes(
      value.population,
    ) ||
    !["off", "absolute-pair", ...(unfinished ? [""] : [])].includes(
      value.window,
    ) ||
    !population(value.population_control, value.population) ||
    !windowPair(value.window_control, value.window) ||
    typeof value.scheduled_occupied_default !== "boolean" ||
    !Number.isSafeInteger(value.scan_seconds) ||
    value.scan_seconds < 1 ||
    value.scan_seconds > 60
  )
    return false;
  if (
    value.population_control &&
    [
      value.population_control.entry_seconds,
      value.population_control.release_seconds,
    ].some((n) => n % value.scan_seconds !== 0)
  )
    return false;
  const pairs = [
    [value.occupied_heating_setpoint, value.occupied_cooling_setpoint],
    [value.unoccupied_heating_setpoint, value.unoccupied_cooling_setpoint],
  ];
  if (value.population_control)
    pairs.push([
      value.occupied_heating_setpoint - value.population_control.offset,
      value.occupied_cooling_setpoint + value.population_control.offset,
    ]);
  if (value.window_control)
    pairs.push([
      value.window_control.heating_setpoint,
      value.window_control.cooling_setpoint,
    ]);
  return pairs.every(
    ([heating, cooling]) =>
      heating < cooling &&
      [heating, cooling].every((n) => {
        const c = value.temperature_unit === "degC" ? n : ((n - 32) * 5) / 9;
        return c >= -50 && c <= 100;
      }),
  );
}
export function catalogResult(value: any) {
  if (
    !object(value) ||
    value.format !== "bms.zone-setpoint-wizard-catalog" ||
    value.version !== 1 ||
    value.profile?.profile !== ZONE_PROFILE ||
    value.profile_sha256 !== ZONE_PROFILE_SHA ||
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
    value.limits.generated_nodes !== 80 ||
    !sourceEqual(value.limits.absolute_celsius, [-50, 100]) ||
    !sourceEqual(value.limits.scan_seconds, [1, 60]) ||
    !sourceEqual(value.limits.timing_seconds, [1, 3600]) ||
    !choicesValid(value.defaults, true) ||
    value.defaults.population !== "" ||
    value.defaults.window !== ""
  )
    throw new Error(
      "Zone-setpoint catalog is malformed or uses an unsupported source profile.",
    );
  for (const unit of ["degF", "degC"]) {
    const branches = value.branch_defaults?.[unit];
    if (
      !object(branches) ||
      !keys(branches, ["population", "window"]) ||
      !object(branches.population) ||
      !keys(branches.population, ["off", "timed-offset"]) ||
      !population(branches.population.off, "off") ||
      !population(branches.population["timed-offset"], "timed-offset") ||
      !object(branches.window) ||
      !keys(branches.window, ["off", "absolute-pair"]) ||
      !windowPair(branches.window.off, "off") ||
      !windowPair(branches.window["absolute-pair"], "absolute-pair")
    )
      throw new Error(
        "Zone-setpoint branch defaults are missing exact unit-qualified choices.",
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
    provenance = program?.metadata?.zone_setpoint_wizard;
  if (
    !object(value) ||
    value.format !== "bms.zone-setpoint-wizard-preview" ||
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
    provenance?.profile !== ZONE_PROFILE ||
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
    program.metadata.application !== "zone-effective-setpoints" ||
    program.metadata.native_deployment_verified !== false ||
    !Array.isArray(program.nodes) ||
    program.nodes.length > 80 ||
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
      "Zone-setpoint preview does not match these exact choices, ordinary graph, interfaces or source profile.",
    );
  const expectedInputs: Record<string, [string, string, any]> = {
    scheduled_occupied: ["boolean", "", choices.scheduled_occupied_default],
  };
  if (choices.population_control)
    expectedInputs.populated = [
      "boolean",
      "",
      choices.population_control.populated_default,
    ];
  if (choices.window_control)
    expectedInputs.window_open = [
      "boolean",
      "",
      choices.window_control.open_default,
    ];
  const expectedOutputs: Record<string, [string, string]> = {
    effective_heating_setpoint: ["number", choices.temperature_unit],
    effective_cooling_setpoint: ["number", choices.temperature_unit],
    occupied_base_selected: ["boolean", ""],
    population_setback_ready: ["boolean", ""],
    population_offset_applied: ["boolean", ""],
    window_override_active: ["boolean", ""],
    applied_population_offset: ["number", "delta-" + choices.temperature_unit],
    setpoint_profile: ["number", ""],
  };
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
      "Zone-setpoint input/output choices, declared units/defaults or graph eligibility are inconsistent.",
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
      "Zone-setpoint unit conversion belongs to another source draft/profile.",
    );
  const expected = structuredClone(original);
  if (unit !== original.temperature_unit) {
    const absolute = (n: number) =>
      unit === "degC" ? ((n - 32) * 5) / 9 : (n * 9) / 5 + 32;
    for (const key of absoluteFields) expected[key] = absolute(expected[key]);
    if (expected.window_control)
      for (const key of ["heating_setpoint", "cooling_setpoint"])
        expected.window_control[key] = absolute(expected.window_control[key]);
    if (expected.population_control)
      expected.population_control.offset *= unit === "degC" ? 5 / 9 : 9 / 5;
  }
  expected.temperature_unit = unit;
  // These bounded business DTOs use the same binary64 operation order as the
  // backend converter. Do not round tiny positive offsets or touch Program atoms.
  function equal(a: any, b: any): boolean {
    if (typeof a === "number" && typeof b === "number") return a === b;
    if (object(a))
      return (
        object(b) &&
        keys(b, Object.keys(a)) &&
        Object.keys(a).every((key) => equal(a[key], b[key]))
      );
    return a === b;
  }
  if (!equal(expected, value.choices))
    throw new Error(
      "Zone-setpoint conversion changed flags/timing/identity or failed coupled absolute/delta conversion.",
    );
  return value.choices;
}
