import { useEffect, useRef, useState } from "react";
import { api, download } from "./api";
import { randomUUID } from "./browserCrypto";
import { controllerKey } from "./workflow";
import type { SnapshotRestoreArchive } from "./nativeSnapshotRestoreContract";

type Row = Record<string, any>;
const profile = "native-inline-local-program-draft/1";
const base = "/bacnet/controller/native-application/inline-sequence/draft";

export function NativeInlineDraft({
  source,
  sources,
}: {
  source: SnapshotRestoreArchive;
  sources: Row[];
}) {
  const candidates = sources.filter(
    (row) =>
      row.source_identity_matches &&
      row.identity &&
      ["model-name", "firmware-revision", "vendor-identifier"].every(
        (k) => row.identity[k] === source.identity[k],
      ),
  );
  const [donorId, setDonor] = useState(source.capture_id);
  const [purpose, setPurpose] = useState("observe");
  const [layout, setLayout] = useState("activities");
  const [first, setFirst] = useState("3000000");
  const [review, setReview] = useState<Row | null>(null);
  const [pendingSelection, setPendingSelection] = useState<string | null>(null);
  const pendingRef = useRef<string | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const epoch = useRef(0);
  const alive = useRef(true);
  const donor = candidates.find((x) => x.id === donorId);
  const current = useRef("");
  const selection = JSON.stringify([
    source.capture_id,
    source.snapshot_sha256,
    donor?.id,
    donor?.evidence_sha256,
    controllerKey(source.target),
    purpose,
    layout,
    first,
  ]);
  if (current.current !== selection) {
    current.current = selection;
    epoch.current++;
  }
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      epoch.current++;
    };
  }, []);
  const working = pendingSelection === selection;
  const applicable = review?.selection === selection ? review : null;
  const valid =
    /^\d+$/.test(first) &&
    Number(first) >= 1 &&
    Number(first) <= 4194302 &&
    Boolean(donor);
  function reset(change: () => void) {
    epoch.current++;
    setReview(null);
    setError("");
    setMessage("");
    pendingRef.current = null;
    setPendingSelection(null);
    change();
  }
  async function run() {
    if (pendingRef.current === selection || !valid || !donor) return;
    const ticket = ++epoch.current;
    const active = () =>
      alive.current &&
      epoch.current === ticket &&
      current.current === selection;
    const request = {
      ...source.target,
      operation_id: randomUUID(),
      capture_id: source.capture_id,
      snapshot_sha256: source.snapshot_sha256,
      prototype_capture_id: donor.id,
      prototype_sha256: donor.evidence_sha256,
      first_instance: Number(first),
      purpose,
      layout,
    };
    pendingRef.current = selection;
    setPendingSelection(selection);
    setError("");
    setMessage("");
    try {
      if (applicable) {
        const saved = await download(
          base + "/export",
          { ...request, review_sha256: applicable.review_sha256 },
          "inline-reheat-" + purpose + ".moi",
          active,
        );
        if (active() && saved)
          setMessage("Saved the reviewed local program file.");
      } else {
        const r = await api(base + "/review", request);
        if (!active()) return;
        if (
          r.profile !== profile ||
          r.snapshot_sha256 !== source.snapshot_sha256 ||
          r.capture_id !== source.capture_id ||
          r.prototype_capture_id !== donor.id ||
          r.prototype_snapshot_sha256 !== donor.evidence_sha256 ||
          !r.target ||
          controllerKey(r.target) !== controllerKey(source.target) ||
          r.purpose !== purpose ||
          r.layout !== layout ||
          r.controller_queries !== false ||
          r.production_transfer_qualified !== false ||
          !/^[0-9a-f]{64}$/.test(r.review_sha256) ||
          !/^[0-9a-f]{64}$/.test(r.compilation?.candidate_sha256) ||
          !Number.isSafeInteger(r.compilation?.root_members) ||
          (layout === "activities" &&
            r.compilation?.activity_layout?.flattened_schedule_verified !==
              true)
        )
          throw new Error(
            "The returned draft does not match this archive and selection.",
          );
        setReview({ ...r, selection });
      }
    } catch (failure) {
      if (active()) setError(String(failure));
    } finally {
      if (active()) {
        pendingRef.current = null;
        setPendingSelection(null);
      }
    }
  }
  const details = applicable?.compilation;
  return (
    <details className="native-compiler-source">
      <summary>Draft an inline reheat program</summary>
      <p>
        Build a local program file from the selected archive. The airflow window
        is 30 seconds. The valve lockout starts at 30 CFM and the discharge
        limit starts at 125 °F.
      </p>
      {!donor && (
        <p role="status">
          Select a verified logic block source captured from the same model and
          firmware.
        </p>
      )}
      <fieldset>
        <legend>Draft settings</legend>
        <label>
          Logic block source
          <select
            aria-label="Logic block source"
            value={donorId}
            onChange={(e) => reset(() => setDonor(e.target.value))}
          >
            {candidates.map((c) => (
              <option key={c.id} value={c.id}>
                {c.identity["object-name"]} ·{" "}
                {new Date(c.captured_at).toLocaleString()}
              </option>
            ))}
          </select>
        </label>
        <label>
          Program purpose
          <select
            aria-label="Program purpose"
            value={purpose}
            onChange={(e) => reset(() => setPurpose(e.target.value))}
          >
            <option value="observe">Observe existing controls</option>
            <option value="control">Control the heating valve</option>
          </select>
        </label>
        <label>
          Drawing layout
          <select
            aria-label="Drawing layout"
            value={layout}
            onChange={(e) => reset(() => setLayout(e.target.value))}
          >
            <option value="activities">Grouped Activities</option>
            <option value="flat">Single root drawing</option>
          </select>
        </label>
        <label>
          First new object instance
          <input
            aria-label="First new object instance"
            type="number"
            min="1"
            max="4194302"
            step="1"
            value={first}
            onChange={(e) => reset(() => setFirst(e.target.value))}
          />
        </label>
      </fieldset>
      {details && (
        <p role="status">
          {details.root_members} root blocks · {details.added_records} added
          records
          {details.activity_layout && (
            <>
              {" "}
              · {details.activity_layout.activities_added} Activities ·{" "}
              {details.activity_layout.signal_connections_traced} verified
              signal connections
            </>
          )}
          .{" "}
          {purpose === "observe"
            ? "The existing valve wiring is preserved."
            : "The draft connects the valve to the protected heat command."}
        </p>
      )}
      <button
        type="button"
        disabled={!valid || working}
        onClick={() => void run()}
      >
        {working
          ? "Working…"
          : applicable
            ? "Save reviewed program file"
            : "Review local program"}
      </button>
      {message && <p role="status">{message}</p>}
      {error && <p role="alert">{error}</p>}
    </details>
  );
}
