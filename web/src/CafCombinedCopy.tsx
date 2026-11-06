import { useEffect, useRef, useState } from "react";
import { api, apiBlobDocument, apiJsonDocument, saveBlob } from "./api";
import {
  combinedSource,
  combinedReview,
  combinedExport,
  type CombinedWiring,
  type ScalarRow,
  type CombinedCafCopy,
  type OpenCombinedCafCopy,
} from "./cafCombinedCopyContract";

type Data = Record<string, any>;
export function CafCombinedCopy({
  archive,
  filename,
  diagram,
  changes,
  candidates,
  disabled,
  surfaceOpen,
  retireKey,
  sourceCurrent,
  onBusy,
  onSaved,
  onOpenCopy,
  onOpenChange,
}: {
  archive: string;
  filename: string;
  diagram: Data;
  changes: ScalarRow[];
  candidates: Partial<Record<"rewire" | "connect", CombinedWiring>>;
  disabled: boolean;
  surfaceOpen: boolean;
  retireKey: string;
  sourceCurrent: () => boolean;
  onBusy: (busy: boolean) => void;
  onSaved: (kind: "rewire" | "connect") => boolean;
  onOpenCopy?: OpenCombinedCafCopy;
  onOpenChange: (open: boolean) => void;
}) {
  const [opened, setOpened] = useState(false),
    [choice, setChoice] = useState<"" | "rewire" | "connect">(""),
    [life, setLife] = useState(0);
  const kinds = Object.keys(candidates) as ("rewire" | "connect")[];
  const kind = kinds.length === 1 ? kinds[0] : choice;
  const wiring = kind ? candidates[kind] : undefined;
  const request = wiring ? { source_sha256: archive, changes, wiring } : null;
  const owner = JSON.stringify([
    archive,
    diagram,
    request,
    disabled,
    surfaceOpen,
    opened,
    retireKey,
    life,
  ]);
  const now = useRef(owner),
    epoch = useRef(0),
    locked = useRef(false),
    alive = useRef(true);
  if (now.current !== owner) {
    now.current = owner;
    epoch.current++;
  }
  const [pending, setPending] = useState(false),
    [review, setReview] = useState<{
      owner: string;
      ticket: number;
      data: Data;
      blob: Blob;
    } | null>(null),
    [saved, setSaved] = useState<{
      owner: string;
      ticket: number;
      copy: CombinedCafCopy;
    } | null>(null),
    [error, setError] = useState("");
  const callbacks = useRef({ onBusy, onOpenChange });
  callbacks.current = { onBusy, onOpenChange };
  const current = (o: string, t: number) =>
    alive.current &&
    sourceCurrent() &&
    now.current === o &&
    epoch.current === t;
  const shown = review && current(review.owner, review.ticket) ? review : null;
  const copy = saved && current(saved.owner, saved.ticket) ? saved.copy : null;
  const usable =
    opened &&
    surfaceOpen &&
    !disabled &&
    sourceCurrent() &&
    changes.length > 0 &&
    !!wiring;
  function unlock() {
    locked.current = false;
    setPending(false);
    callbacks.current.onBusy(false);
  }
  function retire() {
    epoch.current++;
    setReview(null);
    setSaved(null);
    setError("");
    unlock();
  }
  useEffect(() => {
    unlock();
  }, [owner]);
  useEffect(() => {
    callbacks.current.onOpenChange(opened && surfaceOpen);
    return () => callbacks.current.onOpenChange(false);
  }, [opened, surfaceOpen]);
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
      callbacks.current.onBusy(false);
      window.removeEventListener("pagehide", leave);
      document.removeEventListener("visibilitychange", hidden);
    };
  }, []);
  async function prepare() {
    if (!usable || locked.current || !request) return;
    locked.current = true;
    setPending(true);
    onBusy(true);
    setError("");
    setReview(null);
    setSaved(null);
    const o = owner,
      t = ++epoch.current;
    try {
      const source = await api(`/caf/${archive}/combined-copy/source`, request);
      const valid = await combinedSource(source, request, diagram);
      if (!current(o, t)) return;
      if (!valid)
        throw new Error(
          "Combined source proof does not match these scalar and wiring proposals.",
        );
      const body = { ...request, selection_sha256: source.selection_sha256 };
      const result = await apiJsonDocument(
        `/caf/${archive}/combined-copy/preview`,
        body,
      );
      const accepted = await combinedReview(result.data, body, source, diagram);
      if (!current(o, t)) return;
      if (!accepted)
        throw new Error(
          "Combined review proof changed. Review the current proposals again.",
        );
      setReview({ owner: o, ticket: t, ...result });
    } catch (e) {
      if (current(o, t)) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (current(o, t)) unlock();
    }
  }
  async function save() {
    if (!usable || !shown || locked.current || !kind) return;
    const o = owner,
      t = epoch.current,
      snapshot = shown;
    locked.current = true;
    setPending(true);
    onBusy(true);
    setError("");
    setSaved(null);
    try {
      const result = await apiBlobDocument(
        `/caf/${archive}/combined-copy/export`,
        {
          ...snapshot.data.request,
          review_sha256: snapshot.data.review_sha256,
        },
      );
      const valid = await combinedExport(result, snapshot.data);
      if (!current(o, t)) return;
      if (!valid)
        throw new Error(
          "Combined download bytes or proof differ from the complete review.",
        );
      if (!onSaved(kind))
        throw new Error(
          "Proposals changed before saving. Neither family was marked saved.",
        );
      const name =
        (filename.split(/[\\/]/).at(-1) || "program.caf").replace(
          /\.caf$/i,
          "",
        ) + "-combined.caf";
      saveBlob(result.blob, name);
      setSaved({
        owner: o,
        ticket: t,
        copy: {
          blob: result.blob,
          name,
          sha256: snapshot.data.result.output_sha256,
          sourceArchive: archive,
          diagram: diagram.ref,
          selectionSha256: snapshot.data.result.selection.selection_sha256,
          reviewSha256: snapshot.data.review_sha256,
          unchanged: snapshot.data.result.unchanged,
        },
      });
    } catch (e) {
      if (current(o, t)) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (current(o, t)) unlock();
    }
  }
  async function open() {
    if (!usable || !copy || !onOpenCopy || locked.current) return;
    const o = owner,
      t = epoch.current;
    locked.current = true;
    setPending(true);
    onBusy(true);
    setError("");
    try {
      await onOpenCopy(copy, () => current(o, t));
    } catch (e) {
      if (current(o, t)) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (current(o, t)) unlock();
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
      <summary>Scalar + wiring CAF copy</summary>
      <section aria-label="Combined CAF copy">
        <p>
          Include all {changes.length} current scalar proposals and one selected
          wiring operation in one reviewed local copy. Hardware, instance,
          removal and block creation proposals stay separate. Native execution
          and controller transfer remain unverified.
        </p>
        {!changes.length && (
          <p>
            Add a scalar proposal in Parameters before reviewing a combined
            copy.
          </p>
        )}
        {!kinds.length && (
          <p>
            Choose a replacement source or a new connection destination above.
          </p>
        )}
        {kinds.length > 1 && (
          <label>
            Included wiring operation
            <select
              aria-label="Combined wiring operation"
              value={choice}
              disabled={pending}
              onChange={(e) => {
                retire();
                setChoice(e.target.value as typeof choice);
              }}
            >
              <option value="">Choose one operation…</option>
              <option value="rewire">Rewire selected connection</option>
              <option value="connect">Add selected connection</option>
            </select>
          </label>
        )}
        {wiring && (
          <p>
            Include:{" "}
            {wiring.kind === "rewire"
              ? "rewire selected connection"
              : "add selected connection"}
            .{" "}
            {kinds.length > 1 &&
              "The other wiring proposal remains excluded and retained."}
          </p>
        )}
        {disabled && (
          <p role="note">
            Finish the active operation or save/discard conflicting removal or
            block creation work before combined review.
          </p>
        )}
        <div className="button-row">
          <button
            className={!shown ? "primary" : ""}
            disabled={!usable || pending}
            onClick={() => void prepare()}
          >
            Review scalar + wiring copy
          </button>
          {shown && (
            <button
              className={!copy ? "primary" : ""}
              disabled={!usable || pending}
              onClick={() => void save()}
            >
              Save combined CAF copy
            </button>
          )}
          {copy && onOpenCopy && (
            <button
              className="primary"
              disabled={!usable || pending}
              onClick={() => void open()}
            >
              Open CAF copy
            </button>
          )}
        </div>
        {pending && <p role="status">Checking the complete local copy…</p>}
        {shown && (
          <>
            <p role="status">
              Reviewed {shown.data.result.scalar_changes.length} scalar
              proposals: {shown.data.result.actual_scalar_change_count} changed
              fields and {shown.data.result.actual_wiring_change_count} wiring
              changes.{" "}
              {shown.data.result.unchanged &&
                "Output is the exact unchanged original."}
            </p>
            <div
              className="table-scroll"
              role="region"
              aria-label="Combined scalar review"
              tabIndex={0}
              onKeyDown={(event) => {
                if (
                  event.target !== event.currentTarget ||
                  event.altKey ||
                  event.ctrlKey ||
                  event.metaKey ||
                  event.shiftKey
                )
                  return;
                const table = event.currentTarget;
                if (event.key === "ArrowLeft") table.scrollLeft -= 64;
                else if (event.key === "ArrowRight") table.scrollLeft += 64;
                else if (event.key === "Home") table.scrollLeft = 0;
                else if (event.key === "End")
                  table.scrollLeft = table.scrollWidth;
                else return;
                event.preventDefault();
              }}
            >
              <table>
                <thead>
                  <tr>
                    <th>Reference / property</th>
                    <th>Original</th>
                    <th>Proposed raw text</th>
                    <th>Exported text</th>
                    <th>Changed</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.data.result.scalar_changes.map((row: Data) => (
                    <tr key={JSON.stringify([row.ref, row.property])}>
                      <td style={{ overflowWrap: "anywhere" }}>
                        {row.ref} / {row.property}
                      </td>
                      <td>{row.old}</td>
                      <td>{row.value}</td>
                      <td>{row.exported_value}</td>
                      <td>{row.changed ? "Yes" : "No"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <button
              onClick={() => saveBlob(shown.blob, "caf-combined-review.json")}
            >
              Download combined review
            </button>
            <details>
              <summary>Copy evidence</summary>
              <p style={{ overflowWrap: "anywhere" }}>
                Original: {archive}
                <br />
                Output: {shown.data.result.output_sha256}
                <br />
                Both operation orders and exact allowed XML changes verified.
              </p>
            </details>
          </>
        )}
        {copy && (
          <p role="status">
            Browser download requested for {copy.name}. This view still shows
            the original archive.
          </p>
        )}
        {error && <p role="alert">{error}</p>}
      </section>
    </details>
  );
}
