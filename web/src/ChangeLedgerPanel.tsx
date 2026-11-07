import { useEffect, useRef, useState } from "react";
import { NativeBatchBundleInspection } from "./NativeBatchBundleInspection";
import { EncodedAnalogTerminalSummary, NativeEncodedAnalogLedgerView } from "./NativeEncodedAnalogLedgerView";
import { recordedEncodedAnalogTerminal } from "./nativeEncodedAnalogLedger";
import { recordedEncodedAnalogRecovery } from "./nativeEncodedAnalogRecoveryLedger";
import { EncodedAnalogRecoverySummary, NativeEncodedAnalogRecoveryLedgerView } from "./NativeEncodedAnalogRecoveryLedgerView";
import { BinaryTerminalSummary, NativeBinaryTerminalLedgerView } from "./NativeBinaryTerminalLedgerView";
import { recordedBinaryTerminal } from "./nativeBinaryTerminalLedger";
import { recordedBinaryTerminalRecoveryRow } from "./nativeBinaryTerminalRecoveryLedger";
import { BinaryTerminalRecoverySummary, NativeBinaryTerminalRecoveryLedgerView } from "./NativeBinaryTerminalRecoveryLedgerView";
import { api, apiBlobDocument, saveBlob } from "./api";
import {
  controllerKey,
  type CafDocument,
  type ControllerContext,
} from "./workflow";
import "./change-ledger.css";
import { recordedInput, inputAction } from "./nativeInputLedger";
import { recordedTerminal } from "./nativeTerminalLedger";
import {
  NativeTerminalLedgerView,
  TerminalSummary,
} from "./NativeTerminalLedgerView";
import {
  NativeTerminalRecoveryLedgerView,
  TerminalRecoverySummary,
} from "./NativeTerminalRecoveryLedgerView";
import { recordedPointName } from "./nativePointNameLedger";
import { recordedPointNameRecovery } from "./nativePointNameRecoveryLedger";
import { recordedConnection } from "./nativeConnectionLedger";
import { recordedDefaultBatch, NativeDefaultBatchLedgerView } from "./NativeDefaultBatchLedgerView";
import { recordedBatchRecovery } from "./nativeDefaultBatchRecoveryLedger";
import { NativeDefaultBatchRecoveryLedgerView } from "./NativeDefaultBatchRecoveryLedgerView";
import { recordedDefaultWire, NativeDefaultWireLedgerView } from "./NativeDefaultWireLedgerView";
import {
  recordedEnumRecovery,
  ENUM_RECOVERY_UNAVAILABLE,
  type RecordedEnumRecovery,
} from "./nativeEnumRecoveryLedger";

export type LedgerSource =
  | "audit"
  | "native"
  | "instance"
  | "schedule"
  | "bbmd"
  | "event"
  | "temco"
  | "command";
type Cursor = {
  before: Partial<Record<LedgerSource, string>>;
  exhausted: LedgerSource[];
};
type RecordedRecovery = {
  state: "recorded";
  parent_receipt_id: string;
  record_ref: string;
  verified_proof: { kind: "result" | "readback-event"; time: string };
  scope: string;
};
type NativeRecovery =
  | RecordedEnumRecovery
  | (RecordedRecovery & {
      datatype: "ObjectIdentifier";
      before_instance: number;
      after_instance: number;
      unchanged_name: string;
    })
  | (RecordedRecovery & {
      datatype: "CharacterString";
      instance: number;
      before_value: string;
      after_value: string;
    })
  | (RecordedRecovery & {
      datatype?: "Real";
      before_bits: string;
      after_bits: string;
      before_value: number;
      after_value: number;
    })
  | (RecordedRecovery & {
      datatype: "Boolean";
      before_tag: string;
      after_tag: string;
      before_value: boolean;
      after_value: boolean;
    })
  | (RecordedRecovery & {
      datatype: "Wire";
      wire_index: number;
      before_source_ref: string;
      after_source_ref: string;
      before_tuple: number[];
      after_tuple: number[];
      target_ref: string;
      historical_pin?: {
        source_ref: string;
        source_port: number;
        source_class: number;
        original_capture_id: string;
        scope: string;
      };
    })
  | { state: "unavailable"; scope: string };
type Row = {
  key: string;
  source: LedgerSource;
  id: string;
  label: string;
  native_change_kind?: string | null;
  native_reference_issue?: string;
  native_wire_index?: number;
  native_recovery?: NativeRecovery;
  native_input?: unknown;
  native_terminal?: unknown;
  native_binary_terminal?: unknown;
  native_binary_terminal_recovery?: unknown;
  native_encoded_analog_terminal?: unknown;
  native_encoded_analog_recovery?: unknown;
  native_terminal_recovery?: unknown;
  native_point_name?: unknown;
  native_connection?: unknown;
  native_default_wire?: unknown;
  native_default_batch?: unknown;
  native_default_batch_recovery?: unknown;
  native_point_name_recovery?: unknown;
  created_at: string;
  state: string;
  outcome: "attention" | "verified" | "other";
  kind: "audit" | "receipt" | "ownership";
  target: {
    address: string;
    device: string;
    router: string | null;
    dnet: number | null;
  } | null;
  object: string;
  local_source: string;
  pending: boolean;
  integrity: string;
  detail_path: string;
  session_scoped: boolean;
  review_recorded: boolean;
  dispatch: string;
  readback: string;
  interface_label?: string;
};
type Report = {
  rows: Row[];
  errors: { source: string; id?: string; error: string }[];
  captured_at: string;
  next_cursor: Cursor | null;
  coverage: { source: string; read: number; more: boolean }[];
  window_per_source: number;
  scope: string;
};
const sources: { id: LedgerSource; label: string; tool?: string }[] = [
  { id: "audit", label: "Audit events" },
  {
    id: "native",
    label: "Native application transfers",
    tool: "Open identity tools",
  },
  { id: "instance", label: "Instance changes", tool: "Open identity tools" },
  { id: "schedule", label: "Schedule writes", tool: "Open schedule tools" },
  { id: "bbmd", label: "BBMD administration", tool: "Open BBMD tools" },
  { id: "event", label: "Event acknowledgements", tool: "Open event tools" },
  {
    id: "temco",
    label: "Temco program operations",
    tool: "Open Temco transfer tools",
  },
  { id: "command", label: "Owned commands", tool: "Open owned commands" },
];
const outcomeText = (row: Row) =>
  row.outcome === "attention"
    ? "Needs attention"
    : row.outcome === "verified"
      ? "Observed / verified"
      : "Recorded outcome";
