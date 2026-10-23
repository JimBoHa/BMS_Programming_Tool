import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import {
  checkCatalog,
  checkReview,
  documentedModel,
  MODEL_TRANSPORT_SHA,
  type ModelCatalog,
  type ModelContext,
  type Qualification,
} from "./modelTransportContract";

export function ModelTransportPanel({
  context,
  onAdmit,
}: {
  context: ModelContext;
  onAdmit: (value: Qualification | null) => void;
}) {
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null),
    [model, setModel] = useState(""),
    [protocol, setProtocol] = useState("unknown"),
    [review, setReview] = useState<any>(null),
    [pending, setPending] = useState(false),
    [error, setError] = useState("");
  const mounted = useRef(false),
    epoch = useRef(0),
    admit = useRef(onAdmit);
  admit.current = onAdmit;
  const signature = JSON.stringify(context);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      epoch.current++;
      admit.current(null);
    };
  }, []);
  useEffect(() => {
    retire();
  }, [signature]);
  function retire() {
    epoch.current++;
    setReview(null);
    setPending(false);
    setError("");
    admit.current(null);
  }
  const current = (n: number) => mounted.current && n === epoch.current;
  async function load() {
    retire();
    setCatalog(null);
    const n = epoch.current;
    setPending(true);
    try {
      const value = await checkCatalog(
        await api("/bacnet/hardware/model-transport/profile"),
      );
      if (current(n)) setCatalog(value);
    } catch (e) {
      if (current(n)) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (current(n)) setPending(false);
    }
  }
  async function preview() {
    if (!catalog || pending) return;
    retire();
    const n = epoch.current;
    setPending(true);
    const qualification = {
      profile_sha256: MODEL_TRANSPORT_SHA,
      model,
      current_protocol: protocol,
    };
    try {
      if (!model || model.length > 80)
        throw new Error(
          "Enter a complete model declaration, or explicitly enter an unknown model.",
        );
      const value = checkReview(
        await api("/bacnet/hardware/model-transport/review", {
          qualification,
          target: context.target,
        }),
        catalog,
        qualification,
        context,
      );
      if (!current(n)) return;
      setReview(value);
      admit.current(value.dispatch_admitted ? qualification : null);
    } catch (e) {
      if (current(n)) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (current(n)) setPending(false);
    }
  }
  const selected = documentedModel(catalog, model);
  return (
    <section
      className="hardware-model-transport"
      aria-label="Optional model-qualified target"
    >
      <h4>Optional model-qualified target</h4>
      <p className="help-text">
        Declare the complete part and currently selected native protocol. This
        checks one existing target path; it does not identify hardware, open a
        connection or change a controller protocol.
      </p>
      <button onClick={load} disabled={pending}>
        Load or refresh model transport profile
      </button>
      {catalog && (
        <>
          <p className="help-text">
            Source: {catalog.profile.source.document}{" "}
            {catalog.profile.source.edition} · PDF{" "}
            {catalog.profile.source.pdf_pages.join(", ")} · profile{" "}
            {catalog.profile_sha256}
          </p>
          <div className="form-grid">
            <label>
              Declared complete controller model
              <input
                aria-label="Declared complete controller model"
                maxLength={80}
                list="hardware-reviewed-models"
                value={model}
                onChange={(e) => {
                  retire();
                  setModel(e.target.value);
                }}
              />
            </label>
            <datalist id="hardware-reviewed-models">
              {Object.keys(catalog.profile.models).map((name) => (
                <option key={name} value={name} />
              ))}
            </datalist>
            <label>
              Declared current controller protocol
              <select
                aria-label="Declared current controller protocol"
                value={protocol}
                onChange={(e) => {
                  retire();
                  setProtocol(e.target.value);
                }}
              >
                <option value="unknown">Unknown — unresolved</option>
                <option value="bacnet-ip">BACnet/IP</option>
                <option value="bacnet-mstp">BACnet MS/TP</option>
                <option value="bacnet-sc">
                  BACnet/SC — adapter unavailable
                </option>
                <option value="n2">N2 — adapter unavailable</option>
              </select>
            </label>
          </div>
          <p aria-label="Documented controller capability">
            Documented capability:{" "}
            {selected
              ? `${selected.native_protocols.join(", ")} · ports ${selected.ports.join(", ")}`
              : "Unknown exact part — unresolved"}
          </p>
          <p aria-label="Selected protocol adapter">
            Selected protocol adapter:{" "}
            {catalog.profile.adapters[protocol] === true
              ? "implemented"
              : "unavailable or unresolved"}
            . The router endpoint is separate from the downstream controller
            link.
          </p>
          <div className="button-row">
            <button onClick={preview} disabled={pending || !model}>
              Preview model-qualified target
            </button>
            <button onClick={retire}>Discard model target preview</button>
          </div>
          {pending && <p role="status">Reviewing local model metadata…</p>}
          {review && (
            <div aria-label="Model target review">
              <strong>
                {review.dispatch_admitted
                  ? "Model-qualified read admitted"
                  : "Model-qualified read not admitted"}
              </strong>
              <p>
                Declared native protocol: {review.declaration.current_protocol}{" "}
                · selected path: {review.path} · target {review.target.address}{" "}
                / {review.target.device}
                {review.target.router
                  ? ` via router ${review.target.router} · DNET ${review.target.dnet}`
                  : ""}
              </p>
              {review.findings.map((f: any) => (
                <p key={f.code}>
                  {f.code}: {f.message}
                </p>
              ))}
              <p className="help-text">
                Pure local preview: no BACnet request was sent. A qualified
                survey recomputes admission against its current target and open
                interface; this preview is not a reusable authorization token.
                Native compatibility remains unverified.
              </p>
            </div>
          )}
        </>
      )}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}

/** Historical job evidence is descriptive; it never enables another read. */
export function ModelTransportJobEvidence({ job }: { job: any }) {
  const a = job?.model_transport_admission,
    o = job?.model_transport_observation;
  if (!a && !o) return null;
  return (
    <section aria-label="Owned job model transport evidence">
      <h4>Owned job model transport evidence</h4>
      <p className="help-text">
        Historical job evidence only. The saved hardware survey profile and seal
        are separate; self-reported text does not authenticate hardware.
      </p>
      {a && (
        <>
          <p>
            Operator declaration: {String(a.declaration?.model ?? "unknown")} ·
            current protocol{" "}
            {String(a.declaration?.current_protocol ?? "unknown")}
          </p>
          <p>
            Documented capability:{" "}
            {Array.isArray(a.documented_protocols)
              ? a.documented_protocols.join(", ")
              : "unresolved"}{" "}
            · adapter{" "}
            {a.adapter_implemented === true
              ? "implemented"
              : "unavailable or unresolved"}{" "}
            · path {String(a.path ?? "unknown")}
          </p>
        </>
      )}
      {o && (
        <>
          <p>
            Observed model text:{" "}
            {typeof o.raw_identity?.model === "string"
              ? o.raw_identity.model
              : "unavailable"}{" "}
            · interpretation {String(o.model_text_status ?? "unresolved")}
          </p>
          <pre aria-label="Raw controller identity observation">
            {JSON.stringify(o.raw_identity, null, 2)}
          </pre>
          <p>
            Target match: {String(o.target_matches_admission)} · interface
            match: {String(o.config_matches_admission)} · native compatibility
            unverified
          </p>
        </>
      )}
    </section>
  );
}
