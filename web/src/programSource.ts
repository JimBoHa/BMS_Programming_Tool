import type { Program } from "./types";

/** Program source values are not JavaScript Numbers: their JSON token is identity. */
const PROGRAM = Symbol("exact Program source");
const MAX_BYTES = 8 * 1024 * 1024,
  MAX_ITEMS = 200_000,
  MAX_DEPTH = 64;
const NUMBER = /^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?$/;
const CLONE_GUARD = () => {
  throw new Error("Exact Program numbers require cloneSource");
};
export class SourceNumber {
  private readonly cloneGuard = CLONE_GUARD;
  readonly token: string;
  constructor(token: string) {
    if (
      token.length > 4096 ||
      !NUMBER.test(token) ||
      (/[.eE]/.test(token) && !Number.isFinite(Number(token)))
    )
      throw new Error("Invalid or non-finite Program numeric token");
    this.token = token;
    Object.freeze(this);
  }
  toString() {
    return this.token;
  }
  toJSON(): never {
    throw new Error(
      "Exact Program numbers require the Program source serializer",
    );
  }
  [Symbol.toPrimitive](hint: string) {
    if (hint === "string") return this.token;
    throw new Error(
      "Exact Program numbers cannot be implicitly converted to JavaScript Number",
    );
  }
}
export const isSourceNumber = (value: unknown): value is SourceNumber =>
  value instanceof SourceNumber;
export const numericToken = (value: unknown): string =>
  isSourceNumber(value)
    ? value.token
    : typeof value === "number" && Object.is(value, -0)
      ? "-0.0"
      : String(value);
export const sourceNumber = (text: string) => new SourceNumber(text.trim());
export function markProgram<T extends Program>(program: T): T {
  Object.defineProperty(program, PROGRAM, { value: true, enumerable: true });
  return program;
}
export const isExactProgram = (value: any): value is Program =>
  !!value && value[PROGRAM] === true;
function programShape(value: any) {
  return (
    value &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    "schema_version" in value &&
    "id" in value &&
    Array.isArray(value.nodes) &&
    Array.isArray(value.edges) &&
    value.target &&
    typeof value.target === "object"
  );
}
function checkBudget(depth: number, remaining: { n: number }) {
  if (depth > MAX_DEPTH || --remaining.n < 0)
    throw new Error("Program source exceeds its depth or value bound");
}
/** Strict bounded JSON parser captures numeric tokens before any binary64 conversion. */
export function parseSourceJSON(text: string): any {
  if (!text.length || new TextEncoder().encode(text).length > MAX_BYTES)
    throw new Error("Program source must be between 1 byte and 8 MiB");
  let i = 0;
  const budget = { n: MAX_ITEMS };
  const ws = () => {
    while (/[\x20\t\r\n]/.test(text[i] || "!") && i < text.length) i++;
  };
  function string(): string {
    const start = i++;
    while (i < text.length) {
      const char = text[i++];
      if (char === "\\") {
        i++;
        continue;
      }
      if (char === '"') {
        const result = JSON.parse(text.slice(start, i));
        if (
          /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/.test(
            result,
          )
        )
          throw new Error("Program strings require valid Unicode");
        return result;
      }
      if (char.charCodeAt(0) < 32) break;
    }
    throw new Error("Unterminated JSON string");
  }
  function value(depth: number): any {
    checkBudget(depth, budget);
    ws();
    if (text[i] === '"') return string();
    if (text[i] === "{" || text[i] === "[") {
      const object = text[i++] === "{",
        result: any = object ? {} : [],
        keys = new Set<string>();
      ws();
      if (text[i] === (object ? "}" : "]")) {
        i++;
        return result;
      }
      while (true) {
        ws();
        if (object) {
          if (text[i] !== '"') throw new Error("Expected JSON object key");
          const key = string();
          if (keys.has(key))
            throw new Error("Duplicate JSON object key: " + key);
          keys.add(key);
          ws();
          if (text[i++] !== ":") throw new Error("Expected JSON colon");
          Object.defineProperty(result, key, {
            value: value(depth + 1),
            enumerable: true,
            writable: true,
            configurable: true,
          });
        } else result.push(value(depth + 1));
        ws();
        const next = text[i++];
        if (next === (object ? "}" : "]")) return result;
        if (next !== ",") throw new Error("Expected JSON comma");
      }
    }
    for (const [token, result] of [
      ["true", true],
      ["false", false],
      ["null", null],
    ] as const) {
      if (text.startsWith(token, i)) {
        i += token.length;
        return result;
      }
    }
    const match = /^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/.exec(
      text.slice(i),
    );
    if (!match) throw new Error("Expected JSON value");
    i += match[0].length;
    return new SourceNumber(match[0]);
  }
  const result = value(0);
  ws();
  if (i !== text.length) throw new Error("Unexpected trailing JSON data");
  return result;
}
/** Never uses a replacer or numeric placeholders; strings cannot become source tokens. */
export function sourceStringify(
  value: any,
  space = 0,
  byteLimit = MAX_BYTES,
): string {
  const budget = { n: MAX_ITEMS },
    active = new Set<any>();
  const width = Math.max(0, Math.min(10, space));
  function emit(v: any, depth: number, array = false): string | undefined {
    checkBudget(depth, budget);
    if (isSourceNumber(v)) return v.token;
    if (v === null) return "null";
    if (typeof v === "number") {
      if (!Number.isFinite(v)) throw new Error("Non-finite JSON number");
      return Object.is(v, -0)
        ? "-0.0"
        : Number.isInteger(v)
          ? BigInt(v).toString()
          : JSON.stringify(v);
    }
    if (typeof v === "string" || typeof v === "boolean")
      return JSON.stringify(v);
    if (v === undefined) return array ? "null" : undefined;
    if (typeof v !== "object")
      throw new Error("Unsupported Program source value");
    if (active.has(v)) throw new Error("Cyclic Program source");
    active.add(v);
    const items: string[] = [];
    if (Array.isArray(v))
      for (const item of v) items.push(emit(item, depth + 1, true)!);
    else
      for (const key of Object.keys(v)) {
        const item = emit(v[key], depth + 1);
        if (item !== undefined)
          items.push(JSON.stringify(key) + (width ? ": " : ":") + item);
      }
    active.delete(v);
    const open = Array.isArray(v) ? "[" : "{",
      close = Array.isArray(v) ? "]" : "}";
    return items.length && width
      ? open +
          "\n" +
          " ".repeat((depth + 1) * width) +
          items.join(",\n" + " ".repeat((depth + 1) * width)) +
          "\n" +
          " ".repeat(depth * width) +
          close
      : open + items.join(",") + close;
  }
  const result = emit(value, 0);
  if (
    result === undefined ||
    new TextEncoder().encode(result).length > byteLimit
  )
    throw new Error("Program source exceeds its encoded byte bound");
  return result;
}
/** Respect the existing global 9 MiB request cap, including source-envelope escaping. */
export const sourceRequestStringify = (value: any) =>
  sourceStringify(value, 0, 9 * 1024 * 1024);
