import "./native-backup-comparison.css";
import { useContext, useEffect, useRef, useState } from "react";
import { apiJsonDocument, saveBlob, type JsonDocument } from "./api";
import { NativeBooleanTransferContext } from "./NativeBooleanTransferContext";
import { controllerKey, type ControllerContext } from "./workflow";

type Data = Record<string, any>;
const endpoint = "/bacnet/controller/native-application/inspection/compare";
const profile = "native-backup-comparison/1";
const pageSize = 32;
const changeNames: Record<string, string> = {
  "record-added": "Record added",
  "record-removed": "Record removed",
  "record-class-changed": "Native class changed",
  "record-bytes-changed": "Record bytes changed",
  "property-added": "Property added",
  "property-removed": "Property removed",
  "property-encoding-changed": "Property encoding changed",
};
const hash = (value: unknown) =>
  typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const sourceTarget = (source: Data) => ({
  ...source.target,
  device: source.device,
});
const ownerSource = (source: Data | undefined) =>
  source && [source.id, source.evidence_sha256, sourceTarget(source)];
const scalar = (value: Data | null) => {
  if (!value) return "Absent";
  if (!value.scalar)
    return value.record_sha256
      ? `${value.class_name} · ${value.record_sha256.slice(0, 12)}`
      : `Structured or undecoded · ${value.encoded_bytes} bytes · ${value.encoded_sha256?.slice(0, 12)}`;
  const text = Object.is(value.scalar.value, -0)
    ? "-0.0"
    : String(value.scalar.value);
  return `${value.scalar.datatype} · ${text}${value.preview_truncated ? "… (preview)" : ""}`;
};

function validSource(actual: Data, expected: Data) {
  return (
    actual?.profile === "native-backup-record-inspection/1" &&
    actual.source_kind === "native-backup-archive" &&
    actual.capture_id === expected.id &&
    actual.snapshot_sha256 === expected.evidence_sha256 &&
    controllerKey(actual.target) === controllerKey(sourceTarget(expected)) &&
    actual.read_only === true &&
    actual.controller_queries === false &&
    actual.field_actions === false &&
    actual.identity_verified === false &&
    ["3", "11", "12"].every(
      (key) =>
        hash(actual.files?.[key]?.sha256) &&
        Number.isInteger(actual.files[key].bytes) &&
        actual.files[key].bytes >= 1 &&
        actual.files[key].bytes <= 2097152,
    ) &&
    actual.sha256 === actual.files["3"].sha256
  );
}

function validate(
  document: JsonDocument,
  left: Data,
  right: Data,
  query: string,
  offset: number,
) {
  const data = document.data;
  const kinds = [
    "record-added",
    "record-removed",
    "record-class-changed",
    "record-bytes-changed",
    "property-added",
    "property-removed",
    "property-encoding-changed",
  ];
  if (
    document.blob.size > 2097152 ||
    data?.profile !== profile ||
    data.source_kind !== "retained-native-backup-comparison" ||
    !validSource(data.left, left) ||
    !validSource(data.right, right) ||
    !hash(data.evidence_sha256) ||
    data.query !== query ||
    data.offset !== offset ||
    data.limit !== pageSize ||
    !Number.isInteger(data.total_matches) ||
    data.total_matches < 0 ||
    data.total_matches > 4096 ||
    !Array.isArray(data.rows) ||
    data.rows.length > pageSize ||
    data.rows.some(
      (row: Data) =>
        !kinds.includes(row.kind) ||
        typeof row.reference !== "string" ||
        row.reference.length > 512 ||
        !(
          row.property === null ||
          (Number.isSafeInteger(row.property) &&
            row.property >= 0 &&
            row.property <= 4294967295)
        ),
    ) ||
    !(
      data.next_offset === null ||
      (data.next_offset === offset + pageSize &&
        data.next_offset < data.total_matches)
    ) ||
    typeof data.structured_comparison?.supported !== "boolean" ||
    typeof data.structured_comparison.scan_complete !== "boolean" ||
    !Array.isArray(data.structured_comparison.reasons) ||
    (data.structured_comparison.scan_complete &&
      !data.structured_comparison.supported) ||
    !Array.isArray(data.files) ||
    data.files.length !== 3 ||
    data.files.some(
      (row: Data, i: number) =>
        row.file !== [3, 11, 12][i] ||
        typeof row.equal !== "boolean" ||
        row.left?.sha256 !== data.left.files?.[String(row.file)]?.sha256 ||
        row.right?.sha256 !== data.right.files?.[String(row.file)]?.sha256 ||
        row.left?.bytes !== data.left.files?.[String(row.file)]?.bytes ||
        row.right?.bytes !== data.right.files?.[String(row.file)]?.bytes ||
        row.equal !==
          (row.left.sha256 === row.right.sha256 &&
            row.left.bytes === row.right.bytes),
    ) ||
    data.read_only !== true ||
    data.controller_queries !== false ||
    data.field_actions !== false ||
    data.restore_plan !== false ||
    data.semantics_verified !== false
  ) {
    throw new Error(
      "Comparison evidence does not match the selected original backups and page. Compare again.",
    );
  }
}

