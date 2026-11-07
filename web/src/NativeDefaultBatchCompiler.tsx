import { useEffect, useRef, useState } from "react";
import { apiJsonDocument, apiBlobDocument, saveBlob } from "./api";
import { sha256Blob } from "./activityContracts";
import type { ControllerContext } from "./workflow";
import { NativeDefaultBatchTransfer } from "./NativeDefaultBatchTransfer";
import { NativeBatchDraftFiles } from "./NativeBatchDraftFiles";
import {
  defaultBatchBase as base,
  defaultBatchSource,
  defaultBatchRequest,
  defaultBatchReview,
} from "./nativeDefaultBatchContract";

type Data = Record<string, any>;
export type DefaultBatchDrafts = Map<string, Record<string, string>>;
type Owned = { owner: string; ticket: number };
const display = (v: number | boolean) => (Object.is(v, -0) ? "-0" : String(v));
export function NativeDefaultBatchCompiler({
  source,
  context,
  generation,
  visible,
  blocked,
  expanded,
  onExpandedChange,
  parentCurrent,
  drafts,
  controller,
  fieldBlocked = true,
  fieldParentCurrent = () => false,
  onFieldBusy = () => {},
  onCaptured = () => {},
}: {
  source: Data;
  context: string;
  generation: number;
  visible: boolean;
  blocked: boolean;
  expanded: boolean;
  onExpandedChange: (value: boolean) => boolean;
  parentCurrent: () => boolean;
  drafts: DefaultBatchDrafts;
  controller?: ControllerContext | null;
  fieldBlocked?: boolean;
  fieldParentCurrent?: () => boolean;
  onFieldBusy?: (value: boolean) => void;
  onCaptured?: (id: string) => void;
}) {
  const sourceKey = JSON.stringify([source.capture_id, source.snapshot_sha256]);
  const entries = drafts.get(sourceKey) ?? {};
  const owner = JSON.stringify([
    context,
    generation,
    visible,
    blocked,
    expanded,
    sourceKey,
    entries,
  ]);
  const ownerNow = useRef(owner),
    epoch = useRef(0),
    alive = useRef(true),
    expandedNow = useRef(expanded);
  expandedNow.current = expanded;
  if (ownerNow.current !== owner) {
    ownerNow.current = owner;
    epoch.current++;
  }
  const fieldEpoch = useRef(0);
  const fieldOwner = JSON.stringify([
    context,
    generation,
    visible,
    expanded,
    sourceKey,
    entries,
  ]);
  const fieldOwnerNow = useRef(fieldOwner);
  if (fieldOwnerNow.current !== fieldOwner) {
    fieldOwnerNow.current = fieldOwner;
    fieldEpoch.current++;
  }
  const fieldTicket = fieldEpoch.current;
  const renderedEpoch = epoch.current;
  const [, redraw] = useState(0);
  const [loaded, setLoaded] = useState<{ key: string; data: Data } | null>(
    null,
  );
  const [review, setReview] = useState<
    (Owned & { data: Data; blob: Blob; request: Data }) | null
  >(null);
  const [failure, setFailure] = useState<(Owned & { text: string }) | null>(
    null,
  );
  const [pending, setPending] = useState<Owned | null>(null);
  const [saved, setSaved] = useState<Owned | null>(null);
  const [fieldOpen, setFieldOpen] = useState(false);
  const [search, setSearch] = useState(""),
    [page, setPage] = useState(0),
    [selectedOnly, setSelectedOnly] = useState(false);
  const opened = loaded?.key === sourceKey ? loaded.data : null;
  const current = (ticket: number, key = owner) =>
    alive.current &&
    visible &&
    !blocked &&
    expandedNow.current &&
    ownerNow.current === key &&
    epoch.current === ticket &&
    parentCurrent() &&
    document.visibilityState !== "hidden";
  const owns = (v: Owned | null) => !!v && current(v.ticket, v.owner);
  const shown = owns(review) ? review : null,
    busy = owns(pending);
  function retire() {
    epoch.current++;
    fieldEpoch.current++;
    setReview(null);
    setPending(null);
    setFailure(null);
    setSaved(null);
  }
  useEffect(() => {
    alive.current = true;
    const hide = () => {
      if (document.visibilityState === "hidden") retire();
    };
    document.addEventListener("visibilitychange", hide);
    window.addEventListener("pagehide", retire);
    return () => {
      alive.current = false;
      epoch.current++;
      document.removeEventListener("visibilitychange", hide);
      window.removeEventListener("pagehide", retire);
    };
  }, []);
  useEffect(() => {
    if (expanded && visible && !blocked && !opened) void load();
  }, [sourceKey, expanded, visible, blocked]);
  async function load() {
    if (!current(renderedEpoch)) return;
    const ticket = ++epoch.current,
      key = owner;
    if (!current(ticket, key)) return;
    setPending({ owner: key, ticket });
    setFailure(null);
    setReview(null);
    try {
      const document = await apiJsonDocument(base + "/source", {
        capture_id: source.capture_id,
        snapshot_sha256: source.snapshot_sha256,
      });
      if (!defaultBatchSource(document.data, source))
        throw new Error(
          "Batch source does not match the opened native capture, route or saved merge.",
        );
      if (current(ticket, key)) {
        setLoaded({ key: sourceKey, data: document.data });
        setPage(0);
      }
    } catch (error) {
      if (current(ticket, key))
        setFailure({ owner: key, ticket, text: String(error) });
    } finally {
      if (current(ticket, key)) setPending(null);
    }
  }
  function change(ref: string, value: string | null) {
    if (!current(epoch.current)) return;
    const next: Record<string, string> = Object.assign(
      Object.create(null),
      drafts.get(sourceKey) ?? {},
    );
    if (value === null) delete next[ref];
    else next[ref] = value;
    if (Object.keys(next).length > 16) {
      setFailure({
        owner,
        ticket: epoch.current,
        text: "Select at most 16 defaults; existing batch text was kept.",
      });
      return;
    }
    if (
      Object.keys(next).length &&
      !drafts.has(sourceKey) &&
      drafts.size >= 32
    ) {
      setFailure({
        owner,
        ticket: epoch.current,
        text: "32 batch source drafts are retained. Discard an older batch draft before starting another; existing work was kept.",
      });
      return;
    }
    retire();
    if (Object.keys(next).length) drafts.set(sourceKey, next);
    else drafts.delete(sourceKey);
    redraw((v) => v + 1);
  }
  function installDraft(
    values: Record<string, string>,
    ticket: number,
    key: string,
  ) {
    if (!opened || !current(ticket, key)) return false;
    const refs = Object.keys(values);
    if (
      Object.keys(drafts.get(sourceKey) ?? {}).length ||
      !refs.length ||
      refs.length > 16 ||
      refs.some(
        (ref) => !opened.fields.some((row: Data) => row.field.ref === ref),
      ) ||
      (!drafts.has(sourceKey) && drafts.size >= 32)
    )
      return false;
    const next = Object.assign(Object.create(null), values);
    retire();
    drafts.set(sourceKey, next);
    redraw((v) => v + 1);
    return true;
  }
  async function preview() {
    if (!opened || !current(renderedEpoch)) return;
    let request: Data;
    try {
      request = defaultBatchRequest(source, opened, entries);
    } catch (error) {
      setFailure({ owner, ticket: epoch.current, text: String(error) });
      return;
    }
    const ticket = ++epoch.current,
      key = owner;
    setReview(null);
    setSaved(null);
    setFailure(null);
    setPending({ owner: key, ticket });
    try {
      const document = await apiJsonDocument(base + "/preview", request);
      if (!defaultBatchReview(document.data, opened, request))
        throw new Error(
          "Batch review differs from the selected typed edits, source or composition proof.",
        );
      if (current(ticket, key))
        setReview({
          owner: key,
          ticket,
          data: document.data,
          blob: document.blob,
          request,
        });
    } catch (error) {
      if (current(ticket, key))
        setFailure({ owner: key, ticket, text: String(error) });
    } finally {
      if (current(ticket, key)) setPending(null);
    }
  }
  async function save() {
    if (!shown || !opened || !current(shown.ticket, shown.owner)) return;
    const ticket = shown.ticket,
      key = shown.owner;
    setPending({ owner: key, ticket });
    setFailure(null);
    try {
      const result = await apiBlobDocument(base + "/export", {
        ...shown.request,
        review_sha256: shown.data.review_sha256,
      });
      if (
        result.headers.get("X-Studio-Snapshot-Sha256") !==
          source.snapshot_sha256 ||
        result.headers.get("X-Studio-Review-Sha256") !==
          shown.data.review_sha256 ||
        result.headers.get("X-Studio-Artifact-Sha256") !==
          shown.data.output_sha256 ||
        (await sha256Blob(result.blob)) !== shown.data.output_sha256
      )
        throw new Error(
          "Batch copy bytes do not match the reviewed snapshot and digest.",
        );
      if (current(ticket, key)) {
        saveBlob(result.blob, "native-default-batch.moi");
        setSaved({ owner: key, ticket });
      }
    } catch (error) {
      if (current(ticket, key))
        setFailure({ owner: key, ticket, text: String(error) });
    } finally {
      if (current(ticket, key)) setPending(null);
    }
  }
  let fieldProposal: Data | null = null;
  try {
    if (opened) fieldProposal = defaultBatchRequest(source, opened, entries);
  } catch {
    /* Keep unfinished local text. */
  }
  const filtered = (opened?.fields ?? []).filter(
    (row: Data) =>
      (!selectedOnly || Object.hasOwn(entries, row.field.ref)) &&
      [row.name, row.field.ref, row.kind, String(row.field.class_id)].some(
        (v) => v.toLowerCase().includes(search.toLowerCase()),
      ),
  );
  const offset =
    Math.min(page, Math.max(0, Math.ceil(filtered.length / 50) - 1)) * 50;
  return (
    <details aria-label="Native typed default batch" open={expanded}>
      <summary
        aria-disabled={blocked}
        onClick={(event) => {
          event.preventDefault();
          const next = !expandedNow.current;
          if (onExpandedChange(next)) {
            expandedNow.current = next;
            retire();
          }
        }}
      >
        Compile several native defaults together
      </summary>
      <p>
        <strong>{source.identity["object-name"]}</strong> · {source.device} at{" "}
        {source.target.address}
        {source.target.router
          ? ` via ${source.target.router} / DNET ${source.target.dnet}`
          : ""}{" "}
        · captured {source.captured_at}.
      </p>
      <p>
        This local task combines up to 16 existing Real, Boolean or Enum
        defaults after one retained saved-setting merge. Local review and saving
        create no controller transfer. A separate controller review is required
        to Apply. Enum meanings, native execution and physical acceptance remain
        unverified.
      </p>
      {busy && <p role="status">Preparing local batch evidence…</p>}
      {owns(failure) && <p role="alert">{failure!.text}</p>}
      {owns(saved) && (
        <p role="status">Saved the reviewed local native copy.</p>
      )}
      {!opened && (
        <button
          type="button"
          disabled={blocked || busy || !expanded}
          onClick={() => void load()}
        >
          Inspect typed defaults
        </button>
      )}
      {opened && (
        <>
          <div className="native-compiler-fields">
            <label>
              Find a batch default
              <input
                aria-label="Find a batch default"
                value={search}
                onChange={(event) => {
                  setSearch(event.target.value);
                  setPage(0);
                }}
              />
            </label>
            <label className="native-transfer-check">
              <input
                type="checkbox"
                checked={selectedOnly}
                onChange={(event) => {
                  setSelectedOnly(event.target.checked);
                  setPage(0);
                }}
              />
              Show selected batch defaults only
            </label>
          </div>
          <p>
            {Object.keys(entries).length} of 16 defaults selected ·{" "}
            {opened.fields.length} actual typed fields. Drafts stay with this
            original capture; no current controller value is inferred.
          </p>
          <NativeBatchDraftFiles
            source={source}
            opened={opened}
            entries={entries}
            hasDraft={Object.keys(entries).length > 0}
            blocked={blocked || busy || !visible || !expanded}
            parentOwner={owner}
            parentEpoch={renderedEpoch}
            parentCurrent={(ticket, key) => current(ticket, key)}
            install={installDraft}
          />
          <div
            className="application-operation-table"
            role="region"
            aria-label="Native batch defaults table viewport"
            tabIndex={0}
            onKeyDown={(event) => {
              if (
                event.target !== event.currentTarget ||
                event.altKey ||
                event.ctrlKey ||
                event.metaKey ||
                event.shiftKey ||
                !["ArrowLeft", "ArrowRight"].includes(event.key)
              )
                return;
              event.preventDefault();
              event.currentTarget.scrollBy({
                left: event.key === "ArrowRight" ? 80 : -80,
              });
            }}
          >
            <table aria-label="Native batch default fields">
              <thead>
                <tr>
                  <th>Include</th>
                  <th>Recorded field</th>
                  <th>Type</th>
                  <th>Archive</th>
                  <th>Saved effective</th>
                  <th>Proposed default</th>
                </tr>
              </thead>
              <tbody>
                {filtered.slice(offset, offset + 50).map((row: Data) => {
                  const f = row.field,
                    selected = Object.hasOwn(entries, f.ref);
                  return (
                    <tr key={f.ref}>
                      <td>
                        <label className="native-transfer-check">
                          <input
                            type="checkbox"
                            aria-label={`Include ${f.ref} in batch`}
                            checked={selected}
                            disabled={
                              blocked ||
                              (!selected && Object.keys(entries).length >= 16)
                            }
                            onChange={(event) =>
                              change(
                                f.ref,
                                event.target.checked
                                  ? display(f.effective_value)
                                  : null,
                              )
                            }
                          />
                        </label>
                      </td>
                      <th scope="row">
                        {row.name}
                        <br />
                        <code>{f.ref}</code>
                      </th>
                      <td>
                        {row.kind} · class {f.class_id}
                      </td>
                      <td>{display(f.archive_value)}</td>
                      <td>{display(f.effective_value)}</td>
                      <td>
                        {selected &&
                          (row.kind === "boolean" ? (
                            <label className="native-transfer-check">
                              <input
                                type="checkbox"
                                aria-label={`Proposed Boolean for ${f.ref}`}
                                checked={entries[f.ref] === "true"}
                                disabled={blocked}
                                onChange={(event) =>
                                  change(f.ref, String(event.target.checked))
                                }
                              />
                              {entries[f.ref]}
                            </label>
                          ) : (
                            <input
                              aria-label={`Proposed ${row.kind} value for ${f.ref}`}
                              value={entries[f.ref]}
                              maxLength={128}
                              disabled={blocked}
                              onChange={(event) =>
                                change(f.ref, event.target.value)
                              }
                            />
                          ))}
                        {row.kind === "enum" && (
                          <small>
                            Numeric codes 0–{f.maximum_code}; meanings
                            unverified.
                          </small>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="button-row">
            <button
              type="button"
              disabled={offset === 0}
              onClick={() => setPage(Math.max(0, page - 1))}
            >
              Previous batch fields
            </button>
            <span>
              {filtered.length ? offset + 1 : 0}–
              {Math.min(offset + 50, filtered.length)} of {filtered.length}
            </span>
            <button
              type="button"
              disabled={offset + 50 >= filtered.length}
              onClick={() => setPage(page + 1)}
            >
              Next batch fields
            </button>
          </div>
          {!opened.fields.length && (
            <p>
              No supported typed defaults were recorded in this saved source.
            </p>
          )}
          <div className="button-row">
            <button
              type="button"
              className={fieldOpen ? undefined : "primary"}
              disabled={blocked || busy || !Object.keys(entries).length}
              onClick={() => void preview()}
            >
              Review local default batch
            </button>
            <button
              type="button"
              disabled={blocked || !Object.keys(entries).length}
              onClick={() => {
                if (!current(epoch.current)) return;
                retire();
                drafts.delete(sourceKey);
                redraw((v) => v + 1);
              }}
            >
              Discard this batch draft
            </button>
          </div>
        </>
      )}
      <details open={fieldOpen} aria-label="Default batch field workflow">
        <summary
          onClick={(event) => {
            event.preventDefault();
            if (blocked || busy) return;
            retire();
            setFieldOpen((value) => !value);
          }}
        >
          Transfer default batch to controller
        </summary>
        <NativeDefaultBatchTransfer
          source={source}
          opened={opened}
          proposal={fieldProposal}
          controller={controller}
          visible={visible && expanded && fieldOpen}
          otherBusy={fieldBlocked || !!busy}
          revision={fieldTicket}
          onOwnedBusy={onFieldBusy}
          onCaptured={onCaptured}
          parentCurrent={() =>
            alive.current &&
            expandedNow.current &&
            fieldEpoch.current === fieldTicket &&
            fieldParentCurrent()
          }
        />
      </details>
      {shown && (
        <section
          className="native-compiler-source"
          aria-label="Reviewed native default batch"
        >
          <h3>Reviewed local default batch</h3>
          <p>
            {shown.data.compilation.changed_count} of
            {shown.data.compilation.edit_count} selected defaults change. Both
            edit orders reproduce the same native bytes. Other merged
            application bytes, graph and identity are preserved.
          </p>
          <div className="button-row">
            <button
              type="button"
              disabled={blocked || busy}
              onClick={() => void save()}
            >
              Save compiled default batch
            </button>
            <button
              type="button"
              onClick={() => {
                if (current(shown.ticket, shown.owner))
                  saveBlob(shown.blob, "native-default-batch-review.json");
              }}
            >
              Export exact batch review
            </button>
          </div>
          <details>
            <summary>Typed edits, preservation and source hashes</summary>
            <pre>{JSON.stringify(shown.data, null, 2)}</pre>
          </details>
        </section>
      )}
    </details>
  );
}
