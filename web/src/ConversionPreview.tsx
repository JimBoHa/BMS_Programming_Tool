import { sourceStringify } from "./programSource";
import { useRef, useState } from "react";
import { programApi, saveBlob } from "./api";
import type { Program } from "./types";
import "./conversion-preview.css";

type Note = {
  code: string;
  severity: string;
  message: string;
  nodes?: string[];
};
type Target = {
  format: string;
  name: string;
  status: string;
  error: string | null;
  artifact: { bytes: number; sha256: string } | null;
  editable_round_trip: { exact: boolean; changed_fields: string[] } | null;
  native_compilation: string;
  controller_acceptance: string;
  notes: Note[];
  source_generator?: { id: string; rules_sha256: string };
  symbol_generator?: { id: string; rules_sha256: string };
};
type Report = {
  profile: string;
  program: { sha256: string };
  targets: Target[];
  scope: string;
  diagnostics: { level: string; message: string; node?: string }[];
};

export function ConversionPreview({ program }: { program: Program }) {
  const signature = sourceStringify(program);
  const current = useRef(signature);
  current.current = signature;
  const request = useRef(0);
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState<{
    signature: string;
    report: Report;
  } | null>(null);
  const report = saved?.signature === signature ? saved.report : null;

  async function check() {
    const mine = ++request.current;
    const source = signature;
    setOpen(true);
    setPending(true);
    setError("");
    setSaved(null);
    try {
      const result: Report = await programApi("/conversion/preview", {
        program,
      });
      if (mine === request.current && current.current === source)
        setSaved({ signature: source, report: result });
    } catch (e) {
      if (mine === request.current && current.current === source)
        setError(String(e));
    } finally {
      if (mine === request.current) setPending(false);
    }
  }

  return (
    <section className="conversion-preview" aria-label="Conversion review">
      <div className="button-row">
        <button onClick={check} disabled={pending}>
          {pending ? "Checking source formats…" : "Review conversion formats"}
        </button>
        {open && (
          <button onClick={() => setOpen(false)}>Hide conversion review</button>
        )}
        {open && report && (
          <button
            onClick={() =>
              saveBlob(
                new Blob([JSON.stringify(report, null, 2)], {
                  type: "application/json",
                }),
                program.id + "-conversion-review.json",
              )
            }
          >
            Export conversion report
          </button>
        )}
      </div>
      {open && (
        <div>
          <p>
            Compare source representability, editable round trips and execution
            differences before exporting. Native compilation and controller
            acceptance require separate verification.
          </p>
          {error && <p role="alert">{error}</p>}
          {!report && !pending && !error && (
            <p>Program changed. Review the current source again.</p>
          )}
          {report && (
            <>
              <p>
                Source SHA-256: <code>{report.program.sha256}</code>
              </p>
              {report.diagnostics.length > 0 && (
                <ul>
                  {report.diagnostics.map((d, i) => (
                    <li key={i}>
                      {d.level}: {d.message}
                      {d.node ? ` (${d.node})` : ""}
                    </li>
                  ))}
                </ul>
              )}
              <div className="conversion-table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Target</th>
                      <th>Source assessment</th>
                      <th>Editable round trip</th>
                      <th>Review</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.targets.map((target) => (
                      <tr key={target.format} data-format={target.format}>
                        <td>{target.name}</td>
                        <td>
                          {target.status}
                          {target.source_generator && (
                            <div>
                              Literal profile:{" "}
                              <code>{target.source_generator.id}</code>
                            </div>
                          )}
                          {target.symbol_generator && (
                            <div>
                              Symbol profile:{" "}
                              <code>{target.symbol_generator.id}</code>
                            </div>
                          )}
                          {target.artifact && (
                            <div>
                              {target.artifact.bytes.toLocaleString()} bytes
                            </div>
                          )}
                        </td>
                        <td>
                          {target.editable_round_trip
                            ? target.editable_round_trip.exact
                              ? "Exact project digest"
                              : "Authoring fields changed: " +
                                target.editable_round_trip.changed_fields.join(
                                  ", ",
                                )
                            : "Not checked"}
                        </td>
                        <td>
                          {target.error && <p>{target.error}</p>}
                          <details>
                            <summary>Differences and requirements</summary>
                            <p>
                              Native compilation: {target.native_compilation};
                              controller acceptance:{" "}
                              {target.controller_acceptance}.
                            </p>
                            <ul>
                              {target.source_generator && (
                                <li>
                                  Literal rules SHA-256:{" "}
                                  <code>
                                    {target.source_generator.rules_sha256}
                                  </code>
                                </li>
                              )}
                              {target.symbol_generator && (
                                <li>
                                  Symbol rules SHA-256:{" "}
                                  <code>
                                    {target.symbol_generator.rules_sha256}
                                  </code>
                                </li>
                              )}
                              {target.notes.map((note) => (
                                <li key={note.code}>
                                  <strong>{note.severity}:</strong>{" "}
                                  {note.message}
                                  {note.nodes?.length
                                    ? ` Nodes: ${note.nodes.join(", ")}.`
                                    : ""}
                                </li>
                              ))}
                            </ul>
                            {target.artifact && (
                              <p>
                                Preview artifact SHA-256:{" "}
                                <code>{target.artifact.sha256}</code>. A later
                                export is generated separately; archive
                                container timestamps can differ.
                              </p>
                            )}
                          </details>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p>{report.scope}</p>
            </>
          )}
        </div>
      )}
    </section>
  );
}
