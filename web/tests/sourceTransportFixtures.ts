/** Test fixture changes retain every unrelated exact Program token. */
import { createHash } from "node:crypto";
import { parseSourceJSON, sourceStringify } from "../src/programSource";
export function sourceFixtureData(value: any): any {
  return value?.format === "bms.program-source-response/1"
    ? parseSourceJSON(value.source_json)
    : value;
}
export function resealSourceFixture(envelope: any, value: any): any {
  if (envelope?.format !== "bms.program-source-response/1") return value;
  const source = sourceStringify(value);
  return {
    ...envelope,
    source_json: source,
    source_sha256: createHash("sha256").update(source).digest("hex"),
  };
}
/** This name-only test projection is never sent back or used to assert numbers. */
export function requestProgram(value: any): any {
  return value?.format === "bms.program-source/1"
    ? JSON.parse(value.source_json)
    : value;
}
