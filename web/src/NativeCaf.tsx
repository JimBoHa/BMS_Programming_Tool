import { useEffect, useRef, useState } from "react";
import {
  FileArchive,
  Upload,
  Download,
  Search,
  FileCheck2,
} from "lucide-react";
import { api, download } from "./api";
import { CafGraphPanel } from "./CafGraphPanel";
import { CafHardwarePanel } from "./CafHardwarePanel";
import { JciPreflight } from "./JciPreflight";

function scalarSignature(changes: any[]) {
  return JSON.stringify(
    [...changes].sort(
      (a, b) =>
        String(a.ref).localeCompare(String(b.ref)) ||
        String(a.property).localeCompare(String(b.property)),
    ),
  );
}

export function NativeCaf({ visible = true }: { visible?: boolean }) {
  const [caf, setCaf] = useState<any>(null),
    [objects, setObjects] = useState<any[]>([]),
    [total, setTotal] = useState(0),
    [query, setQuery] = useState(""),
    [offset, setOffset] = useState(0),
    [selected, setSelected] = useState<any>(null),
    [properties, setProperties] = useState<any[]>([]),
    [changes, setChanges] = useState<any[]>([]),
    [error, setError] = useState("");
  const [filename, setFilename] = useState("controller.caf");
  const [archiveGeneration, setArchiveGeneration] = useState(0);
  const [opening, setOpening] = useState(false);
  const [loadingObjects, setLoadingObjects] = useState(false);
  const [loadingProperties, setLoadingProperties] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [graphDirty, setGraphDirty] = useState(false);
  const [hardwareDirty, setHardwareDirty] = useState(false);
  const [savedScalarKey, setSavedScalarKey] = useState("[]");
  const [exported, setExported] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const mounted = useRef(false);
  const uploadRequest = useRef(0);
  const propertyRequest = useRef(0);
  const exportRequest = useRef(0);
  const activeArchive = useRef<string | null>(null);
  const scalarKey = scalarSignature(changes);
  const unsavedScalars = changes.length > 0 && scalarKey !== savedScalarKey;
  useEffect(() => {
    if (!unsavedScalars && !graphDirty && !hardwareDirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [unsavedScalars, graphDirty, hardwareDirty]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      uploadRequest.current++;
      propertyRequest.current++;
      exportRequest.current++;
    };
  }, []);
  useEffect(() => {
    if (!caf) return;
    let active = true;
    setObjects([]);
    setTotal(0);
    setLoadingObjects(true);
    api(
      `/caf/${caf.sha256}/objects?q=${encodeURIComponent(query)}&offset=${offset}`,
    )
      .then((r) => {
        if (active) {
          setObjects(r.objects);
          setTotal(r.total);
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      })
      .finally(() => {
        if (active) setLoadingObjects(false);
      });
    return () => {
      active = false;
    };
  }, [caf, query, offset]);
  async function upload(file?: File) {
    if (!file || !visible) return;
    if (
      (unsavedScalars || graphDirty || hardwareDirty) &&
      !window.confirm(
        "Discard unexported CAF edits and open another file? Cancel to keep editing or export the current changes first.",
      )
    )
      return;
    const request = ++uploadRequest.current;
    setOpening(true);
    setError("");
    try {
      const form = new FormData();
      form.append("file", file);
      const next = await api("/caf", form);
      if (!mounted.current || request !== uploadRequest.current) return;
      activeArchive.current = next.sha256;
      propertyRequest.current++;
      exportRequest.current++;
      setCaf(next);
      setArchiveGeneration((value) => value + 1);
      setFilename(file.name);
      setObjects([]);
      setTotal(0);
      setQuery("");
      setChanges([]);
      setSavedScalarKey("[]");
      setGraphDirty(false);
      setHardwareDirty(false);
      setExported("");
      setExporting(false);
      setSelected(null);
      setProperties([]);
      setLoadingProperties(false);
      setError("");
      setOffset(0);
    } catch (e) {
      if (mounted.current && request === uploadRequest.current)
        setError(String(e));
    } finally {
      if (mounted.current && request === uploadRequest.current)
        setOpening(false);
    }
  }
  async function select(object: any) {
    if (opening || !caf) return;
    const request = ++propertyRequest.current;
    const archive = caf.sha256;
    setSelected(object);
    setProperties([]);
    setLoadingProperties(true);
    setError("");
    try {
      const result = await api(
        `/caf/${archive}/properties?ref=${encodeURIComponent(object.ref)}`,
      );
      if (
        mounted.current &&
        request === propertyRequest.current &&
        activeArchive.current === archive
      )
        setProperties(result);
    } catch (e) {
      if (
        mounted.current &&
        request === propertyRequest.current &&
        activeArchive.current === archive
      )
        setError(String(e));
    } finally {
      if (mounted.current && request === propertyRequest.current)
        setLoadingProperties(false);
    }
  }
  function change(p: any, value: string) {
    setChanges((previous) => {
      const rest = previous.filter(
        (c) => !(c.ref === selected.ref && c.property === p.id),
      );
      if (value !== p.scalar.text)
        rest.push({
          ref: selected.ref,
          property: p.id,
          old: p.scalar.text,
          value,
        });
      return rest;
    });
    setError("");
  }
  async function exportScalars() {
    if (!caf || exporting || opening || !visible) return;
    const request = ++exportRequest.current;
    const archive = caf.sha256;
    const snapshot = changes.map((item) => ({ ...item }));
    const key = scalarSignature(snapshot);
    const basename = filename.replace(/\.caf$/i, "");
    const name = `${basename}-${snapshot.length ? "scalars" : "original"}.caf`;
    const current = () =>
      mounted.current &&
      request === exportRequest.current &&
      activeArchive.current === archive;
    setExporting(true);
    setError("");
    try {
      const saved = await download(
        `/caf/${archive}/export`,
        { changes: snapshot },
        name,
        current,
      );
      if (!saved || !current()) return;
      setSavedScalarKey(key);
      setExported(
        `Browser download requested for ${name} with ${snapshot.length} scalar change${snapshot.length === 1 ? "" : "s"}. This view still shows the original archive; current scalar drafts remain visible.`,
      );
    } catch (e) {
      if (current())
        setError(
          `Scalar CAF export failed: ${e instanceof Error ? e.message : String(e)}`,
        );
    } finally {
      if (current()) setExporting(false);
    }
  }
  return (
    <div className="workspace-page">
      <div className="page-intro">
        <div>
          <span className="eyebrow">JOHNSON CONTROLS · NATIVE FILES</span>
          <h1>CAF workbench</h1>
          <p>
            Inspect FX and Metasys files. Preserve unknown objects and export a
            separate edited copy.
          </p>
        </div>
        <button className="primary" onClick={() => input.current?.click()}>
          <Upload size={16} /> Open CAF file
        </button>
        <input
          type="file"
          accept=".caf"
          hidden
          ref={input}
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = "";
            void upload(file);
          }}
        />
      </div>
      {opening && <p role="status">Opening CAF archive…</p>}
      {!caf ? (
        <div
          className="upload-zone"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            upload(e.dataTransfer.files[0]);
          }}
        >
          <FileArchive size={52} />
          <h2>Drop a .caf file here</h2>
          <p>Files remain on this computer. Originals stay unchanged.</p>
          <button onClick={() => input.current?.click()}>Choose file</button>
        </div>
      ) : (
        <>
          <p aria-label="Current CAF archive">{filename}</p>
          <div className="stat-grid">
            <div>
              <small>CONTROLLER</small>
              <strong>{caf.model || "Not identified"}</strong>
            </div>
            <div>
              <small>RELEASE MODE</small>
              <strong>{caf.release_mode || "Not identified"}</strong>
            </div>
            <div>
              <small>OBJECTS</small>
              <strong>{caf.objects.toLocaleString()}</strong>
            </div>
            <div>
              <small>LOCAL EDITS</small>
              <strong>{changes.length}</strong>
            </div>
          </div>
          <div className="notice">
            <FileCheck2 size={20} />
            <div>
              <b>XML/container checks passed</b>
              <p>
                Scalar changes are offline edits. The matching CCT/PCT version
                must validate the edited file before a field download. Full
                native logic creation, simulation and download are pending.
              </p>
            </div>
          </div>
          <JciPreflight
            key={`preflight:${caf.sha256}:${archiveGeneration}`}
            id={caf.sha256}
            disabled={opening || !visible}
          />
          <CafHardwarePanel
            key={`hardware:${caf.sha256}:${archiveGeneration}`}
            id={caf.sha256}
            filename={filename}
            disabled={opening || !visible}
            onDirtyChange={setHardwareDirty}
          />
          <CafGraphPanel
            key={`${caf.sha256}:${archiveGeneration}`}
            id={caf.sha256}
            filename={filename}
            disabled={opening || !visible}
            scalarChangeCount={changes.length}
            onDirtyChange={setGraphDirty}
          />
          <div className="caf-layout">
            <section className="card">
              <div className="card-header">
                <h3>Controller objects</h3>
                <div className="search">
                  <Search size={15} />
                  <input
                    value={query}
                    placeholder="Search name, class, reference…"
                    onChange={(e) => {
                      setQuery(e.target.value);
                      setOffset(0);
                    }}
                  />
                </div>
              </div>
              <div className="table-scroll" aria-busy={loadingObjects}>
                <table>
                  <thead>
                    <tr>
                      <th>Name / description</th>
                      <th>Class</th>
                      <th>Stored value</th>
                    </tr>
                  </thead>
                  <tbody>
                    {objects.map((o) => (
                      <tr
                        key={o.ref}
                        className={o.ref === selected?.ref ? "active-row" : ""}
                        onClick={() => void select(o)}
                      >
                        <td>
                          <b>
                            {o.name || o.description || o.ref.split(".").at(-1)}
                          </b>
                          <small>{o.description || o.ref}</small>
                        </td>
                        <td className="mono">
                          {o.class_id}
                          <small>{o.class_name}</small>
                        </td>
                        <td>{o.stored_value || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="pagination">
                <button
                  disabled={!offset}
                  onClick={() => setOffset(Math.max(0, offset - 200))}
                >
                  Previous
                </button>
                <small>
                  {total ? offset + 1 : 0}–{Math.min(offset + 200, total)} of{" "}
                  {total}
                </small>
                <button
                  disabled={offset + 200 >= total}
                  onClick={() => setOffset(offset + 200)}
                >
                  Next
                </button>
              </div>
            </section>
            <section className="card">
              <div className="card-header">
                <h3>{selected?.name || "Object properties"}</h3>
              </div>
              {!selected ? (
                <div className="empty-panel">
                  Select an object to inspect scalar values and preserved
                  structured data.
                </div>
              ) : (
                <div className="properties-list">
                  <p className="mono ref">{selected.ref}</p>
                  {loadingProperties && (
                    <p role="status">Reading selected object properties…</p>
                  )}
                  {properties.map((p) => {
                    const edited =
                      p.editable &&
                      changes.find(
                        (c) => c.ref === selected.ref && c.property === p.id,
                      );
                    return (
                      <div
                        key={p.kind + ":" + p.id}
                        className={"property-row " + (edited ? "edited" : "")}
                      >
                        <label>
                          <b>{p.name || "Property " + p.id}</b>
                          <small>
                            {p.kind} {p.id} ·{" "}
                            {p.scalar?.type || "structured data"}
                          </small>
                          {p.scalar ? (
                            p.editable ? (
                              <input
                                aria-label={"CAF property " + p.id}
                                disabled={opening}
                                value={edited?.value ?? p.scalar.text}
                                onChange={(e) => change(p, e.target.value)}
                              />
                            ) : (
                              <span className="mono property-value">
                                {p.scalar.text || "(empty)"}
                              </span>
                            )
                          ) : (
                            <details>
                              <summary>Inspect preserved XML</summary>
                              <pre>{p.xml}</pre>
                            </details>
                          )}
                        </label>
                      </div>
                    );
                  })}
                </div>
              )}
            </section>
          </div>
          <div className="export-strip">
            <div>
              <b>{changes.length} proposed scalar changes</b>
              <small>
                Unchanged export preserves the original file bytes exactly.
              </small>
              {unsavedScalars && (
                <small>Current scalar edits have not been exported.</small>
              )}
              {graphDirty && (
                <small>
                  Scalar copies exclude pending native connection proposals.
                  Open the connection-edited copy first to combine changes.
                </small>
              )}
            </div>
            <button
              disabled={opening || exporting || !changes.length}
              onClick={() => {
                if (
                  unsavedScalars &&
                  !window.confirm("Discard unexported scalar CAF edits?")
                )
                  return;
                setChanges([]);
              }}
            >
              Discard edits
            </button>
            <button
              className="primary"
              disabled={opening || exporting}
              onClick={exportScalars}
            >
              <Download size={15} />{" "}
              {exporting ? "Preparing CAF copy…" : "Export CAF copy"}
            </button>
          </div>
          {exported && (
            <p
              className="caf-graph-exported"
              role="status"
              aria-label="Scalar CAF export result"
            >
              {exported}
            </p>
          )}
        </>
      )}
      {error && (
        <div className="inline-error" role="alert">
          {error}
        </div>
      )}
    </div>
  );
}
