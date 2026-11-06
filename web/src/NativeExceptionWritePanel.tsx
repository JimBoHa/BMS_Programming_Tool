import { randomUUID } from "./browserCrypto";
import { useEffect, useRef, useState } from "react";
import {
  api,
  apiJsonDocument,
  apiKeepalive,
  saveBlob,
  type JsonDocument,
} from "./api";
import { controllerKey, type ControllerTarget } from "./workflow";
import {
  EXCEPTION_WRITE_BASE as base,
  exceptionWriteProfile,
  exceptionWritePreview,
  exceptionAppliedReceipt,
  exceptionWriteReceipt,
  exceptionReconciliation,
  calendarDocumentSha,
  calendarEndpoint,
  sameCalendarTarget,
} from "./nativeExceptionWrite";

type Owned = {
  id: string;
  key: string;
  epoch: number;
  kind: "preview" | "apply" | "reconcile";
  retired: boolean;
};
type Prepared = JsonDocument & { key: string; epoch: number };

export function NativeExceptionWritePanel({
  review,
  context,
  connected,
  selectedTarget,
  onOpenChange,
}: {
  review: any | null;
  context: string;
  connected: boolean;
  selectedTarget: ControllerTarget | null;
  onOpenChange: (open: boolean) => void;
}) {
  const [opened, setOpened] = useState(false),
    [profile, setProfile] = useState<any>(null);
  const [operator, setOperator] = useState(""),
    [rationale, setRationale] = useState("");
  const [prepared, setPrepared] = useState<Prepared | null>(null),
    [expired, setExpired] = useState("");
  const [receipt, setReceipt] = useState<JsonDocument | null>(null),
    [observation, setObservation] = useState<JsonDocument | null>(null);
  const [busy, setBusy] = useState(""),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const alive = useRef(false),
    own = useRef<Owned | null>(null),
    epoch = useRef(0),
    history = useRef(0),
    catalog = useRef(0),
    readyOperation = useRef<string | null>(null);
  const raw = JSON.stringify([
    context,
    review?.id ?? null,
    connected,
    selectedTarget ? controllerKey(selectedTarget) : null,
    operator,
    rationale,
  ]);
  const boundary = useRef({ raw, version: 0 });
  if (boundary.current.raw !== raw)
    boundary.current = { raw, version: boundary.current.version + 1 };
  const authority = JSON.stringify([raw, boundary.current.version]),
    authorityNow = useRef(authority);
  authorityNow.current = authority;
  const receiptNow = useRef(receipt?.data.id || "");
  receiptNow.current = receipt?.data.id || "";
  const matches =
    !!review && sameCalendarTarget(review.source.target, selectedTarget);
  const receiptMatches =
    !!receipt && sameCalendarTarget(receipt.data.target, selectedTarget);
  const valid = (op: Owned) =>
    alive.current &&
    own.current === op &&
    !op.retired &&
    authorityNow.current === op.key &&
    epoch.current === op.epoch;
  function cancelId(id: string | null) {
    if (id)
      void apiKeepalive(base + "/cancel", { operation_id: id }).catch(() => {});
  }
  function retire() {
    epoch.current++;
    history.current++;
    const op = own.current;
    if (op && !op.retired) {
      op.retired = true;
      cancelId(op.id);
      setNotice(
        op.kind === "apply"
          ? "The earlier Apply may already have applied. Open its retained receipt before another attempt."
          : "The earlier operation is no longer current. Its late reply cannot authorize Apply.",
      );
    }
    cancelId(readyOperation.current);
    readyOperation.current = null;
    setPrepared(null);
  }
  useEffect(() => {
    retire();
  }, [authority]);
  useEffect(() => {
    alive.current = true;
    document.addEventListener("visibilitychange", retire);
    window.addEventListener("pagehide", retire);
    return () => {
      alive.current = false;
      epoch.current++;
      history.current++;
      catalog.current++;
      document.removeEventListener("visibilitychange", retire);
      window.removeEventListener("pagehide", retire);
      if (own.current) {
        own.current.retired = true;
        cancelId(own.current.id);
      }
      cancelId(readyOperation.current);
    };
  }, []);
  useEffect(() => {
    if (!prepared?.data.can_apply) return;
    const id = prepared.data.id,
      limit = Date.parse(prepared.data.expires_at);
    const tick = () => {
      if (Date.now() >= limit) setExpired(id);
    };
    tick();
    const timer = window.setInterval(tick, 250);
    return () => clearInterval(timer);
  }, [prepared]);
  async function refresh() {
    const ticket = ++catalog.current;
    try {
      const data = exceptionWriteProfile(await api(base + "/profile"));
      if (alive.current && ticket === catalog.current) setProfile(data);
    } catch (e) {
      if (alive.current && ticket === catalog.current) {
        setProfile(null);
        setError(String(e));
        retire();
      }
    }
  }
  async function run(
    kind: Owned["kind"],
    body: any,
    accept: (document: JsonDocument, op: Owned) => void,
  ) {
    if (!connected || own.current) return;
    const op: Owned = {
      id: `exception_${kind}_${randomUUID()}`,
      key: authorityNow.current,
      epoch: epoch.current,
      kind,
      retired: false,
    };
    own.current = op;
    setBusy(kind);
    setError("");
    setNotice("");
    try {
      const document = await apiJsonDocument(base + "/" + kind, {
        ...body,
        operation_id: op.id,
      });
      if (document.blob.size > 8 * 1024 * 1024)
        throw new Error(
          "Exception operation evidence exceeds its response limit.",
        );
      if (valid(op)) accept(document, op);
    } catch (e) {
      if (kind === "preview") cancelId(op.id);
      if (valid(op))
        setError(
          kind === "apply"
            ? `Apply outcome is unconfirmed: ${String(e)}. Open the retained receipt; no retry was sent.`
            : String(e),
        );
    } finally {
      if (own.current === op) own.current = null;
      if (alive.current) {
        setBusy("");
        if (kind === "apply") void refresh();
      }
    }
  }
  async function preview() {
    if (
      !review ||
      !matches ||
      !profile ||
      !connected ||
      !operator.trim() ||
      !rationale.trim()
    )
      return;
    const name = operator.trim(),
      why = rationale.trim(),
      binding = review;
    setPrepared(null);
    cancelId(readyOperation.current);
    readyOperation.current = null;
    await run(
      "preview",
      {
        draft: binding.request,
        expected_review_id: binding.id,
        operator_name: name,
        rationale: why,
      },
      (document, op) => {
        exceptionWritePreview(document.data, binding, op.id, name, why);
        if (document.data.can_apply) readyOperation.current = op.id;
        setPrepared({ ...document, key: op.key, epoch: op.epoch });
      },
    );
  }
  const currentPrepared =
    prepared?.key === authority && prepared.epoch === epoch.current;
  const fresh =
    currentPrepared &&
    prepared?.data.can_apply === true &&
    prepared.data.id !== expired &&
    Date.now() < Date.parse(prepared.data.expires_at);
  async function apply() {
    const candidate = prepared;
    if (
      !connected ||
      !matches ||
      !fresh ||
      !candidate ||
      candidate.key !== authorityNow.current ||
      candidate.epoch !== epoch.current
    )
      return;
    if (Date.now() >= Date.parse(candidate.data.expires_at)) {
      setExpired(candidate.data.id);
      setNotice("Review expired. Review this Exception change again.");
      return;
    }
    setPrepared(null);
    readyOperation.current = null;
    await run(
      "apply",
      {
        token: candidate.data.token,
        review_sha256: candidate.data.review_sha256,
      },
      (document, op) => {
        exceptionAppliedReceipt(document.data, candidate.data, op.id);
        history.current++;
        setReceipt(document);
        setObservation(null);
      },
    );
  }
  async function openReceipt(id: string) {
    const ticket = ++history.current,
      key = authorityNow.current,
      lifecycle = epoch.current;
    setError("");
    setObservation(null);
    try {
      const document = await apiJsonDocument(base + "/receipts/" + id);
      if (
        !alive.current ||
        ticket !== history.current ||
        key !== authorityNow.current ||
        lifecycle !== epoch.current
      )
        return;
      if (document.blob.size > 8 * 1024 * 1024)
        throw new Error("Exception receipt exceeds its response limit.");
      exceptionWriteReceipt(document.data, id);
      setReceipt(document);
    } catch (e) {
      if (
        alive.current &&
        ticket === history.current &&
        key === authorityNow.current &&
        lifecycle === epoch.current
      )
        setError(String(e));
    }
  }
  async function reconcile() {
    if (!receipt || !receiptMatches || !connected || own.current) return;
    const selected = receipt,
      key = authorityNow.current,
      lifecycle = epoch.current,
      ticket = history.current;
    let hash: string;
    try {
      hash = await calendarDocumentSha(selected.blob);
    } catch (e) {
      if (
        alive.current &&
        key === authorityNow.current &&
        lifecycle === epoch.current &&
        ticket === history.current
      )
        setError(String(e));
      return;
    }
    if (
      !alive.current ||
      key !== authorityNow.current ||
      lifecycle !== epoch.current ||
      ticket !== history.current ||
      receiptNow.current !== selected.data.id
    )
      return;
    await run("reconcile", { receipt_id: selected.data.id }, (document, op) => {
      exceptionReconciliation(document.data, selected.data, hash, op.id);
      if (history.current === ticket && receiptNow.current === selected.data.id)
        setObservation(document);
    });
  }
  async function cancel() {
    const op = own.current;
    if (!op) return;
    retire();
    setNotice(
      op.kind === "apply"
        ? "Cancellation requested. A transmitted replacement cannot be undone; open its retained receipt."
        : "Cancellation requested for the active Exception operation.",
    );
  }
  const result = receipt?.data,
    observed = observation?.data.readback;
  return (
    <section
      aria-label="Exception controller deployment"
      className="native-calendar-deployment"
    >
      <h4>Controller deployment and receipts</h4>
      {!opened ? (
        <button
          onClick={() => {
            setOpened(true);
            onOpenChange(true);
            void refresh();
          }}
        >
          Open exception deployment and receipts
        </button>
      ) : (
        <>
          <p>
            Replace one Schedule’s complete exception array. Review reads the
            selected controller; Apply sends one replacement request.
          </p>
          <div className="button-row">
            <button onClick={() => void refresh()}>
              Refresh Exception receipts
            </button>
            <button
              onClick={() => {
                retire();
                setOpened(false);
                onOpenChange(false);
                catalog.current++;
              }}
            >
              Close exception deployment
            </button>
          </div>
          {review ? (
            <p>
              Captured source: {calendarEndpoint(review.source.target)} ·{" "}
              {review.source.object}. {review.diff.old_count} original events →{" "}
              {review.diff.new_count} proposed events.
            </p>
          ) : (
            <p>
              Review local Schedule exceptions to select a deployment source.
              Retained receipts remain available.
            </p>
          )}
          {selectedTarget && (
            <p aria-label="Selected Exception controller">
              Selected controller: {calendarEndpoint(selectedTarget)}
            </p>
          )}
          {!matches && (
            <p role="status">
              Open and verify the captured controller to deploy these
              exceptions. Local review and export remain available.
            </p>
          )}
          <label>
            Declared Exception operator
            <input
              maxLength={48}
              value={operator}
              disabled={!!busy}
              onChange={(e) => setOperator(e.target.value)}
            />
          </label>
          <label>
            Exception change rationale
            <input
              maxLength={240}
              value={rationale}
              disabled={!!busy}
              onChange={(e) => setRationale(e.target.value)}
            />
          </label>
          <p>
            These declarations are user text, not authenticated site identity.
          </p>
          <button
            className={
              !fresh && review?.diff.changed && matches && connected
                ? "primary"
                : ""
            }
            disabled={
              !profile ||
              !review ||
              !connected ||
              !matches ||
              !!busy ||
              !operator.trim() ||
              !rationale.trim()
            }
            onClick={() => void preview()}
          >
            Review Exception controller change
          </button>
          {busy && (
            <p role="status">
              Exception {busy} is pending. No automatic retry or reconnect.
            </p>
          )}
          {busy && (
            <button onClick={() => void cancel()}>
              Cancel active Exception operation
            </button>
          )}
          {error && <p role="alert">{error}</p>}
          {notice && <p role="status">{notice}</p>}
          {prepared && currentPrepared && (
            <div aria-label="Fresh Exception controller review">
              <p>
                <strong>
                  {prepared.data.can_apply
                    ? "Fresh Exception review ready"
                    : `No Apply authority: ${prepared.data.status}`}
                </strong>
              </p>
              {prepared.data.reasons.map((reason: string, i: number) => (
                <p key={i}>{reason}</p>
              ))}
              {prepared.data.can_apply && (
                <>
                  <p>
                    {calendarEndpoint(prepared.data.target)} ·{" "}
                    {prepared.data.object_id}. Review expires{" "}
                    {prepared.data.expires_at}.
                  </p>
                  <button
                    className="primary"
                    disabled={!fresh || !connected || !matches || !!busy}
                    onClick={() => void apply()}
                  >
                    Apply Schedule exceptions
                  </button>
                  {!fresh && (
                    <p role="status">
                      Review expired. Review this Exception change again.
                    </p>
                  )}
                </>
              )}
              <button
                onClick={() =>
                  saveBlob(
                    prepared.blob,
                    `exception-preview-${prepared.data.id}.json`,
                  )
                }
              >
                Save Exception controller review
              </button>
              <details>
                <summary>Exception controller review evidence</summary>
                <pre>{JSON.stringify(prepared.data, null, 2)}</pre>
              </details>
            </div>
          )}
          {profile && (
            <table aria-label="Exception transfer journal">
              <thead>
                <tr>
                  <th>Receipt</th>
                  <th>Recorded</th>
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
                        Open Exception receipt {row.id.slice(0, 12)}
                      </button>
                    </td>
                    <td>{row.created}</td>
                    <td>
                      {row.unresolved
                        ? "Intent awaiting result"
                        : "Sealed result"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {result && (
            <section aria-label="Exception transfer receipt">
              <h5>
                {result.journal_state === "intent_only"
                  ? "Unresolved durable Exception intent"
                  : "Exception transfer receipt"}
              </h5>
              <p>
                {calendarEndpoint(result.target)} · {result.object_id}. Receipt{" "}
                {result.id}.
              </p>
              <dl>
                <dt>Dispatch</dt>
                <dd>
                  {result.dispatch_started === null
                    ? "Unknown after interrupted intent"
                    : result.dispatch_started
                      ? "One dispatch admitted"
                      : "Not admitted"}
                </dd>
                <dt>Protocol response</dt>
                <dd>
                  {result.protocol_accepted === null
                    ? "Unknown"
                    : result.protocol_accepted
                      ? "Accepted"
                      : result.protocol_status === "not_sent"
                        ? "Not sent"
                        : "Rejected"}
                </dd>
                <dt>Fresh readback</dt>
                <dd>{result.readback.status}</dd>
              </dl>
              {(observed || result.readback).status === "match" ? (
                <p role="status">
                  Reviewed exceptions and other static Schedule fields matched
                  at readback. Read the current Exception into a new capture
                  before another change.
                </p>
              ) : (
                result.may_have_applied && (
                  <p role="status">
                    The replacement may have applied. Protocol response and
                    readback are separate evidence; read back this receipt
                    before another attempt.
                  </p>
                )
              )}
              {result.errors.map((reason: string, i: number) => (
                <p key={i}>{reason}</p>
              ))}
              {result.journal_error && (
                <p role="alert">{result.journal_error}</p>
              )}
              <button
                onClick={() =>
                  saveBlob(receipt!.blob, `exception-write-${result.id}.json`)
                }
              >
                Save Exception receipt
              </button>
              <button
                disabled={!connected || !receiptMatches || !!busy}
                onClick={() => void reconcile()}
              >
                Read back Exception receipt
              </button>
              {!receiptMatches && (
                <p role="status">
                  Open this receipt’s original controller before readback. Its
                  local evidence remains available to save.
                </p>
              )}
              <details>
                <summary>Original Exception transfer evidence</summary>
                <pre>{JSON.stringify(result, null, 2)}</pre>
              </details>
            </section>
          )}
          {observation && (
            <section aria-label="Exception receipt readback">
              <p>
                Readback: <strong>{observed.status}</strong>. Writes sent: 0.
                The original receipt remains unchanged.
              </p>
              <button
                onClick={() =>
                  saveBlob(
                    observation.blob,
                    `exception-readback-${observation.data.receipt_id}.json`,
                  )
                }
              >
                Save Exception readback
              </button>
              <details>
                <summary>Exception readback evidence</summary>
                <pre>{JSON.stringify(observation.data, null, 2)}</pre>
              </details>
            </section>
          )}
        </>
      )}
    </section>
  );
}
