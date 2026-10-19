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

export function NativeCaf() {
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
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (!caf) return;
    let active = true;
    api(
      `/caf/${caf.sha256}/objects?q=${encodeURIComponent(query)}&offset=${offset}`,
    )
      .then((r) => {
        if (active) {
          setObjects(r.objects);
          setTotal(r.total);
        }
      })
      .catch((e) => setError(e.message));
    return () => {
      active = false;
    };
  }, [caf, query, offset]);
  async function upload(file?: File) {
    if (!file) return;
    try {
      const form = new FormData();
      form.append("file", file);
      setCaf(await api("/caf", form));
      setFilename(file.name);
      setChanges([]);
      setSelected(null);
      setProperties([]);
      setError("");
      setOffset(0);
    } catch (e) {
      setError(String(e));
    }
  }
  async function select(object: any) {
    try {
      setSelected(object);
      setProperties(
        await api(
          `/caf/${caf.sha256}/properties?ref=${encodeURIComponent(object.ref)}`,
        ),
      );
      setError("");
    } catch (e) {
      setError(String(e));
    }
  }
  function change(p: any, value: string) {
    const rest = changes.filter(
      (c) => !(c.ref === selected.ref && c.property === p.id),
    );
    if (value !== p.scalar.text)
      rest.push({
        ref: selected.ref,
        property: p.id,
        old: p.scalar.text,
        value,
      });
    setChanges(rest);
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
          onChange={(e) => upload(e.target.files?.[0])}
        />
      </div>
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
          <CafGraphPanel id={caf.sha256} filename={filename} />
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
              <div className="table-scroll">
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
                        onClick={() => select(o)}
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
                  {offset + 1}–{Math.min(offset + 200, total)} of {total}
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
            </div>
            <button
              onClick={() => {
                setChanges([]);
              }}
            >
              Discard edits
            </button>
            <button
              className="primary"
              onClick={async () => {
                try {
                  await download(
                    `/caf/${caf.sha256}/export`,
                    { changes },
                    changes.length ? "edited-copy.caf" : "original-copy.caf",
                  );
                  setError("");
                } catch (e) {
                  setError(String(e));
                }
              }}
            >
              <Download size={15} /> Export CAF copy
            </button>
          </div>
        </>
      )}
      {error && <div className="inline-error">{error}</div>}
    </div>
  );
}
