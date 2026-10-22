import { useEffect, useRef, useState } from "react";
import { api, download } from "./api";
import { AccumulatorPrescalePanel } from "./AccumulatorPrescalePanel";
type Props = {
  connected: boolean;
  interfaceIdentity: string;
  defaultAddress: string;
  defaultDevice: string;
  defaultObject: string;
  defaultRouter?: string;
  defaultDnet?: number | null;
};
const pointPattern =
  /^(analog-(input|output|value)|binary-(input|output|value)|multi-state-(input|output|value)|accumulator),\d+$/;
function show(row: any) {
  if (!row) return "Not read";
  if (row.status !== "ok")
    return `${row.status} · ${row.availability || "unknown"}${row.error ? `: ${row.error}` : ""}`;
  const value = row.value;
  return value && typeof value === "object" && "native_datatype" in value
    ? `${value.known === false ? "unknown native code · " : ""}${value.name || value.native_datatype} (${value.value})`
    : JSON.stringify(value);
}
export function PointStatusPanel({
  connected,
  interfaceIdentity,
  defaultAddress,
  defaultDevice,
  defaultObject,
  defaultRouter = "",
  defaultDnet: suppliedDnet,
}: Props) {
  const defaultDnet = suppliedDnet ?? null;
  const [address, setAddress] = useState(defaultAddress),
    [device, setDevice] = useState(defaultDevice),
    [router, setRouter] = useState(defaultRouter),
    [dnet, setDnet] = useState(defaultDnet == null ? "" : String(defaultDnet)),
    [objects, setObjects] = useState(
      pointPattern.test(defaultObject) ? defaultObject : "",
    );
  const [commandable, setCommandable] = useState(false),
    [enumMetadata, setEnumMetadata] = useState(false),
    [accumulatorMetadata, setAccumulatorMetadata] = useState(false),
    [stateTextLimit, setStateTextLimit] = useState("32"),
    [busy, setBusy] = useState(false),
    [report, setReport] = useState<any>(null),
    [profile, setProfile] = useState<any>(null),
    [error, setError] = useState("");
  const alive = useRef(true),
    selection = useRef(0),
    active = useRef<string | null>(null);
  const defaultsKey = JSON.stringify([
      connected,
      interfaceIdentity,
      defaultAddress,
      defaultDevice,
      defaultObject,
      defaultRouter,
      defaultDnet,
    ]),
    defaultsNow = useRef(defaultsKey);
  defaultsNow.current = defaultsKey;
  const formKey = JSON.stringify([
      address,
      device,
      router,
      dnet,
      objects,
      commandable,
      enumMetadata,
      accumulatorMetadata,
      stateTextLimit,
    ]),
    formNow = useRef(formKey);
  formNow.current = formKey;
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      selection.current++;
      if (active.current)
        void api("/bacnet/point-status/cancel", {
          operation_id: active.current,
        }).catch(() => {});
    };
  }, []);
  useEffect(() => {
    selection.current++;
    setAddress(defaultAddress);
    setDevice(defaultDevice);
    setRouter(defaultRouter);
    setDnet(defaultDnet == null ? "" : String(defaultDnet));
    setObjects(pointPattern.test(defaultObject) ? defaultObject : "");
    setReport(null);
    setError("");
    if (active.current)
      void api("/bacnet/point-status/cancel", {
        operation_id: active.current,
      }).catch(() => {});
  }, [
    connected,
    interfaceIdentity,
    defaultAddress,
    defaultDevice,
    defaultObject,
    defaultRouter,
    defaultDnet,
  ]);
  useEffect(() => {
    selection.current++;
    setReport(null);
    setError("");
  }, [formKey]);
  const current = (ticket: number, source: string, draft: string) =>
    alive.current &&
    selection.current === ticket &&
    defaultsNow.current === source &&
    formNow.current === draft;
  async function inspect() {
    const operation = crypto.randomUUID();
    active.current = operation;
    const ticket = ++selection.current,
      source = defaultsNow.current,
      draft = formNow.current;
    setBusy(true);
    setError("");
    setReport(null);
    try {
      const result = await api("/bacnet/point-status/read", {
        operation_id: operation,
        address: address.trim(),
        device: device.trim(),
        router: router.trim() || null,
        dnet: dnet.trim() ? Number(dnet) : null,
        object_ids: objects
          .split(/[;\n]+/)
          .map((v) => v.trim())
          .filter(Boolean),
        include_commandable: commandable,
        include_enum_metadata: enumMetadata,
        include_accumulator_metadata: accumulatorMetadata,
        state_text_limit: Number(stateTextLimit),
      });
      if (current(ticket, source, draft)) setReport(result);
    } catch (failure) {
      if (current(ticket, source, draft)) setError(String(failure));
    } finally {
      if (active.current === operation) active.current = null;
      if (alive.current) setBusy(false);
    }
  }
  async function cancel() {
    if (active.current)
      try {
        await api("/bacnet/point-status/cancel", {
          operation_id: active.current,
        });
      } catch (failure) {
        if (alive.current) setError(String(failure));
      }
  }
  async function refresh() {
    try {
      const result = await api("/bacnet/point-status/profile");
      if (alive.current) setProfile(result);
    } catch (failure) {
      if (alive.current) setError(String(failure));
    }
  }
  async function reopen(id: string) {
    const ticket = ++selection.current,
      source = defaultsNow.current,
      draft = formNow.current;
    setReport(null);
    try {
      const result = await api("/bacnet/point-status/reports/" + id);
      if (current(ticket, source, draft)) setReport(result);
    } catch (failure) {
      if (current(ticket, source, draft)) setError(String(failure));
    }
  }
  async function exportReport() {
    if (!report) return;
    const ticket = selection.current,
      source = defaultsNow.current,
      draft = formNow.current,
      id = report.id;
    try {
      await download(
        "/bacnet/point-status/export",
        { id },
        `point-status-${id}.json`,
        () => current(ticket, source, draft),
      );
    } catch (failure) {
      if (current(ticket, source, draft)) setError(String(failure));
    }
  }
  return (
    <section className="card" aria-label="Native point status inspection">
      <h2>Native point status</h2>
      <p>
        Inspect selected points on one exact Device. Raw native value, units,
        reliability, status flags and service state stay separate. A finite
        value or no-fault indication does not prove physical health. No object
        discovery, polling, scaling or writes.
      </p>
      <p>
        Plain direct IPv4 or explicit IPv4 router and DNET:MAC; no BBMD/direct
        serial in this profile. Choose up to 16 analog/binary/multistate
        input/output/value or Accumulator objects from existing
        point/object-list tools.
      </p>
      <div className="form-grid">
        <label>
          Point-status source address
          <input
            aria-label="Point-status source address"
            value={address}
            disabled={busy}
            onChange={(e) => setAddress(e.target.value)}
          />
        </label>
        <label>
          Point-status Device identifier
          <input
            aria-label="Point-status Device identifier"
            value={device}
            disabled={busy}
            onChange={(e) => setDevice(e.target.value)}
            placeholder="device,1234"
          />
        </label>
        <label>
          Point-status router endpoint
          <input
            aria-label="Point-status router endpoint"
            value={router}
            disabled={busy}
            onChange={(e) => setRouter(e.target.value)}
          />
        </label>
        <label>
          Point-status DNET
          <input
            aria-label="Point-status DNET"
            type="number"
            min={1}
            max={65534}
            value={dnet}
            disabled={busy}
            onChange={(e) => setDnet(e.target.value)}
          />
        </label>
        <label className="full">
          Selected native points
          <textarea
            aria-label="Selected native points"
            value={objects}
            disabled={busy}
            onChange={(e) => setObjects(e.target.value)}
            placeholder="analog-input,1; analog-output,2"
          />
        </label>
        <label>
          <input
            type="checkbox"
            checked={commandable}
            disabled={busy}
            onChange={(e) => setCommandable(e.target.checked)}
          />
          Read optional priority slots and relinquish defaults
        </label>
        <label>
          <input
            type="checkbox"
            checked={enumMetadata}
            disabled={busy}
            onChange={(e) => setEnumMetadata(e.target.checked)}
          />
          Read native binary and multistate domain metadata
        </label>
        <label>
          <input
            type="checkbox"
            checked={accumulatorMetadata}
            disabled={busy}
            onChange={(e) => setAccumulatorMetadata(e.target.checked)}
          />
          Read native Accumulator prescale and metering metadata
        </label>
        {enumMetadata && (
          <label>
            Maximum indexed state labels per point
            <input
              type="number"
              min={1}
              max={256}
              value={stateTextLimit}
              disabled={busy}
              onChange={(e) => setStateTextLimit(e.target.value)}
            />
          </label>
        )}
      </div>
      <div className="toolbar">
        <button disabled={!connected || busy} onClick={() => void inspect()}>
          Inspect native point status
        </button>
        <button disabled={!busy} onClick={() => void cancel()}>
          Cancel point inspection
        </button>
        <button onClick={() => void refresh()}>
          Refresh retained point reports
        </button>
        <button disabled={!report || busy} onClick={() => void exportReport()}>
          Export exact point evidence
        </button>
      </div>
      {busy && <p role="status">Reading finite point evidence…</p>}
      {error && <p role="alert">{error}</p>}
      {profile && (
        <details>
          <summary>Retained point reports and limits</summary>
          <p>
            Session memory only; export before restart or eviction. Reopening
            retained evidence does not read a controller.
          </p>
          <pre>{JSON.stringify(profile.limits, null, 2)}</pre>
          {profile.reports.map((row: any) => (
            <p key={row.id}>
              <button disabled={busy} onClick={() => void reopen(row.id)}>
                Open point report {row.id.slice(0, 8)}
              </button>{" "}
              {row.target.device} at {row.target.address} · {row.status} ·{" "}
              {row.finished_at}
            </p>
          ))}
        </details>
      )}
      {report && (
        <div aria-label="Native point evidence report">
          <p>
            <strong>{report.status}</strong> · Device identity{" "}
            {report.identity_verified ? "verified" : "unverified"} ·{" "}
            {report.target.device} at {report.target.address}
            {report.target.router
              ? ` via ${report.target.router} / DNET ${report.target.dnet}`
              : ""}
          </p>
          <p>
            {report.health_assessment} {report.consistency}
          </p>
          <p>
            Local receipt interval {report.started_at} through{" "}
            {report.finished_at}; source clock unresolved. Native units are read
            from the controller, separate from operator-entered trend metadata.
            Browser JSON previews normalize numeric spelling; exact export
            preserves it.
          </p>
          {!!report.errors.length && (
            <pre>{JSON.stringify(report.errors, null, 2)}</pre>
          )}
          <table>
            <thead>
              <tr>
                <th>Point / native name</th>
                <th>Present value / native type</th>
                <th>Native units</th>
                <th>Status flags</th>
                <th>Reliability</th>
                <th>Out of service</th>
                <th>Read completeness</th>
              </tr>
            </thead>
            <tbody>
              {report.objects.map((obj: any) => (
                <tr key={obj.object}>
                  <td>
                    {obj.object}
                    <br />
                    {show(obj.properties["object-name"])}
                  </td>
                  <td>
                    {show(obj.properties["present-value"])}
                    <br />
                    {obj.properties["present-value"]?.datatype}
                  </td>
                  <td>{show(obj.properties.units)}</td>
                  <td>{show(obj.properties["status-flags"])}</td>
                  <td>{show(obj.properties.reliability)}</td>
                  <td>{show(obj.properties["out-of-service"])}</td>
                  <td>
                    {obj.identity_verified
                      ? "Identity verified"
                      : "Identity unverified"}
                    <br />
                    {obj.complete ? "Selected reads complete" : "Incomplete"}
                    {obj.error && <p>{obj.error}</p>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p>
            Status flag order: in-alarm, fault, overridden, out-of-service.
            Separate sequential service indications may disagree; no substitute
            physical diagnosis is inferred. Optional native errors or unknown
            fields do not imply bad health.
          </p>
          {report.objects.map((obj: any) => (
            <div key={obj.object}>
              {obj.accumulator_metering && (
                <section aria-label={`Native metering ${obj.object}`}>
                  <h3>Accumulator metering · {obj.object}</h3>
                  <p>
                    {obj.accumulator_metering.status} ·{" "}
                    {obj.accumulator_metering.meaning}
                  </p>
                  <pre>
                    {JSON.stringify(
                      Object.fromEntries(
                        Object.entries(obj.properties).filter(([key]) =>
                          [
                            "prescale",
                            "scale",
                            "max-pres-value",
                            "pulse-rate",
                            "limit-monitoring-interval",
                            "value-change-time",
                            "value-before-change",
                          ].includes(key),
                        ),
                      ),
                      null,
                      2,
                    )}
                  </pre>
                </section>
              )}
              {obj.enum_domain && (
                <section aria-label={`Native state domain ${obj.object}`}>
                  <h3>Native state domain · {obj.object}</h3>
                  <p>
                    {obj.enum_domain.status} · {obj.enum_domain.source} ·
                    Present value validation:{" "}
                    {obj.enum_domain.value_validation?.status ||
                      "not applicable"}
                    {obj.enum_domain.value_validation?.code != null
                      ? ` (code ${obj.enum_domain.value_validation.code})`
                      : ""}
                  </p>
                  <p>
                    Native codes and labels are sequential observations,
                    separate from JCI Enum Set IDs and portable/operator enum
                    definitions. Polarity does not flip the reported code or
                    labels. No mapping or controller write is inferred.
                  </p>
                  <p>
                    Number of states:{" "}
                    {obj.enum_domain.number_of_states ?? "not established"};
                    state-text count:{" "}
                    {obj.enum_domain.observed_state_text_count ??
                      "not applicable"}
                    ; labels{" "}
                    {obj.enum_domain.labels_complete
                      ? "complete"
                      : "incomplete"}
                    .
                    {obj.properties.polarity &&
                      ` Native polarity: ${show(obj.properties.polarity)}.`}
                  </p>
                  {!!obj.enum_domain.states?.length && (
                    <table>
                      <thead>
                        <tr>
                          <th>Native code</th>
                          <th>Label evidence</th>
                          <th>Property / index</th>
                        </tr>
                      </thead>
                      <tbody>
                        {obj.enum_domain.states.map((state: any) => (
                          <tr key={state.code}>
                            <td>{state.code}</td>
                            <td>
                              {state.label == null
                                ? "Unknown label"
                                : JSON.stringify(state.label)}{" "}
                              · {state.label_status}
                            </td>
                            <td>
                              {state.property}
                              {state.array_index == null
                                ? ""
                                : ` [${state.array_index}]`}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                  {!!obj.enum_domain.findings?.length && (
                    <pre>
                      {JSON.stringify(obj.enum_domain.findings, null, 2)}
                    </pre>
                  )}
                </section>
              )}
              <details>
                <summary>Raw point evidence {obj.object}</summary>
                <pre>{JSON.stringify(obj, null, 2)}</pre>
              </details>
            </div>
          ))}
          <details>
            <summary>Complete point report and transport provenance</summary>
            <pre className="result">{JSON.stringify(report, null, 2)}</pre>
          </details>
        </div>
      )}
      <AccumulatorPrescalePanel nativeReport={report} />
    </section>
  );
}
