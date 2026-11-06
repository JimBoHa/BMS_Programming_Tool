import { useEffect, useRef, useState } from "react";
import { api, apiBlobDocument, apiJsonDocument, saveBlob } from "./api";
import {
  cafRemovalSource,
  cafRemovalRequest,
  cafRemovalReview,
  cafRemovalExport,
  type CafRemovalDiagram,
  type CafRemovalWire,
  type OpenRemovedCafCopy,
  type RemovedCafCopy,
} from "./cafConnectionRemovalContract";
import {
  cafRemovalKey,
  cafRemovalSignature,
  cafRemovalDirty,
  rememberCafRemoval,
  type CafRemovalDrafts,
} from "./cafRemovalDrafts";

type Data = Record<string, any>;
const identityStyle = { overflowWrap: "anywhere" } as const;
export function CafConnectionRemoval({
  archive,
  filename,
  diagram,
  wire,
  objectCount,
  sourceCurrent,
  disabled,
  surfaceOpen,
  retireKey,
  reviewContext,
  conflict,
  drafts,
  onDraftChange,
  onBusyChange,
  onOpenChange,
  onSelectWire,
  onOpenCopy,
}: {
  archive: string;
  filename: string;
  diagram: CafRemovalDiagram;
  wire?: CafRemovalWire;
  objectCount: number;
  sourceCurrent: () => boolean;
  disabled: boolean;
  surfaceOpen: boolean;
  retireKey: string;
  reviewContext: string;
  conflict: boolean;
  drafts: CafRemovalDrafts;
  onDraftChange: () => void;
  onBusyChange: (busy: boolean) => void;
  onOpenChange: (open: boolean) => void;
  onSelectWire: (index: number) => void;
  onOpenCopy?: OpenRemovedCafCopy;
}) {
  const [opened, setOpened] = useState(false),
    [life, setLife] = useState(0);
  const key = cafRemovalKey(archive, diagram.ref),
    draft = drafts.get(key);
  const selected = wire
    ? {
        archive,
        diagram: diagram.ref,
        index: wire.index,
        old: wire.raw,
        count: diagram.connections.length,
      }
    : null;
  const sameDraft =
    !!draft &&
    !!selected &&
    cafRemovalSignature(draft) === cafRemovalSignature(selected);
  const held = !!draft && cafRemovalDirty(draft) && !sameDraft;
  const context = JSON.stringify([
    archive,
    diagram,
    wire?.index,
    disabled,
    surfaceOpen,
    opened,
    retireKey,
    reviewContext,
    conflict,
    life,
  ]);
  const ownerNow = useRef(context),
    epoch = useRef(0),
    alive = useRef(true),
    locked = useRef(false);
  if (ownerNow.current !== context) {
    ownerNow.current = context;
    epoch.current++;
  }
  const [pending, setPending] = useState<{
    owner: string;
    epoch: number;
  } | null>(null);
  const [review, setReview] = useState<{
    owner: string;
    epoch: number;
    data: Data;
    source: Data;
    request: Data;
    blob: Blob;
  } | null>(null);
  const [created, setCreated] = useState<{
    owner: string;
    epoch: number;
    copy: RemovedCafCopy;
  } | null>(null);
  const [error, setError] = useState<{ owner: string; text: string } | null>(
    null,
  );
  const current = (owner: string, ticket: number) =>
    alive.current &&
    sourceCurrent() &&
    ownerNow.current === owner &&
    epoch.current === ticket;
  const busy = !!pending && current(pending.owner, pending.epoch);
  const shown = review && current(review.owner, review.epoch) ? review : null;
  const openable =
    created && current(created.owner, created.epoch) ? created : null;
  const usable =
    opened &&
    sourceCurrent() &&
    surfaceOpen &&
    !disabled &&
    !conflict &&
    !!wire &&
    !held;
  const callbacks = useRef({ onBusyChange });
  callbacks.current = { onBusyChange };
  function unlock() {
    locked.current = false;
    setPending(null);
    callbacks.current.onBusyChange(false);
  }
  function retire() {
    epoch.current++;
    setReview(null);
    setCreated(null);
    setError(null);
    unlock();
  }
  useEffect(() => {
    unlock();
  }, [context]);
  useEffect(() => {
    onOpenChange(opened && surfaceOpen);
    return () => onOpenChange(false);
  }, [opened, surfaceOpen, onOpenChange]);
  useEffect(() => {
    alive.current = true;
    const leave = () => {
      retire();
      setLife((n) => n + 1);
      setOpened(false);
    };
    const hidden = () => {
      if (document.visibilityState === "hidden") leave();
    };
    window.addEventListener("pagehide", leave);
    document.addEventListener("visibilitychange", hidden);
    return () => {
      alive.current = false;
      epoch.current++;
      locked.current = false;
      callbacks.current.onBusyChange(false);
      window.removeEventListener("pagehide", leave);
      document.removeEventListener("visibilitychange", hidden);
    };
  }, []);
  function start() {
    if (!usable || locked.current) return null;
    locked.current = true;
    const owner = context,
      ticket = ++epoch.current;
    setPending({ owner, epoch: ticket });
    callbacks.current.onBusyChange(true);
    setError(null);
    return { owner, ticket };
  }
  async function prepare() {
    if (!usable || locked.current || !wire || !selected) return;
    if (!rememberCafRemoval(drafts, sameDraft ? draft! : selected)) {
      setError({
        owner: context,
        text: "All 32 removal draft slots are retained. Discard an older removal proposal before adding work. No draft was removed.",
      });
      return;
    }
    onDraftChange();
    const action = start();
    if (!action) return;
    const { owner, ticket } = action;
    setReview(null);
    setCreated(null);
    const base = `/caf/${archive}/connection-removal`;
    try {
      const sourceRequest = {
        source_sha256: archive,
        diagram_ref: diagram.ref,
        wire_index: wire.index,
      };
      const source = await api(base + "/source", sourceRequest);
      const valid = await cafRemovalSource(
        source,
        sourceRequest,
        diagram,
        wire,
      );
      if (!current(owner, ticket)) return;
      if (!valid)
        throw new Error(
          "Connection removal source proof does not match the selected original wire. Review again.",
        );
      const request = cafRemovalRequest(source);
      const result = await apiJsonDocument(base + "/preview", request);
      const reviewed = await cafRemovalReview(
        result.data,
        request,
        source,
        objectCount,
      );
      if (!current(owner, ticket)) return;
      if (!reviewed)
        throw new Error(
          "Connection removal review proof changed. Review the selected wire again.",
        );
      setReview({ owner, epoch: ticket, source, request, ...result });
    } catch (e) {
      if (current(owner, ticket))
        setError({ owner, text: e instanceof Error ? e.message : String(e) });
    } finally {
      if (current(owner, ticket)) unlock();
    }
  }
  async function save() {
    if (!usable || !shown || locked.current) return;
    // Preserve this reviewed epoch while an export is pending.
    const owner = context,
      ticket = epoch.current,
      snapshot = shown;
    locked.current = true;
    setPending({ owner, epoch: ticket });
    onBusyChange(true);
    setError(null);
    setCreated(null);
    try {
      const result = await apiBlobDocument(
        `/caf/${archive}/connection-removal/export`,
        { ...snapshot.request, review_sha256: snapshot.data.review_sha256 },
      );
      const valid = await cafRemovalExport(result, snapshot.data);
      if (!current(owner, ticket)) return;
      if (!valid)
        throw new Error(
          "CAF removal download bytes or proof do not match the review. Review again before saving.",
        );
      const basename = filename.split(/[\\/]/).at(-1) || "program.caf";
      const name = basename.replace(/\.caf$/i, "") + "-connection-removed.caf";
      saveBlob(result.blob, name);
      setCreated({
        owner,
        epoch: ticket,
        copy: {
          blob: result.blob,
          name,
          sha256: snapshot.data.removal.output_sha256,
          sourceArchive: archive,
          diagram: diagram.ref,
          selectionSha256: snapshot.source.selection_sha256,
          reviewSha256: snapshot.data.review_sha256,
        },
      });
      const stored = drafts.get(key);
      if (
        stored &&
        selected &&
        cafRemovalSignature(stored) === cafRemovalSignature(selected)
      ) {
        drafts.set(key, { ...stored, saved: cafRemovalSignature(stored) });
        onDraftChange();
      }
    } catch (e) {
      if (current(owner, ticket))
        setError({ owner, text: e instanceof Error ? e.message : String(e) });
    } finally {
      if (current(owner, ticket)) unlock();
    }
  }
  async function openCopy() {
    if (!usable || !openable || !onOpenCopy || locked.current) return;
    const owner = context,
      ticket = epoch.current;
    locked.current = true;
    setPending({ owner, epoch: ticket });
    onBusyChange(true);
    setError(null);
    try {
      await onOpenCopy(openable.copy, () => current(owner, ticket));
    } catch (e) {
      if (current(owner, ticket))
        setError({ owner, text: e instanceof Error ? e.message : String(e) });
    } finally {
      if (current(owner, ticket)) unlock();
    }
  }
  return (
    <details
      className="caf-connection-create"
      open={opened}
      onToggle={(e) => {
        if (e.currentTarget.open !== opened) {
          retire();
          setOpened(e.currentTarget.open);
        }
      }}
    >
      <summary>Remove selected connection</summary>
      <section aria-label="CAF connection removal">
        <p>
          Remove one original connection and its paired continuation from a
          separate CAF copy. Blocks, execution order, layout and destination
          configuration stay unchanged. CCT/PCT acceptance, native execution and
          controller transfer remain unverified.
        </p>
        {wire ? (
          <dl>
            <div>
              <dt>Selected original record</dt>
              <dd>
                #{wire.index} of {diagram.connections.length} ·{" "}
                <code style={identityStyle}>{JSON.stringify(wire.raw)}</code>
              </dd>
            </div>
            <div>
              <dt>Source</dt>
              <dd>
                <code style={identityStyle}>{wire.source_ref}</code> · property{" "}
                {wire.source_port}
              </dd>
            </div>
            <div>
              <dt>Destination</dt>
              <dd>
                <code style={identityStyle}>{wire.target_ref}</code> · property{" "}
                {wire.target_port}
              </dd>
            </div>
          </dl>
        ) : (
          <p>This diagram has no selected connection to remove.</p>
        )}
        {draft && (
          <p role="note">
            Retained removal proposal: connection #{draft.index}.{" "}
            {cafRemovalDirty(draft)
              ? "Not exported."
              : "A copy was exported; the original archive is still unchanged."}
          </p>
        )}
        {held && (
          <p role="note">
            Another original wire is retained for removal in this diagram.
            Return to that selection or discard it before reviewing this wire.{" "}
            <button
              disabled={disabled || busy}
              onClick={() => onSelectWire(draft!.index)}
            >
              Select retained connection #{draft!.index}
            </button>
          </p>
        )}
        {conflict && (
          <p role="note">
            Another unexported graph proposal is retained for this CAF. Export
            and open its copy, or discard that proposal before reviewing
            removal. No proposals were combined.
          </p>
        )}
        <div className="button-row">
          <button
            className={!shown ? "primary" : ""}
            disabled={!usable || busy}
            onClick={() => void prepare()}
          >
            Review connection removal
          </button>
          {draft && (
            <button
              disabled={disabled || busy}
              onClick={() => {
                retire();
                drafts.delete(key);
                onDraftChange();
              }}
            >
              Discard removal proposal
            </button>
          )}
        </div>
        {busy && <p role="status">Checking the selected CAF removal…</p>}
        {error?.owner === context && <p role="alert">{error.text}</p>}
        {shown && (
          <section aria-label="Reviewed CAF connection removal">
            <h4>Reviewed connection #{shown.source.wire_index} removal</h4>
            <p>
              {shown.source.connection_count} →{" "}
              {shown.data.removal.remaining_connection_count} connections. One
              connection and its aligned continuation will be removed.
            </p>
            <p>
              {shown.source.target_remaining_writer_count === 0
                ? "No recorded writer remains on this destination port after removal. Unwired fallback and native execution remain unverified."
                : `${shown.source.target_remaining_writer_count} other recorded writer(s) remain on this destination port. Their runtime behavior remains unverified.`}
            </p>
            <p>
              The original file and displayed graph remain unchanged until you
              explicitly open the saved copy.
            </p>
            <div className="button-row">
              <button
                className={openable ? "" : "primary"}
                disabled={!usable || busy}
                onClick={() => void save()}
              >
                Save connection removal CAF copy
              </button>
              <button
                disabled={!usable || busy}
                onClick={() => {
                  if (current(shown.owner, shown.epoch))
                    saveBlob(shown.blob, "caf-connection-removal-review.json");
                }}
              >
                Save exact removal review
              </button>
              {openable && onOpenCopy && (
                <button
                  className="primary"
                  disabled={!usable || busy}
                  onClick={() => void openCopy()}
                >
                  Open CAF copy
                </button>
              )}
            </div>
            {openable && (
              <p role="status">
                Verified CAF copy download requested. Opening it is a separate
                local action.
              </p>
            )}
            <details>
              <summary>Removal evidence</summary>
              <dl>
                <div>
                  <dt>Original CAF SHA-256</dt>
                  <dd>
                    <code style={identityStyle}>{archive}</code>
                  </dd>
                </div>
                <div>
                  <dt>Paired continuation</dt>
                  <dd>
                    {String(shown.source.continuation.flag)} ·{" "}
                    {shown.source.continuation.text || "(empty text)"}
                  </dd>
                </div>
                <div>
                  <dt>Output CAF SHA-256</dt>
                  <dd>
                    <code style={identityStyle}>
                      {shown.data.removal.output_sha256}
                    </code>
                  </dd>
                </div>
                <div>
                  <dt>Review SHA-256</dt>
                  <dd>
                    <code style={identityStyle}>
                      {shown.data.review_sha256}
                    </code>
                  </dd>
                </div>
              </dl>
            </details>
          </section>
        )}
      </section>
    </details>
  );
}
