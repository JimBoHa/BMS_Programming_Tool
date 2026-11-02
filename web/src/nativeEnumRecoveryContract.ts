import { sha256Blob } from "./activityContracts";
type Data = Record<string, any>;
export const enumRecoveryProfile = "native-enum-default-recovery-draft/1";
const hash = (v: unknown) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const id = (v: unknown) => typeof v === "string" && /^[a-f0-9]{32}$/.test(v);
const code = (v: unknown) =>
  typeof v === "number" && Number.isInteger(v) && v >= 0 && v <= 65535;
const same = (a: Data | undefined, b: Data | undefined) =>
  !!a &&
  !!b &&
  Object.keys(a).length === Object.keys(b).length &&
  Object.entries(a).every(
    ([key, value]) => Object.hasOwn(b, key) && b[key] === value,
  );
const sameTarget = (a: Data, b: Data) =>
  ["address", "router", "dnet"].every(
    (key) => (a[key] ?? null) === (b[key] ?? null),
  );
function tagged(value: unknown, expected: number) {
  if (
    typeof value !== "string" ||
    !/^9[1-4](?:[a-f0-9]{2}){1,4}2f$/.test(value)
  )
    return false;
  return (
    value.length === (Number(value[1]) + 2) * 2 &&
    parseInt(value.slice(2, -2), 16) === expected
  );
}
function originMatches(origin: Data | undefined) {
  return (
    !!origin &&
    origin.profile === enumRecoveryProfile &&
    id(origin.parent_receipt_id) &&
    hash(origin.parent_intent_sha256) &&
    origin.original_dispatch === "possible" &&
    ["result", "readback-event"].includes(origin.verified_proof?.kind) &&
    hash(origin.verified_proof.sha256) &&
    typeof origin.verified_proof.time === "string" &&
    id(origin.original_backup_id) &&
    hash(origin.original_snapshot_sha256) &&
    id(origin.current_capture_id) &&
    hash(origin.current_snapshot_sha256) &&
    typeof origin.record_ref === "string" &&
    [528, 529].includes(origin.class_id) &&
    origin.property === 3113 &&
    origin.enum_semantics_verified === false &&
    (origin.states_text_encoded_sha256 === null ||
      hash(origin.states_text_encoded_sha256)) &&
    [
      "previous_effective_value",
      "recorded_after_value",
      "current_effective_value",
      "proposal_value",
    ].every((key) => code(origin[key])) &&
    origin.previous_effective_value !== origin.recorded_after_value &&
    origin.proposal_value === origin.previous_effective_value &&
    tagged(origin.previous_encoding_hex, origin.previous_effective_value) &&
    tagged(origin.recorded_after_encoding_hex, origin.recorded_after_value) &&
    tagged(origin.current_encoding_hex, origin.current_effective_value) &&
    tagged(origin.proposal_encoding_hex, origin.proposal_value)
  );
}

/** Bind the actual current tag bytes and the retained-width proposal independently. */
export async function enumRecoveryEncodingMatches(data: Data, selected: Data) {
  const origin = data.origin;
  if (!originMatches(origin)) return false;
  const bytes = new Uint8Array(
    origin.current_encoding_hex
      .match(/../g)
      .map((part: string) => parseInt(part, 16)),
  );
  const currentWidth = Number(origin.current_encoding_hex[1]);
  const minimum = Math.max(
    1,
    Math.ceil(origin.proposal_value.toString(16).length / 2),
  );
  const width = Math.max(currentWidth, minimum);
  return (
    (await sha256Blob(new Blob([bytes]))) === selected.encoded_sha256 &&
    origin.proposal_encoding_hex ===
      `9${width}${origin.proposal_value.toString(16).padStart(width * 2, "0")}2f`
  );
}

/** Recovery is optional. If present, bind every selected typed value and encoding. */
export function enumRecoveryTransferMatches(data: Data) {
  const origin = data.recovery_origin,
    compiled = data.compilation,
    edit = data.default_edit;
  if (origin === undefined) return data.recovery_origin_sha256 === undefined;
  return (
    originMatches(origin) &&
    hash(data.recovery_origin_sha256) &&
    origin.current_capture_id === (data.capture_id ?? data.review_capture_id) &&
    origin.current_snapshot_sha256 ===
      (data.snapshot_sha256 ?? data.review_snapshot_sha256) &&
    origin.record_ref === edit?.record_ref &&
    origin.class_id === compiled?.selected_edit?.class_id &&
    origin.current_effective_value === origin.recorded_after_value &&
    origin.current_effective_value === compiled.selected_edit.before_value &&
    origin.proposal_value === edit.value &&
    origin.current_encoding_hex ===
      compiled.selected_edit.before_encoding_hex &&
    origin.proposal_encoding_hex ===
      compiled.selected_edit.after_encoding_hex &&
    origin.states_text_encoded_sha256 === compiled.states_text_encoded_sha256 &&
    same(origin.saved_storage, compiled.saved_storage)
  );
}

