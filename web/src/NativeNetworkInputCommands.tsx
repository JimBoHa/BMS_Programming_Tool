import { useContext, useEffect, useRef, useState } from "react";
import {
  api,
  apiJsonDocument,
  apiKeepalive,
  saveBlob,
  type JsonDocument,
} from "./api";
import { sha256Blob } from "./activityContracts";
import { randomUUID } from "./browserCrypto";
import { NativeBooleanTransferContext } from "./NativeBooleanTransferContext";
import {
  restoreHash,
  restoreID,
  snapshotRestoreTarget,
  type SnapshotRestoreArchive,
} from "./nativeSnapshotRestoreContract";

type Slot = { type: string; value: unknown };
type CommandSource = Pick<
  SnapshotRestoreArchive,
  "capture_id" | "snapshot_sha256" | "sha256" | "target"
> & {
  source_kind?: "native-backup" | "controller-file";
};
type Input = {
  object: string;
  name: string;
  verified: boolean;
  values: Record<string, unknown> & { "priority-array"?: Slot[] };
  unavailable: Record<string, string>;
};
type Change = {
  object: string;
  status: string;
  changed_fields: string[];
  priority_changes: { priority: number; before: Slot; after: Slot }[];
};
type Report = {
  id: string;
  profile: string;
  read_only: boolean;
  selection: {
    source_kind?: CommandSource["source_kind"];
    capture_id: string;
    snapshot_sha256: string;
    target: SnapshotRestoreArchive["target"];
    offset: number;
    limit: number;
    scope: string;
  };
  finished_at: string;
  input_count: number;
  source_sha256: string;
  evidence_sha256: string;
  baseline_id: string | null;
  points: Input[];
  comparison: Change[] | null;
  unclassified_root_inputs: string[];
};
type Saved = {
  id: string;
  finished_at: string;
  offset: number;
  limit: number;
  verified: number;
  points: number;
};
const base = "/bacnet/controller/native-application/network-inputs";
const pageSize = 16;

function valueLabel(value: unknown): string {
  if (value === null) return "Released";
  if (
    typeof value === "number" ||
    typeof value === "boolean" ||
    typeof value === "string"
  )
    return String(value);
  if (typeof value === "object" && value && "value" in value) {
    const name =
      "name" in value && typeof value.name === "string" ? value.name : "";
    const code = String(value.value);
    return name && name !== code ? name + " (" + code + ")" : code;
  }
  return "Unavailable";
}

function activePriorities(point: Input) {
  const slots = point.values["priority-array"];
  if (
    !Array.isArray(slots) ||
    slots.length !== 16 ||
    "priority-array" in point.unavailable
  )
    return "Incomplete reading";
  return (
    slots
      .flatMap((slot, i) =>
        slot.type === "null"
          ? []
          : ["P" + (i + 1) + " " + valueLabel(slot.value)],
      )
      .join(", ") || "All released"
  );
}

function resultLabel(point: Input, change?: Change) {
  if (!point.verified)
    return (
      Object.entries(point.unavailable)
        .map(([key, message]) => key + " · " + message)
        .join(", ") || "Unverified"
    );
  if (!change) return "Verified";
  if (change.status === "unverified") return "Baseline unverified";
  if (change.status === "unchanged") return "Priorities unchanged";
  return change.priority_changes
    .map(
      (c) =>
        "P" +
        c.priority +
        " " +
        valueLabel(c.before.value) +
        " → " +
        valueLabel(c.after.value),
    )
    .join(", ");
}

function validRows(r: Report) {
  if (
    !Array.isArray(r.points) ||
    new Set(r.points.map((p) => p?.object)).size !== r.points.length
  )
    return false;
  const valid = r.points.every(
    (p) =>
      p &&
      typeof p.object === "string" &&
      typeof p.name === "string" &&
      typeof p.verified === "boolean" &&
      p.values &&
      p.unavailable &&
      typeof p.unavailable === "object",
  );
  if (!valid || !r.baseline_id) return valid && r.comparison === null;
  return (
    restoreID(r.baseline_id) &&
    Array.isArray(r.comparison) &&
    r.comparison.length === r.points.length &&
    r.comparison.every(
      (item, index) =>
        item &&
        item.object === r.points[index].object &&
        ["unchanged", "changed", "unverified"].includes(item.status) &&
        Array.isArray(item.changed_fields) &&
        Array.isArray(item.priority_changes) &&
        item.priority_changes.length > 0 === (item.status === "changed") &&
        item.priority_changes.every(
          (c) =>
            c &&
            Number.isInteger(c.priority) &&
            c.priority >= 1 &&
            c.priority <= 16 &&
            c.before &&
            c.after,
        ),
    )
  );
}

