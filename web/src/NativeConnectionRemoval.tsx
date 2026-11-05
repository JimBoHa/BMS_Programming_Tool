import { useContext, useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import { api, apiBlobDocument, apiJsonDocument, saveBlob } from "./api";
import { NativeBooleanTransferContext } from "./NativeBooleanTransferContext";
import {
  connectionDraftKey,
  connectionExport,
} from "./nativeConnectionContract";
import {
  removalBase,
  removalReview,
  removalSource,
  type RemovalBasis,
} from "./nativeConnectionRemovalContract";
import { rememberWireDraft, type WireCopyDrafts } from "./nativeWireDrafts";
import { controllerKey, type ControllerContext } from "./workflow";
import type { NativeArchiveSource } from "./NativeRecords";

type Data = Record<string, any>;
const full =
  "The 256 retained wire draft slots are full. Discard an older draft before adding work. No existing draft was removed.";
export function NativeConnectionRemoval({
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
  const root = connectionDraftKey(source, record) + "/removal";
  const basisKey = root + "/basis";
  const cachedBasis =
    drafts.get(basisKey) === "effective" ? "effective" : "archive";
  const [basisState, setBasis] = useState({
    key: basisKey,
    value: cachedBasis as RemovalBasis,
  });
  const basis = basisState.key === basisKey ? basisState.value : cachedBasis;
  const indexKey = root + "/" + basis + "/index";
  const cached = Number(drafts.get(indexKey) || 0);
  const initial =
    Number.isInteger(cached) && cached >= 0 && cached <= 4095 ? cached : 0;
  const [chosen, setChosen] = useState({ key: indexKey, value: initial });
  const index = chosen.key === indexKey ? chosen.value : initial;
  const [surfaceOpen, setSurfaceOpen] = useState(false);
  const [opened, setOpened] = useState(false);
  const [reload, setReload] = useState(0);
  const [life, setLife] = useState(0);
  const owner = JSON.stringify([
    root,
    basis,
    index,
    visible,
    surfaceOpen,
    fieldBusy,
    life,
    controller && [
      controllerKey(controller),
      controller.interfaceKey,
      controller.interfaceOpen,
    ],
  ]);
  const ownerNow = useRef(owner),
    epoch = useRef(0),
    loadEpoch = useRef(0),
    alive = useRef(true);
  if (ownerNow.current !== owner) {
    ownerNow.current = owner;
    epoch.current++;
    loadEpoch.current++;
  }
  const [loaded, setLoaded] = useState<{ owner: string; data: Data } | null>(
    null,
  );
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
  const [pending, setPending] = useState<{
    owner: string;
    epoch: number;
  } | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const selection = loaded?.owner === owner ? loaded.data.selection : null;
  const shown =
    review?.owner === owner && review.epoch === epoch.current ? review : null;
  const busy = pending?.owner === owner && pending.epoch === epoch.current;
  const active = visible && surfaceOpen && !fieldBusy;
  const current = (key: string, ticket: number) =>
    alive.current && ownerNow.current === key && epoch.current === ticket;
  const sourceRequest = {
    capture_id: source.capture_id,
    snapshot_sha256: source.snapshot_sha256,
    source_sha256: source.sha256,
    diagram_ref: record.ref,
    record_sha256: record.record_sha256,
    wire_index: index,
  };
  const body = selection?.available
    ? {
        ...sourceRequest,
        property_sha256: selection.property_sha256,
        metadata_property_sha256: selection.metadata_property_sha256,
        old: selection.selected_wire.old,
        connection_count: selection.connection_count,
        ...(basis === "effective"
          ? {
              effective_sha256: loaded!.data.effective_sha256,
              effective_record_sha256: selection.record_sha256,
            }
          : {}),
      }
    : null;

  function retire() {
    epoch.current++;
    loadEpoch.current++;
    setReview(null);
    setPending(null);
    setError(null);
    setSaved(null);
  }
  useEffect(() => {
    alive.current = true;
    const stop = () => {
      epoch.current++;
      loadEpoch.current++;
      setOpened(false);
      setLoaded(null);
      setLoading(null);
      setReview(null);
      setPending(null);
      setError(null);
      setSaved(null);
      setLife((n) => n + 1);
    };
    const hidden = () => {
      if (document.visibilityState === "hidden") stop();
    };
    window.addEventListener("pagehide", stop);
    document.addEventListener("visibilitychange", hidden);
    return () => {
      alive.current = false;
      epoch.current++;
      loadEpoch.current++;
      window.removeEventListener("pagehide", stop);
      document.removeEventListener("visibilitychange", hidden);
    };
  }, []);
  useEffect(() => {
    if (!opened || !active) return;
    const key = owner,
      ticket = ++loadEpoch.current;
    const valid = () =>
      alive.current && ownerNow.current === key && loadEpoch.current === ticket;
    epoch.current++;
    setLoaded(null);
    setReview(null);
    setPending(null);
    setError(null);
    setSaved(null);
    setLoading(key);
    void (async () => {
      try {
        const result = await api(removalBase(basis) + "/source", sourceRequest);
        if (!removalSource(result, source, sourceRequest, basis))
          throw new Error(
            "Native removal source does not match this retained application, diagram and existing connection.",
          );
        if (valid()) setLoaded({ owner: key, data: result });
      } catch (failure) {
        if (valid()) setError({ owner: key, text: String(failure) });
      } finally {
        if (valid()) setLoading(null);
      }
    })();
    return () => {
      loadEpoch.current++;
    };
    // Exact source/basis/index/workspace ownership governs local inspection.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [owner, opened, reload]);

  function changeBasis(value: RemovalBasis) {
    if (value === "archive") drafts.delete(basisKey);
    else if (!rememberWireDraft(drafts, basisKey, value)) {
      setError({ owner, text: full });
      return;
    }
    retire();
    setOpened(false);
    setLoaded(null);
    setBasis({ key: basisKey, value });
  }
  function changeIndex(value: number) {
    if (value === 0) drafts.delete(indexKey);
    else if (!rememberWireDraft(drafts, indexKey, String(value))) {
      setError({ owner, text: full });
      return;
    }
    retire();
    setChosen({ key: indexKey, value });
  }
  async function prepare() {
    if (!body || !loaded || !active || busy) return;
    const key = owner,
      ticket = ++epoch.current,
      request = body,
      original = loaded.data;
    setReview(null);
    setError(null);
    setSaved(null);
    setPending({ owner: key, epoch: ticket });
    try {
      const result = await apiJsonDocument(
        removalBase(basis) + "/preview",
        request,
      );
      if (!(await removalReview(result.data, source, request, original, basis)))
        throw new Error(
          "Native removal review does not match this exact connection and preserved application proof.",
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
    if (!shown || !body || !active || busy) return;
    const key = owner,
      ticket = epoch.current;
    setError(null);
    setSaved(null);
    setPending({ owner: key, epoch: ticket });
    try {
      const result = await apiBlobDocument(removalBase(basis) + "/export", {
        ...body,
        review_sha256: shown.data.review_sha256,
      });
      if (!(await connectionExport(result, shown.data)))
        throw new Error(
          "Native removal output bytes or export proof differ from the reviewed local copy.",
        );
      if (current(key, ticket)) {
        saveBlob(
          result.blob,
          basis === "effective"
            ? "native-effective-connection-removal.moi"
            : "native-connection-removal.moi",
        );
        setSaved(key);
      }
    } catch (failure) {
      if (current(key, ticket)) setError({ owner: key, text: String(failure) });
    } finally {
      if (current(key, ticket)) setPending(null);
    }
  }
  const edit =
    shown &&
    (basis === "effective"
      ? shown.data.compilation.connection_removal
      : shown.data.compilation);
  const disabled = !active || loading === owner || busy;
  return (
    <details
      className="native-wire-copy"
      aria-label="Native connection removal"
      onToggle={(event) => setSurfaceOpen(event.currentTarget.open)}
    >
      <summary>Remove an existing native connection from a local copy</summary>
      <label>
        Connection removal basis
        <span className="wire-copy-select">
          <select
            aria-label="Connection removal basis"
            value={basis}
            disabled={!active}
            onChange={(event) =>
              changeBasis(event.target.value as RemovalBasis)
            }
          >
            <option value="archive">Original archive</option>
            <option value="effective">Saved effective snapshot</option>
          </select>
          <ChevronDown size={16} aria-hidden="true" />
        </span>
      </label>
      <p>
        {basis === "effective"
          ? "Merge this retained snapshot's saved settings before removal. Captured settings are not current live measurements."
          : "Original retained archive. Saved settings are not merged."}{" "}
        Saving this local copy sends no program to a controller.
      </p>
      <button
        className={!selection ? "primary" : undefined}
        disabled={disabled}
        onClick={() => {
          retire();
          setOpened(true);
          setReload((n) => n + 1);
        }}
      >
        Open connections for removal
      </button>
      {loading === owner && (
        <p role="status">Inspecting recorded connections…</p>
      )}
      {error?.owner === owner && <p role="alert">{error.text}</p>}
      {selection && (
        <>
          {basis === "effective" && (
            <p role="status">
              {loaded!.data.parameter_merge.matched_parameters} saved
              application parameters merged before removal.
            </p>
          )}
          {selection.available ? (
            <>
              <label>
                Existing connection to remove
                <span className="wire-copy-select">
                  <select
                    aria-label="Existing connection to remove"
                    value={index}
                    disabled={!active || loading === owner}
                    onChange={(event) =>
                      changeIndex(Number(event.target.value))
                    }
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
              <p>
                {selection.connection_count} recorded connections.{" "}
                {selection.metadata_property_sha256 === null
                  ? "No continuation metadata is recorded."
                  : "The selected connection's aligned continuation row will also be removed."}
              </p>
              <p>
                The destination becomes unwired. Its recorded configuration
                remains unchanged; native fallback or retained-value behavior is
                unverified.
              </p>
              <div className="button-row">
                <button
                  className={!shown ? "primary" : undefined}
                  disabled={disabled || !body}
                  onClick={() => void prepare()}
                >
                  Review connection removal
                </button>
              </div>
            </>
          ) : (
            <p>
              No existing connection is recorded in this diagram. No block or
              input is removed.
            </p>
          )}
        </>
      )}
      {index !== 0 && (
        <button disabled={!active} onClick={() => changeIndex(0)}>
          Discard connection removal selection
        </button>
      )}
      {shown && (
        <section aria-label="Reviewed connection removal">
          <p>
            Remove {edit.source_ref} : {edit.old[1]} → {edit.target_ref} :{" "}
            {edit.old[3]}. Connections: {edit.connection_count_before} →{" "}
            {edit.connection_count_after}.
          </p>
          <p>
            Native structure readback verified. All other expanded bytes,
            members, order, layout and destination configuration are preserved.
          </p>
          <div className="button-row">
            <button
              className="primary"
              disabled={disabled}
              onClick={() => void save()}
            >
              Save native connection removal copy
            </button>
            <button
              disabled={disabled}
              onClick={() => {
                if (current(shown.owner, shown.epoch))
                  saveBlob(shown.blob, "native-connection-removal-review.json");
              }}
            >
              Save exact connection removal review
            </button>
          </div>
          <details>
            <summary>Connection removal details</summary>
            <pre>{JSON.stringify(shown.data.compilation, null, 2)}</pre>
          </details>
        </section>
      )}
      {saved === owner && (
        <p role="status">
          Saved reviewed local connection removal copy. The retained source is
          unchanged.
        </p>
      )}
    </details>
  );
}
