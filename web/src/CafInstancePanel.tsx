import { useEffect, useRef, useState } from "react";
import { api, download } from "./api";

export function CafInstancePanel({
  id,
  filename,
  disabled,
  otherChangesPending,
  onDirtyChange,
}: {
  id: string;
  filename: string;
  disabled: boolean;
  otherChangesPending: boolean;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const [identity, setIdentity] = useState<any>(null);
  const [value, setValue] = useState("");
  const [plan, setPlan] = useState<any>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState("");
  const epoch = useRef(0),
    mounted = useRef(false),
    active = useRef(false);
  const signature = JSON.stringify([id, value]);
  const dirty =
    !!value &&
    !!identity &&
    Number(value) !== identity.instance &&
    saved !== signature;
  useEffect(() => {
    onDirtyChange(dirty);
  }, [dirty, onDirtyChange]);
  useEffect(() => {
    mounted.current = true;
    if (disabled)
      return () => {
        mounted.current = false;
        epoch.current++;
      };
    const generation = ++epoch.current;
    api(`/caf/${id}/device-instance`)
      .then((result) => {
        if (mounted.current && epoch.current === generation)
          setIdentity(result);
      })
      .catch((failure) => {
        if (mounted.current && epoch.current === generation)
          setError(String(failure));
      });
    return () => {
      mounted.current = false;
      epoch.current++;
    };
  }, [id, disabled]);
  useEffect(() => {
    if (disabled) {
      epoch.current++;
      active.current = false;
      setBusy(false);
      setPlan(null);
    }
  }, [disabled]);
  function edit(next: string) {
    epoch.current++;
    setValue(next);
    setPlan(null);
    setMessage("");
    setError("");
  }
  async function review() {
    if (disabled || active.current || !identity) return;
    active.current = true;
    setBusy(true);
    setError("");
    setPlan(null);
    setMessage("");
    const generation = ++epoch.current;
    const current = () => mounted.current && epoch.current === generation;
    try {
      if (!/^(0|[1-9][0-9]*)$/.test(value) || Number(value) > 4194302)
        throw new Error("Enter an integer from 0 through 4194302.");
      const result = await api(`/caf/${id}/device-instance/preview`, {
        source_sha256: id,
        expected_instance: identity.instance,
        new_instance: Number(value),
      });
      if (current()) setPlan(result);
    } catch (failure) {
      if (current()) setError(String(failure));
    } finally {
      if (current()) {
        active.current = false;
        setBusy(false);
      }
    }
  }
  async function save() {
    if (disabled || active.current || !plan) return;
    active.current = true;
    setBusy(true);
    setError("");
    setMessage("");
    const generation = ++epoch.current,
      snapshot = signature;
    const current = () => mounted.current && epoch.current === generation;
    try {
      const result = await download(
        `/caf/${id}/device-instance/export`,
        {
          source_sha256: id,
          expected_instance: plan.old_instance,
          new_instance: plan.new_instance,
          plan_sha256: plan.plan_sha256,
        },
        `${filename.replace(/\.caf$/i, "")}-instance-${plan.new_instance}.caf`,
        current,
      );
      if (result && current()) {
        setSaved(snapshot);
        setMessage(
          "Saved a separate CAF copy with the reviewed instance number. The original file and connected controller have not changed.",
        );
      }
    } catch (failure) {
      if (current()) setError(String(failure));
    } finally {
      if (current()) {
        active.current = false;
        setBusy(false);
      }
    }
  }
  return (
    <details className="card" aria-label="CAF device instance" open>
      <summary className="card-header">
        <h3>Device settings · Instance number</h3>
      </summary>
      <div className="card-body">
        <p>
          Source: <strong>{filename}</strong> · local CAF
        </p>
        {identity && (
          <p>
            {identity.name || identity.model || "CAF controller"} · current
            instance <strong>{identity.instance}</strong>
          </p>
        )}
        <p className="help-text">
          Prepare a CAF copy for commissioning. Saving this file does not
          transfer it to the controller. Reserve the proposed number across the
          BACnet internetwork before a field change.
        </p>
        {otherChangesPending && (
          <p role="status">
            This copy uses the opened CAF. Other pending file edits are
            excluded.
          </p>
        )}
        <label>
          New CAF device instance (0–4194302)
          <input
            value={value}
            disabled={!identity || disabled || busy}
            onChange={(event) => edit(event.target.value)}
            inputMode="numeric"
          />
        </label>
        <button
          disabled={!identity || disabled || busy || !value}
          onClick={() => void review()}
        >
          Review CAF instance change
        </button>
        {plan && (
          <div aria-label="Reviewed CAF instance change">
            <p>
              <strong>
                {plan.old_instance} → {plan.new_instance}
              </strong>{" "}
              · {plan.root_ref}
            </p>
            <p>
              {plan.changes.length === 0
                ? "No change; the saved copy will be byte-for-byte identical."
                : "Updates the root Device identifier and matching archive identity together. Logic, I/O, expansion configuration and existing references remain unchanged."}
            </p>
            <button disabled={disabled || busy} onClick={() => void save()}>
              Save CAF instance copy
            </button>
          </div>
        )}
        {error && <p role="alert">{error}</p>}
        {message && <p role="status">{message}</p>}
      </div>
    </details>
  );
}
