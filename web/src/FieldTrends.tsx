import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  Download,
  Plus,
  RefreshCw,
  Square,
  Trash2,
} from "lucide-react";
import { api, saveBlob } from "./api";
import { showValue } from "./types";
import { ControllerObjectPicker } from "./ControllerObjectPicker";
import { controllerKey, type ControllerTarget } from "./workflow";

type Point = {
  signal: string;
  address: string;
  object_id: string;
  property_id: string;
  unit: string;
  value_type: string;
};
const point = (
  index: number,
  address = "127.0.0.1:47808",
  bound = false,
): Point => ({
  signal: `point_${index}`,
  address,
  object_id: bound ? "" : `analog-input,${index}`,
  property_id: "present-value",
  unit: "",
  value_type: "number",
});

type Draft = {
  owner: string;
  points: Point[];
  name: string;
  interval: number;
  verifyQuality: boolean;
  selectedPoint: number;
};
// Retain local choices across task navigation in this browser document only.
// Exact target and interface keys keep another controller's draft separate.
const fieldDrafts = new Map<string, Draft>();
function newDraft(owner: string, address?: string, bound = false): Draft {
  return {
    owner,
    points: [point(1, address, bound)],
    name: "",
    interval: 10,
    verifyQuality: true,
    selectedPoint: 0,
  };
}
function configKey(value: unknown): string {
  if (Array.isArray(value)) return "[" + value.map(configKey).join(",") + "]";
  if (value !== null && typeof value === "object")
    return (
      "{" +
      Object.entries(value)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([key, item]) => JSON.stringify(key) + ":" + configKey(item))
        .join(",") +
      "}"
    );
  return JSON.stringify(value) ?? "null";
}
function jobTarget(job: any): string {
  const target = job?.controller_target;
  if (target)
    return [
      target.router ? `${target.router} / network ${target.dnet}` : "Direct",
      target.address,
      target.device,
    ].join(" · ");
  return (job?.points || []).map((item: Point) => item.address).join(", ");
}

