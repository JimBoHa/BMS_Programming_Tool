import { useEffect, useRef, useState } from "react";
import { api } from "./api";

type Target = {
  address: string;
  device: string;
  router: string | null;
  dnet: number | null;
};
type Observation = {
  name: string;
  point: string;
  value: number;
  unit: string;
  good: boolean;
  time: string;
};

export function NetworkSensorReading({
  objects,
  target,
  ready,
  config,
}: {
  objects: string[];
  target: Target;
  ready: boolean;
  config?: Record<string, any>;
}) {
  const [selected, setSelected] = useState(objects[0]);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [result, setResult] = useState<Observation | null>(null);
  const request = useRef(0),
    pending = useRef(false);
  useEffect(
    () => () => {
      request.current++;
    },
    [],
  );

  async function read() {
    if (!ready || pending.current || !objects.includes(selected)) return;
    const id = ++request.current;
    pending.current = true;
    setBusy(true);
    setResult(null);
    setError("");
    try {
      const report = await api("/bacnet/controller/properties", {
        ...target,
        object_ids: [selected],
        properties: ["object-name", "913", "941"],
        read_linked_zone_temperature: true,
      });
      if (request.current !== id) return;
      const row = report.objects?.[0],
        link = report.linked_zone_temperature;
      if (
        !report.identity_verified ||
        !row?.identity_verified ||
        row.object !== selected ||
        !Object.entries(target).every(
          ([k, v]) => (report.target?.[k] ?? null) === v,
        ) ||
        (config &&
          !Object.entries(config).every(
            ([k, v]) =>
              JSON.stringify(report.connector_config?.[k]) ===
              JSON.stringify(v),
          ))
      )
        throw new Error(
          "The selected controller or interface could not be verified.",
        );
      if (link?.status !== "observed" || link.sensor !== selected)
        throw new Error(
          link?.reason ||
            report.errors?.join(" ") ||
            "The sensor’s linked temperature input could not be read.",
        );
      const fields = link.properties;
      if (
        !Number.isFinite(fields?.["present-value"]?.value) ||
        !fields.units?.value?.name ||
        !["good", "flagged"].includes(link.quality)
      )
        throw new Error("The linked temperature or its quality is incomplete.");
      setResult({
        name: row.properties["object-name"]?.value || selected,
        point: link.object,
        value: fields["present-value"].value,
        unit: fields.units.value.name,
        good: link.quality === "good",
        time: report.finished_at,
      });
    } catch (e) {
      if (request.current === id) setError(String(e));
    } finally {
      if (request.current === id) {
        pending.current = false;
        setBusy(false);
      }
    }
  }
  return (
    <details>
      <summary>Room sensor temperature</summary>
      <label>
        Room sensor
        <select
          aria-label="Room sensor"
          value={selected}
          disabled={busy}
          onChange={(e) => {
            setSelected(e.target.value);
            setResult(null);
            setError("");
          }}
        >
          {objects.map((obj) => (
            <option key={obj} value={obj}>
              {obj}
            </option>
          ))}
        </select>
      </label>
      <button
        type="button"
        onClick={() => void read()}
        disabled={!ready || busy}
      >
        {busy ? "Reading room temperature…" : "Read linked room temperature"}
      </button>
      {!ready && (
        <p role="status">
          Connect to this survey’s controller to read the sensor.
        </p>
      )}
      {error && <p role="alert">{error}</p>}
      {result && (
        <p role="status">
          {result.name} · {result.point} ·{" "}
          {result.value.toLocaleString(undefined, { maximumFractionDigits: 2 })}{" "}
          {(
            {
              "degrees-fahrenheit": "°F",
              "degrees-celsius": "°C",
              kelvin: "K",
              "degrees-kelvin": "K",
            } as Record<string, string>
          )[result.unit] || result.unit}
          . {result.good ? "Quality good." : "Check sensor or input quality."}{" "}
          Read {new Date(result.time).toLocaleTimeString()}.
        </p>
      )}
    </details>
  );
}
