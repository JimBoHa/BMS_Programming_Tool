import { sha256Blob } from "./activityContracts";
import {
  connectionSame as same,
  connectionSeal as seal,
} from "./nativeConnectionContract";
import { cafEnumMetadata } from "./cafScalarCopy";

type Data = Record<string, any>;
export type ScalarRow = {
  ref: string;
  property: string;
  old: string;
  value: string;
};
export type CombinedWiring =
  | {
      kind: "rewire";
      diagram_ref: string;
      wire_index: number;
      old: number[];
      source_ref: string;
    }
  | {
      kind: "connect";
      diagram_ref: string;
      prototype_diagram_ref: string;
      prototype_wire_index: number;
      prototype_old: number[];
      source_ref: string;
      target_ref: string;
      old_connection_count: number;
    };
export const combinedScope =
  "Local scalar edits plus one rewire or connection addition. Native execution, CCT/PCT acceptance and controller transfer remain unverified.";
const flags = [
  "controller_write",
  "field_transfer_enabled",
  "native_execution_verified",
  "vendor_acceptance_verified",
  "can_apply",
];
const validation =
  "Observed native CAF graph records only. CCT/PCT acceptance, firmware execution, and controller transfer remain unverified.";
const closed = (v: any, keys: string[]): v is Data =>
  !!v &&
  typeof v === "object" &&
  !Array.isArray(v) &&
  Object.keys(v).length === keys.length &&
  keys.every((k) => Object.hasOwn(v, k));
const hash = (v: any) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const safe = (v: any) => flags.every((k) => v[k] === false);
const sourceKeys = [
  "profile",
  "scope",
  "source_sha256",
  "source_xml_sha256",
  "request",
  "request_sha256",
  "fields",
  "wiring_report",
  "selection_sha256",
  ...flags,
];
async function sealed(v: Data, key: string) {
  const { [key]: digest, ...body } = v;
  return hash(digest) && (await seal(body)) === digest;
}

