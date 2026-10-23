import { apiBlobDocument } from "./api";

export const HYDRONIC_PROFILE = "chilled-hydraulic-io-planner/1";
export const HYDRONIC_RULES =
  "2d8d877157863bc4fe48ef7605411878b87db5f4c6cc5d37445df3bbc9770cb9";
export const MONITORS = [
  "chiller-status",
  "chiller-alarm",
  "chiller-maintenance",
  "chiller-entering-temperature",
  "chiller-leaving-temperature",
  "chiller-flow",
  "primary-status",
  "primary-fault",
  "primary-lockout",
  "secondary-status",
  "secondary-fault",
  "secondary-lockout",
  "primary-supply-temperature",
  "primary-return-temperature",
  "secondary-supply-temperature",
  "secondary-return-temperature",
  "primary-flow",
  "secondary-flow",
  "decoupler-flow",
  "system-pressure",
];
export type Role = {
  id: string;
  label: string;
  direction: "input" | "output";
  value_type: "number" | "boolean";
  unit: string;
  subsystem: string;
  reasons: {
    use: string;
    source: string;
    pdf_pages: number[];
    table: number;
  }[];
};
export type Host = {
  id: string;
  label: string;
  plant_host_id: string;
  kind: "controller" | "module";
  model: string;
  parent_controller_id: string | null;
  survey_reference: {
    id: string;
    content_sha256: string;
    host: "base" | "sa";
    sa_mac: number | null;
  } | null;
};
export type Binding = {
  role_id: string;
  instance_id: string;
  node_id: string;
  transport: "physical" | "network";
  physical_host_id: string | null;
  mode: string | null;
  network_link_ids: string[];
};
export const hash = (value: any, n = 64): value is string =>
  typeof value === "string" && new RegExp(`^[a-f0-9]{${n}}$`).test(value);
const list = (v: any, n: number): v is any[] =>
  Array.isArray(v) && v.length <= n;
const text = (v: any, n = 4096): v is string =>
  typeof v === "string" && v.length <= n;
const integer = (v: any, n = 1024) =>
  Number.isSafeInteger(v) && v >= 0 && v <= n;
