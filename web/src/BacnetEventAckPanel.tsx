import { useEffect, useRef, useState } from "react";
import { api, saveBlob } from "./api";

const transitions = ["to_offnormal", "to_fault", "to_normal"];

export function BacnetEventAckPanel({
  connected,
  report,
  selected,
  parentBusy,
  onBusy,
  onAttempt,
}: {
  connected: boolean;
  report: any;
  selected: any;
  parentBusy: boolean;
  onBusy: (busy: boolean) => void;
  onAttempt: () => void;
}) {
  const [operator, setOperator] = useState("");
  const [processId, setProcessId] = useState("1");
  const [zone, setZone] = useState("");
  const [transition, setTransition] = useState("to_offnormal");
  const [plan, setPlan] = useState<any>(null);
  const [receipt, setReceipt] = useState<any>(null);
  const [receipts, setReceipts] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [now, setNow] = useState(Date.now());
  const mounted = useRef(false);
  const operation = useRef<string | null>(null);
  const generation = useRef(0);
  const source = `${connected}/${report?.id}/${report?.evidence_sha256}/${selected?.object_id}`;

  function cancelDetached() {
    if (operation.current)
      void api("/bacnet/events/ack/cancel", {
        operation_id: operation.current,
      }).catch(() => {});
  }
  async function refreshReceipts() {
    try {
      const value = await api("/bacnet/events/ack/profile");
      if (mounted.current) setReceipts(value.receipts);
    } catch (failure) {
      if (mounted.current) setError(String(failure));
    }
  }
  useEffect(() => {
    mounted.current = true;
    void refreshReceipts();
    return () => {
      mounted.current = false;
      generation.current++;
      cancelDetached();
    };
  }, []);
  useEffect(() => {
    generation.current++;
    cancelDetached();
    setPlan(null);
    setError("");
    const available = transitions.find(
      (item) => selected?.acknowledged_transitions[item] === false,
    );
    setTransition(available || "to_offnormal");
  }, [source]);
  useEffect(() => {
    if (!plan?.can_apply) return;
    const timer = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(timer);
  }, [plan]);

  function edit(change: () => void) {
    setPlan(null);
    setError("");
    change();
  }
  const eligible =
    !!selected && selected.acknowledged_transitions[transition] === false;
  const expired = !!plan?.expires_at && now >= Date.parse(plan.expires_at);
  async function run(apply: boolean) {
    if (operation.current || !connected || parentBusy) return;
    const id = crypto.randomUUID().replaceAll("-", "");
    const epoch = generation.current;
    operation.current = id;
    setBusy(true);
    onBusy(true);
    setError("");
    const reviewed = plan;
    if (apply) setPlan(null);
    try {
      const result = await api(
        `/bacnet/events/ack/${apply ? "apply" : "preview"}`,
        apply
          ? {
              operation_id: id,
              token: reviewed.token,
              review_sha256: reviewed.review_sha256,
            }
          : {
              operation_id: id,
              report_id: report.id,
              report_sha256: report.evidence_sha256,
              object_id: selected.object_id,
              transition,
              operator_name: operator,
              process_id: Number(processId),
              acknowledgement_timezone: zone,
            },
      );
      if (mounted.current && epoch === generation.current) {
        if (apply) {
          setReceipt(result);
          onAttempt();
        } else {
          setPlan(result);
          setNow(Date.now());
        }
      }
    } catch (failure) {
      if (mounted.current && epoch === generation.current)
        setError(String(failure));
    } finally {
      if (operation.current === id) operation.current = null;
      if (mounted.current) {
        setBusy(false);
        onBusy(false);
        if (apply) {
          onAttempt();
          void refreshReceipts();
        }
      }
    }
  }
  async function loadReceipt(id: string) {
    try {
      setReceipt(await api(`/bacnet/events/ack/receipts/${id}`));
    } catch (failure) {
      setError(String(failure));
    }
  }
  return (
    <section
      className="bacnet-event-ack"
      aria-label="Reviewed event acknowledgement"
    >
      <h3>Acknowledge a device transition</h3>
      <p>
        Select an inspected, unacknowledged transition, preview fresh device
        evidence, then apply the exact review once. This changes a device
        acknowledgement bit. Protocol acceptance does not prove human receipt,
        resolution, or physical correction.
      </p>
      {!selected && (
        <p>
          Query and inspect a device event before preparing an acknowledgement.
        </p>
      )}
      {selected && (
        <>
          <fieldset disabled={busy || parentBusy || !connected}>
            <legend>Acknowledgement identity and clock</legend>
            <div className="bacnet-events-fields">
              <label>
                Event transition
                <select
                  value={transition}
                  onChange={(event) =>
                    edit(() => setTransition(event.target.value))
                  }
                >
                  {transitions.map((item) => (
                    <option
                      key={item}
                      value={item}
                      disabled={
                        selected.acknowledged_transitions[item] !== false
                      }
                    >
                      {item}
                      {selected.acknowledged_transitions[item]
                        ? " (already acknowledged)"
                        : ""}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Declared operator identity
                <input
                  value={operator}
                  maxLength={48}
                  onChange={(event) =>
                    edit(() => setOperator(event.target.value))
                  }
                />
              </label>
              <label>
                Acknowledging process identifier
                <input
                  type="number"
                  min={0}
                  max={4294967295}
                  value={processId}
                  onChange={(event) =>
                    edit(() => setProcessId(event.target.value))
                  }
                />
              </label>
              <label>
                Acknowledgement clock timezone
                <input
                  value={zone}
                  placeholder="IANA zone, e.g. America/Los_Angeles"
                  onChange={(event) => edit(() => setZone(event.target.value))}
                />
              </label>
            </div>
            <p>
              Identity is user declared. The process identifier must follow your
              site's policy. The acknowledgement clock uses current client time
              in your explicit timezone; the original native event timestamp is
              sent unchanged.
            </p>
            {transition === "to_offnormal" &&
              ![2, 3, 4, 5].includes(selected.event_state.value) && (
                <p>
                  Deferred: the exact historical offnormal state is unavailable
                  from this current summary. A matching event notification or
                  vendor tool is required.
                </p>
              )}
            <button
              disabled={!eligible || !operator.trim() || !zone.trim()}
              onClick={() => void run(false)}
            >
              Preview acknowledgement
            </button>
          </fieldset>
        </>
      )}
      {busy && (
        <div role="status">
          <p>
            Verifying the exact device and transition. No automatic
            acknowledgement retries.
          </p>
          <button onClick={cancelDetached}>
            Cancel acknowledgement operation
          </button>
        </div>
      )}
      {plan && (
        <section aria-label="Acknowledgement review">
          <p role="status">
            {plan.status}
            {expired ? " · expired; preview again" : ""}
          </p>
          {plan.reasons.map((reason: string, index: number) => (
            <p key={index}>{reason}</p>
          ))}
          {plan.can_apply && (
            <>
              <p>
                Review {plan.target.device} at {plan.target.address}
                {plan.target.router
                  ? ` via ${plan.target.router}, DNET ${plan.target.dnet}`
                  : ""}
                : {plan.object_id}, {plan.transition}, native state{" "}
                {plan.event_state_acknowledged}.
              </p>
              <p>
                Exact event timestamp:{" "}
                <code>{JSON.stringify(plan.event_timestamp)}</code>
              </p>
              <p>
                Source: {plan.acknowledgement_source}; process {plan.process_id}
                ; acknowledgement timezone {plan.acknowledgement_timezone}.
                Review expires {plan.expires_at}.
              </p>
              <p>
                The device can change after the final read. Its timestamp/state
                validation is authoritative. A missing response after
                transmission leaves the result unknown; query again before
                another attempt.
              </p>
              <button
                className="primary"
                disabled={busy || parentBusy || !connected || expired}
                onClick={() => void run(true)}
              >
                Apply reviewed acknowledgement
              </button>
            </>
          )}
          <details>
            <summary>Inspect acknowledgement review evidence</summary>
            <pre>{JSON.stringify({ ...plan, token: undefined }, null, 2)}</pre>
          </details>
        </section>
      )}
      {error && <p role="alert">{error}</p>}
      {receipt && (
        <section aria-label="Acknowledgement receipt">
          <p role="status">
            Acknowledgement {receipt.status} · protocol accepted:{" "}
            {String(receipt.protocol_accepted)} · may have applied:{" "}
            {String(receipt.may_have_applied)}
          </p>
          <p>
            Query events again before any further acknowledgement. Cancellation
            cannot undo a transmitted request. No automatic retry was made.
          </p>
          {receipt.errors.map((item: string, index: number) => (
            <p key={index}>{item}</p>
          ))}
          {receipt.audit_error && <p role="alert">{receipt.audit_error}</p>}
          <button
            onClick={() =>
              saveBlob(
                new Blob([JSON.stringify(receipt, null, 2)], {
                  type: "application/json",
                }),
                `bacnet-acknowledgement-${receipt.id}.json`,
              )
            }
          >
            Export acknowledgement receipt
          </button>
          <details>
            <summary>Inspect native acknowledgement receipt</summary>
            <pre>{JSON.stringify(receipt, null, 2)}</pre>
          </details>
        </section>
      )}
      {receipts.length > 0 && (
        <details>
          <summary>Earlier acknowledgement receipts in this session</summary>
          {receipts.map((item) => (
            <p key={item.id}>
              {item.status} · {item.target.device} at {item.target.address} ·{" "}
              {item.finished_at}{" "}
              <button onClick={() => void loadReceipt(item.id)}>
                Inspect receipt {item.id}
              </button>
            </p>
          ))}
        </details>
      )}
    </section>
  );
}
