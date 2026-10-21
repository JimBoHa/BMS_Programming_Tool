import { useEffect, useRef, useState } from "react";
import { api, download, saveBlob } from "./api";
import "./jci-preflight.css";

type Draft = {
  target_model: string;
  target_firmware: string;
  application_object_ref: string;
  transport: string;
  inventory_text: string;
  hardware_sha256: string | null;
};

const initial: Draft = {
  target_model: "",
  target_firmware: "",
  application_object_ref: "",
  transport: "unspecified",
  inventory_text: "{}",
  hardware_sha256: null,
};

export function JciPreflight({
  id,
  disabled = false,
}: {
  id: string;
  disabled?: boolean;
}) {
  const [draft, setDraft] = useState<Draft>(initial);
  const [report, setReport] = useState<any>(null);
  const [reportKey, setReportKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [hardwareName, setHardwareName] = useState("");
  const inventoryInput = useRef<HTMLInputElement>(null);
  const hardwareInput = useRef<HTMLInputElement>(null);
  const request = useRef(0);
  const currentDraft = useRef(draft);
  currentDraft.current = draft;
  const current = JSON.stringify(draft);
  const stale = !!report && current !== reportKey;

  useEffect(() => {
    let active = true;
    const generation = ++request.current;
    setBusy(true);
    api(`/caf/${id}/preflight`)
      .then((value) => {
        if (!active || request.current !== generation) return;
        setReport(value);
        setReportKey(JSON.stringify(initial));
      })
      .catch((failure) => {
        if (active && request.current === generation) setError(String(failure));
      })
      .finally(() => {
        if (active && request.current === generation) setBusy(false);
      });
    return () => {
      active = false;
      request.current++;
    };
  }, [id]);

  function change<K extends keyof Draft>(key: K, value: Draft[K]) {
    setDraft((previous) => ({ ...previous, [key]: value }));
    setError("");
  }

  async function run(exportReport = false) {
    if (disabled || busy) return;
    const generation = ++request.current;
    const snapshot = { ...draft };
    setBusy(true);
    setError("");
    try {
      if (exportReport) {
        await download(
          `/caf/${id}/preflight/export`,
          snapshot,
          "jci-target-readiness.json",
          () =>
            generation === request.current &&
            JSON.stringify(currentDraft.current) === JSON.stringify(snapshot),
        );
      } else {
        const next = await api(`/caf/${id}/preflight`, snapshot);
        if (generation !== request.current) return;
        setReport(next);
        setReportKey(JSON.stringify(snapshot));
      }
    } catch (failure) {
      if (generation === request.current) setError(String(failure));
    } finally {
      if (generation === request.current) setBusy(false);
    }
  }

  async function loadInventory(file?: File) {
    if (!file || disabled || busy) return;
    if (file.size > 256 * 1024) {
      setError("Inventory JSON must be at most 256 KiB.");
      return;
    }
    const generation = ++request.current;
    setBusy(true);
    setError("");
    try {
      const text = new TextDecoder("utf-8", {
        fatal: true,
        ignoreBOM: true,
      }).decode(await file.arrayBuffer());
      if (generation !== request.current) return;
      change("inventory_text", text);
    } catch {
      if (generation === request.current)
        setError("Inventory must be readable UTF-8 JSON text.");
    } finally {
      if (generation === request.current) setBusy(false);
    }
  }

  async function loadHardware(file?: File) {
    if (!file || disabled || busy) return;
    if (file.size > 8 * 1024 * 1024) {
      setError("Hardware XML must be at most 8 MiB.");
      return;
    }
    const generation = ++request.current;
    setBusy(true);
    setError("");
    try {
      const form = new FormData();
      form.append("file", file);
      const value = await api("/jci/hardware/open", form);
      if (generation !== request.current) return;
      change("hardware_sha256", value.sha256);
      setHardwareName(file.name);
    } catch (failure) {
      if (generation === request.current) setError(String(failure));
    } finally {
      if (generation === request.current) setBusy(false);
    }
  }

  async function template() {
    if (disabled || busy) return;
    const generation = ++request.current;
    setBusy(true);
    setError("");
    try {
      const value = await api("/jci/preflight/template");
      if (generation !== request.current) return;
      saveBlob(
        new Blob([JSON.stringify(value, null, 2)], {
          type: "application/json",
        }),
        "jci-inventory-template.json",
      );
    } catch (failure) {
      if (generation === request.current) setError(String(failure));
    } finally {
      if (generation === request.current) setBusy(false);
    }
  }

  return (
    <section className="card jci-preflight" aria-label="JCI target readiness">
      <div className="card-header">
        <h2>Target readiness</h2>
      </div>
      <p>
        Compare the original CAF with your intended controller and declared
        CCT/PCT installation, licenses, and controller packages. Inventory
        values are supplied evidence; this check does not inspect another
        computer or VM.
      </p>
      <p>
        CAF release/application version, controller firmware, and tool version
        are checked separately. A matching report does not authorize deployment.
      </p>
      <fieldset disabled={disabled || busy}>
        <legend>Intended target</legend>
        <div className="jci-preflight-fields">
          <label>
            Target controller model
            <input
              value={draft.target_model}
              placeholder="Exact model and suffix"
              onChange={(event) => change("target_model", event.target.value)}
            />
          </label>
          <label>
            Target controller firmware
            <input
              value={draft.target_firmware}
              placeholder="Firmware from controller inventory"
              onChange={(event) =>
                change("target_firmware", event.target.value)
              }
            />
          </label>
          <label>
            Application object
            <select
              aria-label="Application object"
              value={draft.application_object_ref}
              onChange={(event) =>
                change("application_object_ref", event.target.value)
              }
            >
              <option value="">Automatic if exactly one candidate</option>
              {report?.application_candidates.map((row: any) => (
                <option key={row.object_ref} value={row.object_ref}>
                  {row.object_ref} · {row.model || "Model unknown"}
                </option>
              ))}
            </select>
          </label>
          <label>
            Planned connection
            <select
              aria-label="Planned connection"
              value={draft.transport}
              onChange={(event) => change("transport", event.target.value)}
            >
              <option value="unspecified">Not specified</option>
              <option value="bacnet-ip">BACnet/IP or routed MS/TP</option>
              <option value="btcvt">BTCVT Bluetooth</option>
              <option value="direct-serial">Direct serial</option>
            </select>
          </label>
        </div>
        <div className="jci-preflight-actions">
          <button type="button" onClick={() => inventoryInput.current?.click()}>
            Load inventory JSON
          </button>
          <button type="button" onClick={() => void template()}>
            Download inventory template
          </button>
          <button type="button" onClick={() => hardwareInput.current?.click()}>
            Attach hardware definition XML
          </button>
          {draft.hardware_sha256 && (
            <button
              type="button"
              onClick={() => {
                change("hardware_sha256", null);
                setHardwareName("");
              }}
            >
              Remove hardware definition
            </button>
          )}
        </div>
        <input
          hidden
          ref={inventoryInput}
          type="file"
          accept=".json,application/json"
          aria-label="JCI inventory JSON"
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            void loadInventory(file);
          }}
        />
        <input
          hidden
          ref={hardwareInput}
          type="file"
          accept=".xml,application/xml"
          aria-label="JCI preflight hardware XML"
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            void loadHardware(file);
          }}
        />
        {hardwareName && (
          <p>
            Attached: {hardwareName} <code>{draft.hardware_sha256}</code>
          </p>
        )}
        <details>
          <summary>Edit toolchain and package inventory JSON</summary>
          <p>
            Use the template to declare exact supported models, CAF application
            versions, and firmware versions with an evidence description. Empty
            lists or missing evidence remain unknown. Include required packages
            and their installation and license status.
          </p>
          <label>
            Inventory JSON text
            <textarea
              spellCheck={false}
              rows={14}
              value={draft.inventory_text}
              onChange={(event) => change("inventory_text", event.target.value)}
            />
          </label>
        </details>
      </fieldset>
      <div className="jci-preflight-actions">
        <button
          className="primary"
          disabled={disabled || busy}
          onClick={() => void run()}
        >
          Run target preflight
        </button>
        <button
          disabled={disabled || busy || !report || stale}
          onClick={() => void run(true)}
        >
          Export target readiness report
        </button>
      </div>
      {busy && <p role="status">Checking target evidence…</p>}
      {error && <p role="alert">{error}</p>}
      {stale && (
        <p role="status">
          Inputs changed. Run preflight to update the report before exporting.
        </p>
      )}
      {report && (
        <div aria-label="JCI preflight findings" aria-busy={busy}>
          <p
            className="jci-preflight-result"
            role="status"
            aria-label="Preflight result"
          >
            {stale ? "Previous report" : "Current report"}: {report.status} ·{" "}
            {report.counts.blocked || 0} blocked · {report.counts.unknown || 0}{" "}
            unknown · {report.counts.match || 0} comparisons match
          </p>
          <p>
            Native compilation, transfer integration, and controller acceptance
            remain unverified.
          </p>
          {report.selected_application && (
            <p>
              CAF model: <b>{report.selected_application.model || "Unknown"}</b>{" "}
              · Application version:
              <b>
                {" "}
                {report.selected_application.application_version || "Unknown"}
              </b>{" "}
              · Recorded firmware:
              <b> {report.selected_application.firmware || "Unknown"}</b>
            </p>
          )}
          <details>
            <summary>Review readiness checks ({report.checks.length})</summary>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Category / check</th>
                    <th>Result</th>
                    <th>Finding</th>
                  </tr>
                </thead>
                <tbody>
                  {report.checks.map((check: any) => (
                    <tr key={check.id}>
                      <td>
                        <small>{check.category}</small>
                        <b>{check.label}</b>
                      </td>
                      <td>
                        <span className={`jci-check-${check.status}`}>
                          {check.status}
                        </span>
                      </td>
                      <td>
                        {check.detail}
                        {check.evidence.length > 0 && (
                          <details>
                            <summary>Inspect evidence</summary>
                            <pre>{JSON.stringify(check.evidence, null, 2)}</pre>
                          </details>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
          <details>
            <summary>Source hashes and original CAF properties</summary>
            <p>
              CAF SHA-256: <code>{report.source.caf_sha256}</code>
            </p>
            <p>
              CAF XML SHA-256: <code>{report.source.caf_xml_sha256}</code>
            </p>
            <p>
              Submitted inventory SHA-256 (UTF-8 text):{" "}
              <code>{report.source.inventory_utf8_sha256}</code>
            </p>
            <pre>{JSON.stringify(report.application_candidates, null, 2)}</pre>
          </details>
        </div>
      )}
    </section>
  );
}
