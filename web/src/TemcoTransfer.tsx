import { useEffect, useRef, useState } from "react";
import { Download, RefreshCw, ShieldCheck, Upload } from "lucide-react";
import { api, saveBlob } from "./api";

type Target = {
  address: string;
  device_instance: string;
  slot: string;
  expected_model: string;
  expected_firmware: string;
};
type Plan = {
  token: string;
  backup_id: string;
  target: Record<string, unknown>;
  generation: string;
  before_sha256: string;
  after_sha256: string;
  compiled_bytes: number;
  resume: boolean;
  original_running: boolean;
  final_running: boolean;
  expires_seconds: number;
  restored_backup: string | null;
  program_budget_bytes: number;
};

export function TemcoTransfer({ source }: { source: string | null }) {
  const [target, setTarget] = useState<Target>({
    address: "",
    device_instance: "",
    slot: "0",
    expected_model: "",
    expected_firmware: "",
  });
  const [status, setStatus] = useState<any>(null);
  const [inspection, setInspection] = useState<any>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [result, setResult] = useState<any>(null);
  const [backup, setBackup] = useState("");
  const [resume, setResume] = useState(true);
  const [reviewed, setReviewed] = useState(false);
  const [expires, setExpires] = useState(0);
  const [remaining, setRemaining] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const generation = useRef(0);
  const mounted = useRef(false);
  async function refresh() {
    const next = await api("/temco/transfer/status");
    if (mounted.current) setStatus(next);
    return next;
  }
  useEffect(() => {
    mounted.current = true;
    refresh().catch((e) => {
      if (mounted.current) setError(String(e));
    });
    return () => {
      mounted.current = false;
      generation.current++;
    };
  }, []);
  useEffect(() => {
    generation.current++;
    setPlan(null);
    setReviewed(false);
    setError("");
  }, [source]);
  useEffect(() => {
    if (!expires) return;
    const update = () =>
      setRemaining(Math.max(0, Math.ceil((expires - Date.now()) / 1000)));
    update();
    const timer = window.setInterval(update, 1000);
    return () => window.clearInterval(timer);
  }, [expires]);
  function invalidate() {
    generation.current++;
    setPlan(null);
    setReviewed(false);
    setInspection(null);
    setResult(null);
    setError("");
  }
  function requestTarget() {
    const instance = Number(target.device_instance),
      slot = Number(target.slot);
    if (
      !target.device_instance ||
      !Number.isInteger(instance) ||
      instance < 0 ||
      instance > 4194302
    )
      throw new Error("Enter the exact BACnet device instance (0..4194302).");
    if (!target.slot || !Number.isInteger(slot) || slot < 0 || slot > 15)
      throw new Error("Enter a zero-based program slot from 0 through 15.");
    if (
      !target.address.trim() ||
      !target.expected_model.trim() ||
      !target.expected_firmware.trim()
    )
      throw new Error("Address, exact model and exact firmware are required.");
    return {
      ...target,
      address: target.address.trim(),
      device_instance: instance,
      slot,
      expected_model: target.expected_model.trim(),
      expected_firmware: target.expected_firmware.trim(),
    };
  }
  async function action(
    kind:
      | "inspect"
      | "plan"
      | "restore-plan"
      | "apply"
      | "refresh"
      | "download",
  ) {
    if (busy) return;
    const requestGeneration = generation.current;
    setBusy(true);
    setError("");
    try {
      if (kind === "refresh") {
        await refresh();
        return;
      }
      if (kind === "download") {
        if (!backup) throw new Error("Choose a backup first.");
        const value = await api("/temco/transfer/backups/" + backup);
        saveBlob(
          new Blob([JSON.stringify(value, null, 2)], {
            type: "application/json",
          }),
          "temco-backup-" + backup + ".json",
        );
        return;
      }
      let next;
      if (kind === "apply") {
        if (!plan || !reviewed || !remaining)
          throw new Error("Review a current transfer plan before applying it.");
        const token = plan.token;
        setPlan(null);
        setReviewed(false);
        next = await api("/temco/transfer/apply", { token });
      } else {
        const identity = requestTarget();
        setResult(null);
        setPlan(null);
        setReviewed(false);
        if (kind === "inspect")
          next = await api("/temco/transfer/inspect", identity);
        else if (kind === "plan") {
          if (!source)
            throw new Error(
              "Compile this graph into Control Basic before planning a transfer.",
            );
          next = await api("/temco/transfer/plan", {
            ...identity,
            source,
            resume,
          });
        } else {
          if (!backup)
            throw new Error("Choose the backup for this exact target first.");
          next = await api("/temco/transfer/restore-plan", {
            ...identity,
            backup_id: backup,
            resume,
          });
        }
      }
      // Applying consumes a reviewed, pinned plan. A later authoring-source
      // change must not hide the outcome of a field operation already sent.
      if (
        !mounted.current ||
        (kind !== "apply" && requestGeneration !== generation.current)
      )
        return;
      if (kind === "inspect") setInspection(next);
      else if (kind === "apply") setResult(next);
      else {
        setPlan(next);
        setExpires(Date.now() + next.expires_seconds * 1000);
      }
      await refresh();
    } catch (e) {
      if (
        mounted.current &&
        (kind === "apply" || requestGeneration === generation.current)
      ) {
        setError(String(e));
        try {
          await refresh();
        } catch {
          /* Preserve the actionable request error. */
        }
      }
    } finally {
      if (mounted.current) setBusy(false);
    }
  }

  return (
    <section
      className="temco-card"
      aria-label="Temco controller program transfer"
    >
      <h2>Controller program transfer</h2>
      <p>
        Use the shared BACnet connection from Connect. This adapter supports the
        observed Temco program-slot protocol. It verifies vendor 148 and the
        exact device, model, firmware and slot before each write.
      </p>
      <p className="temco-scope">
        Replacement stops the selected program. Existing outputs may remain
        commanded while stopped. This is not an atomic online edit. Only the
        program image and descriptor are backed up. Physical execution, flash
        persistence, scan cadence and host calendar services require separate
        commissioning.
      </p>
      <div className="temco-actions">
        {(
          [
            ["address", "Temco device address", "e.g. 192.0.2.10 or 2001:5"],
            [
              "device_instance",
              "Temco device instance",
              "Exact BACnet instance",
            ],
            ["slot", "Temco program slot (0–15)", "0"],
            ["expected_model", "Temco expected model", "Exact model-name"],
            [
              "expected_firmware",
              "Temco expected firmware",
              "Exact firmware-revision",
            ],
          ] as const
        ).map(([key, label, placeholder]) => (
          <label key={key} style={{ maxWidth: key === "address" ? 230 : 190 }}>
            {label}
            <input
              aria-label={label}
              value={target[key]}
              placeholder={placeholder}
              disabled={busy}
              onChange={(e) => {
                invalidate();
                setTarget({ ...target, [key]: e.target.value });
              }}
            />
          </label>
        ))}
      </div>
      <div className="temco-actions">
        <label className="temco-transfer-review" style={{ maxWidth: 460 }}>
          <input
            type="checkbox"
            aria-label="Resume previously running Temco program"
            checked={resume}
            disabled={busy}
            onChange={(e) => {
              invalidate();
              setResume(e.target.checked);
            }}
          />{" "}
          Resume after verification if the program was running
        </label>
      </div>
      <div className="temco-actions">
        <button disabled={busy} onClick={() => action("refresh")}>
          <RefreshCw size={15} />
          Refresh transfer status
        </button>
        <button disabled={busy} onClick={() => action("inspect")}>
          <ShieldCheck size={15} />
          Inspect Temco program slot
        </button>
        <button disabled={busy || !source} onClick={() => action("plan")}>
          <Upload size={15} />
          Plan compiled program transfer
        </button>
      </div>
      {!source && (
        <p className="temco-muted">
          Compile Control Basic above to enable replacement planning. Inspection
          and backup restoration remain available.
        </p>
      )}
      {inspection && (
        <details open>
          <summary>Verified slot snapshot</summary>
          <pre>{JSON.stringify(inspection, null, 2)}</pre>
        </details>
      )}
      {status && (
        <>
          <p>
            Shared BACnet interface:{" "}
            {status.connected ? "connected" : "not connected"}.{" "}
            {status.backups.length} durable program backups.
          </p>
          {!!status.uncertain.length && (
            <div className="temco-error" role="alert">
              {status.uncertain.length} operations require manual recovery
              review. No recovery writes run automatically. Inspect the current
              slot and operation history before creating a restore plan.
            </div>
          )}
          <details>
            <summary>Transfer operation history and profile limits</summary>
            <pre>
              {JSON.stringify(
                {
                  operations: status.operations,
                  limits: status.limits,
                  source_commits: status.source_commits,
                },
                null,
                2,
              )}
            </pre>
          </details>
          <div className="temco-actions">
            <label style={{ maxWidth: 460 }}>
              Durable slot backup
              <select
                aria-label="Temco durable slot backup"
                value={backup}
                disabled={busy}
                onChange={(e) => {
                  invalidate();
                  setBackup(e.target.value);
                }}
              >
                <option value="">Choose a backup…</option>
                {status.backups.map((item: any) => (
                  <option key={item.id} value={item.id}>
                    {item.created} · {item.target.address} · slot{" "}
                    {item.target.slot}
                  </option>
                ))}
              </select>
            </label>
            <button
              disabled={busy || !backup}
              onClick={() => action("download")}
            >
              <Download size={15} />
              Download Temco backup JSON
            </button>
            <button
              disabled={busy || !backup}
              onClick={() => action("restore-plan")}
            >
              Plan backup restoration
            </button>
          </div>
        </>
      )}
      {plan && (
        <section
          className="temco-transfer-plan"
          aria-label="Reviewed Temco transfer plan"
        >
          <h3>
            {plan.restored_backup ? "Restore plan" : "Program replacement plan"}{" "}
            · expires in {remaining} seconds
          </h3>
          <p>
            Slot {String(plan.target.slot)} on {String(plan.target.address)} ·{" "}
            {plan.compiled_bytes} native image bytes ·{" "}
            {plan.program_budget_bytes} total program bytes. Durable rollback
            backup: <code>{plan.backup_id}</code>.
          </p>
          <p>
            After readback, the program will{" "}
            {plan.final_running ? "run" : "remain stopped"}.
          </p>
          <details>
            <summary>
              Review pinned identity, generation and image hashes
            </summary>
            <pre>{JSON.stringify({ ...plan, token: undefined }, null, 2)}</pre>
          </details>
          <label className="temco-transfer-review">
            <input
              type="checkbox"
              aria-label="Reviewed Temco program stop and replacement"
              checked={reviewed}
              disabled={busy}
              onChange={(e) => setReviewed(e.target.checked)}
            />{" "}
            I reviewed this exact target, slot, backup and output behavior while
            the program is stopped.
          </label>
          <div className="temco-actions">
            <button
              className="primary"
              disabled={busy || !reviewed || !remaining}
              onClick={() => action("apply")}
            >
              <Upload size={15} />
              Apply reviewed Temco transfer
            </button>
            <button
              disabled={busy}
              onClick={() => {
                setPlan(null);
                setReviewed(false);
              }}
            >
              Discard transfer plan
            </button>
          </div>
        </section>
      )}
      {busy && <p role="status">Working on the explicit Temco request…</p>}
      {error && (
        <div className="temco-error" role="alert">
          {error}
        </div>
      )}
      {result && (
        <section
          aria-label="Temco transfer result"
          className={result.ok ? "temco-result-match" : "temco-error"}
        >
          <strong>
            {result.ok
              ? "Program image readback verified"
              : "Transfer failed; review recovery outcome"}
          </strong>
          <p>
            Device {result.target.address} · slot {result.target.slot}.{" "}
            {result.ok
              ? result.running
                ? "Program is running."
                : "Program remains stopped."
              : result.recovery?.restored
                ? "Original program image and run state were restored."
                : "Manual recovery is required; inspect the slot before further changes."}
          </p>
          {!result.ok && <p>{result.error}</p>}
          <details open={!result.ok}>
            <summary>Transfer, backup and readback evidence</summary>
            <pre>{JSON.stringify(result, null, 2)}</pre>
          </details>
        </section>
      )}
    </section>
  );
}
