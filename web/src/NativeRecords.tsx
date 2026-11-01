import {
  useContext,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import { NativeBooleanTransferContext } from "./NativeBooleanTransferContext";
import { api } from "./api";
import { controllerKey, type ControllerContext } from "./workflow";
import {
  NativeBooleanDefaultCopy,
  type BooleanCopyDrafts,
} from "./NativeBooleanDefaultCopy";

type Data = Record<string, any>;
const pageSize = 64;
export type NativeArchiveSource = {
  capture_id: string;
  snapshot_sha256: string;
  sha256: string;
  target: {
    address: string;
    device: string;
    router?: string | null;
    dnet?: number | null;
  };
};
type RecordSource =
  | {
      kind?: "controller-file";
      controller: ControllerContext;
      capture: { id: string; sha256: string };
    }
  | {
      kind: "native-backup";
      source: NativeArchiveSource;
      controller?: ControllerContext | null;
      visible: boolean;
      booleanDrafts?: BooleanCopyDrafts;
    };
function scrollTable(event: KeyboardEvent<HTMLDivElement>) {
  if (
    event.target !== event.currentTarget ||
    event.altKey ||
    event.ctrlKey ||
    event.metaKey ||
    event.shiftKey
  )
    return;
  if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
    event.preventDefault();
    event.currentTarget.scrollBy({
      left: event.key === "ArrowRight" ? 64 : -64,
    });
  }
}
const scalarText = (scalar: Data | null) => {
  if (!scalar) return "Structured or undecoded value";
  if (scalar.datatype === "Null") return "null";
  return Object.is(scalar.value, -0) ? "-0.0" : String(scalar.value);
};

