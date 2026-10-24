import { isSourceNumber, numericToken, sourceEqual } from "./programSource";
import type { Block, Program } from "./types";

export type Data = Record<string, any>;
export type ActivityPort = {
  id: string;
  label: string;
  value_type: "number" | "boolean";
  unit: string;
  required?: boolean;
};
export type ActivityBinding = {
  instance_path: string[];
  definition: string;
  output_id: string;
  alias_node_id: string;
  value_type: "number" | "boolean";
  unit: string;
};
export type ActivityBindings = {
  format: "bms.activity-bindings/1";
  profile: Data;
  profile_sha256: string;
  program_id: string;
  program_revision: number;
  source_sha256: string;
  expanded_sha256: string;
  outputs: ActivityBinding[];
};
export const ACTIVITY_BASE = "/activities";
export const ACTIVITY_PROFILE = "studio-activities/2";
// Versioned authored contract. Refresh only after the backend profile freezes.
export const ACTIVITY_PROFILE_SHA =
  "dfb962a09a47517a10892c0c3f30fd41e8e3fb49f4a1a577709b0afec6559568";
export const object = (value: any): value is Data =>
  value !== null && typeof value === "object" && !Array.isArray(value);
export const identifier = (value: any): value is string =>
  typeof value === "string" && /^[A-Za-z][A-Za-z0-9_\-]{0,79}$/.test(value);
export const hash = (value: any): value is string =>
  typeof value === "string" && /^[a-f0-9]{64}$/.test(value);

/** Read one declared control field without projecting opaque Program metadata. */
export function libraryVersion(program: Program): 1 | 2 | null {
  if (!Object.hasOwn(program.metadata, "macros")) return 1;
  const library = program.metadata.macros;
  if (!object(library) || !Object.hasOwn(library, "version")) return null;
  const value = library.version;
  // Preserve the old Literal[1] admission (including true and float1). New v2
  // requires its exact integer token; selecting a view never rewrites a source.
  if (value === true || value === 1) return 1;
  if (value === 2) return 2;
  if (isSourceNumber(value)) {
    const token = numericToken(value);
    if (token === "2") return 2;
    if (Number(token) === 1) return 1;
  }
  return null;
}
export function reusableBase(program: Program): "/macros" | "/activities" {
  const version = libraryVersion(program);
  if (version === 1) return "/macros";
  if (version === 2) return "/activities";
  throw new Error(
    "Unsupported reusable-library version. Keep the original source and choose a supported format explicitly.",
  );
}
export const reusableKind = (kind: string) =>
  kind === "Macro" || kind === "Activity";
export const matchesBlock = (
  block: Block,
  node?: { kind: string; params: Data },
) =>
  !!node &&
  block.kind === node.kind &&
  (!reusableKind(block.kind) ||
    block.parameters.definition === node.params.definition);

