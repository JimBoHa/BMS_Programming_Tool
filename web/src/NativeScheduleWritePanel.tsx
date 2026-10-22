import { useEffect, useRef, useState } from "react";
import {
  api,
  apiJsonDocument,
  apiKeepalive,
  saveBlob,
  type JsonDocument,
} from "./api";

const BASE = "/bacnet/schedules/writes";
const PROFILE = "native-schedule-reviewed-weekly-day-write/1";
const hex = (value: unknown, length: number): value is string =>
  typeof value === "string" && new RegExp(`^[a-f0-9]{${length}}$`).test(value);
const text = (value: unknown, maximum = 4096): value is string =>
  typeof value === "string" && value.length <= maximum;
type Target = {
  device: string;
  address: string;
  router?: string | null;
  dnet?: number | null;
};
type Binding = {
  id: string;
  source: {
    source_sha256: string;
    capture_id: string;
    object: string;
    day: number;
    target: Target;
  };
};
type Document = JsonDocument<any>;
type PreparedDocument = Document & { authority: string };
type Owned = {
  id: string;
  kind: "preview" | "apply" | "reconcile";
  key: string;
  retired: boolean;
};
const targetKey = (value: Target) =>
  JSON.stringify([
    value.device,
    value.address,
    value.router ?? null,
    value.dnet ?? null,
  ]);
function target(value: any): value is Target {
  return (
    text(value?.device, 128) &&
    text(value?.address, 256) &&
    (value.router == null || text(value.router, 256)) &&
    (value.dnet == null ||
      (Number.isInteger(value.dnet) && value.dnet >= 1 && value.dnet <= 65534))
  );
}
const strings = (value: any, maximum = 64) =>
  Array.isArray(value) &&
  value.length <= maximum &&
  value.every((item: any) => text(item));
