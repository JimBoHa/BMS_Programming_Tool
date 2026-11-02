import { EXCEPTION_PROFILE, EXCEPTION_RULES } from "./nativeScheduleExceptions";
import { ordered } from "./nativeCalendar";
export {
  calendarDocumentSha,
  calendarEndpoint,
  sameCalendarTarget,
} from "./nativeCalendarWrite";
import { calendarTarget, sameCalendarTarget } from "./nativeCalendarWrite";

export const EXCEPTION_WRITE_BASE = "/bacnet/schedule-exceptions/writes";
export const EXCEPTION_WRITE_PROFILE =
  "native-schedule-reviewed-exception-write/1";
export const EXCEPTION_WRITE_RULES =
  "3f17f31c560b241cd248414915a3fe519462e653ee8e1dbb02eb2d16ea9bc381";
const hex = (v: any, size: number) =>
  typeof v === "string" && new RegExp(`^[a-f0-9]{${size}}$`).test(v);
const text = (v: any, size = 4096) => typeof v === "string" && v.length <= size;
const operation = (v: any) =>
  typeof v === "string" && /^[A-Za-z0-9_-]{8,80}$/.test(v);
const strings = (v: any) =>
  Array.isArray(v) && v.length <= 64 && v.every((s: any) => text(s));
const schedule = (v: any) =>
  typeof v === "string" &&
  /^schedule,(0|[1-9][0-9]{0,6})$/.test(v) &&
  Number(v.split(",")[1]) <= 4194302;
const domain = (v: any) =>
  v?.profile === EXCEPTION_WRITE_PROFILE &&
  v.rules_sha256 === EXCEPTION_WRITE_RULES;
function coherentReadback(v: any) {
  return (
    v?.status !== "match" ||
    (v.selected_value_matches === true &&
      v.other_static_context_matches === true)
  );
}
function localReview(v: any) {
  return (
    v?.profile === EXCEPTION_PROFILE &&
    v.rules_sha256 === EXCEPTION_RULES &&
    hex(v.id, 64) &&
    hex(v.source?.capture_id, 64) &&
    v.source.source_sha256 === v.source.capture_id &&
    schedule(v.source.object) &&
    calendarTarget(v.source.target) &&
    v.request?.capture_id === v.source.capture_id &&
    v.request.object_id === v.source.object &&
    Array.isArray(v.request.events) &&
    v.request.events.length <= 32 &&
    typeof v.diff?.changed === "boolean" &&
    Number.isInteger(v.diff.old_count) &&
    v.diff.old_count >= 0 &&
    v.diff.old_count <= 32 &&
    Number.isInteger(v.diff.new_count) &&
    v.diff.new_count === v.request.events.length &&
    typeof v.new?.encoded_hex === "string" &&
    /^(?:[a-f0-9]{2})*$/.test(v.new.encoded_hex) &&
    v.new.encoded_hex.length <= 512 * 1024 &&
    v.new.roundtrip_tags_exhausted === true &&
    v.new.target_revision_verified === false &&
    v.new.Calendar_references_queried === false &&
    [null, 18].includes(v.new.minimum_known_protocol_revision)
  );
}
const sameSource = (v: any, draft: any) =>
  localReview(draft) &&
  v.draft_id === draft.id &&
  v.source_sha256 === draft.source.source_sha256 &&
  v.object_id === draft.source.object &&
  sameCalendarTarget(v.target, draft.source.target) &&
  v.property === "exception-schedule" &&
  v.array_index === null;
