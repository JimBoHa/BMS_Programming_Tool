import { useEffect, useId, useMemo, useRef, useState } from "react";
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
  enumSelectorMultiplexerProfile,
  enumMultiplexerProfile,
  enumEnumSelectorMultiplexerProfile,
  hasEnumMultiplexerOutput,
  hasBooleanMultiplexerOutput,
  booleanEnumSelectorMultiplexerProfile,
  type ConstantKind,
  type ConstantDrafts,
} from "./cafConstantContract";
import "./caf-constant-copy.css";
import {
  creationHintFor,
  type CafCreationHint,
  type CreatedCafCopy,
  type OpenCafCopy,
} from "./cafCreatedCopy";
import type { ReferenceState } from "./cafReferenceLabels";
import { CafCreationDraftRecovery } from "./CafCreationDraftRecovery";

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
  referenceLabels,
  creationHint,
  onOpenCopy,
  checkpointEpoch: sharedCheckpointEpoch,
  checkpointCurrent = () => true,
  checkpointRetireKey = "",
}: {
  archive: string;
  filename: string;
  diagram: Data;
  disabled: boolean;
  drafts: ConstantDrafts;
  onDraftChange: () => void;
  reviewContext: string;
  kind?: ConstantKind;
  referenceLabels?: ReferenceState;
  creationHint?: CafCreationHint | null;
  onOpenCopy?: OpenCafCopy;
  checkpointEpoch?: { current: number };
  checkpointCurrent?: () => boolean;
  checkpointRetireKey?: string;
}) {
  const localCheckpointEpoch = useRef(0);
  const checkpointEpoch = sharedCheckpointEpoch || localCheckpointEpoch;
  const spec = constantKinds[kind];
  const comparison = kind === "comparison";
  const timer = kind === "timer";
  const booleanLogic = kind === "booleanLogic";
  const reliability = kind === "reliability";
  const multiplexer = kind === "multiplexer";
  const primitive =
    comparison ||
    kind === "math" ||
    timer ||
    booleanLogic ||
    reliability ||
    multiplexer;
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
  const preferred = creationHintFor(creationHint, archive, {
    ref: diagram.ref,
    blocks: diagram.blocks,
  });
  const [chosen, setChosen] = useState(
    (preferred?.kind === kind ? preferred.prototype : "") ||
      cached?.prototype ||
      prototypes[0]?.ref ||
      "",
  );
  const block = prototypes.find((b: Data) => b.ref === chosen);
  const references = useMemo(
    () =>
      new Map<string, Data>(
        (referenceLabels?.data?.rows ?? []).map((r: Data) => [r.ref, r]),
      ),
    [referenceLabels?.data],
  );
  const referenceRow = references.get(chosen);
  const [referenceOpen, setReferenceOpen] = useState(false);
  const referenceId = useId();
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
  const [created, setCreated] = useState<{
    owner: string;
    epoch: number;
    copy: CreatedCafCopy;
  } | null>(null);
  const openingCopy = useRef<{ owner: string; epoch: number } | null>(null);
  const openable =
    onOpenCopy &&
    created?.owner === owner &&
    created.epoch === epoch.current &&
    saved === owner
      ? created
      : null;
  useEffect(() => {
    setCreated(null);
  }, [owner]);

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
      setCreated(null);
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
    checkpointEpoch.current++;
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
    checkpointEpoch.current++;
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
      const suffix = hasEnumMultiplexerOutput(source?.profile)
        ? "enum-multiplexer-copy"
        : hasBooleanMultiplexerOutput(source?.profile)
          ? "boolean-multiplexer-copy"
          : spec.path;
      const name = filename.replace(/\.caf$/i, "") + `-${suffix}.caf`;
      saveBlob(result.blob, name);
      setCreated({
        owner: o,
        epoch: n,
        copy: {
          blob: result.blob,
          name,
          sha256: snapshot.data.creation.output_sha256,
          sourceArchive: archive,
          diagram: diagram.ref,
          prototype: snapshot.data.creation.selection.new_ref,
          kind,
        },
      });
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
  async function openCopy() {
    if (!openable || !onOpenCopy || disabled || busy) return;
    const o = owner,
      n = epoch.current,
      copy = openable.copy;
    if (openingCopy.current?.owner === o && openingCopy.current.epoch === n)
      return;
    openingCopy.current = { owner: o, epoch: n };
    setPending({ owner: o, epoch: n });
    setError(null);
    try {
      await onOpenCopy(copy, () => current(o, n));
    } catch (e: any) {
      if (current(o, n)) setError({ owner: o, text: e.message });
    } finally {
      if (openingCopy.current?.owner === o && openingCopy.current.epoch === n)
        openingCopy.current = null;
      if (current(o, n)) setPending(null);
    }
  }
  if (!prototypes.length) return null;
  const checkpointTicket = checkpointEpoch.current;
  const checkpointGeneration = generation.current;
  const checkpointSourceCurrent = () =>
    alive.current &&
    !disabled &&
    opened &&
    checkpointCurrent() &&
    contextNow.current === context &&
    generation.current === checkpointGeneration &&
    checkpointEpoch.current === checkpointTicket;
  return (
    <details
      className="caf-constant-copy"
      onToggle={(e) => {
        if (!e.currentTarget.open) {
          checkpointEpoch.current++;
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
        ) : booleanLogic ? (
          <p>
            Create a local CAF copy containing a new unconnected Boolean logic
            block and its three or four recorded ports. Child order and omitted
            defaults stay exact. Operator behavior, CCT/PCT acceptance and
            controller allocation remain unverified.
          </p>
        ) : reliability ? (
          <p>
            Create a local CAF copy containing a new unconnected Reliability
            Check and its two recorded ports. Boolean output spelling, omitted
            defaults and Enum metadata stay exact. Reliability behavior, CCT/PCT
            acceptance and controller allocation remain unverified.
          </p>
        ) : multiplexer ? (
          <p>
            Create a local CAF copy containing a new unconnected Multiplexer and
            its recorded ports. Inspection identifies the supported Float,
            Boolean or Enum I/O profile and selector. Stored configuration and
            omitted defaults stay exact. Other variants require a separate
            profile. Mode/Enum behavior, CCT/PCT acceptance and controller
            allocation remain unverified.
          </p>
        ) : timer ? (
          <p>
            Create a local CAF copy containing a new unconnected Timer and all
            seven recorded ports, including four hidden ports and both outputs.
            Stored values and metadata stay exact. Timer behavior, CCT/PCT
            acceptance and controller allocation remain unverified.
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
              {prototypes.map((b: Data) => {
                const referenceName = references.get(b.ref)?.standard_name
                  .reference_name;
                return (
                  <option key={b.ref} value={b.ref}>
                    {b.ref.split(".").at(-1)}
                    {referenceName ? ` · ${referenceName} (reference)` : ""}
                  </option>
                );
              })}
            </select>
            <ChevronDown size={16} aria-hidden="true" />
          </span>
        </label>
        {referenceLabels?.error && (
          <p role="note" aria-label="Reference-name availability">
            {referenceLabels.error}
          </p>
        )}
        {source && referenceRow && (
          <div>
            <button
              type="button"
              aria-expanded={referenceOpen}
              aria-controls={referenceId}
              onClick={() => setReferenceOpen((v) => !v)}
            >
              Reference names and provenance
            </button>
            <div id={referenceId} hidden={!referenceOpen}>
              <p>
                Reference standard name:{" "}
                {referenceRow.standard_name.reference_name ??
                  "unmapped; raw reference retained"}
                .
              </p>
              <p>
                Reference setup:{" "}
                {referenceRow.setup.reference_name ??
                  "unmapped or absent; no setup inferred"}
                .
              </p>
              <p>
                Catalog: FDB Control 10.8 / Firmware 12.0. Compatibility with
                this archive and runtime meaning remain unverified.
              </p>
              <p>
                Actual source codes and names stay unchanged. These labels grant
                no compile, deployment or field authority.
              </p>
              <p>
                Catalog source:{" "}
                <a
                  href="https://github.com/thecontrolscompany/oct/blob/c1d76ba7d6a8f17ca089c4671fa3333e4eba43e2/ui/src/data/fdbEnums.ts"
                  target="_blank"
                  rel="noreferrer"
                >
                  OCT exported reference names
                </a>
                .
              </p>
            </div>
          </div>
        )}
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
                {timer || reliability || multiplexer ? (
                  "Recorded standard-name code "
                ) : (
                  <>
                    Recorded setup code {source.setup_code}; standard-name
                    code{" "}
                  </>
                )}
                {source.standard_name_code}.{" "}
                {timer
                  ? "Seven"
                  : reliability
                    ? "Two"
                    : multiplexer && source.children.length === 6
                      ? "Six"
                      : source.children.length === 3
                        ? "Three"
                        : "Four"}{" "}
                port objects are copied as recorded; operator meanings and
                runtime output are unverified.
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
            {(comparison || multiplexer) &&
              source.enum_semantics_verified === false && (
                <p>
                  Enumeration input codes, state metadata and encoding
                  namespaces are copied as recorded. Enum meanings remain
                  unverified.
                </p>
              )}
            {multiplexer && (
              <p>
                Recorded I/O:{" "}
                {hasBooleanMultiplexerOutput(source.profile)
                  ? source.profile === booleanEnumSelectorMultiplexerProfile
                    ? "Boolean inputs and output; Enum selector."
                    : "Boolean inputs and output; Boolean selector."
                  : source.profile === enumMultiplexerProfile
                    ? "Enum inputs and output; Boolean selector."
                    : source.profile === enumEnumSelectorMultiplexerProfile
                      ? "Enum inputs and output; Enum selector."
                      : source.profile === enumSelectorMultiplexerProfile
                        ? "Float inputs and output; Enum selector."
                        : "Float inputs and output; Boolean selector."}
              </p>
            )}
            {primitive && (
              <details>
                <summary>
                  {timer ? (
                    "Recorded Timer ports"
                  ) : reliability ? (
                    "Recorded reliability ports"
                  ) : multiplexer ? (
                    "Recorded multiplexer ports"
                  ) : (
                    <>
                      Recorded{" "}
                      {comparison
                        ? "comparison"
                        : booleanLogic
                          ? "Boolean logic"
                          : "math"}{" "}
                      inputs
                    </>
                  )}
                </summary>
                {source.children
                  .filter(
                    (r: Data) =>
                      timer || reliability || multiplexer || r.port !== 85,
                  )
                  .map((r: Data) => (
                    <p key={r.ref}>
                      {timer || reliability || multiplexer
                        ? `${r.direction} port`
                        : "Port"}{" "}
                      {r.port}:{" "}
                      {r.recorded_default === null
                        ? "default omitted in source"
                        : `recorded default ${r.recorded_default}`}
                      ; {r.exposed ? "exposed" : "not exposed"} in source.
                      {(comparison || timer || reliability || multiplexer) &&
                        r.bacnet_type === 19 && (
                          <>
                            {" "}
                            Number Of States: {r.number_of_states}. States Text
                            code: {r.states_text_code ?? "omitted in source"}{" "}
                            (encoding set{" "}
                            {r.states_text_encoding_set ?? "omitted"}). Default
                            Value encoding set:{" "}
                            {r.default_encoding_set ?? "omitted with value"}.
                          </>
                        )}
                      {timer && r.units_code !== null && (
                        <>
                          {" "}
                          Recorded units code {r.units_code} (encoding set{" "}
                          {r.units_encoding_set}); Float metadata{" "}
                          {r.recorded_metadata_661}.
                        </>
                      )}
                      {(kind === "math" ||
                        booleanLogic ||
                        (multiplexer &&
                          (hasBooleanMultiplexerOutput(source.profile) ||
                            [
                              enumSelectorMultiplexerProfile,
                              enumMultiplexerProfile,
                              enumEnumSelectorMultiplexerProfile,
                            ].includes(source.profile)))) &&
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
              checkpointEpoch.current++;
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
        <CafCreationDraftRecovery
          archive={archive}
          context={{ kind, diagram_ref: diagram.ref, prototype_ref: chosen }}
          source={source}
          x={x}
          y={y}
          hasDraft={!!draft}
          disabled={disabled || busy}
          surfaceOpen={opened}
          retireKey={JSON.stringify([
            context,
            checkpointRetireKey,
            checkpointTicket,
            checkpointGeneration,
          ])}
          sourceCurrent={checkpointSourceCurrent}
          onRestore={(selection) => {
            if (
              !checkpointSourceCurrent() ||
              busy ||
              !source ||
              selection.kind !== kind ||
              selection.diagram_ref !== diagram.ref ||
              selection.prototype_ref !== chosen ||
              selection.selection_sha256 !== source.selection_sha256
            )
              return false;
            if (!remember({ x: selection.x, y: selection.y })) return false;
            epoch.current++;
            setReview(null);
            setSaved(null);
            setCreated(null);
            const restored = drafts.get(key);
            if (restored) drafts.set(key, { ...restored, saved: undefined });
            return true;
          }}
        />
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
              {timer ? "Primary output:" : "Required output:"}{" "}
              <code>{shown.data.creation.selection.new_output_ref}</code>
            </p>
            <p>
              One graph member and{" "}
              {primitive
                ? timer
                  ? "eight"
                  : reliability
                    ? "three"
                    : multiplexer &&
                        shown.data.creation.selection.object_count === 7
                      ? "seven"
                      : shown.data.creation.selection.object_count === 4
                        ? "four"
                        : "five"
                : "two"}{" "}
              objects added. Existing connections and continuation records stay
              unchanged.
            </p>
            <button
              className={openable ? "" : "primary"}
              disabled={disabled || busy}
              onClick={save}
            >
              Save {subject} CAF copy
            </button>
            {openable && (
              <button
                className="primary"
                disabled={disabled || busy}
                onClick={openCopy}
              >
                Open CAF copy
              </button>
            )}

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
