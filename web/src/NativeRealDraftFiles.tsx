import { useEffect, useRef, useState } from "react";
import { saveBlob } from "./api";
import { sha256Digest } from "./browserCrypto";
import {
  nativeRealDraftBytes,
  nativeRealDraftDocument,
  parseNativeRealDraft,
} from "./nativeRealDraftFile";

type Data = Record<string, any>;
type Message = { owner: string; text: string };
type Imported = { binding: string; value: string; text: string };
export function NativeRealDraftFiles({
  source,
  field,
  valueText,
  hasDraft,
  blocked,
  parentOwner,
  parentEpoch,
  parentCurrent,
  install,
}: {
  source: Data;
  field: Data;
  valueText: string;
  hasDraft: boolean;
  blocked: boolean;
  parentOwner: string;
  parentEpoch: number;
  parentCurrent: (ticket: number, owner: string) => boolean;
  install: (text: string, ticket: number, owner: string) => boolean;
}) {
  const owner = JSON.stringify([
    parentOwner,
    parentEpoch,
    valueText,
    hasDraft,
    blocked,
  ]);
  const binding = JSON.stringify([
    source.capture_id,
    source.snapshot_sha256,
    field.ref,
    field.encoded_sha256,
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
        nativeRealDraftDocument(source, field, valueText),
        "native-unfinished-real-draft.json",
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
        text: "Discard the selected field draft before importing another. Your existing text was kept.",
      });
      return;
    }
    setPending({ owner, text: "Reading unfinished Real draft…" });
    try {
      if (!file.size || file.size > nativeRealDraftBytes)
        throw new Error(
          "Choose an unfinished Real draft JSON file no larger than 16 KiB.",
        );
      const bytes = await file.arrayBuffer();
      if (!current(ticket)) return;
      if (
        bytes.byteLength !== file.size ||
        bytes.byteLength > nativeRealDraftBytes
      )
        throw new Error(
          "The selected draft file changed while reading; existing text was kept.",
        );
      const raw = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
      const text = parseNativeRealDraft(raw, source, field);
      const fileSha = Array.from(
        new Uint8Array(await sha256Digest(bytes)),
        (b) => b.toString(16).padStart(2, "0"),
      ).join("");
      if (!current(ticket)) return;
      if (!install(text, parentEpoch, parentOwner))
        throw new Error(
          "This draft can no longer be installed. Keep existing work and check for an active controller operation or a full 64-field draft cache before trying again.",
        );
      // Import retires the parent's review epoch immediately. The raw text is
      // now owned by that parent; this local message grants no review authority.
      setSaved({
        binding,
        value: text,
        text: `Imported unfinished text from ${file.name.slice(0, 1024)} · SHA-256 ${fileSha}. Review native compilation separately.`,
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
      aria-label="Unfinished native Real draft files"
      onToggle={(event) => {
        if (!event.currentTarget.open) retire();
      }}
    >
      <summary onClick={retire}>Save or import unfinished Real text</summary>
      <p>
        Save unfinished text to continue on another computer with the same
        original native backup. Import restores ordinary text only. Native
        compilation and controller transfer require separate reviews.
      </p>
      <div className="button-row">
        <button
          type="button"
          onClick={exportDraft}
          disabled={blocked || !hasDraft}
        >
          Save unfinished Real draft
        </button>
        <label>
          Import unfinished Real draft
          <input
            aria-label="Import unfinished Real draft"
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
          Discard the selected field draft before importing a replacement.
          Existing drafts are never evicted.
        </p>
      )}
      {pending?.owner === owner && <p role="status">{pending.text}</p>}
      {error?.owner === owner && <p role="alert">{error.text}</p>}
      {saved?.binding === binding &&
        saved.value === valueText &&
        hasDraft &&
        !blocked && <p role="status">{saved.text}</p>}
    </details>
  );
}