export function FieldTrends({
  defaultAddress,
  controllerReady,
  defaultTarget,
  interfaceKey,
}: {
  defaultAddress?: string;
  controllerReady?: boolean;
  defaultTarget?: ControllerTarget | null;
  interfaceKey?: string;
}) {
  const bound = !!defaultTarget;
  const address = defaultTarget?.address || defaultAddress;
  const targetIdentity = defaultTarget
    ? controllerKey(defaultTarget)
    : JSON.stringify(["standalone", defaultAddress || null]);
  const draftIdentity = JSON.stringify([targetIdentity, interfaceKey || null]);
  const draftCache = useRef(fieldDrafts);
  const [editingDraft, setEditingDraft] = useState(
    () =>
      draftCache.current.get(draftIdentity) ||
      newDraft(draftIdentity, address, bound),
  );
  const draft =
    editingDraft.owner === draftIdentity
      ? editingDraft
      : draftCache.current.get(draftIdentity) ||
        newDraft(draftIdentity, address, bound);
  const { points, name, interval, verifyQuality } = draft;
  const selectedPoint = Math.min(draft.selectedPoint, points.length - 1);
  const [status, setStatus] = useState<any>({ jobs: [], running_jobs: 0 });
  const [connected, setConnected] = useState(false);
  const [connectorConfig, setConnectorConfig] = useState<any>(null);
  const [sources, setSources] = useState<any[]>([]);
  const [source, setSource] = useState("");
  const [samples, setSamples] = useState<any[]>([]);
  const [events, setEvents] = useState<any[]>([]);
  const [after, setAfter] = useState(0);
  const [pages, setPages] = useState<number[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const selectionIdentity = JSON.stringify([source, after]);
  const currentSelection = useRef(selectionIdentity);
  currentSelection.current = selectionIdentity;
  const mounted = useRef(false);
  const request = useRef(0);
  const operation = useRef(0);
  const expectedConnector = useMemo(() => {
    if (!bound || !interfaceKey) return null;
    try {
      const value = JSON.parse(interfaceKey);
      return value && typeof value === "object" && !Array.isArray(value)
        ? value
        : null;
    } catch {
      return null;
    }
  }, [bound, interfaceKey]);
  const connectorMatches =
    !!expectedConnector &&
    configKey(expectedConnector) === configKey(connectorConfig);
  const serialBound = bound && expectedConnector?.transport === "mstp";
  const ready =
    connected &&
    controllerReady !== false &&
    (!bound || (connectorMatches && !serialBound));
  const contextIdentity = JSON.stringify([
    draftIdentity,
    controllerReady !== false,
    connected,
    configKey(connectorConfig),
  ]);
  const currentContext = useRef(contextIdentity);
  if (currentContext.current !== contextIdentity) {
    currentContext.current = contextIdentity;
    operation.current++;
  }
  useEffect(() => {
    setBusy(false);
  }, [contextIdentity]);
  useEffect(() => {
    draftCache.current.set(editingDraft.owner, editingDraft);
  }, [editingDraft]);
  useEffect(() => {
    setEditingDraft((previous) => {
      draftCache.current.set(previous.owner, previous);
      return (
        draftCache.current.get(draftIdentity) ||
        newDraft(draftIdentity, address, bound)
      );
    });
    setSource("");
    setAfter(0);
    setPages([]);
    setError("");
    setBusy(false);
  }, [draftIdentity, address, bound]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      operation.current++;
      request.current++;
    };
  }, []);
  const refresh = useCallback(async () => {
    const selection = JSON.stringify([source, after]);
    // A completed action can hold an older refresh callback. It must not issue
    // a newer request for a source/cursor the operator has already left.
    if (!mounted.current || selection !== currentSelection.current) return;
    const current = ++request.current;
    const context = currentContext.current;
    const query = new URLSearchParams({ after: String(after), limit: "100" });
    if (source) query.set("source", source);
    try {
      const [state, link, streams, data, log] = await Promise.all([
        api("/field-trends/status"),
        api("/bacnet/status"),
        api("/field-trends/sources"),
        api("/field-trends/samples?" + query),
        api(
          "/field-trends/events?" +
            new URLSearchParams(
              source ? { source, limit: "100" } : { limit: "100" },
            ),
        ),
      ]);
      if (
        !mounted.current ||
        current !== request.current ||
        context !== currentContext.current ||
        selection !== currentSelection.current
      )
        return;
      setStatus(state);
      setConnected(!!link.connected);
      setConnectorConfig(link.config || null);
      setSources(streams);
      setSamples(data);
      setEvents(log);
    } catch (e) {
      if (
        mounted.current &&
        current === request.current &&
        context === currentContext.current &&
        selection === currentSelection.current
      )
        setError(String(e));
    }
  }, [source, after, controllerReady, draftIdentity]);
  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => {
      void refresh();
    }, 5000);
    return () => {
      request.current++;
      window.clearInterval(timer);
    };
  }, [refresh]);
  function editDraft(change: (value: Draft) => Draft) {
    setEditingDraft((current) =>
      change(
        current.owner === draftIdentity
          ? current
          : draftCache.current.get(draftIdentity) ||
              newDraft(draftIdentity, address, bound),
      ),
    );
  }
  async function action(work: (current: () => boolean) => Promise<void>) {
    const generation = ++operation.current;
    const context = currentContext.current;
    const current = () =>
      mounted.current &&
      generation === operation.current &&
      context === currentContext.current;
    setBusy(true);
    setError("");
    try {
      await work(current);
      if (current()) await refresh();
    } catch (e) {
      if (current()) setError(String(e));
    } finally {
      if (current()) setBusy(false);
    }
  }
  function update(index: number, key: keyof Point, value: string) {
    editDraft((old) => ({
      ...old,
      points: old.points.map((p, i) =>
        i === index ? { ...p, [key]: value } : p,
      ),
    }));
  }
  function csv() {
    const columns = [
      "sequence",
      "source_kind",
      "acquisition_kind",
      "clock_basis",
      "source_clock",
      "receipt_at",
      "provenance",
      "source",
      "signal",
      "clock",
      "recorded_at",
      "value",
      "value_type",
      "quality",
      "unit",
    ];
    const quote = (value: unknown) =>
      '"' +
      (typeof value === "object" && value !== null
        ? JSON.stringify(value)
        : String(value ?? "")
      ).replaceAll('"', '""') +
      '"';
    saveBlob(
      new Blob(
        [
          [
            columns.map(quote).join(","),
            ...samples.map((row) =>
              columns.map((key) => quote(row[key])).join(","),
            ),
          ].join("\r\n"),
        ],
        { type: "text/csv;charset=utf-8" },
      ),
      "field-trends-page.csv",
    );
  }
  return (
    <div className="workspace-page field-trends">
      <div className="page-intro">
        <div>
          <span className="eyebrow">FIELD OBSERVATIONS</span>
          <h1>Field trends</h1>
          <p>
            Read addressed BACnet values through the interface selected in
            Connect. Samples and acquisition events persist locally. Explicitly
            recorded COV numeric receipts also appear with their own provenance.
          </p>
        </div>
        <span className={"connection-badge " + (ready ? "connected" : "")}>
          <span className="status-dot" />
          {bound
            ? ready
              ? "Selected controller ready for sampling"
              : "Selected controller sampling unavailable"
            : connected
              ? "BACnet interface open"
              : "Open a BACnet interface in Connect"}
        </span>
      </div>
      <section className="card" aria-label="Field trend acquisition">
        <div className="card-header">
          <h3>
            <Activity size={18} /> Start read-only sampling
          </h3>
          <span className="pill">EXPLICIT START</span>
        </div>
        <div className="card-body">
          <p className="help-text">
            Starting a job sends property reads through the existing BACnet
            interface. Jobs stop if that interface changes or fails. A restart
            preserves samples and requires an explicit new start. This does not
            download programs, command outputs, or acquire controller-native
            alarm events.
          </p>
          <div className="form-grid">
            <label>
              Trend job name
              <input
                aria-label="Trend job name"
                value={name}
                maxLength={120}
                onChange={(e) =>
                  editDraft((old) => ({ ...old, name: e.target.value }))
                }
              />
            </label>
            <label>
              Sampling interval (seconds)
              <input
                aria-label="Field sampling interval"
                type="number"
                min={5}
                max={3600}
                value={interval}
                onChange={(e) =>
                  editDraft((old) => ({
                    ...old,
                    interval: Number(e.target.value),
                  }))
                }
              />
            </label>
            <label className="full">
              <span>
                <input
                  type="checkbox"
                  checked={verifyQuality}
                  onChange={(e) =>
                    editDraft((old) => ({
                      ...old,
                      verifyQuality: e.target.checked,
                    }))
                  }
                />{" "}
                Verify BACnet reliability, status flags and out-of-service
              </span>
            </label>
          </div>
          <p className="help-text">
            Raw values carry unknown quality unless all requested quality checks
            succeed. Read failures appear in the acquisition log; no zero value
            is substituted. Units are operator labels, not device conversions.
          </p>
          {defaultTarget && (
            <>
              <p className="help-text" aria-label="Field sampling target">
                Selected controller: {defaultTarget.address} ·{" "}
                {defaultTarget.device}
                {defaultTarget.router &&
                  ` · router ${defaultTarget.router} · network ${defaultTarget.dnet}`}
                . Sampling choices belong to this target and interface; earlier
                drafts remain separate. Existing jobs keep their original target
                until explicitly stopped.
              </p>
              {!ready && (
                <p className="help-text" role="status">
                  {serialBound
                    ? "Selected-controller sampling over direct MS/TP is not supported by this identity-verified profile. Saved history and existing job controls remain available."
                    : "Verify the selected controller on its matching BACnet interface before choosing points or starting sampling. Saved history remains available."}
                </p>
              )}
              <div className="form-grid">
                <label>
                  Sampling point to choose
                  <select
                    aria-label="Sampling point to choose"
                    value={selectedPoint}
                    disabled={busy}
                    onChange={(e) =>
                      editDraft((old) => ({
                        ...old,
                        selectedPoint: Number(e.target.value),
                      }))
                    }
                  >
                    {points.map((p, i) => (
                      <option key={i} value={i}>
                        {i + 1} · {p.signal}
                      </option>
                    ))}
                  </select>
                </label>
                <ControllerObjectPicker
                  target={defaultTarget}
                  interfaceKey={interfaceKey}
                  connected={ready}
                  value={points[selectedPoint]?.object_id || ""}
                  onChange={(objectId) =>
                    update(selectedPoint, "object_id", objectId)
                  }
                  kind="value"
                  label="Field discovered object"
                  disabled={busy}
                />
              </div>
            </>
          )}
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Signal</th>
                  <th>Unicast target</th>
                  <th>Object</th>
                  <th>Property</th>
                  <th>Value type</th>
                  <th>Unit label</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {points.map((p, i) => (
                  <tr key={i}>
                    {(
                      ["signal", "address", "object_id", "property_id"] as const
                    ).map((key) => (
                      <td key={key}>
                        <input
                          aria-label={`Field ${{ object_id: "object identifier", property_id: "property identifier", signal: "signal", address: "address" }[key]} ${i + 1}`}
                          value={p[key]}
                          readOnly={
                            (key === "address" &&
                              (!!defaultTarget || !!defaultAddress)) ||
                            (key === "object_id" && bound)
                          }
                          onChange={(e) => update(i, key, e.target.value)}
                        />
                      </td>
                    ))}
                    <td>
                      <select
                        aria-label={`Field value type ${i + 1}`}
                        value={p.value_type}
                        onChange={(e) =>
                          update(i, "value_type", e.target.value)
                        }
                      >
                        <option value="number">Number</option>
                        <option value="boolean">Boolean</option>
                      </select>
                    </td>
                    <td>
                      <input
                        aria-label={`Field unit ${i + 1}`}
                        value={p.unit}
                        onChange={(e) => update(i, "unit", e.target.value)}
                      />
                    </td>
                    <td>
                      <button
                        aria-label={`Remove field point ${i + 1}`}
                        disabled={busy || points.length === 1}
                        onClick={() =>
                          editDraft((old) => ({
                            ...old,
                            points: old.points.filter((_, j) => j !== i),
                            selectedPoint: Math.max(
                              0,
                              Math.min(
                                old.selectedPoint,
                                old.points.length - 2,
                              ),
                            ),
                          }))
                        }
                      >
                        <Trash2 size={15} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="button-row">
            <button
              disabled={busy || points.length >= 16}
              onClick={() =>
                editDraft((old) => ({
                  ...old,
                  points: [
                    ...old.points,
                    point(old.points.length + 1, address, bound),
                  ],
                  selectedPoint: old.points.length,
                }))
              }
            >
              <Plus size={15} /> Add field point
            </button>
            <button
              className="primary"
              disabled={
                busy || !ready || (bound && points.some((p) => !p.object_id))
              }
              onClick={() =>
                action(async (current) => {
                  const job = await api("/field-trends/start", {
                    points,
                    name,
                    interval_seconds: interval,
                    verify_quality: verifyQuality,
                    ...(defaultTarget
                      ? {
                          controller_target: {
                            address: defaultTarget.address,
                            device: defaultTarget.device,
                            router: defaultTarget.router || null,
                            dnet: defaultTarget.dnet ?? null,
                          },
                          expected_connector_config: expectedConnector,
                        }
                      : {}),
                  });
                  // A job stays bound to its original target. A late admission
                  // is visible in global jobs, never selected for a new target.
                  if (!current()) return;
                  if (
                    defaultTarget &&
                    (!job.controller_target ||
                      controllerKey(job.controller_target) !==
                        controllerKey(defaultTarget) ||
                      configKey(job.connector_config) !==
                        configKey(expectedConnector))
                  )
                    throw new Error(
                      "The sampling job response does not match the selected controller and interface. Refresh sampling jobs to inspect its original target; no source was selected.",
                    );
                  setSource(job.source);
                  setAfter(0);
                  setPages([]);
                })
              }
            >
              Start field sampling
            </button>
          </div>
        </div>
      </section>
      <section className="card" aria-label="Field sampling jobs">
        <div className="card-header">
          <h3>Sampling jobs</h3>
          <button onClick={() => action(async () => {})} disabled={busy}>
            <RefreshCw size={15} /> Refresh field trends
          </button>
        </div>
        {!status.jobs.length ? (
          <div className="card-body">
            No sampling jobs in this server session. Saved samples remain below.
          </div>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Job</th>
                  <th>Original target</th>
                  <th>State</th>
                  <th>Polls</th>
                  <th>Samples</th>
                  <th>Failures</th>
                  <th>Last error</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {status.jobs.map((job: any) => (
                  <tr key={job.id}>
                    <td>
                      <button
                        onClick={() => {
                          setSource(job.source);
                          setAfter(0);
                          setPages([]);
                        }}
                      >
                        {job.name || job.id}
                      </button>
                    </td>
                    <td>{jobTarget(job) || "Original target unavailable"}</td>
                    <td>{job.state}</td>
                    <td>{job.polls}</td>
                    <td>{job.samples}</td>
                    <td>{job.failures}</td>
                    <td>{job.last_error || "—"}</td>
                    <td>
                      <button
                        disabled={busy || !job.running}
                        onClick={() =>
                          action(async () => {
                            await api("/field-trends/stop", { id: job.id });
                          })
                        }
                      >
                        <Square size={13} /> Stop sampling
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <section className="card" aria-label="Saved field trend samples">
        <div className="card-header">
          <h3>Saved field samples</h3>
          <button disabled={!samples.length} onClick={csv}>
            <Download size={15} /> Export field page CSV
          </button>
        </div>
        <div className="card-body">
          <p className="help-text">
            Saved samples retain their original source across controllers and
            remain available offline. Selecting a controller does not retarget
            existing jobs or turn these saved observations into live values.
          </p>
          <label>
            Field source
            <select
              aria-label="Field trend source"
              value={source}
              onChange={(e) => {
                setSource(e.target.value);
                setAfter(0);
                setPages([]);
              }}
            >
              <option value="">All field sources</option>
              {sources.map((stream: any) => (
                <option key={stream.source} value={stream.source}>
                  {stream.source} ·{" "}
                  {stream.provenance?.acquisition_kind === "bacnet-cov"
                    ? "COV receipts · "
                    : ""}
                  {stream.samples} samples
                  {stream.provenance?.controller_target &&
                    ` · ${jobTarget(stream.provenance)}`}
                </option>
              ))}
            </select>
          </label>
          <div className="button-row">
            <button
              disabled={
                busy ||
                !sources.find((s) => s.source === source)?.ended ||
                status.jobs.some(
                  (job: any) => job.source === source && job.running,
                )
              }
              onClick={() =>
                action(async (current) => {
                  const selection = currentSelection.current;
                  const result = await api("/field-trends/retire", { source });
                  if (!current() || selection !== currentSelection.current)
                    return;
                  if (result.audit_error) setError(result.audit_error);
                  setSource("");
                  setAfter(0);
                  setPages([]);
                })
              }
            >
              Delete ended field history
            </button>
            <span className="help-text">
              Deletes saved samples and the selected ended source marker. COV
              receipts and provenance belonging to this source are also deleted.
              Acquisition log events remain.
            </span>
          </div>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Source / signal</th>
                <th>Observation / receipt UTC</th>
                <th>Saved UTC</th>
                <th>Value</th>
                <th>Quality</th>
                <th>Unit</th>
              </tr>
            </thead>
            <tbody>
              {samples.map((sample) => (
                <tr key={sample.sequence}>
                  <td>
                    {sample.source}
                    <br />
                    {sample.signal}
                    {sample.provenance?.controller_target && (
                      <>
                        <br />
                        {jobTarget(sample.provenance)}
                      </>
                    )}
                    {sample.acquisition_kind === "bacnet-cov" && (
                      <>
                        <br />
                        COV receipt · controller clock unknown
                      </>
                    )}
                  </td>
                  <td>{sample.clock}</td>
                  <td>{sample.recorded_at}</td>
                  <td>{showValue(sample.value)}</td>
                  <td>{sample.quality}</td>
                  <td>{sample.unit}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="card-body button-row">
          <button
            disabled={!pages.length}
            onClick={() => {
              setAfter(pages.at(-1)!);
              setPages(pages.slice(0, -1));
            }}
          >
            Previous field page
          </button>
          <span>{samples.length} samples shown</span>
          <button
            disabled={samples.length < 100}
            onClick={() => {
              setPages([...pages, after]);
              setAfter(samples.at(-1).sequence);
            }}
          >
            Next field page
          </button>
        </div>
      </section>
      <section className="card" aria-label="Field acquisition events">
        <div className="card-header">
          <h3>Acquisition log</h3>
        </div>
        <div className="card-body">
          <pre className="result">
            {events.length
              ? JSON.stringify(events, null, 2)
              : "No acquisition events recorded."}
          </pre>
        </div>
      </section>
      {error && (
        <div className="inline-error" role="alert">
          {error}
        </div>
      )}
    </div>
  );
}
