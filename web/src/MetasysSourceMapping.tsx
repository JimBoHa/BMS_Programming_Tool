import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import {
  controllerKey,
  type ControllerContext,
  type ControllerTarget,
} from "./workflow";

type Inspection = {
  target: ControllerTarget;
  object: string;
  identity_verified: boolean;
  mapping_observed: boolean;
  complete: boolean;
  read_only: boolean;
  finished_at: string;
  errors: string[];
  write_support: { available: boolean; reason: string };
  limitations: string[];
  mapping: {
    local_object: string;
    local_name: string;
    item_reference: string;
    source_instance: number;
    remote_object_name: string | null;
  } | null;
};

export function MetasysSourceMapping({
  controller,
  object,
  connected,
  busy: externalBusy,
}: {
  controller: ControllerContext;
  object: string;
  connected: boolean;
  busy: boolean;
}) {
  const [report, setReport] = useState<Inspection | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const epoch = useRef(0);
  const source = controllerKey(controller) + controller.interfaceKey + object;
  useEffect(() => {
    epoch.current++;
    setReport(null);
    setError("");
    setBusy(false);
    return () => {
      epoch.current++;
    };
  }, [source, connected]);

  async function inspect() {
    const current = ++epoch.current;
    setBusy(true);
    setError("");
    setReport(null);
    try {
      const result: Inspection = await api(
        "/bacnet/controller/metasys-source-mapping/inspect",
        {
          address: controller.address,
          device: controller.device,
          router: controller.router || null,
          dnet: controller.dnet ?? null,
          object_id: object,
        },
      );
      if (current !== epoch.current) return;
      if (
        controllerKey(result.target) !== controllerKey(controller) ||
        result.object !== object ||
        result.read_only !== true ||
        result.write_support?.available !== false
      )
        throw new Error(
          "Source inspection returned an unexpected target or capability.",
        );
      setReport(result);
      if (
        !result.complete ||
        !result.identity_verified ||
        !result.mapping_observed
      )
        setError(
          result.errors?.join(" ") || "The source mapping was not verified.",
        );
    } catch (failure) {
      if (current === epoch.current) setError(String(failure));
    } finally {
      if (current === epoch.current) setBusy(false);
    }
  }

  return (
    <details aria-label="Metasys source mapping">
      <summary>Metasys source mapping · read only</summary>
      <p className="help-text">
        For JCI mapped analog inputs and binary values. The source instance is
        separate from this point’s local object identifier. Live remapping is
        not implemented.
      </p>
      <button
        disabled={!connected || busy || externalBusy}
        onClick={() => void inspect()}
      >
        {busy ? "Reading source mapping…" : "Read Metasys source mapping"}
      </button>
      {error && <p role="alert">{error}</p>}
      {report && (
        <>
          <p className="help-text">
            Observation completed at {report.finished_at}.
          </p>
          {report.complete &&
            report.identity_verified &&
            report.mapping_observed &&
            report.mapping && (
              <dl className="workflow-identity-grid">
                {[
                  ["Local mapped object", report.mapping.local_object],
                  ["Local point name", report.mapping.local_name],
                  ["Metasys item reference", report.mapping.item_reference],
                  ["Remote source instance", report.mapping.source_instance],
                  [
                    "Remote object name",
                    report.mapping.remote_object_name ?? "Not available",
                  ],
                ].map(([label, value]) => (
                  <div key={label}>
                    <dt>{label}</dt>
                    <dd>{value}</dd>
                  </div>
                ))}
              </dl>
            )}
          <p>{report.write_support.reason}</p>
          <details>
            <summary>Evidence and scope</summary>
            <ul>
              {report.limitations.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
            <pre>{JSON.stringify(report, null, 2)}</pre>
          </details>
        </>
      )}
    </details>
  );
}
