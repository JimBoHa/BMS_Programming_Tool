import { useEffect, useRef, useState } from "react";
import { api, apiKeepalive, saveBlob } from "./api";
import type { ControllerTarget } from "./workflow";
import "./sa-bus-probe.css";

const base = "/bacnet/controller/sa-bus-probe";
const labels: Record<string, string> = {
  not_tested: "Not tested",
  testing: "Testing",
  success_reported: "Diagnostic success reported",
  diagnostic_error: "Controller reported diagnostic error",
  test_timeout: "Diagnostic still pending at deadline",
  uncertain: "Outcome uncertain",
};
type Probe = {
  id: string;
  state: string;
  error: string | null;
  recovery_required: boolean;
  restoration: string;
  started_at: string;
  finished_at: string | null;
  plan: { target: ControllerTarget; identity: Record<string, any> };
  rows: {
    mac: number;
    status: string;
    code: number | null;
    observed_pending?: boolean;
  }[];
};

export function SaBusProbePanel({
  connected,
  target,
  interfaceIdentity,
}: {
  connected: boolean;
  target: ControllerTarget | null;
  interfaceIdentity: string;
}) {
  const [low, setLow] = useState("199");
  const [high, setHigh] = useState("206");
  const [review, setReview] = useState<any>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [report, setReport] = useState<Probe | null>(null);
  const [saved, setSaved] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const generation = useRef(0);
  const activeJob = useRef<string | null>(null);
  const selected = target
    ? {
        address: target.address,
        device: target.device,
        router: target.router || null,
        dnet: target.dnet ?? null,
      }
    : null;
  const owner = JSON.stringify([selected, interfaceIdentity, connected]);
  const running = !!report && ["running", "cancelling"].includes(report.state);

  useEffect(() => {
    const epoch = ++generation.current;
    setReview(null);
    setConfirmed(false);
    setReport(null);
    setError("");
    setMessage("");
    setBusy(false);
    void api(base + "/reports")
      .then((rows) => {
        if (epoch === generation.current) setSaved(rows);
      })
      .catch((e) => {
        if (epoch === generation.current) setError(e.message);
      });
    return () => {
      ++generation.current;
      if (activeJob.current)
        void apiKeepalive(
          `${base}/reports/${activeJob.current}/cancel`,
          {},
        ).catch(() => {});
      activeJob.current = null;
    };
  }, [owner]);

  useEffect(() => {
    if (!running || !report) return;
    let retired = false;
    const epoch = generation.current;
    let timer: ReturnType<typeof setTimeout>;
    // One in-flight request: a slow progress response cannot replace a newer
    // terminal result or accumulate large retained-evidence downloads.
    async function poll() {
      try {
        const value: Probe = await api(`${base}/reports/${report!.id}`);
        if (retired || epoch !== generation.current) return;
        setReport(value);
        if (!["running", "cancelling"].includes(value.state)) {
          activeJob.current = null;
          setMessage(
            "Probe finished. Review each address and diagnostic restoration below.",
          );
          return;
        }
      } catch (e) {
        if (!retired && epoch === generation.current)
          setError(
            `Progress unavailable: ${(e as Error).message}. The server may still be testing; reopen its saved report.`,
          );
      }
      if (!retired && epoch === generation.current)
        timer = setTimeout(poll, 1000);
    }
    timer = setTimeout(poll, 1000);
    return () => {
      retired = true;
      clearTimeout(timer);
    };
  }, [running, report?.id]);

  async function action(work: () => Promise<void>) {
    const epoch = generation.current;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await work();
    } catch (e) {
      if (epoch === generation.current) setError((e as Error).message);
    } finally {
      if (epoch === generation.current) setBusy(false);
    }
  }
  function invalidate() {
    setReview(null);
    setConfirmed(false);
  }
  const matching = (value: ControllerTarget) =>
    JSON.stringify({
      address: value.address,
      device: value.device,
      router: value.router || null,
      dnet: value.dnet ?? null,
    }) === JSON.stringify(selected);

  return (
    <section
      className="card sa-bus-probe"
      aria-label="SA-bus address diagnostics"
    >
      <h3>SA-bus address diagnostics</h3>
      <p>
        Test addresses behind the selected controller, using its native SA-port
        communication test. This briefly changes a diagnostic selector and
        restores it to zero. Application settings, configured sensor addresses
        and operating points are preserved.
      </p>
      <p className="help-text">
        The default 199–206 range covers NS8000 address switches. Other SA
        devices may use different addresses. Each request is limited to 16
        addresses; no automatic repeat scan runs.
      </p>
      {!connected && (
        <p role="status">
          Open and verify a controller on a BACnet/IP interface to run
          diagnostics.
        </p>
      )}
      <div className="form-grid">
        <label>
          First SA MAC
          <input
            type="number"
            min="1"
            max="254"
            value={low}
            disabled={busy || running}
            onChange={(e) => {
              setLow(e.target.value);
              invalidate();
            }}
          />
        </label>
        <label>
          Last SA MAC
          <input
            type="number"
            min="1"
            max="254"
            value={high}
            disabled={busy || running}
            onChange={(e) => {
              setHigh(e.target.value);
              invalidate();
            }}
          />
        </label>
      </div>
      {!review && (
        <button
          className="primary"
          disabled={!connected || !selected || busy || running}
          onClick={() =>
            void action(async () => {
              const epoch = generation.current;
              const value = await api(base + "/review", {
                ...selected,
                mac_low: Number(low),
                mac_high: Number(high),
              });
              if (epoch !== generation.current) return;
              if (
                !matching(value.target) ||
                value.target.mac_low !== Number(low) ||
                value.target.mac_high !== Number(high)
              )
                throw new Error(
                  "Review target or address range changed; review again.",
                );
              setReview(value);
              setConfirmed(false);
            })
          }
        >
          Review SA-bus probe
        </button>
      )}
      {review && (
        <div className="notice">
          <p>
            <strong>{review.identity["object-name"]}</strong> ·{" "}
            {review.identity["model-name"]} · Firmware{" "}
            {review.identity["firmware-revision"]}
          </p>
          <p>
            {review.target.address} · {review.target.device} · SA MAC{" "}
            {review.target.mac_low}–{review.target.mac_high}
          </p>
          <p>
            The review expires after two minutes. One controller is tested at a
            time. Cancellation finishes the current address test, then restores
            the diagnostic selector.
          </p>
          <label>
            <input
              type="checkbox"
              checked={confirmed}
              disabled={busy || running}
              onChange={(e) => setConfirmed(e.target.checked)}
            />{" "}
            Run temporary SA-port diagnostics on this controller
          </label>
          <button
            className="primary"
            disabled={!connected || busy || running || !confirmed}
            onClick={() =>
              void action(async () => {
                const epoch = generation.current;
                const intent = {
                  token: review.token,
                  review_sha256: review.review_sha256,
                  diagnostic_test_confirmed: confirmed,
                };
                invalidate();
                setReport(null);
                let value: Probe;
                try {
                  value = await api(base + "/run", intent);
                } catch (e) {
                  throw new Error(
                    `${(e as Error).message}. The start response was not received; the server may still be testing. Refresh saved probe reports to inspect or cancel it before another attempt.`,
                  );
                }
                if (epoch !== generation.current) {
                  void apiKeepalive(
                    `${base}/reports/${value.id}/cancel`,
                    {},
                  ).catch(() => {});
                  return;
                }
                activeJob.current = value.id;
                setReport(value);
                invalidate();
              })
            }
          >
            Run SA-bus probe
          </button>
          <button disabled={busy || running} onClick={invalidate}>
            Discard review
          </button>
        </div>
      )}
      {running && (
        <button
          disabled={busy}
          onClick={() =>
            void action(async () => {
              await api(`${base}/reports/${report!.id}/cancel`, {});
              setMessage(
                "Cancellation requested; waiting for the current test and restoration.",
              );
            })
          }
        >
          Cancel SA-bus probe
        </button>
      )}
      {message && <p role="status">{message}</p>}
      {error && <p role="alert">{error}</p>}
      {report && (
        <>
          <p role="status">
            Probe: {report.state} · Diagnostic restoration: {report.restoration}
          </p>
          {report.error && <p role="alert">{report.error}</p>}
          <p className="help-text">
            Success is the controller’s communication-test result. It does not
            verify sensor identity, measured temperature or wiring. An error or
            timeout does not prove physical absence.
          </p>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>SA MAC</th>
                  <th>Result</th>
                  <th>Native code</th>
                  <th>Pending state observed</th>
                </tr>
              </thead>
              <tbody>
                {report.rows.map((row) => (
                  <tr key={row.mac}>
                    <td>{row.mac}</td>
                    <td>{labels[row.status] || row.status}</td>
                    <td>{row.code ?? "—"}</td>
                    <td>
                      {row.observed_pending === undefined
                        ? "—"
                        : row.observed_pending
                          ? "Yes"
                          : "No"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {report.recovery_required && !running && (
            <>
              <p role="alert">
                Diagnostic restoration needs attention. New probes are blocked.
                Restore only the retained selector on its original controller;
                another tool’s destination will not be overwritten.
              </p>
              <button
                disabled={!connected || busy || !matching(report.plan.target)}
                onClick={() =>
                  void action(async () => {
                    const epoch = generation.current;
                    const value = await api(
                      `${base}/reports/${report.id}/recover`,
                      { restore_diagnostic_destination_confirmed: true },
                    );
                    if (epoch === generation.current) setReport(value);
                  })
                }
              >
                Restore original diagnostic destination
              </button>
            </>
          )}
          <button
            disabled={running || busy}
            onClick={() =>
              saveBlob(
                new Blob([JSON.stringify(report, null, 2)], {
                  type: "application/json",
                }),
                `sa-bus-probe-${report.id}.json`,
              )
            }
          >
            Download probe evidence
          </button>
        </>
      )}
      <details>
        <summary>Saved probe reports</summary>
        <button
          disabled={busy}
          onClick={() =>
            void action(async () => {
              const epoch = generation.current;
              const rows = await api(base + "/reports");
              if (epoch === generation.current) setSaved(rows);
            })
          }
        >
          Refresh saved reports
        </button>
        {saved
          .filter((item) => matching(item.target))
          .map((item) => (
            <p key={item.id}>
              <button
                disabled={busy || running}
                onClick={() =>
                  void action(async () => {
                    const epoch = generation.current;
                    const value = await api(`${base}/reports/${item.id}`);
                    if (epoch === generation.current) {
                      setReport(value);
                      if (["running", "cancelling"].includes(value.state))
                        activeJob.current = value.id;
                    }
                  })
                }
              >
                Open {item.started_at} · {item.state}
                {item.recovery_required ? " · restoration required" : ""}
              </button>
            </p>
          ))}
      </details>
    </section>
  );
}
