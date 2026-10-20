import { useEffect, useRef, useState } from "react";
import { BellRing, Download, Pause, Play, RefreshCw } from "lucide-react";
import { api, saveBlob } from "./api";

const EVENTS = ["activated", "returned", "acknowledged", "source-ended"];
const STATES = [
  "queued",
  "sending",
  "retry_wait",
  "delivered",
  "failed",
  "uncertain",
  "discarded",
  "gap",
];

export function Notifications() {
  const [status, setStatus] = useState<any>(null),
    [routes, setRoutes] = useState<any[]>([]),
    [deliveries, setDeliveries] = useState<any[]>([]),
    [total, setTotal] = useState(0),
    [name, setName] = useState(""),
    [url, setUrl] = useState(""),
    [sources, setSources] = useState(""),
    [bearer, setBearer] = useState(""),
    [urlEnv, setUrlEnv] = useState(""),
    [events, setEvents] = useState(EVENTS),
    [replay, setReplay] = useState(false),
    [routeFilter, setRouteFilter] = useState(""),
    [stateFilter, setStateFilter] = useState(""),
    [after, setAfter] = useState(0),
    [nextAfter, setNextAfter] = useState<number | null>(null),
    [actor, setActor] = useState("operator"),
    [note, setNote] = useState(""),
    [pruneThrough, setPruneThrough] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [message, setMessage] = useState("");
  const mounted = useRef(false),
    epoch = useRef(0),
    busyRef = useRef(false);
  const query = new URLSearchParams({
    after: String(after),
    limit: "100",
    ...(routeFilter ? { route_id: routeFilter } : {}),
    ...(stateFilter ? { state: stateFilter } : {}),
  });
  async function refresh() {
    const current = ++epoch.current;
    const [health, targets, rows] = await Promise.all([
      api("/notifications/status"),
      api("/notifications/routes"),
      api("/notifications/deliveries?" + query),
    ]);
    if (!mounted.current || current !== epoch.current) return;
    setStatus(health);
    setRoutes(targets);
    setDeliveries(rows.rows);
    setTotal(rows.total);
    setNextAfter(rows.next_after);
  }
  useEffect(() => {
    mounted.current = true;
    refresh().catch((e) => {
      if (mounted.current) setError(String(e));
    });
    const timer = setInterval(() => {
      if (!busyRef.current)
        refresh().catch((e) => {
          if (mounted.current) setError(String(e));
        });
    }, 3000);
    return () => {
      mounted.current = false;
      epoch.current++;
      clearInterval(timer);
    };
  }, [after, routeFilter, stateFilter]);
  async function action(fn: () => Promise<void>) {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError("");
    setMessage("");
    epoch.current++;
    try {
      await fn();
      await refresh();
    } catch (e) {
      if (mounted.current) setError(String(e));
    } finally {
      busyRef.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  async function create() {
    await api("/notifications/routes", {
      name: name.trim(),
      url: url.trim() || null,
      url_env: urlEnv.trim() || null,
      sources: sources.trim()
        ? sources
            .split(",")
            .map((item) => item.trim())
            .filter(Boolean)
        : null,
      events,
      bearer_env: bearer.trim() || null,
      start_after: replay ? 0 : null,
    });
    if (mounted.current) {
      setName("");
      setUrl("");
      setUrlEnv("");
      setBearer("");
      setMessage(
        "Route saved and paused. Start it to deliver matching events.",
      );
    }
  }
  async function download(id: number) {
    const value = await api("/notifications/deliveries/" + id);
    if (!mounted.current) return;
    saveBlob(
      new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }),
      `alarm-delivery-${id}.json`,
    );
  }
  return (
    <div className="workspace-page">
      <div className="page-intro">
        <div>
          <span className="eyebrow">ALARMS · EXPLICIT WEBHOOK ROUTES</span>
          <h1>Alarm delivery</h1>
          <p>
            Deliver recorded simulation alarm events to configured HTTP
            endpoints. Delivery receipts and alarm acknowledgments remain
            separate.
          </p>
        </div>
        <BellRing size={30} />
      </div>
      <p className="help-text">
        Saved routes start paused after every server restart. Starting a route
        enables background delivery for its selected sources and events. A retry
        may repeat an accepted message; the receiver must honor its stable
        idempotency key.
      </p>
      {error && (
        <div className="inline-error" role="alert">
          {error}
        </div>
      )}
      {message && <p role="status">{message}</p>}
      {status && (
        <section className="card" aria-label="Alarm delivery status">
          <div className="card-body">
            <p>
              {status.active_routes} active routes · {total} matching delivery
              records · latest alarm event {status.latest_alarm_event_sequence}
            </p>
            {status.worker_error && (
              <p className="inline-error">
                Delivery worker: {status.worker_error}
              </p>
            )}
            {status.source_error && (
              <p className="inline-error">
                Alarm source: {status.source_error}
              </p>
            )}
            <div className="button-row">
              <button disabled={busy} onClick={() => action(refresh)}>
                <RefreshCw size={14} />
                Refresh alarm delivery
              </button>
              <button
                disabled={busy || !status.active_routes}
                onClick={() =>
                  action(async () => {
                    const result = await api("/notifications/cycle", {
                      limit: 20,
                    });
                    if (mounted.current)
                      setMessage(
                        "Delivery pass finished. Inspect the retained results below. " +
                          JSON.stringify(result),
                      );
                  })
                }
              >
                Run delivery pass
              </button>
            </div>
          </div>
        </section>
      )}
      <section className="card" aria-label="Create alarm delivery route">
        <div className="card-header">
          <h3>New route</h3>
        </div>
        <div className="card-body">
          <div className="form-grid">
            <label>
              Route name
              <input
                aria-label="Alarm route name"
                value={name}
                maxLength={100}
                disabled={busy}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <label>
              Webhook URL
              <input
                aria-label="Alarm webhook URL"
                type="url"
                value={url}
                maxLength={2048}
                disabled={busy}
                placeholder="https://receiver.example/alarms"
                onChange={(e) => setUrl(e.target.value)}
              />
            </label>
            <label>
              Or URL environment variable
              <input
                aria-label="Alarm URL environment variable"
                value={urlEnv}
                maxLength={128}
                disabled={busy}
                placeholder="BMS_ALARM_WEBHOOK_URL"
                onChange={(e) => setUrlEnv(e.target.value)}
              />
            </label>
            <label>
              Sources (comma separated; blank selects all)
              <input
                aria-label="Alarm route sources"
                value={sources}
                maxLength={2048}
                disabled={busy}
                onChange={(e) => setSources(e.target.value)}
              />
            </label>
            <label>
              Bearer token environment variable (optional)
              <input
                aria-label="Alarm bearer environment variable"
                value={bearer}
                maxLength={128}
                disabled={busy}
                placeholder="BMS_ALARM_WEBHOOK_TOKEN"
                onChange={(e) => setBearer(e.target.value)}
              />
            </label>
          </div>
          <p className="help-text">
            Provide either a fixed URL or its environment variable name. Use the
            variable for URLs containing secret path/query tokens; fixed URLs
            are saved as route configuration. Token fields take variable names,
            not secret values. HTTPS certificates are verified and redirects are
            not followed.
          </p>
          <div className="button-row">
            {EVENTS.map((event) => (
              <label key={event}>
                <input
                  type="checkbox"
                  disabled={busy}
                  checked={events.includes(event)}
                  onChange={(e) =>
                    setEvents(
                      e.target.checked
                        ? [...events, event]
                        : events.filter((value) => value !== event),
                    )
                  }
                />
                {event}
              </label>
            ))}
          </div>
          <label>
            <input
              type="checkbox"
              checked={replay}
              disabled={busy}
              onChange={(e) => setReplay(e.target.checked)}
            />
            Include retained historical events. Otherwise start after the latest
            current event.
          </label>
          <div className="button-row">
            <button
              className="primary"
              disabled={
                busy ||
                !status?.available ||
                !name.trim() ||
                !!url.trim() === !!urlEnv.trim() ||
                !events.length
              }
              onClick={() => action(create)}
            >
              Save paused alarm route
            </button>
          </div>
        </div>
      </section>
      <section className="card" aria-label="Configured alarm routes">
        <div className="card-header">
          <h3>Routes</h3>
        </div>
        <div className="card-body">
          {!routes.length && (
            <p>No route is configured. No alarm messages are sent.</p>
          )}
          {routes.map((route) => (
            <article key={route.id} className="owned-command">
              <div>
                <b>{route.name}</b>
                <p>{route.url || `Endpoint from ${route.url_env}`}</p>
                <small>
                  {route.enabled ? "Running" : "Paused"} ·{" "}
                  {route.sources?.join(", ") || "all sources"} ·{" "}
                  {route.events.join(", ")}
                </small>
                {" · "}
                <small className="mono">
                  Route {route.id} · cursor {route.cursor}
                </small>
                {route.error && <p className="inline-error">{route.error}</p>}
              </div>
              <button
                disabled={busy}
                onClick={() =>
                  action(async () => {
                    await api("/notifications/routes/enable", {
                      route_id: route.id,
                      enabled: !route.enabled,
                    });
                  })
                }
              >
                {route.enabled ? <Pause size={14} /> : <Play size={14} />}{" "}
                {route.enabled ? "Pause" : "Start"} route {route.name}
              </button>
            </article>
          ))}
        </div>
      </section>
      <section className="card" aria-label="Alarm delivery records">
        <div className="card-header">
          <h3>Delivery history</h3>
        </div>
        <div className="card-body">
          <div className="form-grid">
            <label>
              Delivery route filter
              <select
                aria-label="Delivery route filter"
                disabled={busy}
                value={routeFilter}
                onChange={(e) => {
                  setAfter(0);
                  setRouteFilter(e.target.value);
                }}
              >
                <option value="">All routes</option>
                {routes.map((route) => (
                  <option key={route.id} value={route.id}>
                    {route.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Delivery state filter
              <select
                aria-label="Delivery state filter"
                disabled={busy}
                value={stateFilter}
                onChange={(e) => {
                  setAfter(0);
                  setStateFilter(e.target.value);
                }}
              >
                <option value="">All states</option>
                {STATES.map((state) => (
                  <option key={state} value={state}>
                    {state}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Delivery operator
              <input
                aria-label="Delivery operator"
                maxLength={100}
                disabled={busy}
                value={actor}
                onChange={(e) => setActor(e.target.value)}
              />
            </label>
            <label>
              Reason for retry or discard
              <input
                aria-label="Delivery action note"
                maxLength={500}
                disabled={busy}
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
            </label>
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Delivery</th>
                  <th>State / evidence</th>
                  <th>Operator actions</th>
                </tr>
              </thead>
              <tbody>
                {deliveries.map((row) => (
                  <tr key={row.id}>
                    <td>
                      <b>
                        #{row.id} ·{" "}
                        {routes.find((route) => route.id === row.route_id)
                          ?.name || row.route_id}
                      </b>
                      <small>
                        Event {row.event_sequence ?? "gap"} · {row.kind}
                      </small>
                    </td>
                    <td>
                      <b>{row.state}</b>
                      <small>{row.attempts} attempts</small>
                      {row.error && <small>{row.error}</small>}
                      <small className="mono">{row.payload_sha256}</small>
                    </td>
                    <td>
                      <button
                        disabled={busy}
                        onClick={() => action(() => download(row.id))}
                      >
                        <Download size={13} />
                        Download delivery {row.id}
                      </button>
                      {["failed", "uncertain"].includes(row.state) && (
                        <button
                          disabled={busy || !note.trim() || !actor.trim()}
                          onClick={() =>
                            action(async () => {
                              await api("/notifications/retry", {
                                id: row.id,
                                actor: actor.trim(),
                                note: note.trim(),
                              });
                            })
                          }
                        >
                          {row.state === "uncertain"
                            ? "Retry uncertain delivery"
                            : "Retry delivery"}{" "}
                          {row.id}
                        </button>
                      )}
                      {["queued", "retry_wait", "failed", "uncertain"].includes(
                        row.state,
                      ) && (
                        <button
                          disabled={busy || !note.trim() || !actor.trim()}
                          onClick={() =>
                            action(async () => {
                              await api("/notifications/discard", {
                                id: row.id,
                                actor: actor.trim(),
                                note: note.trim(),
                              });
                            })
                          }
                        >
                          Discard delivery {row.id}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!deliveries.length && (
            <p>No delivery records match these filters.</p>
          )}
          <div className="button-row">
            <button disabled={busy || !after} onClick={() => setAfter(0)}>
              First delivery page
            </button>
            <span>{total} matching records</span>
            <button
              disabled={busy || nextAfter === null}
              onClick={() => setAfter(nextAfter!)}
            >
              Next delivery page
            </button>
          </div>
          <details>
            <summary>Release completed history capacity</summary>
            <p>
              Across all routes, delete up to 1000 delivered, discarded or gap
              records through the selected ID. Queued, sending, failed and
              uncertain deliveries remain. Download evidence first if it is
              needed.
            </p>
            <label>
              Completed history through ID
              <input
                aria-label="Completed delivery history through ID"
                type="number"
                min={1}
                disabled={busy}
                value={pruneThrough}
                onChange={(e) => setPruneThrough(e.target.value)}
              />
            </label>
            <button
              disabled={busy || !pruneThrough}
              onClick={() =>
                action(async () => {
                  const id = Number(pruneThrough);
                  if (!Number.isInteger(id) || id < 1)
                    throw new Error("Enter a positive completed delivery ID.");
                  const result = await api("/notifications/prune", {
                    through_id: id,
                    limit: 1000,
                  });
                  if (mounted.current)
                    setMessage(
                      "Completed delivery history cleanup: " +
                        JSON.stringify(result),
                    );
                })
              }
            >
              Delete completed delivery history
            </button>
          </details>
        </div>
      </section>
    </div>
  );
}
