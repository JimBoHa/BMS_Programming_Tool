import { useEffect, useRef, useState } from "react";
import { api, saveBlob } from "./api";

type Data = Record<string, any>;
const base = "/bacnet/controller/native-application/backup-library";
const digest = (value: unknown) =>
  typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const envelope = (value: Data) =>
  value?.profile === "native-backup-integrity/1" &&
  value.read_only === true &&
  value.controller_queries === false &&
  value.field_actions === false &&
  value.storage_mutations === false &&
  digest(value.report_sha256);
const integer = (value: unknown, maximum: number) =>
  typeof value === "number" &&
  Number.isInteger(value) &&
  value >= 0 &&
  value <= maximum;
function validEntry(row: Data) {
  return (
    typeof row?.entry_name === "string" &&
    row.entry_name.length > 0 &&
    row.entry_name.length <= 1024 &&
    (row.capture_id === null ||
      (/^[a-f0-9]{32}$/.test(row.capture_id) &&
        row.capture_id === row.entry_name)) &&
    row.original_files_checked === false &&
    (row.status === "manifest_available"
      ? row.capture_id !== null &&
        digest(row.manifest_sha256) &&
        digest(row.snapshot_sha256)
      : ["manifest_unavailable", "unrecognized_entry"].includes(row.status) &&
        row.manifest_sha256 === null &&
        row.snapshot_sha256 === null)
  );
}
function validCheck(result: Data, selected: Data) {
  if (
    !envelope(result) ||
    result.kind !== "original_file_check" ||
    result.capture_id !== selected.capture_id ||
    result.manifest_sha256 !== selected.manifest_sha256 ||
    result.snapshot_sha256 !== selected.snapshot_sha256 ||
    result.observation_is_atomic !== false ||
    typeof result.checked_at !== "string" ||
    !Array.isArray(result.files) ||
    result.files.length !== 3
  )
    return false;
  for (const [index, file] of result.files.entries()) {
    if (
      file.file_id !== [3, 11, 12][index] ||
      !integer(file.expected_bytes, 2097152) ||
      file.expected_bytes === 0 ||
      !digest(file.expected_sha256) ||
      !["matches", "mismatch", "unavailable"].includes(file.status)
    )
      return false;
    if (file.status === "unavailable") {
      if (file.observed_bytes !== null || file.observed_sha256 !== null)
        return false;
    } else if (
      !integer(file.observed_bytes, 2097152) ||
      !digest(file.observed_sha256) ||
      (file.status === "matches") !==
        (file.observed_bytes === file.expected_bytes &&
          file.observed_sha256 === file.expected_sha256)
    )
      return false;
  }
  const expected = result.files.some(
    (file: Data) => file.status === "unavailable",
  )
    ? "incomplete"
    : result.files.some((file: Data) => file.status === "mismatch")
      ? "mismatch"
      : "matches_manifest";
  return result.integrity === expected;
}

