import { useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import { api, apiBlobDocument, apiJsonDocument, saveBlob } from "./api";
import {
  constantCoordinate,
  constantSource,
  constantReview,
  constantExport,
  constantDraftKey,
  constantDraftSignature,
  rememberConstant,
  constantKinds,
  type ConstantKind,
  type ConstantDrafts,
} from "./cafConstantContract";
import "./caf-constant-copy.css";

type Data = Record<string, any>;
const full =
  "All 32 constant draft slots are retained. Discard an older draft before adding work. No draft was removed.";
export function CafConstantCopy({
  archive,
  filename,
  diagram,
  disabled,
  drafts,
  onDraftChange,
  reviewContext,
  kind = "float",
}: {
  archive: string;
  filename: string;
  diagram: Data;
  disabled: boolean;
  drafts: ConstantDrafts;
  onDraftChange: () => void;
  reviewContext: string;
  kind?: ConstantKind;
}) {
  const spec = constantKinds[kind];
  const comparison = kind === "comparison";
  const primitive = comparison || kind === "math";
  const subject = primitive ? "block" : "constant";
  const base = `/caf/${archive}/${spec.path}`;
  const prototypes = diagram.blocks.filter(
    (b: Data) => b.class_id === spec.classId && b.class_version === "1.0",
  );
  const cached = [...drafts.values()]
    .reverse()
    .find(
      (d) =>
        d.archive === archive &&
        d.diagram === diagram.ref &&
        prototypes.some((b: Data) => b.ref === d.prototype),
    );
  const [chosen, setChosen] = useState(
    cached?.prototype || prototypes[0]?.ref || "",
  );
  const block = prototypes.find((b: Data) => b.ref === chosen);
  const key = constantDraftKey(archive, diagram.ref, chosen);
  const draft = drafts.get(key);
  const [, repaint] = useState(0);
  const [opened, setOpened] = useState(false),
    [life, setLife] = useState(0);
  const [loaded, setLoaded] = useState<{ owner: string; data: Data } | null>(
    null,
  );
  const context = JSON.stringify([
    archive,
    diagram.ref,
    chosen,
    disabled,
    life,
    reviewContext,
    kind,
  ]);
  const contextNow = useRef(context),
    generation = useRef(0),
    alive = useRef(true);
  if (contextNow.current !== context) {
    contextNow.current = context;
    generation.current++;
  }
  const loadOwner = JSON.stringify([context, generation.current]);
  const source = loaded?.owner === loadOwner ? loaded.data : null;
  const x = draft?.x ?? source?.suggested_position.x ?? "";
  const y = draft?.y ?? source?.suggested_position.y ?? "";
  const owner = JSON.stringify([loadOwner, x, y]);
  const ownerNow = useRef(owner),
    epoch = useRef(0);
  if (ownerNow.current !== owner) {
    ownerNow.current = owner;
    epoch.current++;
  }
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
  const [error, setError] = useState<{ owner: string; text: string } | null>(
    null,
  );
  const shown =
    review?.owner === owner && review.epoch === epoch.current ? review : null;
  const busy = pending?.owner === owner && pending.epoch === epoch.current;
  const current = (o: string, n: number) =>
    alive.current && ownerNow.current === o && epoch.current === n;
  const sourceRequest = {
    source_sha256: archive,
    diagram_ref: diagram.ref,
    prototype_ref: chosen,
  };
  const request = source
    ? { ...sourceRequest, selection_sha256: source.selection_sha256, x, y }
    : null;
  const [saved, setSaved] = useState<string | null>(null);
  useEffect(() => {
    alive.current = true;
    const retire = () => {
      epoch.current++;
      generation.current++;
      setLife((n) => n + 1);
      setOpened(false);
      setLoaded(null);
      setReview(null);
      setPending(null);
      setSaved(null);
    };
    const hidden = () => {
      if (document.visibilityState === "hidden") retire();
    };
    window.addEventListener("pagehide", retire);
    document.addEventListener("visibilitychange", hidden);
    return () => {
      alive.current = false;
      epoch.current++;
      generation.current++;
      window.removeEventListener("pagehide", retire);
      document.removeEventListener("visibilitychange", hidden);
    };
  }, []);
  useEffect(() => {
    if (!opened || disabled || !block) return;
    let active = true;
    const ticket = generation.current;
    setError(null);
    api(base + "/source", sourceRequest)
      .then(async (data) => {
        const valid = await constantSource(
          data,
          sourceRequest,
          diagram,
          block,
          kind,
        );
        if (!active || ticket !== generation.current) return;
        if (!valid)
          throw new Error(
            "Constant source proof does not match this CAF and prototype. Inspect again.",
          );
        setLoaded({ owner: loadOwner, data });
      })
      .catch((e) => {
        if (active && ticket === generation.current)
          setError({ owner: ownerNow.current, text: e.message });
      });
    return () => {
      active = false;
    };
  }, [opened, loadOwner]);
  function remember(next: { x?: string; y?: string }) {
    const value = {
      archive,
      diagram: diagram.ref,
      prototype: chosen,
      ...draft,
      ...next,
    };
    if (!rememberConstant(drafts, value)) {
      setError({ owner, text: full });
      return false;
    }
    repaint((n) => n + 1);
    onDraftChange();
    return true;
  }
  function select(next: string) {
    if (disabled || busy) return;
    const previous = drafts.get(constantDraftKey(archive, diagram.ref, next));
    if (
      !rememberConstant(
        drafts,
        previous || { archive, diagram: diagram.ref, prototype: next },
      )
    ) {
      setError({ owner, text: full });
      return;
    }
    setChosen(next);
    onDraftChange();
  }
  async function prepare() {
    if (
      disabled ||
      busy ||
      !request ||
      !constantCoordinate(x) ||
      !constantCoordinate(y) ||
      !remember({ x, y })
    )
      return;
    const o = owner,
      n = ++epoch.current;
    setPending({ owner: o, epoch: n });
    setReview(null);
    setSaved(null);
    setError(null);
    try {
      const result = await apiJsonDocument(base + "/preview", request);
      const valid = await constantReview(result.data, request, source!);
      if (!current(o, n)) return;
      if (!valid)
        throw new Error(
          "Constant review proof changed. Review the current proposal again.",
        );
      setReview({ owner: o, epoch: n, ...result });
    } catch (e: any) {
      if (current(o, n)) setError({ owner: o, text: e.message });
    } finally {
      if (current(o, n)) setPending(null);
    }
  }
  async function save() {
    if (!shown || disabled || busy || !request) return;
    const o = owner,
      n = epoch.current,
      snapshot = shown;
    setPending({ owner: o, epoch: n });
    setError(null);
    try {
      const result = await apiBlobDocument(base + "/export", {
        ...request,
        review_sha256: snapshot.data.review_sha256,
      });
      const valid = await constantExport(result, snapshot.data);
      if (!current(o, n)) return;
      if (!valid)
        throw new Error(
          "CAF download bytes or proof do not match the review. Review again before saving.",
        );
      saveBlob(
        result.blob,
        filename.replace(/\.caf$/i, "") + `-${spec.path}.caf`,
      );
      const value = drafts.get(key);
      if (value && value.x === request.x && value.y === request.y) {
        drafts.set(key, { ...value, saved: constantDraftSignature(value) });
        onDraftChange();
      }
      setSaved(o);
    } catch (e: any) {
      if (current(o, n)) setError({ owner: o, text: e.message });
    } finally {
      if (current(o, n)) setPending(null);
    }
  }
  if (!prototypes.length) return null;
  return (
    <details
      className="caf-constant-copy"
      onToggle={(e) => {
        if (!e.currentTarget.open) {
          epoch.current++;
          generation.current++;
          setLife((n) => n + 1);
          setOpened(false);
          setLoaded(null);
          setReview(null);
          setPending(null);
        }
      }}
    >
      <summary>Copy a recorded {spec.label}</summary>
      <section
        aria-label={primitive ? "CAF block creation" : "CAF constant creation"}
      >
        {comparison ? (
          <p>
            Create a local CAF copy containing a new unconnected comparison and
            four recorded port objects. Setup and input configuration are copied
            as recorded. CCT/PCT acceptance and controller allocation remain
            unverified.
          </p>
        ) : kind === "math" ? (
          <p>
            Create a local CAF copy containing a new unconnected Math block and
            its three or four recorded port objects. Setup, child order and
            input configuration are copied as recorded. CCT/PCT acceptance and
            controller allocation remain unverified.
          </p>
        ) : (
          <p>
            Create a local CAF copy containing a new unconnected constant and
            its output object. Recorded configuration and output value stay with
            the copy. CCT/PCT acceptance and controller allocation remain
            unverified.
          </p>
        )}
        <p>
          This copy starts from the opened archive. Other pending edits are not
          included.
        </p>
        <label>
          {primitive ? "Block prototype" : "Constant prototype"}
          <span className="caf-constant-select">
            <select
              aria-label={primitive ? "Block prototype" : "Constant prototype"}
              value={chosen}
              disabled={disabled || busy}
              onChange={(e) => select(e.target.value)}
            >
              {prototypes.map((b: Data) => (
                <option key={b.ref} value={b.ref}>
                  {b.ref.split(".").at(-1)}
                </option>
              ))}
            </select>
            <ChevronDown size={16} aria-hidden="true" />
          </span>
        </label>
        <button
          disabled={disabled || busy || !block}
          onClick={() => {
            generation.current++;
            setLife((n) => n + 1);
            setOpened(true);
          }}
        >
          Inspect {subject} prototype
        </button>
        {source && (
          <>
            {primitive ? (
              <p>
                Recorded setup code {source.setup_code}; standard-name code{" "}
                {source.standard_name_code}.{" "}
                {source.children.length === 3 ? "Three" : "Four"} port objects
                are copied as recorded; operator meanings and runtime output are
                unverified.
              </p>
            ) : (
              <p>
                Recorded standard-name code {source.standard_name_code}; output{" "}
                {source.recorded_value === null
                  ? "value omitted in source"
                  : source.recorded_value}
                . Both are copied as recorded.
              </p>
            )}
            {comparison && source.enum_semantics_verified === false && (
              <p>
                Enumeration input codes, state metadata and encoding namespaces
                are copied as recorded. Enum meanings remain unverified.
              </p>
            )}
            {primitive && (
              <details>
                <summary>
                  Recorded {comparison ? "comparison" : "math"} inputs
                </summary>
                {source.children
                  .filter((r: Data) => r.port !== 85)
                  .map((r: Data) => (
                    <p key={r.ref}>
                      Port {r.port}:{" "}
                      {r.recorded_default === null
                        ? "default omitted in source"
                        : `recorded default ${r.recorded_default}`}
                      ; {r.exposed ? "exposed" : "not exposed"} in source.
                      {comparison && r.bacnet_type === 19 && (
                        <>
                          {" "}
                          Number Of States: {r.number_of_states}. States Text
                          code: {r.states_text_code} (encoding set{" "}
                          {r.states_text_encoding_set}). Default Value encoding
                          set: {r.default_encoding_set ?? "omitted with value"}.
                        </>
                      )}
                      {kind === "math" &&
                        r.recorded_standard_name_code !== null && (
                          <>
                            {" "}
                            Recorded input standard-name code{" "}
                            {r.recorded_standard_name_code}.
                          </>
                        )}
                    </p>
                  ))}
              </details>
            )}
            {kind === "enumeration" && (
              <details>
                <summary>Recorded enumeration metadata</summary>
                <p>
                  Number Of States: {source.number_of_states}. States Text code:{" "}
                  {source.states_text_code} (encoding set{" "}
                  {source.states_text_encoding_set}). Default Value encoding
                  set: {source.default_encoding_set ?? "omitted with value"}.
                </p>
                <p>
                  Enum meanings are unverified. This copy preserves the recorded
                  code and metadata.
                </p>
              </details>
            )}
            <div className="caf-constant-position">
              {(["x", "y"] as const).map((axis) => (
                <label key={axis}>
                  New {subject} {axis.toUpperCase()}
                  <input
                    aria-label={`New ${subject} ${axis.toUpperCase()}`}
                    value={axis === "x" ? x : y}
                    disabled={disabled || busy}
                    onChange={(e) => remember({ [axis]: e.target.value })}
                  />
                </label>
              ))}
            </div>
            <button
              className={shown ? "" : "primary"}
              disabled={
                disabled ||
                busy ||
                !constantCoordinate(x) ||
                !constantCoordinate(y)
              }
              onClick={prepare}
            >
              Review {subject} CAF copy
            </button>
          </>
        )}
        {draft && (
          <button
            disabled={disabled || busy}
            onClick={() => {
              drafts.delete(key);
              epoch.current++;
              setReview(null);
              setSaved(null);
              repaint((n) => n + 1);
              onDraftChange();
            }}
          >
            Discard {subject} draft
          </button>
        )}
        {error?.owner === owner && <p role="alert">{error.text}</p>}
        {busy && <p role="status">Checking local CAF copy…</p>}
        {shown && (
          <section
            aria-label={
              primitive
                ? "Reviewed CAF block copy"
                : "Reviewed CAF constant copy"
            }
          >
            <p>
              New {subject}:{" "}
              <code>{shown.data.creation.selection.new_ref}</code>
            </p>
            <p>
              Required output:{" "}
              <code>{shown.data.creation.selection.new_output_ref}</code>
            </p>
            <p>
              One graph member and{" "}
              {primitive
                ? shown.data.creation.selection.object_count === 4
                  ? "four"
                  : "five"
                : "two"}{" "}
              objects added. Existing connections and continuation records stay
              unchanged.
            </p>
            <button
              className="primary"
              disabled={disabled || busy}
              onClick={save}
            >
              Save {subject} CAF copy
            </button>
            <button
              disabled={disabled || busy}
              onClick={() => {
                if (current(shown.owner, shown.epoch))
                  saveBlob(shown.blob, `caf-${subject}-review.json`);
              }}
            >
              Save exact {subject} review
            </button>
          </section>
        )}
        {saved === owner && (
          <p role="status">
            Local {subject} CAF copy saved. Open that copy to inspect or connect
            its new block. No controller write was sent.
          </p>
        )}
      </section>
    </details>
  );
}
