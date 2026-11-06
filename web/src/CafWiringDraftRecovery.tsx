import { useEffect, useRef, useState } from "react";
import { api, saveBlob } from "./api";
import { connectionSame } from "./nativeConnectionContract";
import {
  wiringSelection,
  wiringDraftToken,
  wiringDraftStatus,
  wiringDraftResult,
  wiringDraftRemoved,
  type WiringSelection,
} from "./cafWiringDraftContract";
type Data = Record<string, any>;
export function CafWiringDraftRecovery({
  id,
  diagram,
  selection,
  context,
  retireKey,
  disabled,
  surfaceOpen,
  sourceCurrent,
  onRestore,
}: {
  id: string;
  diagram: Data;
  selection: WiringSelection;
  context: string;
  retireKey: string;
  disabled: boolean;
  surfaceOpen: boolean;
  sourceCurrent: () => boolean;
  onRestore: (selection: WiringSelection) => boolean;
}) {
  const [opened, setOpened] = useState(false),
    [life, setLife] = useState(0),
    [loaded, setLoaded] = useState<Data | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [replacement, setReplacement] = useState<Data | null>(null);
  const owner = JSON.stringify([
    id,
    diagram,
    selection,
    context,
    retireKey,
    disabled,
    surfaceOpen,
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
  const checkpoint = loaded?.context === context ? loaded.checkpoint : null;
  const saved = checkpoint && !checkpoint.state ? checkpoint : null;
  const expected = wiringDraftToken(checkpoint);
  const hasCurrent = [
    selection.rewire_source_ref,
    selection.connection_source_ref,
    selection.connection_target_ref,
  ].some(Boolean);
  const base = `/caf/${id}/wiring-draft`;
  function unlock() {
    locked.current = false;
    setBusy(false);
  }
  function retire() {
    epoch.current++;
    setError("");
    setNotice("");
    setReplacement(null);
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
      const data = await api(
        base + "?diagram_ref=" + encodeURIComponent(diagram.ref),
      );
      const valid = await wiringDraftStatus(data, id, diagram);
      if (!current(o, t)) return;
      if (!valid)
        throw new Error(
          "Saved wiring status does not match the current source and diagram.",
        );
      setLoaded({
        context,
        checkpoint: data.checkpoint,
        capacity: data.capacity,
      });
    });
  }
  // Only this disclosure fetches checkpoints; it never opens a field interface.
  useEffect(() => {
    if (usable) void refresh();
  }, [opened, surfaceOpen, context, disabled]);
  function save() {
    return run(async (o, t) => {
      if (
        !loaded ||
        loaded.context !== context ||
        checkpoint?.state ||
        !wiringSelection(selection, diagram)
      )
        return;
      const snapshot = structuredClone(selection),
        token = expected;
      const data = await api(base, { selection: snapshot, expected: token });
      const valid = await wiringDraftResult(
        data,
        "save",
        id,
        diagram,
        token,
        snapshot,
      );
      if (!current(o, t)) return;
      if (!valid)
        throw new Error(
          "Saved wiring checkpoint proof differs from the requested selections.",
        );
      setLoaded({
        context,
        checkpoint: data.checkpoint,
        capacity: loaded.capacity,
      });
      setNotice("Unfinished wiring selections saved. No CAF was exported.");
    });
  }
  function apply(checkpoint: Data) {
    if (!sourceCurrent() || !onRestore(checkpoint.selection))
      throw new Error(
        "Wiring selections changed before restoration. Current work was retained.",
      );
    setReplacement(null);
    setNotice(
      "Unfinished wiring selections restored. Export and compatibility checks remain required.",
    );
  }
  function restore() {
    return run(async (o, t) => {
      if (!saved || !expected) return;
      const data = await api(base + "/restore", {
        diagram_ref: diagram.ref,
        expected,
      });
      const valid = await wiringDraftResult(
        data,
        "restore",
        id,
        diagram,
        expected,
      );
      if (!current(o, t)) return;
      if (!valid)
        throw new Error(
          "Restored wiring checkpoint proof differs from the current original source.",
        );
      if (hasCurrent && !connectionSame(selection, data.checkpoint.selection))
        setReplacement({ owner: o, ticket: t, checkpoint: data.checkpoint });
      else apply(data.checkpoint);
    });
  }
  function remove() {
    return run(async (o, t) => {
      if (!expected) return;
      const data = await api(
        base,
        { diagram_ref: diagram.ref, expected },
        "DELETE",
      );
      if (!current(o, t)) return;
      if (!wiringDraftRemoved(data, id, diagram.ref, expected))
        throw new Error(
          "Removed wiring checkpoint proof changed; refresh status.",
        );
      setLoaded({ context, checkpoint: null, capacity: loaded?.capacity });
      setNotice(
        "Saved checkpoint removed. Current wiring selections are retained.",
      );
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
      <summary>Saved wiring draft</summary>
      <section aria-label="Saved CAF wiring draft">
        <p>
          Save unfinished rewire and connection choices for this exact original
          CAF and diagram. A checkpoint restores no successful export,
          compatibility review or controller action.
        </p>
        <div className="button-row">
          <button
            disabled={!usable || busy || !!staged}
            onClick={() => void refresh()}
          >
            Refresh saved wiring draft
          </button>
          <button
            disabled={
              !usable ||
              busy ||
              !!staged ||
              !loaded ||
              loaded.context !== context ||
              !!checkpoint?.state ||
              !hasCurrent
            }
            onClick={() => void save()}
          >
            Save unfinished wiring draft
          </button>
          {saved && (
            <button
              disabled={!usable || busy || !!staged}
              onClick={() => void restore()}
            >
              Restore saved wiring draft
            </button>
          )}
          {expected && (
            <button
              disabled={!usable || busy || !!staged}
              onClick={() => void remove()}
            >
              Remove saved wiring draft
            </button>
          )}
        </div>
        {busy && <p role="status">Checking local wiring checkpoint…</p>}
        {!hasCurrent && (
          <p>
            Choose a replacement source or begin a new connection to save
            unfinished selections.
          </p>
        )}
        {loaded?.context === context && !checkpoint && (
          <p>No wiring checkpoint is saved for this original diagram.</p>
        )}
        {saved && (
          <>
            <p>
              Saved checkpoint revision {saved.revision}, original connection #
              {saved.selection.wire_index}.
            </p>
            <dl>
              <div>
                <dt>Replacement source</dt>
                <dd style={{ overflowWrap: "anywhere" }}>
                  {saved.selection.rewire_source_ref || "(unfinished)"}
                </dd>
              </div>
              <div>
                <dt>New connection source</dt>
                <dd style={{ overflowWrap: "anywhere" }}>
                  {saved.selection.connection_source_ref || "(original source)"}
                </dd>
              </div>
              <div>
                <dt>New connection destination</dt>
                <dd style={{ overflowWrap: "anywhere" }}>
                  {saved.selection.connection_target_ref || "(unfinished)"}
                </dd>
              </div>
            </dl>
            <button
              onClick={() =>
                saveBlob(
                  new Blob([JSON.stringify(saved, null, 2) + "\n"], {
                    type: "application/json",
                  }),
                  "caf-wiring-checkpoint.json",
                )
              }
            >
              Download wiring checkpoint
            </button>
          </>
        )}
        {checkpoint?.state && <p role="alert">{checkpoint.error}</p>}
        {staged && (
          <div role="region" aria-label="Replace current wiring selections">
            <p>
              Current selections differ. Replace them with saved connection #
              {staged.checkpoint.selection.wire_index}? Other edit families
              remain retained.
            </p>
            <button
              disabled={!usable || busy}
              onClick={() => {
                if (!current(staged.owner, staged.ticket)) return;
                try {
                  apply(staged.checkpoint);
                } catch (e) {
                  setError(String(e));
                }
              }}
            >
              Replace current wiring draft
            </button>
            <button onClick={() => setReplacement(null)}>
              Keep current wiring draft
            </button>
          </div>
        )}
        {notice && <p role="status">{notice}</p>}
        {error && <p role="alert">{error}</p>}
      </section>
    </details>
  );
}
