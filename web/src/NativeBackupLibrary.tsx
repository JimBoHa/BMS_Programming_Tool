import { useEffect, useRef, useState } from "react";
import { api, apiBlobDocument, saveBlob } from "./api";
import "./native-backup-library.css";

type Data = Record<string, any>;
const base = "/bacnet/controller/native-application";
const profile = "native-backup-lifecycle/1";
const hash = (value: unknown) =>
  typeof value === "string" && /^[a-f0-9]{64}$/.test(value);

function validBackup(row: Data) {
  return (
    /^[a-f0-9]{32}$/.test(row?.id || "") &&
    hash(row.evidence_sha256) &&
    typeof row.archived === "boolean" &&
    Number.isInteger(row.revision) &&
    row.revision >= 0 &&
    row.revision <= 1024 &&
    typeof row.captured_at === "string" &&
    typeof row.device === "string" &&
    typeof row.target?.address === "string" &&
    ["3", "11", "12"].every(
      (id) =>
        hash(row.files?.[id]?.sha256) &&
        Number.isInteger(row.files[id].bytes) &&
        row.files[id].bytes > 0 &&
        row.files[id].bytes <= 2097152,
    ) &&
    row.file_bytes ===
      Object.values(row.files).reduce(
        (total: number, file: any) => total + file.bytes,
        0,
      )
  );
}
const envelope = (row: Data) =>
  row?.profile === profile &&
  row.controller_queries === false &&
  row.field_actions === false &&
  row.active_limit === 128 &&
  row.archive_limit === 1024;

