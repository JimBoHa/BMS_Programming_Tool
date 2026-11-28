import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { equal } from "./modelTransportContract";
import { controllerKey, type ControllerTarget } from "./workflow";

const counters = [
  ["2867", "Token frames sent"],
  ["2868", "Token frames received"],
  ["2869", "Polls for a manager sent"],
  ["2872", "Replies to polls received"],
  ["2884", "Packets timed out"],
  ["1146", "Framing errors"],
  ["2887", "Header CRC errors"],
  ["2888", "Data CRC errors"],
  ["2892", "Lost tokens"],
] as const;

export function networkPortId(input: string): string | null {
  const match = /^(?:network-port|56),(\d+)$/.exec(input.trim());
  const instance = match ? Number(match[1]) : NaN;
  return Number.isInteger(instance) && instance <= 4194302
    ? `network-port,${instance}`
    : null;
}

type Field = {
  status: string;
  value?: unknown;
  error?: string;
  datatype?: string;
};
type Fields = Record<string, Field>;
type Sample = {
  time: string;
  name: string;
  standard: Fields;
  vendor: number | null;
  counts: Fields | null;
};

function scalar(field?: Field): unknown {
  if (field?.status !== "ok") return null;
  const v = field.value;
  return v && typeof v === "object" && "native_datatype" in v && "value" in v
    ? v.value
    : v;
}
function display(field?: Field) {
  if (!field || field.status !== "ok")
    return field?.error || field?.status || "Unavailable";
  const value = field.value;
  if (
    value &&
    typeof value === "object" &&
    "name" in value &&
    "known" in value &&
    value.known === true
  )
    return String(value.name);
  const simple = scalar(field);
  return Array.isArray(simple)
    ? simple.join(", ")
    : String(simple ?? "Unavailable");
}
function count(fields: Fields | null, key: string): number | null {
  const field = fields?.[key];
  const n = scalar(field);
  return field?.datatype === "Unsigned" &&
    typeof n === "number" &&
    Number.isSafeInteger(n) &&
    n >= 0
    ? n
    : null;
}
function difference(previous: Fields | null, current: Fields, key: string) {
  const old = count(previous, key),
    next = count(current, key);
  if (old === null || next === null) return "—";
  return next >= old ? String(next - old) : "Counter decreased";
}

export function NetworkPortDiagnostics({
  target,
  port,
  config,
}: {
  target: ControllerTarget;
  port: string;
  config: Record<string, unknown>;
}) {
  const [last, setLast] = useState<Sample | null>(null);
  const [previous, setPrevious] = useState<Sample | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const mounted = useRef(true);
  const pending = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  async function read() {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setError("");
    const source = {
      address: target.address,
      device: target.device,
      router: target.router || null,
      dnet: target.dnet ?? null,
    };
    async function properties(object: string, names: string[]) {
      const r = await api("/bacnet/controller/properties", {
        ...source,
        object_ids: [object],
        properties: names,
      });
      if (!mounted.current) throw new Error("Selection changed.");
      const row = r.objects?.[0];
      if (
        !r.read_only ||
        !r.identity_verified ||
        !r.target ||
        controllerKey(r.target) !== controllerKey(source) ||
        !equal(r.connector_config, config) ||
        r.objects?.length !== 1 ||
        !row?.identity_verified ||
        row.object !== object ||
        scalar(row.properties?.["object-identifier"]) !== object ||
        !Number.isFinite(Date.parse(r.finished_at))
      )
        throw new Error(
          "The source of this reading could not be verified. Reopen the controller and try again.",
        );
      return {
        fields: row.properties as Fields,
        time: r.finished_at as string,
      };
    }
    try {
      const device = await properties(source.device, ["vendor-identifier"]);
      const vendor = scalar(device.fields["vendor-identifier"]);
      const standard = await properties(port, [
        "object-name",
        "network-type",
        "network-number",
        "link-speed",
        "reliability",
        "out-of-service",
      ]);
      const name = scalar(standard.fields["object-name"]);
      if (typeof name !== "string" || !name)
        throw new Error("The port did not return its name.");
      let counts: Fields | null = null,
        time = standard.time;
      if (vendor === 5 && scalar(standard.fields["network-type"]) === 2) {
        const more = await properties(port, [
          "object-name",
          "network-number",
          "network-type",
          ...counters.map(([k]) => k),
        ]);
        if (
          scalar(more.fields["object-name"]) !== name ||
          scalar(more.fields["network-type"]) !== 2 ||
          scalar(standard.fields["network-number"]) === null ||
          scalar(more.fields["network-number"]) !==
            scalar(standard.fields["network-number"])
        )
          throw new Error(
            "The port identity or network number changed during the read.",
          );
        counts = more.fields;
        time = more.time;
      }
      const current = {
        name,
        standard: standard.fields,
        counts,
        time,
        vendor: typeof vendor === "number" ? vendor : null,
      };
      const samePort =
        last &&
        last.name === name &&
        last.vendor === current.vendor &&
        scalar(last.standard["network-type"]) ===
          scalar(current.standard["network-type"]) &&
        scalar(last.standard["network-number"]) ===
          scalar(current.standard["network-number"]) &&
        Date.parse(last.time) < Date.parse(time);
      setPrevious(samePort ? last : null);
      setLast(current);
    } catch (failure) {
      if (mounted.current) setError(String(failure));
    } finally {
      pending.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  return (
    <div className="full" role="region" aria-label="Network port diagnostics">
      <button type="button" disabled={busy} onClick={read}>
        {busy
          ? "Reading port diagnostics…"
          : last
            ? "Read port diagnostics again"
            : "Read port diagnostics"}
      </button>
      {error && (
        <p className="inline-error" role="alert">
          {error}
        </p>
      )}
      {last && (
        <>
          <p role="status">
            <b>{last.name}</b> · {port} · Network{" "}
            {display(last.standard["network-number"])} ·{" "}
            {display(last.standard["network-type"])} · Link speed{" "}
            {display(last.standard["link-speed"])}
            {typeof scalar(last.standard["link-speed"]) === "number" &&
              " bit/s"}
          </p>
          <p>
            Last verified reading {new Date(last.time).toLocaleString()} ·
            Reliability {display(last.standard.reliability)} · Out of service{" "}
            {display(last.standard["out-of-service"])}
          </p>
          {last.counts ? (
            <>
              <p>
                {previous
                  ? `Changes since ${new Date(previous.time).toLocaleTimeString()}.`
                  : "Read the port again to see how the counters change."}
              </p>
              <div style={{ overflowX: "auto" }}>
                <table>
                  <thead>
                    <tr>
                      <th>MS/TP counter</th>
                      <th>Reading</th>
                      <th>Change</th>
                    </tr>
                  </thead>
                  <tbody>
                    {counters.map(([k, label]) => (
                      <tr key={k}>
                        <th scope="row">{label}</th>
                        <td>
                          {count(last.counts, k) ??
                            (last.counts?.[k]?.status === "ok"
                              ? "Unexpected counter type"
                              : display(last.counts?.[k]))}
                        </td>
                        <td>
                          {difference(
                            previous?.counts ?? null,
                            last.counts!,
                            k,
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <p>
              Vendor-specific counters are available for verified Johnson
              Controls MS/TP ports.
            </p>
          )}
        </>
      )}
    </div>
  );
}
