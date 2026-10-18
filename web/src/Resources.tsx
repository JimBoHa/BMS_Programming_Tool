import { useEffect, useState } from "react";
import { BookOpen, Search, ExternalLink } from "lucide-react";
import { api } from "./api";

export function Resources() {
  const [capabilities, setCapabilities] = useState<any[]>([]),
    [references, setReferences] = useState<any[]>([]),
    [requirements, setRequirements] = useState<any[]>([]),
    [search, setSearch] = useState(""),
    [error, setError] = useState("");
  useEffect(() => {
    Promise.all([
      api("/capabilities"),
      api("/references"),
      api("/requirements"),
    ])
      .then(([c, r, requirements]) => {
        setCapabilities(c);
        setReferences(r);
        setRequirements(requirements);
      })
      .catch((e) => setError(e.message));
  }, []);
  const shown = references.filter((r) =>
    JSON.stringify(r).toLowerCase().includes(search.toLowerCase()),
  );
  return (
    <div className="workspace-page">
      <div className="page-intro">
        <div>
          <span className="eyebrow">EVIDENCE AND COMPATIBILITY</span>
          <h1>Reference desk</h1>
          <p>
            Feature support is specific to the format, runtime and controller.
            Pending adapters remain visible.
          </p>
        </div>
        <BookOpen size={32} />
      </div>
      <section className="card">
        <div className="card-header">
          <h3>Capability matrix</h3>
        </div>
        <table>
          <thead>
            <tr>
              <th>Capability</th>
              <th>Status</th>
              <th>Scope / remaining work</th>
            </tr>
          </thead>
          <tbody>
            {capabilities.map((c: any) => (
              <tr key={c.feature}>
                <td>
                  <b>{c.feature}</b>
                </td>
                <td>
                  <span
                    className={
                      "pill " +
                      (c.status === "implemented" ? "complete" : "pending")
                    }
                  >
                    {c.status}
                  </span>
                </td>
                <td>{c.scope}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <details className="card requirement-details">
        <summary>
          Feature criteria · {requirements.length} requirements from the manuals
        </summary>
        <table>
          <thead>
            <tr>
              <th>Criterion</th>
              <th>Status</th>
              <th>Evidence</th>
            </tr>
          </thead>
          <tbody>
            {requirements.map((r) => (
              <tr key={r.id}>
                <td>
                  <b>
                    {r.id} · {r.feature}
                  </b>
                  <small>{r.acceptance_criterion}</small>
                </td>
                <td>
                  <span
                    className={
                      "pill " +
                      (r.status === "implemented" ? "complete" : "pending")
                    }
                  >
                    {r.status}
                  </span>
                </td>
                <td>
                  {r.evidence}
                  <small>PDF pages / section: {r.pdf_pages_or_section}</small>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
      <section className="card">
        <div className="card-header">
          <h3>Research sources</h3>
          <div className="search">
            <Search size={15} />
            <input
              aria-label="Search research sources"
              placeholder="Vendor, title, feature…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
        </div>
        <div className="reference-list">
          {shown.map((r: any, i) => (
            <div className="reference-item" key={i}>
              <a href={r.url} target="_blank" rel="noreferrer">
                <div>
                  <span className="eyebrow">{r.vendor || r.kind}</span>
                  <h4>{r.title || r.repository || r.url.split("/").at(-1)}</h4>
                  <p>{r.notes || r.scope || ""}</p>
                </div>
                <ExternalLink size={15} />
              </a>
              {r.local_collection && r.local_id && (
                <a
                  className="local-pdf"
                  href={`/api/library/${r.local_collection}/${r.local_id}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open local PDF{r.pages ? " · " + r.pages + " pages" : ""}
                </a>
              )}
            </div>
          ))}
        </div>
      </section>
      {error && <div className="inline-error">{error}</div>}
    </div>
  );
}
