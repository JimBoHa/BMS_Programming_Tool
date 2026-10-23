import { executionSourceValue } from "./programSource";
import { parseExecutionSourceJSON } from "./programSource";
import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Code2,
  Download,
  FlaskConical,
} from "lucide-react";
import {
  programApi,
  programJsonDocument,
  saveBlob,
  type JsonDocument,
} from "./api";
import { showValue, type Program } from "./types";
import "./temco-simulator.css";

type InputValue = { value: string | boolean; quality: string };
type Compilation = {
  source_st: string;
  generated_c: string;
  warnings: { count: number; categories: string[]; detail: string };
  program_sha256: string;
};
type Row = {
  clock: string;
  time: number;
  fault: boolean;
  outputs: Record<string, number | boolean>;
  reference_outputs: Record<string, number | boolean>;
  reference_fault: string | null;
  matches_reference: boolean;
};
type Verification = {
  matches_reference: boolean;
  rows: Row[];
  warnings: { count: number; categories: string[]; detail: string };
  program_sha256: string;
};

export function IECVerifier({ program }: { program: Program }) {
  const [status, setStatus] = useState<any>(null);
  const [inputs, setInputs] = useState<Record<string, InputValue>>({});
  const [scans, setScans] = useState("5");
  const [dt, setDt] = useState(String(program.scan_seconds));
  const [clock, setClock] = useState("");
  const [events, setEvents] = useState("[]");
  const [duration, setDuration] = useState("10");
  const [compiled, setCompiled] = useState<Compilation | null>(null);
  const [verificationDocument, setVerificationDocument] =
    useState<JsonDocument<Verification> | null>(null);
  const verification = verificationDocument?.data;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const mounted = useRef(false);
  const generation = useRef(0);
  const graphInputs = program.nodes.filter((node) => node.kind === "Input");
  const graphOutputs = program.nodes.filter((node) => node.kind === "Output");

  useEffect(() => {
    mounted.current = true;
    programApi("/iec/status")
      .then((next) => {
        if (mounted.current) setStatus(next);
      })
      .catch((e) => {
        if (mounted.current) setError(String(e));
      });
    return () => {
      mounted.current = false;
      generation.current++;
    };
  }, []);
  useEffect(() => {
    generation.current++;
    setInputs(
      Object.fromEntries(
        graphInputs.map((node) => [
          node.id,
          {
            value:
              node.value_type === "boolean"
                ? Boolean(node.params.default ?? false)
                : String(node.params.default ?? 0),
            quality: "good",
          },
        ]),
      ),
    );
    setDt(String(program.scan_seconds));
    setCompiled(null);
    setVerificationDocument(null);
    setError("");
  }, [program]);
  function invalidate() {
    generation.current++;
    setVerificationDocument(null);
    setError("");
  }
  function inputValues() {
    return Object.fromEntries(
      graphInputs.map((node) => {
        const item = inputs[node.id];
        const value =
          node.value_type === "boolean"
            ? item.value
            : executionSourceValue(String(item.value));
        if (node.value_type !== "boolean" && item.value === "")
          throw new Error(
            `${node.label || node.id}: enter a finite input value.`,
          );
        return [node.id, { value, quality: item.quality }];
      }),
    );
  }
  const allowed =
    status?.available &&
    !!graphOutputs.length &&
    !("native_sedona" in program.metadata);
  async function action(kind: "compile" | "verify" | "scenario") {
    if (busy || !allowed) return;
    const requestGeneration = generation.current;
    setBusy(true);
    setError("");
    setVerificationDocument(null);
    if (kind === "compile") setCompiled(null);
    try {
      const step = Number(dt);
      if (!Number.isFinite(step) || step <= 0 || step > 60)
        throw new Error("Native scan interval must be in (0,60] seconds.");
      const options = {
        program,
        dt: step,
        ...(clock ? { clock: clock + "Z" } : {}),
      };
      let result;
      if (kind === "compile")
        result = await programApi("/iec/compile", { program });
      else if (kind === "verify") {
        const count = Number(scans);
        if (!Number.isInteger(count) || count < 1 || count > 1000)
          throw new Error("Enter 1..1000 whole native scans.");
        result = await programJsonDocument<Verification>("/iec/verify", {
          ...options,
          scans: count,
          inputs: inputValues(),
        });
      } else {
        const length = Number(duration);
        if (
          !Number.isFinite(length) ||
          length <= 0 ||
          length > 86400 ||
          Math.ceil(length / step) > 1000
        )
          throw new Error(
            "Scenario needs a positive duration and at most 1000 native scans.",
          );
        result = await programJsonDocument<Verification>("/iec/scenario", {
          ...options,
          duration: length,
          events: parseExecutionSourceJSON(events),
        });
      }
      if (!mounted.current || requestGeneration !== generation.current) return;
      if (kind === "compile") setCompiled(result);
      else setVerificationDocument(result);
    } catch (e) {
      if (mounted.current && requestGeneration === generation.current)
        setError(String(e));
    } finally {
      if (mounted.current) setBusy(false);
    }
  }
  function save(value: string, extension: string, type = "text/plain") {
    saveBlob(new Blob([value], { type }), program.id + extension);
  }
  const faults = verification?.rows.filter((row) => row.fault).length || 0;

  return (
    <div className="workspace-page temco-simulator">
      <div className="page-intro">
        <div>
          <span className="eyebrow">
            STRUCTURED TEXT / INDEPENDENT COMPILER
          </span>
          <h1>IEC native verification</h1>
          <p>
            Compile exported Structured Text with MatIEC, execute the generated
            C, and compare each scan with the portable simulator.
          </p>
        </div>
        <span className="temco-availability">
          {status
            ? status.available
              ? "MatIEC compiler available"
              : "Compiler unavailable"
            : "Checking compiler…"}
        </span>
      </div>
      <p className="temco-scope">
        This verifier runs a persistent native process on this Mac with
        simulated I/O. It does not download a program to JCI, Honeywell, ALC or
        other physical controllers.
      </p>
      {error && (
        <div className="temco-error" role="alert">
          {error}
        </div>
      )}
      {status && !status.available && (
        <p className="temco-error" role="alert">
          {status.error}
        </p>
      )}
      {!graphOutputs.length && (
        <p className="temco-error">Open a program with at least one output.</p>
      )}
      {"native_sedona" in program.metadata && (
        <p className="temco-error">
          Native Sedona extensions cannot be omitted by this compiler profile.
        </p>
      )}
      <section className="temco-card" aria-label="IEC target profile">
        <h2>Native execution profile</h2>
        <div className="temco-profile-grid">
          <p>
            <strong>30 blocks and nested macros</strong>
            <span>
              Retained state, staged scan commits, timers, PI, schedules and
              input-quality validity flags.
            </span>
          </p>
          <p>
            <strong>IEC REAL / BOOL</strong>
            <span>
              Numbers use IEEE float32. Comparison tolerance is 0.0002 absolute
              / 0.002% relative. Small numeric differences are expected.
            </span>
          </p>
          <p>
            <strong>Bounded, isolated runs</strong>
            <span>
              At most 1000 scans. Each verification starts fresh, then retains
              native state across its scans. Calendars use explicit
              host-supplied active/valid flags.
            </span>
          </p>
        </div>
        {status && (
          <details>
            <summary>Compiler provenance and scope</summary>
            <p>
              MatIEC revision <code>{status.revision}</code>. {status.calendar}.
              This profile is not a certified PLC runtime.
            </p>
            {status.source_generator && (
              <p>
                Literal profile: <code>{status.source_generator.id}</code> ·
                rules <code>{status.source_generator.rules_sha256}</code>
              </p>
            )}
          </details>
        )}
      </section>
      <section className="temco-card" aria-label="IEC simulated inputs">
        <h2>Simulated inputs</h2>
        <div className="temco-table-wrap">
          <table className="temco-points">
            <thead>
              <tr>
                <th>Graph input</th>
                <th>Value</th>
                <th>Quality</th>
              </tr>
            </thead>
            <tbody>
              {graphInputs.map((node) => (
                <tr key={node.id}>
                  <td>
                    <strong>{node.label || node.id}</strong>
                    <small>
                      {node.value_type}
                      {node.unit ? " · " + node.unit : ""}
                    </small>
                  </td>
                  <td>
                    {node.value_type === "boolean" ? (
                      <select
                        aria-label={`IEC value ${node.id}`}
                        value={String(inputs[node.id]?.value ?? false)}
                        disabled={busy}
                        onChange={(e) => {
                          invalidate();
                          setInputs({
                            ...inputs,
                            [node.id]: {
                              ...inputs[node.id],
                              value: e.target.value === "true",
                            },
                          });
                        }}
                      >
                        <option value="false">FALSE</option>
                        <option value="true">TRUE</option>
                      </select>
                    ) : (
                      <input
                        aria-label={`IEC value ${node.id}`}
                        type="number"
                        step="any"
                        value={String(inputs[node.id]?.value ?? "")}
                        disabled={busy}
                        onChange={(e) => {
                          invalidate();
                          setInputs({
                            ...inputs,
                            [node.id]: {
                              ...inputs[node.id],
                              value: e.target.value,
                            },
                          });
                        }}
                      />
                    )}
                  </td>
                  <td>
                    <select
                      aria-label={`IEC quality ${node.id}`}
                      value={inputs[node.id]?.quality ?? "good"}
                      disabled={busy}
                      onChange={(e) => {
                        invalidate();
                        setInputs({
                          ...inputs,
                          [node.id]: {
                            ...inputs[node.id],
                            quality: e.target.value,
                          },
                        });
                      }}
                    >
                      <option value="good">Good</option>
                      <option value="open-circuit">Open circuit</option>
                      <option value="unreliable">Unreliable</option>
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="temco-actions">
          <label className="temco-clock-label">
            First scan clock (UTC)
            <input
              aria-label="IEC first scan clock UTC"
              type="datetime-local"
              step="1"
              value={clock}
              disabled={busy}
              onChange={(e) => {
                invalidate();
                setClock(e.target.value);
              }}
            />
          </label>
          <label>
            Scan interval (seconds)
            <input
              aria-label="IEC scan interval"
              type="number"
              min="0.001"
              max="60"
              step="any"
              value={dt}
              disabled={busy}
              onChange={(e) => {
                invalidate();
                setDt(e.target.value);
              }}
            />
          </label>
          <label>
            Scan count
            <input
              aria-label="IEC scan count"
              type="number"
              min="1"
              max="1000"
              step="1"
              value={scans}
              disabled={busy}
              onChange={(e) => {
                invalidate();
                setScans(e.target.value);
              }}
            />
          </label>
          <button disabled={busy || !allowed} onClick={() => action("compile")}>
            <Code2 size={16} />
            Compile native IEC
          </button>
          <button
            className="primary"
            disabled={busy || !allowed}
            onClick={() => action("verify")}
          >
            <FlaskConical size={16} />
            Run IEC verification
          </button>
          {busy && (
            <span role="status">Compiling and executing native code…</span>
          )}
        </div>
      </section>
      <section className="temco-card" aria-label="IEC timed scenario">
        <h2>Timed input scenario</h2>
        <p>
          Enter JSON events such as{" "}
          <code>
            {
              '[{"time":0,"inputs":{"temperature":72}},{"time":5,"inputs":{"temperature":{"value":0,"quality":"open-circuit"}}}]'
            }
          </code>
          . Use input IDs from this graph. Events apply before each scan;
          unchanged inputs retain their last supplied value. Unspecified inputs
          use graph defaults.
        </p>
        <textarea
          aria-label="IEC scenario events"
          className="temco-source"
          rows={5}
          value={events}
          disabled={busy}
          spellCheck={false}
          onChange={(e) => {
            invalidate();
            setEvents(e.target.value);
          }}
        />
        <div className="temco-actions">
          <label>
            Duration (seconds)
            <input
              aria-label="IEC scenario duration"
              type="number"
              min="0.001"
              max="86400"
              step="any"
              value={duration}
              disabled={busy}
              onChange={(e) => {
                invalidate();
                setDuration(e.target.value);
              }}
            />
          </label>
          <button
            disabled={busy || !allowed}
            onClick={() => action("scenario")}
          >
            <FlaskConical size={16} />
            Run native scenario
          </button>
        </div>
        <p className="temco-muted">
          Scenario clock is the start boundary; the first scan runs one interval
          later. The input table above applies to fixed-input verification only.
        </p>
      </section>
      {verification && verificationDocument && (
        <section
          className="temco-card temco-verification"
          aria-label="IEC verification results"
        >
          <div
            role="status"
            className={
              verification.matches_reference
                ? faults
                  ? "temco-result-held"
                  : "temco-result-match"
                : "temco-error"
            }
          >
            {verification.matches_reference && !faults ? (
              <CheckCircle2 size={18} />
            ) : (
              <AlertTriangle size={18} />
            )}
            {verification.matches_reference
              ? faults
                ? "Matched retained outputs after scan faults"
                : "Matched compiled IEC/reference outputs"
              : "Compiled IEC/reference difference"}
          </div>
          <p>
            {verification.rows.length} native scans · {faults} scans held by
            validity or arithmetic faults.
          </p>
          <button
            onClick={() =>
              saveBlob(
                verificationDocument.blob,
                program.id + ".iec-trace.json",
              )
            }
          >
            <Download size={15} />
            Download full IEC trace
          </button>
          <div className="temco-table-wrap">
            <table className="temco-results">
              <thead>
                <tr>
                  <th>Scan / UTC clock</th>
                  <th>Compiled IEC outputs</th>
                  <th>Portable outputs</th>
                  <th>Result / fault</th>
                </tr>
              </thead>
              <tbody>
                {verification.rows.slice(-50).map((row, index) => (
                  <tr key={index}>
                    <td>
                      {verification.rows.length -
                        Math.min(50, verification.rows.length) +
                        index +
                        1}
                      <small>{row.clock}</small>
                    </td>
                    <td>
                      {Object.entries(row.outputs)
                        .map(([id, value]) => `${id}: ${showValue(value)}`)
                        .join(", ")}
                    </td>
                    <td>
                      {Object.entries(row.reference_outputs)
                        .map(([id, value]) => `${id}: ${showValue(value)}`)
                        .join(", ")}
                    </td>
                    <td>
                      {row.matches_reference ? "Match" : "Difference"}
                      {row.reference_fault && (
                        <small>{row.reference_fault}</small>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {verification.rows.length > 50 && (
            <p>
              Showing the last 50 scans. Download the full trace for all scans.
            </p>
          )}
          {!!verification.warnings.count && (
            <details>
              <summary>Compiler diagnostics</summary>
              <pre>{verification.warnings.detail}</pre>
            </details>
          )}
        </section>
      )}
      {compiled && (
        <section className="temco-card" aria-label="Compiled IEC artifacts">
          <h2>Compiled artifacts</h2>
          <div className="button-row">
            <button onClick={() => save(compiled.source_st, ".st")}>
              <Download size={15} />
              Download Structured Text
            </button>
            <button onClick={() => save(compiled.generated_c, ".generated.c")}>
              <Download size={15} />
              Download generated C
            </button>
          </div>
          <p>
            Generated C uses the MatIEC runtime headers and host bindings.
            Compilation alone does not prove application behavior.
          </p>
          <textarea
            className="temco-source"
            aria-label="Compiled IEC Structured Text"
            value={compiled.source_st}
            readOnly
            rows={12}
            spellCheck={false}
          />
          {!!compiled.warnings.count && (
            <details>
              <summary>Compiler diagnostics</summary>
              <pre>{compiled.warnings.detail}</pre>
            </details>
          )}
        </section>
      )}
    </div>
  );
}
