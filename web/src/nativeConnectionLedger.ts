import { matchingConnectionProfile } from "./nativeMatchingConnectionContract";

export const CONNECTION_LEDGER_SCOPE =
  "Recorded connection proposal and compilation bindings only. No original-backup " +
  "revalidation, current graph reading, controller query or transfer authority.";
const integer = (v: unknown, max = 65535) =>
  Number.isSafeInteger(v) && (v as number) >= 0 && (v as number) <= max;
const reference = (v: unknown) =>
  typeof v === "string" &&
  Array.from(v).length > 0 &&
  Array.from(v).length <= 512 &&
  !/[\u0000-\u001f\u007f]/.test(v) &&
  new TextDecoder().decode(new TextEncoder().encode(v)) === v;
const tuple = (v: any) =>
  Array.isArray(v) && v.length === 4 && v.every((n) => integer(n));
export type RecordedConnection = {
  state: "recorded";
  profile: string;
  diagram_ref: string;
  prototype_index: number;
  prototype_old: number[];
  index: number;
  new: number[];
  source_ref: string;
  target_ref: string;
  connection_count_before: number;
  connection_count_after: number;
  compiled_native_sha256: string;
  connection_confirmation_recorded: boolean;
  scope: string;
};
export function recordedConnection(v: any): RecordedConnection | null {
  const keys = [
    "state",
    "profile",
    "diagram_ref",
    "prototype_index",
    "prototype_old",
    "index",
    "new",
    "source_ref",
    "target_ref",
    "connection_count_before",
    "connection_count_after",
    "compiled_native_sha256",
    "connection_confirmation_recorded",
    "scope",
  ];
  if (
    !v ||
    typeof v !== "object" ||
    Array.isArray(v) ||
    Object.keys(v).length !== keys.length ||
    !keys.every((k) => Object.hasOwn(v, k)) ||
    v.state !== "recorded" ||
    v.profile !== matchingConnectionProfile ||
    v.scope !== CONNECTION_LEDGER_SCOPE ||
    ![v.diagram_ref, v.source_ref, v.target_ref].every(reference) ||
    v.source_ref === v.target_ref ||
    !integer(v.connection_count_before, 4095) ||
    v.connection_count_before === 0 ||
    !integer(v.connection_count_after, 4096) ||
    v.connection_count_after !== v.connection_count_before + 1 ||
    v.index !== v.connection_count_before ||
    !integer(v.index, 4095) ||
    !integer(v.prototype_index, v.connection_count_before - 1) ||
    !tuple(v.prototype_old) ||
    !tuple(v.new) ||
    v.new[0] === v.new[2] ||
    v.new[2] === v.prototype_old[2] ||
    v.new[1] !== v.prototype_old[1] ||
    v.new[3] !== v.prototype_old[3] ||
    typeof v.compiled_native_sha256 !== "string" ||
    !/^[a-f0-9]{64}$/.test(v.compiled_native_sha256) ||
    typeof v.connection_confirmation_recorded !== "boolean"
  )
    return null;
  return { ...v, prototype_old: [...v.prototype_old], new: [...v.new] };
}
