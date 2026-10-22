import { useEffect, useRef, useState } from "react";
import { Database, Download, FileSearch, RefreshCw, Save } from "lucide-react";
import { api, saveBlob } from "./api";
import "./bacnet-files.css";

type FileMetadata = {
  object_id: string;
  object_name: string;
  file_type: string;
  file_size: number;
  read_only: boolean;
  file_access_method: string;
  modification_date: { date: number[]; time: number[] };
  description: string | null;
  record_count: number | null;
  read_supported: boolean;
  read_reason: string;
  metadata_sha256: string;
};
type Inspection = {
  id: string;
  target: { address: string; device: string };
  inspected_at: string;
  device_identity: Record<string, string | number>;
  connector_config: Record<string, unknown>;
  configuration_files: string[];
  discovery_source: "configuration-files" | "object-list";
  advertised_files: string[];
  object_list_count: number | null;
  files: FileMetadata[];
};
type Capture = {
  id: string;
  target: { address: string; device: string; object_id: string };
  bytes: number;
  sha256: string;
  received_at: string;
  access_method: string;
  native_caf: false;
};
type Receipt = Capture & {
  metadata: FileMetadata;
  device_identity: Record<string, string | number>;
  connector_config: Record<string, unknown>;
  complete: boolean;
  consistency: string;
  record_boundaries: { record: number; offset: number; length: number }[];
  pages: number;
  read_at: string;
  discovery_source?: "configuration-files" | "object-list";
  configuration_files?: string[];
  advertised_files?: string[];
};
type Profile = {
  storage?: { durability: string; directory_flush: boolean };
  limits: {
    file_bytes: number;
    configuration_files: number;
    records: number;
    operation_seconds: number;
    request_gap_seconds: number;
    captures: number;
  };
};

