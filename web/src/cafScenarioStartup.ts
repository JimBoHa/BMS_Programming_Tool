import { stable, importProfile, type Profile } from "./cafSimulationProfile";
export type ScenarioInput = {
  id: string;
  ref: string;
  property_id: string;
  class_id: string;
  class_version: string;
  name: string;
  native_type: string;
  units_native: unknown;
  unit_status: string;
  initial_value: string;
  enum_representation?: {
    attributes: Record<string, string>;
    maximum_code: number;
    enum_semantics_verified: false;
  };
};
export type ScenarioSample = { value: string; quality: string };
export type ScenarioEvent = {
  time: number;
  values: Record<string, ScenarioSample>;
};
export type InputScenario = {
  format: string;
  version: number;
  source_sha256: string;
  profile_sha256: string;
  inputs: ScenarioInput[];
  name: string;
  description: string;
  duration: number;
  dt: number;
  events: ScenarioEvent[];
};
const object = (value: any) =>
  !!value && typeof value === "object" && !Array.isArray(value);
const keys = (value: any, wanted: string[]) =>
  object(value) && Object.keys(value).sort().join() === wanted.sort().join();
const text = (value: any) =>
  typeof value === "string" &&
  value.length <= 128 &&
  !/[\uD800-\uDFFF]/u.test(value);
const seconds = (value: any, max = 86400) =>
  typeof value === "number" &&
  Number.isFinite(value) &&
  value >= 0 &&
  value <= max;
const qualities = [
  "good",
  "open-circuit",
  "short-circuit",
  "unreliable",
  "out-of-service",
];
const identity = (row: { ref: string; property_id: string }) =>
  `${row.ref}::simulationProperty:${row.property_id}`;
