import { useMemo, useRef, useState } from "react";
import { Download, FileArchive, RefreshCw, Upload } from "lucide-react";
import { api, download } from "./api";
import "./niagara-inspector.css";

type Component = { handle: string; name: string; path: string; type: string };
type NativeLink = {
  name: string;
  target: string | null;
  target_path: string;
  type: string;
  source_ord: string;
  source_slot: string;
  target_slot: string;
  source: string | null;
  resolved: boolean;
  converter: boolean;
  relation_id?: string;
  relation_tags?: string;
  unknown_properties?: string[];
};
type Summary = {
  sha256: string;
  components: Component[];
  links: NativeLink[];
  unhandled_typed_records: { path: string; type: string }[];
  members: string[];
  encoding: string;
  validation: string;
};
const PAGE_SIZE = 100;

export function NiagaraInspector() {
  const input = useRef<HTMLInputElement>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [filename, setFilename] = useState("");
  const [fileBytes, setFileBytes] = useState(0);
  const [componentSearch, setComponentSearch] = useState("");
  const [linkSearch, setLinkSearch] = useState("");
  const [componentPage, setComponentPage] = useState(0);
  const [linkPage, setLinkPage] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [exported, setExported] = useState("");

  const byHandle = useMemo(
    () =>
      new Map(
        summary?.components.map((component) => [component.handle, component]) ||
          [],
      ),
    [summary],
  );
  const components = useMemo(() => {
    const query = componentSearch.trim().toLowerCase();
    return (summary?.components || []).filter((component) =>
      [component.name, component.path, component.type, component.handle]
        .join(" ")
        .toLowerCase()
        .includes(query),
    );
  }, [summary, componentSearch]);
  const links = useMemo(() => {
    const query = linkSearch.trim().toLowerCase();
    return (summary?.links || []).filter((link) =>
      [
        link.name,
        link.type,
        link.source_ord,
        link.source_slot,
        link.target_path,
        link.target_slot,
        link.resolved ? "resolved" : "unresolved",
        byHandle.get(link.source || "")?.path,
      ]
        .join(" ")
        .toLowerCase()
        .includes(query),
    );
  }, [summary, linkSearch, byHandle]);

  async function open(file?: File) {
    if (!file || busy) return;
    setBusy(true);
    setError("");
    setExported("");
    try {
      const form = new FormData();
      form.append("file", file);
      const result = await api("/niagara/open", form);
      setSummary(result);
      setFilename(file.name);
      setFileBytes(file.size);
      setComponentSearch("");
      setLinkSearch("");
      setComponentPage(0);
      setLinkPage(0);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  async function reload() {
    if (!summary || busy) return;
    setBusy(true);
    setError("");
    try {
      setSummary(await api(`/niagara/${summary.sha256}`));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function exportOriginal() {
    if (!summary || busy) return;
    setBusy(true);
    setError("");
    setExported("");
    try {
      const name =
        "original-" + (filename.split(/[\\/]/).at(-1) || "archive.bog");
      await download(`/niagara/${summary.sha256}/export`, {}, name);
      setExported(
        `Downloaded ${name}. Original archive bytes, unknown resources and protected content are preserved.`,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="workspace-page niagara-inspector"
      role="region"
      aria-label="Niagara BOG archive inspector"
    >
      <div className="page-intro">
        <div>
          <span className="eyebrow">TRIDIUM · NATIVE ARCHIVE INSPECTION</span>
          <h1>BOG archive inspector</h1>
          <p>
            Inspect native components and links. Keep the original XML, unknown
            logic and resources intact.
          </p>
        </div>
        <button
          className="primary"
          disabled={busy}
          onClick={() => input.current?.click()}
        >
          <Upload size={16} /> Open BOG archive
        </button>
        <input
          type="file"
          accept=".bog,.xml"
          hidden
          ref={input}
          onChange={(event) => open(event.target.files?.[0])}
        />
      </div>
      {!summary ? (
        <div
          className="upload-zone"
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => {
            event.preventDefault();
            open(event.dataTransfer.files[0]);
          }}
        >
          <FileArchive size={52} />
          <h2>Drop a BOG archive or native XML here</h2>
          <p>
            Inspection reads local file structure. Native components are never
            executed.
          </p>
          <button disabled={busy} onClick={() => input.current?.click()}>
            {busy ? "Reading archive…" : "Choose BOG file"}
          </button>
        </div>
      ) : (
        <>
          <div className="stat-grid">
            <div>
              <small>COMPONENTS</small>
              <strong>{summary.components.length.toLocaleString()}</strong>
            </div>
            <div>
              <small>LINKS</small>
              <strong>{summary.links.length.toLocaleString()}</strong>
            </div>
            <div>
              <small>ZIP MEMBERS</small>
              <strong>{summary.members.length || "Raw XML"}</strong>
            </div>
            <div>
              <small>ENCODING KEY SOURCE</small>
              <strong>{summary.encoding}</strong>
            </div>
          </div>
          <section
            className="card niagara-archive-info"
            aria-label="BOG archive metadata"
          >
            <div className="card-header">
              <h3>
                <FileArchive size={17} /> {filename}
              </h3>
              <div className="button-row">
                <button disabled={busy} onClick={reload}>
                  <RefreshCw size={14} /> Reload archive details
                </button>
                <button
                  className="primary"
                  disabled={busy}
                  onClick={exportOriginal}
                >
                  <Download size={15} /> Export original BOG bytes
                </button>
              </div>
            </div>
            <div className="niagara-info-body">
              <dl>
                <div>
                  <dt>Original size</dt>
                  <dd>{fileBytes.toLocaleString()} bytes</dd>
                </div>
                <div>
                  <dt>SHA-256</dt>
                  <dd className="mono">{summary.sha256}</dd>
                </div>
                <div>
                  <dt>Validation</dt>
                  <dd>{summary.validation}</dd>
                </div>
              </dl>
              {summary.encoding !== "none" && (
                <p className="niagara-protected">
                  Protected content is retained. This inspector does not decrypt
                  the archive or require its native components to execute.
                </p>
              )}
              <p>
                Unknown native logic and additional resources remain preserved
                in the original export. To convert supported logic, use Program
                → Import with the original BOG file. That separate workflow
                reports semantic limits.
              </p>
              <details>
                <summary>Inspect preserved archive members</summary>
                {summary.members.length ? (
                  <ul className="niagara-members">
                    {summary.members.map((member) => (
                      <li key={member}>
                        <code>{member}</code>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p>This file is raw native XML, with no ZIP members.</p>
                )}
              </details>
            </div>
          </section>
          {!!summary.unhandled_typed_records?.length && (
            <section
              className="card niagara-unhandled"
              aria-label="Unmodeled native records"
            >
              <div className="card-header">
                <h3>
                  {summary.unhandled_typed_records.length} typed records without
                  component handles
                </h3>
              </div>
              <p>
                These records remain in the original file. Semantic conversion
                requires explicit support for their types.
              </p>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Native path</th>
                      <th>Native type</th>
                    </tr>
                  </thead>
                  <tbody>
                    {summary.unhandled_typed_records
                      .slice(0, 100)
                      .map((record, index) => (
                        <tr key={index}>
                          <td className="mono">{record.path}</td>
                          <td className="mono">{record.type}</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
              {summary.unhandled_typed_records.length > 100 && (
                <p>
                  Showing the first 100 records. Every record remains in the
                  original export.
                </p>
              )}
            </section>
          )}
          <section
            className="card niagara-component-table"
            aria-label="BOG component inventory"
          >
            <div className="card-header">
              <h3>Native components</h3>
              <input
                aria-label="Search BOG components"
                type="search"
                placeholder="Search name, path, type or handle…"
                value={componentSearch}
                onChange={(event) => {
                  setComponentSearch(event.target.value);
                  setComponentPage(0);
                }}
              />
            </div>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Name / native path</th>
                    <th>Type</th>
                    <th>Handle</th>
                  </tr>
                </thead>
                <tbody>
                  {components
                    .slice(
                      componentPage * PAGE_SIZE,
                      (componentPage + 1) * PAGE_SIZE,
                    )
                    .map((component) => (
                      <tr key={component.handle}>
                        <td>
                          <b>{component.name}</b>
                          <small className="mono">{component.path}</small>
                        </td>
                        <td className="mono">{component.type}</td>
                        <td className="mono">{component.handle}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
            {!components.length && (
              <p className="niagara-empty">No components match this search.</p>
            )}
            <div className="pagination">
              <button
                disabled={!componentPage}
                onClick={() => setComponentPage((value) => value - 1)}
              >
                Previous components
              </button>
              <small>
                {components.length ? componentPage * PAGE_SIZE + 1 : 0}–
                {Math.min((componentPage + 1) * PAGE_SIZE, components.length)}{" "}
                of {components.length}
              </small>
              <button
                disabled={(componentPage + 1) * PAGE_SIZE >= components.length}
                onClick={() => setComponentPage((value) => value + 1)}
              >
                Next components
              </button>
            </div>
          </section>
          <section
            className="card niagara-link-table"
            aria-label="BOG link inventory"
          >
            <div className="card-header">
              <h3>Native links</h3>
              <input
                aria-label="Search BOG links"
                type="search"
                placeholder="Search source, destination or resolution…"
                value={linkSearch}
                onChange={(event) => {
                  setLinkSearch(event.target.value);
                  setLinkPage(0);
                }}
              />
            </div>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Link / resolution</th>
                    <th>Source / native slot</th>
                    <th>Destination / native slot</th>
                  </tr>
                </thead>
                <tbody>
                  {links
                    .slice(linkPage * PAGE_SIZE, (linkPage + 1) * PAGE_SIZE)
                    .map((link, index) => (
                      <tr key={index}>
                        <td>
                          <b>{link.name || "Unnamed link"}</b>
                          <small>
                            {link.resolved
                              ? "Resolved locally"
                              : "Unresolved · retained"}
                          </small>
                          <small className="mono">{link.type}</small>
                          {link.converter && <small>Converter retained</small>}
                          {!!link.unknown_properties?.length && (
                            <small>
                              Additional properties:{" "}
                              {link.unknown_properties.join(", ")}
                            </small>
                          )}
                        </td>
                        <td>
                          <span className="mono">
                            {byHandle.get(link.source || "")?.path ||
                              link.source_ord}
                          </span>
                          <small className="mono">
                            {link.source_ord} · {link.source_slot}
                          </small>
                        </td>
                        <td>
                          <span className="mono">{link.target_path}</span>
                          <small className="mono">{link.target_slot}</small>
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
            {!links.length && (
              <p className="niagara-empty">No links match this search.</p>
            )}
            <div className="pagination">
              <button
                disabled={!linkPage}
                onClick={() => setLinkPage((value) => value - 1)}
              >
                Previous links
              </button>
              <small>
                {links.length ? linkPage * PAGE_SIZE + 1 : 0}–
                {Math.min((linkPage + 1) * PAGE_SIZE, links.length)} of{" "}
                {links.length}
              </small>
              <button
                disabled={(linkPage + 1) * PAGE_SIZE >= links.length}
                onClick={() => setLinkPage((value) => value + 1)}
              >
                Next links
              </button>
            </div>
          </section>
        </>
      )}
      {error && (
        <div className="inline-error" role="alert">
          {error}
        </div>
      )}
      {exported && (
        <p className="niagara-exported" role="status">
          {exported}
        </p>
      )}
    </div>
  );
}
