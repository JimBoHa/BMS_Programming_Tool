import { useEffect, useRef, useState } from "react";
import { api, downloadGet } from "./api";

export function EventReceptionPanel({
  connected,
  defaultAddress = "",
  defaultDevice = "",
  defaultRouter = "",
  defaultDnet,
}: {
  connected: boolean;
  defaultAddress?: string;
  defaultDevice?: string;
  defaultRouter?: string;
  defaultDnet?: number | null;
}) {
  const [address, setAddress] = useState(defaultAddress);
  const [device, setDevice] = useState(defaultDevice);
  const [object, setObject] = useState("");
  const [router, setRouter] = useState(defaultRouter);
  const [dnet, setDnet] = useState(String(defaultDnet || ""));
  const [process, setProcess] = useState("7");
  const [mode, setMode] = useState("both");
  const [duration, setDuration] = useState("60");
  const [sessions, setSessions] = useState<any[]>([]);
  const [snapshots, setSnapshots] = useState<any[]>([]);
  const [receipt, setReceipt] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [watch, setWatch] = useState(false);
  const [error, setError] = useState("");
  const alive = useRef(false);
  const changing = useRef(false);
  const selected = useRef("");
  const saved = useRef(false);
  const generation = useRef(0);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      generation.current++;
    };
  }, []);
  useEffect(() => {
    generation.current++;
    setAddress(defaultAddress);
    setDevice(defaultDevice);
    setRouter(defaultRouter);
    setDnet(String(defaultDnet || ""));
    setObject("");
  }, [defaultAddress, defaultDevice, defaultRouter, defaultDnet]);
  function show(value: any, fromDisk = false) {
    generation.current++;
    selected.current = value.id;
    saved.current = fromDisk;
    setReceipt(value);
  }
  async function refresh() {
    const state = await api("/bacnet/event-reception/status");
    if (!alive.current) return;
    setSessions(state.sessions);
    setWatch(state.sessions.some((item: any) => item.active));
  }
  useEffect(() => {
    if (!watch) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    async function tick() {
      try {
        const state = await api("/bacnet/event-reception/status");
        const id = selected.current;
        const data =
          id && !saved.current
            ? await api(`/bacnet/event-reception/sessions/${id}`)
            : null;
        if (stopped || !alive.current) return;
        setSessions(state.sessions);
        if (data && selected.current === data.id && !saved.current)
          setReceipt(data);
        if (state.sessions.some((item: any) => item.active))
          timer = setTimeout(tick, 500);
        else setWatch(false);
      } catch (e) {
        if (!stopped && alive.current) {
          setError(String(e));
          setWatch(false);
        }
      }
    }
    timer = setTimeout(tick, 100);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [watch]);

  async function act(action: string, id?: string) {
    if (changing.current) return;
    changing.current = true;
    setBusy(true);
    setError("");
    try {
      if (action === "start") {
        const integer = (text: string) =>
          /^[0-9]+$/.test(text) ? Number(text) : null;
        const data = await api("/bacnet/event-reception/start", {
          address,
          device,
          object_id: object.trim() || null,
          router: router.trim() || null,
          dnet: router.trim() ? integer(dnet) : null,
          process_identifier: integer(process),
          mode,
          duration_seconds: integer(duration),
        });
        if (alive.current) show(data);
      } else if (action === "open") {
        const data = await api(`/bacnet/event-reception/sessions/${id}`);
        if (alive.current) show(data);
      } else if (action === "stop") {
        const data = await api("/bacnet/event-reception/stop", { id });
        if (alive.current) show(data);
      } else if (action === "save") {
        const data = await api("/bacnet/event-reception/save", { id });
        if (alive.current) show(data, true);
        const rows = await api("/bacnet/event-reception/snapshots");
        if (alive.current) setSnapshots(rows);
      } else if (action === "history") {
        const rows = await api("/bacnet/event-reception/snapshots");
        if (alive.current) setSnapshots(rows);
      } else if (action === "saved") {
        const data = await api(`/bacnet/event-reception/snapshots/${id}`);
        if (alive.current) show(data, true);
      } else if (action === "export") {
        const epoch = generation.current;
        const fromDisk = saved.current;
        await downloadGet(
          `/bacnet/event-reception/${saved.current ? "snapshots" : "sessions"}/${id}`,
          `${id}-event-reception.json`,
          () =>
            alive.current &&
            generation.current === epoch &&
            selected.current === id &&
            saved.current === fromDisk,
        );
      }
      await refresh();
    } catch (e) {
      if (alive.current) setError(String(e));
    } finally {
      changing.current = false;
      if (alive.current) setBusy(false);
    }
  }
  return (
    <section
      className="card"
      role="region"
      aria-label="Finite BACnet event reception"
    >
      <div className="card-header">
        <h3>Receive BACnet event notifications</h3>
      </div>
      <div className="card-body">
        <p>
          Listen explicitly on the already-open IPv4 interface for one verified
          Device and process identifier. Devices must already send notifications
          here; this page does not configure recipients or subscribe.
        </p>
        <p className="help-text">
          Unsegmented direct IPv4 or an explicit router/DNET:MAC only. Protocol
          ACK means reception, never operator AcknowledgeAlarm, human receipt,
          resolution or guaranteed delivery. Source clocks and quality remain
          unresolved. No automatic restart; export or save a stopped session
          before restart. Leaving this tab keeps the chosen finite listen window
          running; stop explicitly when finished.
        </p>
        <div className="form-grid">
          <label>
            Event source address
            <input
              aria-label="Event source address"
              value={address}
              disabled={busy}
              onChange={(e) => setAddress(e.target.value)}
            />
          </label>
          <label>
            Event source Device
            <input
              aria-label="Event source Device"
              value={device}
              disabled={busy}
              onChange={(e) => setDevice(e.target.value)}
            />
          </label>
          <label>
            Optional event object filter
            <input
              aria-label="Optional event object filter"
              value={object}
              disabled={busy}
              onChange={(e) => setObject(e.target.value)}
              placeholder="Any object from this Device"
            />
          </label>
          <label>
            Event router endpoint
            <input
              aria-label="Event router endpoint"
              value={router}
              disabled={busy}
              onChange={(e) => setRouter(e.target.value)}
              placeholder="Blank for direct IPv4"
            />
          </label>
          <label>
            Event DNET
            <input
              aria-label="Event DNET"
              value={dnet}
              disabled={busy}
              onChange={(e) => setDnet(e.target.value)}
            />
          </label>
          <label>
            Event process identifier
            <input
              aria-label="Event process identifier"
              value={process}
              disabled={busy}
              onChange={(e) => setProcess(e.target.value)}
            />
          </label>
          <label>
            Event notification mode
            <select
              aria-label="Event notification mode"
              value={mode}
              disabled={busy}
              onChange={(e) => setMode(e.target.value)}
            >
              <option value="both">Confirmed and unconfirmed</option>
              <option value="confirmed">Confirmed only</option>
              <option value="unconfirmed">Unconfirmed only</option>
            </select>
          </label>
          <label>
            Listen duration in seconds
            <input
              aria-label="Listen duration in seconds"
              value={duration}
              disabled={busy}
              onChange={(e) => setDuration(e.target.value)}
            />
          </label>
        </div>
        <div className="actions">
          <button
            disabled={busy || !connected}
            onClick={() => void act("start")}
          >
            Verify identity and start finite listener
          </button>
          <button disabled={busy} onClick={() => void act("refresh")}>
            Refresh event listeners
          </button>
          <button disabled={busy} onClick={() => void act("history")}>
            Load saved event receipts
          </button>
        </div>
        {error && <p role="alert">{error}</p>}
        <ul>
          {sessions.map((item) => (
            <li key={item.id}>
              <button disabled={busy} onClick={() => void act("open", item.id)}>
                {item.config.address} · {item.config.device} · Process{" "}
                {item.config.process_identifier} · {item.state} ·{" "}
                {item.received} receipts
              </button>
            </li>
          ))}
        </ul>
        {!!snapshots.length && (
          <details open>
            <summary>
              Saved event-reception snapshots ({snapshots.length})
            </summary>
            <ul>
              {snapshots.map((item) => (
                <li key={item.id}>
                  <button
                    disabled={busy}
                    onClick={() => void act("saved", item.id)}
                  >
                    {item.id} · {item.created}
                  </button>
                </li>
              ))}
            </ul>
          </details>
        )}
        {receipt && (
          <section aria-label={`Event reception receipt ${receipt.id}`}>
            <h4>
              {receipt.config.device} · {receipt.config.address} · Process{" "}
              {receipt.config.process_identifier}
            </h4>
            <p>
              State: {receipt.state} · Received: {receipt.received} · Ignored:{" "}
              {receipt.ignored} · Evicted: {receipt.evicted} · ACK failures:{" "}
              {receipt.ack_failures} · Remaining: {receipt.seconds_remaining}s.
            </p>
            <p>
              Original local UDP endpoint: {receipt.local_endpoint?.join(":")} ·
              Mode: {receipt.config.mode} · Router:{" "}
              {receipt.config.router || "direct"} · DNET:{" "}
              {receipt.config.dnet ?? "none"}. Receipt time is local; source
              clock and operator acknowledgment are unknown.
            </p>
            {receipt.saved_sha256 && (
              <p>
                Saved immutable snapshot · SHA-256 {receipt.saved_sha256} ·
                Restart never resumes reception.
              </p>
            )}
            {receipt.last_ignored && (
              <p>Last discarded: {receipt.last_ignored}</p>
            )}
            <div className="actions">
              <button
                disabled={busy || !receipt.active || saved.current}
                onClick={() => void act("stop", receipt.id)}
              >
                Stop event listener
              </button>
              <button
                disabled={
                  busy ||
                  receipt.active ||
                  receipt.pending_callbacks > 0 ||
                  !!receipt.saved_sha256
                }
                onClick={() => void act("save", receipt.id)}
              >
                Save stopped event receipt
              </button>
              <button
                disabled={busy}
                onClick={() => void act("export", receipt.id)}
              >
                Export event reception receipt
              </button>
            </div>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Receipt</th>
                    <th>Object</th>
                    <th>Notify / event</th>
                    <th>Native transition</th>
                    <th>Priority</th>
                    <th>Protocol ACK</th>
                    <th>Local receipt UTC</th>
                  </tr>
                </thead>
                <tbody>
                  {receipt.events.map((event: any) => (
                    <tr key={event.sequence}>
                      <td>
                        {event.sequence}
                        {event.possible_duplicate ? " (possible repeat)" : ""}
                      </td>
                      <td>{event.event_object}</td>
                      <td>
                        {event.notify_type.name} / {event.event_type.name}
                      </td>
                      <td>
                        {event.from_state?.name ?? "absent"} /{" "}
                        {event.to_state.name}
                      </td>
                      <td>{event.priority}</td>
                      <td>{event.protocol_ack}</td>
                      <td>{event.received_at}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <details>
              <summary>Raw notifications and source-qualified evidence</summary>
              <pre>{JSON.stringify(receipt, null, 2)}</pre>
            </details>
          </section>
        )}
      </div>
    </section>
  );
}
