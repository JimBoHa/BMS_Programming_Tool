import { sha256Blob } from "./activityContracts";
import { connectionSeal } from "./nativeConnectionContract";
import type { JsonDocument } from "./api";

const object = (v: any) => !!v && typeof v === "object" && !Array.isArray(v);
const exact = (v: any, keys: string[]) =>
  object(v) &&
  Object.keys(v).length === keys.length &&
  keys.every((k) => Object.hasOwn(v, k));
const hash = (v: any) =>
  typeof v === "string" && v.length === 64 && /^[a-f0-9]{64}$/.test(v);
const text = (v: any, max = 8192) => typeof v === "string" && v.length <= max;
const count = (v: any, max = 8388608) =>
  Number.isSafeInteger(v) && v >= 0 && v <= max;
const flags = [
  "network_requests",
  "controller_queries",
  "field_actions",
  "source_retained_on_server",
  "native_sct_archive_decoded",
  "native_jct_graphics_decoded",
  "compile_authority",
  "apply_authority",
  "physical_acceptance",
];
export function engineeringInventory(v: any) {
  if (
    !object(v) ||
    v.profile !== "jci-engineering-inventory/1" ||
    v.manual_operation_mapping !== "partial" ||
    v.read_only !== true ||
    [
      "field_actions",
      "native_sct_archive_decoded",
      "native_jct_graphics_decoded",
    ].some((k) => v[k] !== false) ||
    !text(v.scope) ||
    !Array.isArray(v.artifact_families) ||
    v.artifact_families.length > 64 ||
    !Array.isArray(v.operations) ||
    v.operations.length > 256 ||
    !Array.isArray(v.packages) ||
    v.packages.length > 256 ||
    !Array.isArray(v.manual_sources) ||
    v.manual_sources.length > 64 ||
    !Array.isArray(v.fixture_manifest)
  )
    return false;
  const ids = new Set<string>();
  for (const row of v.packages) {
    if (
      !object(row) ||
      !text(row.id, 40) ||
      !row.id ||
      ids.has(row.id) ||
      !["planned", "partial"].includes(row.status) ||
      !text(row.title, 1024) ||
      !text(row.scope) ||
      !text(row.acceptance) ||
      !text(row.workspace, 1024) ||
      !text(row.category, 1024) ||
      !["Shared", "SCT", "JCT"].includes(row.product) ||
      !count(row.priority, 256) ||
      !Array.isArray(row.dependencies) ||
      !row.dependencies.every((s: any) => text(s, 128))
    )
      return false;
    ids.add(row.id);
  }
  for (const row of v.artifact_families) {
    if (
      !object(row) ||
      !["id", "title", "support", "remaining"].every((k) => text(row[k])) ||
      !Array.isArray(row.extensions) ||
      !row.extensions.every((s: any) => text(s, 32)) ||
      ![
        "bounded reader profile",
        "explicit schema-1 reader",
        "native codec planned",
        "planned under SJ-02",
      ].includes(row.support) ||
      !(
        row.reader_profile === null ||
        [
          "jci-single-xml-objects/1",
          "jci-moi-tagged/1",
          "bms-portable-program/1",
        ].includes(row.reader_profile)
      )
    )
      return false;
  }
  for (const row of v.operations) {
    if (
      !object(row) ||
      ![
        "id",
        "title",
        "support",
        "implementation",
        "tests",
        "evidence_level",
        "remaining",
      ].every((k) => text(row[k])) ||
      ![
        "implemented local inspection",
        "implemented bounded reader",
        "implemented schema-1 reader",
        "implemented local report",
      ].includes(row.support)
    )
      return false;
  }
  for (const row of v.manual_sources) {
    if (!object(row) || !text(row.id, 80) || !text(row.url, 4096)) return false;
    try {
      const url = new URL(row.url);
      if (
        url.protocol !== "https:" ||
        url.hostname !== "docs.johnsoncontrols.com"
      )
        return false;
    } catch {
      return false;
    }
  }
  return true;
}

