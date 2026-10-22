import {
  executionNumber,
  isSourceNumber,
  parseExecutionJSON,
  parseSourceJSON,
  sourceNumber,
  type SourceNumber,
} from "./programSource";

export type BacnetCommandIntent = SourceNumber | string | boolean;
export type BacnetCommandRequest = {
  address: string;
  object_id: string;
  priority: number;
  value: BacnetCommandIntent;
};

/** Bare enum labels are explicit strings, never a fallback after numeric refusal. */
export function parseBacnetCommandIntent(text: string): BacnetCommandIntent {
  const token = text.trim();
  if (!token || text.length > 4096)
    throw new Error("Command value must contain 1..4096 characters.");
  if (/^[+-]?(?:nan|infinity)$/i.test(token))
    throw new Error("Command value requires a finite number.");
  const jsonLike =
    /^[\[\{"+\-.0-9]/.test(token) || /^(?:true|false|null)(?:\s|$)/.test(token);
  if (!jsonLike) return text;
  let value: unknown;
  try {
    value = parseExecutionJSON(text);
  } catch (error) {
    throw new Error("Command value refused: " + String(error));
  }
  if (typeof value === "number") return sourceNumber(token);
  if (typeof value === "string" || typeof value === "boolean") return value;
  throw new Error(
    "Command value must be a finite numeric scalar, string or Boolean; no null, array or object.",
  );
}

/** Check the original response tokens before making its opaque apply token usable. */
export function verifyBacnetCommandPlan(
  request: BacnetCommandRequest,
  receipt: any,
  text: string,
): void {
  const source = parseSourceJSON(text);
  if (
    !source ||
    typeof source !== "object" ||
    Array.isArray(source) ||
    !receipt ||
    receipt.address !== request.address ||
    receipt.object !== request.object_id ||
    receipt.priority !== request.priority ||
    source.address !== request.address ||
    source.object !== request.object_id ||
    !isSourceNumber(source.priority) ||
    source.priority.token !== String(request.priority) ||
    typeof receipt.token !== "string" ||
    !receipt.token.length ||
    receipt.token.length > 128 ||
    source.token !== receipt.token
  )
    throw new Error(
      "Command preview identity does not match the admitted request.",
    );
  const expected = request.value,
    actual = source.requested_value;
  if (isSourceNumber(expected)) {
    if (!isSourceNumber(actual))
      throw new Error("Command preview requested value type does not match.");
    const integer = !/[.eE]/.test(expected.token);
    if (
      integer !== !/[.eE]/.test(actual.token) ||
      (integer
        ? BigInt(expected.token) !== BigInt(actual.token)
        : !Object.is(
            executionNumber(expected.token),
            executionNumber(actual.token),
          ))
    )
      throw new Error(
        "Command preview requested numeric intent does not match.",
      );
  } else if (typeof actual !== typeof expected || actual !== expected)
    throw new Error("Command preview requested scalar intent does not match.");
}