function numberProjection(value: any, integer: boolean, field: string): number {
  const token = numericToken(value),
    n = Number(token);
  if (
    !Number.isFinite(n) ||
    (integer && (!Number.isSafeInteger(n) || BigInt(token) !== BigInt(n)))
  )
    throw new Error("Unsupported browser numeric projection at " + field);
  return n;
}
export function hydrateProgram(raw: any): Program {
  if (!programShape(raw))
    throw new Error("Response does not contain a Program source");
  for (const key of ["schema_version", "revision"])
    raw[key] = numberProjection(raw[key], true, key);
  raw.scan_seconds = numberProjection(raw.scan_seconds, false, "scan_seconds");
  for (const key of ["max_nodes", "physical_inputs", "physical_outputs"])
    if (raw.target[key] != null)
      raw.target[key] = numberProjection(
        raw.target[key],
        true,
        "target." + key,
      );
  raw.nodes.forEach((node: any) => {
    node.x = numberProjection(node.x, false, "node.x");
    node.y = numberProjection(node.y, false, "node.y");
  });
  return markProgram(raw);
}
/** DTO fields are projected explicitly; opaque params/metadata of each Program remain atoms. */
export function projectSourceDocument(value: any): any {
  if (isSourceNumber(value))
    return numberProjection(value, !/[.eE]/.test(value.token), "response");
  if (programShape(value)) return hydrateProgram(value);
  if (Array.isArray(value)) return value.map(projectSourceDocument);
  if (value && typeof value === "object")
    return Object.fromEntries(
      Object.entries(value).map(([k, v]) => [k, projectSourceDocument(v)]),
    );
  return value;
}
export const parseSourceDocument = (text: string) =>
  projectSourceDocument(parseSourceJSON(text));
