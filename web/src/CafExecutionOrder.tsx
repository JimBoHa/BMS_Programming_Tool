import { useEffect, useRef, useState } from "react";
import { apiJsonDocument, apiBlobDocument, saveBlob } from "./api";
import { connectionSame } from "./nativeConnectionContract";
import {
  orderAllowed,
  orderDirty,
  orderExport,
  orderKey,
  orderRequest,
  orderReview,
  orderSource,
  rememberOrder,
  type OrderDiagram,
  type OrderDrafts,
} from "./cafExecutionOrderContract";

type Data = Record<string, any>;
export function CafExecutionOrder({
  archive,
  filename,
  diagram,
  objectCount,
  sourceCurrent,
  disabled,
  surfaceOpen,
  retireKey,
  reviewContext,
  conflict,
  drafts,
  onDraftChange,
  onOpenChange,
}: {
  archive: string;
  filename: string;
  diagram: OrderDiagram;
  objectCount: number;
  sourceCurrent: () => boolean;
  disabled: boolean;
  surfaceOpen: boolean;
  retireKey: string;
  reviewContext: string;
  conflict: boolean;
  drafts: OrderDrafts;
  onDraftChange: () => void;
  onOpenChange: (open: boolean) => void;
}) {
  const [opened, setOpened] = useState(false),
    [life, setLife] = useState(0),
    [block, setBlock] = useState(0);
  const key = orderKey(archive, diagram.ref),
    draft = drafts.get(key),
    proposed = draft?.proposed || diagram.execution_order;
  const basis = JSON.stringify([archive, diagram, retireKey, reviewContext]);
  const context = JSON.stringify([
    basis,
    disabled,
    surfaceOpen,
    opened,
    conflict,
    life,
    proposed,
  ]);
  const owner = useRef(context),
    epoch = useRef(0),
    alive = useRef(true),
    locked = useRef(false),
    lifetime = useRef(true);
  const sourceNow = useRef(sourceCurrent);
  sourceNow.current = sourceCurrent;
  if (owner.current !== context) {
    owner.current = context;
    epoch.current++;
  }
  const renderEpoch = epoch.current;
  const [pending, setPending] = useState<{
    owner: string;
    ticket: number;
  } | null>(null);
  const [source, setSource] = useState<{ basis: string; data: Data } | null>(
    null,
  );
  const [review, setReview] = useState<{
    owner: string;
    ticket: number;
    data: Data;
    blob: Blob;
  } | null>(null);
  const [error, setError] = useState<{ owner: string; text: string } | null>(
    null,
  );
  const current = (o: string, t: number) =>
    alive.current &&
    lifetime.current &&
    document.visibilityState === "visible" &&
    sourceNow.current() &&
    owner.current === o &&
    epoch.current === t;
  const busy = !!pending && current(pending.owner, pending.ticket);
  const shown = review && current(review.owner, review.ticket) ? review : null;
  const selected = source?.basis === basis ? source.data : null;
  const usable =
    opened &&
    surfaceOpen &&
    !disabled &&
    !conflict &&
    lifetime.current &&
    document.visibilityState === "visible" &&
    sourceCurrent() &&
    diagram.observed_version &&
    diagram.blocks.length >= 2 &&
    diagram.blocks.length <= 512 &&
    diagram.connections.length <= 6000;
  const usableNow = useRef(usable);
  usableNow.current = usable;
  const reviewNow = useRef(shown);
  reviewNow.current = shown;
  function retire() {
    epoch.current++;
    locked.current = false;
    reviewNow.current = null;
    setReview(null);
    setPending(null);
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
    const hide = () => {
      lifetime.current = false;
      retire();
      setLife((x) => x + 1);
    };
    const show = () => {
      lifetime.current = true;
      retire();
      setLife((x) => x + 1);
    };
    const visibility = () => {
      if (document.visibilityState !== "visible") hide();
      else show();
    };
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
  useEffect(() => () => onOpenChange(false), [onOpenChange]);
  function begin() {
    if (!usableNow.current || locked.current || !current(context, renderEpoch))
      return null;
    const o = context;
    if (owner.current !== o) return null;
    const ticket = ++epoch.current;
    locked.current = true;
    reviewNow.current = null;
    setReview(null);
    setError(null);
    setPending({ owner: o, ticket });
    return { o, ticket };
  }
  async function prepare() {
    const run = begin();
    if (!run) return;
    try {
      const sourceResponse = await apiJsonDocument(
        `/caf/${archive}/execution-order/source`,
        { source_sha256: archive, diagram_ref: diagram.ref },
      );
      if (!current(run.o, run.ticket)) return;
      if (!(await orderSource(sourceResponse.data, archive, diagram)))
        throw Error(
          "The execution-order source proof does not match this CAF diagram.",
        );
      if (!current(run.o, run.ticket)) return;
      setSource({ basis, data: sourceResponse.data });
      const request = orderRequest(sourceResponse.data, proposed);
      if (connectionSame(proposed, diagram.execution_order)) return;
      const response = await apiJsonDocument(
        `/caf/${archive}/execution-order/preview`,
        request,
      );
      if (!current(run.o, run.ticket)) return;
      if (
        !(await orderReview(
          response.data,
          sourceResponse.data,
          request,
          objectCount,
          diagram,
        ))
      )
        throw Error("The execution-order review does not match this proposal.");
      if (current(run.o, run.ticket))
        setReview({
          owner: run.o,
          ticket: run.ticket,
          data: response.data,
          blob: response.blob,
        });
    } catch (e) {
      if (current(run.o, run.ticket))
        setError({ owner: run.o, text: (e as Error).message });
    } finally {
      if (current(run.o, run.ticket)) {
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
      const response = await apiBlobDocument(
        `/caf/${archive}/execution-order/export`,
        { ...held.data.request, review_sha256: held.data.review_sha256 },
      );
      if (!current(run.o, run.ticket)) return;
      if (!(await orderExport(response, held.data)))
        throw Error(
          "The CAF copy bytes or proof headers do not match the execution-order review.",
        );
      if (!current(run.o, run.ticket)) return;
      const active = drafts.get(key);
      if (
        !active ||
        !connectionSame(active.proposed, held.data.request.proposed_order)
      )
        return;
      saveBlob(
        response.blob,
        `${filename.replace(/\.caf$/i, "")}-execution-order.caf`,
      );
      active.saved = JSON.stringify(active.proposed);
      onDraftChange();
      setReview({ ...held, owner: run.o, ticket: run.ticket });
    } catch (e) {
      if (current(run.o, run.ticket))
        setError({ owner: run.o, text: (e as Error).message });
    } finally {
      if (current(run.o, run.ticket)) {
        locked.current = false;
        setPending(null);
      }
    }
  }
  function moved(delta: number) {
    const next = [...proposed],
      position = next.indexOf(block),
      to = position + delta;
    if (position < 0 || to < 0 || to >= next.length) return null;
    [next[position], next[to]] = [next[to], next[position]];
    return next;
  }
  function move(delta: number) {
    if (!usableNow.current || locked.current || !current(context, renderEpoch))
      return;
    const next = moved(delta);
    if (!next) return;
    retire();
    try {
      rememberOrder(drafts, archive, diagram, next);
      onDraftChange();
    } catch (e) {
      setError({ owner: context, text: (e as Error).message });
    }
  }
  const eligible = (delta: number) => {
    const next = moved(delta);
    return !!next && orderAllowed(diagram, next);
  };
  return (
    <details
      className="caf-connection-create"
      open={opened}
      onToggle={(e) => {
        if (e.currentTarget.open !== opened) {
          retire();
          setOpened(e.currentTarget.open);
          onOpenChange(e.currentTarget.open);
        }
      }}
    >
      <summary>Change block execution order</summary>
      <section aria-label="CAF execution order">
        <p>
          Reorder existing blocks in a separate CAF copy. Each recorded
          connection keeps its current forward, backward or self execution
          relationship. Other pending edits are separate exports.
        </p>
        {(!diagram.observed_version ||
          diagram.blocks.length > 512 ||
          diagram.connections.length > 6000) && (
          <p role="note">
            This copy profile requires diagram version 1.0, 1–512 blocks and at
            most 6,000 connections.
          </p>
        )}
        {conflict && (
          <p role="note">
            Export and open, or discard, the other retained proposal before
            reviewing execution order. No proposals were combined.
          </p>
        )}
        <label>
          Execution-order block
          <select
            value={block}
            disabled={!usable || busy}
            onChange={(e) => setBlock(Number(e.target.value))}
          >
            {diagram.blocks.map((b) => (
              <option key={b.index} value={b.index}>
                {b.name || b.ref} · {b.class_name}
              </option>
            ))}
          </select>
        </label>
        <div className="button-row">
          <button
            disabled={!usable || busy || !eligible(-1)}
            onClick={() => move(-1)}
          >
            Move block earlier
          </button>
          <button
            disabled={!usable || busy || !eligible(1)}
            onClick={() => move(1)}
          >
            Move block later
          </button>
          {draft && (
            <button
              disabled={disabled || busy || !sourceCurrent()}
              onClick={() => {
                if (!current(context, renderEpoch)) return;
                retire();
                drafts.delete(key);
                onDraftChange();
              }}
            >
              Discard execution-order proposal
            </button>
          )}
        </div>
        <p>
          Moves that reverse an existing wire's execution relationship are
          unavailable. These checks preserve recorded structure; CCT/PCT
          acceptance, native behavior and controller transfer remain unverified.
        </p>
        <div className="caf-graph-table">
          <div className="table-scroll">
            <table aria-label="CAF proposed execution order">
              <thead>
                <tr>
                  <th>Proposed order</th>
                  <th>Original order</th>
                  <th>Block</th>
                </tr>
              </thead>
              <tbody>
                {proposed.map((index, rank) => {
                  const b = diagram.blocks.find((x) => x.index === index);
                  return (
                    <tr key={index}>
                      <td>{rank + 1}</td>
                      <td>{diagram.execution_order.indexOf(index) + 1}</td>
                      <td>
                        <b>{b?.name || b?.ref}</b>
                        <small>{b?.class_name}</small>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
        {draft && (
          <p role="status">
            {orderDirty(draft)
              ? "Execution-order proposal has not been exported."
              : "An execution-order copy was exported. The opened original remains unchanged."}
          </p>
        )}
        <div className="button-row">
          <button
            className={!shown ? "primary" : ""}
            disabled={!usable || busy}
            onClick={() => void prepare()}
          >
            {draft ? "Review execution order" : "Inspect execution order"}
          </button>
        </div>
        {selected && (
          <details>
            <summary>Execution-order source details</summary>
            <p>
              {selected.members.length} original blocks ·{" "}
              {selected.edge_relationships.length} recorded wire relationships
            </p>
            <code style={{ overflowWrap: "anywhere" }}>
              {selected.selection_sha256}
            </code>
          </details>
        )}
        {busy && (
          <p role="status">Checking the original CAF execution order…</p>
        )}
        {error?.owner === context && <p role="alert">{error.text}</p>}
        {shown && (
          <section aria-label="Reviewed CAF execution order">
            <p>
              {shown.data.result.changed_positions} positions change. All
              recorded wire relationships remain unchanged.
            </p>
            <div className="button-row">
              <button
                className="primary"
                disabled={!usable || busy}
                onClick={() => void save()}
              >
                Save execution-order CAF copy
              </button>
              <button
                disabled={!usable || busy}
                onClick={() => {
                  if (
                    reviewNow.current === shown &&
                    usableNow.current &&
                    current(shown.owner, shown.ticket)
                  )
                    saveBlob(shown.blob, "caf-execution-order-review.json");
                }}
              >
                Save exact execution-order review
              </button>
            </div>
          </section>
        )}
      </section>
    </details>
  );
}
