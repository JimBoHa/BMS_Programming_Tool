import { useContext, useEffect, useRef, useState } from "react";
import { apiBlobDocument, apiJsonDocument, saveBlob } from "./api";
import { NativeOrderTransfer } from "./NativeOrderTransfer";
import { NativeBooleanTransferContext } from "./NativeBooleanTransferContext";
import { controllerKey, type ControllerContext } from "./workflow";
import type { NativeArchiveSource } from "./NativeRecords";
import { rememberWireDraft, type WireCopyDrafts } from "./nativeWireDrafts";
import {
  nativeOrderAllowed,
  nativeOrderBase,
  nativeOrderDraft,
  nativeOrderDraftKey,
  nativeOrderExport,
  nativeOrderRequest,
  nativeOrderReview,
  nativeOrderSource,
  rememberNativeOrder,
} from "./nativeExecutionOrderContract";

type Data = Record<string, any>;
export function NativeExecutionOrder({
  source,
  record,
  controller,
  visible,
  drafts,
  operationGeneration,
  operationCurrent,
}: {
  source: NativeArchiveSource;
  record: Data;
  controller?: ControllerContext | null;
  visible: boolean;
  drafts: WireCopyDrafts;
  operationGeneration: number;
  operationCurrent: () => boolean;
}) {
  const field = useContext(NativeBooleanTransferContext),
    fieldNow = useRef(field);
  fieldNow.current = field;
  const [opened, setOpened] = useState(false),
    [life, setLife] = useState(0),
    [, setRefresh] = useState(0),
    [block, setBlock] = useState(0);
  const basis = JSON.stringify([source, record]),
    key = nativeOrderDraftKey(source, record);
  const [loaded, setLoaded] = useState<{ basis: string; data: Data } | null>(
      null,
    ),
    [error, setError] = useState<{ owner: string; text: string } | null>(null);
  const report = loaded?.basis === basis ? loaded.data : null;
  const [ownedFieldBusy, setOwnedFieldBusy] = useState(false);
  const [ownedMutationBusy, setOwnedMutationBusy] = useState(false);
  const otherFieldBusy = !!field?.fieldBusy && !ownedFieldBusy;
  const destinationKey = key + "/destination";
  const [destination, setDestination] = useState(
    drafts.get(destinationKey) === "controller" ? "controller" : "file",
  );
  const destinationNow = useRef(destination);

  let draft: Data | null = null,
    draftError = "";
  if (report)
    try {
      draft = nativeOrderDraft(drafts, key, report.selection);
    } catch (e) {
      draftError = (e as Error).message;
    }
  const proposed = draft?.proposed || report?.selection.original_order || [];
  const context = JSON.stringify([
    basis,
    visible,
    opened,
    life,
    controller
      ? [
          controllerKey(controller),
          controller.interfaceKey,
          controller.interfaceOpen,
        ]
      : null,
    field?.visible,
    field?.fieldBusy,
    field?.workspaceGeneration,
    proposed,
    draftError,
    operationGeneration,
  ]);
  const owner = useRef(context),
    epoch = useRef(0),
    alive = useRef(true),
    present = useRef(true),
    locked = useRef(false),
    visibleNow = useRef(visible);
  visibleNow.current = visible;
  if (owner.current !== context) {
    owner.current = context;
    epoch.current++;
  }
  const fieldOwner = JSON.stringify([
    basis,
    visible,
    opened,
    life,
    destination,
    proposed,
    draftError,
    operationGeneration,
    field?.workspaceGeneration,
    otherFieldBusy,
    controller && [
      controllerKey(controller),
      controller.interfaceKey,
      controller.interfaceOpen,
      controller.ownedCommands,
    ],
  ]);
  const fieldOwnerNow = useRef(fieldOwner),
    fieldEpoch = useRef(0);
  if (fieldOwnerNow.current !== fieldOwner) {
    fieldOwnerNow.current = fieldOwner;
    fieldEpoch.current++;
  }
  const fieldTicket = fieldEpoch.current;
  const renderEpoch = epoch.current;
  const operationNow = useRef(operationCurrent);
  operationNow.current = operationCurrent;
  const [pending, setPending] = useState<{
      owner: string;
      ticket: number;
    } | null>(null),
    [review, setReview] = useState<{
      owner: string;
      ticket: number;
      data: Data;
      blob: Blob;
    } | null>(null);
  const current = (o: string, t: number) =>
    alive.current &&
    operationNow.current() &&
    present.current &&
    document.visibilityState === "visible" &&
    visibleNow.current &&
    fieldNow.current?.fieldBusy !== true &&
    fieldNow.current?.visible !== false &&
    fieldNow.current?.workspaceCurrent?.() !== false &&
    owner.current === o &&
    epoch.current === t;
  const busy = !!pending && current(pending.owner, pending.ticket),
    shown = review && current(review.owner, review.ticket) ? review : null;
  const reviewNow = useRef(shown);
  reviewNow.current = shown;
  const usable = opened && visible && current(context, renderEpoch),
    usableNow = useRef(usable);
  usableNow.current = usable;
  function retire() {
    fieldEpoch.current++;
    epoch.current++;
    locked.current = false;
    reviewNow.current = null;
    setPending(null);
    setReview(null);
    setError(null);
  }
  useEffect(() => {
    locked.current = false;
    setPending(null);
    setReview(null);
    setError(null);
  }, [context]);
  useEffect(() => {
    alive.current = true;
    const change = (active: boolean) => {
      present.current = active;
      retire();
      setLife((v) => v + 1);
    };
    const hide = () => change(false),
      show = () => change(true),
      visibility = () => change(document.visibilityState === "visible");
    window.addEventListener("pagehide", hide);
    window.addEventListener("pageshow", show);
    document.addEventListener("visibilitychange", visibility);
    return () => {
      alive.current = false;
      epoch.current++;
      locked.current = false;
      window.removeEventListener("pagehide", hide);
      window.removeEventListener("pageshow", show);
      document.removeEventListener("visibilitychange", visibility);
    };
  }, []);
  function begin() {
    if (!usableNow.current || locked.current || !current(context, renderEpoch))
      return null;
    const ticket = ++epoch.current;
    locked.current = true;
    reviewNow.current = null;
    setReview(null);
    setError(null);
    setPending({ owner: context, ticket });
    return { owner: context, ticket };
  }
  async function prepare(withReview: boolean) {
    const run = begin();
    if (!run) return;
    try {
      const response = await apiJsonDocument(nativeOrderBase + "/source", {
        capture_id: source.capture_id,
        snapshot_sha256: source.snapshot_sha256,
        source_sha256: source.sha256,
        diagram_ref: record.ref,
        record_sha256: record.record_sha256,
      });
      if (!current(run.owner, run.ticket)) return;
      if (!(await nativeOrderSource(response.data, source, record)))
        throw Error(
          "The native order source proof does not match this retained diagram.",
        );
      if (!current(run.owner, run.ticket)) return;
      setLoaded({ basis, data: response.data });
      const retained = nativeOrderDraft(drafts, key, response.data.selection);
      if (!withReview) return;
      const request = nativeOrderRequest(
        source,
        record,
        response.data,
        retained?.proposed || response.data.selection.original_order,
      );
      const result = await apiJsonDocument(
        nativeOrderBase + "/preview",
        request,
      );
      if (!current(run.owner, run.ticket)) return;
      if (
        !(await nativeOrderReview(
          result.data,
          source,
          record,
          response.data,
          request,
        ))
      )
        throw Error(
          "The native order compilation proof does not match the selected proposal.",
        );
      if (current(run.owner, run.ticket))
        setReview({ ...run, data: result.data, blob: result.blob });
    } catch (e) {
      if (current(run.owner, run.ticket))
        setError({ owner: run.owner, text: (e as Error).message });
    } finally {
      if (current(run.owner, run.ticket)) {
        locked.current = false;
        setPending(null);
      }
    }
  }
  async function save() {
    const held = shown;
    if (
      !held ||
      reviewNow.current !== held ||
      !current(held.owner, held.ticket)
    )
      return;
    const run = begin();
    if (!run) return;
    try {
      const response = await apiBlobDocument(nativeOrderBase + "/export", {
        ...held.data.request,
        review_sha256: held.data.review_sha256,
      });
      if (!current(run.owner, run.ticket)) return;
      if (!(await nativeOrderExport(response, held.data)))
        throw Error(
          "The native order file bytes or proof headers do not match the review.",
        );
      if (!current(run.owner, run.ticket)) return;
      saveBlob(response.blob, "native-effective-execution-order.moi");
      const d = nativeOrderDraft(drafts, key, held.data.source.selection);
      if (d) {
        d.saved = JSON.stringify(d.proposed);
        rememberWireDraft(drafts, key, JSON.stringify(d));
        setRefresh((v) => v + 1);
      }
      setReview({ ...run, data: held.data, blob: held.blob });
    } catch (e) {
      if (current(run.owner, run.ticket))
        setError({ owner: run.owner, text: (e as Error).message });
    } finally {
      if (current(run.owner, run.ticket)) {
        locked.current = false;
        setPending(null);
      }
    }
  }
  function moved(delta: number) {
    const order = [...proposed],
      position = order.indexOf(block),
      to = position + delta;
    if (position < 0 || to < 0 || to >= order.length) return null;
    [order[position], order[to]] = [order[to], order[position]];
    return order;
  }
  function move(delta: number) {
    if (
      !usableNow.current ||
      locked.current ||
      !current(context, renderEpoch) ||
      !report
    )
      return;
    const next = moved(delta);
    if (!next) return;
    retire();
    try {
      rememberNativeOrder(drafts, key, report.selection, next);
      setRefresh((v) => v + 1);
    } catch (e) {
      setError({ owner: context, text: (e as Error).message });
    }
  }
  const eligible = (delta: number) => {
    const next = moved(delta);
    return !!next && !!report && nativeOrderAllowed(report.selection, next);
  };
  return (
    <details
      className="native-wire-copy"
      aria-label="Native execution-order compilation"
      open={opened}
      onToggle={(e) => {
        if (e.currentTarget.open !== opened) {
          retire();
          setOpened(e.currentTarget.open);
        }
      }}
    >
      <summary
        aria-disabled={ownedMutationBusy || otherFieldBusy || !visible}
        onClick={(event) => {
          if (ownedMutationBusy || otherFieldBusy || !visible) {
            event.preventDefault();
            return;
          }
          retire();
          setLife((value) => value + 1);
        }}
      >
        Compile native execution order
      </summary>
      <p>
        Reorder existing blocks after merging this retained backup's saved
        settings. Existing wire timing relationships and original index widths
        stay unchanged. This saves a local native copy; controller transfer is
        separate.
      </p>
      <label>
        Native execution-order destination
        <select
          aria-label="Native execution-order destination"
          value={destination}
          disabled={!usable || busy || !!field?.fieldBusy}
          onChange={(event) => {
            const value = event.target.value;
            if (value === destinationNow.current) return;
            if (value === "file") drafts.delete(destinationKey);
            else if (!rememberWireDraft(drafts, destinationKey, value)) {
              setError({
                owner: context,
                text: "The 256 retained draft slots are full. Discard an older draft first; no work was removed.",
              });
              return;
            }
            destinationNow.current = value;
            retire();
            setDestination(value);
          }}
        >
          <option value="file">Local native copy</option>
          <option value="controller">Selected controller</option>
        </select>
      </label>
      <div className="button-row">
        <button
          className={!report && !shown ? "primary" : ""}
          disabled={!usable || busy}
          onClick={() => void prepare(false)}
        >
          Inspect effective execution order
        </button>
      </div>
      {report && (
        <>
          <label>
            Native execution-order block
            <select
              disabled={!usable || busy || !!draftError}
              value={block}
              onChange={(e) => setBlock(Number(e.target.value))}
            >
              {report.selection.members.map((b: Data) => (
                <option key={b.index} value={b.index}>
                  {b.name || b.ref}
                </option>
              ))}
            </select>
          </label>
          <div className="button-row">
            <button
              disabled={!usable || busy || !!draftError || !eligible(-1)}
              onClick={() => move(-1)}
            >
              Move native block earlier
            </button>
            <button
              disabled={!usable || busy || !!draftError || !eligible(1)}
              onClick={() => move(1)}
            >
              Move native block later
            </button>
            {drafts.has(key) && (
              <button
                disabled={!usable || busy}
                onClick={() => {
                  if (!current(context, renderEpoch)) return;
                  retire();
                  drafts.delete(key);
                  setRefresh((v) => v + 1);
                }}
              >
                Discard native order proposal
              </button>
            )}
          </div>
          <div
            className="native-record-table"
            tabIndex={0}
            aria-label="Native execution-order table"
          >
            <table aria-label="Proposed native execution order">
              <thead>
                <tr>
                  <th>Proposed order</th>
                  <th>Original effective order</th>
                  <th>Block</th>
                </tr>
              </thead>
              <tbody>
                {proposed.map((index: number, rank: number) => {
                  const b = report.selection.members[index];
                  return (
                    <tr key={index}>
                      <td>{rank + 1}</td>
                      <td>
                        {report.selection.original_order.indexOf(index) + 1}
                      </td>
                      <td>{b.name || b.ref}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {draft && (
            <p role="status">
              {draft.saved === JSON.stringify(draft.proposed)
                ? "A native order copy was exported; the retained originals are unchanged."
                : "Native order proposal has not been exported."}
            </p>
          )}
          <p>
            Moves that reverse a recorded wire relationship or exceed an
            existing index width are unavailable. Saved values are historical.
            Native execution and CCT/physical acceptance remain unverified.
          </p>
          <button
            className={destination === "file" && !shown ? "primary" : ""}
            disabled={!usable || busy || !!draftError}
            onClick={() => void prepare(true)}
          >
            Review native execution-order compilation
          </button>
        </>
      )}
      {busy && <p role="status">Checking retained files and native order…</p>}
      {(draftError || error?.owner === context) && (
        <p role="alert">{draftError || error?.text}</p>
      )}
      {shown && (
        <section aria-label="Reviewed native execution-order compilation">
          <p>
            {shown.data.compilation.order_edit.patches.length} order positions
            change. Saved settings merged; other expanded bytes preserved.
          </p>
          <div className="button-row">
            <button
              className="primary"
              disabled={!usable || busy}
              onClick={() => void save()}
            >
              Save native execution-order copy
            </button>
            <button
              disabled={!usable || busy}
              onClick={() => {
                if (
                  reviewNow.current === shown &&
                  current(shown.owner, shown.ticket)
                )
                  saveBlob(shown.blob, "native-execution-order-review.json");
              }}
            >
              Save exact native order review
            </button>
          </div>
          <details>
            <summary>Native order compilation details</summary>
            <code style={{ overflowWrap: "anywhere" }}>
              {shown.data.compilation.compilation_sha256}
            </code>
          </details>
        </section>
      )}
      <div hidden={destination !== "controller"}>
        <NativeOrderTransfer
          source={source}
          proposal={
            report &&
            !draftError &&
            !proposed.every(
              (v: number, i: number) =>
                v === report.selection.original_order[i],
            )
              ? nativeOrderRequest(source, record, report, proposed)
              : null
          }
          opened={report}
          controller={controller}
          visible={visible && opened && destination === "controller"}
          otherBusy={otherFieldBusy || !!pending}
          onOwnedBusy={(value, kind) => {
            setOwnedFieldBusy(value);
            setOwnedMutationBusy(
              value && ["capture", "apply", "readback"].includes(kind),
            );
          }}
          parentGeneration={JSON.stringify([fieldTicket])}
          parentCurrent={() =>
            alive.current &&
            present.current &&
            visibleNow.current &&
            opened &&
            fieldOwnerNow.current === fieldOwner &&
            fieldEpoch.current === fieldTicket &&
            destinationNow.current === "controller" &&
            operationNow.current() &&
            fieldNow.current?.visible !== false &&
            fieldNow.current?.workspaceCurrent?.() !== false &&
            document.visibilityState === "visible"
          }
        />
      </div>
    </details>
  );
}
