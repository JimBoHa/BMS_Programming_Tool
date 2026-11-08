import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { api, apiJsonDocument, saveBlob, type JsonDocument } from "./api";
import { sha256Blob } from "./activityContracts";
import {
  engineeringInventory,
  engineeringReport,
} from "./jciEngineeringContract";
import "./jci-engineering.css";

export function JciEngineeringDesk({ active }: { active: boolean }) {
  const [catalog, setCatalog] = useState<any>(null);
  const [catalogError, setCatalogError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [pane, setPane] = useState("source");
  const [file, setFile] = useState<File | null>(null);
  const [report, setReport] = useState<JsonDocument | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");
  const [product, setProduct] = useState("All");
  const fileRef = useRef<File | null>(null),
    input = useRef<HTMLInputElement>(null);
  const epoch = useRef(0),
    alive = useRef(false),
    activeRef = useRef(active),
    paneRef = useRef(pane);
  activeRef.current = active;
  useLayoutEffect(() => {
    alive.current = true;
    epoch.current++;
    setBusy(false);
    return () => {
      alive.current = false;
      epoch.current++;
    };
  }, [active]);
  useEffect(() => {
    if (!active) return;
    let current = true;
    setCatalogError("");
    api("/jci/engineering/inventory")
      .then((value) => {
        if (!current) return;
        if (!engineeringInventory(value))
          throw new Error(
            "The SCT/JCT inventory profile is unsupported or malformed.",
          );
        setCatalog(value);
      })
      .catch((e) => {
        if (current) {
          setCatalog(null);
          setCatalogError(e.message);
        }
      });
    return () => {
      current = false;
    };
  }, [active, refresh]);
  function choose(value: File | null) {
    epoch.current++;
    fileRef.current = value;
    setFile(value);
    setReport(null);
    setError("");
    setBusy(false);
  }
  function show(value: string) {
    epoch.current++;
    paneRef.current = value;
    setPane(value);
    setBusy(false);
    setError("");
  }
  async function inspect() {
    const selected = fileRef.current;
    if (!selected || !activeRef.current || paneRef.current !== "source") return;
    const own = ++epoch.current;
    const current = () =>
      alive.current &&
      activeRef.current &&
      paneRef.current === "source" &&
      epoch.current === own &&
      fileRef.current === selected;
    setBusy(true);
    setError("");
    setReport(null);
    try {
      if (!selected.size || selected.size > 8 * 1024 * 1024)
        throw new Error(
          "Choose a nonempty source within the 8 MiB inspection profile.",
        );
      const digest = await sha256Blob(selected);
      if (!current()) return;
      const form = new FormData();
      form.append("file", selected);
      const result = await apiJsonDocument(
        "/jci/engineering/inspect",
        form,
        true,
      );
      if (!current()) return;
      if (!(await engineeringReport(result, selected, digest)))
        throw new Error(
          "Inspection evidence does not match this file or the supported read-only profile. Inspect the source again.",
        );
      if (current()) setReport(result);
    } catch (e: any) {
      if (current()) setError(e.message);
    } finally {
      if (current()) setBusy(false);
    }
  }
  const result = report?.data;
  const shown = (catalog?.packages || []).filter(
    (r: any) =>
      (product === "All" || r.product === product) &&
      JSON.stringify(r).toLowerCase().includes(query.toLowerCase()),
  );
  return (
    <section
      className="jci-engineering-desk"
      aria-label="SCT/JCT engineering sources"
    >
      <p>
        Inspect a selected file and its supported reader scope. Archive, field
        application, portable graph and graphics formats have separate evidence.
      </p>
      <div
        className="jci-engineering-tabs"
        role="group"
        aria-label="Engineering view"
      >
        <button aria-pressed={pane === "source"} onClick={() => show("source")}>
          Source inspection
        </button>
        <button
          aria-pressed={pane === "inventory"}
          onClick={() => show("inventory")}
        >
          Parity inventory
        </button>
      </div>
      {pane === "source" ? (
        <>
          <label>
            Engineering source file
            <input
              ref={input}
              type="file"
              onChange={(e) => choose(e.target.files?.[0] || null)}
            />
          </label>
          {file && (
            <p className="jci-engineering-file">
              Selected local file: <strong>{file.name}</strong> ·{" "}
              {file.size.toLocaleString()} bytes
            </p>
          )}
          <div className="jci-engineering-actions">
            <button
              className="primary"
              disabled={!file || busy || !active}
              onClick={inspect}
            >
              {busy ? "Inspecting source…" : "Inspect source"}
            </button>
            <button
              disabled={!file && !report && !busy}
              onClick={() => {
                choose(null);
                if (input.current) input.current.value = "";
              }}
            >
              Clear source
            </button>
          </div>
          {error && (
            <p className="inline-error" role="alert">
              {error}
            </p>
          )}
          {result && (
            <div
              aria-label="Engineering inspection result"
              className="jci-engineering-result"
            >
              <h3>
                {result.detected.state === "readable"
                  ? "Readable projection"
                  : result.detected.state === "partial"
                    ? "Partial projection"
                    : "Unrecognized content"}
              </h3>
              <p>
                <strong>{result.source.name}</strong> ·{" "}
                {result.detected.reader_profile || "No qualified decoder"}
              </p>
              <p>
                Selected-file evidence · Read-only · Native supervisory and
                graphics decoding remain unqualified.
              </p>
              {result.summary.objects !== undefined && (
                <p>
                  {result.summary.objects.toLocaleString()} represented objects
                  · {result.summary.class_count} class groups
                </p>
              )}
              {result.summary.nodes !== undefined && (
                <p>
                  {result.summary.nodes} graph nodes · {result.summary.edges}{" "}
                  edges · {result.summary.name}
                </p>
              )}
              <div className="jci-engineering-table">
                <table>
                  <thead>
                    <tr>
                      <th>Operation</th>
                      <th>Availability</th>
                      <th>Evidence / remaining work</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.operations.map((row: any) => (
                      <tr key={row.id}>
                        <td>{row.id}</td>
                        <td>{row.status}</td>
                        <td>{row.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <ul>
                {result.diagnostics.map((s: string, i: number) => (
                  <li key={i}>{s}</li>
                ))}
              </ul>
              <button
                onClick={() => {
                  if (
                    report &&
                    fileRef.current === file &&
                    activeRef.current &&
                    paneRef.current === "source"
                  )
                    saveBlob(
                      report.blob,
                      "engineering-inspection-" +
                        result.source.sha256.slice(0, 12) +
                        ".json",
                    );
                }}
              >
                Save exact inspection report
              </button>
              <details>
                <summary>Source fingerprint and coverage</summary>
                <pre>
                  {JSON.stringify(
                    {
                      source: result.source,
                      detected: result.detected,
                      summary: result.summary,
                      coverage: result.coverage,
                      report_sha256: result.report_sha256,
                    },
                    null,
                    2,
                  )}
                </pre>
              </details>
            </div>
          )}
        </>
      ) : (
        <>
          <p>
            Manual-operation mapping is partial. The 48 parent packages retain
            their remaining native-format, deployment and acceptance work.
          </p>
          {catalogError ? (
            <p className="inline-error" role="alert">
              {catalogError}
            </p>
          ) : !catalog ? (
            <p>Loading operation inventory…</p>
          ) : (
            <>
              <label>
                SCT/JCT feature search
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Archive, graphics, simulation…"
                />
              </label>
              <label>
                Engineering product
                <select
                  value={product}
                  onChange={(e) => setProduct(e.target.value)}
                >
                  {["All", "Shared", "SCT", "JCT"].map((s) => (
                    <option key={s}>{s}</option>
                  ))}
                </select>
              </label>
              <p>
                {shown.length} of {catalog.packages.length} planned or partial
                packages
              </p>
              <div className="jci-engineering-table">
                <table aria-label="SCT/JCT parity packages">
                  <thead>
                    <tr>
                      <th>Package</th>
                      <th>Priority / group</th>
                      <th>Status</th>
                      <th>Acceptance and dependencies</th>
                    </tr>
                  </thead>
                  <tbody>
                    {shown.map((row: any) => (
                      <tr key={row.id}>
                        <td>
                          <strong>
                            {row.id} · {row.title}
                          </strong>
                          <small>{row.workspace}</small>
                        </td>
                        <td>
                          {row.priority} · {row.category}
                        </td>
                        <td>{row.status}</td>
                        <td>
                          {row.acceptance}
                          <small>
                            Depends on:{" "}
                            {row.dependencies.join("; ") ||
                              "No earlier package"}
                          </small>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <details>
                <summary>Artifact families and actual reader coverage</summary>
                <div className="jci-engineering-table">
                  <table>
                    <thead>
                      <tr>
                        <th>Family</th>
                        <th>Reader scope</th>
                        <th>Remaining work</th>
                      </tr>
                    </thead>
                    <tbody>
                      {catalog.artifact_families.map((r: any) => (
                        <tr key={r.id}>
                          <td>
                            {r.title}
                            <small>{r.extensions.join(", ")}</small>
                          </td>
                          <td>{r.support}</td>
                          <td>{r.remaining}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
              <details>
                <summary>
                  Implemented inspection operations and reproducible evidence
                </summary>
                {catalog.operations.map((r: any) => (
                  <div key={r.id}>
                    <h4>{r.title}</h4>
                    <p>
                      {r.support} · {r.evidence_level}
                    </p>
                    <p>{r.implementation}</p>
                    <p>{r.tests}</p>
                    <p>{r.remaining}</p>
                  </div>
                ))}
              </details>
              <details>
                <summary>Versioned manual sources</summary>
                <ul>
                  {catalog.manual_sources.map((r: any) => (
                    <li key={r.id}>
                      <a href={r.url} target="_blank" rel="noreferrer">
                        {r.id}
                        {r.version ? " · " + r.version : ""}
                      </a>
                    </li>
                  ))}
                </ul>
              </details>
            </>
          )}
          <button onClick={() => setRefresh((value) => value + 1)}>
            Refresh operation inventory
          </button>
        </>
      )}
    </section>
  );
}