function fraction(value: number): [bigint, bigint] {
  const [mantissa, power = "0"] = String(value).split("e"),
    parts = mantissa.split(".");
  const shift = Number(power) - (parts[1]?.length || 0),
    digits = BigInt(parts.join(""));
  return shift >= 0
    ? [digits * 10n ** BigInt(shift), 1n]
    : [digits, 10n ** BigInt(-shift)];
}
function boundary(time: number, dt: number) {
  const [a, b] = fraction(time),
    [c, d] = fraction(dt);
  return (a * d) % (b * c) === 0n;
}
function nativeText(value: any, type: string) {
  if (!text(value)) return false;
  if (type === "boolean") return ["0", "1", "false", "true"].includes(value);
  if (type === "enum")
    return /^(0|[1-9][0-9]{0,9})$/.test(value) && Number(value) <= 4294967295;
  if (type !== "float") return false;
  const v = value.replace(/^[ \t\r\n]+|[ \t\r\n]+$/g, "");
  if (!/^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$/.test(v))
    return false;
  const rounded = Math.fround(Number(v)),
    nonzero = /[1-9]/.test(v.split(/[eE]/)[0]);
  return Number.isFinite(rounded) && !(nonzero && rounded === 0);
}
/** Project startup input text only; this never executes native controller logic. */
export function scenarioStartupProfile(
  scenario: InputScenario,
  time: number,
  baseline: Profile,
  original: InputScenario,
): Profile {
  if (
    !object(scenario) ||
    !object(original) ||
    ![1, 2].includes(baseline.version) ||
    baseline.format !== "bms.caf-simulation-profile" ||
    scenario.format !== "bms.caf-local-input-scenario" ||
    scenario.version !== baseline.version ||
    original.format !== scenario.format ||
    original.version !== baseline.version ||
    scenario.source_sha256 !== baseline.source_sha256 ||
    original.source_sha256 !== baseline.source_sha256 ||
    !/^[a-f0-9]{64}$/.test(scenario.profile_sha256) ||
    scenario.profile_sha256 !== original.profile_sha256 ||
    !Array.isArray(scenario.inputs) ||
    scenario.inputs.length < 1 ||
    scenario.inputs.length > 256 ||
    stable(scenario.inputs) !== stable(original.inputs) ||
    !Array.isArray(scenario.events) ||
    scenario.events.length > 2000 ||
    new Blob([JSON.stringify(scenario)]).size > 2 * 1024 * 1024 ||
    !seconds(scenario.duration) ||
    scenario.duration === 0 ||
    !seconds(scenario.dt, 60) ||
    scenario.dt === 0 ||
    !seconds(time, scenario.duration)
  )
    throw new Error(
      "Startup scenario differs from the selected source or bounded input contract.",
    );
  const eligible = baseline.entries.filter(
    (row) =>
      row.editable &&
      row.kind === "simulationProperty" &&
      row.property_id === "3113" &&
      row.class_version === "1.0" &&
      ((row.class_id === "526" && row.native_type === "float") ||
        (row.class_id === "530" && row.native_type === "boolean") ||
        (baseline.version === 2 &&
          row.class_id === "528" &&
          row.native_type === "enum" &&
          row.enum_semantics_verified === false &&
          row.maximum_code === 4294967295)),
  );
  if (eligible.length !== scenario.inputs.length)
    throw new Error("Startup scenario inputs differ from the original CAF.");
  const definitions = new Map<string, ScenarioInput>(),
    values = new Map<string, ScenarioSample>();
  for (let i = 0; i < eligible.length; i++) {
    const row = eligible[i],
      input = scenario.inputs[i];
    if (
      !object(input) ||
      input.id !== identity(row) ||
      input.ref !== row.ref ||
      input.property_id !== row.property_id ||
      input.class_id !== row.class_id ||
      input.class_version !== row.class_version ||
      input.name !== row.name ||
      input.native_type !== row.native_type ||
      input.initial_value !== row.old ||
      definitions.has(input.id) ||
      !nativeText(input.initial_value, input.native_type)
    )
      throw new Error("Startup scenario inputs differ from the original CAF.");
    if (
      input.native_type === "enum" &&
      stable(input.enum_representation) !==
        stable({
          attributes: row.attributes,
          maximum_code: 4294967295,
          enum_semantics_verified: false,
        })
    )
      throw new Error(
        "Startup Enum representation differs from the original CAF.",
      );
    definitions.set(input.id, input);
    values.set(input.id, { value: input.initial_value, quality: "good" });
  }
  let previous = -1,
    atEvent = false;
  for (const event of scenario.events) {
    if (
      !keys(event, ["time", "values"]) ||
      !seconds(event.time, scenario.duration) ||
      event.time <= previous ||
      !object(event.values) ||
      !Object.keys(event.values).length
    )
      throw new Error("Startup scenario event order or shape is unsupported.");
    previous = event.time;
    if (event.time === time) atEvent = true;
    for (const [id, sample] of Object.entries(event.values)) {
      const input = definitions.get(id);
      if (
        !input ||
        !keys(sample, ["value", "quality"]) ||
        !nativeText(sample.value, input.native_type) ||
        !qualities.includes(sample.quality)
      )
        throw new Error(
          "Startup scenario sample does not match its original input.",
        );
      if (event.time <= time) values.set(id, { ...sample });
    }
  }
  if (time !== scenario.duration && !atEvent && !boundary(time, scenario.dt))
    throw new Error("Choose an exact selected scenario frame.");
  if ([...values.values()].some((sample) => sample.quality !== "good"))
    throw new Error(
      "Only an all-good selected scenario frame can prepare native startup values.",
    );
  return {
    ...baseline,
    entries: baseline.entries.map((row) => ({
      ...row,
      value: values.get(identity(row))?.value ?? row.old,
    })),
  };
}
export function admitStartupProfile(
  candidate: unknown,
  expected: Profile,
  baseline: Profile,
) {
  const profile = importProfile(candidate, baseline);
  if (stable(profile) !== stable(expected))
    throw new Error(
      "Startup profile differs from the selected scenario frame.",
    );
  return profile;
}
