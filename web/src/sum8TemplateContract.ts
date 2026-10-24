import { projectSourceDocument, sourceEqual } from "./programSource";
export type Data = Record<string, any>;
export const SUM8_BASE = "/macros/templates/sum8";
export const SUM8_PROFILE = "studio-sum8-macro-template/1";
export const SUM8_PROFILE_SHA =
  "c3de5dfc9c21f1377c7598a10754677b9dd2f553eb2821200593c63de42602cf";
export const unitOptions = [
  { value: "", label: "dimensionless", id: "dimensionless" },
  { value: "A", label: "amperes", id: "amperes" },
  { value: "kW", label: "kilowatts", id: "kw" },
  { value: "cfm", label: "cfm", id: "cfm" },
  { value: "L/s", label: "litres per second", id: "lps" },
];
const object = (v: any): v is Data =>
  v !== null && typeof v === "object" && !Array.isArray(v);
const hash = (v: any) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
export async function blobSha256(blob: Blob) {
  return Array.from(
    new Uint8Array(
      await crypto.subtle.digest("SHA-256", await blob.arrayBuffer()),
    ),
    (b) => b.toString(16).padStart(2, "0"),
  ).join("");
}
function canonicalProfile(v: any): string {
  if (Array.isArray(v)) return "[" + v.map(canonicalProfile).join(",") + "]";
  if (object(v))
    return (
      "{" +
      Object.keys(v)
        .sort()
        .map((k) => JSON.stringify(k) + ":" + canonicalProfile(v[k]))
        .join(",") +
      "}"
    );
  if (typeof v === "number" && !Number.isSafeInteger(v))
    throw new Error("Unsupported sum profile number.");
  return JSON.stringify(v);
}
export async function catalogResult(v: any) {
  if (
    !object(v) ||
    v.format !== "bms.sum8-macro-template-catalog" ||
    v.version !== 1 ||
    v.profile?.profile !== SUM8_PROFILE ||
    v.profile_sha256 !== SUM8_PROFILE_SHA ||
    !sourceEqual(
      v.units,
      unitOptions.map(({ value, label }) => ({ value, label })),
    ) ||
    !sourceEqual(v.exports, ["review", "bundle"]) ||
    v.native_compile !== false ||
    v.controller_writes !== false ||
    (await blobSha256(new Blob([canonicalProfile(v.profile)]))) !==
      SUM8_PROFILE_SHA
  )
    throw new Error(
      "Eight-input sum catalog uses an unsupported source profile or unit contract.",
    );
  return v;
}
export function previewResult(v: any, unit: string, catalog: Data) {
  const option = unitOptions.find((u) => u.value === unit),
    p = v?.program,
    b = v?.bundle,
    item = b?.library?.definitions?.[0],
    prov = p?.metadata?.sum8_macro_template;
  if (
    !option ||
    !object(v) ||
    v.format !== "bms.sum8-macro-template-preview" ||
    v.version !== 1 ||
    v.profile_sha256 !== catalog.profile_sha256 ||
    !sourceEqual(v.profile, catalog.profile) ||
    !sourceEqual(v.choices, { unit }) ||
    ![
      v.choices_sha256,
      v.definition_sha256,
      v.program_sha256,
      v.bundle_sha256,
    ].every(hash) ||
    v.definition_id !== "studio-sum8-" + option.id ||
    !object(p) ||
    p.id !== v.definition_id ||
    p.name !== "Eight-input sum (" + option.label + ")" ||
    p.revision !== 0 ||
    p.scan_seconds !== 1 ||
    !sourceEqual(p.target, {
      family: "universal-runtime",
      model: "",
      firmware: "",
      release_mode: "",
      max_nodes: 2000,
      physical_inputs: null,
      physical_outputs: null,
    }) ||
    p.metadata?.native_deployment_verified !== false ||
    prov?.profile !== SUM8_PROFILE ||
    prov.profile_sha256 !== v.profile_sha256 ||
    prov.choices_sha256 !== v.choices_sha256 ||
    !sourceEqual(prov.choices, { unit }) ||
    !sourceEqual(prov.source, catalog.profile.source) ||
    !sourceEqual(prov.unimplemented, catalog.profile.gaps) ||
    b?.format !== "bms-macro-library/1" ||
    b.root !== v.definition_id ||
    b.library?.version !== 1 ||
    b.library.definitions.length !== 1 ||
    item.id !== v.definition_id ||
    item.name !== p.name ||
    !sourceEqual(item.program, p) ||
    !Array.isArray(p.nodes) ||
    p.nodes.length !== 16 ||
    !Array.isArray(p.edges) ||
    p.edges.length !== 15 ||
    new Set(p.nodes.map((n: any) => n.id)).size !== 16 ||
    !Array.isArray(v.inputs) ||
    v.inputs.length !== 8 ||
    !Array.isArray(v.diagnostics) ||
    !v.diagnostics.every(
      (d: any) =>
        object(d) &&
        ["warning", "error"].includes(d.level) &&
        typeof d.code === "string" &&
        typeof d.message === "string",
    ) ||
    typeof v.can_import !== "boolean" ||
    v.can_import !== !v.diagnostics.some((d: any) => d.level === "error") ||
    v.native_compile !== false ||
    v.controller_writes !== false
  )
    throw new Error(
      "Eight-input sum preview does not match the exact unit, source, original definition or ordinary graph.",
    );
  const edges: Data[] = [];
  for (let i = 1; i <= 8; i++) {
    const n = p.nodes.find((n: any) => n.id === "i" + i);
    if (
      !n ||
      n.kind !== "Input" ||
      n.label !== "Input " + i ||
      n.unit !== unit ||
      n.value_type !== "number" ||
      Object.keys(n.params).join() !== "default" ||
      !Object.is(projectSourceDocument(n.params.default), 0) ||
      !sourceEqual(v.inputs[i - 1], {
        id: "i" + i,
        label: "Input " + i,
        value_type: "number",
        unit,
        required: true,
      })
    )
      throw new Error(
        "All eight sum ports require their declared numeric unit and explicit zero defaults.",
      );
    if (i >= 2) {
      const n = p.nodes.find((n: any) => n.id === "sum_" + i);
      if (
        !n ||
        n.kind !== "Add" ||
        n.unit !== unit ||
        n.value_type !== "number" ||
        Object.keys(n.params).length
      )
        throw new Error(
          "Sum template must use exactly seven ordinary Add blocks.",
        );
      edges.push(
        {
          id: `sum_${i}_a`,
          source: i === 2 ? "i1" : `sum_${i - 1}`,
          target: `sum_${i}`,
          source_port: "out",
          target_port: "a",
        },
        {
          id: `sum_${i}_b`,
          source: `i${i}`,
          target: `sum_${i}`,
          source_port: "out",
          target_port: "b",
        },
      );
    }
  }
  edges.push({
    id: "publish_sum",
    source: "sum_8",
    target: "result",
    source_port: "out",
    target_port: "in",
  });
  const out = p.nodes.find((n: any) => n.id === "result");
  if (
    !out ||
    out.kind !== "Output" ||
    out.value_type !== "number" ||
    out.unit !== unit ||
    Object.keys(out.params).length ||
    !sourceEqual(p.edges, edges) ||
    !sourceEqual(v.output, {
      id: "result",
      label: "Sum",
      value_type: "number",
      unit,
    })
  )
    throw new Error("Sum template output or fixed left-fold wiring changed.");
  return v;
}