export function NativeBackupLibrary() {
  const [state, setState] = useState("active"),
    [query, setQuery] = useState(""),
    [search, setSearch] = useState(""),
    [offset, setOffset] = useState(0),
    [report, setReport] = useState<{ key: string; data: Data } | null>(null),
    [selection, setSelection] = useState(""),
    [error, setError] = useState(""),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false);
  const key = JSON.stringify([state, query, offset]);
  const alive = useRef(false),
    epoch = useRef(0),
    owner = useRef(key),
    active = useRef(false);
  if (owner.current !== key) {
    owner.current = key;
    epoch.current++;
  }
  const data = report?.key === key ? report.data : null;
  const selected = data?.backups.find((row: Data) => row.id === selection);
  const current = (ticket: number, context: string) =>
    alive.current && epoch.current === ticket && owner.current === context;

  async function refresh() {
    const ticket = ++epoch.current,
      context = owner.current;
    setBusy(true);
    setReport(null);
    setSelection("");
    setError("");
    try {
      const result = await api(base + "/backup-library/list", {
        state,
        query,
        offset,
        limit: 32,
      });
      if (
        !envelope(result) ||
        result.read_only !== true ||
        result.state !== state ||
        result.query !== query ||
        result.offset !== offset ||
        result.limit !== 32 ||
        !Array.isArray(result.backups) ||
        result.backups.length > 32 ||
        result.backups.some(
          (row: Data) =>
            !validBackup(row) || row.archived !== (state === "archived"),
        ) ||
        !Number.isInteger(result.active_count) ||
        result.active_count < 0 ||
        result.active_count > 128 ||
        !Number.isInteger(result.archived_count) ||
        result.archived_count < 0 ||
        result.archived_count > 1024 ||
        !Number.isInteger(result.total) ||
        result.total < result.backups.length ||
        result.total > 1024 ||
        typeof result.has_more !== "boolean"
      )
        throw new Error(
          "Backup list does not match the requested local catalog.",
        );
      if (current(ticket, context)) setReport({ key: context, data: result });
    } catch (failure) {
      if (current(ticket, context)) setError(String(failure));
    } finally {
      if (current(ticket, context)) setBusy(false);
    }
  }
  useEffect(() => {
    alive.current = true;
    const retire = () => {
      epoch.current++;
      setReport(null);
      setSelection("");
      setError("");
      setMessage("");
      setBusy(false);
    };
    document.addEventListener("visibilitychange", retire);
    return () => {
      alive.current = false;
      epoch.current++;
      document.removeEventListener("visibilitychange", retire);
    };
  }, []);
  useEffect(() => {
    setMessage("");
    void refresh();
  }, [key]);

  async function change() {
    if (!selected || active.current) return;
    active.current = true;
    const ticket = ++epoch.current,
      context = owner.current,
      source = selected,
      action = source.archived ? "restore" : "archive";
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await api(base + "/backup-library/change", {
        capture_id: source.id,
        snapshot_sha256: source.evidence_sha256,
        expected_revision: source.revision,
        action,
      });
      if (
        !envelope(result) ||
        result.local_state_changed !== true ||
        !validBackup(result.backup) ||
        result.backup.id !== source.id ||
        result.backup.evidence_sha256 !== source.evidence_sha256 ||
        result.backup.revision !== source.revision + 1 ||
        result.backup.archived !== (action === "archive") ||
        result.transition?.capture_id !== source.id ||
        result.transition?.snapshot_sha256 !== source.evidence_sha256 ||
        result.transition?.revision !== result.backup.revision ||
        result.transition?.archived !== result.backup.archived ||
        !hash(result.transition?.evidence_sha256)
      )
        throw new Error(
          "Catalog response does not match the selected original backup. Refresh before continuing.",
        );
      if (current(ticket, context)) {
        setMessage(
          action === "archive"
            ? "Backup archived locally. Original files and recovery references retained."
            : "Backup restored to the active list. No controller operation performed.",
        );
        await refresh();
      }
    } catch (failure) {
      if (current(ticket, context)) {
        setReport(null);
        setSelection("");
        setError(String(failure));
      }
    } finally {
      active.current = false;
      if (current(ticket, context)) setBusy(false);
    }
  }
  async function download() {
    if (!selected || active.current) return;
    active.current = true;
    const ticket = ++epoch.current,
      context = owner.current,
      source = selected;
    setBusy(true);
    setError("");
    try {
      const document = await apiBlobDocument(base + "/backups/" + source.id);
      if (current(ticket, context))
        saveBlob(document.blob, "native-backup-" + source.id + ".zip");
    } catch (failure) {
      if (current(ticket, context)) setError(String(failure));
    } finally {
      active.current = false;
      if (current(ticket, context)) setBusy(false);
    }
  }
  return (
    <section
      className="native-backup-library"
      aria-label="Native backup library"
    >
      <h1>Native backups</h1>
      <p>
        Retained controller captures on this computer. Archiving frees an active
        slot, not disk space. Original files stay in place, including their
        transfer and recovery references.
      </p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          setOffset(0);
          setQuery(search);
        }}
      >
        <label>
          Backup list
          <select
            aria-label="Backup list"
            value={state}
            disabled={busy}
            onChange={(event) => {
              setState(event.target.value);
              setOffset(0);
              setSelection("");
            }}
          >
            <option value="active">Active backups</option>
            <option value="archived">Archived backups</option>
          </select>
        </label>
        <label>
          Search backups
          <input
            aria-label="Search backups"
            value={search}
            maxLength={256}
            disabled={busy}
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
        <button disabled={busy} type="submit">
          Search backups
        </button>
        <button
          disabled={busy}
          type="button"
          onClick={() => {
            setMessage("");
            void refresh();
          }}
        >
          Refresh backups
        </button>
      </form>
      {busy && <p role="status">Updating local backup catalog…</p>}
      {error && (
        <p role="alert">
          {error} Refresh backups to obtain their current catalog state.
        </p>
      )}
      {message && <p role="status">{message}</p>}
      {data && (
        <>
          <p>
            {data.active_count} / 128 active · {data.archived_count} / 1024
            archived · {data.total} matching.
          </p>
          <div className="native-backup-list-scroll">
            <table>
              <caption>
                {state === "archived" ? "Archived" : "Active"} native backups
              </caption>
              <thead>
                <tr>
                  <th>Controller / source</th>
                  <th>Route / Device</th>
                  <th>Captured</th>
                  <th>Original files</th>
                  <th>Details</th>
                </tr>
              </thead>
              <tbody>
                {data.backups.map((row: Data) => (
                  <tr key={row.id}>
                    <td>
                      {row.identity?.["object-name"] || "Unnamed controller"}
                      <br />
                      <code>{row.id.slice(0, 8)}</code>
                      <br />
                      {row.source_identity_matches
                        ? "Identity captured"
                        : "Identity unverified"}
                    </td>
                    <td>
                      {row.target.address}
                      <br />
                      {row.target.router && (
                        <>
                          via {row.target.router} / DNET {row.target.dnet}
                          <br />
                        </>
                      )}
                      {row.device}
                    </td>
                    <td>{row.captured_at}</td>
                    <td>{row.file_bytes.toLocaleString()} bytes</td>
                    <td>
                      <button
                        disabled={busy}
                        aria-pressed={selection === row.id}
                        onClick={() => setSelection(row.id)}
                        aria-label={"Select backup " + row.id.slice(0, 8)}
                      >
                        Select backup
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!data.backups.length && (
            <p>
              No matching backups. Capture a verified controller first, or
              choose another list or search.
            </p>
          )}
          <div className="button-row">
            <button
              disabled={busy || offset === 0}
              onClick={() => setOffset(Math.max(0, offset - 32))}
            >
              Previous backups
            </button>
            <button
              disabled={busy || !data.has_more}
              onClick={() => setOffset(offset + 32)}
            >
              Next backups
            </button>
          </div>
        </>
      )}
      {selected && (
        <section
          aria-label="Selected native backup"
          className="native-backup-selection"
        >
          <h2>{selected.identity?.["object-name"] || selected.device}</h2>
          <p>
            {selected.device} at {selected.target.address}
            {selected.target.router
              ? ` via ${selected.target.router} / DNET ${selected.target.dnet}`
              : ""}{" "}
            · captured {selected.captured_at}
          </p>
          <p>
            {selected.archived ? "Archived locally" : "Active local backup"}.
            Restoring to the list makes it selectable for inspection or a new,
            separately reviewed operation. This action never restores or writes
            a controller.
          </p>
          <div className="button-row">
            <button
              className="primary"
              disabled={busy}
              onClick={() => void change()}
            >
              {selected.archived
                ? "Restore to active backups"
                : "Archive local backup"}
            </button>
            <button disabled={busy} onClick={() => void download()}>
              Download original backup ZIP
            </button>
          </div>
          <details>
            <summary>Original source evidence</summary>
            <pre>{JSON.stringify(selected, null, 2)}</pre>
          </details>
        </section>
      )}
    </section>
  );
}
