import { useEffect, useRef, useState } from "react";
import { api } from "./api";

type Target = {
  address: string;
  device: string;
  router: string | null;
  dnet: number | null;
};
type Header = {
  id: string;
  target: Target;
  connector_config: Record<string, unknown>;
  command_slot_objects?: string[];
  started_at: string;
  finished_at: string;
};
type Point = {
  object: string;
  properties: Record<
    string,
    { value?: unknown; complete?: boolean; status?: string }
  >;
};
type Result = {
  baseline_id: string;
  current_id: string;
  object: string;
  slots_compared: number;
  changes: {
    priority: number;
    change: string;
    before: string;
    after: string;
  }[];
};

function sameTarget(a: Target, b: Target) {
  return (
    a.address === b.address &&
    a.device === b.device &&
    a.router === b.router &&
    a.dnet === b.dnet
  );
}

export function CommandSlotComparison({
  report,
}: {
  report: Header & { objects: Point[] };
}) {
  const points = report.objects.filter(
    (p) => p.properties["priority-array"]?.complete === true,
  );
  const [open, setOpen] = useState(false);
  const [earlier, setEarlier] = useState<Header[] | null>(null);
  const [baseline, setBaseline] = useState("");
  const [object, setObject] = useState(points[0]?.object ?? "");
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const generation = useRef(0);

  useEffect(() => {
    if (!open) return;
    let visible = true;
    setEarlier(null);
    setBaseline("");
    setError("");
    setResult(null);
    setBusy(false);
    api("/bacnet/point-status/profile")
      .then((profile) => {
        if (!visible) return;
        const candidates: Header[] = profile.reports
          .filter(
            (other: Header) =>
              other.id !== report.id &&
              sameTarget(other.target, report.target) &&
              Object.keys(other.connector_config).length ===
                Object.keys(report.connector_config).length &&
              Object.entries(other.connector_config).every(
                ([k, v]) => v === report.connector_config[k],
              ) &&
              other.command_slot_objects?.includes(object) &&
              Date.parse(other.finished_at) <= Date.parse(report.started_at),
          )
          .reverse();
        setEarlier(candidates);
        setBaseline(candidates[0]?.id ?? "");
      })
      .catch((e) => {
        if (visible) setError(String(e));
      });
    return () => {
      visible = false;
      generation.current++;
    };
  }, [open, report, object]);

  function reset() {
    generation.current++;
    setResult(null);
    setBusy(false);
    setError("");
  }
  async function compare() {
    const ticket = ++generation.current;
    setBusy(true);
    setResult(null);
    setError("");
    try {
      const comparison: Result = await api(
        "/bacnet/point-status/compare-command-slots",
        {
          baseline_id: baseline,
          current_id: report.id,
          object_id: object,
        },
      );
      if (ticket !== generation.current) return;
      if (
        comparison.baseline_id !== baseline ||
        comparison.current_id !== report.id ||
        comparison.object !== object ||
        comparison.slots_compared !== 16 ||
        !Array.isArray(comparison.changes)
      )
        throw new Error(
          "The comparison does not match these reports and point.",
        );
      setResult(comparison);
    } catch (e) {
      if (ticket === generation.current) setError(String(e));
    } finally {
      if (ticket === generation.current) setBusy(false);
    }
  }

  if (!points.length) return null;
  return (
    <details
      className="observation-retention"
      onToggle={(e) => setOpen(e.currentTarget.open)}
    >
      <summary>Compare command slots</summary>
      {open && (
        <section aria-label="Compare retained command slots">
          <p>
            Compare all 16 priorities with an earlier inspection of this point.
            Slots are read in sequence. A difference shows what changed between
            the two readings.
          </p>
          <label>
            Point for slot comparison
            <select
              value={object}
              onChange={(e) => {
                reset();
                setObject(e.target.value);
              }}
            >
              {points.map((p) => (
                <option key={p.object} value={p.object}>
                  {String(p.properties["object-name"]?.value ?? p.object)} ·{" "}
                  {p.object}
                </option>
              ))}
            </select>
          </label>
          {earlier === null && !error && (
            <p role="status">Loading earlier reports…</p>
          )}
          {earlier?.length === 0 && (
            <p role="status">
              No earlier complete command slots are available for this point on
              this interface. Inspect the point again with commandable
              properties selected to compare it.
            </p>
          )}
          {!!earlier?.length && (
            <>
              <label>
                Earlier point report
                <select
                  value={baseline}
                  onChange={(e) => {
                    reset();
                    setBaseline(e.target.value);
                  }}
                >
                  {earlier.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.finished_at} · {r.id}
                    </option>
                  ))}
                </select>
              </label>
              <button
                disabled={!baseline || !object || busy}
                onClick={() => void compare()}
              >
                Compare retained readings
              </button>
            </>
          )}
          {busy && <p role="status">Comparing the two reports…</p>}
          {error && <p role="alert">{error}</p>}
          {result && (
            <>
              <p role="status">
                {result.changes.length} of {result.slots_compared} command slots
                changed.
              </p>
              {result.changes.length > 0 && (
                <div className="table-wrap">
                  <table>
                    <caption>Command slot changes for {result.object}</caption>
                    <thead>
                      <tr>
                        <th>Priority</th>
                        <th>Change</th>
                        <th>Earlier</th>
                        <th>Later</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.changes.map((row) => (
                        <tr key={row.priority}>
                          <th scope="row">{row.priority}</th>
                          <td>{row.change}</td>
                          <td>{row.before}</td>
                          <td>{row.after}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </section>
      )}
    </details>
  );
}