export function previousEnumDefaultMatches(
  data: Data,
  source: Data,
  receipt: Data,
  selected: Data,
) {
  const origin = data.origin,
    parent = receipt.intent,
    edit = parent?.compilation?.selected_edit,
    field = source.fields?.find((row: Data) => row.ref === origin?.record_ref),
    proof = origin?.verified_proof;
  if (
    data.profile !== enumRecoveryProfile ||
    !hash(data.evidence_sha256) ||
    !hash(data.origin_sha256) ||
    !originMatches(origin) ||
    !parent ||
    !field ||
    !edit ||
    parent.change_kind !== "enum-default" ||
    parent.operation_profile !== "native-effective-enum-default-transfer/1" ||
    parent.enum_semantics_verified !== false ||
    receipt.pending !== false ||
    origin.parent_receipt_id !== parent.id ||
    origin.parent_intent_sha256 !== parent.evidence_sha256 ||
    origin.original_backup_id !== parent.backup_id ||
    origin.current_capture_id !== source.capture_id ||
    origin.current_snapshot_sha256 !== source.snapshot_sha256 ||
    origin.record_ref !== parent.default_edit?.record_ref ||
    origin.record_ref !== selected.ref ||
    origin.class_id !== field.class_id ||
    origin.class_id !== selected.class_id ||
    field.encoded_sha256 !== selected.encoded_sha256 ||
    field.effective_value !== selected.effective_value ||
    field.states_text_encoded_sha256 !== selected.states_text_encoded_sha256 ||
    origin.states_text_encoded_sha256 !== field.states_text_encoded_sha256 ||
    origin.states_text_encoded_sha256 !==
      parent.compilation.states_text_encoded_sha256 ||
    !same(origin.saved_storage, field.saved_storage) ||
    !same(origin.saved_storage, selected.saved_storage) ||
    !same(origin.saved_storage, parent.compilation.saved_storage) ||
    !code(edit.before_value) ||
    !code(edit.after_value) ||
    origin.previous_effective_value !== edit.before_value ||
    origin.recorded_after_value !== edit.after_value ||
    origin.current_effective_value !== field.effective_value ||
    origin.proposal_value !== edit.before_value ||
    origin.previous_encoding_hex !== edit.before_encoding_hex ||
    origin.recorded_after_encoding_hex !== edit.after_encoding_hex ||
    data.previous_effective_value !== edit.before_value ||
    data.recorded_after_value !== edit.after_value ||
    data.current_effective_value !== field.effective_value ||
    data.source?.capture_id !== source.capture_id ||
    data.source?.snapshot_sha256 !== source.snapshot_sha256 ||
    data.source?.source_identity_matches !== true ||
    data.source?.target?.device !== source.device ||
    data.source?.sha256 !== source.source_sha256 ||
    !sameTarget(data.source?.target ?? {}, source.target) ||
    !sameTarget(parent.target ?? {}, source.target) ||
    parent.identity?.device !== source.device ||
    parent.identity?.["vendor-identifier"] !== 5 ||
    source.identity?.["vendor-identifier"] !== 5 ||
    data.read_only !== true ||
    data.controller_queries !== false ||
    data.field_actions !== false ||
    data.can_apply !== false ||
    data.enum_semantics_verified !== false ||
    typeof data.already_recorded !== "boolean"
  )
    return false;
  const verified =
    proof.kind === "result"
      ? receipt.result?.status === "verified" &&
        receipt.result.evidence_sha256 === proof.sha256 &&
        receipt.result.finished_at === proof.time
      : receipt.events?.some(
          (event: Data) =>
            event.stage === "readback" &&
            event.detail?.status === "verified" &&
            event.evidence_sha256 === proof.sha256 &&
            event.created_at === proof.time,
        );
  if (!verified) return false;
  if (data.already_recorded)
    return (
      data.proposal === null &&
      data.new_review_required === false &&
      field.effective_value === edit.before_value
    );
  const proposal = data.proposal;
  return (
    data.new_review_required === true &&
    field.effective_value === edit.after_value &&
    proposal?.capture_id === source.capture_id &&
    proposal.snapshot_sha256 === source.snapshot_sha256 &&
    proposal.source_sha256 === source.source_sha256 &&
    proposal.record_ref === field.ref &&
    proposal.encoded_sha256 === field.encoded_sha256 &&
    proposal.recovery_parent_receipt === parent.id &&
    code(proposal.value) &&
    proposal.value === edit.before_value
  );
}