export function NativeBackupComparison({
  selection,
  sources,
  controller,
  visible,
}: {
  selection: string;
  sources: Data[];
  controller?: ControllerContext | null;
  visible: boolean;
}) {
  const fieldBusy =
    useContext(NativeBooleanTransferContext)?.fieldBusy ?? false;
  const [expanded, setExpanded] = useState(false);
  const [rightId, setRightId] = useState("");
  const [query, setQuery] = useState("");
  const left = sources.find((row) => row.id === selection);
  const right = sources.find((row) => row.id === rightId);
  const owner = JSON.stringify([
    visible,
    expanded,
    ownerSource(left),
    ownerSource(right),
    query,
    fieldBusy,
    controller && [
      controllerKey(controller),
      controller.interfaceKey,
      controller.interfaceOpen,
    ],
  ]);
  const epoch = useRef(0),
    latest = useRef(owner),
    alive = useRef(true);
  if (latest.current !== owner) {
    latest.current = owner;
    epoch.current++;
  }
  const [result, setResult] = useState<{
    owner: string;
    epoch: number;
    document: JsonDocument;
  } | null>(null);
  const [pending, setPending] = useState<{
    owner: string;
    epoch: number;
  } | null>(null);
  const [failure, setFailure] = useState<{
    owner: string;
    epoch: number;
    text: string;
  } | null>(null);
  const current = (key: string, ticket: number) =>
    alive.current && latest.current === key && epoch.current === ticket;
  const shown =
    result?.owner === owner && result.epoch === epoch.current
      ? result.document
      : null;
  const busy = pending?.owner === owner && pending.epoch === epoch.current;
  const error =
    failure?.owner === owner && failure.epoch === epoch.current
      ? failure.text
      : "";
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      epoch.current++;
    };
  }, []);
  async function compare(offset = 0) {
    if (!visible || !expanded || !left || !right || fieldBusy) return;
    const key = latest.current,
      ticket = ++epoch.current;
    setResult(null);
    setFailure(null);
    setPending({ owner: key, epoch: ticket });
    try {
      const document = await apiJsonDocument(endpoint, {
        left: { capture_id: left.id, snapshot_sha256: left.evidence_sha256 },
        right: { capture_id: right.id, snapshot_sha256: right.evidence_sha256 },
        query,
        offset,
        limit: pageSize,
      });
      validate(document, left, right, query, offset);
      if (current(key, ticket))
        setResult({ owner: key, epoch: ticket, document });
    } catch (error) {
      if (current(key, ticket))
        setFailure({ owner: key, epoch: ticket, text: String(error) });
    } finally {
      if (current(key, ticket)) setPending(null);
    }
  }
  function invalidate() {
    epoch.current++;
    setResult(null);
    setFailure(null);
    setPending(null);
  }
  const data = shown?.data;
  return (
    <details
      className="native-records native-compiler-source native-backup-comparison"
      aria-label="Retained native backup comparison"
      open={expanded}
    >
      <summary
        onClick={(event) => {
          event.preventDefault();
          invalidate();
          setExpanded(!expanded);
        }}
      >
        Compare retained backups
      </summary>
      <p>
        Compare original archived bytes and recognized records locally. Saved
        settings are compared as files; this view prepares no controller change
        or restore.
      </p>
      {left ? (
        <p>
          Left backup: {left.identity?.["object-name"] || left.device} ·{" "}
          {left.target?.address} · captured {left.captured_at} ·{" "}
          <code>{left.id}</code>
        </p>
      ) : (
        <p>Select the left retained backup above.</p>
      )}
      <label>
        Right native backup
        <select
          aria-label="Right native backup"
          value={rightId}
          disabled={fieldBusy}
          onChange={(event) => {
            invalidate();
            setRightId(event.target.value);
          }}
        >
          <option value="">Select a retained backup</option>
          {sources.map((row) => (
            <option key={row.id} value={row.id}>
              {row.identity?.["object-name"] || row.device} ·{" "}
              {row.target?.address} · {row.captured_at} · {row.id.slice(0, 8)}
            </option>
          ))}
        </select>
      </label>
      <label>
        Search comparison evidence
        <input
          aria-label="Search native comparison"
          value={query}
          disabled={fieldBusy}
          onChange={(event) => {
            invalidate();
            setQuery(event.target.value);
          }}
          maxLength={256}
        />
      </label>
      <div className="button-row">
        <button
          className="primary"
          disabled={!left || !right || busy || fieldBusy}
          onClick={() => void compare()}
        >
          Compare original backups
        </button>
        <button
          disabled={!shown || busy || fieldBusy}
          onClick={() => {
            if (shown && result && current(result.owner, result.epoch))
              saveBlob(
                shown.blob,
                `native-backup-comparison-${left?.id}-${right?.id}.json`,
              );
          }}
        >
          Download comparison JSON
        </button>
      </div>
      {busy && <p role="status">Comparing retained original files…</p>}
      {error && <p role="alert">{error}</p>}
      {data && (
        <section aria-label="Native backup comparison results">
          <p>
            Historical archive comparison · {data.captured_at}. Current
            controller identity and compatibility remain unverified.
          </p>
          <div className="native-comparison-sources">
            {["left", "right"].map((side) => (
              <div key={side} aria-label={`${side} compared backup`}>
                <strong>
                  {side === "left" ? "Left" : "Right"}:{" "}
                  {data[side].identity?.["object-name"] ||
                    data[side].target.device}
                </strong>
                <p>
                  {data[side].target.device} at {data[side].target.address}
                  {data[side].target.router
                    ? ` via ${data[side].target.router} / DNET ${data[side].target.dnet}`
                    : ""}{" "}
                  · captured {data[side].captured_at}
                </p>
                {data[side].source_identity_error && (
                  <p role="status">
                    Recorded acquisition limitation:{" "}
                    {data[side].source_identity_error}
                  </p>
                )}
              </div>
            ))}
          </div>
          <div
            className="native-record-table"
            tabIndex={0}
            aria-label="Original file comparison scroll area"
          >
            <table aria-label="Original native backup files">
              <thead>
                <tr>
                  <th>File</th>
                  <th>Original bytes</th>
                  <th>Left bytes / SHA-256</th>
                  <th>Right bytes / SHA-256</th>
                </tr>
              </thead>
              <tbody>
                {data.files.map((row: Data) => (
                  <tr key={row.file}>
                    <td>{row.file}</td>
                    <td>{row.equal ? "Identical" : "Different"}</td>
                    <td>
                      {row.left.bytes} ·{" "}
                      <code title={row.left.sha256}>
                        {row.left.sha256.slice(0, 16)}
                      </code>
                    </td>
                    <td>
                      {row.right.bytes} ·{" "}
                      <code title={row.right.sha256}>
                        {row.right.sha256.slice(0, 16)}
                      </code>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p role="status">
            {!data.structured_comparison.supported
              ? "Structured record comparison unavailable. Original file comparison remains available."
              : data.structured_comparison.scan_complete
                ? "Recognized engineering record scan complete."
                : `Partial recognized-record scan: ${data.structured_comparison.budget_reason}`}
          </p>
          {data.structured_comparison.reasons.map(
            (reason: string, i: number) => (
              <p key={i}>{reason}</p>
            ),
          )}
          <p>
            Metadata record hash multisets:{" "}
            {data.structured_comparison.metadata_hash_multisets_equal === null
              ? "Unavailable"
              : data.structured_comparison.metadata_hash_multisets_equal
                ? "Identical"
                : "Different"}
            . Metadata records are not paired by offset or name.
          </p>
          {!data.rows.length && data.structured_comparison.supported && (
            <p>
              No engineering record/property encoding changes observed within
              this page and scan. File and metadata comparisons remain separate.
            </p>
          )}
          {!!data.rows.length && (
            <div
              className="native-record-table"
              tabIndex={0}
              aria-label="Native difference table scroll area"
            >
              <table aria-label="Native record and property differences">
                <thead>
                  <tr>
                    <th>Change</th>
                    <th>Engineering reference</th>
                    <th>Property</th>
                    <th>Left archive</th>
                    <th>Right archive</th>
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((row: Data, i: number) => (
                    <tr key={i}>
                      <td>{changeNames[row.kind]}</td>
                      <td>{row.reference}</td>
                      <td>
                        {row.property === null
                          ? row.name
                          : `${row.property} · ${row.name}`}
                      </td>
                      <td>{scalar(row.left)}</td>
                      <td>{scalar(row.right)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="button-row">
            <button
              disabled={busy || fieldBusy || data.offset === 0}
              onClick={() => void compare(Math.max(0, data.offset - pageSize))}
            >
              Previous comparison page
            </button>
            <span>
              {data.rows.length ? data.offset + 1 : 0}–
              {data.offset + data.rows.length} of {data.total_matches} observed
              matches
            </span>
            <button
              disabled={busy || fieldBusy || data.next_offset === null}
              onClick={() => void compare(data.next_offset)}
            >
              Next comparison page
            </button>
          </div>
          <details>
            <summary>Comparison scope and source evidence</summary>
            <p>{data.scope}</p>
            <p>Alignment: {data.structured_comparison.alignment}</p>
            <p>
              Recorded targets:{" "}
              {data.same_recorded_target
                ? "Same recorded address and Device"
                : "Different recorded targets"}
              . Recorded interfaces:{" "}
              {data.same_recorded_interface === null
                ? "Unknown"
                : data.same_recorded_interface
                  ? "Same captured configuration"
                  : "Different captured configurations"}
              .
            </p>
            <p>
              Evidence seal: <code>{data.evidence_sha256}</code>
            </p>
          </details>
        </section>
      )}
    </details>
  );
}
