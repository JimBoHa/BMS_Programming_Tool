import {
  useContext,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { ChevronDown } from "lucide-react";
import "./native-wire-copy.css";
import { api, apiJsonDocument, apiBlobDocument, saveBlob } from "./api";
import { sha256Blob } from "./activityContracts";
import { controllerKey, type ControllerContext } from "./workflow";
import { NativeBooleanTransferContext } from "./NativeBooleanTransferContext";
import { NativeDefaultTransfer } from "./NativeDefaultTransfer";
import type { NativeArchiveSource } from "./NativeRecords";
import { rememberWireDraft, type WireCopyDrafts } from "./nativeWireDrafts";
import type { NativeDefaultRecoveryDocument } from "./nativeDefaultRecoveryContract";
import { historicalWireRecoveryProfile } from "./nativeWireRecoveryContract";
export type { WireCopyDrafts } from "./nativeWireDrafts";

type Data = Record<string, any>;
const archiveBase =
  "/bacnet/controller/native-application/inspection/wire-source";
const archiveProfile = "native-archive-wire-source-copy/1";
const effectiveProfile = "native-effective-wire-source-compiler/1";
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
  const transferContext = useContext(NativeBooleanTransferContext);
  const fieldBusy = transferContext?.fieldBusy ?? false;
  const transferOwner = useId();
  const [ownedBusy, setOwnedBusy] = useState(false);
  const archiveKey = JSON.stringify([
    source.capture_id,
    source.snapshot_sha256,
    source.sha256,
    source.target,
    record.ref,
    record.record_sha256,
  ]);
  const [basis, setBasis] = useState<"archive" | "effective">(() =>
    drafts.get(archiveKey + "/basis") === "effective" ? "effective" : "archive",
  );
  const effective = basis === "effective";
  const base = effective
    ? "/bacnet/controller/native-application/inspection/effective-wire-source"
    : archiveBase;
  const profile = effective ? effectiveProfile : archiveProfile;
  const graphKey = archiveKey + "/" + basis;
  const cachedIndex = Number(drafts.get(graphKey + "/wire") || "0");
  const [chosen, setChosen] = useState({
    key: graphKey,
    index:
      Number.isInteger(cachedIndex) && cachedIndex >= 0 && cachedIndex <= 4095
        ? cachedIndex
        : 0,
  });
  const wireIndex =
    chosen.key === graphKey
      ? chosen.index
      : Number.isInteger(cachedIndex) && cachedIndex >= 0 && cachedIndex <= 4095
        ? cachedIndex
        : 0;
  const context = JSON.stringify([
    graphKey,
    visible,
    fieldBusy && !ownedBusy,
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
  const recoveryKey = candidateKey + "/" + (selection?.property_sha256 ?? "");
  const [recovery, setRecovery] = useState<{
    key: string;
    document: NativeDefaultRecoveryDocument | null;
  } | null>(null);
  const recoveryDocument =
    recovery?.key === recoveryKey
      ? recovery.document
      : (transferContext?.wireRecoveryDrafts.get(recoveryKey) ?? null);
  const shownRecovery =
    effective &&
    selection &&
    recoveryDocument &&
    recoveryDocument.data.origin.current_capture_id === source.capture_id &&
    recoveryDocument.data.origin.current_snapshot_sha256 ===
      source.snapshot_sha256 &&
    recoveryDocument.data.origin.diagram_ref === record.ref &&
    recoveryDocument.data.origin.wire_index === wireIndex
      ? recoveryDocument
      : null;
  const activeRecovery = shownRecovery?.data.proposal ? shownRecovery : null;
  const ordinarySourceRef =
    choice?.key === candidateKey
      ? choice.value
      : (drafts.get(candidateKey) ?? wire?.source_ref ?? "");
  const sourceRef =
    activeRecovery?.data.proposal.source_ref ?? ordinarySourceRef;
  const recoveryPanel = useRef<HTMLElement>(null),
    pendingRecoveryFocus = useRef(false);
  useLayoutEffect(() => {
    if (pendingRecoveryFocus.current && visible && shownRecovery) {
      pendingRecoveryFocus.current = false;
      recoveryPanel.current?.focus({ preventScroll: true });
      recoveryPanel.current?.scrollIntoView({
        block: "nearest",
        inline: "nearest",
      });
    }
  });
  const historical =
    activeRecovery?.data.profile === historicalWireRecoveryProfile;
  const candidates: Data[] = selection
    ? historical
      ? [...selection.candidates, activeRecovery!.data.proposal_candidate]
      : selection.candidates
    : [];
  const candidate = candidates.find((row: Data) => row.ref === sourceRef);
  const fieldTransferActive =
    effective &&
    !!transferContext?.controller?.interfaceOpen &&
    transferContext.controller.ownedCommands === 0 &&
    controllerKey(transferContext.controller) ===
      controllerKey(source.target) &&
    !!candidate &&
    sourceRef !== wire?.source_ref;
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
        ...(effective
          ? {
              effective_sha256: data?.effective_sha256,
              effective_record_sha256: selection.record_sha256,
            }
          : {}),
      }
    : null;
  const copyBody =
    historical && body
      ? {
          ...body,
          recovery_parent_receipt:
            activeRecovery!.data.origin.parent_receipt_id,
          recovery_origin_sha256: activeRecovery!.data.origin_sha256,
        }
      : body;
  const copyBase = historical
    ? "/bacnet/controller/native-application/inspection/historical-wire-source"
    : base;
  const owner = JSON.stringify([
    context,
    contextEpoch.current,
    wireIndex,
    selection?.property_sha256,
    sourceRef,
    shownRecovery?.data.origin_sha256,
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
  const shownEdit =
    shown &&
    (effective ? shown.data.compilation.wire_edit : shown.data.compilation);
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
  function receiveRecovery(document: NativeDefaultRecoveryDocument) {
    const cache = transferContext?.wireRecoveryDrafts,
      origin = document.data.origin;
    if (
      !effective ||
      !selection ||
      origin.current_capture_id !== source.capture_id ||
      origin.current_snapshot_sha256 !== source.snapshot_sha256 ||
      origin.diagram_ref !== record.ref ||
      origin.wire_index !== wireIndex
    )
      return;
    if (cache && !cache.has(recoveryKey) && cache.size >= 256) {
      setError({
        owner: ownerNow.current,
        ticket: epoch.current,
        text: "256 wire recovery drafts are retained. Discard an older proposal before preparing another.",
      });
      return;
    }
    cache?.set(recoveryKey, document);
    epoch.current++;
    setReview(null);
    setError(null);
    setSaved(null);
    pendingRecoveryFocus.current = true;
    setRecovery({ key: recoveryKey, document });
  }
  function discardRecovery() {
    transferContext?.wireRecoveryDrafts.delete(recoveryKey);
    epoch.current++;
    setReview(null);
    setError(null);
    setSaved(null);
    setRecovery({ key: recoveryKey, document: null });
  }
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
      result.saved_settings_merged === effective &&
      (!effective ||
        (result.current_identity_verified === false &&
          result.source_immutable === true &&
          result.archive_record_sha256 === record.record_sha256 &&
          (["11", "12"] as const).every(
            (key) =>
              result.files?.[key]?.sha256 === source.files[key]?.sha256 &&
              result.files?.[key]?.bytes === source.files[key]?.bytes,
          ) &&
          hash(result.effective_sha256))) &&
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
        (!effective && info.record_sha256 !== record.record_sha256) ||
        !hash(info.record_sha256) ||
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
      const result = await apiJsonDocument(copyBase + "/preview", copyBody),
        value = result.data,
        compilation = value.compilation,
        copy = effective ? compilation?.wire_edit : compilation;
      const expected = [candidate.index, ...wire.old.slice(1)];
      if (
        !matches(value) ||
        !value.request ||
        Object.keys(value.request).sort().join() !==
          Object.keys(copyBody!).sort().join() ||
        Object.entries(copyBody!).some(([key, value]) =>
          key === "old"
            ? !tuple(result.data.request[key], value as number[])
            : result.data.request[key] !== value,
        ) ||
        !copy ||
        copy.profile !== compilerProfile ||
        copy.source_sha256 !==
          (effective ? data?.effective_sha256 : source.sha256) ||
        copy.diagram_ref !== record.ref ||
        copy.record_sha256 !== selection.record_sha256 ||
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
        (effective &&
          (value.effective_sha256 !== data?.effective_sha256 ||
            compilation.profile !== effectiveProfile ||
            compilation.archive_sha256 !== source.sha256 ||
            compilation.effective_sha256 !== data?.effective_sha256 ||
            (["3", "11", "12"] as const).some(
              (key) =>
                compilation.files?.[key]?.sha256 !==
                  source.files[key]?.sha256 ||
                compilation.files?.[key]?.bytes !== source.files[key]?.bytes,
            ) ||
            compilation.parameter_merge?.static_sha256 !==
              source.files["11"]?.sha256 ||
            compilation.parameter_merge?.dynamic_sha256 !==
              source.files["12"]?.sha256 ||
            compilation.parameter_merge?.output_sha256 !==
              data?.effective_sha256 ||
            compilation.other_merged_bytes_preserved !== true ||
            compilation.saved_settings_merged !== true ||
            compilation.controller_write !== false ||
            compilation.field_transfer_enabled !== false ||
            compilation.compiled_sha256 !== copy.output_sha256 ||
            compilation.compiled_native_sha256 !==
              copy.output_native_sha256)) ||
        value.output_sha256 !== copy.output_sha256 ||
        value.controller_write !== false ||
        !hash(value.review_sha256) ||
        (historical &&
          (value.recovery_profile !== historicalWireRecoveryProfile ||
            value.recovery_origin_sha256 !==
              activeRecovery!.data.origin_sha256 ||
            JSON.stringify(value.recovery_origin) !==
              JSON.stringify(activeRecovery!.data.origin) ||
            compilation.historical_pin_evidence_sha256 !==
              activeRecovery!.data.origin.historical_pin_sha256 ||
            JSON.stringify(compilation.historical_pin_evidence) !==
              JSON.stringify(activeRecovery!.data.origin.historical_pin)))
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
      const result = await apiBlobDocument(copyBase + "/export", {
        ...copyBody,
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
        saveBlob(
          result.blob,
          effective
            ? "native-effective-wire-source.moi"
            : "native-wire-source-copy.moi",
        );
        setSaved({
          owner: key,
          ticket,
          text: effective
            ? "Saved reviewed effective native wire compilation."
            : "Saved reviewed native wire source copy.",
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
      aria-label={
        effective
          ? "Effective native wire compilation"
          : "Native archive wire source copy"
      }
    >
      <summary>
        {effective
          ? "Compile an existing effective wire source"
          : "Copy an existing native wire source"}
      </summary>
      <label>
        Native wire source basis
        <span className="wire-copy-select">
          <select
            aria-label="Native wire source basis"
            value={basis}
            disabled={fieldBusy || !visible}
            onChange={(event) => {
              const value = event.target.value as "archive" | "effective";
              if (value === "archive") drafts.delete(archiveKey + "/basis");
              else if (
                !rememberWireDraft(drafts, archiveKey + "/basis", value)
              ) {
                setLoadError({ context: contextNow.current, text: fullDrafts });
                return;
              }
              setBasis(value);
            }}
          >
            <option value="archive">Original archive</option>
            <option value="effective">Saved effective snapshot</option>
          </select>
          <ChevronDown size={16} aria-hidden="true" />
        </span>
      </label>
      <p>
        {effective
          ? "Merge this retained snapshot's saved application values before the wire edit. These are captured effective values, not current controller readings."
          : "Original retained archive only. Paired saved settings are not merged."}{" "}
        Saving this copy does not send a program to a controller.
      </p>
      <button
        disabled={fieldBusy || !visible || loading}
        onClick={() => void load(wireIndex)}
      >
        {effective ? "Open saved wire sources" : "Open native wire sources"}
      </button>
      {loading && <p role="status">Inspecting recorded wire sources…</p>}
      {loadError?.context === context && <p role="alert">{loadError.text}</p>}
      {data && (
        <>
          {effective && (
            <p role="status">
              {data.parameter_merge?.matched_parameters} saved application
              parameters merged. The original graph membership, connections,
              order and layout remain unchanged before the selected edit.
            </p>
          )}
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
                    disabled={fieldBusy || !visible || !!activeRecovery}
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
                    {candidates.map((row: Data) => (
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
              {!selection.available && !historical && (
                <p>
                  No alternate source passes this recorded prototype, pin,
                  order, cycle and width profile.
                </p>
              )}
              {shownRecovery && (
                <section
                  className="native-compiler-source"
                  aria-label="Prepared previous wire source"
                  ref={recoveryPanel}
                  tabIndex={-1}
                >
                  <h3>
                    {shownRecovery.data.already_recorded
                      ? "Previous wire source already recorded in this backup"
                      : "Previous wire source prepared locally"}
                  </h3>
                  <p>
                    Receipt{" "}
                    <code>{shownRecovery.data.origin.parent_receipt_id}</code> ·{" "}
                    {record.ref} · connection {wireIndex + 1}:{" "}
                    {shownRecovery.data.origin.current_source_ref} to{" "}
                    {shownRecovery.data.origin.previous_source_ref}.
                  </p>
                  <p>
                    {shownRecovery.data.already_recorded
                      ? "No transfer proposal was created. This retained backup does not establish current live state."
                      : "A new controller review and both transfer confirmations are required. Other current saved settings remain current."}{" "}
                    Your ordinary wire draft remains retained separately.
                  </p>
                  {historical && (
                    <p>
                      The previous output pin comes from the verified original
                      program. Its current native configuration still matches
                      that evidence.
                    </p>
                  )}
                  <div className="button-row">
                    <button
                      onClick={() =>
                        saveBlob(
                          shownRecovery.blob,
                          "native-previous-wire-source-proposal.json",
                        )
                      }
                    >
                      Export exact previous wire proposal
                    </button>
                    <button
                      disabled={fieldBusy || !visible}
                      onClick={discardRecovery}
                    >
                      Discard wire recovery proposal
                    </button>
                  </div>
                </section>
              )}
              <div className="button-row">
                <button
                  className={
                    shown || fieldTransferActive ? undefined : "primary"
                  }
                  disabled={busy || fieldBusy || !visible || !candidate}
                  onClick={() => void prepare()}
                >
                  {effective
                    ? "Review effective wire compilation"
                    : "Review native wire copy"}
                </button>
                <button
                  disabled={fieldBusy || !visible || !!activeRecovery}
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
        <section
          aria-label={
            effective
              ? "Reviewed effective native wire compilation"
              : "Reviewed native wire copy"
          }
        >
          <h4>
            {effective
              ? "Reviewed effective wire compilation"
              : "Reviewed local connection copy"}
          </h4>
          <p>
            {shownEdit.old.join(", ")} → {shownEdit.new.join(", ")}.
          </p>
          <p>
            {shownEdit.changed
              ? "Only the existing source-index payload changes."
              : effective
                ? "No wire change; the merged snapshot bytes are retained."
                : "No wire change; the original archive bytes are retained."}{" "}
            {effective &&
              "Other saved values are merged before this wire edit. "}
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
              {effective
                ? "Save compiled native wire"
                : "Save native wire copy"}
            </button>
            <button
              onClick={() =>
                saveBlob(
                  shown.blob,
                  effective
                    ? "native-effective-wire-review.json"
                    : "native-wire-source-review.json",
                )
              }
            >
              {effective
                ? "Save exact effective wire review"
                : "Save exact native wire review"}
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
      {effective && data && wire && transferContext && (
        <NativeDefaultTransfer
          wireSource
          controller={transferContext.controller}
          source={{ ...data, device: source.target.device }}
          proposal={body}
          field={
            candidate && sourceRef !== wire.source_ref
              ? {
                  ref: record.ref,
                  encoded_sha256: selection.property_sha256,
                  wire_index: wireIndex,
                  old: wire.old,
                  old_source_ref: wire.source_ref,
                  target_ref: wire.target_ref,
                  source_index: candidate.index,
                  source_class: candidate.class_id,
                }
              : undefined
          }
          visible={visible}
          parentBusy={transferContext.parentBusy}
          otherOperationBusy={transferContext.otherOperationBusy}
          onBusy={(busy) => {
            setOwnedBusy(busy);
            transferContext.onBusy(transferOwner, busy);
          }}
          onCaptured={transferContext.onCaptured}
          wireSelection={{
            diagram_ref: record.ref,
            wire_index: wireIndex,
            class_id: record.class_id,
          }}
          recoveryDraft={activeRecovery}
          onRecoveryPrepared={receiveRecovery}
        />
      )}
    </details>
  );
}
