import { useEffect, useRef, useState } from "react";
import { api, apiBlobDocument, saveBlob } from "./api";
import { sha256Blob } from "./activityContracts";
import { connectionSame } from "./nativeConnectionContract";
import {
  creationCheckpoint,
  creationDraftToken,
  creationDraftStatus,
  creationDraftResult,
  creationDraftRemoved,
  type CreationContext,
  type CreationSelection,
} from "./cafCreationDraftContract";
type Data = Record<string, any>;

export function CafCreationDraftRecovery({
  archive,
  context,
  source,
  x,
  y,
  hasDraft,
  disabled,
  surfaceOpen,
  retireKey,
  sourceCurrent,
  onRestore,
}: {
  archive: string;
  context: CreationContext;
  source: Data | null;
  x: string;
  y: string;
  hasDraft: boolean;
  disabled: boolean;
  surfaceOpen: boolean;
  retireKey: string;
  sourceCurrent: () => boolean;
  onRestore: (selection: CreationSelection) => boolean;
}) {
  const [opened, setOpened] = useState(false),
    [life, setLife] = useState(0),
    [loaded, setLoaded] = useState<Data | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [replacement, setReplacement] = useState<Data | null>(null);
  const key = JSON.stringify([archive, context]);
  const owner = JSON.stringify([
    key,
    source?.selection_sha256,
    x,
    y,
    hasDraft,
    disabled,
    surfaceOpen,
    retireKey,
    opened,
    life,
  ]);
  const ownerNow = useRef(owner),
    epoch = useRef(0),
    alive = useRef(true),
    locked = useRef(false);
  if (ownerNow.current !== owner) {
    ownerNow.current = owner;
    epoch.current++;
  }
  const current = (o: string, t: number) =>
    alive.current &&
    sourceCurrent() &&
    ownerNow.current === o &&
    epoch.current === t;
  const usable = opened && surfaceOpen && !disabled && sourceCurrent();
  const checkpoint = loaded?.key === key ? loaded.checkpoint : null;
  const saved = checkpoint && !checkpoint.state ? checkpoint : null;
  const expected = creationDraftToken(checkpoint);
  const base = `/caf/${archive}/creation-draft`;
  const selection: CreationSelection | null = source
    ? { ...context, selection_sha256: source.selection_sha256, x, y }
    : null;
  function unlock() {
    locked.current = false;
    setBusy(false);
  }
  function retire() {
    epoch.current++;
    setReplacement(null);
    setError("");
    setNotice("");
    unlock();
  }
  useEffect(() => {
    setReplacement(null);
    setError("");
    unlock();
  }, [owner]);
  useEffect(() => {
    alive.current = true;
    const leave = () => {
      retire();
      setOpened(false);
      setLife((n) => n + 1);
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
      window.removeEventListener("pagehide", leave);
      document.removeEventListener("visibilitychange", hidden);
    };
  }, []);
  async function run(action: (o: string, t: number) => Promise<void>) {
    if (!usable || locked.current) return;
    const o = owner,
      t = ++epoch.current;
    locked.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    setReplacement(null);
    try {
      await action(o, t);
    } catch (e) {
      if (current(o, t)) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (current(o, t)) unlock();
    }
  }
  function refresh() {
    return run(async (o, t) => {
      const query = new URLSearchParams(context);
      const data = await api(base + "?" + query);
      const valid = await creationDraftStatus(data, archive, context);
      if (!current(o, t)) return;
      if (!valid)
        throw new Error(
          "Saved copy status does not match this original CAF and prototype.",
        );
      setLoaded({ key, checkpoint: data.checkpoint, capacity: data.capacity });
    });
  }
  // Only an explicit disclosure reads local checkpoints; opening a CAF does not connect.
  useEffect(() => {
    if (usable) void refresh();
  }, [opened, surfaceOpen, key, disabled, source?.selection_sha256]);
  function save() {
    return run(async (o, t) => {
      if (!source || !selection || loaded?.key !== key || checkpoint?.state)
        return;
      const snapshot = structuredClone(selection),
        token = expected;
      const data = await api(base, { selection: snapshot, expected: token });
      const valid = await creationDraftResult(
        data,
        "save",
        archive,
        context,
        source,
        token,
        snapshot,
      );
      if (!current(o, t)) return;
      if (!valid)
        throw new Error(
          "Saved copy checkpoint proof differs from the requested unfinished text.",
        );
      setLoaded({
        key,
        checkpoint: data.checkpoint,
        capacity: loaded.capacity,
      });
      setNotice("Unfinished copy draft saved. No CAF was exported.");
    });
  }
  function apply(value: Data) {
    if (!sourceCurrent() || !onRestore(value.selection))
      throw new Error(
        "Copy choices changed before restoration. Current work was retained.",
      );
    setReplacement(null);
    setNotice(
      "Unfinished copy coordinates restored. Review and export remain required.",
    );
  }
  function restore() {
    return run(async (o, t) => {
      if (!source || !saved || !expected) return;
      const data = await api(base + "/restore", { ...context, expected });
      const valid = await creationDraftResult(
        data,
        "restore",
        archive,
        context,
        source,
        expected,
        undefined,
        saved,
      );
      if (!current(o, t)) return;
      if (!valid)
        throw new Error(
          "Restored copy checkpoint proof differs from the original source or saved generation.",
        );
      if (
        hasDraft &&
        (x !== data.checkpoint.selection.x || y !== data.checkpoint.selection.y)
      )
        setReplacement({ owner: o, ticket: t, checkpoint: data.checkpoint });
      else apply(data.checkpoint);
    });
  }
  function remove() {
    return run(async (o, t) => {
      if (!expected) return;
      const data = await api(base, { ...context, expected }, "DELETE");
      if (!current(o, t)) return;
      if (!creationDraftRemoved(data, archive, context, expected))
        throw new Error(
          "Removed copy checkpoint proof changed; refresh status.",
        );
      setLoaded({ key, checkpoint: null, capacity: loaded?.capacity });
      setNotice(
        "Saved copy checkpoint removed. Current coordinates are retained.",
      );
    });
  }
  function replace() {
    const chosen = replacement;
    if (!chosen || !current(chosen.owner, chosen.ticket)) return;
    return run(async (o, t) => {
      if (!source) return;
      const token = creationDraftToken(chosen.checkpoint);
      if (!token) return;
      const data = await api(base + "/restore", {
        ...context,
        expected: token,
      });
      const valid = await creationDraftResult(
        data,
        "restore",
        archive,
        context,
        source,
        token,
        undefined,
        chosen.checkpoint,
      );
      if (!current(o, t)) return;
      if (!valid)
        throw new Error(
          "Saved copy draft changed before replacement. Refresh its status.",
        );
      apply(data.checkpoint);
    });
  }
  function download() {
    return run(async (o, t) => {
      if (!saved || !expected) return;
      const document = await apiBlobDocument(base + "/report", {
        ...context,
        expected,
      });
      if (document.blob.size > 1024 * 1024)
        throw new Error("Saved copy checkpoint exceeds its byte limit.");
      const value = JSON.parse(await document.blob.text());
      const valid = await creationCheckpoint(value, archive, context);
      const digest = await sha256Blob(document.blob);
      if (!current(o, t)) return;
      if (
        !valid ||
        !connectionSame(value, saved) ||
        document.headers.get("X-Studio-Artifact-Sha256") !== digest
      )
        throw new Error(
          "Saved copy checkpoint bytes differ from the selected generation.",
        );
      saveBlob(document.blob, "caf-copy-checkpoint.json");
    });
  }
  const staged =
    replacement && current(replacement.owner, replacement.ticket)
      ? replacement
      : null;
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
      <summary>Saved copy draft</summary>
      <section aria-label="Saved CAF copy draft">
        <p>
          Keep unfinished coordinates for this original CAF and recorded
          prototype. A checkpoint restores no review, successful export or
          controller action.
        </p>
        <div className="button-row">
          <button
            disabled={!usable || busy || !!staged}
            onClick={() => void refresh()}
          >
            Refresh saved copy draft
          </button>
          <button
            disabled={
              !usable ||
              busy ||
              !!staged ||
              !source ||
              !selection ||
              !hasDraft ||
              loaded?.key !== key ||
              !!checkpoint?.state
            }
            onClick={() => void save()}
          >
            Save unfinished copy draft
          </button>
          {saved && (
            <button
              disabled={!usable || busy || !!staged || !source}
              onClick={() => void restore()}
            >
              Restore saved copy draft
            </button>
          )}
          {expected && (
            <button
              disabled={!usable || busy || !!staged}
              onClick={() => void remove()}
            >
              Remove saved copy draft
            </button>
          )}
          {saved && (
            <button
              disabled={!usable || busy || !!staged}
              onClick={() => void download()}
            >
              Download copy checkpoint
            </button>
          )}
        </div>
        {!source && (
          <p>
            Inspect the original prototype before saving or restoring
            coordinates.
          </p>
        )}
        {loaded?.key === key && !checkpoint && (
          <p>No copy checkpoint is saved for this original prototype.</p>
        )}
        {saved && (
          <p>
            Saved checkpoint revision {saved.revision}. Original prototype:{" "}
            <code>{saved.selection.prototype_ref}</code>.
          </p>
        )}
        {busy && <p role="status">Checking local copy checkpoint…</p>}
        {checkpoint?.state && <p role="alert">{checkpoint.error}</p>}
        {staged && (
          <div role="region" aria-label="Replace current copy coordinates">
            <p>
              Current coordinates differ. Replace this prototype’s current draft
              with its saved coordinates?
            </p>
            <div
              className="table-scroll"
              tabIndex={0}
              role="region"
              aria-label="Copy coordinate comparison"
            >
              <table>
                <thead>
                  <tr>
                    <th scope="col">Coordinate</th>
                    <th scope="col">Current text</th>
                    <th scope="col">Saved text</th>
                  </tr>
                </thead>
                <tbody>
                  {(["x", "y"] as const).map((axis) => (
                    <tr key={axis}>
                      <th scope="row">{axis.toUpperCase()}</th>
                      <td>
                        <code>{JSON.stringify(axis === "x" ? x : y)}</code>
                      </td>
                      <td>
                        <code>
                          {JSON.stringify(staged.checkpoint.selection[axis])}
                        </code>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <button disabled={!usable || busy} onClick={() => void replace()}>
              Replace current copy draft
            </button>
            <button
              disabled={!usable || busy}
              onClick={() => {
                retire();
                setNotice("Current coordinates retained.");
              }}
            >
              Keep current copy draft
            </button>
          </div>
        )}
        {error && <p role="alert">{error}</p>}
        {notice && <p role="status">{notice}</p>}
      </section>
    </details>
  );
}