export function cloneSource<T>(value: T): T {
  if (isSourceNumber(value) || value === null || typeof value !== "object")
    return value;
  const result: any = Array.isArray(value)
    ? value.map(cloneSource)
    : Object.fromEntries(
        Object.entries(value).map(([k, v]) => [k, cloneSource(v)]),
      );
  if (isExactProgram(value)) markProgram(result);
  return result;
}
export function sourceEqual(a: any, b: any): boolean {
  const ordered = (v: any): any =>
    isSourceNumber(v) || !v || typeof v !== "object"
      ? v
      : Array.isArray(v)
        ? v.map(ordered)
        : Object.fromEntries(
            Object.keys(v)
              .sort()
              .map((k) => [k, ordered(v[k])]),
          );
  return sourceStringify(ordered(a)) === sourceStringify(ordered(b));
}
async function sha256(text: string) {
  return Array.from(
    new Uint8Array(
      await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text)),
    ),
    (b) => b.toString(16).padStart(2, "0"),
  ).join("");
}
export async function prepareSourceRequest(value: any): Promise<any> {
  const budget = { n: MAX_ITEMS },
    active = new Set<any>();
  async function visit(item: any, depth: number): Promise<any> {
    checkBudget(depth, budget);
    if (isExactProgram(item)) {
      const source = sourceStringify(item);
      return {
        format: "bms.program-source/1",
        source_json: source,
        source_sha256: await sha256(source),
        program_id: item.id,
        revision_text: String(item.revision),
      };
    }
    if (programShape(item))
      throw new Error(
        "Unmarked Program projection refused; reload its exact source",
      );
    if (isSourceNumber(item) || item === null || typeof item !== "object")
      return item;
    if (active.has(item)) throw new Error("Cyclic Program request");
    active.add(item);
    const output: any = Array.isArray(item) ? [] : {};
    for (const [key, child] of Object.entries(item))
      Object.defineProperty(output, key, {
        value: await visit(child, depth + 1),
        enumerable: true,
        writable: true,
        configurable: true,
      });
    active.delete(item);
    return output;
  }
  return visit(value, 0);
}
export async function decodeSourceResponse(envelope: any): Promise<any> {
  if (
    envelope?.format !== "bms.program-source-response/1" ||
    typeof envelope.source_json !== "string"
  )
    throw new Error("Invalid exact Program source response");
  const raw = parseSourceJSON(envelope.source_json);
  if ((await sha256(envelope.source_json)) !== envelope.source_sha256)
    throw new Error("Invalid exact Program source response hash");
  if (envelope.kind === "blocks") {
    if (
      !Array.isArray(raw) ||
      !Array.isArray(envelope.programs) ||
      envelope.programs.length
    )
      throw new Error("Invalid block source response");
    return raw.map((block: any) => ({
      ...projectSourceDocument({ ...block, parameters: undefined }),
      parameters: block.parameters,
    }));
  }
  if (envelope.kind !== "programs" || !Array.isArray(envelope.programs))
    throw new Error("Unknown exact Program response profile");
  const roots = new Map<string, any>();
  function collect(item: any, path: (string | number)[]) {
    if (programShape(item)) {
      roots.set(JSON.stringify(path), item);
      return;
    }
    if (Array.isArray(item))
      item.forEach((child, index) => collect(child, [...path, index]));
    else if (item && typeof item === "object" && !isSourceNumber(item))
      for (const [key, child] of Object.entries(item))
        collect(child, [...path, key]);
  }
  collect(raw, []);
  for (const descriptor of envelope.programs) {
    if (
      !Array.isArray(descriptor.path) ||
      descriptor.path.some(
        (key: any) => typeof key !== "string" && !Number.isSafeInteger(key),
      ) ||
      descriptor.canonical_format !== "canonical-json/1" ||
      !/^[a-f0-9]{64}$/.test(descriptor.canonical_sha256)
    )
      throw new Error("Invalid Program source descriptor");
    const key = JSON.stringify(descriptor.path),
      program = roots.get(key);
    if (
      !program ||
      program.id !== descriptor.program_id ||
      numericToken(program.revision) !== descriptor.revision_text
    )
      throw new Error("Program source identity/path mismatch");
    roots.delete(key);
  }
  if (roots.size)
    throw new Error("Program source descriptor coverage mismatch");
  return projectSourceDocument(raw);
}
/** Explicit execution boundary: never round an integer typed by an operator. */
export function executionNumber(text: string): number {
  const atom = sourceNumber(text),
    n = Number(atom.token);
  if (!Number.isFinite(n))
    throw new Error("Execution requires a finite binary64 number");
  if (!/[.eE]/.test(atom.token) && BigInt(atom.token) !== BigInt(n))
    throw new Error(
      "This integer is not exactly representable by the execution numeric profile",
    );
  return n;
}
export function parseExecutionJSON(text: string): any {
  const project = (v: any): any =>
    isSourceNumber(v)
      ? executionNumber(v.token)
      : Array.isArray(v)
        ? v.map(project)
        : v && typeof v === "object"
          ? Object.fromEntries(
              Object.entries(v).map(([k, item]) => [k, project(item)]),
            )
          : v;
  return project(parseSourceJSON(text));
}
/** Finite live-input edits report refusal without dispatching a rounded value. */
export function executionInput(
  event: { currentTarget: HTMLInputElement },
  apply: (value: number) => void,
): void {
  try {
    const value = executionNumber(event.currentTarget.value);
    event.currentTarget.setCustomValidity("");
    apply(value);
  } catch (error) {
    event.currentTarget.setCustomValidity(String(error));
    event.currentTarget.reportValidity();
  }
}