export async function engineeringReport(
  doc: JsonDocument,
  file: File,
  expectedHash: string,
) {
  const v = doc.data;
  if (doc.blob.size > 65536) return false;
  const keys = [
    "profile",
    "source",
    "detected",
    "summary",
    "diagnostics",
    "operations",
    "coverage",
    ...flags,
    "read_only",
    "report_sha256",
  ];
  if (
    !object(v) ||
    Object.keys(v).length !== keys.length ||
    !keys.every((k) => Object.hasOwn(v, k)) ||
    v.profile !== "jci-engineering-source-inspection/1" ||
    v.read_only !== true ||
    flags.some((k) => v[k] !== false) ||
    !hash(v.report_sha256) ||
    !exact(v.source, [
      "name",
      "bytes",
      "sha256",
      "extension",
      "declared_family",
    ]) ||
    v.source.name !== file.name.replaceAll("\\", "/").split("/").at(-1) ||
    v.source.bytes !== file.size ||
    v.source.sha256 !== expectedHash ||
    !hash(expectedHash) ||
    !text(v.source.extension, 512) ||
    !text(v.source.declared_family, 128) ||
    !exact(v.detected, [
      "state",
      "reader_profile",
      "container_hint",
      "artifact_identity_proved",
    ]) ||
    !["readable", "partial", "unrecognized"].includes(v.detected.state) ||
    ![
      "zip",
      "gzip",
      "native-moi",
      "json-looking",
      "xml-looking",
      "opaque",
    ].includes(v.detected.container_hint) ||
    !(
      v.detected.reader_profile === null ||
      [
        "jci-single-xml-objects/1",
        "jci-moi-tagged/1",
        "bms-portable-program/1",
      ].includes(v.detected.reader_profile)
    ) ||
    typeof v.detected.artifact_identity_proved !== "boolean" ||
    (v.detected.state === "unrecognized") !==
      (v.detected.reader_profile === null) ||
    (v.detected.artifact_identity_proved &&
      v.detected.reader_profile !== "bms-portable-program/1") ||
    !object(v.summary) ||
    !exact(v.coverage, [
      "source_bytes_fingerprinted",
      "complete_native_semantics",
      "unknown_sections_preserved_in_original_only",
    ]) ||
    v.coverage.source_bytes_fingerprinted !== true ||
    v.coverage.complete_native_semantics !== false ||
    v.coverage.unknown_sections_preserved_in_original_only !== true ||
    !Array.isArray(v.diagnostics) ||
    v.diagnostics.length > 16 ||
    !v.diagnostics.every((s: any) => text(s, 2048)) ||
    !Array.isArray(v.operations) ||
    v.operations.length !== 6
  )
    return false;
  const expected = [
    "fingerprint",
    "inspect-projection",
    "export-inspection-report",
    "native-sct-import-export",
    "native-jct-graphics",
    "compile-or-deploy",
  ];
  const statuses = [
    "available-local",
    v.detected.reader_profile ? "available-local" : "unavailable",
    "available-local",
    "not-qualified",
    "not-qualified",
    "not-granted",
  ];
  if (
    !v.operations.every(
      (r: any, i: number) =>
        exact(r, ["id", "status", "reason", "implementation"]) &&
        r.id === expected[i] &&
        r.status === statuses[i] &&
        text(r.reason) &&
        (r.implementation === null || text(r.implementation, 512)),
    )
  )
    return false;
  if (v.detected.reader_profile === "bms-portable-program/1") {
    if (
      !exact(v.summary, [
        "program_id",
        "name",
        "revision_text",
        "nodes",
        "edges",
        "schema_version",
      ]) ||
      !text(v.summary.name, 200) ||
      !text(v.summary.program_id, 80) ||
      !text(v.summary.revision_text, 4096) ||
      !/^(0|[1-9][0-9]*)$/.test(v.summary.revision_text) ||
      /[^0-9]/.test(v.summary.revision_text) ||
      !count(v.summary.nodes, 2000) ||
      !count(v.summary.edges, 10000) ||
      v.summary.schema_version !== 1
    )
      return false;
  } else if (v.detected.reader_profile) {
    if (
      !count(v.summary.objects, 500000) ||
      !count(v.summary.class_count, 500000) ||
      !count(v.summary.unrepresented_class_ids, 500000) ||
      !Array.isArray(v.summary.classes) ||
      v.summary.classes.length > 64 ||
      !v.summary.classes.every(
        (r: any) =>
          exact(r, ["id", "objects"]) &&
          text(r.id, 64) &&
          count(r.objects, 500000),
      ) ||
      typeof v.summary.class_list_complete !== "boolean" ||
      v.summary.tool_release !== null
    )
      return false;
    const classes = v.summary.classes;
    const total = classes.reduce(
      (sum: number, row: any) => sum + row.objects,
      0,
    );
    if (
      new Set(classes.map((row: any) => row.id)).size !== classes.length ||
      classes.some((row: any) => row.objects < 1) ||
      total > v.summary.objects ||
      v.summary.class_count < classes.length ||
      (v.summary.class_list_complete &&
        (v.summary.unrepresented_class_ids !== 0 ||
          total !== v.summary.objects ||
          v.summary.class_count !== classes.length))
    )
      return false;
    const common = [
      "objects",
      "class_count",
      "classes",
      "class_list_complete",
      "unrepresented_class_ids",
      "tool_release",
    ];
    if (v.detected.reader_profile === "jci-single-xml-objects/1") {
      if (
        !exact(v.summary, [
          ...common,
          "xml_bytes",
          "class_versions",
          "class_versions_complete",
          "omitted_class_versions",
          "root_metadata_records",
        ]) ||
        !count(v.summary.xml_bytes, 33554432) ||
        !count(v.summary.root_metadata_records, 500000) ||
        !count(v.summary.omitted_class_versions, 500000) ||
        typeof v.summary.class_versions_complete !== "boolean" ||
        !Array.isArray(v.summary.class_versions) ||
        v.summary.class_versions.length > 32 ||
        !v.summary.class_versions.every((s: any) => text(s, 128))
      )
        return false;
    } else if (
      !exact(v.summary, [
        ...common,
        "metadata_records",
        "record_framing",
        "readable_diagrams",
        "reader_errors",
      ]) ||
      !["declared-lengths", "scanned-reference-records"].includes(
        v.summary.record_framing,
      ) ||
      !["metadata_records", "readable_diagrams", "reader_errors"].every((k) =>
        count(v.summary[k], 500000),
      ) ||
      (v.detected.state === "partial") !== v.summary.reader_errors > 0
    )
      return false;
  } else if (Object.keys(v.summary).length) {
    return false;
  }
  if (
    doc.headers?.get("X-BMS-Source-SHA256") !== expectedHash ||
    doc.headers?.get("X-BMS-Report-SHA256") !== (await sha256Blob(doc.blob))
  )
    return false;
  const { report_sha256, ...body } = v;
  return (await connectionSeal(body)) === report_sha256;
}