function profileResult(value: any) {
  if (
    value?.profile !== PROFILE ||
    !hex(value.rules_sha256, 64) ||
    !Array.isArray(value.journal?.records) ||
    value.journal.records.length > 64 ||
    !Number.isSafeInteger(value.journal.used_bytes) ||
    value.journal.used_bytes < 0 ||
    value.journal.used_bytes > 67108864 ||
    value.journal.records.some(
      (row: any) =>
        !hex(row?.id, 32) ||
        !text(row.created) ||
        ![0, 1].includes(row.unresolved),
    ) ||
    new Set(value.journal.records.map((row: any) => row.id)).size !==
      value.journal.records.length ||
    (value.active_operation !== null && !text(value.active_operation, 80))
  )
    throw new Error("Native write profile is malformed or unsupported.");
  return value;
}
function sameSource(value: any, binding: Binding) {
  return (
    value.draft_id === binding.id &&
    value.source_sha256 === binding.source.source_sha256 &&
    value.object_id === binding.source.object &&
    value.day === binding.source.day &&
    target(value.target) &&
    targetKey(value.target) === targetKey(binding.source.target)
  );
}
function previewResult(
  value: any,
  binding: Binding,
  operation: string,
  operator: string,
  rationale: string,
  rules: string,
) {
  if (
    value?.profile !== PROFILE ||
    value.operation_id !== operation ||
    value.rules_sha256 !== rules ||
    !hex(value.id, 32) ||
    !sameSource(value, binding) ||
    value.operator_name !== operator ||
    value.rationale !== rationale ||
    typeof value.can_apply !== "boolean" ||
    !text(value.status) ||
    !strings(value.reasons) ||
    value.native_draft?.id !== binding.id ||
    value.native_draft?.source?.capture_id !== binding.source.capture_id ||
    !Array.isArray(value.native_draft?.new?.transitions) ||
    value.native_draft.new.transitions.length > 32 ||
    value.native_draft.new.transitions.some(
      (row: any) =>
        !Array.isArray(row?.time) ||
        row.time.length !== 4 ||
        row.time.some(
          (part: any, index: number) =>
            !Number.isInteger(part) ||
            part < 0 ||
            part > [23, 59, 59, 99][index],
        ) ||
        ![
          "Null",
          "Boolean",
          "Unsigned",
          "Integer",
          "Enumerated",
          "Real",
          "Double",
        ].includes(row.native_type) ||
        !text(row.value_text, 256) ||
        !text(row.wire_value_text, 256),
    ) ||
    value.automatic_retries !== false
  )
    throw new Error(
      "Fresh native preview does not match the selected draft, source or operation.",
    );
  if (
    value.can_apply &&
    (value.status !== "review_required" ||
      !hex(value.review_sha256, 64) ||
      typeof value.token !== "string" ||
      !/^[A-Za-z0-9_-]{32}$/.test(value.token) ||
      !text(value.expires_at) ||
      !Number.isFinite(Date.parse(value.expires_at)) ||
      value.fresh?.complete !== true ||
      value.fresh?.identity_verified !== true ||
      !Number.isInteger(value.request_apdu_bytes) ||
      value.request_apdu_bytes < 4 ||
      value.request_apdu_bytes > 480 ||
      !Number.isInteger(value.remote_max_apdu) ||
      value.remote_max_apdu < value.request_apdu_bytes ||
      typeof value.request_service_body_hex !== "string" ||
      !/^[a-f0-9]+$/.test(value.request_service_body_hex) ||
      value.request_service_body_hex.length !==
        (value.request_apdu_bytes - 4) * 2)
  )
    throw new Error(
      "Fresh native preview has no exact bounded Apply authority.",
    );
  return value;
}
function receiptResult(value: any, id?: string) {
  const unresolved = value?.journal_state === "intent_only";
  if (
    value?.profile !== PROFILE ||
    !hex(value.id, 32) ||
    (id && value.id !== id) ||
    !hex(value.evidence_sha256, 64) ||
    !hex(value.draft_id, 64) ||
    !hex(value.source_sha256, 64) ||
    !text(value.operation_id, 80) ||
    !target(value.target) ||
    !text(value.object_id, 128) ||
    !Number.isInteger(value.day) ||
    value.day < 1 ||
    value.day > 7 ||
    !strings(value.errors) ||
    (value.journal_error != null && !text(value.journal_error)) ||
    (value.intent_sha256 != null && !hex(value.intent_sha256, 64)) ||
    value.automatic_retries !== false ||
    (unresolved
      ? value.dispatch_started !== null ||
        value.protocol_accepted !== null ||
        value.protocol_status !== "unknown" ||
        value.may_have_applied !== true ||
        value.readback?.status !== "unknown"
      : typeof value.dispatch_started !== "boolean" ||
        typeof value.protocol_accepted !== "boolean" ||
        typeof value.may_have_applied !== "boolean" ||
        value.may_have_applied !== value.dispatch_started ||
        !["accepted", "rejected", "unknown", "not_sent"].includes(
          value.protocol_status,
        ) ||
        value.protocol_accepted !== (value.protocol_status === "accepted") ||
        !["match", "mismatch", "unavailable", "not_attempted"].includes(
          value.readback?.status,
        ))
  )
    throw new Error(
      "Native write receipt is malformed, unsupported or belongs to another selection.",
    );
  return value;
}
const endpoint = (value: Target) =>
  `${value.device} at ${value.address}${value.router ? ` via ${value.router} / ${value.dnet}` : ""}`;
function nativeEnum(value: any) {
  return value &&
    Number.isInteger(value.value) &&
    text(value.native_datatype, 64)
    ? `${value.native_datatype}: ${value.known === true && text(value.name) ? value.name : "unknown native enum"} (${value.value})`
    : "Native reason is retained in the original receipt.";
}
async function sha(blob: Blob) {
  return Array.from(
    new Uint8Array(
      await crypto.subtle.digest("SHA-256", await blob.arrayBuffer()),
    ),
    (v) => v.toString(16).padStart(2, "0"),
  ).join("");
}

