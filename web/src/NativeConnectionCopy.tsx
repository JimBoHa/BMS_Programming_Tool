import { useContext, useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import { api, apiBlobDocument, apiJsonDocument, saveBlob } from "./api";
import { NativeBooleanTransferContext } from "./NativeBooleanTransferContext";
import { NativeMatchingConnectionTransfer } from "./NativeMatchingConnectionTransfer";
import { controllerKey, type ControllerContext } from "./workflow";
import type { NativeArchiveSource } from "./NativeRecords";
import { rememberWireDraft, type WireCopyDrafts } from "./nativeWireDrafts";
import {
  connectionBase,
  connectionDraftKey,
  connectionSource,
  connectionReview,
  connectionExport,
} from "./nativeConnectionContract";
import {
  effectiveConnectionBase,
  effectiveConnectionSource,
  effectiveConnectionReview,
} from "./nativeEffectiveConnectionContract";

type Data = Record<string, any>;
const full =
  "The 256 retained wire draft slots are full. Discard an older draft before adding work. No existing draft was removed.";
function draft(value: string | undefined) {
  try {
    const p = JSON.parse(value || "{}");
    return {
      source_ref:
        typeof p.source_ref === "string" && p.source_ref.length <= 512
          ? p.source_ref
          : "",
      target_ref:
        typeof p.target_ref === "string" && p.target_ref.length <= 512
          ? p.target_ref
          : "",
    };
  } catch {
    return { source_ref: "", target_ref: "" };
  }
}

export function NativeConnectionCopy({
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
  const [ownedFieldBusy, setOwnedFieldBusy] = useState(false);
  const [ownedMutationBusy, setOwnedMutationBusy] = useState(false);
  const otherFieldBusy = fieldBusy && !ownedFieldBusy;
  const archiveKey = connectionDraftKey(source, record);
  const destinationKey = archiveKey + "/destination";
  const cachedDestination =
    drafts.get(destinationKey) === "controller" ? "controller" : "file";
  const [destinationChoice, setDestinationChoice] = useState({
    key: destinationKey,
    value: cachedDestination,
  });
  const destination =
    destinationChoice.key === destinationKey
      ? destinationChoice.value
      : cachedDestination;
  const [surfaceOpen, setSurfaceOpen] = useState(false);
  const fieldSurface = useRef(false),
    fieldGeneration = useRef(0);
  function surfaceChanged(open: boolean) {
    if (fieldSurface.current !== open) {
      fieldGeneration.current++;
      repaint((value) => value + 1);
    }
    fieldSurface.current = open;
    setSurfaceOpen(open);
  }
  const [basis, setBasis] = useState<"archive" | "effective">(
    drafts.get(archiveKey + "/basis") === "effective" ? "effective" : "archive",
  );
  const effective = basis === "effective";
  const fieldMode = effective && destination === "controller";
  const apiBase = effective ? effectiveConnectionBase : connectionBase;
  const baseKey = archiveKey + (effective ? "/effective" : "");
  const cached = Number(drafts.get(baseKey + "/prototype") || 0);
  const validIndex =
    Number.isInteger(cached) && cached >= 0 && cached <= 4095 ? cached : 0;
  const [chosen, setChosen] = useState({ key: baseKey, index: validIndex });
  const index = chosen.key === baseKey ? chosen.index : validIndex;
  const setIndex = (value: number) => setChosen({ key: baseKey, index: value });
  const pairKey = baseKey + "/pair/" + index;
  const pair = draft(drafts.get(pairKey));
  const [, repaint] = useState(0);
  const [life, setLife] = useState(0);
  const context = JSON.stringify([
    baseKey,
    visible,
    otherFieldBusy,
    fieldMode,
    life,
    controller && [
      controllerKey(controller),
      controller.interfaceKey,
      controller.interfaceOpen,
    ],
  ]);
  const contextNow = useRef(context),
    generation = useRef(0),
    alive = useRef(true);
  if (contextNow.current !== context) {
    contextNow.current = context;
    generation.current++;
  }
  const loadKey = JSON.stringify([
    context,
    generation.current,
    index,
    pair.source_ref,
  ]);
  const owner = JSON.stringify([loadKey, pair.target_ref]);
  const ownerNow = useRef(owner),
    epoch = useRef(0),
    loadNow = useRef(loadKey),
    loadEpoch = useRef(0);
  if (ownerNow.current !== owner) {
    ownerNow.current = owner;
    epoch.current++;
  }
  if (loadNow.current !== loadKey) {
    loadNow.current = loadKey;
    loadEpoch.current++;
  }
  const [opened, setOpened] = useState(false),
    [reload, setReload] = useState(0);
  const [loaded, setLoaded] = useState<{ key: string; data: Data } | null>(
    null,
  );
  const selection = loaded?.key === loadKey ? loaded.data.selection : null;
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState<{ owner: string; text: string } | null>(
    null,
  );
  const [review, setReview] = useState<{
    owner: string;
    epoch: number;
    data: Data;
    blob: Blob;
  } | null>(null);
  const shown =
    review?.owner === owner && review.epoch === epoch.current ? review : null;
  const shownEdit =
    shown &&
    (effective
      ? shown.data.compilation.connection_edit
      : shown.data.compilation);
  const [pending, setPending] = useState<{
    owner: string;
    epoch: number;
  } | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const busy = pending?.owner === owner && pending.epoch === epoch.current;
  const current = (key: string, ticket: number) =>
    alive.current && ownerNow.current === key && epoch.current === ticket;
  const sourceRef = pair.source_ref || selection?.source_ref || "";
  const sourceRow = selection?.sources.find((r: Data) => r.ref === sourceRef);
  const targetRow = selection?.targets.find(
    (r: Data) => r.ref === pair.target_ref,
  );
  const sourceRequest = {
    capture_id: source.capture_id,
    snapshot_sha256: source.snapshot_sha256,
    source_sha256: source.sha256,
    diagram_ref: record.ref,
    record_sha256: record.record_sha256,
    prototype_index: index,
    source_ref: pair.source_ref || null,
  };
  const body =
    selection?.available && sourceRow && targetRow
      ? {
          ...sourceRequest,
          source_ref: sourceRef,
          target_ref: pair.target_ref,
          property_sha256: selection.property_sha256,
          metadata_property_sha256: selection.metadata_property_sha256,
          prototype_old: selection.prototype.old,
          connection_count: selection.connection_count,
          ...(effective
            ? {
                effective_sha256: loaded!.data.effective_sha256,
                effective_record_sha256: selection.record_sha256,
              }
            : {}),
        }
      : null;
  useEffect(() => {
    alive.current = true;
    function retire() {
      epoch.current++;
      loadEpoch.current++;
      generation.current++;
      setLife((n) => n + 1);
      setOpened(false);
      setLoaded(null);
      setReview(null);
      setPending(null);
      setLoading(null);
      setError(null);
      setSaved(null);
    }
    const hidden = () => {
      if (document.visibilityState === "hidden") retire();
    };
    window.addEventListener("pagehide", retire);
    document.addEventListener("visibilitychange", hidden);
    return () => {
      alive.current = false;
      epoch.current++;
      loadEpoch.current++;
      window.removeEventListener("pagehide", retire);
      document.removeEventListener("visibilitychange", hidden);
    };
  }, []);
  useEffect(() => {
    if (!opened || !visible || fieldBusy) return;
    const key = loadKey,
      ticket = ++loadEpoch.current;
    const valid = () =>
      alive.current && loadNow.current === key && loadEpoch.current === ticket;
    epoch.current++;
    setReview(null);
    setLoaded(null);
    setError(null);
    setSaved(null);
    setLoading(key);
    void (async () => {
      try {
        const result = await api(apiBase + "/source", sourceRequest);
        if (
          !(effective
            ? effectiveConnectionSource(result, source, sourceRequest)
            : connectionSource(result, source, sourceRequest))
        )
          throw new Error(
            "Native connection candidates do not match this original archive, graph and prototype.",
          );
        if (valid()) setLoaded({ key, data: result });
      } catch (failure) {
        if (valid())
          setError({ owner: ownerNow.current, text: String(failure) });
      } finally {
        if (valid()) setLoading(null);
      }
    })();
    return () => {
      loadEpoch.current++;
    };
    // A load is owned by the exact source/prototype/output selection, not its destination draft.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadKey, reload, opened]);
  function changePair(value: { source_ref: string; target_ref: string }) {
    if (!value.source_ref && !value.target_ref) drafts.delete(pairKey);
    else if (!rememberWireDraft(drafts, pairKey, JSON.stringify(value))) {
      setError({ owner, text: full });
      return;
    }
    epoch.current++;
    setReview(null);
    setError(null);
    setSaved(null);
    repaint((n) => n + 1);
  }
  async function prepare() {
    if (!body || !selection || fieldBusy || !visible) return;
    const key = owner,
      ticket = ++epoch.current,
      request = body,
      original = selection,
      openedSource = loaded!.data;
    setReview(null);
    setError(null);
    setSaved(null);
    setPending({ owner: key, epoch: ticket });
    try {
      const result = await apiJsonDocument(apiBase + "/preview", request);
      if (
        !(effective
          ? await effectiveConnectionReview(
              result.data,
              source,
              request,
              openedSource,
            )
          : await connectionReview(result.data, source, request, original))
      )
        throw new Error(
          "Native connection review does not match this exact proposal and compilation proof.",
        );
      if (current(key, ticket))
        setReview({ owner: key, epoch: ticket, ...result });
    } catch (failure) {
      if (current(key, ticket)) setError({ owner: key, text: String(failure) });
    } finally {
      if (current(key, ticket)) setPending(null);
    }
  }
  async function save() {
    if (!shown || !body || fieldBusy || !visible) return;
    const key = owner,
      ticket = epoch.current;
    setError(null);
    setSaved(null);
    setPending({ owner: key, epoch: ticket });
    try {
      const result = await apiBlobDocument(apiBase + "/export", {
        ...body,
        review_sha256: shown.data.review_sha256,
      });
      if (!(await connectionExport(result, shown.data)))
        throw new Error(
          "Native connection output bytes or export proof differ from the reviewed copy.",
        );
      if (current(key, ticket)) {
        saveBlob(
          result.blob,
          effective
            ? "native-effective-connection.moi"
            : "native-connection-copy.moi",
        );
        setSaved(owner);
      }
    } catch (failure) {
      if (current(key, ticket)) setError({ owner: key, text: String(failure) });
    } finally {
      if (current(key, ticket)) setPending(null);
    }
  }
  const disabled = fieldBusy || !visible || loading === loadKey;
  const fieldTicket = epoch.current,
    surfaceTicket = fieldGeneration.current;
  return (
    <details
      className="native-wire-copy"
      aria-label="Native matching connection copy"
      onToggle={(event) => surfaceChanged(event.currentTarget.open)}
    >
      <summary
        aria-disabled={ownedMutationBusy || otherFieldBusy || !visible}
        onClick={(event) => {
          if (ownedMutationBusy || otherFieldBusy || !visible) {
            event.preventDefault();
            return;
          }
          surfaceChanged(
            !event.currentTarget.parentElement!.hasAttribute("open"),
          );
        }}
      >
        {fieldMode
          ? "Add a matching connection to the controller"
          : "Add a matching native connection to a local copy"}
      </summary>
      <label>
        Native connection basis
        <span className="wire-copy-select">
          <select
            aria-label="Native connection basis"
            value={basis}
            disabled={fieldBusy || !visible}
            onChange={(event) => {
              const value = event.target.value as "archive" | "effective";
              if (value === "archive") drafts.delete(archiveKey + "/basis");
              else if (
                !rememberWireDraft(drafts, archiveKey + "/basis", value)
              ) {
                setError({ owner, text: full });
                return;
              }
              epoch.current++;
              setReview(null);
              setOpened(false);
              setError(null);
              setSaved(null);
              setBasis(value);
            }}
          >
            <option value="archive">Original archive</option>
            <option value="effective">Saved effective snapshot</option>
          </select>
          <ChevronDown size={16} aria-hidden="true" />
        </span>
      </label>
      {effective && (
        <label>
          Matching connection destination
          <span className="wire-copy-select">
            <select
              aria-label="Matching connection destination"
              value={destination}
              disabled={fieldBusy || !visible}
              onChange={(event) => {
                const value = event.target.value;
                if (value === "file") drafts.delete(destinationKey);
                else if (!rememberWireDraft(drafts, destinationKey, value)) {
                  setError({ owner, text: full });
                  return;
                }
                epoch.current++;
                setReview(null);
                setSaved(null);
                setError(null);
                setDestinationChoice({ key: destinationKey, value });
              }}
            >
              <option value="file">Save a local file</option>
              <option value="controller">
                Apply to the selected controller
              </option>
            </select>
            <ChevronDown size={16} aria-hidden="true" />
          </span>
        </label>
      )}
      <p>
        {effective
          ? "Merge this retained snapshot's saved application values before adding the connection. These are captured effective values, not current controller readings."
          : "Original retained archive only. Saved settings are not merged."}{" "}
        Choose a recorded connection as the port and configuration prototype,
        then an unused matching input. Saving sends no program to a controller.
      </p>
      <button
        className={!fieldMode && !selection ? "primary" : undefined}
        disabled={disabled}
        onClick={() => {
          epoch.current++;
          setReview(null);
          setOpened(true);
          setReload((n) => n + 1);
        }}
      >
        {effective
          ? "Open saved connection candidates"
          : "Open native connection candidates"}
      </button>
      {loading === loadKey && (
        <p role="status">Inspecting recorded connection candidates…</p>
      )}
      {error?.owner === owner && <p role="alert">{error.text}</p>}
      {selection && (
        <>
          {effective && (
            <p role="status">
              {loaded!.data.parameter_merge.matched_parameters} saved
              application parameters merged before the connection addition.
            </p>
          )}
          {!selection.prototype ? (
            <p>
              No recorded native connection prototype is available. No pin or
              connection is invented.
            </p>
          ) : (
            <>
              <label>
                Native connection prototype
                <span className="wire-copy-select">
                  <select
                    aria-label="Native connection prototype"
                    value={index}
                    disabled={disabled}
                    onChange={(e) => {
                      const value = Number(e.target.value);
                      if (value === 0) drafts.delete(baseKey + "/prototype");
                      else if (
                        !rememberWireDraft(
                          drafts,
                          baseKey + "/prototype",
                          String(value),
                        )
                      ) {
                        setError({ owner, text: full });
                        return;
                      }
                      epoch.current++;
                      setReview(null);
                      setIndex(value);
                    }}
                  >
                    {selection.wires.map((w: Data) => (
                      <option key={w.index} value={w.index}>
                        {w.index + 1}. {w.source_ref} : {w.source_port} →{" "}
                        {w.target_ref} : {w.target_port}
                      </option>
                    ))}
                  </select>
                  <ChevronDown size={16} aria-hidden="true" />
                </span>
              </label>
              <label>
                Native connection source
                <span className="wire-copy-select">
                  <select
                    aria-label="Native connection source"
                    value={sourceRef}
                    disabled={disabled}
                    onChange={(e) =>
                      changePair({
                        source_ref:
                          e.target.value === selection.prototype.source_ref
                            ? ""
                            : e.target.value,
                        target_ref: "",
                      })
                    }
                  >
                    {!sourceRow && (
                      <option value={sourceRef}>
                        Unqualified retained source: {sourceRef}
                      </option>
                    )}
                    {selection.sources.map((r: Data) => (
                      <option key={r.ref} value={r.ref}>
                        {r.name} · {r.ref} · port{" "}
                        {selection.prototype.source_port}
                      </option>
                    ))}
                  </select>
                  <ChevronDown size={16} aria-hidden="true" />
                </span>
              </label>
              <label>
                Unused native destination
                <span className="wire-copy-select">
                  <select
                    aria-label="Unused native destination"
                    value={pair.target_ref}
                    disabled={disabled}
                    onChange={(e) =>
                      changePair({ ...pair, target_ref: e.target.value })
                    }
                  >
                    <option value="">Choose an unused matching input</option>
                    {!!pair.target_ref && !targetRow && (
                      <option value={pair.target_ref}>
                        Unqualified retained destination: {pair.target_ref}
                      </option>
                    )}
                    {selection.targets.map((r: Data) => (
                      <option key={r.ref} value={r.ref}>
                        {r.name} · {r.ref} · port{" "}
                        {selection.prototype.target_port}
                      </option>
                    ))}
                  </select>
                  <ChevronDown size={16} aria-hidden="true" />
                </span>
              </label>
              {!selection.available && (
                <p>
                  No destination passes the recorded configuration, unused
                  input, execution order, cycle and native size profile.
                </p>
              )}
              <p>
                {selection.connection_count} recorded connections. Continuation
                metadata:{" "}
                {selection.continuation_metadata === "not-recorded"
                  ? "not recorded"
                  : "copy the recorded prototype row"}
                .
              </p>
              {!fieldMode && (
                <div className="button-row">
                  <button
                    className={shown ? undefined : "primary"}
                    disabled={disabled || busy || !body}
                    onClick={() => void prepare()}
                  >
                    {effective
                      ? "Review saved connection compilation"
                      : "Review native connection copy"}
                  </button>
                </div>
              )}
            </>
          )}
        </>
      )}
      <div className="button-row">
        <button
          disabled={fieldBusy || !visible || !drafts.has(pairKey)}
          onClick={() => changePair({ source_ref: "", target_ref: "" })}
        >
          Discard native connection draft
        </button>
        {index !== 0 && (
          <button
            disabled={fieldBusy || !visible}
            onClick={() => {
              drafts.delete(baseKey + "/prototype");
              epoch.current++;
              setReview(null);
              setIndex(0);
            }}
          >
            Return to first native prototype
          </button>
        )}
      </div>
      {shown && !fieldMode && (
        <section
          aria-label={
            effective
              ? "Reviewed saved connection compilation"
              : "Reviewed native connection copy"
          }
        >
          <p>
            New connection: {shownEdit.new.join(", ")}. Connections:{" "}
            {shownEdit.connection_count_before} →{" "}
            {shownEdit.connection_count_after}.
          </p>
          <p>
            Native structure readback verified. Other expanded bytes preserved.
            Controller transfer and CCT acceptance remain unqualified for this
            copy.
          </p>
          <div className="button-row">
            <button
              className="primary"
              disabled={busy || fieldBusy || !visible}
              onClick={() => void save()}
            >
              {effective
                ? "Save effective connection compilation"
                : "Save native connection copy"}
            </button>
            <button
              disabled={busy || fieldBusy || !visible}
              onClick={() => {
                if (current(shown.owner, shown.epoch))
                  saveBlob(
                    shown.blob,
                    effective
                      ? "native-effective-connection-review.json"
                      : "native-connection-review.json",
                  );
              }}
            >
              {effective
                ? "Save exact effective connection review"
                : "Save exact native connection review"}
            </button>
          </div>
          <details>
            <summary>Connection compilation details</summary>
            <pre>{JSON.stringify(shown.data.compilation, null, 2)}</pre>
          </details>
        </section>
      )}
      {saved === owner && (
        <p role="status">
          {effective
            ? "Saved reviewed local effective connection compilation."
            : "Saved reviewed local native connection copy."}
        </p>
      )}
      <div hidden={!fieldMode}>
        <NativeMatchingConnectionTransfer
          source={source}
          proposal={fieldMode ? body : null}
          opened={selection ? loaded!.data : null}
          controller={controller}
          visible={visible && fieldMode && surfaceOpen}
          otherBusy={otherFieldBusy}
          onOwnedBusy={(busy, kind) => {
            setOwnedFieldBusy(busy);
            setOwnedMutationBusy(
              busy && ["capture", "apply", "readback"].includes(kind),
            );
          }}
          parentGeneration={JSON.stringify([fieldTicket, surfaceTicket])}
          parentCurrent={() =>
            current(owner, fieldTicket) &&
            visible &&
            fieldMode &&
            fieldGeneration.current === surfaceTicket &&
            fieldSurface.current
          }
        />
      </div>
    </details>
  );
}
