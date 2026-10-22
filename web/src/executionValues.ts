import { sourceJsonDocument } from "./api";
import {
  executionNumber,
  executionSourceTree,
  isSourceNumber,
  projectSourceDocument,
} from "./programSource";

// Only declared signal-value slots use the execution profile. Structural fields,
// including unknown fields, still pass through the default safe DTO projector.
function displayValues(value: any): any {
  if (isSourceNumber(value)) return executionNumber(value.token);
  if (Array.isArray(value)) return value.map(displayValues);
  if (value && typeof value === "object")
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [key, displayValues(item)]),
    );
  return value;
}
function snapshots(programs: any) {
  if (!programs || typeof programs !== "object" || Array.isArray(programs))
    return programs;
  return Object.fromEntries(
    Object.entries(programs).map(([alias, raw]: [string, any]) => {
      const result = { ...raw };
      for (const key of ["values", "outputs", "forces", "computed"])
        if (Object.hasOwn(result, key))
          result[key] = displayValues(result[key]);
      return [alias, result];
    }),
  );
}
/** Narrow group response projection: original live inputs/initials, projected display DTOs. */
export function projectGroupExecutionDocument(raw: any): any {
  const definition = raw.definition || raw;
  const maskedDefinition = { ...definition };
  if (Array.isArray(definition.links))
    maskedDefinition.links = definition.links.map((link: any) => ({
      ...link,
      initial: undefined,
    }));
  const masked = raw.definition
    ? { ...raw, definition: maskedDefinition }
    : maskedDefinition;
  if (Object.hasOwn(raw, "external_inputs")) masked.external_inputs = undefined;
  if (raw.programs && !Array.isArray(raw.programs))
    masked.programs = snapshots(raw.programs);
  if (Array.isArray(raw.history))
    masked.history = raw.history.map((row: any) => ({
      ...row,
      programs: snapshots(row.programs),
      inputs: displayValues(row.inputs),
    }));
  if (Array.isArray(raw.failures))
    masked.failures = raw.failures.map((row: any) => ({
      ...row,
      inputs: displayValues(row.inputs),
    }));
  const projected = projectSourceDocument(masked);
  const projectedDefinition = projected.definition || projected;
  if (Array.isArray(definition.links))
    projectedDefinition.links = definition.links.map(
      (link: any, index: number) => ({
        ...projectedDefinition.links[index],
        initial: executionSourceTree(link.initial),
      }),
    );
  if (Object.hasOwn(raw, "external_inputs"))
    projected.external_inputs = executionSourceTree(raw.external_inputs);
  return projected;
}
export async function groupSourceApi(path: string, body?: unknown) {
  return (await sourceJsonDocument(path, body, projectGroupExecutionDocument))
    .data;
}