function expectedWire(w: CombinedWiring, diagram: Data) {
  if (w.diagram_ref !== diagram.ref || diagram.class_version !== "1.0")
    return null;
  const selected =
    diagram.connections[
      w.kind === "rewire" ? w.wire_index : w.prototype_wire_index
    ];
  const source = diagram.blocks.find((b: Data) => b.ref === w.source_ref);
  if (
    !selected ||
    !source ||
    !same(selected.raw, w.kind === "rewire" ? w.old : w.prototype_old)
  )
    return null;
  if (w.kind === "rewire")
    return source.ref === selected.source_ref
      ? []
      : [
          {
            diagram_ref: w.diagram_ref,
            wire_index: w.wire_index,
            old: w.old,
            new: [source.index, ...selected.raw.slice(1)],
            validation,
          },
        ];
  const target = diagram.blocks.find((b: Data) => b.ref === w.target_ref);
  if (
    !target ||
    w.prototype_diagram_ref !== diagram.ref ||
    w.old_connection_count !== diagram.connections.length
  )
    return null;
  return [
    {
      diagram_ref: w.diagram_ref,
      wire_index: w.old_connection_count,
      new: [
        source.index,
        selected.source_port,
        target.index,
        selected.target_port,
      ],
      prototype_diagram_ref: w.prototype_diagram_ref,
      prototype_wire_index: w.prototype_wire_index,
      prototype_old: w.prototype_old,
      old_connection_count: w.old_connection_count,
      validation,
    },
  ];
}
function reports(rows: any, expected: Data[], source: string, output?: string) {
  return (
    Array.isArray(rows) &&
    rows.length === expected.length &&
    rows.every((r, i) => {
      if (
        !closed(r, [
          ...Object.keys(expected[i]),
          "source_sha256",
          "result_sha256",
        ]) ||
        r.source_sha256 !== source ||
        !hash(r.result_sha256) ||
        (output && r.result_sha256 !== output)
      )
        return false;
      const { source_sha256, result_sha256, ...semantic } = r;
      return same(semantic, expected[i]);
    })
  );
}
export async function combinedSource(v: Data, request: Data, diagram: Data) {
  if (
    !closed(v, sourceKeys) ||
    !safe(v) ||
    v.profile !== "caf-combined-copy-source/1" ||
    v.scope !== combinedScope ||
    v.source_sha256 !== request.source_sha256 ||
    !hash(v.source_xml_sha256) ||
    !same(v.request, request) ||
    !Array.isArray(v.fields) ||
    v.fields.length !== request.changes.length
  )
    return false;
  for (let i = 0; i < request.changes.length; i++) {
    const row = request.changes[i],
      f = v.fields[i],
      p = f?.property;
    if (
      !closed(f, ["ref", "class_id", "property"]) ||
      f.ref !== row.ref ||
      typeof f.class_id !== "string" ||
      !closed(p, [
        "id",
        "kind",
        "editable",
        "scalar",
        ...(p?.enum_code_copy ? ["enum_code_copy"] : []),
      ]) ||
      p.id !== row.property ||
      p.kind !== "property" ||
      p.editable !== true ||
      !closed(p.scalar, ["type", "text", "attributes"]) ||
      p.scalar.text !== row.old ||
      typeof p.scalar.type !== "string" ||
      !p.scalar.attributes ||
      typeof p.scalar.attributes !== "object" ||
      Array.isArray(p.scalar.attributes)
    )
      return false;
    const known = diagram.blocks.find((b: Data) => b.ref === f.ref);
    if (
      (known && known.class_id !== f.class_id) ||
      (f.ref === diagram.ref && f.class_id !== diagram.class_id)
    )
      return false;
    if (
      p.scalar.type === "enum"
        ? !cafEnumMetadata(
            p,
            { ref: f.ref, class_id: f.class_id },
            v.source_sha256,
          )
        : p.enum_code_copy
    )
      return false;
  }
  const expected = expectedWire(request.wiring, diagram);
  return (
    expected !== null &&
    reports(v.wiring_report, expected, v.source_sha256) &&
    v.request_sha256 ===
      (await seal({ profile: "caf-combined-copy-request/1", request })) &&
    (await sealed(v, "selection_sha256"))
  );
}
export async function combinedReview(
  v: Data,
  request: Data,
  source: Data,
  diagram: Data,
) {
  if (
    !closed(v, ["profile", "request", "result", "review_sha256", ...flags]) ||
    !safe(v) ||
    v.profile !== "caf-combined-copy-review/1" ||
    !same(v.request, request)
  )
    return false;
  const r = v.result;
  if (
    !closed(r, [
      "profile",
      "selection",
      "output_sha256",
      "output_xml_sha256",
      "scalar_changes",
      "actual_scalar_change_count",
      "actual_wiring_change_count",
      "legacy_scalar_report",
      "orders",
      "unchanged",
      "independent_byte_deltas_verified",
      "combined_sha256",
      ...flags,
    ]) ||
    !safe(r) ||
    r.profile !== "caf-combined-copy-result/1" ||
    !same(r.selection, source) ||
    !hash(r.output_sha256) ||
    !hash(r.output_xml_sha256) ||
    r.independent_byte_deltas_verified !== true ||
    typeof r.unchanged !== "boolean" ||
    !Array.isArray(r.scalar_changes) ||
    r.scalar_changes.length !== source.request.changes.length ||
    !Array.isArray(r.legacy_scalar_report)
  )
    return false;
  for (let i = 0; i < r.scalar_changes.length; i++) {
    const row = r.scalar_changes[i],
      original = source.request.changes[i],
      field = source.fields[i].property.scalar;
    if (
      !closed(row, [
        "ref",
        "property",
        "old",
        "value",
        "type",
        "exported_value",
        "changed",
      ]) ||
      !same(
        {
          ref: row.ref,
          property: row.property,
          old: row.old,
          value: row.value,
        },
        original,
      ) ||
      row.type !== field.type ||
      typeof row.exported_value !== "string" ||
      typeof row.changed !== "boolean"
    )
      return false;
    const emitted = r.legacy_scalar_report.filter(
      (e: Data) => e.ref === row.ref && e.property === row.property,
    );
    if (
      emitted.length > 1 ||
      row.exported_value !== (emitted[0]?.value ?? row.old)
    )
      return false;
    if (emitted[0]) {
      const e = emitted[0];
      if (
        !closed(e, [
          "ref",
          "property",
          "old",
          "value",
          "type",
          ...(row.type === "enum"
            ? ["profile", "set_reference", "enum_semantics_verified"]
            : []),
        ]) ||
        e.old !== row.old ||
        e.type !== row.type ||
        (row.type === "enum" &&
          (e.profile !== "caf-enum-default-code-copy/1" ||
            e.enum_semantics_verified !== false ||
            e.set_reference !== (field.attributes.set ?? null)))
      )
        return false;
    }
  }
  if (
    r.legacy_scalar_report.some(
      (e: Data) =>
        !r.scalar_changes.some(
          (c: Data) => c.ref === e.ref && c.property === e.property,
        ),
    ) ||
    r.actual_scalar_change_count !==
      r.scalar_changes.filter((c: Data) => c.changed).length ||
    r.actual_wiring_change_count !== source.wiring_report.length ||
    r.unchanged !==
      (r.actual_scalar_change_count === 0 &&
        r.actual_wiring_change_count === 0) ||
    r.unchanged !== (r.output_xml_sha256 === source.source_xml_sha256) ||
    r.unchanged !== (r.output_sha256 === source.source_sha256)
  )
    return false;
  const orders = r.orders;
  if (!closed(orders, ["scalar_then_wiring", "wiring_then_scalar"]))
    return false;
  const a = orders.scalar_then_wiring,
    b = orders.wiring_then_scalar,
    expected = expectedWire(request.wiring, diagram);
  if (
    !closed(a, ["intermediate_sha256", "output_sha256", "wiring_report"]) ||
    !closed(b, ["intermediate_sha256", "output_sha256", "scalar_report"]) ||
    ![
      a.intermediate_sha256,
      a.output_sha256,
      b.intermediate_sha256,
      b.output_sha256,
    ].every(hash) ||
    !same(b.scalar_report, r.legacy_scalar_report) ||
    expected === null ||
    !reports(
      source.wiring_report,
      expected,
      source.source_sha256,
      b.intermediate_sha256,
    ) ||
    !reports(
      a.wiring_report,
      expected,
      a.intermediate_sha256,
      a.output_sha256,
    ) ||
    (!r.unchanged && r.output_sha256 !== a.output_sha256)
  )
    return false;
  return (
    (await sealed(r, "combined_sha256")) && (await sealed(v, "review_sha256"))
  );
}
export async function combinedExport(
  result: { blob: Blob; headers: Headers },
  review: Data,
) {
  const r = review.result,
    s = r.selection;
  const headers: Data = {
    "X-CAF-Source-SHA256": s.source_sha256,
    "X-CAF-Request-SHA256": s.request_sha256,
    "X-CAF-Selection-SHA256": s.selection_sha256,
    "X-CAF-Review-SHA256": review.review_sha256,
    "X-CAF-Combined-SHA256": r.combined_sha256,
    "X-CAF-Output-SHA256": r.output_sha256,
  };
  return (
    Object.entries(headers).every(
      ([k, value]) => result.headers.get(k) === value,
    ) && (await sha256Blob(result.blob)) === r.output_sha256
  );
}
export type CombinedCafCopy = {
  blob: Blob;
  name: string;
  sha256: string;
  sourceArchive: string;
  diagram: string;
  selectionSha256: string;
  reviewSha256: string;
  unchanged: boolean;
};
export type OpenCombinedCafCopy = (
  copy: CombinedCafCopy,
  current: () => boolean,
) => Promise<boolean>;
export async function combinedCafFile(
  copy: CombinedCafCopy,
  current: () => boolean,
) {
  if (!current()) return null;
  if (
    !copy ||
    !(copy.blob instanceof Blob) ||
    ![
      copy.sha256,
      copy.sourceArchive,
      copy.selectionSha256,
      copy.reviewSha256,
    ].every(hash) ||
    typeof copy.unchanged !== "boolean" ||
    copy.unchanged !== (copy.sha256 === copy.sourceArchive) ||
    typeof copy.diagram !== "string" ||
    !copy.diagram ||
    copy.diagram.length > 512 ||
    typeof copy.name !== "string" ||
    !/\.caf$/i.test(copy.name) ||
    /[\\/\r\n\x00]/.test(copy.name) ||
    (await sha256Blob(copy.blob)) !== copy.sha256
  )
    throw new Error(
      "Combined CAF copy identity or bytes changed. Review and save again.",
    );
  return current()
    ? new File([copy.blob], copy.name, { type: "application/octet-stream" })
    : null;
}