export function NativeBackupIntegrity() {
  const [search, setSearch] = useState(""),
    [inventory, setInventory] = useState<Data | null>(null),
    [selection, setSelection] = useState(""),
    [check, setCheck] = useState<{ key: string; data: Data } | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const alive = useRef(false),
    epoch = useRef(0);
  const selected = inventory?.entries.find(
    (row: Data) => row.entry_name === selection,
  );
  const key = selected
    ? JSON.stringify([selected.capture_id, selected.manifest_sha256])
    : "";
  const owner = useRef(key);
  if (owner.current !== key) {
    owner.current = key;
    epoch.current++;
  }
  const result = check?.key === key ? check.data : null;
  const current = (ticket: number) => alive.current && epoch.current === ticket;
  useEffect(() => {
    alive.current = true;
    const retire = () => {
      epoch.current++;
      setInventory(null);
      setSelection("");
      setCheck(null);
      setError("");
      setBusy(false);
    };
    document.addEventListener("visibilitychange", retire);
    return () => {
      alive.current = false;
      epoch.current++;
      document.removeEventListener("visibilitychange", retire);
    };
  }, []);

  async function inspect(query = search, offset = 0) {
    const ticket = ++epoch.current;
    // Retire a selected source synchronously before admitting this scan reply.
    owner.current = "";
    setSelection("");
    setCheck(null);
    setInventory(null);
    setError("");
    setBusy(true);
    try {
      const data = await api(base + "/storage-inventory", {
        query,
        offset,
        limit: 16,
      });
      if (
        !envelope(data) ||
        data.kind !== "storage_inventory" ||
        data.query !== query ||
        data.offset !== offset ||
        data.limit !== 16 ||
        data.entry_limit !== 1152 ||
        typeof data.scan_complete !== "boolean" ||
        !integer(data.observed_entries, 1152) ||
        !integer(data.matching_observed_entries, data.observed_entries) ||
        typeof data.has_more !== "boolean" ||
        !Array.isArray(data.entries) ||
        data.entries.length > 16 ||
        data.entries.some((row: Data) => !validEntry(row))
      )
        throw new Error(
          "Storage inventory does not match the requested local page.",
        );
      if (current(ticket)) setInventory(data);
    } catch (failure) {
      if (current(ticket)) setError(String(failure));
    } finally {
      if (current(ticket)) setBusy(false);
    }
  }
  async function checkOriginals() {
    if (!selected || selected.status !== "manifest_available") return;
    const source = selected,
      context = key,
      ticket = ++epoch.current;
    setCheck(null);
    setError("");
    setBusy(true);
    try {
      const data = await api(base + "/check-originals", {
        capture_id: source.capture_id,
        manifest_sha256: source.manifest_sha256,
      });
      if (!validCheck(data, source))
        throw new Error(
          "Integrity response does not match the selected original source.",
        );
      if (current(ticket) && owner.current === context)
        setCheck({ key: context, data });
    } catch (failure) {
      if (current(ticket)) setError(String(failure));
    } finally {
      if (current(ticket)) setBusy(false);
    }
  }
  function choose(name: string) {
    epoch.current++;
    setSelection(name);
    setCheck(null);
    setError("");
    setBusy(false);
  }
  return (
    <section aria-label="Native backup storage inspection">
      <p>
        Inspect stored entries even when a damaged manifest prevents the
        ordinary backup list from opening. Incomplete captures remain evidence;
        this view does not repair, delete, archive or restore them.
      </p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void inspect();
        }}
      >
        <label>
          Stored entry name or capture ID
          <input
            aria-label="Stored entry search"
            value={search}
            maxLength={256}
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
        <button type="submit" disabled={busy}>
          Inspect backup storage
        </button>
      </form>
      {busy && <p role="status">Reading local backup evidence…</p>}
      {error && (
        <p role="alert">
          {error} Inspect storage again before selecting a source.
        </p>
      )}
      {inventory && (
        <>
          <p>
            {inventory.observed_entries} observed entries ·{" "}
            {inventory.matching_observed_entries} matching names.
          </p>
          {!inventory.scan_complete && (
            <p role="alert">
              Inspection stopped at 1152 entries. Additional entries were not
              inspected; search and counts cover only this observed portion.
            </p>
          )}
          <div className="native-backup-list-scroll">
            <table>
              <caption>Observed native backup storage entries</caption>
              <thead>
                <tr>
                  <th>Entry</th>
                  <th>Manifest</th>
                  <th>Original files</th>
                  <th>Details</th>
                </tr>
              </thead>
              <tbody>
                {inventory.entries.map((row: Data) => (
                  <tr key={row.entry_name}>
                    <td>
                      <button
                        aria-label={`Inspect stored entry ${row.entry_name}`}
                        aria-pressed={selection === row.entry_name}
                        onClick={() => choose(row.entry_name)}
                      >
                        {row.entry_name}
                      </button>
                    </td>
                    <td>
                      {row.status === "manifest_available"
                        ? "Manifest available"
                        : row.status === "manifest_unavailable"
                          ? "Manifest unavailable"
                          : "Unrecognized entry"}
                    </td>
                    <td>Not checked</td>
                    <td>
                      {row.problem ||
                        "Select this source to check its three original files."}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <button
            disabled={busy || inventory.offset === 0}
            onClick={() =>
              void inspect(inventory.query, Math.max(0, inventory.offset - 16))
            }
          >
            Previous storage page
          </button>{" "}
          <button
            disabled={busy || !inventory.has_more}
            onClick={() => void inspect(inventory.query, inventory.offset + 16)}
          >
            Next storage page
          </button>
        </>
      )}
      {selected && (
        <section
          className="native-backup-selection"
          aria-label="Selected backup storage entry"
        >
          <h2>Stored entry {selected.entry_name}</h2>
          {selected.status === "manifest_available" ? (
            <>
              <p>
                Original manifest is readable. The payloads have not been
                checked by this inventory.
              </p>
              <button disabled={busy} onClick={() => void checkOriginals()}>
                Check original backup files
              </button>
            </>
          ) : (
            <p>
              {selected.problem} Retain this original entry for investigation.
            </p>
          )}
          {result && (
            <div aria-label="Original backup integrity result">
              <p>
                <strong>
                  {result.integrity === "matches_manifest"
                    ? "Original files match manifest"
                    : result.integrity === "mismatch"
                      ? "Original file mismatch"
                      : "Original files incomplete"}
                </strong>{" "}
                · {result.checked_at}
              </p>
              <p>
                Local size and SHA-256 observations only. Files are read
                sequentially; this is not an atomic snapshot or proof of
                controller restore acceptance.
              </p>
              <div className="native-backup-list-scroll">
                <table>
                  <caption>Original file integrity observations</caption>
                  <thead>
                    <tr>
                      <th>File</th>
                      <th>Result</th>
                      <th>Expected bytes</th>
                      <th>Observed bytes</th>
                      <th>Problem</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.files.map((file: Data) => (
                      <tr key={file.file_id}>
                        <td>{file.file_id}</td>
                        <td>{file.status}</td>
                        <td>{file.expected_bytes}</td>
                        <td>{file.observed_bytes ?? "Unavailable"}</td>
                        <td>{file.problem || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <button
                onClick={() =>
                  saveBlob(
                    new Blob([JSON.stringify(result, null, 2)], {
                      type: "application/json",
                    }),
                    `native-backup-integrity-${result.capture_id}.json`,
                  )
                }
              >
                Export integrity report
              </button>
              <details>
                <summary>Integrity evidence</summary>
                <pre>{JSON.stringify(result, null, 2)}</pre>
              </details>
            </div>
          )}
          <details>
            <summary>Stored source evidence</summary>
            <pre>{JSON.stringify(selected, null, 2)}</pre>
          </details>
        </section>
      )}
    </section>
  );
}