export function NativeNetworkInputCommands({
  source,
  connected,
  locked,
}: {
  source: CommandSource;
  connected: boolean;
  locked: boolean;
}) {
  const context = useContext(NativeBooleanTransferContext);
  const [doc, setDoc] = useState<JsonDocument<Report> | null>(null);
  const [saved, setSaved] = useState<Saved[]>([]);
  const [baseline, setBaseline] = useState("");
  const [offset, setOffset] = useState(0);
  const [count, setCount] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const details = useRef<HTMLDetailsElement>(null);
  const active = useRef<{ ticket: string; field: boolean } | null>(null);
  const busyCallback = useRef(context?.onBusy);
  busyCallback.current = context?.onBusy;
  function release() {
    const work = active.current;
    active.current = null;
    if (work?.field) busyCallback.current?.(work.ticket, false);
  }
  function cancel() {
    const work = active.current;
    if (work?.field)
      void apiKeepalive("/bacnet/controller/native-application/cancel", {
        operation_id: work.ticket,
      }).catch(() => {});
    release();
  }
  useEffect(() => {
    const hide = () => {
      if (document.hidden) {
        cancel();
        setBusy(false);
      }
    };
    document.addEventListener("visibilitychange", hide);
    window.addEventListener("pagehide", cancel);
    return () => {
      document.removeEventListener("visibilitychange", hide);
      window.removeEventListener("pagehide", cancel);
      cancel();
    };
  }, []);
  const known = saved.filter(
    (entry) => entry.offset === offset && entry.limit === pageSize,
  );
  const pending = busy || locked;
  function page(next: number) {
    setOffset(next);
    setBaseline("");
    setDoc(null);
    setMessage("");
  }
  async function run(mode: "read" | "compare" | "history" | "load") {
    const field = mode === "read" || mode === "compare";
    if (
      active.current ||
      !details.current?.open ||
      document.hidden ||
      (field &&
        (!connected || locked || context?.workspaceCurrent?.() === false))
    )
      return;
    if ((mode === "compare" || mode === "load") && !restoreID(baseline)) return;
    const work = { ticket: randomUUID(), field };
    active.current = work;
    setBusy(true);
    setMessage("");
    if (field) busyCallback.current?.(work.ticket, true);
    try {
      if (mode === "history") {
        const history: Saved[] = await api(
          base + "/history/" + source.capture_id,
        );
        if (active.current !== work) return;
        if (
          !Array.isArray(history) ||
          history.some(
            (x) =>
              !restoreID(x.id) ||
              !Number.isSafeInteger(x.offset) ||
              x.offset < 0 ||
              !Number.isSafeInteger(x.limit) ||
              x.limit < 1,
          )
        )
          throw new Error("Invalid saved-reading index.");
        setSaved(history);
        if (!history.length) setMessage("No saved readings for this capture.");
        return;
      }
      const result = await apiJsonDocument<Report>(
        field ? base + "/read" : base + "/reports/" + baseline,
        field
          ? {
              ...source.target,
              source_kind: source.source_kind,
              capture_id: source.capture_id,
              snapshot_sha256: source.snapshot_sha256,
              operation_id: work.ticket,
              offset,
              limit: pageSize,
              baseline_id: mode === "compare" ? baseline : null,
            }
          : undefined,
        true,
      );
      const r = result.data;
      const hash = result.headers?.get("X-Studio-Artifact-Sha256");
      if (
        !restoreHash(hash) ||
        (await sha256Blob(result.blob)) !== hash ||
        r.profile !== "native-network-input-commands/1" ||
        r.read_only !== true ||
        !restoreID(r.id) ||
        !restoreHash(r.evidence_sha256) ||
        r.source_sha256 !== source.sha256 ||
        r.selection?.scope !== "root-exposed-commandable-file-3" ||
        (r.selection.source_kind ?? "native-backup") !==
          (source.source_kind ?? "native-backup") ||
        r.selection.capture_id !== source.capture_id ||
        r.selection.snapshot_sha256 !== source.snapshot_sha256 ||
        !snapshotRestoreTarget(r.selection.target, source.target) ||
        r.selection.offset !== offset ||
        r.selection.limit !== pageSize ||
        !Number.isSafeInteger(r.input_count) ||
        r.input_count < offset ||
        !Array.isArray(r.points) ||
        r.points.length !== Math.min(pageSize, r.input_count - offset) ||
        !Array.isArray(r.unclassified_root_inputs) ||
        (mode === "load" && r.id !== baseline) ||
        (mode === "compare" && r.baseline_id !== baseline) ||
        (mode === "read" && r.baseline_id !== null) ||
        !validRows(r)
      )
        throw new Error(
          "The reading does not match the selected capture and input page.",
        );
      if (active.current !== work) return;
      setDoc(result);
      setCount(r.input_count);
      setSaved((prev) => [
        {
          id: r.id,
          finished_at: r.finished_at,
          offset,
          limit: pageSize,
          verified: r.points.filter((p) => p.verified).length,
          points: r.points.length,
        },
        ...prev.filter((x) => x.id !== r.id),
      ]);
      if (mode === "read") setBaseline(r.id);
    } catch (error) {
      if (active.current === work) setMessage(String(error));
    } finally {
      if (active.current === work) {
        release();
        setBusy(false);
      }
    }
  }
  const r = doc?.data;
  return (
    <details
      ref={details}
      onToggle={(e) => {
        if (e.target === e.currentTarget && !e.currentTarget.open) {
          cancel();
          setBusy(false);
        }
      }}
    >
      <summary>
        {source.source_kind === "controller-file"
          ? "Inspect network input commands"
          : "Check network inputs before and after restart"}
      </summary>
      <section aria-label="Network input command readings">
        <p>
          {source.source_kind === "controller-file"
            ? "The captured program identifies the inputs. Read their current command priorities from the controller, or compare them with an earlier reading."
            : "Read the controller’s command priorities before a transfer. Compare them with a second reading after restart to see which inputs gained, lost or changed a command."}
        </p>
        {!connected && (
          <p>
            Open the controller recorded in this capture to read live values.
            Saved readings are available offline.
          </p>
        )}
        <div className="button-row">
          <button
            disabled={pending || !connected}
            onClick={() => void run("read")}
          >
            Read network inputs
          </button>
          <button disabled={busy} onClick={() => void run("history")}>
            List saved readings
          </button>
        </div>
        <label>
          Baseline reading
          <select
            value={baseline}
            disabled={busy}
            onChange={(e) => {
              setBaseline(e.target.value);
              setDoc(null);
              setMessage("");
            }}
          >
            <option value="">Select a saved reading</option>
            {known.map((s) => (
              <option key={s.id} value={s.id}>
                {s.finished_at} · {s.verified}/{s.points} verified
              </option>
            ))}
          </select>
        </label>
        <div className="button-row">
          <button disabled={busy || !baseline} onClick={() => void run("load")}>
            Open saved reading
          </button>
          <button
            disabled={pending || !connected || !baseline}
            onClick={() => void run("compare")}
          >
            Compare with baseline
          </button>
        </div>
        <p role="status">
          {busy
            ? "Reading…"
            : message ||
              (r &&
                "Reading completed " +
                  r.finished_at +
                  " · " +
                  r.points.filter((p) => p.verified).length +
                  " of " +
                  r.points.length +
                  " inputs verified.")}
        </p>
        {r && (
          <>
            {r.unclassified_root_inputs.length > 0 && (
              <p>
                Unclassified root inputs:{" "}
                {r.unclassified_root_inputs.join(", ")}
              </p>
            )}
            {r.input_count === 0 ? (
              <p>
                The captured application contains no identified root-level
                commandable network inputs.
              </p>
            ) : (
              <div
                className="network-input-table"
                tabIndex={0}
                role="region"
                aria-label="Controller input priorities"
              >
                <table>
                  <caption>Recorded {r.finished_at}</caption>
                  <thead>
                    <tr>
                      <th>Network input</th>
                      <th>Present value</th>
                      <th>Default</th>
                      <th>Active priorities</th>
                      <th>Verification</th>
                    </tr>
                  </thead>
                  <tbody>
                    {r.points.map((p, i) => {
                      const change = r.comparison?.[i];
                      return (
                        <tr key={p.object}>
                          <th scope="row">
                            {p.name}
                            <br />
                            <small>{p.object}</small>
                          </th>
                          <td>{valueLabel(p.values["present-value"])}</td>
                          <td>{valueLabel(p.values["relinquish-default"])}</td>
                          <td>{activePriorities(p)}</td>
                          <td>
                            {resultLabel(p, change)}
                            {Array.isArray(p.values["status-flags"]) &&
                            (p.values["status-flags"][0] ||
                              p.values["status-flags"][2]) ? (
                              <div>
                                {[
                                  p.values["status-flags"][0] && "In alarm",
                                  p.values["status-flags"][2] && "Overridden",
                                ]
                                  .filter(Boolean)
                                  .join(", ")}
                              </div>
                            ) : null}
                            {change?.changed_fields.length ? (
                              <div>
                                Other changes:{" "}
                                {change.changed_fields.join(", ")}
                              </div>
                            ) : null}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
            <button
              disabled={busy}
              onClick={() =>
                doc &&
                saveBlob(doc.blob, "network-input-commands-" + r.id + ".json")
              }
            >
              Save exact reading
            </button>
          </>
        )}
        {(offset > 0 ||
          (count !== null && count > pageSize) ||
          saved.some((s) => s.offset > offset)) && (
          <div className="button-row">
            <button
              disabled={busy || offset === 0}
              onClick={() => page(offset - pageSize)}
            >
              Previous inputs
            </button>
            <span>Inputs starting at {offset + 1}</span>
            <button
              disabled={
                busy ||
                !(count !== null
                  ? offset + pageSize < count
                  : saved.some((s) => s.offset > offset))
              }
              onClick={() => page(offset + pageSize)}
            >
              Next inputs
            </button>
          </div>
        )}
      </section>
    </details>
  );
}
