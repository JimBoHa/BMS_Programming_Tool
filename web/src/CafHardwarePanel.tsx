import { useEffect, useRef, useState } from "react";
import { Download, FileCheck2 } from "lucide-react";
import { api, download, saveBlob } from "./api";

type Binding = {
  ref: string;
  object: string;
  name: string;
  slot: number;
  device_type: string;
  movable: boolean;
};
type Inventory = {
  supported: boolean;
  source_sha256: string;
  model?: string;
  device?: string;
  inputs: Binding[];
  unassigned_slots: number[];
  errors: string[];
  boundary: string;
};

export function CafHardwarePanel({
  id,
  filename,
  disabled,
  onDirtyChange,
}: {
  id: string;
  filename: string;
  disabled: boolean;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const [inventory, setInventory] = useState<Inventory | null>(null);
  const [source, setSource] = useState("");
  const [destination, setDestination] = useState("");
  const [plan, setPlan] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [exported, setExported] = useState("");
  const mounted = useRef(false),
    epoch = useRef(0),
    active = useRef(false);
  const selected = inventory?.inputs.find((p) => p.ref === source);
  const signature = JSON.stringify([id, source, destination]);
  const dirty =
    !!selected &&
    !!destination &&
    Number(destination) !== selected.slot &&
    signature !== exported;
  useEffect(() => {
    onDirtyChange(dirty);
  }, [dirty, onDirtyChange]);
  useEffect(() => {
    mounted.current = true;
    let current = true;
    api(`/caf/${id}/hardware`)
      .then((next) => {
        if (mounted.current && current) setInventory(next);
      })
      .catch((e) => {
        if (mounted.current && current) setError(String(e));
      });
    return () => {
      current = false;
      mounted.current = false;
      epoch.current++;
    };
  }, [id]);
  useEffect(() => {
    if (disabled) {
      epoch.current++;
      active.current = false;
      setBusy(false);
    }
  }, [disabled]);
  function edit(work: () => void) {
    epoch.current++;
    setPlan(null);
    setError("");
    setMessage("");
    work();
  }
  async function review() {
    if (!selected || !destination || disabled || active.current) return;
    active.current = true;
    setBusy(true);
    setError("");
    setMessage("");
    const generation = ++epoch.current;
    try {
      const next = await api(`/caf/${id}/hardware/preview`, {
        source_sha256: id,
        ref: source,
        old_slot: selected.slot,
        destination_slot: Number(destination),
      });
      if (mounted.current && epoch.current === generation) setPlan(next);
    } catch (e) {
      if (mounted.current && epoch.current === generation) setError(String(e));
    } finally {
      if (mounted.current && epoch.current === generation) {
        active.current = false;
        setBusy(false);
      }
    }
  }
  async function exportCaf() {
    if (!plan || disabled || active.current) return;
    active.current = true;
    setBusy(true);
    setError("");
    const generation = ++epoch.current,
      snapshot = signature;
    const current = () => mounted.current && epoch.current === generation;
    try {
      const saved = await download(
        `/caf/${id}/hardware/export`,
        { ...plan.request, plan_sha256: plan.plan_sha256 },
        `${filename.replace(/\.caf$/i, "")}-hardware.caf`,
        current,
      );
      if (saved && current()) {
        setExported(snapshot);
        setMessage(
          "Downloaded a separate CAF with the reviewed terminal edit. Reopen that copy to inspect it. CCT/PCT acceptance remains unverified.",
        );
      }
    } catch (e) {
      if (current()) setError(String(e));
    } finally {
      if (current()) {
        active.current = false;
        setBusy(false);
      }
    }
  }
  return (
    <section
      className="card"
      role="region"
      aria-label="Offline CAF hardware bindings"
    >
      <div className="card-header">
        <h3>
          <FileCheck2 size={17} /> Offline CAF terminal binding
        </h3>
      </div>
      <div className="card-body">
        <p>
          Move an existing input between compatible universal terminals on the
          same base controller in a separate CAF copy. This preserves its signal
          curve and application references.
        </p>
        <p className="help-text">
          This profile does not move inputs between SA modules, create new
          points, compile applications, download programs or change running
          controllers. Hardware copies exclude other pending CAF edits; reopen
          an exported copy to combine changes.
        </p>
        {!inventory && !error && (
          <p role="status">Inspecting native input bindings…</p>
        )}
        {inventory && !inventory.supported && (
          <p role="status">
            Terminal editing unavailable for this archive:{" "}
            {inventory.errors.join(" ")}
          </p>
        )}
        {inventory?.supported && (
          <>
            <p>
              {inventory.model} · {inventory.device} · Candidate unassigned
              local terminals:{" "}
              {inventory.unassigned_slots.map((s) => `IN${s}`).join(", ") ||
                "None"}
            </p>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Existing input</th>
                    <th scope="col">Object / reference</th>
                    <th scope="col">Terminal</th>
                    <th scope="col">Edit scope</th>
                  </tr>
                </thead>
                <tbody>
                  {inventory.inputs.map((p) => (
                    <tr key={p.ref}>
                      <td>{p.name || p.object}</td>
                      <td>
                        {p.object}
                        <br />
                        <code>{p.ref}</code>
                      </td>
                      <td>{p.device_type}</td>
                      <td>
                        {p.movable
                          ? "Local universal input"
                          : "Internal DPT — fixed"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="form-grid">
              <label>
                CAF input to move
                <select
                  aria-label="CAF input to move"
                  value={source}
                  disabled={disabled || busy}
                  onChange={(e) =>
                    edit(() => {
                      setSource(e.target.value);
                      setDestination("");
                    })
                  }
                >
                  <option value="">Choose an existing local UI</option>
                  {inventory.inputs
                    .filter((p) => p.movable)
                    .map((p) => (
                      <option key={p.ref} value={p.ref}>
                        {p.name || p.object} · {p.device_type}
                      </option>
                    ))}
                </select>
              </label>
              <label>
                CAF destination universal input
                <select
                  aria-label="CAF destination universal input"
                  value={destination}
                  disabled={!selected || disabled || busy}
                  onChange={(e) => edit(() => setDestination(e.target.value))}
                >
                  <option value="">Choose a terminal</option>
                  {selected &&
                    [selected.slot, ...inventory.unassigned_slots]
                      .filter((s, i, a) => a.indexOf(s) === i)
                      .sort()
                      .map((slot) => (
                        <option key={slot} value={slot}>
                          IN{slot}
                          {slot === selected.slot
                            ? " (current)"
                            : " (candidate unassigned)"}
                        </option>
                      ))}
                </select>
              </label>
            </div>
            <button
              disabled={!selected || !destination || disabled || busy}
              onClick={review}
            >
              Review CAF terminal edit
            </button>
            {plan && (
              <section aria-label="CAF terminal edit review">
                <p>
                  <strong>
                    Offline edit review — native validation pending
                  </strong>
                </p>
                <pre>{JSON.stringify(plan, null, 2)}</pre>
                <div className="button-row">
                  <button disabled={disabled || busy} onClick={exportCaf}>
                    <Download size={14} /> Download terminal-edited CAF
                  </button>
                  <button
                    disabled={disabled || busy}
                    onClick={() =>
                      saveBlob(
                        new Blob([JSON.stringify(plan, null, 2)], {
                          type: "application/json",
                        }),
                        `${filename.replace(/\.caf$/i, "")}-hardware-review.json`,
                      )
                    }
                  >
                    Download terminal review JSON
                  </button>
                </div>
              </section>
            )}
            {dirty && (
              <p className="help-text">
                Current terminal proposal has not been exported.
              </p>
            )}
          </>
        )}
        {error && (
          <p className="inline-error" role="alert">
            {error}
          </p>
        )}
        {message && <p role="status">{message}</p>}
      </div>
    </section>
  );
}
