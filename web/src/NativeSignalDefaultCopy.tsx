import { sha256Digest } from "./browserCrypto";
import { useEffect, useRef, useState } from "react";
import { api, apiBlobDocument, saveBlob } from "./api";
import { controllerKey, type ControllerContext } from "./workflow";

const base = "/bacnet/controller/application/signal-default/";
const profile = "tagged-moi-signal-default-copy/1";
const prefix = "bms-native-signal-copy/1/";
const numberText = (value: number) =>
  Object.is(value, -0) ? "-0" : String(value);
const hex = (bytes: ArrayBuffer) =>
  Array.from(new Uint8Array(bytes), (b) =>
    b.toString(16).padStart(2, "0"),
  ).join("");

/** Text is retained by exact source/route. Reviews are never restored. */
export function NativeSignalDefaultCopy({
  controller,
  capture,
  sha256,
  block,
  property,
}: {
  controller: ControllerContext;
  capture: string;
  sha256: string;
  block: Record<string, any>;
  property: Record<string, any>;
}) {
  const target = {
    address: controller.address,
    device: controller.device,
    router: controller.router || null,
    dnet: controller.dnet ?? null,
  };
  const storageKey =
    prefix +
    JSON.stringify([
      controllerKey(controller),
      controller.interfaceKey,
      sha256,
      block.ref,
      property.encoded_sha256,
    ]);
  const [draft, setDraft] = useState(() => {
    try {
      const saved = sessionStorage.getItem(storageKey);
      return {
        text:
          saved !== null && saved.length <= 128
            ? saved
            : numberText(property.scalar.value),
        storageError: "",
      };
    } catch {
      return {
        text: numberText(property.scalar.value),
        storageError:
          "Browser storage is unavailable. Keep this view open to retain this draft.",
      };
    }
  });
  const [review, setReview] = useState<Record<string, any> | null>(null);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [saved, setSaved] = useState("");
  const epoch = useRef(0);
  useEffect(
    () => () => {
      epoch.current++;
    },
    [],
  );
  const body = {
    ...target,
    capture_id: capture,
    source_sha256: sha256,
    record_ref: block.ref,
    encoded_sha256: property.encoded_sha256,
    value_text: draft.text,
  };
  const editText = (text: string) => {
    epoch.current++;
    setReview(null);
    setBusy(false);
    setError("");
    setSaved("");
    let storageError = "";
    try {
      // Bound only this feature's cache; never discard other workspace drafts.
      const keys = Object.keys(sessionStorage).filter(
        (key) => key.startsWith(prefix) && key !== storageKey,
      );
      while (keys.length >= 64) sessionStorage.removeItem(keys.shift()!);
      sessionStorage.setItem(storageKey, text);
    } catch {
      storageError =
        "Browser storage is unavailable. Keep this view open to retain this draft.";
    }
    setDraft({ text, storageError });
  };
  const preview = async () => {
    const run = ++epoch.current;
    setBusy(true);
    setReview(null);
    setError("");
    setSaved("");
    try {
      const result = await api(base + "preview", body);
      if (run !== epoch.current) return;
      if (
        result.profile !== profile ||
        controllerKey(result.target) !== controllerKey(controller) ||
        result.capture_id !== capture ||
        result.controller_write !== false ||
        result.field_actions !== false ||
        result.edit?.source_sha256 !== sha256 ||
        result.edit.record_ref !== block.ref ||
        result.edit.encoded_sha256 !== property.encoded_sha256 ||
        result.edit.value_text !== draft.text ||
        !/^[a-f0-9]{64}$/.test(result.review_sha256)
      )
        throw new Error(
          "The review belongs to a different native source. Review this draft again.",
        );
      setReview(result);
    } catch (failure) {
      if (run === epoch.current) setError(String(failure));
    } finally {
      if (run === epoch.current) setBusy(false);
    }
  };
  const exportCopy = async () => {
    if (!review) return;
    const run = ++epoch.current;
    setBusy(true);
    setError("");
    setSaved("");
    try {
      const result = await apiBlobDocument(base + "export", {
        ...body,
        review_sha256: review.review_sha256,
      });
      const digest = hex(await sha256Digest(await result.blob.arrayBuffer()));
      if (run !== epoch.current) return;
      if (
        result.headers.get("X-Source-SHA256") !== sha256 ||
        result.headers.get("X-Edit-Review-SHA256") !== review.review_sha256 ||
        result.headers.get("X-Output-SHA256") !== digest
      )
        throw new Error(
          "File evidence does not match this review. Review again before saving a copy.",
        );
      saveBlob(result.blob, "controller-signal-default-copy.moi");
      setSaved(
        "File copy saved. Original capture retained; no controller write.",
      );
      setReview(null);
    } catch (failure) {
      if (run === epoch.current) {
        setError(String(failure));
        setReview(null);
      }
    } finally {
      if (run === epoch.current) setBusy(false);
    }
  };
  return (
    <section
      className="native-signal-copy"
      aria-label="Native signal default file copy"
    >
      <h4>Edit default in a file copy</h4>
      <p>
        Change this captured signal’s Real Default Value in a separate file. The
        original capture and live controller stay unchanged. CCT reopening and
        controller acceptance require separate verification.
      </p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (!busy && draft.text.trim()) void preview();
        }}
      >
        <label>
          Proposed signal default
          <input
            aria-label="Proposed signal default"
            type="text"
            inputMode="decimal"
            maxLength={128}
            value={draft.text}
            onChange={(event) => editText(event.target.value)}
          />
        </label>
        {draft.storageError && <p role="status">{draft.storageError}</p>}
        {!review && (
          <button type="submit" disabled={busy || !draft.text.trim()}>
            {busy ? "Reviewing file copy…" : "Review file copy"}
          </button>
        )}
        {review && (
          <div aria-label="Reviewed signal default copy">
            <p>
              Captured default: {numberText(review.edit.before_value)}. Proposed
              text: {review.edit.value_text}. Stored Real:{" "}
              {numberText(review.edit.stored_value)}.
            </p>
            <p>
              {review.edit.changed
                ? "Four native value bytes may change."
                : "No value change; the copy will match the original bytes exactly."}{" "}
              {review.edit.decimal_precision_changed &&
                "The decimal text rounds to the displayed float32 value."}
            </p>
            <details>
              <summary>File-copy review evidence</summary>
              <p>{review.edit.numeric_policy}</p>
              <p>
                Before bits: {review.edit.before_bits}. After bits:{" "}
                {review.edit.after_bits}.
              </p>
              <p>Source SHA-256: {sha256}</p>
              <p>Review SHA-256: {review.review_sha256}</p>
            </details>
            <button
              type="button"
              disabled={busy}
              onClick={() => void exportCopy()}
            >
              {busy ? "Saving file copy…" : "Save edited File copy"}
            </button>
          </div>
        )}
        {error && <p role="alert">{error}</p>}
        {saved && <p role="status">{saved}</p>}
      </form>
    </section>
  );
}