export async function sha256Text(text: string) {
  return Array.from(
    new Uint8Array(
      await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text)),
    ),
    (value) => value.toString(16).padStart(2, "0"),
  ).join("");
}
export async function sha256Blob(blob: Blob) {
  return Array.from(
    new Uint8Array(
      await crypto.subtle.digest("SHA-256", await blob.arrayBuffer()),
    ),
    (value) => value.toString(16).padStart(2, "0"),
  ).join("");
}
function profileJSON(value: any): string {
  if (Array.isArray(value)) return "[" + value.map(profileJSON).join(",") + "]";
  if (object(value))
    return (
      "{" +
      Object.keys(value)
        .sort()
        .map((key) => JSON.stringify(key) + ":" + profileJSON(value[key]))
        .join(",") +
      "}"
    );
  if (typeof value === "number" && !Number.isSafeInteger(value))
    throw new Error("Unsupported activity profile number.");
  return JSON.stringify(value);
}
export async function manifestSha256(value: any) {
  // Used only for profiled manifests of strings/Booleans/null and safe integers.
  // Never call this on a Program, parameters or arbitrary operator metadata.
  return sha256Text(profileJSON(value));
}
export async function activityProfile(value: any) {
  if (
    !object(value) ||
    value.profile?.profile !== ACTIVITY_PROFILE ||
    value.profile_sha256 !== ACTIVITY_PROFILE_SHA ||
    (await sha256Text(profileJSON(value.profile))) !== ACTIVITY_PROFILE_SHA
  )
    throw new Error("Unsupported reusable-activity source profile.");
  return value;
}
function port(value: any): value is ActivityPort {
  return (
    object(value) &&
    identifier(value.id) &&
    typeof value.label === "string" &&
    ["number", "boolean"].includes(value.value_type) &&
    typeof value.unit === "string"
  );
}
function diagnostics(value: any): boolean {
  return (
    Array.isArray(value) &&
    value.length <= 20000 &&
    value.every(
      (row: any) =>
        object(row) &&
        ["info", "warning", "error"].includes(row.level) &&
        typeof row.code === "string" &&
        typeof row.message === "string" &&
        (row.node === undefined ||
          row.node === null ||
          typeof row.node === "string"),
    )
  );
}
function definitions(program: Program) {
  const library = program.metadata.macros;
  if (
    libraryVersion(program) !== 2 ||
    !Array.isArray(library?.definitions) ||
    library.definitions.length > 64
  )
    throw new Error(
      "Activity source requires a bounded explicit version-two library.",
    );
  const result = new Map<string, Data>();
  let count = 0;
  for (const definition of library.definitions) {
    if (
      !object(definition) ||
      !identifier(definition.id) ||
      typeof definition.name !== "string" ||
      result.has(definition.id) ||
      !Array.isArray(definition.program?.nodes) ||
      !Array.isArray(definition.program?.edges) ||
      (count += definition.program.nodes.length) > 4000
    )
      throw new Error("Invalid or duplicate activity source definition.");
    result.set(definition.id, definition);
  }
  return result;
}
export function activitySource(program: Program) {
  const library = definitions(program);
  for (const graph of [
    program,
    ...[...library.values()].map((item) => item.program),
  ]) {
    const nodes = new Set<string>();
    for (const node of graph.nodes) {
      if (
        !object(node) ||
        !identifier(node.id) ||
        nodes.has(node.id) ||
        node.kind === "Macro"
      )
        throw new Error(
          "Activity source contains duplicate, unknown or mixed-version nodes.",
        );
      nodes.add(node.id);
      if (
        node.kind === "Activity" &&
        ((node.value_type ?? "number") !== "number" ||
          (node.unit ?? "") !== "" ||
          !object(node.params) ||
          Object.keys(node.params).length !== 1 ||
          !library.has(node.params.definition))
      )
        throw new Error(
          "Activity container or dependency contract is invalid.",
        );
    }
  }
  return library;
}
/** Check every alias against its actual named source Output, not a scalar container. */
export async function activityBindings(
  value: any,
  program: Program,
): Promise<ActivityBindings> {
  await activityProfile(value);
  if (
    value.format !== "bms.activity-bindings/1" ||
    value.program_id !== program.id ||
    value.program_revision !== program.revision ||
    !hash(value.source_sha256) ||
    !hash(value.expanded_sha256) ||
    !Array.isArray(value.outputs) ||
    value.outputs.length > 2000
  )
    throw new Error(
      "Activity bindings do not match the current executable source.",
    );
  const library = definitions(program),
    expected = new Map<
      string,
      { definition: string; port: Data; path: string[] }
    >();
  let instances = 0;
  function visit(graph: Data, path: string[], ancestry: string[]) {
    if (path.length > 8 || !Array.isArray(graph.nodes))
      throw new Error("Activity binding depth or source graph is invalid.");
    for (const node of graph.nodes) {
      if (node.kind !== "Activity") continue;
      const definition = library.get(node.params?.definition),
        next = [...path, node.id];
      if (
        !identifier(node.id) ||
        !definition ||
        ancestry.includes(definition.id) ||
        ++instances > 256
      )
        throw new Error(
          "Activity bindings contain an unresolved or recursive instance.",
        );
      const ports = definition.program.nodes.filter(
        (item: any) => item.kind === "Output",
      );
      if (ports.length < 1 || ports.length > 32)
        throw new Error("Activity output count is invalid.");
      for (const output of ports) {
        if (
          !identifier(output.id) ||
          !["number", "boolean"].includes(output.value_type ?? "number") ||
          typeof (output.unit ?? "") !== "string"
        )
          throw new Error("Invalid declared activity Output.");
        const key = JSON.stringify([...next, output.id]);
        if (expected.has(key))
          throw new Error("Duplicate activity output binding.");
        expected.set(key, {
          definition: definition.id,
          port: output,
          path: next,
        });
      }
      visit(definition.program, next, [...ancestry, definition.id]);
    }
  }
  visit(program, [], []);
  if (value.outputs.length !== expected.size)
    throw new Error("Activity output binding coverage is incomplete.");
  const aliases = new Set<string>();
  for (const row of value.outputs) {
    if (
      !object(row) ||
      !Array.isArray(row.instance_path) ||
      !row.instance_path.every(identifier) ||
      !identifier(row.output_id)
    )
      throw new Error("Invalid activity output binding identity.");
    const key = JSON.stringify([...row.instance_path, row.output_id]),
      declared = expected.get(key);
    const alias =
      "ao2_" +
      (
        await sha256Text(
          JSON.stringify(["output", ...row.instance_path, row.output_id]),
        )
      ).slice(0, 24);
    if (
      !declared ||
      row.definition !== declared.definition ||
      row.value_type !== (declared.port.value_type ?? "number") ||
      row.unit !== (declared.port.unit ?? "") ||
      row.alias_node_id !== alias ||
      aliases.has(alias)
    )
      throw new Error(
        "Activity output alias, type or unit differs from the declared source port.",
      );
    expected.delete(key);
    aliases.add(alias);
  }
  return value;
}
export async function activityCatalog(value: any, program: Program) {
  await activityProfile(value);
  if (
    value.format !== "bms.activities-catalog" ||
    value.version !== 2 ||
    !hash(value.source_sha256) ||
    !Array.isArray(value.definitions) ||
    value.definitions.length > 64 ||
    !diagnostics(value.diagnostics)
  )
    throw new Error("Unsupported activity catalog envelope.");
  const source = definitions(program),
    seen = new Set<string>();
  for (const item of value.definitions) {
    const definition = source.get(item.id);
    if (
      !object(item) ||
      !identifier(item.id) ||
      seen.has(item.id) ||
      !definition ||
      typeof item.name !== "string" ||
      item.name !== definition.name ||
      item.title !== item.name ||
      item.category !== "Activities" ||
      typeof item.help !== "string" ||
      !object(item.parameters) ||
      Object.keys(item.parameters).length !== 1 ||
      !hash(item.program_sha256) ||
      !hash(item.definition_sha256) ||
      !hash(item.archive_sha256) ||
      item.kind !== "Activity" ||
      item.output !== "ports" ||
      item.unit !== "" ||
      item.parameters?.definition !== item.id ||
      !Array.isArray(item.inputs) ||
      !Array.isArray(item.input_contracts) ||
      !Array.isArray(item.outputs) ||
      item.input_contracts.length > 32 ||
      item.outputs.length < 1 ||
      item.outputs.length > 32 ||
      !item.input_contracts.every(
        (row: any) => port(row) && row.required === true,
      ) ||
      !item.outputs.every(port)
    )
      throw new Error("Activity catalog port contract is invalid.");
    const inputs = definition.program.nodes.filter(
      (node: any) => node.kind === "Input",
    );
    const outputs = definition.program.nodes.filter(
      (node: any) => node.kind === "Output",
    );
    const declared = (node: any) => ({
      id: node.id,
      label: node.label || node.id,
      value_type: node.value_type ?? "number",
      unit: node.unit ?? "",
    });
    if (
      !sourceEqual(
        item.inputs,
        inputs.map((node: any) => node.id),
      ) ||
      !sourceEqual(
        item.input_contracts,
        inputs.map((node: any) => ({ ...declared(node), required: true })),
      ) ||
      !sourceEqual(item.outputs, outputs.map(declared))
    )
      throw new Error(
        "Activity catalog differs from the current source interfaces.",
      );
    seen.add(item.id);
  }
  if (seen.size !== source.size)
    throw new Error("Activity catalog definition coverage is incomplete.");
  if (value.bindings !== null) {
    await activityBindings(value.bindings, program);
    if (value.bindings.source_sha256 !== value.source_sha256)
      throw new Error(
        "Activity catalog and executable bindings have different source authority.",
      );
  }
  return value as Data;
}

