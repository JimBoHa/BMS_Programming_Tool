import { useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import { api, apiBlobDocument, apiJsonDocument, saveBlob } from "./api";
import { controllerKey, type ControllerContext } from "./workflow";
import { connectionExport } from "./nativeConnectionContract";
import {
  terminalArchive,
  terminalBase,
  terminalProposal,
  terminalReview,
  terminalSource,
  type TerminalBasis,
} from "./nativeTerminalCopyContract";
import {
  blankTerminalDraft,
  discardTerminalDraft,
  rememberTerminalDraft,
  terminalDraft,
  type TerminalDraft,
} from "./nativeTerminalDrafts";
import type { NativeArchiveSource } from "./NativeRecords";

type Data = Record<string, any>;
const root = "/bacnet/controller/native-application";
const hash = (v: unknown) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
export function NativeTerminalCopy({
  controller,
  connected,
  fieldBusy,
}: {
  controller: ControllerContext | null;
  connected: boolean;
  fieldBusy: boolean;
}) {
  const draftOwner = controller
    ? JSON.stringify([controllerKey(controller), controller.interfaceKey])
    : "offline-native-terminal-copy";
  const context = JSON.stringify([draftOwner, connected, fieldBusy]);
  const contextNow = useRef(context),
    alive = useRef(true),
    epoch = useRef(0);
  if (contextNow.current !== context) {
    contextNow.current = context;
    epoch.current++;
  }
  const [draft, setDraft] = useState<TerminalDraft>(() =>
    terminalDraft(draftOwner),
  );
  const [opened, setOpened] = useState(false),
    [sources, setSources] = useState<Data[]>([]),
    [loaded, setLoaded] = useState<{
      owner: string;
      archive: NativeArchiveSource;
      data: Data;
    } | null>(null);
  const [review, setReview] = useState<{
      owner: string;
      ticket: number;
      data: Data;
      blob: Blob;
    } | null>(null),
    [pending, setPending] = useState<{ owner: string; ticket: number } | null>(
      null,
    ),
    [error, setError] = useState(""),
    [saved, setSaved] = useState("");
  const owner = JSON.stringify([context, draft.capture, draft.basis]);
  const ownerNow = useRef(owner);
  if (ownerNow.current !== owner) {
    ownerNow.current = owner;
    epoch.current++;
  }
  const current = (key: string, ticket: number) =>
    alive.current && ownerNow.current === key && epoch.current === ticket;
  const source = loaded?.owner === owner ? loaded : null;
  const row = source?.data.inventory.inputs.find(
    (p: Data) => p.ref === draft.ref && p.movable,
  );
  const active = opened && !fieldBusy;
  const shown =
    active && review?.owner === owner && review.ticket === epoch.current
      ? review
      : null;
  const busy = pending?.owner === owner && pending.ticket === epoch.current;
  const query = source
    ? {
        capture_id: source.archive.capture_id,
        snapshot_sha256: source.archive.snapshot_sha256,
        source_sha256: source.archive.sha256,
      }
    : null;
  const destination = Number(draft.destination);
  const body =
    source &&
    query &&
    row &&
    draft.destination &&
    source.data.inventory.unassigned_slots.includes(destination)
      ? terminalProposal(source.data, query, row, destination, draft.basis)
      : null;

  function retire() {
    epoch.current++;
    setReview(null);
    setPending(null);
    setSaved("");
    setError("");
  }
  function update(change: Partial<TerminalDraft>) {
    const next = { ...draft, ...change };
    retire();
    if (!rememberTerminalDraft(draftOwner, next)) {
      setError(
        "Local terminal drafts are full (32 workspaces). Save or discard an earlier draft first.",
      );
      return;
    }
    setDraft(next);
  }
  useEffect(() => {
    alive.current = true;
    const stop = () => {
      epoch.current++;
      setReview(null);
      setPending(null);
      setLoaded(null);
      setOpened(false);
      setSaved("");
      setError("");
    };
    const hidden = () => {
      if (document.visibilityState === "hidden") stop();
    };
    window.addEventListener("pagehide", stop);
    document.addEventListener("visibilitychange", hidden);
    return () => {
      alive.current = false;
      epoch.current++;
      window.removeEventListener("pagehide", stop);
      document.removeEventListener("visibilitychange", hidden);
    };
  }, []);
  useEffect(() => {
    retire();
    setLoaded(null);
    setDraft(terminalDraft(draftOwner));
  }, [draftOwner]);
  useEffect(() => {
    retire();
    setLoaded(null);
  }, [context]);
  useEffect(() => {
    if (!active) return;
    const key = owner,
      ticket = ++epoch.current;
    setReview(null);
    setPending({ owner: key, ticket });
    setLoaded(null);
    setError("");
    setSaved("");
    void (async () => {
      try {
        const list = await api(root + "/signal-default/sources");
        if (
          !list ||
          list.profile !== "native-effective-signal-default-compiler/1" ||
          list.controller_queries !== false ||
          !Array.isArray(list.sources) ||
          list.sources.length > 128 ||
          list.sources.some(
            (s: Data) =>
              !s ||
              typeof s.id !== "string" ||
              !/^[a-f0-9]{32}$/.test(s.id) ||
              !hash(s.evidence_sha256) ||
              !s.target ||
              typeof s.target.address !== "string" ||
              typeof s.device !== "string" ||
              !s.identity ||
              typeof s.captured_at !== "string",
          ) ||
          new Set(list.sources.map((s: Data) => s.id)).size !==
            list.sources.length
        )
          throw Error("Unsupported retained native source list.");
        if (!current(key, ticket)) return;
        setSources(list.sources);
        if (!draft.capture) return;
        const selected = list.sources.find((s: Data) => s.id === draft.capture);
        if (!selected)
          throw Error(
            "This retained source is unavailable. Select a current capture.",
          );
        const archive = await api(root + "/inspection/source", {
          capture_id: selected.id,
          snapshot_sha256: selected.evidence_sha256,
        });
        if (!terminalArchive(archive, selected))
          throw Error(
            "Native archive evidence differs from the selected capture.",
          );
        if (!current(key, ticket)) return;
        const data = await api(terminalBase(draft.basis) + "/source", {
          capture_id: archive.capture_id,
          snapshot_sha256: archive.snapshot_sha256,
          source_sha256: archive.sha256,
        });
        if (!terminalSource(data, archive, draft.basis))
          throw Error("Unsupported or mismatched local terminal source.");
        if (current(key, ticket)) setLoaded({ owner: key, archive, data });
      } catch (failure) {
        if (current(key, ticket)) setError(String(failure));
      } finally {
        if (current(key, ticket)) setPending(null);
      }
    })();
  }, [owner, active]);

  async function prepare() {
    if (!body || !source || !active || busy) return;
    const key = owner,
      ticket = ++epoch.current,
      request = body,
      original = source;
    setReview(null);
    setPending({ owner: key, ticket });
    setError("");
    setSaved("");
    try {
      const result = await apiJsonDocument(
        terminalBase(draft.basis) + "/preview",
        request,
      );
      if (
        !(await terminalReview(
          result.data,
          original.archive,
          request,
          original.data,
          draft.basis,
        ))
      )
        throw Error(
          "Terminal review does not match this input, destination and preserved application proof.",
        );
      if (current(key, ticket)) setReview({ owner: key, ticket, ...result });
    } catch (failure) {
      if (current(key, ticket)) setError(String(failure));
    } finally {
      if (current(key, ticket)) setPending(null);
    }
  }
  async function save() {
    if (!shown || !body || !active || busy) return;
    const key = owner,
      ticket = epoch.current;
    setPending({ owner: key, ticket });
    setError("");
    setSaved("");
    try {
      const result = await apiBlobDocument(
        terminalBase(draft.basis) + "/export",
        { ...body, review_sha256: shown.data.review_sha256 },
      );
      if (!(await connectionExport(result, shown.data)))
        throw Error(
          "Terminal-copy bytes or export evidence differ from the reviewed file.",
        );
      if (current(key, ticket)) {
        saveBlob(
          result.blob,
          draft.basis === "effective"
            ? "native-effective-terminal-copy.moi"
            : "native-local-terminal-copy.moi",
        );
        setSaved("Saved a local native copy. No controller was changed.");
      }
    } catch (failure) {
      if (current(key, ticket)) setError(String(failure));
    } finally {
      if (current(key, ticket)) setPending(null);
    }
  }
  return (
    <details
      className="native-boolean-copy"
      aria-label="Local native terminal reassignment"
      open={opened}
      onToggle={(e) => {
        const next = e.currentTarget.open;
        if (next !== opened) {
          retire();
          setOpened(next);
          if (!next) setLoaded(null);
        }
      }}
    >
      <summary>
        <ChevronDown size={16} aria-hidden="true" />
        Reassign an existing local terminal
      </summary>
      {opened && (
        <div>
          <p>
            Save a separate native file moving one existing analog or binary
            input to a free universal terminal on the same controller. Modes,
            scaling and program logic stay unchanged. No controller write or
            physical wiring verification.
          </p>
          {controller && (
            <p>
              <strong>Selected controller:</strong> {controller.name} ·{" "}
              {controller.device} · {controller.router || controller.address} /
              network {controller.dnet ?? "local"} / station{" "}
              {controller.address}.{" "}
              {connected
                ? "Matching interface open."
                : "Interface offline; local copies remain available."}
            </p>
          )}
          <fieldset disabled={fieldBusy}>
            <legend>Local terminal copy source</legend>
            <label>
              Captured terminal source
              <select
                aria-label="Captured terminal source"
                value={draft.capture}
                onChange={(e) =>
                  update({ capture: e.target.value, ref: "", destination: "" })
                }
              >
                <option value="">Select a retained application</option>
                {sources.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.identity["object-name"] || "Unnamed controller"} ·{" "}
                    {s.device} · {s.target.router || s.target.address} /{" "}
                    {s.target.dnet ?? "local"} / {s.target.address} ·{" "}
                    {s.captured_at}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Terminal copy basis
              <select
                aria-label="Terminal copy basis"
                value={draft.basis}
                onChange={(e) =>
                  update({
                    basis: e.target.value as TerminalBasis,
                    ref: "",
                    destination: "",
                  })
                }
              >
                <option value="archive">Original archive</option>
                <option value="effective">
                  Captured saved settings merged
                </option>
              </select>
            </label>
          </fieldset>
          {busy && <p role="status">Checking this local terminal copy…</p>}
          {fieldBusy && (
            <p>
              Finish the active input operation before reviewing a local
              terminal copy.
            </p>
          )}
          {error && (
            <p role="alert" className="inline-error">
              {error}
            </p>
          )}
          {source && (
            <>
              <p>
                <strong>Captured source:</strong>{" "}
                {source.data.identity["object-name"]} ·{" "}
                {source.archive.target.device} ·{" "}
                {source.archive.target.router || source.archive.target.address}{" "}
                / network {source.archive.target.dnet ?? "local"} / station{" "}
                {source.archive.target.address} · {source.data.captured_at}.{" "}
                {draft.basis === "effective"
                  ? "Captured saved values merged; these are not live values."
                  : "Original archive; saved values are not merged."}
              </p>
              <p>
                Configured free local terminals:{" "}
                {source.data.inventory.unassigned_slots
                  .map((n: number) => `UI IN${n}`)
                  .join(", ") || "None"}
                . Integral DPT, SA modules, cross-host and dedicated binary
                terminals are outside this profile.
              </p>
              <fieldset disabled={fieldBusy}>
                <legend>Move one configured input</legend>
                <label>
                  Input to reassign
                  <select
                    aria-label="Input to reassign"
                    value={draft.ref}
                    onChange={(e) =>
                      update({ ref: e.target.value, destination: "" })
                    }
                  >
                    <option value="">Select an existing local input</option>
                    {source.data.inventory.inputs
                      .filter((p: Data) => p.movable)
                      .map((p: Data) => (
                        <option key={p.ref} value={p.ref}>
                          {p.name || p.object} · {p.object} · {p.device_type}
                        </option>
                      ))}
                  </select>
                </label>
                <label>
                  Destination universal terminal
                  <select
                    aria-label="Destination universal terminal"
                    value={draft.destination}
                    onChange={(e) => update({ destination: e.target.value })}
                  >
                    <option value="">Select a configured free terminal</option>
                    {source.data.inventory.unassigned_slots.map((n: number) => (
                      <option key={n} value={n}>
                        UI IN{n}
                      </option>
                    ))}
                  </select>
                </label>
                {!shown && (
                  <button
                    className="primary"
                    disabled={!body || busy}
                    onClick={() => void prepare()}
                  >
                    Review local terminal copy
                  </button>
                )}
              </fieldset>
            </>
          )}
          {shown && (
            <section aria-label="Reviewed local terminal copy">
              <h4>Reviewed local terminal copy</h4>
              <p>
                {row?.object}: UI IN{body?.old_slot} to UI IN
                {body?.destination_slot}. Identity, mode, scaling, graph and
                other bytes preserved in this{" "}
                {draft.basis === "effective"
                  ? "saved-effective"
                  : "original archive"}{" "}
                copy. Saving does not change a controller.
              </p>
              <div className="button-row">
                <button
                  className="primary"
                  disabled={busy || fieldBusy}
                  onClick={() => void save()}
                >
                  Save native terminal copy
                </button>
                <button
                  disabled={busy || fieldBusy}
                  onClick={() => {
                    if (shown)
                      saveBlob(shown.blob, "native-terminal-copy-review.json");
                  }}
                >
                  Save terminal review
                </button>
              </div>
              <details>
                <summary>Terminal preservation evidence</summary>
                <pre>{JSON.stringify(shown.data, null, 2)}</pre>
              </details>
            </section>
          )}
          {saved && <p role="status">{saved}</p>}
          <button
            disabled={busy || fieldBusy}
            onClick={() => {
              retire();
              discardTerminalDraft(draftOwner);
              setDraft(blankTerminalDraft());
              setLoaded(null);
            }}
          >
            Discard terminal draft
          </button>
        </div>
      )}
    </details>
  );
}
