type Property = { status?: string; value?: unknown; display_label?: string };
type Properties = Record<string, Property | undefined>;

function valueOf(properties: Properties, name: string) {
  const row = properties[name];
  if (row?.status !== "ok") return undefined;
  const value = row.value;
  return value &&
    typeof value === "object" &&
    "native_datatype" in value &&
    "value" in value
    ? value.value
    : value;
}

const engineeringUnits: Record<string, string> = {
  "degrees-fahrenheit": "°F",
  "degrees-celsius": "°C",
  "cubic-feet-per-minute": "CFM",
  "inches-of-water": "in. w.c.",
  percent: "%",
  seconds: "s",
  "no-units": "",
};

export function logicReadingUnit(properties: Properties): string {
  const row = properties.units;
  if (row?.status !== "ok" || !row.value || typeof row.value !== "object")
    return "";
  const unit = row.value;
  if (
    !("native_datatype" in unit) ||
    unit.native_datatype !== "EngineeringUnits"
  )
    return "";
  if (row.display_label) return row.display_label;
  if (
    "known" in unit &&
    unit.known === true &&
    "name" in unit &&
    typeof unit.name === "string"
  ) {
    return engineeringUnits[unit.name] ?? unit.name.replaceAll("-", " ");
  }
  return "value" in unit && typeof unit.value === "number"
    ? `unit ${unit.value}`
    : "";
}

export function logicReadingConditions(properties: Properties): string[] {
  const flags = valueOf(properties, "status-flags");
  const complete =
    Array.isArray(flags) &&
    flags.length === 4 &&
    flags.every((f) => typeof f === "boolean" || f === 0 || f === 1);
  const [alarm, fault, overridden, outOfService] = complete ? flags : [];
  const reliability = valueOf(properties, "reliability");
  const conditions: string[] = [];
  if (outOfService || valueOf(properties, "out-of-service") === true)
    conditions.push("Out of service");
  if (fault || (typeof reliability === "number" && reliability !== 0))
    conditions.push("Fault");
  if (overridden) conditions.push("Overridden");
  if (alarm) conditions.push("In alarm");
  if (!complete) conditions.push("Status flags unavailable");
  return conditions;
}