export function NativeRecords(props: RecordSource) {
  const fieldBusy =
    useContext(NativeBooleanTransferContext)?.fieldBusy ?? false;
  const native = props.kind === "native-backup";
  const controller = props.controller;
  const capture = native
    ? { id: props.source.capture_id, sha256: props.source.sha256 }
    : props.capture;
  const base = native
    ? "/bacnet/controller/native-application/inspection/"
    : "/bacnet/controller/application/";
  const [inventoryState, setInventory] = useState<{
    data: Data;
    owner: string;
    generation: number;
  } | null>(null);
  const [detailState, setDetail] = useState<{
    data: Data;
    owner: string;
    generation: number;
  } | null>(null);
  const [query, setQuery] = useState("");
  const [propertyQuery, setPropertyQuery] = useState("");
  const [selected, setSelected] = useState("");
  const [busy, setBusy] = useState(false);
  const [detailBusy, setDetailBusy] = useState(false);
  const [error, setError] = useState("");
  const [detailError, setDetailError] = useState("");
  const listEpoch = useRef(0),
    detailEpoch = useRef(0);
  const owner = JSON.stringify([
    native
      ? ["native-backup", props.source.snapshot_sha256, props.visible]
      : "controller-file",
    capture.id,
    capture.sha256,
    controller && [
      controllerKey(controller),
      controller.interfaceKey,
      controller.interfaceOpen,
    ],
  ]);
  const ownerNow = useRef(owner);
  const ownerGeneration = useRef(0);
  if (ownerNow.current !== owner) {
    ownerNow.current = owner;
    ownerGeneration.current++;
    listEpoch.current++;
    detailEpoch.current++;
  }
  const inventory =
    inventoryState?.owner === owner &&
    inventoryState.generation === ownerGeneration.current
      ? inventoryState.data
      : null;
  const detail =
    detailState?.owner === owner &&
    detailState.generation === ownerGeneration.current
      ? detailState.data
      : null;
  const booleanDefault =
    native && detail?.record.ref && [530, 531].includes(detail.record.class_id)
      ? detail.properties.find(
          (prop: Data) =>
            prop.id === 3113 &&
            prop.scalar?.datatype === "Boolean" &&
            typeof prop.scalar.value === "boolean",
        )
      : null;
  useEffect(() => {
    setBusy(false);
    setDetailBusy(false);
    setError("");
    setDetailError("");
    setQuery("");
    setPropertyQuery("");
    setSelected("");
  }, [owner]);
  useEffect(
    () => () => {
      listEpoch.current++;
      detailEpoch.current++;
    },
    [],
  );
  const target = native
    ? {
        capture_id: capture.id,
        snapshot_sha256: props.source.snapshot_sha256,
      }
    : {
        address: controller!.address,
        device: controller!.device,
        router: controller!.router || null,
        dnet: controller!.dnet ?? null,
        capture_id: capture.id,
      };
  function check(result: Data, search: string, offset: number) {
    if (
      result.profile !==
        (native
          ? "native-backup-record-inspection/1"
          : "controller-native-records/1") ||
      result.capture_id !== capture.id ||
      result.sha256 !== capture.sha256 ||
      controllerKey(result.target) !==
        controllerKey(native ? props.source.target : controller!) ||
      result.read_only !== true ||
      result.field_actions !== false ||
      result.source_kind !==
        (native ? "native-backup-archive" : "controller-file-capture") ||
      (native &&
        (result.snapshot_sha256 !== props.source.snapshot_sha256 ||
          result.controller_queries !== false)) ||
      result.query !== search ||
      result.offset !== offset
    )
      throw new Error(
        "Native record response differs from the selected source or request.",
      );
  }
  async function list(offset = 0, search = query) {
    const epoch = ++listEpoch.current;
    detailEpoch.current++;
    setDetail(null);
    setSelected("");
    setPropertyQuery("");
    setDetailError("");
    setDetailBusy(false);
    setBusy(true);
    setError("");
    try {
      const result = await api(base + "records", {
        ...target,
        query: search,
        offset,
        limit: pageSize,
      });
      if (epoch !== listEpoch.current) return;
      check(result, search, offset);
      setInventory({
        data: result,
        owner,
        generation: ownerGeneration.current,
      });
    } catch (failure) {
      if (epoch === listEpoch.current) setError(String(failure));
    } finally {
      if (epoch === listEpoch.current) setBusy(false);
    }
  }
  async function inspect(record: string, offset = 0, search = "") {
    const epoch = ++detailEpoch.current;
    setSelected(record);
    setDetail(null);
    setDetailError("");
    setDetailBusy(true);
    try {
      const result = await api(base + "record", {
        ...target,
        record_id: record,
        query: search,
        offset,
        limit: pageSize,
      });
      if (epoch !== detailEpoch.current) return;
      check(result, search, offset);
      if (result.record?.id !== record)
        throw new Error("Native property response names another record.");
      setDetail({ data: result, owner, generation: ownerGeneration.current });
    } catch (failure) {
      if (epoch === detailEpoch.current) setDetailError(String(failure));
    } finally {
      if (epoch === detailEpoch.current) setDetailBusy(false);
    }
  }
  return (
    <details
      className="native-records"
      aria-label="Captured native record explorer"
      onToggle={(event) => {
        if (event.target !== event.currentTarget) return;
        if (event.currentTarget.open) {
          if (!inventory && !busy) void list();
        } else {
          listEpoch.current++;
          detailEpoch.current++;
          setBusy(false);
          setDetailBusy(false);
        }
      }}
    >
      <summary>Browse captured native records</summary>
      {native && (
        <p>
          Original retained File 3 archive. Stored properties are not merged
          saved settings or current live values.
        </p>
      )}
      <p>
        Captured File records, including records outside diagrams. Values here
        come from this snapshot; live values are acquired separately.
      </p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void list();
        }}
      >
        <label>
          Search captured native records
          <input
            maxLength={256}
            value={query}
            disabled={fieldBusy}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <button disabled={busy || fieldBusy}>Search records</button>
      </form>
      {busy && <p role="status">Loading captured records…</p>}
      {error && (
        <p role="alert">
          {error} Previous results retain their recorded query.
        </p>
      )}
      {inventory && (
        <>
          <p>
            {inventory.recognized_record_count} recognized records ·{" "}
            {inventory.total_matches} matches · query:{" "}
            {inventory.query || "all records"}.
          </p>
          <p>
            Framing:{" "}
            {inventory.record_framing === "declared-lengths"
              ? "declared native record lengths"
              : "reference scan; other source regions are not enumerated"}
            . {inventory.record_parse_errors} record parse errors. The original
            source remains retained.
          </p>
          <div
            className="native-record-table"
            tabIndex={0}
            role="region"
            aria-label="Captured record list scroll area"
            onKeyDown={scrollTable}
          >
            <table aria-label="Captured native records">
              <thead>
                <tr>
                  <th>Record</th>
                  <th>Reference and kind</th>
                  <th>Native class / stored object</th>
                  <th>Properties</th>
                  <th>Inspect</th>
                </tr>
              </thead>
              <tbody>
                {inventory.records.map((row: Data) => (
                  <tr key={row.id}>
                    <th scope="row">
                      {row.name}
                      <small>{row.id}</small>
                    </th>
                    <td>
                      {row.ref || "No engineering reference"}
                      <small>{row.kind}</small>
                    </td>
                    <td>
                      {row.class_name} ({row.class_id})
                      <small>
                        {row.object || "No decoded object reference"}
                      </small>
                    </td>
                    <td>{row.property_count}</td>
                    <td>
                      <button
                        type="button"
                        disabled={busy || fieldBusy}
                        aria-pressed={selected === row.id}
                        onClick={() => {
                          setPropertyQuery("");
                          void inspect(row.id);
                        }}
                      >
                        Inspect record
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!inventory.records.length && (
            <p>No recognized records match this query.</p>
          )}
          <div className="button-row">
            <button
              type="button"
              disabled={busy || fieldBusy || inventory.offset === 0}
              onClick={() =>
                void list(
                  Math.max(0, inventory.offset - pageSize),
                  inventory.query,
                )
              }
            >
              Previous records
            </button>
            <button
              type="button"
              disabled={busy || fieldBusy || inventory.next_offset == null}
              onClick={() => void list(inventory.next_offset, inventory.query)}
            >
              Next records
            </button>
            <span>
              Rows {inventory.records.length ? inventory.offset + 1 : 0}–
              {inventory.offset + inventory.records.length} of{" "}
              {inventory.total_matches}
            </span>
          </div>
        </>
      )}
      {detailBusy && <p role="status">Loading captured properties…</p>}
      {detailError && <p role="alert">{detailError}</p>}
      {detail && (
        <section aria-label="Captured native record properties">
          <h4>
            {detail.record.name} · {detail.record.id}
          </h4>
          <p>
            {detail.record.ref ||
              "Metadata record without an engineering reference"}
            . Captured source values only.
          </p>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void inspect(selected, 0, propertyQuery);
            }}
          >
            <label>
              Search captured properties
              <input
                maxLength={256}
                value={propertyQuery}
                disabled={fieldBusy}
                onChange={(event) => setPropertyQuery(event.target.value)}
              />
            </label>
            <button disabled={detailBusy || fieldBusy}>
              Search properties
            </button>
          </form>
          <p>
            {detail.total_matches} matching properties · query:{" "}
            {detail.query || "all properties"}.
          </p>
          <div
            className="native-record-table"
            tabIndex={0}
            role="region"
            aria-label="Captured property table scroll area"
            onKeyDown={scrollTable}
          >
            <table aria-label="Captured record properties">
              <thead>
                <tr>
                  <th>Property</th>
                  <th>Native datatype</th>
                  <th>Stored value</th>
                  <th>Encoding evidence</th>
                </tr>
              </thead>
              <tbody>
                {detail.properties.map((prop: Data) => (
                  <tr key={prop.id}>
                    <th scope="row">
                      {prop.name} ({prop.id})
                      <small>Source property order {prop.index + 1}</small>
                    </th>
                    <td>{prop.scalar?.datatype || "Structured / undecoded"}</td>
                    <td>{scalarText(prop.scalar)}</td>
                    <td>
                      <details>
                        <summary>Encoding evidence</summary>
                        <p>
                          {prop.encoded_bytes} bytes · expanded offsets{" "}
                          {prop.value_start_offset}–{prop.value_end_offset}
                        </p>
                        <code>{prop.encoded_sha256}</code>
                      </details>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!detail.properties.length && (
            <p>No captured properties match this query.</p>
          )}
          {native && props.booleanDrafts && booleanDefault && (
            <NativeBooleanDefaultCopy
              key={JSON.stringify([
                owner,
                ownerGeneration.current,
                detail.record.ref,
                booleanDefault.encoded_sha256,
              ])}
              source={props.source}
              field={{
                ref: detail.record.ref,
                class_id: detail.record.class_id,
                encoded_sha256: booleanDefault.encoded_sha256,
                value: booleanDefault.scalar.value,
              }}
              drafts={props.booleanDrafts}
            />
          )}
          <div className="button-row">
            <button
              type="button"
              disabled={detailBusy || fieldBusy || detail.offset === 0}
              onClick={() =>
                void inspect(
                  selected,
                  Math.max(0, detail.offset - pageSize),
                  detail.query,
                )
              }
            >
              Previous properties
            </button>
            <button
              type="button"
              disabled={detailBusy || fieldBusy || detail.next_offset == null}
              onClick={() =>
                void inspect(selected, detail.next_offset, detail.query)
              }
            >
              Next properties
            </button>
          </div>
          <details>
            <summary>Record byte evidence</summary>
            <p>
              {detail.record.expanded_bytes} bytes · expanded offsets{" "}
              {detail.record.expanded_offset}–
              {detail.record.expanded_end_offset}
            </p>
            <p>
              Record SHA-256 <code>{detail.record.record_sha256}</code>
            </p>
            <p>
              Original File SHA-256 <code>{capture.sha256}</code>
            </p>
          </details>
        </section>
      )}
    </details>
  );
}