export function NativeScheduleWritePanel({
  draft,
  connected,
  connectionKey,
}: {
  draft: Binding | null;
  connected: boolean;
  connectionKey: string;
}) {
  const [opened, setOpened] = useState(false),
    [profile, setProfile] = useState<any>(null),
    [operator, setOperator] = useState(""),
    [rationale, setRationale] = useState(""),
    [prepared, setPrepared] = useState<PreparedDocument | null>(null),
    [expiredId, setExpiredId] = useState(""),
    [receipt, setReceipt] = useState<Document | null>(null),
    [observation, setObservation] = useState<Document | null>(null),
    [busy, setBusy] = useState(""),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const alive = useRef(true),
    own = useRef<Owned | null>(null),
    localTicket = useRef(0),
    historyTicket = useRef(0);
  const authority = JSON.stringify([
      draft?.id ?? null,
      connectionKey,
      connected,
      operator,
      rationale,
    ]),
    authorityNow = useRef(authority);
  authorityNow.current = authority;
  const receiptNow = useRef(receipt?.data.id || "");
  receiptNow.current = receipt?.data.id || "";
  const valid = (operation: Owned) =>
    alive.current &&
    own.current === operation &&
    !operation.retired &&
    authorityNow.current === operation.key;
  function retire(send = true) {
    const operation = own.current;
    if (operation && !operation.retired) {
      operation.retired = true;
      if (send)
        void apiKeepalive(BASE + "/cancel", {
          operation_id: operation.id,
        }).catch(() => {});
      if (alive.current)
        setNotice(
          operation.kind === "apply"
            ? "The earlier Apply is no longer current. It may already have applied; open its journal receipt before considering a fresh attempt."
            : "The earlier operation is no longer current. Its late response cannot authorize Apply.",
        );
    }
    setPrepared(null);
  }
  useEffect(() => {
    retire();
  }, [authority]);
  useEffect(() => {
    if (!prepared?.data.can_apply) return;
    const id = prepared.data.id,
      expires = Date.parse(prepared.data.expires_at);
    const check = () => {
      if (Date.now() >= expires) setExpiredId(id);
    };
    check();
    const timer = setInterval(check, 250);
    return () => clearInterval(timer);
  }, [prepared]);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      localTicket.current++;
      historyTicket.current++;
      const operation = own.current;
      if (operation && !operation.retired) {
        operation.retired = true;
        void apiKeepalive(BASE + "/cancel", {
          operation_id: operation.id,
        }).catch(() => {});
      }
    };
  }, []);
  async function refresh() {
    const ticket = ++localTicket.current;
    try {
      const result = profileResult(await api(BASE + "/profile"));
      if (alive.current && localTicket.current === ticket) setProfile(result);
    } catch (failure) {
      if (alive.current && localTicket.current === ticket) {
        setPrepared(null);
        setError(String(failure));
      }
    }
  }
  async function run(
    kind: Owned["kind"],
    body: any,
    accept: (result: Document, operation: Owned) => Promise<void> | void,
  ) {
    if (own.current) return;
    const operation: Owned = {
      id: `${kind}_${crypto.randomUUID().replaceAll("-", "")}`,
      kind,
      key: authorityNow.current,
      retired: false,
    };
    own.current = operation;
    setBusy(kind);
    setError("");
    setNotice("");
    try {
      const result = await apiJsonDocument(BASE + "/" + kind, {
        ...body,
        operation_id: operation.id,
      });
      if (result.blob.size > 8 * 1024 * 1024)
        throw new Error(
          "Native operation evidence exceeds its bounded response profile.",
        );
      if (valid(operation)) await accept(result, operation);
    } catch (failure) {
      if (valid(operation))
        setError(
          kind === "apply"
            ? `Apply outcome is unconfirmed: ${String(failure)}. Check the local journal; no retry was sent.`
            : String(failure),
        );
    } finally {
      if (own.current === operation) own.current = null;
      if (alive.current) {
        setBusy("");
        if (kind === "apply") void refresh();
      }
    }
  }
  async function preview() {
    if (!draft || !connected || !operator.trim() || !rationale.trim()) return;
    const binding = draft,
      name = operator.trim(),
      why = rationale.trim();
    setPrepared(null);
    await run(
      "preview",
      { draft_id: binding.id, operator_name: name, rationale: why },
      (result, operation) => {
        previewResult(
          result.data,
          binding,
          operation.id,
          name,
          why,
          profile.rules_sha256,
        );
        setPrepared({ ...result, authority: operation.key });
      },
    );
  }
  async function apply() {
    const candidate = prepared,
      binding = draft;
    if (!candidate?.data.can_apply || !binding || !connected || own.current)
      return;
    // A new render can expose new props before passive cleanup has retired the
    // old plan. The captured authority must match here, before any native POST.
    if (
      candidate.authority !== authorityNow.current ||
      candidate.data.rules_sha256 !== profile?.rules_sha256 ||
      !sameSource(candidate.data, binding)
    )
      return;
    if (
      expiredId === candidate.data.id ||
      Date.now() >= Date.parse(candidate.data.expires_at)
    ) {
      setExpiredId(candidate.data.id);
      setNotice(
        "This native review expired. Preview again before considering Apply; the server also validates expiry.",
      );
      return;
    }
    setPrepared(null); // consume UI authority synchronously, before any await
    await run(
      "apply",
      {
        token: candidate.data.token,
        review_sha256: candidate.data.review_sha256,
      },
      (result, operation) => {
        const body = receiptResult(result.data);
        if (
          body.operation_id !== operation.id ||
          !sameSource(body, binding) ||
          body.review_sha256 !== candidate.data.review_sha256
        )
          throw new Error(
            "Apply receipt does not match this exact operation and reviewed source.",
          );
        historyTicket.current++;
        setReceipt(result);
        setObservation(null);
      },
    );
  }
  async function openReceipt(id: string) {
    const ticket = ++historyTicket.current;
    setError("");
    setObservation(null);
    try {
      const result = await apiJsonDocument(BASE + "/receipts/" + id);
      if (result.blob.size > 8 * 1024 * 1024)
        throw new Error("Native receipt exceeds its bounded response profile.");
      receiptResult(result.data, id);
      if (alive.current && historyTicket.current === ticket) setReceipt(result);
    } catch (failure) {
      if (alive.current && historyTicket.current === ticket)
        setError(String(failure));
    }
  }
  async function reconcile() {
    if (!receipt || !connected || own.current) return;
    const selected = receipt,
      id = selected.data.id,
      ticket = historyTicket.current,
      key = authorityNow.current,
      digest = await sha(selected.blob);
    if (
      !alive.current ||
      authorityNow.current !== key ||
      receiptNow.current !== id ||
      historyTicket.current !== ticket
    )
      return;
    await run("reconcile", { receipt_id: id }, (result, operation) => {
      const value = result.data;
      if (
        value?.profile !== PROFILE ||
        value.operation_id !== operation.id ||
        value.receipt_id !== id ||
        value.receipt_sha256 !== digest ||
        value.read_only !== true ||
        value.writes_sent !== 0 ||
        !hex(value.evidence_sha256, 64) ||
        !target(value.target) ||
        targetKey(value.target) !== targetKey(selected.data.target) ||
        !["match", "mismatch", "unavailable"].includes(value.readback?.status)
      )
        throw new Error(
          "Read-only reconciliation does not match the selected original receipt.",
        );
      if (historyTicket.current === ticket && receiptNow.current === id)
        setObservation(result);
    });
  }
  async function cancel() {
    const operation = own.current;
    if (!operation) return;
    const currentCancellation = () =>
      alive.current &&
      authorityNow.current === operation.key &&
      (own.current === operation || own.current === null);
    retire(false);
    try {
      const result = await api(BASE + "/cancel", {
        operation_id: operation.id,
      });
      if (
        result?.operation_id !== operation.id ||
        typeof result.cancel_requested !== "boolean"
      )
        throw new Error(
          "Cancellation response did not match the owned operation.",
        );
      if (currentCancellation())
        setNotice(
          result.cancel_requested
            ? "Cancellation requested for the active operation. A transmitted write cannot be undone; check its journal receipt."
            : "The named operation was no longer active. Late UI authority was discarded; a ready server token expires separately.",
        );
    } catch (failure) {
      if (currentCancellation())
        setError(
          `Cancellation was not confirmed: ${String(failure)}. The operation may continue.`,
        );
    }
  }
  function download(document: Document, filename: string) {
    saveBlob(document.blob, filename);
  }
  const result = receipt?.data,
    recovered = result?.journal_state === "intent_only",
    preparedCurrent =
      prepared?.authority === authority &&
      prepared?.data.rules_sha256 === profile?.rules_sha256,
    expired =
      !!prepared?.data.can_apply &&
      (expiredId === prepared.data.id ||
        Date.now() >= Date.parse(prepared.data.expires_at));
  return (
    <section aria-label="Native weekly-day deployment">
      <h4>Native weekly-day deployment</h4>
      {!opened ? (
        <button
          onClick={() => {
            setOpened(true);
            void refresh();
          }}
        >
          Open native deployment and local history
        </button>
      ) : (
        <>
          <p>
            One existing BACnet Schedule day. Preview reads fresh controller
            context; Apply makes one guarded write attempt. Offline draft review
            alone cannot authorize a write.
          </p>
          <div className="toolbar">
            <button onClick={() => void refresh()}>
              Refresh native write journal
            </button>
            <button
              onClick={() => {
                retire();
                localTicket.current++;
                historyTicket.current++;
                setOpened(false);
              }}
            >
              Close native deployment workspace
            </button>
          </div>
          {busy && (
            <p role="status">
              Native {busy} is pending. No automatic retry or reconnect.
            </p>
          )}
          {busy && (
            <button onClick={() => void cancel()}>
              Cancel active native operation
            </button>
          )}
          {error && <p role="alert">{error}</p>}
          {notice && <p role="status">{notice}</p>}
          {draft ? (
            <div aria-label="Selected native deployment source">
              <p>
                {endpoint(draft.source.target)} · {draft.source.object} · weekly
                day {draft.source.day}
              </p>
              <p className="mono">Draft {draft.id}</p>
            </div>
          ) : (
            <p>
              Review a typed weekly-day draft above to select a deployment
              source. Stored receipts remain available disconnected.
            </p>
          )}
          <label>
            Declared native write operator
            <input
              aria-label="Declared native write operator"
              value={operator}
              maxLength={48}
              disabled={!!busy}
              onChange={(e) => setOperator(e.target.value)}
            />
          </label>
          <label>
            Native write rationale
            <input
              aria-label="Native write rationale"
              value={rationale}
              maxLength={240}
              disabled={!!busy}
              onChange={(e) => setRationale(e.target.value)}
            />
          </label>
          <p>
            These declarations are user text, not authenticated site identity.
            The captured target is fixed; connection form edits cannot override
            it.
          </p>
          <button
            disabled={
              !profile ||
              !draft ||
              !connected ||
              !!busy ||
              !operator.trim() ||
              !rationale.trim()
            }
            onClick={() => void preview()}
          >
            Preview fresh native weekly-day write
          </button>
          {prepared && preparedCurrent && (
            <div aria-label="Fresh native write review">
              <h5>
                {prepared.data.can_apply
                  ? "Fresh review required before one Apply"
                  : `No Apply authority: ${prepared.data.status}`}
              </h5>
              {prepared.data.reasons.map((reason: string, index: number) => (
                <p key={index}>{reason}</p>
              ))}
              {prepared.data.can_apply && (
                <>
                  <p>
                    {endpoint(prepared.data.target)} · {prepared.data.object_id}{" "}
                    · day {prepared.data.day}
                  </p>
                  <p>
                    {prepared.data.request_apdu_bytes} native APDU bytes; remote
                    limit {prepared.data.remote_max_apdu}. Server review expires{" "}
                    {prepared.data.expires_at}.
                  </p>
                  <p>
                    Fresh reads are sequential. Another writer can change
                    configuration after the last check; this is not atomic
                    compare-and-swap. ACK and matching readback do not prove
                    output behavior or persistence.
                  </p>
                  <button
                    disabled={!!busy || !connected || expired}
                    onClick={() => void apply()}
                  >
                    Apply one native weekly-day request
                  </button>
                  {expired && (
                    <p role="status">
                      This native review expired. Preview again before Apply.
                      The server independently enforces its lease.
                    </p>
                  )}
                </>
              )}
              <button
                onClick={() =>
                  download(
                    prepared,
                    `native-weekly-preview-${prepared.data.id}.json`,
                  )
                }
              >
                Export exact native write preview
              </button>
              <details>
                <summary>Fresh native context and request encoding</summary>
                <pre>
                  {JSON.stringify(
                    {
                      review_sha256: prepared.data.review_sha256,
                      static_native_sha256: prepared.data.static_native_sha256,
                      service_body_hex: prepared.data.request_service_body_hex,
                      target: prepared.data.target,
                      interpretation: prepared.data.native_draft.interpretation,
                      transitions: prepared.data.native_draft.new.transitions,
                    },
                    null,
                    2,
                  )}
                </pre>
              </details>
            </div>
          )}
          {profile && (
            <>
              <p>
                {profile.journal.records.length} journal records ·{" "}
                {profile.journal.used_bytes} retained bytes. Evidence is not
                automatically evicted.
              </p>
              <table aria-label="Native write journal">
                <thead>
                  <tr>
                    <th>Receipt</th>
                    <th>Local journal time</th>
                    <th>Evidence</th>
                  </tr>
                </thead>
                <tbody>
                  {profile.journal.records.map((row: any) => (
                    <tr key={row.id}>
                      <td>
                        <button
                          disabled={!!busy}
                          onClick={() => void openReceipt(row.id)}
                        >
                          Open native receipt {row.id.slice(0, 12)}
                        </button>
                      </td>
                      <td>{row.created}</td>
                      <td>
                        {row.unresolved === 1
                          ? "Unresolved intent"
                          : "Sealed result"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
          {result && (
            <div aria-label="Native write receipt">
              <h5>
                {recovered
                  ? "Unresolved durable write intent"
                  : "Native write operation receipt"}
              </h5>
              <p>
                {endpoint(result.target)} · {result.object_id} · day{" "}
                {result.day}
              </p>
              <p className="mono">
                Receipt {result.id} · operation {result.operation_id}
              </p>
              <dl>
                <dt>Remote change possible</dt>
                <dd>
                  {result.may_have_applied
                    ? "May have applied"
                    : "This completed operation did not admit a write"}
                </dd>
                <dt>Dispatch</dt>
                <dd>
                  {recovered
                    ? "Unknown after interrupted intent"
                    : result.dispatch_started
                      ? "One dispatch admitted"
                      : "Not admitted"}
                </dd>
                <dt>Protocol response</dt>
                <dd>{recovered ? "Unknown" : result.protocol_status}</dd>
                <dt>Fresh readback</dt>
                <dd>{recovered ? "Unknown" : result.readback.status}</dd>
              </dl>
              {result.response?.error_class && (
                <p>
                  {nativeEnum(result.response.error_class)} ·{" "}
                  {nativeEnum(result.response.error_code)}
                </p>
              )}
              {result.response?.reason && (
                <p>{nativeEnum(result.response.reason)}</p>
              )}
              {result.errors.map((reason: string, index: number) => (
                <p key={index}>{reason}</p>
              ))}
              <p>
                Protocol acceptance and observed state are separate evidence. No
                automatic retry, rollback or inverse write was sent.
              </p>
              {result.journal_error && (
                <p role="alert">{result.journal_error}</p>
              )}
              <button
                onClick={() =>
                  download(receipt!, `native-weekly-write-${result.id}.json`)
                }
              >
                Export exact native write receipt
              </button>
              <button
                disabled={!connected || !!busy}
                onClick={() => void reconcile()}
              >
                Read-only reconcile selected receipt
              </button>
              {recovered && (
                <details>
                  <summary>Original pre-send intent snapshot</summary>
                  <p>
                    This snapshot cannot establish whether dispatch happened.
                    The original stored bytes are bound by{" "}
                    {result.intent_sha256}.
                  </p>
                  <pre>{JSON.stringify(result.intent_snapshot, null, 2)}</pre>
                </details>
              )}
            </div>
          )}
          {observation && (
            <div aria-label="Native write reconciliation">
              <h5>Separate read-only observation</h5>
              <p>
                Readback: {observation.data.readback.status}. Writes sent: 0.
                The original receipt remains unchanged.
              </p>
              <button
                onClick={() =>
                  download(
                    observation,
                    `native-weekly-reconcile-${observation.data.receipt_id}.json`,
                  )
                }
              >
                Export exact native reconciliation
              </button>
              <p>
                This observation remains in workspace memory; export it before
                leaving.
              </p>
            </div>
          )}
          <p>
            Direct unicast IPv4 and explicitly pinned routed IPv4 only. Serial,
            BTCVT, BBMD/foreign writes, Calendar/exception edits and physical
            manufacturer acceptance are outside this profile. Native numeric
            evidence downloads retain original server bytes; JSON previews may
            normalize numeric spelling.
          </p>
        </>
      )}
    </section>
  );
}
