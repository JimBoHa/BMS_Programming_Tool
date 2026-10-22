import { executionNumber } from "./programSource";
import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Code2,
  Download,
  FlaskConical,
} from "lucide-react";
import { programApi, saveBlob } from "./api";
import { showValue, type Program } from "./types";
import { TemcoTransfer } from "./TemcoTransfer";
import "./temco-simulator.css";

type InputValue = { value: string | boolean; quality: string };
type Compilation = {
  source: string;
  bytecode_base64: string;
  bindings: Record<string, string>;
  calendar_bindings: Record<string, { active: string; valid: string }>;
  manifest: { source_commit: string; source_url: string; license: string };
};
type Verification = {
  outputs: Record<string, number | boolean>;
  reference_outputs: Record<string, number | boolean>;
  reference_fault: string | null;
  differences: {
    node: string;
    native: number | boolean;
    reference: number | boolean;
  }[];
  matches_reference: boolean;
  bytecode_bytes: number;
  scans: number;
  history: {
    scan: number;
    clock: string;
    outputs: Record<string, number | boolean>;
    reference_outputs: Record<string, number | boolean>;
    reference_fault: string | null;
  }[];
  calendar_scope: string | null;
  calendar_bindings: Record<string, { active: string; valid: string }>;
};

export function TemcoSimulator({ program }: { program: Program }) {
  const [status, setStatus] = useState<any>(null);
  const [bindings, setBindings] = useState<Record<string, string>>({});
  const [inputs, setInputs] = useState<Record<string, InputValue>>({});
  const [scans, setScans] = useState("1");
  const [clock, setClock] = useState("");
  const [compiled, setCompiled] = useState<Compilation | null>(null);
  const [verification, setVerification] = useState<Verification | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const generation = useRef(0);
  const mounted = useRef(false);
  const graphInputs = program.nodes.filter((node) => node.kind === "Input");
  const graphOutputs = program.nodes.filter((node) => node.kind === "Output");

  useEffect(() => {
    mounted.current = true;
    programApi("/temco/status")
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
    setBindings(
      Object.fromEntries([
        ...graphInputs.map((node, index) => [node.id, "IN" + (index + 1)]),
        ...graphOutputs.map((node, index) => [node.id, "OUT" + (index + 1)]),
      ]),
    );
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
    setCompiled(null);
    setVerification(null);
    setError("");
  }, [program]);

  const unsupported = Array.from(
    new Set(
      program.nodes
        .filter(
          (node) =>
            node.kind !== "Macro" &&
            status?.capabilities &&
            !status.capabilities.supported_blocks.includes(node.kind),
        )
        .map((node) => node.kind),
    ),
  );
  const nativeExtension = "native_sedona" in program.metadata;
  const allowed =
    status?.available &&
    !unsupported.length &&
    !nativeExtension &&
    !!program.nodes.length &&
    !!graphOutputs.length;

  function invalidate(clearCompile: boolean) {
    generation.current++;
    setVerification(null);
    if (clearCompile) setCompiled(null);
    setError("");
  }
  function editInput(identifier: string, change: Partial<InputValue>) {
    invalidate(false);
    setInputs((current) => ({
      ...current,
      [identifier]: { ...current[identifier], ...change },
    }));
  }
  function values() {
    return Object.fromEntries(
      graphInputs.map((node) => {
        const item = inputs[node.id];
        const value =
          node.value_type === "boolean"
            ? item.value
            : executionNumber(String(item.value));
        if (
          node.value_type !== "boolean" &&
          (item.value === "" || !Number.isFinite(value))
        )
          throw new Error(
            `${node.label || node.id}: enter a finite input value.`,
          );
        return [node.id, { value, quality: item.quality }];
      }),
    );
  }
  async function action(kind: "compile" | "verify") {
    if (busy || !allowed) return;
    const requestGeneration = generation.current;
    setBusy(true);
    setError("");
    setVerification(null);
    if (kind === "compile") setCompiled(null);
    try {
      let next;
      if (kind === "compile") {
        next = await programApi("/temco/compile", { program, bindings });
      } else {
        const count = Number(scans);
        if (!Number.isInteger(count) || count < 1 || count > 1000)
          throw new Error("Native verification requires 1..1000 whole scans.");
        next = await programApi("/temco/verify", {
          program,
          bindings,
          inputs: values(),
          scans: count,
          ...(clock ? { clock: clock + "Z" } : {}),
        });
      }
      if (!mounted.current || requestGeneration !== generation.current) return;
      if (kind === "compile") setCompiled(next);
      else setVerification(next);
    } catch (e) {
      if (mounted.current && requestGeneration === generation.current)
        setError(String(e));
    } finally {
      if (mounted.current) setBusy(false);
    }
  }
  function downloadSource() {
    if (compiled)
      saveBlob(
        new Blob([compiled.source], { type: "text/plain;charset=us-ascii" }),
        program.id + ".bas",
      );
  }
  function downloadBytecode() {
    if (compiled) {
      const bytes = Uint8Array.from(atob(compiled.bytecode_base64), (c) =>
        c.charCodeAt(0),
      );
      saveBlob(
        new Blob([bytes], { type: "application/octet-stream" }),
        program.id + ".temco.bin",
      );
    }
  }

  return (
    <div className="workspace-page temco-simulator">
      <div className="page-intro">
        <div>
          <span className="eyebrow">
            MANUFACTURER COMPILER / LOCAL INTERPRETER
          </span>
          <h1>Temco Control Basic</h1>
          <p>
            Compile this graph into numbered BASIC and real Temco bytecode.
            Compare the manufacturer interpreter with the portable simulator.
          </p>
        </div>
        <span className="temco-availability">
          {status
            ? status.available
              ? "Native compiler available"
              : "Native compiler unavailable"
            : "Checking compiler…"}
        </span>
      </div>
      <p className="temco-scope">
        Local simulation uses memory-only points. The separate controller
        transfer panel below requires an explicit BACnet target and reviewed
        stop, replacement and readback plan.
      </p>
      {error && (
        <div className="temco-error" role="alert">
          {error}
        </div>
      )}
      {status && !status.available && (
        <p className="temco-error" role="alert">
          {status.reason}
        </p>
      )}
      {unsupported.length > 0 && (
        <p className="temco-error" role="alert">
          This target profile cannot compile: {unsupported.join(", ")}. No
          blocks will be omitted.
        </p>
      )}
      {nativeExtension && (
        <p className="temco-error" role="alert">
          This project has native Sedona extensions. Control Basic export would
          omit native logic and is unavailable.
        </p>
      )}
      {!program.nodes.length || !graphOutputs.length ? (
        <p className="temco-error" role="alert">
          Open a graph with at least one output to compile and verify it.
        </p>
      ) : null}
      <section className="temco-card" aria-label="Temco target profile">
        <h2>Target profile</h2>
        <div className="temco-profile-grid">
          <p>
            <strong>27 block types with retained state</strong>
            <span>
              Includes PI, delay, hysteresis, timers, alarms and rate limits.
              Private native locals retain state across scans. Calendars require
              host-supplied flags; nested macros are expanded and checked.
            </span>
          </p>
          <p>
            <strong>0.001 numeric resolution</strong>
            <span>
              Signed 32-bit fixed point. Literals require increments of 0.001
              within ±2,000,000; arithmetic overflow is reported by comparison.
            </span>
          </p>
          <p>
            <strong>Under 2,000 byte programs</strong>
            <span>
              The actual compiler enforces program memory. Source has at most
              180 numbered lines. A failed division holds both state and
              outputs.
            </span>
          </p>
        </div>
        <details>
          <summary>Scan timing, calendars and input quality</summary>
          <p>
            Each native invocation advances state by the program scan interval (
            {program.scan_seconds} seconds). A physical host must provide that
            cadence. Schedules use explicit active/valid VAR pairs evaluated by
            the host; an unbound calendar holds state and outputs. Native source
            has no physical sensor quality channel in this profile. Commission
            sensor range and fault handling for the actual installation. This
            local verifier accepts good input quality only. Each verification
            starts a fresh native instance and then retains state for the
            requested scans.
          </p>
        </details>
      </section>
      <section
        className="temco-card"
        aria-label="Temco points and simulated inputs"
      >
        <h2>Point bindings and inputs</h2>
        <p>
          Bind inputs to IN1–64 or VAR1–256; outputs to OUT1–64 or VAR1–256.
          Every interface needs a distinct point.
        </p>
        <div className="temco-table-wrap">
          <table className="temco-points">
            <thead>
              <tr>
                <th>Graph interface</th>
                <th>Local Temco point</th>
                <th>Simulated value</th>
                <th>Quality</th>
              </tr>
            </thead>
            <tbody>
              {[...graphInputs, ...graphOutputs].map((node) => (
                <tr key={node.id}>
                  <td>
                    <strong>{node.label || node.id}</strong>
                    <small>
                      {node.kind} · {node.value_type}
                      {node.unit ? " · " + node.unit : ""}
                    </small>
                  </td>
                  <td>
                    <input
                      aria-label={`Temco point for ${node.id}`}
                      value={bindings[node.id] || ""}
                      disabled={busy}
                      spellCheck={false}
                      onChange={(e) => {
                        invalidate(true);
                        setBindings({ ...bindings, [node.id]: e.target.value });
                      }}
                    />
                  </td>
                  <td>
                    {node.kind === "Input" ? (
                      node.value_type === "boolean" ? (
                        <select
                          aria-label={`Native value ${node.id}`}
                          value={String(inputs[node.id]?.value ?? false)}
                          disabled={busy}
                          onChange={(e) =>
                            editInput(node.id, {
                              value: e.target.value === "true",
                            })
                          }
                        >
                          <option value="false">FALSE</option>
                          <option value="true">TRUE</option>
                        </select>
                      ) : (
                        <input
                          aria-label={`Native value ${node.id}`}
                          type="number"
                          step="0.001"
                          value={String(inputs[node.id]?.value ?? "")}
                          disabled={busy}
                          onChange={(e) =>
                            editInput(node.id, { value: e.target.value })
                          }
                        />
                      )
                    ) : (
                      <span className="temco-muted">Read after execution</span>
                    )}
                  </td>
                  <td>
                    {node.kind === "Input" ? (
                      <select
                        aria-label={`Native quality ${node.id}`}
                        value={inputs[node.id]?.quality ?? "good"}
                        disabled={busy}
                        onChange={(e) =>
                          editInput(node.id, { quality: e.target.value })
                        }
                      >
                        <option value="good">Good</option>
                        <option value="open-circuit">Open circuit</option>
                        <option value="unreliable">Unreliable</option>
                      </select>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="temco-actions">
          <label className="temco-clock-label">
            First native scan clock (UTC)
            <input
              aria-label="First native scan clock UTC"
              type="datetime-local"
              step="1"
              value={clock}
              disabled={busy}
              onChange={(e) => {
                invalidate(false);
                setClock(e.target.value);
              }}
            />
          </label>
          <label>
            Native scan count
            <input
              aria-label="Native scan count"
              type="number"
              min="1"
              max="1000"
              step="1"
              value={scans}
              disabled={busy}
              onChange={(e) => {
                invalidate(false);
                setScans(e.target.value);
              }}
            />
          </label>
          <button disabled={busy || !allowed} onClick={() => action("compile")}>
            <Code2 size={16} /> Compile Control Basic
          </button>
          <button
            className="primary"
            disabled={busy || !allowed}
            onClick={() => action("verify")}
          >
            <FlaskConical size={16} /> Run native verification
          </button>
          {busy && <span role="status">Running manufacturer toolchain…</span>}
        </div>
      </section>
      {verification && (
        <section
          className="temco-card temco-verification"
          aria-label="Native verification results"
        >
          <div
            role="status"
            className={
              verification.reference_fault
                ? "temco-result-held"
                : verification.matches_reference
                  ? "temco-result-match"
                  : "temco-error"
            }
          >
            {verification.matches_reference && !verification.reference_fault ? (
              <CheckCircle2 size={18} />
            ) : (
              <AlertTriangle size={18} />
            )}
            {verification.reference_fault
              ? "Retained outputs after a scan fault"
              : verification.matches_reference
                ? "Matched native/reference outputs"
                : "Native/reference difference"}
          </div>
          <p>
            {verification.bytecode_bytes} native bytes · {verification.scans}{" "}
            scans · numeric comparison tolerance 0.01 absolute / 0.001%
            relative.
          </p>
          {verification.reference_fault && (
            <p className="temco-result-held">{verification.reference_fault}</p>
          )}
          {verification.calendar_scope && (
            <p className="temco-scope">
              {verification.calendar_scope}.{" "}
              {Object.entries(verification.calendar_bindings)
                .map(
                  ([id, ports]) =>
                    `${id}: ${ports.active} active / ${ports.valid} valid`,
                )
                .join("; ")}
            </p>
          )}
          <table className="temco-results">
            <thead>
              <tr>
                <th>Output</th>
                <th>Native interpreter</th>
                <th>Portable simulator</th>
                <th>Across scans</th>
              </tr>
            </thead>
            <tbody>
              {graphOutputs.map((node) => (
                <tr key={node.id}>
                  <td>{node.label || node.id}</td>
                  <td>{showValue(verification.outputs[node.id])}</td>
                  <td>{showValue(verification.reference_outputs[node.id])}</td>
                  <td>
                    {verification.differences.some((d) => d.node === node.id)
                      ? "Difference"
                      : "Match"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <details className="temco-trace">
            <summary>Inspect native scan trace</summary>
            <p>
              Showing the last {Math.min(50, verification.history.length)} of{" "}
              {verification.history.length} native scans.
            </p>
            <div className="temco-table-wrap">
              <table className="temco-results">
                <thead>
                  <tr>
                    <th>Scan / UTC clock</th>
                    <th>Native outputs</th>
                    <th>Portable outputs</th>
                    <th>Scan fault</th>
                  </tr>
                </thead>
                <tbody>
                  {verification.history.slice(-50).map((row) => (
                    <tr key={row.scan}>
                      <td>
                        {row.scan}
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
                      <td>{row.reference_fault || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </section>
      )}
      <TemcoTransfer source={compiled?.source ?? null} />
      {compiled && (
        <section
          className="temco-card"
          aria-label="Compiled native Control Basic"
        >
          <h2>Compiled source and bytecode</h2>
          <div className="button-row">
            <button onClick={downloadSource}>
              <Download size={15} /> Download BASIC source
            </button>
            <button onClick={downloadBytecode}>
              <Download size={15} /> Download Temco bytecode
            </button>
          </div>
          <textarea
            className="temco-source"
            aria-label="Compiled Control Basic source"
            value={compiled.source
              .split(/\r?\n/)
              .filter((line) => !line.includes(" REM BMSIR2 "))
              .join("\n")}
            readOnly
            rows={14}
            spellCheck={false}
          />
          <p className="temco-muted">
            Executable source preview omits authoring annotation comments. The
            .bas download includes validated annotations for lossless stateful
            graph reimport.
          </p>
          <details>
            <summary>Compiler provenance</summary>
            <p>
              <a
                href={
                  compiled.manifest.source_url.replace(/\.git$/, "") +
                  "/tree/" +
                  compiled.manifest.source_commit
                }
                target="_blank"
                rel="noreferrer"
              >
                Temco manufacturer source
              </a>{" "}
              · {compiled.manifest.license} · revision{" "}
              <code>{compiled.manifest.source_commit}</code>. The host adapts
              Windows helpers and 32-bit integer layout; field I/O is simulated.
            </p>
          </details>
        </section>
      )}
    </div>
  );
}