const realText = (value: number) =>
  Object.is(value, -0) ? "-0" : String(value);
function Target({ row }: { row: Row }) {
  if (!row.target)
    return (
      <span>
        {row.local_source
          ? `Local source ${row.local_source}`
          : "Target not recorded"}
      </span>
    );
  return (
    <>
      <strong>{row.target.address}</strong>
      <span>{row.target.device || "Device ID not recorded"}</span>
      {row.target.router && (
        <span>
          Router {row.target.router} · Network{" "}
          {row.target.dnet ?? "not recorded"}
        </span>
      )}
      {row.interface_label && <span>{row.interface_label}</span>}
    </>
  );
}
function InputSummary({ value }: { value: unknown }) {
  const input = recordedInput(value);
  return input ? (
    <span>
      {inputAction(input)} · {input.terminal_label}
      {input.requested_name && ` · ${input.requested_name}`}
    </span>
  ) : null;
}
function PointNameSummary({ value }: { value: unknown }) {
  const point = recordedPointName(value);
  return point ? (
    <span>
      Recorded name: {JSON.stringify(point.before)} →{" "}
      {JSON.stringify(point.after)}
    </span>
  ) : null;
}
function PointNameRecoverySummary({ row }: { row: Row }) {
  if (row.native_point_name_recovery === undefined) return null;
  const value = recordedPointNameRecovery(
    row.native_point_name_recovery,
    recordedPointName(row.native_point_name),
    row.id,
    row.target?.device,
  );
  return (
    <span>
      {value
        ? "Previous point-name recovery · parent " + value.parent_receipt_id
        : "Point-name recovery metadata unavailable"}
    </span>
  );
}

