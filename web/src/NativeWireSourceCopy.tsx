import { useContext, useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import "./native-wire-copy.css";
import { api, apiJsonDocument, apiBlobDocument, saveBlob } from "./api";
import { sha256Blob } from "./activityContracts";
import { controllerKey, type ControllerContext } from "./workflow";
import { NativeBooleanTransferContext } from "./NativeBooleanTransferContext";
import type { NativeArchiveSource } from "./NativeRecords";
import { rememberWireDraft, type WireCopyDrafts } from "./nativeWireDrafts";
export type { WireCopyDrafts } from "./nativeWireDrafts";

type Data = Record<string, any>;
const base = "/bacnet/controller/native-application/inspection/wire-source";
const profile = "native-archive-wire-source-copy/1";
const compilerProfile = "tagged-moi-wire-source-copy/1";
const hash = (value: unknown) =>
  typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const tuple = (a: unknown, b: number[]) =>
  Array.isArray(a) &&
  a.length === 4 &&
  a.every((v, i) => Number.isInteger(v) && v === b[i]);
const fullDrafts =
  "The 256 retained wire draft slots are full. Discard an older wire draft or return its connection selector to the first wire, then try again. No existing draft was removed.";

export function NativeWireSourceCopy({
  source,
  record,
  controller,
  visible,
  drafts,
}: {
  source: NativeArchiveSource;
  record: Data;
  controller?: ControllerContext | null;
  visible: boolean;
  drafts: WireCopyDrafts;
}) {
  const fieldBusy =
    useContext(NativeBooleanTransferContext)?.fieldBusy ?? false;
  const graphKey = JSON.stringify([
    source.capture_id,
    source.snapshot_sha256,
    source.sha256,
    source.target,
    record.ref,
    record.record_sha256,
  ]);
  const cachedIndex = Number(drafts.get(graphKey + "/wire") || "0");
  const [chosen, setChosen] = useState({
    key: graphKey,
    index:
      Number.isInteger(cachedIndex) && cachedIndex >= 0 && cachedIndex <= 4095
        ? cachedIndex
        : 0,
  });
  const wireIndex = chosen.key === graphKey ? chosen.index : 0;
  const context = JSON.stringify([
    graphKey,
    visible,
    fieldBusy,
    controller && [
      controllerKey(controller),
      controller.interfaceKey,
      controller.interfaceOpen,
    ],
  ]);
  const contextNow = useRef(context),
    contextEpoch = useRef(0),
    loadTicket = useRef(0),
    alive = useRef(true);
  if (contextNow.current !== context) {
    contextNow.current = context;
    contextEpoch.current++;
    loadTicket.current++;
  }
  const [loaded, setLoaded] = useState<{
    context: string;
    epoch: number;
    data: Data;
  } | null>(null);
  const data =
    loaded?.context === context && loaded.epoch === contextEpoch.current
      ? loaded.data
      : null;
  const selection =
    data?.selection.wire_index === wireIndex ? data.selection : null;
  const wire = selection?.selected_wire;
  const candidateKey = graphKey + "/" + wireIndex;
  const [choice, setChoice] = useState<{ key: string; value: string } | null>(
    null,
  );
  const sourceRef =
    choice?.key === candidateKey
      ? choice.value
      : (drafts.get(candidateKey) ?? wire?.source_ref ?? "");
  const candidate = selection?.candidates.find(
    (row: Data) => row.ref === sourceRef,
  );
  const request = {
    capture_id: source.capture_id,
    snapshot_sha256: source.snapshot_sha256,
    source_sha256: source.sha256,
    diagram_ref: record.ref,
    record_sha256: record.record_sha256,
    wire_index: wireIndex,
  };
  const body = wire
    ? {
        ...request,
        property_sha256: selection.property_sha256,
        old: wire.old,
        source_ref: sourceRef,
      }
    : null;
  const owner = JSON.stringify([
    context,
    contextEpoch.current,
    wireIndex,
    selection?.property_sha256,
    sourceRef,
  ]);
  const ownerNow = useRef(owner),
    epoch = useRef(0);
  if (ownerNow.current !== owner) {
    ownerNow.current = owner;
    epoch.current++;
  }
  const [review, setReview] = useState<{
    owner: string;
    ticket: number;
    data: Data;
    blob: Blob;
  } | null>(null);
  const shown =
    review?.owner === owner && review.ticket === epoch.current ? review : null;
  const [pending, setPending] = useState<{
    owner: string;
    ticket: number;
  } | null>(null);
  const [loadPending, setLoadPending] = useState<{
      context: string;
      epoch: number;
      ticket: number;
    } | null>(null),
    [loadError, setLoadError] = useState<{
      context: string;
      text: string;
    } | null>(null);
  const [error, setError] = useState<{
    owner: string;
    ticket: number;
    text: string;
  } | null>(null);
  const [saved, setSaved] = useState<{
    owner: string;
    ticket: number;
    text: string;
  } | null>(null);
  const busy = pending?.owner === owner && pending.ticket === epoch.current;
  const loading =
    loadPending?.context === context &&
    loadPending.epoch === contextEpoch.current &&
    loadPending.ticket === loadTicket.current;
  const failure =
    error?.owner === owner && error.ticket === epoch.current ? error.text : "";
  const current = (key: string, ticket: number) =>
    alive.current && ownerNow.current === key && epoch.current === ticket;
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      contextEpoch.current++;
      loadTicket.current++;
      epoch.current++;
    };
  }, []);
  function matches(result: Data) {
    return (
      result.profile === profile &&
      result.compiler_profile === compilerProfile &&
      result.source_kind === "native-backup-archive" &&
      result.capture_id === source.capture_id &&
      result.snapshot_sha256 === source.snapshot_sha256 &&
      result.source_sha256 === source.sha256 &&
      result.sha256 === source.sha256 &&
      result.files?.["3"]?.sha256 === source.sha256 &&
      controllerKey(result.target) === controllerKey(source.target) &&
      result.read_only === true &&
      result.controller_queries === false &&
      result.field_actions === false &&
      result.identity_verified === false &&
      result.saved_settings_merged === false &&
      result.field_transfer_enabled === false &&
      result.can_apply === false
    );
  }
  async function load(index: number) {
    if (fieldBusy || !visible) return;
    if (index === 0) drafts.delete(graphKey + "/wire");
    else if (!rememberWireDraft(drafts, graphKey + "/wire", String(index))) {
      setLoadError({ context: contextNow.current, text: fullDrafts });
      return;
    }
    setChosen({ key: graphKey, index });
    const key = contextNow.current,
      version = contextEpoch.current,
      ticket = ++loadTicket.current;
    setLoadPending({ context: key, epoch: version, ticket });
    setLoadError(null);
    setReview(null);
    setError(null);
    setSaved(null);
    try {
      const result = await api(base + "/source", {
          ...request,
          wire_index: index,
        }),
        info = result.selection;
      if (
        !matches(result) ||
        !info ||
        info.diagram_ref !== record.ref ||
        info.record_sha256 !== record.record_sha256 ||
        info.wire_index !== index ||
        !hash(info.property_sha256) ||
        !Array.isArray(info.wires) ||
        info.wires.length > 4096 ||
        !Array.isArray(info.candidates) ||
        info.candidates.length > 512 ||
        typeof info.available !== "boolean" ||
        (info.wires.length &&
          (!info.selected_wire ||
            info.selected_wire.index !== index ||
            !tuple(info.selected_wire.old, info.wires[index]?.old || []))) ||
        info.candidates.some(
          (row: Data) =>
            typeof row.ref !== "string" ||
            !Number.isInteger(row.index) ||
            row.index < 0 ||
            row.index >= info.block_count ||
            !Number.isInteger(row.class_id) ||
            typeof row.current_source !== "boolean",
        )
      )
        throw new Error(
          "Native wire sources do not match this original archive and graph.",
        );
      if (
        alive.current &&
        contextNow.current === key &&
        contextEpoch.current === version &&
        loadTicket.current === ticket
      )
        setLoaded({ context: key, epoch: version, data: result });
    } catch (failure) {
      if (
        alive.current &&
        contextNow.current === key &&
        contextEpoch.current === version &&
        loadTicket.current === ticket
      )
        setLoadError({ context: key, text: String(failure) });
    } finally {
      if (
        alive.current &&
        contextNow.current === key &&
        contextEpoch.current === version &&
        loadTicket.current === ticket
      )
        setLoadPending(null);
    }
  }
  async function prepare() {
    if (!body || !candidate || fieldBusy || !visible) return;
    const key = ownerNow.current,
      ticket = ++epoch.current;
    setReview(null);
    setError(null);
    setSaved(null);
    setPending({ owner: key, ticket });
    try {
      const result = await apiJsonDocument(base + "/preview", body),
        value = result.data,
        copy = value.compilation;
      const expected = [candidate.index, ...wire.old.slice(1)];
      if (
        !matches(value) ||
        !value.request ||
        Object.keys(value.request).sort().join() !==
          Object.keys(body).sort().join() ||
        Object.entries(body).some(([key, value]) =>
          key === "old"
            ? !tuple(result.data.request[key], value as number[])
            : result.data.request[key] !== value,
        ) ||
        !copy ||
        copy.profile !== compilerProfile ||
        copy.source_sha256 !== source.sha256 ||
        copy.diagram_ref !== record.ref ||
        copy.record_sha256 !== record.record_sha256 ||
        copy.property_sha256 !== selection.property_sha256 ||
        copy.wire_index !== wireIndex ||
        !tuple(copy.old, wire.old) ||
        !tuple(copy.new, expected) ||
        copy.source_ref !== sourceRef ||
        copy.old_source_ref !== wire.source_ref ||
        copy.target_ref !== wire.target_ref ||
        copy.source_class !== candidate.class_id ||
        copy.other_expanded_bytes_preserved !== true ||
        copy.native_structure_readback_verified !== true ||
        copy.saved_settings_merged !== false ||
        copy.controller_write !== false ||
        copy.field_transfer_enabled !== false ||
        typeof copy.changed !== "boolean" ||
        copy.changed !== (sourceRef !== wire.source_ref) ||
        !Number.isInteger(copy.source_index_offset) ||
        copy.source_index_offset < 0 ||
        copy.source_index_offset > 8388608 ||
        ![1, 2, 3, 4].includes(copy.source_index_bytes) ||
        !hash(copy.output_sha256) ||
        !hash(copy.output_native_sha256) ||
        !hash(copy.compilation_sha256) ||
        value.output_sha256 !== copy.output_sha256 ||
        value.controller_write !== false ||
        !hash(value.review_sha256)
      )
        throw new Error(
          "Native wire review differs from this source, tuple and proposed connection.",
        );
      if (current(key, ticket)) setReview({ owner: key, ticket, ...result });
    } catch (failure) {
      if (current(key, ticket))
        setError({ owner: key, ticket, text: String(failure) });
    } finally {
      if (current(key, ticket)) setPending(null);
    }
  }
  async function save() {
    if (!shown || !body || fieldBusy || !visible) return;
    const key = ownerNow.current,
      ticket = epoch.current;
    setPending({ owner: key, ticket });
    setError(null);
    setSaved(null);
    try {
      const result = await apiBlobDocument(base + "/export", {
        ...body,
        review_sha256: shown.data.review_sha256,
      });
      if (
        result.headers.get("X-Studio-Artifact-Sha256") !==
          shown.data.output_sha256 ||
        result.headers.get("X-Studio-Review-Sha256") !==
          shown.data.review_sha256 ||
        result.headers.get("X-Studio-Snapshot-Sha256") !==
          source.snapshot_sha256 ||
        (await sha256Blob(result.blob)) !== shown.data.output_sha256
      )
        throw new Error(
          "Native wire output bytes differ from the reviewed copy.",
        );
      if (current(key, ticket)) {
        saveBlob(result.blob, "native-wire-source-copy.moi");
        setSaved({
          owner: key,
          ticket,
          text: "Saved reviewed native wire source copy.",
        });
      }
    } catch (failure) {
      if (current(key, ticket))
        setError({ owner: key, ticket, text: String(failure) });
    } finally {
      if (current(key, ticket)) setPending(null);
    }
  }
  return (
    <details
      className="native-wire-copy"
      aria-label="Native archive wire source copy"
    >
      <summary>Copy an existing native wire source</summary>
      <p>
        Original retained archive only. Paired saved settings are not merged.
        Saving this copy does not send a program to a controller.
      </p>
      <button
        disabled={fieldBusy || !visible || loading}
        onClick={() => void load(wireIndex)}
      >
        Open native wire sources
      </button>
      {loading && <p role="status">Inspecting recorded wire sources…</p>}
      {loadError?.context === context && <p role="alert">{loadError.text}</p>}
      {data && (
        <>
          <label>
            Existing native connection
            <span className="wire-copy-select">
              <select
                aria-label="Existing native connection"
                value={wireIndex}
                disabled={fieldBusy || !visible || loading}
                onChange={(event) => void load(Number(event.target.value))}
              >
                {data.selection.wires.map((row: Data) => (
                  <option key={row.index} value={row.index}>
                    {row.index + 1}. {row.source_ref} : {row.source_port} →{" "}
                    {row.target_ref} : {row.target_port}
                  </option>
                ))}
              </select>
              <ChevronDown size={16} aria-hidden="true" />
            </span>
          </label>
          {!data.selection.wires.length && (
            <p>
              No existing native connection is recorded. This copy tool
              allocates no connection.
            </p>
          )}
          {selection && wire && (
            <>
              <p>
                Recorded source: {wire.source_ref} · port {wire.source_port}.
                Destination: {wire.target_ref} · port {wire.target_port}.
              </p>
              <label>
                Replacement native source
                <span className="wire-copy-select">
                  <select
                    aria-label="Replacement native source"
                    value={sourceRef}
                    disabled={fieldBusy || !visible}
                    onChange={(event) => {
                      if (event.target.value === wire.source_ref)
                        drafts.delete(candidateKey);
                      else if (
                        !rememberWireDraft(
                          drafts,
                          candidateKey,
                          event.target.value,
                        )
                      ) {
                        setError({
                          owner: ownerNow.current,
                          ticket: epoch.current,
                          text: fullDrafts,
                        });
                        return;
                      }
                      setChoice({
                        key: candidateKey,
                        value: event.target.value,
                      });
                    }}
                  >
                    {!candidate && sourceRef && (
                      <option value={sourceRef}>
                        Unqualified retained draft: {sourceRef}
                      </option>
                    )}
                    {selection.candidates.map((row: Data) => (
                      <option key={row.ref} value={row.ref}>
                        {row.name} · {row.ref} · class {row.class_id}
                        {row.current_source ? " · current source" : ""}
                      </option>
                    ))}
                  </select>
                  <ChevronDown size={16} aria-hidden="true" />
                </span>
              </label>
              {!candidate && (
                <p role="status">
                  The retained draft no longer matches the current source
                  profile. Choose an observed candidate or discard it.
                </p>
              )}
              {!selection.available && (
                <p>
                  No alternate source passes this recorded prototype, pin,
                  order, cycle and width profile.
                </p>
              )}
              <div className="button-row">
                <button
                  className={shown ? undefined : "primary"}
                  disabled={busy || fieldBusy || !visible || !candidate}
                  onClick={() => void prepare()}
                >
                  Review native wire copy
                </button>
                <button
                  disabled={fieldBusy || !visible}
                  onClick={() => {
                    drafts.delete(candidateKey);
                    setChoice({ key: candidateKey, value: wire.source_ref });
                  }}
                >
                  Discard native wire draft
                </button>
              </div>
            </>
          )}
        </>
      )}
      {failure && <p role="alert">{failure}</p>}
      {shown && (
        <section aria-label="Reviewed native wire copy">
          <h4>Reviewed local connection copy</h4>
          <p>
            {shown.data.compilation.old.join(", ")} →{" "}
            {shown.data.compilation.new.join(", ")}.
          </p>
          <p>
            {shown.data.compilation.changed
              ? "Only the existing source-index payload changes."
              : "No wire change; the original archive bytes are retained."}{" "}
            Other expanded bytes, identities, order, layout and metadata are
            preserved. Native runtime and CCT/physical acceptance remain
            unverified.
          </p>
          <div className="button-row">
            <button
              className="primary"
              disabled={busy || fieldBusy || !visible}
              onClick={() => void save()}
            >
              Save native wire copy
            </button>
            <button
              onClick={() =>
                saveBlob(shown.blob, "native-wire-source-review.json")
              }
            >
              Save exact native wire review
            </button>
          </div>
          <details>
            <summary>Wire copy evidence</summary>
            <pre>{JSON.stringify(shown.data, null, 2)}</pre>
          </details>
        </section>
      )}
      {saved?.owner === owner && saved.ticket === epoch.current && (
        <p role="status">{saved.text}</p>
      )}
    </details>
  );
}