export const endpoint = (v: any) => JSON.stringify([v.instance_id, v.node_id]);
export function stable(value: any): string {
  if (
    typeof value === "number" &&
    (!Number.isSafeInteger(value) || Object.is(value, -0))
  )
    throw new Error(
      "Unexpected numeric metadata; opaque Program source must remain text.",
    );
  return Array.isArray(value)
    ? `[${value.map(stable).join(",")}]`
    : value && typeof value === "object"
      ? `{${Object.keys(value)
          .sort()
          .map((k) => `${JSON.stringify(k)}:${stable(value[k])}`)
          .join(",")}}`
      : JSON.stringify(value);
}
export async function sha256(value: Blob | string) {
  const bytes =
    typeof value === "string"
      ? new TextEncoder().encode(value)
      : await value.arrayBuffer();
  return Array.from(
    new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
    (b) => b.toString(16).padStart(2, "0"),
  ).join("");
}
async function sealed(value: any, key = "content_sha256") {
  if (
    !hash(value?.[key]) ||
    (await sha256(
      stable(
        Object.fromEntries(Object.entries(value).filter(([k]) => k !== key)),
      ),
    )) !== value[key]
  )
    throw new Error("Hydraulic response seal is invalid.");
}
export async function fileDocument(
  path: string,
  body: any,
  kind: "json" | "csv",
  limit = 24 * 1024 * 1024,
) {
  const result = await apiBlobDocument(path, body);
  if (
    !result.blob.size ||
    result.blob.size > limit ||
    !result.headers
      .get("Content-Type")
      ?.startsWith(kind === "json" ? "application/json" : "text/csv") ||
    result.headers.get("X-File-SHA256") !== (await sha256(result.blob))
  )
    throw new Error("Hydraulic file bytes, media type or digest are invalid.");
  return result.blob;
}
export async function profileResult(value: any, catalog: any) {
  const profile = value?.profile;
  if (
    profile?.id !== HYDRONIC_PROFILE ||
    profile.sha256 !== HYDRONIC_RULES ||
    value.field_queries !== false ||
    value.controller_writes !== false ||
    value.capacity_catalog_sha256 !== catalog?.catalog_sha256 ||
    !hash(value.capacity_catalog_sha256) ||
    catalog.profile !== "jci-physical-counts/1" ||
    !list(catalog.models, 64) ||
    !catalog.models.length ||
    !catalog.modes ||
    !list(profile.source_conflicts, 16) ||
    profile.sources?.["chilled-2025"]?.sha256 !==
      "87298adc723f40cc5c0ff08d08822dbd7c931698e576b7c51b099f5a59c839d7"
  )
    throw new Error("Hydraulic profile or capacity catalog is unsupported.");
  await sealed(profile, "sha256");
  if (
    catalog.models.some(
      (m: any) =>
        !text(m?.model, 100) || !["controller", "expansion"].includes(m.kind),
    ) ||
    new Set(catalog.models.map((m: any) => m.model)).size !==
      catalog.models.length
  )
    throw new Error("Capacity model identities are invalid.");
  return value;
}
export async function plantDocument(blob: Blob, expected: any) {
  if (!blob.size || blob.size > 8 * 1024 * 1024)
    throw new Error("Exact PLANT source exceeds its byte profile.");
  const raw = new TextDecoder("utf-8", { fatal: true }).decode(
      await blob.arrayBuffer(),
    ),
    value = JSON.parse(raw);
  if (
    value.format !== "bms.plant-signal-review/1" ||
    value.id !== expected.id ||
    value.content_sha256 !== expected.content_sha256 ||
    value.plan_sha256 !== expected.plan_sha256 ||
    stable(value.plan) !== stable(expected.plan) ||
    stable(value.analysis) !== stable(expected.analysis) ||
    value.profile?.sha256 !== expected.profile.sha256 ||
    !list(value.sources, 32) ||
    value.sources.length !== expected.sources.length ||
    value.field_queries !== false ||
    value.field_writes !== false
  )
    throw new Error("Exact PLANT export belongs to another review/source.");
  for (const source of value.sources) {
    const summary = expected.sources.find((s: any) => s.id === source.id);
    if (
      !summary ||
      !text(source.source_json, 1048576) ||
      (await sha256(source.source_json)) !== source.id ||
      new Blob([source.source_json]).size !== source.source_bytes ||
      [
        "canonical_sha256",
        "program_id",
        "name",
        "revision_text",
        "source_bytes",
      ].some((k) => source[k] !== summary[k])
    )
      throw new Error("Exact PLANT Program source identity failed.");
  }
  await sealed(value);
  return { blob, raw, raw_sha256: await sha256(blob) };
}
export async function rolePlanResult(value: any, topology: any) {
  if (
    value?.format !== "bms.chilled-hydraulic-role-plan/1" ||
    value.profile_sha256 !== HYDRONIC_RULES ||
    stable(value.topology) !== stable(topology) ||
    !list(value.roles, 256) ||
    !value.roles.length ||
    new Set(value.roles.map((r: any) => r.id)).size !== value.roles.length ||
    value.roles.some(
      (r: any) =>
        !/^[A-Za-z][A-Za-z0-9_.-]{0,79}$/.test(r?.id) ||
        !text(r.label, 200) ||
        !["input", "output"].includes(r.direction) ||
        !["number", "boolean"].includes(r.value_type) ||
        !text(r.unit, 80) ||
        !list(r.reasons, 16) ||
        !r.reasons.length ||
        r.reasons.some(
          (why: any) =>
            why.source !== "chilled-2025" ||
            !list(why.pdf_pages, 16) ||
            !why.pdf_pages.every((p: any) => integer(p, 54) && p > 0),
        ),
    )
  )
    throw new Error(
      "Hydraulic roles belong to another topology or unsupported profile.",
    );
  const ids = new Set(value.roles.map((r: Role) => r.id));
  if (
    !list(value.dependencies, 32) ||
    value.dependencies.some(
      (d: any) =>
        !text(d?.id, 80) ||
        !list(d.role_ids, 256) ||
        d.role_ids.some((id: any) => !ids.has(id)),
    ) ||
    !list(value.unresolved_sequence_assumptions, 3) ||
    !list(value.outside_subset_dependencies, 16) ||
    value.outside_subset_dependencies.some((s: any) => !text(s)) ||
    !list(value.source_conflicts, 16) ||
    ["control_program_generated", "field_queries", "controller_writes"].some(
      (k) => value[k] !== false,
    )
  )
    throw new Error("Hydraulic dependencies or scope are invalid.");
  const counts = value.equipment_counts;
  if (
    counts?.chillers !== topology.chillers ||
    counts.primary_pumps !==
      (topology.primary_arrangement === "dedicated"
        ? topology.chillers
        : topology.primary_pumps) ||
    counts.secondary_pumps !== (topology.secondary_pumps ?? 0)
  )
    throw new Error(
      "Derived equipment counts do not match the selected layout.",
    );
  await sealed(value);
  return value;
}
export async function reviewResult(
  value: any,
  request: any,
  plan: any,
  plant: any,
  profile: any,
) {
  if (
    value?.format !== "bms.chilled-hydraulic-io-review/1" ||
    stable(value.request) !== stable(request) ||
    stable(value.profile) !== stable(profile) ||
    stable(value.role_plan) !== stable(plan) ||
    value.plant_reference?.review?.id !== request.plant_review.id ||
    value.plant_reference.review.content_sha256 !==
      request.plant_review.content_sha256 ||
    value.plant_reference.raw_sha256 !== plant.raw_sha256 ||
    value.plant_reference.original_review_json !== plant.raw ||
    !["unresolved", "declared-subset-consistent"].includes(value.status) ||
    typeof value.logical_bindings_complete !== "boolean" ||
    !list(value.binding_results, 256) ||
    value.binding_results.length !== request.bindings.length ||
    !list(value.capacity_reviews, 32) ||
    value.capacity_reviews.length !== request.physical_hosts.length ||
    !list(value.diagnostics, 4096) ||
    [
      "hardware_verified",
      "terminal_assignment_verified",
      "whole_application_fit_established",
      "native_allocation_verified",
      "control_program_generated",
      "field_queries",
      "controller_writes",
    ].some((k) => value[k] !== false)
  )
    throw new Error(
      "Hydraulic review belongs to another declaration/source or unsupported scope.",
    );
  const sourcePlant = JSON.parse(plant.raw),
    points = sourcePlant.analysis.io_schedule;
  for (const row of value.binding_results) {
    const bound = request.bindings.find(
        (b: Binding) => b.role_id === row.role_id,
      ),
      point = points.find((p: any) => endpoint(p) === endpoint(row));
    if (
      !bound ||
      Object.keys(bound).some((k) => stable(row[k]) !== stable(bound[k])) ||
      stable(row.point) !== stable(point ?? null) ||
      !["unresolved", "exact-declaration-consistent"].includes(row.status) ||
      !list(row.issues, 32) ||
      !list(row.network_evidence, 32)
    )
      throw new Error(
        "Hydraulic binding does not preserve the exact source endpoint.",
      );
    const role = plan.roles.find((r: Role) => r.id === row.role_id);
    const expectedLinks =
      row.transport === "network"
        ? sourcePlant.analysis.network_schedule.filter(
            (link: any) =>
              endpoint(
                link[role.direction === "input" ? "target" : "source"],
              ) === endpoint(row),
          )
        : [];
    if (
      stable(row.network_evidence) !== stable(expectedLinks) ||
      (row.status === "exact-declaration-consistent") !==
        (row.issues.length === 0)
    )
      throw new Error(
        "Hydraulic network/status evidence differs from the exact PLANT review.",
      );
  }
  if (
    new Set(value.binding_results.map((r: any) => r.role_id)).size !==
    request.bindings.length
  )
    throw new Error("Hydraulic response duplicates a role binding.");
  for (const result of value.capacity_reviews) {
    const declared = request.physical_hosts.find(
        (h: Host) => h.id === result.physical_host?.id,
      ),
      witness = result.capacity_review;
    if (
      !declared ||
      stable(result.physical_host) !== stable(declared) ||
      result.spare_channels_established !== false ||
      result.whole_application_fit_established !== false ||
      witness?.catalog_sha256 !== request.capacity_catalog_sha256 ||
      witness.request?.model !== declared.model ||
      stable(witness.request?.survey_reference) !==
        stable(declared.survey_reference) ||
      ![
        "count-mode-fit",
        "count-mode-shortfall",
        "unknown-model",
        "no-demand-declared",
      ].includes(witness.status) ||
      [
        "installed_verified",
        "electrical_compatibility_verified",
        "terminal_assignment_verified",
        "power_verified",
        "native_allocation_verified",
        "controller_writes",
        "field_queries",
      ].some((k) => witness[k] !== false)
    )
      throw new Error(
        "Hydraulic capacity witness belongs to another physical declaration.",
      );
    await sealed(witness);
    const contributing = value.binding_results
      .filter(
        (r: any) =>
          r.transport === "physical" &&
          r.physical_host_id === declared.id &&
          r.status === "exact-declaration-consistent",
      )
      .map((r: any) => r.role_id)
      .sort();
    if (
      !list(result.role_demands, 32) ||
      stable(result.role_demands.flatMap((d: any) => d.role_ids).sort()) !==
        stable(contributing) ||
      witness.declared_channels !== contributing.length ||
      !integer(witness.matched_channels) ||
      witness.matched_channels > contributing.length ||
      result.role_demands.some((d: any) => {
        const demand = witness.request.demands.find(
          (v: any) => v.id === d.demand_id,
        );
        return !demand || demand.quantity !== d.role_ids.length;
      })
    )
      throw new Error(
        "Hydraulic capacity channels do not match explicit physical bindings.",
      );
  }
  if (
    new Set(value.capacity_reviews.map((r: any) => r.physical_host.id)).size !==
    request.physical_hosts.length
  )
    throw new Error("Hydraulic capacity response duplicates a physical host.");
  if (
    (value.status === "declared-subset-consistent") !==
      (value.diagnostics.length === 0) ||
    value.logical_bindings_complete !==
      (request.bindings.length === plan.roles.length &&
        value.binding_results.every(
          (r: any) => r.status === "exact-declaration-consistent",
        ) &&
        sourcePlant.analysis.errors === 0)
  )
    throw new Error(
      "Hydraulic completeness/status is inconsistent with its explicit bindings.",
    );
  await sealed(value);
  return value;
}
function csvRows(text: string) {
  const rows: string[][] = [];
  let row: string[] = [],
    cell = "",
    quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === '"') {
      if (quoted && text[i + 1] === '"') {
        cell += '"';
        i++;
      } else quoted = !quoted;
    } else if (!quoted && (c === "," || c === "\n" || c === "\r")) {
      row.push(cell);
      cell = "";
      if (c !== ",") {
        if (c === "\r" && text[i + 1] === "\n") i++;
        rows.push(row);
        row = [];
      }
    } else cell += c;
    if (cell.length > 65536 || row.length > 64 || rows.length > 257)
      throw new Error("Hydraulic CSV exceeds its row/column profile.");
  }
  if (quoted || cell || row.length)
    throw new Error("Hydraulic CSV is incomplete.");
  return rows;
}
export async function checkCSV(blob: Blob, plan: any, review?: any) {
  const [columns, ...rows] = csvRows(
    new TextDecoder("utf-8", { fatal: true }).decode(await blob.arrayBuffer()),
  );
  if (
    !columns ||
    new Set(columns).size !== columns.length ||
    rows.length !== plan.roles.length ||
    [
      "role_id",
      "profile_sha256",
      "role_plan_sha256",
      "hydraulic_review_sha256",
      "plant_review_sha256",
      "hardware_verified",
      "native_allocation_verified",
    ].some((k) => !columns.includes(k))
  )
    throw new Error("Hydraulic CSV does not match its role schedule.");
  const at = (r: string[], name: string) => r[columns.indexOf(name)],
    ids = new Set<string>();
  for (const row of rows) {
    const id = at(row, "role_id");
    if (
      row.length !== columns.length ||
      ids.has(id) ||
      !plan.roles.some((r: Role) => r.id === id) ||
      at(row, "profile_sha256") !== HYDRONIC_RULES ||
      at(row, "role_plan_sha256") !== plan.content_sha256 ||
      at(row, "hydraulic_review_sha256") !== (review?.content_sha256 ?? "") ||
      at(row, "plant_review_sha256") !==
        (review?.plant_reference.raw_sha256 ?? "") ||
      at(row, "hardware_verified") !== "false" ||
      at(row, "native_allocation_verified") !== "false"
    )
      throw new Error("Hydraulic CSV belongs to another source/review.");
    ids.add(id);
  }
}
