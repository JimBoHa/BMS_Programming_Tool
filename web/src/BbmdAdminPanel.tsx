import { useEffect, useRef, useState } from "react";
import { api, saveBlob } from "./api";

type Row = { ip: string; port: string; mask: string };
export function BbmdAdminPanel({
  connected,
  defaultEndpoint = "",
}: {
  connected: boolean;
  defaultEndpoint?: string;
}) {
  const [endpoint, setEndpoint] = useState(defaultEndpoint);
  const [operation, setOperation] = useState("write-bdt");
  const [rows, setRows] = useState<Row[]>([]);
  const [target, setTarget] = useState("");
  const [proposal, setProposal] = useState<any>(null);
  const [receipt, setReceipt] = useState<any>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const [history, setHistory] = useState<any[]>([]);
  const [watch, setWatch] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const mounted = useRef(false);
  const generation = useRef(0);
  const selected = useRef("");
  const changing = useRef(false);
  const forgetReview = () => {
    generation.current++;
    setProposal(null);
    setAcknowledged(false);
  };
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    forgetReview();
    setEndpoint(defaultEndpoint);
    setRows([]);
    setTarget("");
  }, [defaultEndpoint]);

  function show(value: any) {
    selected.current = value.id;
    setReceipt(value);
  }
  async function refresh() {
    const [saved, status] = await Promise.all([
      api("/bacnet/bbmd-admin/history"),
      api("/bacnet/bbmd-admin/status"),
    ]);
    if (!mounted.current) return;
    setHistory(saved);
    setWatch(status.active.length > 0);
    if (!selected.current && status.active.length) show(status.active[0]);
  }
  useEffect(() => {
    if (!watch) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    async function tick() {
      try {
        const state = await api("/bacnet/bbmd-admin/status");
        const id = selected.current;
        const detail = id
          ? await api(`/bacnet/bbmd-admin/receipts/${id}`)
          : null;
        if (!stopped && mounted.current) {
          if (detail && selected.current === detail.id) setReceipt(detail);
          if (state.active.length) timer = setTimeout(tick, 500);
          else {
            setWatch(false);
            await refresh();
          }
        }
      } catch (e) {
        if (!stopped && mounted.current) {
          setError(String(e));
          setWatch(false);
        }
      }
    }
    timer = setTimeout(tick, 100);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [watch]);

  async function act(action: string, id?: string) {
    if (changing.current) return;
    changing.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    const current = generation.current;
    try {
      if (action === "load" || action === "preview") {
        const data = await api("/bacnet/bbmd-admin/preview", {
          endpoint,
          operation: action === "load" ? "write-bdt" : operation,
          ...(action === "load"
            ? {}
            : operation === "write-bdt"
              ? {
                  rows: rows.map((row) => ({
                    ...row,
                    port: /^[0-9]+$/.test(row.port) ? Number(row.port) : null,
                  })),
                }
              : { delete_target: target }),
        });
        if (!mounted.current) return;
        show(data);
        if (current !== generation.current) {
          setNotice(
            `Review prepared for earlier source ${data.endpoint}; create a fresh review for the current draft.`,
          );
        } else if (action === "load") {
          setRows(
            data.desired_rows.map((row: any) => ({
              ip: row.ip,
              port: String(row.port),
              mask: row.mask,
            })),
          );
          setProposal(null);
          setAcknowledged(false);
          setNotice(
            "Current BDT copied into draft. Edit, then prepare a fresh review. No write sent.",
          );
        } else {
          setProposal(data.apply_available ? data : null);
          setAcknowledged(false);
        }
      } else if (action === "apply") {
        const reviewed = proposal;
        setProposal(null);
        setAcknowledged(false); // do not offer automatic retry
        const data = await api("/bacnet/bbmd-admin/apply", {
          id: reviewed.id,
          apply_token: reviewed.apply_token,
          review_hash: reviewed.review_hash,
          acknowledge_limits: acknowledged,
        });
        if (mounted.current) {
          show(data);
          setWatch(true);
        }
      } else if (action === "open") {
        const data = await api(`/bacnet/bbmd-admin/receipts/${id}`);
        if (mounted.current) {
          show(data);
          setProposal(null);
          setAcknowledged(false);
        }
      } else if (action === "cancel") {
        const data = await api("/bacnet/bbmd-admin/cancel", { id });
        if (mounted.current) show(data);
      } else if (action === "restore") {
        const data = await api("/bacnet/bbmd-admin/restore-preview", { id });
        if (mounted.current) {
          show(data);
          if (current === generation.current) {
            setEndpoint(data.endpoint);
            setOperation("write-bdt");
            setRows(
              data.desired_rows.map((row: any) => ({
                ip: row.ip,
                port: String(row.port),
                mask: row.mask,
              })),
            );
            setTarget("");
            setProposal(data.apply_available ? data : null);
            setAcknowledged(false);
          } else
            setNotice(
              `Restore review belongs to ${data.endpoint}; current draft changed. Prepare another review.`,
            );
        }
      } else if (action === "export") {
        const data = await api(`/bacnet/bbmd-admin/receipts/${id}`);
        if (mounted.current)
          saveBlob(
            new Blob([JSON.stringify(data, null, 2)], {
              type: "application/json",
            }),
            `${id}-bbmd-administration.json`,
          );
      }
      await refresh();
    } catch (e) {
      if (mounted.current) setError(String(e));
    } finally {
      changing.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  function edit(index: number, key: keyof Row, value: string) {
    forgetReview();
    setRows((old) =>
      old.map((row, position) =>
        position === index ? { ...row, [key]: value } : row,
      ),
    );
  }
  return (
    <section
      className="card"
      role="region"
      aria-label="Reviewed BBMD administration"
    >
      <div className="card-header">
        <h3>Reviewed BBMD table changes</h3>
      </div>
      <div className="card-body">
        <p>
          Replace the whole BDT or delete one exact FDT endpoint. Prepare a
          fresh preview, review its original source and bytes, then Apply once
          within 60 seconds.
        </p>
        <p className="help-text">
          Plain IPv4 only. Foreign registration and native or custom BVLC
          management owners are refused. A concurrent change can race the last
          read and write. Generic Results cannot prove authorship or atomic CAS;
          post-state observations stay separate. FDT renewal can recreate a
          deleted entry; identical address/TTL does not identify a lease
          generation. No automatic retry or rollback.
        </p>
        <div className="form-grid">
          <label>
            BBMD change endpoint
            <input
              aria-label="BBMD change endpoint"
              value={endpoint}
              disabled={busy}
              onChange={(e) => {
                forgetReview();
                setEndpoint(e.target.value);
                setRows([]);
                setTarget("");
              }}
            />
          </label>
          <label>
            BBMD change operation
            <select
              aria-label="BBMD change operation"
              value={operation}
              disabled={busy}
              onChange={(e) => {
                forgetReview();
                setOperation(e.target.value);
              }}
            >
              <option value="write-bdt">Replace entire BDT</option>
              <option value="delete-fdt">Delete exact FDT endpoint</option>
            </select>
          </label>
        </div>
        {operation === "write-bdt" ? (
          <>
            <p>
              Desired BDT replacement: {rows.length} entries. Zero rows clears
              the entire BDT. Native IP, port and mask bytes are preserved; the
              BBMD decides whether it accepts them.
            </p>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Peer IPv4</th>
                    <th>Native UDP port</th>
                    <th>Distribution mask</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, index) => (
                    <tr key={index}>
                      {(["ip", "port", "mask"] as const).map((key) => (
                        <td key={key}>
                          <input
                            aria-label={`BDT ${key} ${index + 1}`}
                            value={row[key]}
                            disabled={busy}
                            onChange={(e) => edit(index, key, e.target.value)}
                          />
                        </td>
                      ))}
                      <td>
                        <button
                          aria-label={`Remove BDT row ${index + 1}`}
                          disabled={busy}
                          onClick={() => {
                            forgetReview();
                            setRows(
                              rows.filter((_, position) => position !== index),
                            );
                          }}
                        >
                          Remove
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="button-row">
              <button
                disabled={busy || !connected || watch}
                onClick={() => void act("load")}
              >
                Load current BDT into draft
              </button>
              <button
                disabled={busy || rows.length >= 256}
                onClick={() => {
                  forgetReview();
                  setRows([
                    ...rows,
                    { ip: "", port: "47808", mask: "255.255.255.255" },
                  ]);
                }}
              >
                Add BDT row
              </button>
            </div>
          </>
        ) : (
          <label>
            Exact FDT endpoint to delete
            <input
              aria-label="Exact FDT endpoint to delete"
              value={target}
              disabled={busy}
              placeholder="IPv4:port exactly as advertised"
              onChange={(e) => {
                forgetReview();
                setTarget(e.target.value);
              }}
            />
          </label>
        )}
        <div className="button-row">
          <button
            disabled={
              busy ||
              !connected ||
              watch ||
              !endpoint.trim() ||
              (operation === "delete-fdt" && !target.trim())
            }
            onClick={() => void act("preview")}
          >
            Prepare BBMD change review
          </button>
          <button disabled={busy} onClick={() => void act("history")}>
            Load BBMD change history
          </button>
        </div>
        {!connected && (
          <p className="help-text">
            Open a plain BACnet/IPv4 interface explicitly. This feature does not
            interrupt a foreign-device registration.
          </p>
        )}
        {proposal && (
          <section aria-label="BBMD change approval">
            <h4>
              Apply review for {proposal.endpoint} · {proposal.operation}
            </h4>
            <p>
              Expires UTC {proposal.expires_at}. Review hash{" "}
              {proposal.review_hash}. Original and desired bytes shown in the
              receipt below.
            </p>
            <label>
              <input
                type="checkbox"
                aria-label="Acknowledge exact BBMD change and protocol limits"
                checked={acknowledged}
                disabled={busy}
                onChange={(e) => setAcknowledged(e.target.checked)}
              />{" "}
              I reviewed this exact source and replacement/removal. Results
              cannot prove authorship or atomicity.
            </label>
            <button
              disabled={busy || !connected || !acknowledged || watch}
              onClick={() => void act("apply")}
            >
              Apply reviewed BBMD change once
            </button>
          </section>
        )}
        {notice && <p role="status">{notice}</p>}
        {error && (
          <p role="alert" className="inline-error">
            {error}
          </p>
        )}
        {!!history.length && (
          <details>
            <summary>
              Saved BBMD change history ({history.length} receipts)
            </summary>
            {history.map((item) => (
              <p key={item.id}>
                <button
                  disabled={busy}
                  onClick={() => void act("open", item.id)}
                >
                  {item.id}
                </button>{" "}
                · {item.endpoint} · {item.operation} · {item.state} ·
                Observation: {item.outcome}
              </p>
            ))}
          </details>
        )}
        {receipt && (
          <section aria-label={`BBMD change receipt ${receipt.id}`}>
            <h4>
              Receipt {receipt.id} · {receipt.endpoint} · {receipt.operation}
            </h4>
            <p>
              State: {receipt.state} · Write outcome:{" "}
              {receipt.write_outcome || "not-dispatched"} · Observation:{" "}
              {receipt.outcome}. Authorship proven: no. Atomic CAS: no.
            </p>
            {receipt.write_result && (
              <p>
                Native Result evidence:{" "}
                {receipt.write_result.result_hex ||
                  receipt.write_result.result_code ||
                  receipt.write_result.state}
                . It does not prove acceptance.
              </p>
            )}
            {!!receipt.results_observed?.length && (
              <p>
                All retained native Results:{" "}
                {receipt.results_observed
                  .map((item: any) =>
                    item.result_code === null
                      ? "malformed"
                      : `0x${Number(item.result_code).toString(16).padStart(4, "0")}`,
                  )
                  .join(", ")}
                . Additional Results omitted: {receipt.results_omitted}.
              </p>
            )}
            {receipt.last_native_admin_nack && (
              <p role="status">
                Native administration NACK observed: 0x
                {Number(receipt.last_native_admin_nack.result_code)
                  .toString(16)
                  .padStart(4, "0")}
                . Retained separately from the bounded Result list. Its
                relationship to this operation is unproven.
              </p>
            )}
            {receipt.target_before && (
              <p>
                Target {receipt.target_before.address} · Native TTL{" "}
                {receipt.target_before.ttl_seconds}s · Remaining at preview{" "}
                {receipt.target_before.remaining_seconds}s. Lease generation
                unproven.
              </p>
            )}
            {receipt.reason && <p>{receipt.reason}</p>}
            {receipt.storage_error && (
              <p role="alert">
                {receipt.storage_error} Runtime observations may be absent from
                durable storage.
              </p>
            )}
            <div className="button-row">
              <button
                disabled={busy || !receipt.active_in_this_process}
                onClick={() => void act("cancel", receipt.id)}
              >
                Cancel BBMD Apply
              </button>
              <button
                disabled={busy}
                onClick={() => void act("export", receipt.id)}
              >
                Export BBMD change receipt
              </button>
              <button
                disabled={
                  busy ||
                  !connected ||
                  watch ||
                  receipt.operation !== "write-bdt"
                }
                onClick={() => void act("restore", receipt.id)}
              >
                Review restoring BDT before-state
              </button>
            </div>
            <details open>
              <summary>Original table and proposed change</summary>
              <pre>
                {JSON.stringify(
                  {
                    endpoint: receipt.endpoint,
                    interface: receipt.config,
                    local_endpoint: receipt.local_endpoint,
                    interface_id: receipt.interface_id,
                    before: receipt.before,
                    desired_rows: receipt.desired_rows,
                    delete_target: receipt.delete_target,
                    write_wire_hex: receipt.write_wire_hex,
                    write_sha256: receipt.write_sha256,
                  },
                  null,
                  2,
                )}
              </pre>
            </details>
            <details>
              <summary>Full evidence and protocol limits</summary>
              <pre>{JSON.stringify(receipt, null, 2)}</pre>
            </details>
          </section>
        )}
      </div>
    </section>
  );
}