export function ChangeLedgerPanel({
  controller,
  cafDocument,
  graph,
  onOpenDraft,
  onOpenTool,
}: {
  controller: ControllerContext | null;
  cafDocument: CafDocument | null;
  graph: { id: string; name: string; revision: number } | null;
  onOpenDraft: (kind: "caf" | "graph") => void;
  onOpenTool: (source: LedgerSource, nativeChangeKind?: string) => void;
}) {
  const [source, setSource] = useState("all");
  const [outcome, setOutcome] = useState("all");
  const [scope, setScope] = useState("all");
  const [search, setSearch] = useState("");
  const [text, setText] = useState("");
  const [refresh, setRefresh] = useState(0);
  const context = controller
    ? [
        controllerKey(controller),
        controller.interfaceKey,
        controller.interfaceOpen,
      ]
    : null;
  const filterKey = JSON.stringify([source, outcome, scope, text, context]);
  const [page, setPage] = useState<{
    filterKey: string;
    cursor: Cursor | null;
    trail: (Cursor | null)[];
  }>({ filterKey: "", cursor: null, trail: [] });
  const activePage =
    page.filterKey === filterKey
      ? page
      : { filterKey, cursor: null, trail: [] };
  const key = JSON.stringify([filterKey, activePage.cursor, refresh]);
  const generation = useRef({ key, value: 0 });
  if (generation.current.key !== key)
    generation.current = { key, value: generation.current.value + 1 };
  const [result, setResult] = useState<{
    key: string;
    report?: Report;
    error?: string;
    busy: boolean;
  } | null>(null);
  const [selected, setSelected] = useState<{ key: string; row: Row } | null>(
    null,
  );
  const [detail, setDetail] = useState<{
    key: string;
    rowKey: string;
    blob?: Blob;
    text?: string;
    error?: string;
  } | null>(null);
  const detailGeneration = useRef(0);
  useEffect(() => {
    let retired = false;
    const epoch = generation.current.value;
    setResult({ key, busy: true });
    setSelected(null);
    setDetail(null);
    detailGeneration.current++;
    if (scope === "station" && !controller) {
      setResult({
        key,
        busy: false,
        error:
          "Open a controller before filtering by its original station and route. All local records remain available.",
      });
      return;
    }
    api("/changes/query", {
      source,
      outcome,
      text,
      ...(activePage.cursor || {}),
      ...(scope === "station" && controller
        ? {
            selected_target: {
              address: controller.address,
              device: controller.device,
              router: controller.router ?? null,
              dnet: controller.dnet ?? null,
              interface_key: controller.interfaceKey,
            },
          }
        : {}),
    })
      .then((report: Report) => {
        if (!retired && epoch === generation.current.value) {
          const rows = report.rows.map((row) =>
            row.native_recovery !== undefined &&
            (row.native_change_kind === "enum-default" ||
              (row.native_recovery?.state === "recorded" &&
                row.native_recovery.datatype === "Enumerated"))
              ? {
                  ...row,
                  native_recovery: recordedEnumRecovery(
                    row.native_recovery,
                    row,
                  ) ?? {
                    state: "unavailable" as const,
                    scope: ENUM_RECOVERY_UNAVAILABLE,
                  },
                }
              : row,
          );
          setResult({ key, report: { ...report, rows }, busy: false });
        }
      })
      .catch((error) => {
        if (!retired && epoch === generation.current.value)
          setResult({ key, error: String(error), busy: false });
      });
    return () => {
      retired = true;
      detailGeneration.current++;
    };
    // The immutable key includes all filters, source identity and cursor fields.
  }, [key]);
  const current = result?.key === key ? result : null;
  const report = current?.report;
  const choice = selected?.key === key ? selected.row : null;
  const evidence =
    choice && detail?.key === key && detail.rowKey === choice.key
      ? detail
      : null;
  async function openDetail(row: Row) {
    const ticket = ++detailGeneration.current,
      epoch = generation.current.value;
    setSelected({ key, row });
    setDetail(null);
    try {
      // Original source endpoints retain their own seals and number spelling.
      const document = await apiBlobDocument(row.detail_path);
      const raw = await document.blob.text();
      if (
        ticket === detailGeneration.current &&
        epoch === generation.current.value
      )
        setDetail({ key, rowKey: row.key, blob: document.blob, text: raw });
    } catch (error) {
      if (
        ticket === detailGeneration.current &&
        epoch === generation.current.value
      )
        setDetail({ key, rowKey: row.key, error: String(error) });
    }
  }
  function closeDetail() {
    detailGeneration.current++;
    setSelected(null);
    setDetail(null);
  }
  const sourceInfo = sources.find((s) => s.id === choice?.source);
  const binaryRecoveryPresent = choice?.native_binary_terminal_recovery !== undefined;
  const binaryRecovery = choice?.source === "native"
    ? recordedBinaryTerminalRecoveryRow(choice)
    : null;
  const nativeKind =
    choice?.native_change_kind === undefined
      ? "instance"
      : typeof choice.native_change_kind === "string"
        ? choice.native_change_kind
        : "unsupported";
  const batchRecovery = recordedBatchRecovery(choice);
  const nativeProgram =
    choice?.source === "native" && !binaryRecoveryPresent &&
    (["signal-default", "boolean-default", "wire-source", "execution-order"].includes(
      nativeKind,
    ) ||
      (nativeKind === "connection" &&
        !!recordedConnection(choice.native_connection)) ||
      (nativeKind === "default-wire" && !!recordedDefaultWire(choice.native_default_wire)) ||
      (nativeKind === "default-batch" &&
        (choice.native_default_batch_recovery !== undefined
          ? !!batchRecovery
          : !!recordedDefaultBatch(choice.native_default_batch))));
  const defaultBatch = choice?.source === "native" && !binaryRecoveryPresent && nativeKind === "default-batch" && choice.native_default_batch_recovery === undefined
    ? recordedDefaultBatch(choice.native_default_batch) : null;
  const combined = choice?.source === "native" && !binaryRecoveryPresent && nativeKind === "default-wire"
    ? recordedDefaultWire(choice.native_default_wire) : null;
  const connection =
    choice?.source === "native" && !binaryRecoveryPresent
      ? recordedConnection(choice.native_connection)
      : null;
  const input =
    choice?.source === "native" && !binaryRecoveryPresent && choice.native_terminal === undefined && choice.native_binary_terminal === undefined && choice.native_encoded_analog_terminal === undefined && choice.native_encoded_analog_recovery === undefined
      ? recordedInput(choice.native_input)
      : null;
  const terminal =
    choice?.source === "native" && !binaryRecoveryPresent && nativeKind === "input" && choice.native_binary_terminal === undefined && choice.native_encoded_analog_terminal === undefined && choice.native_encoded_analog_recovery === undefined
      ? recordedTerminal(choice.native_terminal)
      : null;
  const binaryTerminal = choice?.source === "native" && nativeKind === "input" && choice.native_encoded_analog_terminal === undefined && choice.native_encoded_analog_recovery === undefined ? recordedBinaryTerminal(choice.native_binary_terminal) : null;
  const encodedAnalogTerminal = choice?.source === "native" && !binaryRecoveryPresent && nativeKind === "input" ? recordedEncodedAnalogTerminal(choice.native_encoded_analog_terminal) : null;
  const encodedAnalogRecovery = choice?.source === "native" && !binaryRecoveryPresent && nativeKind === "input"
    ? recordedEncodedAnalogRecovery(choice.native_encoded_analog_recovery, choice.native_encoded_analog_terminal, choice.id, choice.target?.device)
    : null;
  const pointName =
    choice?.source === "native" && !binaryRecoveryPresent
      ? recordedPointName(choice.native_point_name)
      : null;
  const pointRecovery = choice && !binaryRecoveryPresent
    ? recordedPointNameRecovery(
        choice.native_point_name_recovery,
        pointName,
        choice.id,
        choice.target?.device,
      )
    : null;
  const unsupportedNative =
    (choice?.source === "native" && binaryRecoveryPresent && !binaryRecovery) ||
    (choice?.source === "native" && choice.native_encoded_analog_recovery !== undefined && !encodedAnalogRecovery) ||
    (choice?.source === "native" &&
      ![
        "instance",
        "name",
        "signal-default",
        "boolean-default",
        "wire-source",
        "default-wire",
        "default-batch",
        "connection",
        "execution-order",
        "input",
        "point-name",
      ].includes(nativeKind)) ||
    (choice?.source === "native" &&
      nativeKind === "input" &&
      !input &&
      !terminal && !binaryTerminal && !encodedAnalogTerminal) ||
    (choice?.source === "native" &&
      nativeKind === "point-name" &&
      !pointName) ||
    (choice?.source === "native" && nativeKind === "connection" && !connection) ||
    (choice?.source === "native" && nativeKind === "default-wire" && !combined) ||
    (choice?.source === "native" && nativeKind === "default-batch" && !defaultBatch && !batchRecovery);
  const toolLabel = unsupportedNative
    ? undefined
    : pointName
      ? "Open point tools"
      : input || terminal || binaryTerminal || encodedAnalogTerminal
        ? "Open input tools"
        : nativeProgram
          ? "Open native program tools"
          : sourceInfo?.tool;
  const needsController =
    choice &&
    !!toolLabel &&
    !nativeProgram &&
    ["native", "instance", "schedule", "event"].includes(choice.source) &&
    !input &&
    !terminal && !binaryTerminal && !encodedAnalogTerminal;
  function searchParent(id: string) {
    setSource("native");
    setOutcome("all");
    setScope("all");
    setSearch(id);
    setText(id);
    setPage({ filterKey: "", cursor: null, trail: [] });
    setRefresh((value) => value + 1);
  }
  return (
    <section className="panel change-ledger" aria-label="Change ledger">
      <header className="change-ledger-heading">
        <div>
          <h2>Change ledger</h2>
          <p>
            Local drafts and recorded operations. Refreshing this list sends no
            field requests.
          </p>
        </div>
      </header>
      <NativeBatchBundleInspection contextKey={JSON.stringify([context, cafDocument?.sha256, cafDocument?.name, graph?.id, graph?.revision])} />
      {(cafDocument || graph) && (
        <section aria-label="Local work" className="change-ledger-local">
          <h3>Local work</h3>
          <table>
            <thead>
              <tr>
                <th>Source</th>
                <th>State</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {cafDocument && (
                <tr>
                  <td>
                    <strong>{cafDocument.name}</strong>
                    <span>
                      CAF file · {cafDocument.model || "Model not recorded"} ·{" "}
                      {cafDocument.release || "Release not recorded"}
                    </span>
                  </td>
                  <td>
                    {cafDocument.dirty
                      ? `${cafDocument.changes} local changes${cafDocument.structuralDirty ? " including hardware edits" : ""}`
                      : "No pending local CAF changes"}
                    <span>Saving a copy does not write to a controller.</span>
                  </td>
                  <td>
                    <button onClick={() => onOpenDraft("caf")}>
                      Review CAF changes
                    </button>
                  </td>
                </tr>
              )}
              {graph && (
                <tr>
                  <td>
                    <strong>{graph.name}</strong>
                    <span>Local graph · {graph.id}</span>
                  </td>
                  <td>
                    {graph.revision === 0
                      ? "No saved revision"
                      : `Based on saved revision ${graph.revision}`}
                    <span>Inspect current edits in Program before saving.</span>
                  </td>
                  <td>
                    <button onClick={() => onOpenDraft("graph")}>
                      Open local graph
                    </button>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </section>
      )}
      <form
        className="change-ledger-filters"
        onSubmit={(event) => {
          event.preventDefault();
          setText(search.trim());
          setPage({ filterKey: "", cursor: null, trail: [] });
          setRefresh((v) => v + 1);
        }}
      >
        <label>
          Search recorded changes
          <input
            type="search"
            maxLength={200}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Operation, station, object or receipt ID"
          />
        </label>
        <label>
          Record family
          <select
            aria-label="Record family"
            value={source}
            onChange={(event) => setSource(event.target.value)}
          >
            <option value="all">All record families</option>
            {sources.map((s) => (
              <option key={s.id} value={s.id}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Recorded outcome
          <select
            aria-label="Recorded outcome"
            value={outcome}
            onChange={(event) => setOutcome(event.target.value)}
          >
            <option value="all">All outcomes</option>
            <option value="attention">Needs attention</option>
            <option value="verified">Observed / verified</option>
            <option value="other">Other recorded outcomes</option>
          </select>
        </label>
        <label>
          Target scope
          <select
            aria-label="Target scope"
            value={scope}
            onChange={(event) => setScope(event.target.value)}
          >
            <option value="all">All original targets</option>
            <option value="station" disabled={!controller}>
              Selected station and original route
            </option>
          </select>
        </label>
        <button type="submit" className="primary" disabled={current?.busy}>
          Refresh ledger
        </button>
      </form>
      <p className="change-ledger-scope">
        Each adapter keeps its own review, dispatch and recovery rules. This
        list is not a batch operation or a current controller-health check.
        Owned commands require explicit release. BBMD state observation does not
        prove who changed it.
      </p>
      {scope === "station" && controller && (
        <p>
          Filtering by {controller.address}
          {controller.router
            ? ` via ${controller.router}, network ${controller.dnet}`
            : ""}
          . Historical Device IDs may differ after an instance change. Serial
          MAC matching also requires the original interface identity;
          unqualified records remain in All original targets.
        </p>
      )}
      {(current?.busy || !current) && (
        <p role="status">Reading local change records…</p>
      )}
      {current?.error && (
        <p className="error" role="alert">
          {current.error}
        </p>
      )}
      {report && (
        <>
          <p role="status">
            {report.rows.length} records in this window · Captured{" "}
            {report.captured_at}. Search and filters cover at most{" "}
            {report.window_per_source} records per family in this window. Older
            windows may contain more matches.
          </p>
          {report.errors.length > 0 && (
            <div className="change-ledger-warning" role="alert">
              <strong>Some local evidence is unavailable.</strong>
              <ul>
                {report.errors.map((error, index) => (
                  <li key={index}>
                    {error.source}
                    {error.id ? ` · ${error.id}` : ""}: {error.error}
                  </li>
                ))}
              </ul>
              <p>
                Other records remain available. Inspect the original tool or
                refresh after resolving the local journal issue.
              </p>
            </div>
          )}
          <div
            className="change-ledger-table"
            role="region"
            aria-label="Recorded changes"
            tabIndex={0}
          >
            <table>
              <thead>
                <tr>
                  <th>Recorded time</th>
                  <th>Operation and source</th>
                  <th>Original target / local source</th>
                  <th>Outcome</th>
                  <th>Evidence</th>
                </tr>
              </thead>
              <tbody>
                {report.rows.map((row) => (
                  <tr key={row.key}>
                    <td>{row.created_at || "Not recorded"}</td>
                    <td>
                      <strong>{row.label}</strong>
                      <span>
                        {row.source} · {row.kind} · {row.id}
                      </span>
                      {row.object && <span>{row.object}</span>}
                      {row.native_wire_index !== undefined && (
                        <span>
                          Connection {row.native_wire_index + 1} · wire index{" "}
                          {row.native_wire_index}
                        </span>
                      )}
                      {row.native_reference_issue && (
                        <span>{row.native_reference_issue}</span>
                      )}
                      {row.native_binary_terminal_recovery === undefined && row.native_terminal === undefined && row.native_binary_terminal === undefined && row.native_encoded_analog_terminal === undefined && row.native_encoded_analog_recovery === undefined && (
                        <InputSummary value={row.native_input} />
                      )}
                      {row.native_binary_terminal_recovery === undefined && row.native_binary_terminal === undefined && row.native_encoded_analog_terminal === undefined && row.native_encoded_analog_recovery === undefined && <TerminalSummary value={row.native_terminal} />}
                      {row.native_encoded_analog_terminal === undefined && row.native_encoded_analog_recovery === undefined && <BinaryTerminalSummary value={row.native_binary_terminal} />}
                      {row.native_binary_terminal_recovery === undefined && <EncodedAnalogTerminalSummary value={row.native_encoded_analog_terminal} />}
                      {row.native_binary_terminal_recovery === undefined && <EncodedAnalogRecoverySummary row={row} />}
                      <BinaryTerminalRecoverySummary row={row} />
                      {row.native_binary_terminal_recovery === undefined && row.native_encoded_analog_terminal === undefined && row.native_encoded_analog_recovery === undefined && <TerminalRecoverySummary row={row} />}
                      {row.native_binary_terminal_recovery === undefined && <PointNameSummary value={row.native_point_name} />}
                      {row.native_binary_terminal_recovery === undefined && row.native_connection !== undefined && (
                        <span>
                          {recordedConnection(row.native_connection)
                            ? `Matching connection · ${recordedConnection(row.native_connection)!.connection_count_before} → ${recordedConnection(row.native_connection)!.connection_count_after}`
                            : "Connection metadata unavailable"}
                        </span>
                      )}
                      {row.native_default_batch_recovery !== undefined ? (
                        <span>
                          {recordedBatchRecovery(row)
                            ? `Previous batch recovery · parent ${recordedBatchRecovery(row)!.origin.parent_receipt_id}`
                            : "Batch recovery metadata unavailable"}
                        </span>
                      ) : row.native_default_batch !== undefined && <span>{recordedDefaultBatch(row.native_default_batch) ? "Recorded typed defaults" : "Batch metadata unavailable"}</span>}
                      {row.native_default_wire !== undefined && <span>{recordedDefaultWire(row.native_default_wire) ? "Recorded default and connection" : "Combined metadata unavailable"}</span>}
                      {row.native_binary_terminal_recovery === undefined && <PointNameRecoverySummary row={row} />}
                      {row.native_binary_terminal_recovery === undefined && row.native_encoded_analog_terminal === undefined && row.native_encoded_analog_recovery === undefined && row.native_recovery && (
                        <span>
                          {row.native_recovery.state === "recorded"
                            ? `${row.native_recovery.datatype === "Wire" ? "Previous wire source recovery" : row.native_recovery.datatype === "ObjectIdentifier" ? "Previous controller instance recovery" : row.native_recovery.datatype === "CharacterString" ? "Previous controller name recovery" : row.native_recovery.datatype === "Enumerated" ? "Previous Enum code recovery" : "Previous-value recovery"} · parent ${row.native_recovery.parent_receipt_id}`
                            : "Recovery metadata unavailable"}
                        </span>
                      )}
                      {row.session_scoped && (
                        <span>Session-scoped receipt</span>
                      )}
                    </td>
                    <td>
                      <Target row={row} />
                    </td>
                    <td>
                      <span className={`change-ledger-state ${row.outcome}`}>
                        {outcomeText(row)}
                      </span>
                      <span>{row.state}</span>
                      <span>Readback: {row.readback}</span>
                    </td>
                    <td>
                      <button
                        aria-label={`Details for ${row.source} ${row.id}`}
                        onClick={() => openDetail(row)}
                      >
                        Details
                      </button>
                    </td>
                  </tr>
                ))}
                {!report.rows.length && (
                  <tr>
                    <td colSpan={5}>
                      No matching records in this window. Check older windows or
                      change the filters.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <div className="change-ledger-pages">
            <button
              disabled={!activePage.trail.length || current?.busy}
              onClick={() =>
                setPage({
                  filterKey,
                  cursor: activePage.trail.at(-1) ?? null,
                  trail: activePage.trail.slice(0, -1),
                })
              }
            >
              Previous window
            </button>
            <span>Window {activePage.trail.length + 1}</span>
            <button
              disabled={!report.next_cursor || current?.busy}
              onClick={() =>
                setPage({
                  filterKey,
                  cursor: report.next_cursor,
                  trail: [...activePage.trail, activePage.cursor],
                })
              }
            >
              Older window
            </button>
          </div>
        </>
      )}
      {choice && (
        <section className="change-ledger-detail" aria-label="Change evidence">
          <div className="change-ledger-heading">
            <h3>{choice.label}</h3>
            <button onClick={closeDetail}>Close evidence</button>
          </div>
          <p className="change-ledger-original">
            <Target row={choice} />
          </p>
          <dl>
            <dt>Receipt / event</dt>
            <dd>
              {choice.source} · {choice.id}
            </dd>
            {nativeProgram && (
              <>
                <dt>Native edit reference</dt>
                <dd>
                  {choice.object ||
                    choice.native_reference_issue ||
                    "Not recorded"}
                </dd>
              </>
            )}
            {choice.native_wire_index !== undefined && (
              <>
                <dt>Native wire index</dt>
                <dd>
                  {choice.native_wire_index} · connection{" "}
                  {choice.native_wire_index + 1}
                </dd>
              </>
            )}
            <dt>Recorded outcome</dt>
            <dd>
              {outcomeText(choice)} · {choice.state}
            </dd>
            <dt>Review evidence</dt>
            <dd>
              {choice.review_recorded
                ? "Review hash recorded"
                : "Consult source evidence"}
            </dd>
            <dt>Dispatch</dt>
            <dd>{choice.dispatch}</dd>
            <dt>Readback</dt>
            <dd>{choice.readback}</dd>
            <dt>Integrity scope</dt>
            <dd>{choice.integrity}</dd>
          </dl>
          {choice.native_reference_issue && (
            <p>{choice.native_reference_issue}</p>
          )}
          {!binaryRecoveryPresent && nativeKind === "default-batch" && (
            choice.native_default_batch_recovery !== undefined ? (
              <NativeDefaultBatchRecoveryLedgerView row={choice} onParent={searchParent} />
            ) : defaultBatch ? <NativeDefaultBatchLedgerView data={defaultBatch} /> : <p>Batch metadata is unavailable. Inspect the original evidence.</p>
          )}
          {!binaryRecoveryPresent && nativeKind === "default-wire" && (
            combined ? <NativeDefaultWireLedgerView data={combined} /> : <p>Combined native metadata is unavailable. Inspect the original evidence.</p>
          )}
          {!binaryRecoveryPresent && nativeKind === "connection" && (
            <section aria-label="Recorded native matching connection">
              <h4>
                {connection
                  ? "Recorded matching connection"
                  : "Connection metadata unavailable"}
              </h4>
              {connection ? (
                <>
                  <dl>
                    <dt>Native diagram</dt>
                    <dd>{connection.diagram_ref}</dd>
                    <dt>Source member</dt>
                    <dd>{connection.source_ref}</dd>
                    <dt>Destination member</dt>
                    <dd>{connection.target_ref}</dd>
                    <dt>Connection count</dt>
                    <dd>
                      {connection.connection_count_before} →{" "}
                      {connection.connection_count_after}
                    </dd>
                    <dt>Recorded prototype index</dt>
                    <dd>{connection.prototype_index}</dd>
                    <dt>Added native tuple</dt>
                    <dd>{connection.new.join(", ")}</dd>
                    <dt>Connection confirmation recorded</dt>
                    <dd>
                      {connection.connection_confirmation_recorded
                        ? "Yes"
                        : "No"}
                    </dd>
                  </dl>
                  <p>{connection.scope}</p>
                  <p>
                    Choose a current captured diagram before preparing a fresh
                    transfer review. Opening this record preserves the current
                    controller selection.
                  </p>
                  <details>
                    <summary>Recorded connection binding</summary>
                    <pre>{JSON.stringify(connection, null, 2)}</pre>
                  </details>
                </>
              ) : (
                <p>
                  Inspect the original receipt. The present graph and
                  original-backup availability are not established by this
                  metadata.
                </p>
              )}
            </section>
          )}
          {!binaryRecoveryPresent && nativeKind === "point-name" && (
            <section aria-label="Recorded native point name">
              <h4>
                {pointName
                  ? "Recorded point-name proposal"
                  : "Point-name metadata unavailable"}
              </h4>
              {pointName ? (
                <>
                  <dl>
                    <dt>Recorded object</dt>
                    <dd>{pointName.object_id}</dd>
                    <dt>Native reference</dt>
                    <dd>{pointName.record_ref}</dd>
                    <dt>Before</dt>
                    <dd>
                      <code>{JSON.stringify(pointName.before)}</code>
                    </dd>
                    <dt>Requested after</dt>
                    <dd>
                      <code>{JSON.stringify(pointName.after)}</code>
                    </dd>
                    <dt>Native character encoding</dt>
                    <dd>{pointName.character_encoding}</dd>
                    <dt>Name confirmation recorded</dt>
                    <dd>
                      {pointName.name_confirmation_recorded ? "Yes" : "No"}
                    </dd>
                  </dl>
                  <p>{pointName.scope}</p>
                  <p>
                    Point tools open for the current selection. Choose a point
                    there before preparing a fresh change.
                  </p>
                  <details>
                    <summary>Recorded name binding hashes</summary>
                    <pre>
                      {JSON.stringify(
                        {
                          before_record_sha256: pointName.before_record_sha256,
                          compiled_native_sha256:
                            pointName.compiled_native_sha256,
                        },
                        null,
                        2,
                      )}
                    </pre>
                  </details>
                </>
              ) : (
                <p>
                  Inspect the original receipt. Current point names and
                  original-backup availability are not established here.
                </p>
              )}
            </section>
          )}
          {!binaryRecoveryPresent && nativeKind === "point-name" &&
            choice.native_point_name_recovery !== undefined && (
              <section aria-label="Recorded point name recovery lineage">
                <h4>
                  {pointRecovery
                    ? "Recorded previous point-name proposal"
                    : "Point-name recovery metadata unavailable"}
                </h4>
                {pointRecovery ? (
                  <>
                    <dl>
                      <dt>Parent receipt</dt>
                      <dd>{pointRecovery.parent_receipt_id}</dd>
                      <dt>Recorded point</dt>
                      <dd>
                        {pointRecovery.object_id} · {pointRecovery.record_ref} ·
                        device,{pointRecovery.instance}
                      </dd>
                      <dt>Recorded prior name</dt>
                      <dd>{JSON.stringify(pointRecovery.before)}</dd>
                      <dt>Requested previous name</dt>
                      <dd>{JSON.stringify(pointRecovery.after)}</dd>
                      <dt>Historical parent verification</dt>
                      <dd>
                        {pointRecovery.verified_proof.kind === "result"
                          ? "Original result"
                          : "Later readback event"}{" "}
                        · {pointRecovery.verified_proof.time}
                      </dd>
                    </dl>
                    <p>{pointRecovery.scope}</p>
                    <button
                      onClick={() =>
                        searchParent(pointRecovery.parent_receipt_id)
                      }
                    >
                      Search recorded point-name parent receipt
                    </button>
                    <details>
                      <summary>Recorded point-name recovery references</summary>
                      <pre>
                        {JSON.stringify(
                          {
                            parent_intent_sha256:
                              pointRecovery.parent_intent_sha256,
                            original_backup_id:
                              pointRecovery.original_backup_id,
                            original_snapshot_sha256:
                              pointRecovery.original_snapshot_sha256,
                            current_capture_id:
                              pointRecovery.current_capture_id,
                            current_snapshot_sha256:
                              pointRecovery.current_snapshot_sha256,
                            origin_sha256: pointRecovery.origin_sha256,
                            verified_proof: pointRecovery.verified_proof,
                          },
                          null,
                          2,
                        )}
                      </pre>
                    </details>
                  </>
                ) : (
                  <p>
                    Inspect original evidence. Parent/source availability,
                    current names and new transfer authority are not established
                    here.
                  </p>
                )}
              </section>
            )}
          {!binaryRecoveryPresent && nativeKind === "input" && choice.native_terminal !== undefined && choice.native_binary_terminal === undefined && choice.native_encoded_analog_terminal === undefined && choice.native_encoded_analog_recovery === undefined && (
            <NativeTerminalLedgerView value={choice.native_terminal} />
          )}
          {!binaryRecoveryPresent && nativeKind === "input" &&
            choice.native_binary_terminal === undefined && choice.native_encoded_analog_terminal === undefined && choice.native_encoded_analog_recovery === undefined &&
            choice.native_terminal_recovery !== undefined && (
              <NativeTerminalRecoveryLedgerView
                row={choice}
                onParent={searchParent}
              />
            )}
          {binaryRecoveryPresent && (
            <NativeBinaryTerminalRecoveryLedgerView row={choice} onParent={searchParent} />
          )}
          {nativeKind === "input" && choice.native_binary_terminal !== undefined && choice.native_encoded_analog_terminal === undefined && choice.native_encoded_analog_recovery === undefined && <NativeBinaryTerminalLedgerView value={choice.native_binary_terminal} />}
          {!binaryRecoveryPresent && nativeKind === "input" && choice.native_encoded_analog_terminal !== undefined && <NativeEncodedAnalogLedgerView value={choice.native_encoded_analog_terminal} />}
          {!binaryRecoveryPresent && nativeKind === "input" && choice.native_encoded_analog_recovery !== undefined && (
            <NativeEncodedAnalogRecoveryLedgerView row={choice} onParent={searchParent} />
          )}
          {!binaryRecoveryPresent && nativeKind === "input" && choice.native_terminal === undefined && choice.native_binary_terminal === undefined && choice.native_encoded_analog_terminal === undefined && choice.native_encoded_analog_recovery === undefined && (
            <section aria-label="Recorded native input configuration">
              <h4>
                {input ? inputAction(input) : "Input metadata unavailable"}
              </h4>
              {input ? (
                <>
                  <dl>
                    <dt>Recorded object</dt>
                    <dd>
                      {input.object_id} · {input.terminal_label}
                    </dd>
                    <dt>Native reference</dt>
                    <dd>{input.record_ref}</dd>
                    {input.requested_name && (
                      <>
                        <dt>Requested allocation name</dt>
                        <dd>{input.requested_name}</dd>
                      </>
                    )}
                    <dt>Wiring confirmation recorded</dt>
                    <dd>{input.wiring_confirmation_recorded ? "Yes" : "No"}</dd>
                  </dl>
                  <p>{input.scope}</p>
                  {input.requested_configuration &&
                    input.stored_configuration && (
                      <>
                        <p>
                          Electrical mode: {input.requested_configuration.mode}.
                          Engineering values use the recorded native unit code.
                        </p>
                        <div className="change-ledger-table">
                          <table>
                            <caption>
                              Requested and compiled input configuration
                            </caption>
                            <thead>
                              <tr>
                                <th>Field</th>
                                <th>Requested</th>
                                <th>Compiled</th>
                              </tr>
                            </thead>
                            <tbody>
                              {[
                                ["input_low", "Electrical range low"],
                                ["input_high", "Electrical range high"],
                                ["output_low", "Engineering range low"],
                                ["output_high", "Engineering range high"],
                                ["units", "Engineering unit code"],
                                ["minimum", "Minimum present value"],
                                ["maximum", "Maximum present value"],
                              ].map(([key, label]) => (
                                <tr key={key}>
                                  <th>{label}</th>
                                  <td>
                                    {realText(
                                      input.requested_configuration![key],
                                    )}
                                  </td>
                                  <td>
                                    {realText(input.stored_configuration![key])}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </>
                    )}
                  {input.allocation_receipt_id && (
                    <>
                      <p>
                        Recorded allocation reference:{" "}
                        {input.allocation_receipt_id}. Its present availability
                        is not established here.
                      </p>
                      <button
                        onClick={() => {
                          setSource("native");
                          setScope("all");
                          setSearch(input.allocation_receipt_id!);
                          setText(input.allocation_receipt_id!);
                        }}
                      >
                        Search recorded allocation receipt
                      </button>
                    </>
                  )}
                </>
              ) : (
                <p>
                  Recorded input metadata is incomplete or inconsistent. Inspect
                  the original evidence; it grants no tool or transfer
                  authority.
                </p>
              )}
            </section>
          )}
          {!binaryRecoveryPresent && choice.native_encoded_analog_terminal === undefined && choice.native_encoded_analog_recovery === undefined && choice.native_recovery && (
            <section aria-label="Recorded native recovery lineage">
              <h4>Recorded recovery origin</h4>
              {choice.native_recovery.state === "recorded" && (
                <>
                  <dl>
                    <dt>Parent receipt</dt>
                    <dd>{choice.native_recovery.parent_receipt_id}</dd>
                    <dt>
                      {choice.native_recovery.datatype === "Wire"
                        ? "Recorded wire change"
                        : choice.native_recovery.datatype === "ObjectIdentifier"
                          ? "Recorded controller instance change"
                          : choice.native_recovery.datatype ===
                              "CharacterString"
                            ? "Recorded controller name change"
                            : choice.native_recovery.datatype === "Boolean"
                              ? "Recorded Boolean change"
                              : choice.native_recovery.datatype === "Enumerated"
                                ? "Recorded Enum code proposal"
                                : "Recorded Real change"}
                    </dt>
                    <dd>
                      {choice.native_recovery.record_ref} ·{" "}
                      {choice.native_recovery.datatype === "Wire" ? (
                        <>
                          Connection {choice.native_recovery.wire_index + 1}:{" "}
                          {choice.native_recovery.before_source_ref} to{" "}
                          {choice.native_recovery.after_source_ref} · tuples{" "}
                          {choice.native_recovery.before_tuple.join(", ")} to{" "}
                          {choice.native_recovery.after_tuple.join(", ")} ·
                          destination {choice.native_recovery.target_ref}
                        </>
                      ) : choice.native_recovery.datatype ===
                        "ObjectIdentifier" ? (
                        <>
                          Device {choice.native_recovery.before_instance} to{" "}
                          {choice.native_recovery.after_instance} ·{" "}
                          {choice.native_recovery.unchanged_name}
                        </>
                      ) : choice.native_recovery.datatype ===
                        "CharacterString" ? (
                        <>
                          {choice.native_recovery.before_value} to{" "}
                          {choice.native_recovery.after_value} · Device{" "}
                          {choice.native_recovery.instance}
                        </>
                      ) : choice.native_recovery.datatype === "Boolean" ? (
                        <>
                          {String(choice.native_recovery.before_value)} to{" "}
                          {String(choice.native_recovery.after_value)} · tags{" "}
                          {choice.native_recovery.before_tag} to{" "}
                          {choice.native_recovery.after_tag}
                        </>
                      ) : choice.native_recovery.datatype === "Enumerated" ? (
                        <>
                          {choice.native_recovery.before_value} to{" "}
                          {choice.native_recovery.after_value} · class{" "}
                          {choice.native_recovery.class_id} · property 3113.
                          Code meanings remain unverified.
                        </>
                      ) : (
                        <>
                          {realText(choice.native_recovery.before_value)} to{" "}
                          {realText(choice.native_recovery.after_value)} · bits{" "}
                          {choice.native_recovery.before_bits} to{" "}
                          {choice.native_recovery.after_bits}
                        </>
                      )}
                    </dd>
                    {choice.native_recovery.datatype === "Enumerated" && (
                      <>
                        <dt>Recorded current and proposed encodings</dt>
                        <dd>
                          <code>
                            {choice.native_recovery.before_encoding_hex}
                          </code>{" "}
                          to{" "}
                          <code>
                            {choice.native_recovery.after_encoding_hex}
                          </code>
                        </dd>
                        <dt>Historical previous and after encodings</dt>
                        <dd>
                          <code>
                            {choice.native_recovery.previous_encoding_hex}
                          </code>{" "}
                          ·{" "}
                          <code>
                            {choice.native_recovery.recorded_after_encoding_hex}
                          </code>
                        </dd>
                        <dt>Captured storage and state metadata</dt>
                        <dd>
                          {choice.native_recovery.saved_storage.bytes} bytes ·
                          numeric maximum{" "}
                          {choice.native_recovery.saved_storage.maximum_code} ·{" "}
                          {choice.native_recovery.states_text_encoded_sha256 ? (
                            <code>
                              {
                                choice.native_recovery
                                  .states_text_encoded_sha256
                              }
                            </code>
                          ) : (
                            "No encoded state metadata was recorded"
                          )}
                          . Numeric capacity does not establish allowed states.
                        </dd>
                      </>
                    )}
                    <dt>Historical verification</dt>
                    <dd>
                      {choice.native_recovery.verified_proof.kind === "result"
                        ? "Original result"
                        : "Later readback event"}{" "}
                      · {choice.native_recovery.verified_proof.time}
                    </dd>
                    {choice.native_recovery.datatype === "Wire" &&
                      choice.native_recovery.historical_pin && (
                        <>
                          <dt>Retained original output pin</dt>
                          <dd>
                            {choice.native_recovery.historical_pin.source_ref} ·
                            port{" "}
                            {choice.native_recovery.historical_pin.source_port}{" "}
                            · class{" "}
                            {choice.native_recovery.historical_pin.source_class}{" "}
                            · backup{" "}
                            {
                              choice.native_recovery.historical_pin
                                .original_capture_id
                            }
                            . {choice.native_recovery.historical_pin.scope}
                          </dd>
                        </>
                      )}
                  </dl>
                  <button
                    onClick={() => {
                      const origin = choice.native_recovery;
                      if (origin?.state === "recorded")
                        searchParent(origin.parent_receipt_id);
                    }}
                  >
                    Search recorded parent receipt
                  </button>
                </>
              )}
              <p>{choice.native_recovery.scope}</p>
            </section>
          )}
          <p>
            Evidence belongs to this original target. Opening a tool keeps the
            current workspace target and never applies, releases, retries or
            reconciles an operation.
          </p>
          {toolLabel && (
            <button
              disabled={!!needsController && !controller}
              onClick={() =>
                onOpenTool(
                  choice.source,
                  choice.source === "native" ? nativeKind : undefined,
                )
              }
            >
              {toolLabel}
            </button>
          )}
          {unsupportedNative && (
            <p>
              This native operation is unsupported by the ledger's tool links.
              Its original evidence remains available.
            </p>
          )}
          {needsController && !controller && (
            <p>
              {pointName
                ? "Open a controller and choose a point to use its current configuration tools. "
                : "Open the original controller to use its recovery tools. "}
              Saved evidence remains readable offline.
            </p>
          )}
          {!evidence && <p role="status">Loading local evidence…</p>}
          {evidence?.error && (
            <p className="error" role="alert">
              {evidence.error} Inspect the source tool; the recorded outcome has
              not been changed.
            </p>
          )}
          {evidence?.blob && (
            <>
              <p>
                {["native", "instance", "schedule", "bbmd", "event"].includes(
                  choice.source,
                )
                  ? "Original source endpoint response. Download preserves the HTTP response bytes."
                  : "Redacted local evidence view; this is not an original controller archive."}
              </p>
              <button
                onClick={() =>
                  saveBlob(
                    evidence.blob!,
                    `change-${choice.source}-${choice.id}.json`,
                  )
                }
              >
                Download evidence JSON
              </button>
              <details>
                <summary>Technical evidence</summary>
                <pre>{evidence.text}</pre>
              </details>
            </>
          )}
        </section>
      )}
    </section>
  );
}