function serviceBody(draft: any) {
  const instance = Number(draft.source.object.split(",")[1]);
  return (
    "0c" +
    ((17 << 22) | instance).toString(16).padStart(8, "0") +
    "19263e" +
    draft.new.encoded_hex +
    "3f"
  );
}
export function exceptionWriteProfile(v: any) {
  const journal = v?.journal;
  if (
    !domain(v) ||
    v.automatic_retries !== false ||
    !journal ||
    journal.max_records !== 64 ||
    journal.max_bytes !== 67108864 ||
    journal.record_bytes !== 8388608 ||
    journal.automatic_eviction !== false ||
    !Number.isSafeInteger(journal.used_bytes) ||
    journal.used_bytes < 0 ||
    journal.used_bytes > journal.max_bytes ||
    !Array.isArray(journal.records) ||
    journal.records.length > 64 ||
    journal.records.some(
      (r: any) =>
        !hex(r?.id, 32) ||
        !text(r.created, 128) ||
        ![0, 1].includes(r.unresolved),
    ) ||
    new Set(journal.records.map((r: any) => r.id)).size !==
      journal.records.length ||
    (v.active_operation !== null && !operation(v.active_operation))
  )
    throw new Error(
      "Schedule exception write profile is malformed or unsupported.",
    );
  return v;
}
export function exceptionWritePreview(
  v: any,
  draft: any,
  id: string,
  operator: string,
  rationale: string,
) {
  if (
    !domain(v) ||
    !hex(v.id, 32) ||
    v.operation_id !== id ||
    !sameSource(v, draft) ||
    ordered(v.native_draft) !== ordered(draft) ||
    v.operator_name !== operator ||
    v.rationale !== rationale ||
    typeof v.can_apply !== "boolean" ||
    !text(v.status, 80) ||
    !strings(v.reasons) ||
    v.automatic_retries !== false
  )
    throw new Error(
      "Schedule exception review differs from this operation, source or draft.",
    );
  if (v.can_apply) {
    const bytes = serviceBody(draft),
      remote = v.capabilities?.remote_max_apdu;
    if (
      v.status !== "review_required" ||
      !hex(v.review_sha256, 64) ||
      !/^[A-Za-z0-9_-]{32}$/.test(v.token) ||
      !Number.isFinite(Date.parse(v.expires_at)) ||
      !Number.isFinite(Date.parse(v.created_at)) ||
      Date.parse(v.expires_at) - Date.parse(v.created_at) <= 0 ||
      // created_at precedes the bounded fresh reads; the 30-second plan starts afterward.
      Date.parse(v.expires_at) - Date.parse(v.created_at) > 45000 ||
      v.fresh?.complete !== true ||
      v.fresh.identity_verified !== true ||
      v.fresh.objects?.length !== 1 ||
      v.fresh.objects[0].object !== v.object_id ||
      v.fresh.objects[0].identity_verified !== true ||
      !sameCalendarTarget(v.fresh.target, v.target) ||
      !Number.isInteger(remote) ||
      remote < 50 ||
      remote > 65535 ||
      !hex(v.static_native_sha256, 64) ||
      (draft.new.minimum_known_protocol_revision === 18 &&
        (!Number.isInteger(v.capabilities.protocol_revision) ||
          v.capabilities.protocol_revision < 18)) ||
      ordered(v.capabilities.calendar_references) !==
        ordered(
          [
            ...new Set<string>(
              draft.new.events
                .filter(
                  (event: any) => event.period.kind === "calendarReference",
                )
                .map((event: any) => event.period.object_id),
            ),
          ].sort(),
        ) ||
      v.request_service_body_hex !== bytes ||
      v.request_apdu_bytes !== bytes.length / 2 + 4 ||
      v.request_apdu_bytes > Math.min(480, remote)
    )
      throw new Error(
        "Schedule exception review has no exact bounded Apply authority.",
      );
  } else if (v.token !== null)
    throw new Error("Deferred Schedule exception review cannot grant a token.");
  return v;
}
export function exceptionWriteReceipt(v: any, id?: string) {
  const intent = v?.journal_state === "intent_only",
    draft = v?.review?.native_draft;
  if (
    !domain(v) ||
    !hex(v.id, 32) ||
    (id != null && v.id !== id) ||
    !operation(v.operation_id) ||
    !hex(v.evidence_sha256, 64) ||
    !hex(v.review_sha256, 64) ||
    !sameSource(v, draft) ||
    !domain(v.review) ||
    v.review.can_apply !== true ||
    v.review.review_sha256 !== v.review_sha256 ||
    !sameSource(v.review, draft) ||
    v.review.token !== null ||
    v.automatic_retries !== false ||
    !strings(v.errors) ||
    !coherentReadback(v.readback) ||
    !text(v.status, 80) ||
    (v.intent_sha256 != null && !hex(v.intent_sha256, 64)) ||
    (v.journal_error != null && !text(v.journal_error)) ||
    (intent
      ? v.dispatch_started !== null ||
        v.protocol_accepted !== null ||
        v.protocol_status !== "unknown" ||
        v.may_have_applied !== true ||
        v.readback?.status !== "unknown"
      : typeof v.dispatch_started !== "boolean" ||
        v.may_have_applied !== v.dispatch_started ||
        !["accepted", "rejected", "unknown", "not_sent"].includes(
          v.protocol_status,
        ) ||
        v.protocol_accepted !==
          (
            {
              accepted: true,
              rejected: false,
              unknown: null,
              not_sent: false,
            } as Record<string, boolean | null>
          )[v.protocol_status] ||
        !["match", "mismatch", "unavailable", "not_attempted"].includes(
          v.readback?.status,
        ))
  )
    throw new Error(
      "Schedule exception receipt is malformed, unsupported or belongs to another selection.",
    );
  if (v.dispatch_started === true || intent) {
    const wire = v.native_request,
      bytes = serviceBody(draft);
    if (
      !wire ||
      wire.service_choice !== 15 ||
      wire.array_index !== null ||
      wire.request_priority !== null ||
      !hex(wire.apdu_sha256, 64) ||
      typeof wire.apdu_hex !== "string" ||
      !/^[a-f0-9]+$/.test(wire.apdu_hex) ||
      !Number.isInteger(wire.invoke_id) ||
      wire.invoke_id < 0 ||
      wire.invoke_id > 255 ||
      wire.apdu_bytes !== wire.apdu_hex.length / 2 ||
      wire.apdu_bytes !== bytes.length / 2 + 4 ||
      wire.apdu_bytes > 480 ||
      !["00", "02"].includes(wire.apdu_hex.slice(0, 2)) ||
      wire.apdu_hex.slice(4, 6) !==
        wire.invoke_id.toString(16).padStart(2, "0") ||
      wire.apdu_hex.slice(6, 8) !== "0f" ||
      wire.apdu_hex.slice(8) !== bytes
    )
      throw new Error(
        "Schedule exception receipt request differs from its original reviewed replacement.",
      );
  }
  return v;
}
export function exceptionAppliedReceipt(v: any, preview: any, id: string) {
  exceptionWriteReceipt(v);
  if (
    v.operation_id !== id ||
    v.review_sha256 !== preview.review_sha256 ||
    ordered(v.review) !== ordered({ ...preview, token: null })
  )
    throw new Error(
      "Schedule exception Apply receipt differs from this owned review and operation.",
    );
  return v;
}
export function exceptionReconciliation(
  v: any,
  receipt: any,
  sha: string,
  id: string,
) {
  if (
    !domain(v) ||
    v.operation_id !== id ||
    v.receipt_id !== receipt.id ||
    v.receipt_sha256 !== sha ||
    !sameCalendarTarget(v.target, receipt.target) ||
    v.object_id !== receipt.object_id ||
    v.property !== "exception-schedule" ||
    v.array_index !== null ||
    v.read_only !== true ||
    v.writes_sent !== 0 ||
    !coherentReadback(v.readback) ||
    !hex(v.evidence_sha256, 64) ||
    !["match", "mismatch", "unavailable"].includes(v.readback?.status)
  )
    throw new Error(
      "Schedule exception readback differs from the selected original receipt.",
    );
  return v;
}