function legacyRewrites(program: Program) {
  if (libraryVersion(program) !== 1)
    throw new Error("Migration requires a version-one source editor.");
  const list = Object.hasOwn(program.metadata, "macros")
    ? program.metadata.macros.definitions
    : [];
  if (!Array.isArray(list) || list.length > 64)
    throw new Error("Invalid legacy dependency library.");
  const library = new Map<string, Data>();
  for (const item of list) {
    if (
      !object(item) ||
      !identifier(item.id) ||
      library.has(item.id) ||
      !Array.isArray(item.program?.nodes) ||
      !Array.isArray(item.program?.edges)
    )
      throw new Error(
        "Legacy definition identities are incomplete or duplicate.",
      );
    library.set(item.id, item);
  }
  const expected = new Map<string, Data>();
  for (const { graph, definition } of [
    { graph: program, definition: null as string | null },
    ...list.map((item: Data) => ({ graph: item.program, definition: item.id })),
  ]) {
    const scope = definition === null ? "root" : "definition";
    const nodes = new Map<string, Data>(
      graph.nodes.map((node: Data) => [node.id, node]),
    );
    for (const node of graph.nodes) {
      if (node.kind !== "Macro") continue;
      const item = library.get(node.params?.definition);
      if (
        !item ||
        item.program.nodes.filter((output: Data) => output.kind === "Output")
          .length !== 1
      )
        throw new Error(
          "Legacy reference does not have one unambiguous Output.",
        );
      const row = {
        scope,
        definition,
        kind: "container",
        node: node.id,
        from: {
          kind: "Macro",
          value_type: node.value_type ?? "number",
          unit: node.unit ?? "",
        },
        to: { kind: "Activity", value_type: "number", unit: "" },
      };
      expected.set(
        JSON.stringify([scope, definition, "container", node.id]),
        row,
      );
    }
    for (const edge of graph.edges) {
      const node = nodes.get(edge.source);
      if (node?.kind !== "Macro") continue;
      const outputs = library
        .get(node.params.definition)
        ?.program.nodes.filter((output: Data) => output.kind === "Output");
      if ((edge.source_port ?? "out") !== "out" || outputs?.length !== 1)
        throw new Error("Legacy output connection is ambiguous.");
      const row = {
        scope,
        definition,
        kind: "source-port",
        edge: edge.id,
        source: edge.source,
        from: "out",
        to: outputs[0].id,
      };
      expected.set(
        JSON.stringify([scope, definition, "source-port", edge.id]),
        row,
      );
    }
  }
  return expected;
}
export async function activityMigration(value: any, source: Program) {
  await activityProfile(value);
  if (
    value.format !== "bms.activity-migration-preview" ||
    value.version !== 1 ||
    !hash(value.source_sha256) ||
    !hash(value.program_sha256) ||
    !hash(value.rewrites_sha256) ||
    !hash(value.review_sha256) ||
    !Array.isArray(value.rewrites) ||
    value.rewrites.length > 20000 ||
    value.can_apply !== true ||
    !diagnostics(value.before_diagnostics) ||
    !diagnostics(value.after_diagnostics) ||
    value.program?.id !== source.id ||
    value.program.revision !== source.revision ||
    value.program.scan_seconds !== source.scan_seconds ||
    !sourceEqual(value.program.target, source.target) ||
    libraryVersion(value.program) !== 2
  )
    throw new Error(
      "Activity migration does not match the current source and supported profile.",
    );
  const manifest = {
    format: value.format,
    version: 1,
    profile_sha256: value.profile_sha256,
    source_sha256: value.source_sha256,
    program_sha256: value.program_sha256,
    rewrites_sha256: value.rewrites_sha256,
  };
  if (
    (await manifestSha256(value.rewrites)) !== value.rewrites_sha256 ||
    (await manifestSha256(manifest)) !== value.review_sha256
  )
    throw new Error("Activity migration manifest digest is inconsistent.");
  const expected = legacyRewrites(source);
  activitySource(value.program);
  for (const row of value.rewrites) {
    if (!object(row)) throw new Error("Invalid activity migration rewrite.");
    const key = JSON.stringify([
      row.scope,
      row.definition,
      row.kind,
      row.kind === "container" ? row.node : row.edge,
    ]);
    if (!expected.has(key) || !sourceEqual(row, expected.get(key)))
      throw new Error(
        "Activity migration rewrites differ from the current legacy source.",
      );
    expected.delete(key);
  }
  if (expected.size)
    throw new Error("Activity migration omitted a required source rewrite.");
  return value as Data;
}
