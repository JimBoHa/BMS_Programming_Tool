import { useEffect, useRef, useState } from "react";
import { saveBlob } from "./api";
import { sourceEqual } from "./programSource";
import { sha256Digest } from "./browserCrypto";
import {
  nativeBatchDraftBytes,
  nativeBatchDraftDocument,
  parseNativeBatchDraft,
} from "./nativeBatchDraftFile";

type Data = Record<string, any>;
type Message = { owner: string; text: string };
type Imported = {
  binding: string;
  value: Record<string, string>;
  text: string;
};
export function NativeBatchDraftFiles({
  source,
  opened,
  entries,
  hasDraft,
  blocked,
  parentOwner,
  parentEpoch,
  parentCurrent,
  install,
}: {
  source: Data;
  opened: Data;
  entries: Record<string, string>;
  hasDraft: boolean;
  blocked: boolean;
  parentOwner: string;
  parentEpoch: number;
  parentCurrent: (ticket: number, owner: string) => boolean;
  install: (
    text: Record<string, string>,
    ticket: number,
    owner: string,
  ) => boolean;
}) {
  const owner = JSON.stringify([
    parentOwner,
    parentEpoch,
    entries,
    hasDraft,
    blocked,
  ]);
  const binding = JSON.stringify([
    source.capture_id,
    source.snapshot_sha256,
    opened.source_sha256,
    opened.effective_sha256,
  ]);
  const ownerNow = useRef(owner),
    epoch = useRef(0),
    alive = useRef(true),
    details = useRef<HTMLDetailsElement>(null);
  if (ownerNow.current !== owner) {
    ownerNow.current = owner;
    epoch.current++;
  }
  const renderedEpoch = epoch.current;
  const [, redraw] = useState(0);
  const [error, setError] = useState<Message | null>(null);
  const [saved, setSaved] = useState<Imported | null>(null);
  const [pending, setPending] = useState<Message | null>(null);
  const current = (ticket: number) =>
    alive.current &&
    !blocked &&
    details.current?.open === true &&
    document.visibilityState !== "hidden" &&
    ownerNow.current === owner &&
    epoch.current === ticket &&
    parentCurrent(parentEpoch, parentOwner);
  function retire() {
    epoch.current++;
    setPending(null);
    setError(null);
    redraw((value) => value + 1);
  }
  useEffect(() => {
    alive.current = true;
    const hidden = () => {
      if (document.visibilityState === "hidden") retire();
    };
    document.addEventListener("visibilitychange", hidden);
    window.addEventListener("pagehide", retire);
    return () => {
      alive.current = false;
      epoch.current++;
      document.removeEventListener("visibilitychange", hidden);
      window.removeEventListener("pagehide", retire);
    };
  }, []);
  function exportDraft() {
    if (!hasDraft || !current(renderedEpoch)) return;
    setError(null);
    setSaved(null);
    try {
      saveBlob(
        nativeBatchDraftDocument(source, opened, entries),
        "native-unfinished-batch-draft.json",
      );
    } catch (failure) {
      setError({ owner, text: String(failure) });
    }
  }
  async function importDraft(file: File) {
    if (!current(renderedEpoch)) return;
    const ticket = ++epoch.current;
    if (!current(ticket)) return;
    setError(null);
    setSaved(null);
    if (hasDraft) {
      setError({
        owner,
        text: "Discard the batch draft before importing another. Your existing text was kept.",
      });
      return;
    }
    setPending({ owner, text: "Reading unfinished batch draft…" });
    try {
      if (!file.size || file.size > nativeBatchDraftBytes)
        throw new Error(
          "Choose an unfinished batch draft JSON file no larger than 64 KiB.",
        );
      const bytes = await file.arrayBuffer();
      if (!current(ticket)) return;
      if (
        bytes.byteLength !== file.size ||
        bytes.byteLength > nativeBatchDraftBytes
      )
        throw new Error(
          "The selected draft file changed while reading; existing text was kept.",
        );
      const raw = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
      const text = parseNativeBatchDraft(raw, source, opened);
      const fileSha = Array.from(
        new Uint8Array(await sha256Digest(bytes)),
        (b) => b.toString(16).padStart(2, "0"),
      ).join("");
      if (!current(ticket)) return;
      if (!install(text, parentEpoch, parentOwner))
        throw new Error(
          "This draft can no longer be installed. Keep existing work and check for an active controller operation or a full 32-source batch draft cache before trying again.",
        );
      // Import retires the parent's review epoch immediately. The raw text is
      // now owned by that parent; this local message grants no review authority.
      setSaved({
        binding,
        value: text,
        text: `Imported ${Object.keys(text).length} unfinished batch fields from ${file.name.slice(0, 1024)} · SHA-256 ${fileSha}. Review native compilation separately.`,
      });
    } catch (failure) {
      if (current(ticket)) setError({ owner, text: String(failure) });
    } finally {
      if (
        alive.current &&
        ownerNow.current === owner &&
        epoch.current === ticket
      )
        setPending(null);
    }
  }
  return (
    <details
      ref={details}
      aria-label="Unfinished native batch draft files"
      onToggle={(event) => {
        if (!event.currentTarget.open) retire();
      }}
    >
      <summary onClick={retire}>Save or import unfinished batch text</summary>
      <p>
        Save unfinished text to continue on another computer with the same
        original native backup. Import restores selected raw text only. Native
        compilation and controller transfer require separate reviews.
      </p>
      <div className="button-row">
        <button
          type="button"
          onClick={exportDraft}
          disabled={blocked || !hasDraft}
        >
          Save unfinished batch draft
        </button>
        <label>
          Import unfinished batch draft
          <input
            aria-label="Import unfinished batch draft"
            type="file"
            accept="application/json,.json"
            disabled={blocked}
            onChange={(event) => {
              const file = event.currentTarget.files?.[0];
              event.currentTarget.value = "";
              if (file) void importDraft(file);
            }}
          />
        </label>
      </div>
      {hasDraft && (
        <p>
          Discard the batch draft before importing a replacement. Existing
          drafts are never evicted.
        </p>
      )}
      {pending?.owner === owner && <p role="status">{pending.text}</p>}
      {error?.owner === owner && <p role="alert">{error.text}</p>}
      {saved?.binding === binding &&
        sourceEqual(saved.value, entries) &&
        hasDraft &&
        !blocked && <p role="status">{saved.text}</p>}
    </details>
  );
}