export function BacnetFilesPanel({
  connected,
  defaultAddress,
  defaultDevice,
}: {
  connected: boolean;
  defaultAddress: string;
  defaultDevice: string;
}) {
  const [address, setAddress] = useState(defaultAddress);
  const [device, setDevice] = useState(defaultDevice);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [inspection, setInspection] = useState<Inspection | null>(null);
  const [captures, setCaptures] = useState<Capture[]>([]);
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [outcome, setOutcome] = useState("");
  const mounted = useRef(false);
  const active = useRef(false);
  const epoch = useRef(0);
  const refreshEpoch = useRef(0);
  const current = (request: number) =>
    mounted.current && request === epoch.current;

  useEffect(() => {
    mounted.current = true;
    void refresh();
    return () => {
      mounted.current = false;
      epoch.current++;
      refreshEpoch.current++;
    };
  }, []);
  useEffect(() => {
    epoch.current++;
    setInspection(null);
    setAddress(defaultAddress);
    setDevice(defaultDevice);
    setError("");
    setOutcome("");
  }, [connected, defaultAddress, defaultDevice]);

  function edit(change: () => void) {
    if (active.current) return;
    epoch.current++;
    setInspection(null);
    setError("");
    setOutcome("");
    change();
  }
  async function refresh(request?: number) {
    const generation = ++refreshEpoch.current;
    try {
      const [nextProfile, nextCaptures] = await Promise.all([
        api("/bacnet/files/status"),
        api("/bacnet/files/captures"),
      ]);
      if (
        mounted.current &&
        generation === refreshEpoch.current &&
        (request === undefined || current(request))
      ) {
        setProfile(nextProfile);
        setCaptures(nextCaptures);
      }
    } catch (error) {
      if (
        mounted.current &&
        generation === refreshEpoch.current &&
        (request === undefined || current(request))
      )
        setError(String(error));
    }
  }
  async function action(work: (request: number) => Promise<void>) {
    if (active.current) return;
    active.current = true;
    const request = ++epoch.current;
    setBusy(true);
    setError("");
    setOutcome("");
    try {
      await work(request);
    } catch (error) {
      if (current(request)) setError(String(error));
    } finally {
      active.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  async function inspect() {
    if (!connected) return;
    await action(async (request) => {
      if (!address.trim() || !device.trim())
        throw new Error(
          "Enter the explicit device address and Device object identifier.",
        );
      setInspection(null);
      const next = await api("/bacnet/files/inspect", {
        address: address.trim(),
        device: device.trim(),
      });
      if (current(request)) {
        setInspection(next);
        setOutcome(
          "Inspected advertised files. No file content was read or device backup session started.",
        );
      }
    });
  }
  async function readFile(metadata: FileMetadata) {
    if (!connected || !inspection) return;
    const inspected = inspection;
    await action(async (request) => {
      const next = await api("/bacnet/files/read", {
        inspection_id: inspected.id,
        object_id: metadata.object_id,
        metadata_sha256: metadata.metadata_sha256,
      });
      if (!current(request)) return;
      setReceipt(next);
      setOutcome(
        "Saved a complete opaque file capture locally. Native application recovery remains unverified.",
      );
      await refresh(request);
    });
  }
  async function openReceipt(id: string) {
    await action(async (request) => {
      const next = await api("/bacnet/files/captures/" + id);
      if (current(request)) setReceipt(next);
    });
  }
  async function exportCapture(capture: Capture) {
    await action(async (request) => {
      const response = await fetch(
        "/api/bacnet/files/captures/" + capture.id + "/export",
      );
      if (!response.ok) {
        const body = await response.json();
        throw new Error(
          typeof body.detail === "string"
            ? body.detail
            : JSON.stringify(body.detail),
        );
      }
      const blob = await response.blob();
      if (!current(request)) return;
      const recordMode = capture.access_method === "record-access";
      if (!recordMode) {
        const hash = await crypto.subtle.digest(
          "SHA-256",
          await blob.arrayBuffer(),
        );
        const actual = Array.from(new Uint8Array(hash), (value) =>
          value.toString(16).padStart(2, "0"),
        ).join("");
        if (blob.size !== capture.bytes || actual !== capture.sha256)
          throw new Error(
            "Downloaded stream bytes do not match the saved size and SHA-256 receipt.",
          );
      }
      if (!current(request)) return;
      saveBlob(blob, capture.id + (recordMode ? "-records.zip" : ".bin"));
      setOutcome(
        recordMode
          ? "Exported the verified record container, including the receipt and empty records."
          : "Exported exact stream bytes; browser SHA-256 matches the saved receipt.",
      );
    });
  }
  function exportReceipt() {
    if (active.current || !receipt) return;
    saveBlob(
      new Blob([JSON.stringify(receipt, null, 2)], {
        type: "application/json",
      }),
      receipt.id + "-receipt.json",
    );
  }

  return (
    <section
      className="card bacnet-files"
      aria-label="BACnet configuration files"
    >
      <div className="card-header">
        <h3>
          <Database size={18} /> Advertised controller files
        </h3>
        <button
          className="button"
          disabled={busy}
          onClick={() => void action(refresh)}
        >
          <RefreshCw size={15} /> Refresh saved files
        </button>
      </div>
      <div className="card-body">
        <p>
          Read existing File objects advertised by Device configuration-files,
          or its Object List when configuration-files is empty. Copies are
          opaque bytes, not CAF files or proof of a coherent application backup.
          This tool does not issue STARTBACKUP or any device write.
        </p>
        <div className="form-grid">
          <label>
            File device address
            <input
              aria-label="File device address"
              disabled={busy}
              value={address}
              placeholder="2105:79 or 192.168.1.10:47808"
              onChange={(event) => edit(() => setAddress(event.target.value))}
            />
          </label>
          <label>
            File Device object
            <input
              aria-label="File Device object"
              disabled={busy}
              value={device}
              placeholder="device,132079"
              onChange={(event) => edit(() => setDevice(event.target.value))}
            />
          </label>
          <div className="bacnet-file-action">
            <button
              className="button primary"
              disabled={busy || !connected}
              onClick={() => void inspect()}
            >
              <FileSearch size={16} /> Inspect advertised files
            </button>
          </div>
        </div>
        {!connected && (
          <p className="muted">
            Open a BACnet interface before inspecting or reading controller
            files. Saved captures remain available offline.
          </p>
        )}
        {profile && (
          <p className="muted">
            Bounded profile: {profile.limits.configuration_files} advertised
            files, {profile.limits.file_bytes.toLocaleString()} bytes per file,{" "}
            {profile.limits.records} records, {profile.limits.operation_seconds}
            s operation deadline, at least {profile.limits.request_gap_seconds}s
            between requests. Up to {profile.limits.captures} local captures; no
            automatic reads.
          </p>
        )}
        {profile?.storage && (
          <p className="muted" aria-label="File capture storage durability">
            Local capture storage: {profile.storage.durability}
          </p>
        )}
        {busy && <p role="status">Working on the requested file operation…</p>}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {outcome && (
          <p className="success" role="status">
            {outcome}
          </p>
        )}
        {inspection && (
          <section aria-label="Inspected configuration files">
            <h3>
              {inspection.target.device} · {inspection.target.address}
            </h3>
            <p className="muted">
              Inspected {inspection.inspected_at}. Metadata and connection
              identity are checked again before and after a read.
            </p>
            <dl className="bacnet-file-evidence">
              <dt>File discovery</dt>
              <dd>
                {inspection.discovery_source}
                {inspection.object_list_count !== null && (
                  <>
                    {" "}
                    · {inspection.object_list_count} Object List entries checked
                  </>
                )}
              </dd>
              <dt>Configuration files</dt>
              <dd>
                {inspection.configuration_files.length
                  ? inspection.configuration_files.join(", ")
                  : "Empty configuration-files list; listed files come from the Object List."}
              </dd>
              <dt>Advertised Files</dt>
              <dd>{inspection.advertised_files.join(", ") || "None"}</dd>
              <dt>Device</dt>
              <dd>{inspection.device_identity["object-name"]}</dd>
              <dt>Model / firmware</dt>
              <dd>
                {inspection.device_identity["model-name"]} /{" "}
                {inspection.device_identity["firmware-revision"]}
              </dd>
              <dt>Vendor / maximum APDU</dt>
              <dd>
                {inspection.device_identity["vendor-identifier"]} /{" "}
                {inspection.device_identity["max-apdu-length-accepted"]}
              </dd>
            </dl>
            {inspection.files.length === 0 ? (
              <p>
                No File objects advertised. No native application backup was
                obtained.
              </p>
            ) : (
              <div className="bacnet-file-table">
                <table>
                  <thead>
                    <tr>
                      <th>File object</th>
                      <th>Metadata</th>
                      <th>Guard</th>
                      <th>Read</th>
                    </tr>
                  </thead>
                  <tbody>
                    {inspection.files.map((row) => (
                      <tr key={row.object_id}>
                        <td>
                          <strong>{row.object_id}</strong>
                          <br />
                          {row.object_name}
                          <br />
                          <span className="muted">{row.description}</span>
                        </td>
                        <td>
                          {row.file_access_method}
                          <br />
                          {row.file_size} bytes
                          {row.record_count !== null && (
                            <> · {row.record_count} records</>
                          )}
                          <br />
                          {row.file_type}
                          <br />
                          Read-only property: {row.read_only ? "true" : "false"}
                        </td>
                        <td>
                          <code>{row.metadata_sha256}</code>
                          <br />
                          <span className="muted">{row.read_reason}</span>
                        </td>
                        <td>
                          <button
                            className="button"
                            disabled={busy || !connected || !row.read_supported}
                            onClick={() => void readFile(row)}
                            aria-label={"Read and save " + row.object_id}
                          >
                            <Save size={15} /> Read and save opaque file
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <details>
              <summary>
                Inspection evidence and connection configuration
              </summary>
              <pre>{JSON.stringify(inspection, null, 2)}</pre>
            </details>
          </section>
        )}
        <section aria-label="Saved BACnet file captures">
          <h3>Saved opaque captures · {captures.length}</h3>
          {captures.length === 0 ? (
            <p className="muted">No saved file captures.</p>
          ) : (
            <div className="bacnet-file-table">
              <table>
                <thead>
                  <tr>
                    <th>Source</th>
                    <th>Saved bytes</th>
                    <th>SHA-256</th>
                    <th>Local actions</th>
                  </tr>
                </thead>
                <tbody>
                  {captures.map((row) => (
                    <tr key={row.id}>
                      <td>
                        {row.target.address}
                        <br />
                        {row.target.device} · {row.target.object_id}
                        <br />
                        <span className="muted">{row.received_at}</span>
                      </td>
                      <td>
                        {row.bytes} · {row.access_method}
                      </td>
                      <td>
                        <code>{row.sha256}</code>
                      </td>
                      <td>
                        <div className="button-row">
                          <button
                            className="button"
                            disabled={busy}
                            onClick={() => void openReceipt(row.id)}
                            aria-label={"Open file receipt " + row.id}
                          >
                            Receipt
                          </button>
                          <button
                            className="button"
                            disabled={busy}
                            onClick={() => void exportCapture(row)}
                            aria-label={"Export opaque capture " + row.id}
                          >
                            <Download size={15} /> Export{" "}
                            {row.access_method === "record-access"
                              ? "records ZIP"
                              : "exact bytes"}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
        {receipt && (
          <section aria-label="BACnet file capture receipt">
            <div className="bacnet-file-heading">
              <h3>Capture receipt · {receipt.target.object_id}</h3>
              <button
                className="button"
                disabled={busy}
                onClick={exportReceipt}
              >
                <Download size={15} /> Download file receipt JSON
              </button>
            </div>
            <p>{receipt.consistency}</p>
            <dl className="bacnet-file-evidence">
              <dt>Capture</dt>
              <dd>
                <code>{receipt.id}</code>
              </dd>
              <dt>Source</dt>
              <dd>
                {receipt.target.device} · {receipt.target.address} ·{" "}
                {receipt.target.object_id}
              </dd>
              <dt>File discovery</dt>
              <dd>
                {receipt.discovery_source ??
                  "Not recorded in this older capture"}
                {receipt.configuration_files?.length === 0 &&
                  " · configuration-files was empty"}
              </dd>
              <dt>SHA-256</dt>
              <dd>
                <code>{receipt.sha256}</code>
              </dd>
              <dt>Transfer</dt>
              <dd>
                {receipt.bytes} bytes · {receipt.pages} pages ·{" "}
                {receipt.access_method} ·{" "}
                {receipt.complete
                  ? "complete within the opaque file profile"
                  : "incomplete"}
              </dd>
              <dt>Read / received</dt>
              <dd>
                {receipt.read_at} / {receipt.received_at}
              </dd>
            </dl>
            {receipt.record_boundaries.length > 0 && (
              <p>
                Record boundaries preserved: {receipt.record_boundaries.length},
                including{" "}
                {
                  receipt.record_boundaries.filter((row) => row.length === 0)
                    .length
                }{" "}
                empty records. Export ZIP contains the individual records and
                receipt; its ZIP bytes have a different hash from the
                concatenated source data.
              </p>
            )}
            <details>
              <summary>Complete capture receipt</summary>
              <pre>{JSON.stringify(receipt, null, 2)}</pre>
            </details>
          </section>
        )}
      </div>
    </section>
  );
}
