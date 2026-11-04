import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { connectionSeal } from "./nativeConnectionContract";

type Data = Record<string, any>;
export const referenceProfile = "caf-reference-labels/1";
export const referenceCatalogHash =
  "d155e2fac61c7e0c0455f4e25d749831993b4f72b6ad8d433008f3840f3a4515";
const sourceHash =
  "ce867309de563177133975dcf02661696b11a7839a81a554f24c2cfedef8986e";
const sourceCommit = "c1d76ba7d6a8f17ca089c4671fa3333e4eba43e2";
const integer = (v: unknown) =>
  Number.isInteger(v) && (v as number) >= 0 && (v as number) <= 4294967295;

function field(v: Data, pid: number, sets: number[]) {
  if (
    !v ||
    v.property_id !== pid ||
    !["absent", "unsupported_encoding", "unmapped", "reference_label"].includes(
      v.status,
    )
  )
    return false;
  if (v.status === "absent" || v.status === "unsupported_encoding")
    return (
      v.enum_set === null &&
      v.code === null &&
      v.reference_name === null &&
      (v.status !== "absent" || v.observed === null)
    );
  if (
    !sets.includes(v.enum_set) ||
    !integer(v.code) ||
    v.observed?.type !== "enum" ||
    v.observed.text !== String(v.code) ||
    !v.observed.attributes ||
    Object.keys(v.observed.attributes).length !== 1 ||
    v.observed.attributes.set !== String(v.enum_set)
  )
    return false;
  return v.status === "unmapped"
    ? v.reference_name === null
    : typeof v.reference_name === "string" &&
        v.reference_name.length > 0 &&
        [...v.reference_name].length <= 4096 &&
        !v.reference_name.includes("\0");
}
export async function admitReferenceLabels(
  v: Data,
  archive: string,
  diagram: Data,
) {
  const c = v?.catalog,
    s = c?.source;
  if (
    !v ||
    v.profile !== referenceProfile ||
    v.source_sha256 !== archive ||
    v.diagram_ref !== diagram.ref ||
    v.controller_write !== false ||
    v.field_requests !== 0 ||
    v.runtime_meaning_verified !== false ||
    c?.profile !== "oct-fdb-control-10.8-firmware-12.0/1" ||
    c.sha256 !== referenceCatalogHash ||
    c.archive_compatibility_verified !== false ||
    s?.repository !== "https://github.com/thecontrolscompany/oct" ||
    s.commit !== sourceCommit ||
    s.path !== "ui/src/data/fdbEnums.ts" ||
    s.sha256 !== sourceHash ||
    s.database !== "FDB_Control_10_8___Firmware_12_0" ||
    s.license !== "Apache-2.0" ||
    !Array.isArray(c.sets) ||
    c.sets.length !== 3 ||
    !c.sets.every(
      (r: Data, i: number) =>
        r.id === [287, 288, 432][i] &&
        r.members === [6, 23, 11152][i] &&
        typeof r.name === "string",
    ) ||
    !Array.isArray(v.rows) ||
    v.rows.length !== diagram.blocks.length
  )
    return false;
  for (let i = 0; i < v.rows.length; i++) {
    const r = v.rows[i],
      b = diagram.blocks[i];
    if (
      !r ||
      r.index !== b.index ||
      r.ref !== b.ref ||
      r.class_id !== b.class_id ||
      r.instance !== b.instance ||
      !field(r.standard_name, 3670, [432]) ||
      !field(r.setup, 518, [287, 288])
    )
      return false;
  }
  const { annotation_sha256, ...body } = v;
  return (
    typeof annotation_sha256 === "string" &&
    /^[a-f0-9]{64}$/.test(annotation_sha256) &&
    (await connectionSeal(body)) === annotation_sha256
  );
}

export type ReferenceState = { data: Data | null; error: string };
/** Local catalog metadata never participates in a creation review or field plan. */
export function useCafReferenceLabels(
  archive: string,
  diagram: Data,
  context: string,
  enabled: boolean,
): ReferenceState {
  const owner = JSON.stringify([archive, diagram.ref, context, enabled]),
    now = useRef(owner),
    generation = useRef(0);
  if (now.current !== owner) {
    now.current = owner;
    generation.current++;
  }
  const [result, setResult] = useState<{
    owner: string;
    data: Data | null;
    error: string;
  } | null>(null);
  useEffect(() => {
    if (!enabled) return;
    let active = true;
    const stamp = generation.current;
    const current = () =>
      active && now.current === owner && generation.current === stamp;
    api(
      `/caf/${archive}/reference-labels?ref=${encodeURIComponent(diagram.ref)}`,
    )
      .then(async (data) => {
        if (!(await admitReferenceLabels(data, archive, diagram)))
          throw Error(
            "Reference-name evidence does not match this CAF diagram.",
          );
        if (current()) setResult({ owner, data, error: "" });
      })
      .catch(() => {
        if (current())
          setResult({
            owner,
            data: null,
            error:
              "Reference names unavailable. Raw references and existing CAF tools remain available.",
          });
      });
    return () => {
      active = false;
    };
  }, [owner]);
  return result?.owner === owner ? result : { data: null, error: "" };
}
