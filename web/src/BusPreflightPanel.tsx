import { useEffect, useRef, useState } from "react";
import { api, download } from "./api";
import "./bus-preflight.css";

type Data = Record<string, any>;
const key = () => crypto.randomUUID();
const blankBus = () => ({
  id: key(),
  name: "Physical bus",
  profile: "unknown",
  kind: "unknown",
  segments: ["segment-1"],
  inventory_complete: false,
  nce_integral: "unknown",
  zfr1810_coordinators: "unknown",
  notes: "",
});
const blankDevice = (bus: Data | undefined) => ({
  id: key(),
  bus_id: bus?.id || "",
  label: "Device connection",
  model: "",
  role: "unknown",
  generation: null,
  mac: null,
  segment: bus?.segments[0] || null,
  mode: "wired",
  switch128: "unknown",
  eol: "unknown",
  notes: "",
});
const blankLink = () => ({
  id: key(),
  a: "",
  b: "",
  kind: "unknown",
  length_m: null,
  straight_through: null,
  notes: "",
});
const show = (value: any) => (value === null ? "Unknown" : String(value));
const roles = [
  "fc-host",
  "sa-host",
  "field-controller",
  "iom",
  "fit",
  "converter",
  "display",
  "network-sensor",
  "handheld-balancer",
  "subordinate",
  "nce-integral",
  "zfr1810",
  "repeater-port",
  "unknown",
];
function Select({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: (string | [string, string])[];
  onChange: (value: string) => void;
}) {
  return (
    <label>
      {label}
      <select
        aria-label={label}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        {value &&
          !options.some(
            (row) => (Array.isArray(row) ? row[0] : row) === value,
          ) && <option value={value}>Unreviewed: {value}</option>}
        {options.map((row) => {
          const [value, text] = Array.isArray(row) ? row : [row, row];
          return (
            <option key={value} value={value}>
              {text}
            </option>
          );
        })}
      </select>
    </label>
  );
}
function Text({
  label,
  value,
  onChange,
  max = 160,
  disabled = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  max?: number;
  disabled?: boolean;
}) {
  return (
    <label>
      {label}
      <input
        aria-label={label}
        disabled={disabled}
        maxLength={max}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}
export function BusPreflightPanel() {
  const [catalog, setCatalog] = useState<Data | null>(null),
    [draft, setDraft] = useState<Data | null>(null);
  const [bus, setBus] = useState<Data>(blankBus),
    [device, setDevice] = useState<Data>(() => blankDevice(undefined)),
    [link, setLink] = useState<Data>(blankLink);
  const [busEditing, setBusEditing] = useState(false),
    [deviceEditing, setDeviceEditing] = useState(false),
    [linkEditing, setLinkEditing] = useState(false);
  const [pending, setPending] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [message, setMessage] = useState("");
  const [report, setReport] = useState<Data | null>(null),
    [saved, setSaved] = useState("");
  const details = useRef<HTMLDetailsElement>(null),
    importer = useRef<HTMLInputElement>(null);
  const pendingKinds = useRef(new Set<string>());
  const mounted = useRef(false),
    generation = useRef(0),
    requestId = useRef(0),
    template = useRef<Data | null>(null);
  const dirty = !!draft && (pending || JSON.stringify(draft) !== saved);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      requestId.current++;
    };
  }, []);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  function invalidate() {
    generation.current++;
    setReport(null);
    setError("");
    setMessage("");
  }
  function current(request: number, epoch: number) {
    return (
      mounted.current &&
      !!details.current?.open &&
      request === requestId.current &&
      epoch === generation.current
    );
  }
  async function run(
    action: (request: number, epoch: number) => Promise<void>,
  ) {
    const request = ++requestId.current,
      epoch = generation.current;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await action(request, epoch);
    } catch (e) {
      if (current(request, epoch))
        setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (mounted.current && request === requestId.current) setBusy(false);
    }
  }
  async function initialize() {
    if (catalog) return;
    await run(async (request, epoch) => {
      const data = await api("/bus-preflight/catalog");
      if (!current(request, epoch)) return;
      setCatalog(data.catalog);
      template.current = data.template;
      setDraft(data.template);
      setSaved(JSON.stringify(data.template));
    });
  }
  function editPlan(changes: Data) {
    if (!draft) return;
    invalidate();
    setDraft({ ...draft, ...changes });
  }
  function editForm(kind: "bus" | "device" | "link", changes: Data) {
    invalidate();
    setPending(true);
    pendingKinds.current.add(kind);
    if (kind === "bus") setBus({ ...bus, ...changes });
    else if (kind === "device") setDevice({ ...device, ...changes });
    else setLink({ ...link, ...changes });
  }
  function clearEditors(firstBus?: Data) {
    pendingKinds.current.clear();
    setBus(blankBus());
    setDevice(blankDevice(firstBus));
    setLink(blankLink());
    setBusEditing(false);
    setDeviceEditing(false);
    setLinkEditing(false);
    setPending(false);
  }
  async function apply(kind: "bus" | "device" | "link") {
    if (!draft) return;
    const [name, row, editing] =
      kind === "bus"
        ? ["buses", bus, busEditing]
        : kind === "device"
          ? ["devices", device, deviceEditing]
          : ["links", link, linkEditing];
    const proposed = {
      ...draft,
      [name]: editing
        ? draft[name].map((item: Data) => (item.id === row.id ? row : item))
        : [...draft[name], row],
    };
    await run(async (request, epoch) => {
      const result = await api("/bus-preflight/validate", { plan: proposed });
      if (!current(request, epoch)) return;
      invalidate();
      setDraft(result.plan);
      pendingKinds.current.delete(kind);
      setPending(pendingKinds.current.size > 0);
      if (kind === "bus") {
        setBus(blankBus());
        setBusEditing(false);
        if (!pendingKinds.current.has("device") && !deviceEditing)
          setDevice(blankDevice(result.plan.buses[0]));
      }
      if (kind === "device") {
        setDevice(blankDevice(result.plan.buses[0]));
        setDeviceEditing(false);
      }
      if (kind === "link") {
        setLink(blankLink());
        setLinkEditing(false);
      }
      setMessage(
        "Applied local declaration. Run a fresh review; no field operation occurred.",
      );
    });
  }
  function selectEdit(kind: "bus" | "device" | "link", row: Data) {
    if (
      pending &&
      !window.confirm("Discard unapplied bus/device/link editor changes?")
    )
      return;
    invalidate();
    clearEditors(draft?.buses[0]);
    if (kind === "bus") {
      setBus(structuredClone(row));
      setBusEditing(true);
    } else if (kind === "device") {
      setDevice(structuredClone(row));
      setDeviceEditing(true);
    } else {
      setLink(structuredClone(row));
      setLinkEditing(true);
    }
  }
  function remove(kind: "buses" | "devices" | "links", row: Data) {
    if (!draft) return;
    if (pending) {
      setError(
        "Apply or clear unapplied editor changes before removing a declaration.",
      );
      return;
    }
    if (
      kind === "buses" &&
      draft.devices.some((d: Data) => d.bus_id === row.id)
    ) {
      setError(
        "Remove this bus's device connections and their links before deleting its declaration.",
      );
      return;
    }
    if (
      kind === "devices" &&
      draft.links.some((l: Data) => l.a === row.id || l.b === row.id)
    ) {
      setError(
        "Remove this device's declared cable links before deleting its connection.",
      );
      return;
    }
    editPlan({
      [kind]: draft[kind].filter((item: Data) => item.id !== row.id),
    });
    clearEditors(draft.buses[0]);
  }
  function reset() {
    if (
      !template.current ||
      (dirty &&
        !window.confirm("Discard this unsaved bus plan and unapplied edits?"))
    )
      return;
    invalidate();
    requestId.current++;
    setBusy(false);
    setDraft(structuredClone(template.current));
    setSaved(JSON.stringify(template.current));
    clearEditors();
  }
  async function operate(kind: "review" | "plan" | "report") {
    if (!draft || pending) return;
    const snapshot = structuredClone(draft);
    await run(async (request, epoch) => {
      if (kind === "review") {
        const value = await api("/bus-preflight/review", { plan: snapshot });
        if (current(request, epoch)) setReport(value);
        return;
      }
      const requested = await download(
        kind === "plan"
          ? "/bus-preflight/export-plan"
          : "/bus-preflight/export-review",
        { plan: snapshot },
        kind === "plan" ? "jci-bus-plan.json" : "jci-bus-review.json",
        () => current(request, epoch),
      );
      if (!requested || !current(request, epoch)) return;
      if (kind === "plan") setSaved(JSON.stringify(snapshot));
      setMessage(
        "Source-checked server JSON download requested. This does not inspect or change physical wiring.",
      );
    });
  }
  async function importPlan(file?: File) {
    if (
      !file ||
      !catalog ||
      (dirty &&
        !window.confirm(
          "Replace the current bus plan and unapplied edits with this file?",
        ))
    )
      return;
    invalidate();
    await run(async (request, epoch) => {
      if (file.size > 2 * 1024 * 1024)
        throw new Error("Bus plan exceeds 2 MiB.");
      const value = await api("/bus-preflight/validate", {
        plan: JSON.parse(await file.text()),
      });
      if (!current(request, epoch)) return;
      setDraft(value.plan);
      setSaved(JSON.stringify(value.plan));
      clearEditors(value.plan.buses[0]);
      setMessage(
        "Imported exact source-checked declarations. Run a fresh review.",
      );
    });
  }
  const deviceBus = draft?.buses.find((b: Data) => b.id === device.bus_id);
  const deviceName = (id: string) =>
    draft?.devices.find((d: Data) => d.id === id)?.label || id;
  return (
    <details
      className="bus-preflight card"
      ref={details}
      onToggle={(event) => {
        if (event.target !== event.currentTarget) return;
        invalidate();
        if (event.currentTarget.open && !catalog) void initialize();
      }}
    >
      <summary>JCI bus address and topology plan</summary>
      <section aria-label="JCI bus preflight">
        <h2>MS/TP and SA bus declarations</h2>
        <p>
          Offline planned connections only. Each physical bus has its own MAC
          address scope; the same controller's FC and SA interfaces are separate
          device connections. Choose the exact reviewed manual/profile. Numbers,
          models, cable lengths and EOL settings are operator declarations.
        </p>
        {!catalog || !draft ? (
          <button disabled={busy} onClick={() => void initialize()}>
            {busy ? "Loading reviewed profiles…" : "Load bus planning profiles"}
          </button>
        ) : (
          <>
            <div className="bus-plan-actions">
              <button onClick={reset}>New empty bus plan</button>
              <button onClick={() => importer.current?.click()}>
                Import bus plan JSON
              </button>
              <button
                disabled={busy || pending}
                onClick={() => void operate("plan")}
              >
                Export bus plan JSON
              </button>
              <button
                disabled={busy || pending}
                onClick={() => void operate("review")}
              >
                Review bus plan
              </button>
              <button
                disabled={busy || pending || !report}
                onClick={() => void operate("report")}
              >
                Export bus review JSON
              </button>
            </div>
            <input
              hidden
              ref={importer}
              type="file"
              aria-label="Bus plan JSON"
              accept=".json,application/json"
              onChange={(event) => {
                void importPlan(event.target.files?.[0]);
                event.target.value = "";
              }}
            />
            <Text
              label="Bus plan name"
              value={draft.name}
              onChange={(name) => editPlan({ name })}
            />
            <label>
              Bus plan notes
              <textarea
                aria-label="Bus plan notes"
                maxLength={4000}
                value={draft.notes}
                onChange={(event) => editPlan({ notes: event.target.value })}
              />
            </label>
            <fieldset>
              <legend>
                {busEditing ? "Edit physical bus" : "Add physical bus"}
              </legend>
              <div className="bus-plan-grid">
                <Text
                  label="Physical bus name"
                  value={bus.name}
                  onChange={(name) => editForm("bus", { name })}
                />
                <Text
                  label="Physical bus key"
                  disabled={busEditing}
                  value={bus.id}
                  max={80}
                  onChange={(id) => editForm("bus", { id })}
                />
                <Select
                  label="Bus manual profile"
                  value={bus.profile}
                  options={[
                    ["unknown", "Unknown / unreviewed"],
                    ["metasys-r15", "Metasys Release 15 (2026-09-29)"],
                    ["fx-2024", "FX bulletin (2024-12-11)"],
                  ]}
                  onChange={(profile) => editForm("bus", { profile })}
                />
                <Select
                  label="Physical bus type"
                  value={bus.kind}
                  options={[
                    ["unknown", "Unknown"],
                    ["fc", "FC bus"],
                    ["sa", "SA bus"],
                  ]}
                  onChange={(kind) => editForm("bus", { kind })}
                />
                <Text
                  label="Segment keys (comma separated)"
                  value={bus.segments.join(",")}
                  max={1295}
                  onChange={(value) =>
                    editForm("bus", { segments: value.split(",") })
                  }
                />
                <Select
                  label="NCE integral controller context"
                  value={bus.nce_integral}
                  options={["unknown", "absent", "present"]}
                  onChange={(nce_integral) => editForm("bus", { nce_integral })}
                />
                <Select
                  label="ZFR1810 coordinator context"
                  value={bus.zfr1810_coordinators}
                  options={["unknown", "absent", "present"]}
                  onChange={(zfr1810_coordinators) =>
                    editForm("bus", { zfr1810_coordinators })
                  }
                />
              </div>
              <label className="bus-plan-check">
                <input
                  type="checkbox"
                  checked={bus.inventory_complete}
                  onChange={(event) =>
                    editForm("bus", {
                      inventory_complete: event.target.checked,
                    })
                  }
                />
                All intended devices and cables for this bus are declared
              </label>
              <label>
                Physical bus evidence notes
                <textarea
                  aria-label="Physical bus evidence notes"
                  maxLength={2000}
                  value={bus.notes}
                  onChange={(event) =>
                    editForm("bus", { notes: event.target.value })
                  }
                />
              </label>
              <p>
                Keys are exact case-sensitive identifiers, not BACnet network
                numbers. SA has one segment and one host. NCE/address 4 and
                ZFR1810/address 120–127 contexts apply only to the reviewed
                Metasys FC profile. Unknown context remains unresolved where
                relevant.
              </p>
              <button disabled={busy} onClick={() => void apply("bus")}>
                {busEditing ? "Apply bus edits" : "Add physical bus to plan"}
              </button>
            </fieldset>
            <h3>Physical buses ({draft.buses.length}/32)</h3>
            <div className="bus-plan-table">
              <table>
                <thead>
                  <tr>
                    <th>Bus / key</th>
                    <th>Profile / type</th>
                    <th>Segments / coverage</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {draft.buses.map((row: Data) => (
                    <tr key={row.id}>
                      <td>
                        {row.name}
                        <small>{row.id}</small>
                      </td>
                      <td>
                        {row.profile}
                        <small>{row.kind}</small>
                      </td>
                      <td>
                        {row.segments.join(", ")}
                        <small>
                          {row.inventory_complete
                            ? "Operator-declared inventory included"
                            : "Incomplete inventory"}
                        </small>
                      </td>
                      <td>
                        <button
                          aria-label={`Edit bus ${row.name}`}
                          onClick={() => selectEdit("bus", row)}
                        >
                          Edit
                        </button>
                        <button
                          aria-label={`Remove bus ${row.name}`}
                          onClick={() => remove("buses", row)}
                        >
                          Remove
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <fieldset>
              <legend>
                {deviceEditing
                  ? "Edit device connection"
                  : "Add device connection"}
              </legend>
              <div className="bus-plan-grid">
                <Text
                  label="Device connection label"
                  value={device.label}
                  onChange={(label) => editForm("device", { label })}
                />
                <Select
                  label="Device physical bus"
                  value={device.bus_id}
                  options={[
                    ["", "Select physical bus"],
                    ...draft.buses.map(
                      (b: Data) => [b.id, b.name] as [string, string],
                    ),
                  ]}
                  onChange={(bus_id) =>
                    editForm("device", {
                      bus_id,
                      segment:
                        draft.buses.find((b: Data) => b.id === bus_id)
                          ?.segments[0] || null,
                    })
                  }
                />
                <label>
                  Exact device model
                  <input
                    aria-label="Exact device model"
                    list="bus-reviewed-models"
                    maxLength={120}
                    value={device.model}
                    onChange={(event) =>
                      editForm("device", { model: event.target.value })
                    }
                  />
                  <datalist id="bus-reviewed-models">
                    {Object.keys(catalog.models).map((model) => (
                      <option value={model} key={model} />
                    ))}
                  </datalist>
                </label>
                <Select
                  label="Declared device generation"
                  value={device.generation || ""}
                  options={[
                    ["", "Unknown"],
                    ["legacy-dip128", "Legacy controller DIP128 mode"],
                    ["refreshed-2025-12-08", "NS8000 refreshed 2025-12-08"],
                  ]}
                  onChange={(generation) =>
                    editForm("device", { generation: generation || null })
                  }
                />
                <Select
                  label="Device connection role"
                  value={device.role}
                  options={roles}
                  onChange={(role) => editForm("device", { role })}
                />
                <label>
                  Device MAC (blank = unknown)
                  <input
                    aria-label="Device MAC (blank = unknown)"
                    type="number"
                    min={0}
                    max={255}
                    step={1}
                    value={device.mac ?? ""}
                    onChange={(event) =>
                      editForm("device", {
                        mac:
                          event.target.value === ""
                            ? null
                            : Number(event.target.value),
                      })
                    }
                  />
                </label>
                <Select
                  label="Device segment"
                  value={device.segment || ""}
                  options={[
                    ["", "Unknown"],
                    ...(deviceBus?.segments || []).map(
                      (s: string) => [s, s] as [string, string],
                    ),
                  ]}
                  onChange={(segment) =>
                    editForm("device", { segment: segment || null })
                  }
                />
                <Select
                  label="Connection mode"
                  value={device.mode}
                  options={["wired", "wireless", "unknown"]}
                  onChange={(mode) => editForm("device", { mode })}
                />
                <Select
                  label="Switch128 interpretation"
                  value={device.switch128}
                  options={[
                    ["unknown", "Unknown"],
                    ["off", "OFF"],
                    ["on", "ON"],
                    ["not-applicable", "Not applicable to this interface"],
                  ]}
                  onChange={(switch128) => editForm("device", { switch128 })}
                />
                <Select
                  label="Planned device EOL"
                  value={device.eol}
                  options={["unknown", "off", "on", "fixed-on"]}
                  onChange={(eol) => editForm("device", { eol })}
                />
              </div>
              <label>
                Device evidence notes
                <textarea
                  aria-label="Device evidence notes"
                  maxLength={2000}
                  value={device.notes}
                  onChange={(event) =>
                    editForm("device", { notes: event.target.value })
                  }
                />
              </label>
              <p>
                Unknown model suffixes and generations receive no inferred
                profile. Legacy controller switch128 selects wireless mode; it
                is not added to the MAC. SA host 0 is distinct from that
                controller's upstream FC address. Refreshed NS8000 sensor
                address switches are a different profile.
              </p>
              <button
                disabled={busy || !draft.buses.length}
                onClick={() => void apply("device")}
              >
                {deviceEditing
                  ? "Apply device edits"
                  : "Add device connection to plan"}
              </button>
            </fieldset>
            <h3>Device connections ({draft.devices.length}/256)</h3>
            <div className="bus-plan-table">
              <table>
                <thead>
                  <tr>
                    <th>Device / model</th>
                    <th>Bus / segment</th>
                    <th>Role / MAC</th>
                    <th>Mode / switch128 / EOL</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {draft.devices.map((row: Data) => (
                    <tr key={row.id}>
                      <td>
                        {row.label}
                        <small>{row.model || "Unknown model"}</small>
                        <small>{row.generation || "Unknown generation"}</small>
                      </td>
                      <td>
                        {
                          draft.buses.find((b: Data) => b.id === row.bus_id)
                            ?.name
                        }
                        <small>{row.segment || "Unknown segment"}</small>
                      </td>
                      <td>
                        {row.role}
                        <small>MAC {show(row.mac)}</small>
                      </td>
                      <td>
                        {row.mode}
                        <small>
                          {row.switch128} / EOL {row.eol}
                        </small>
                      </td>
                      <td>
                        <button
                          aria-label={`Edit device ${row.label}`}
                          onClick={() => selectEdit("device", row)}
                        >
                          Edit
                        </button>
                        <button
                          aria-label={`Remove device ${row.label}`}
                          onClick={() => remove("devices", row)}
                        >
                          Remove
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <fieldset>
              <legend>
                {linkEditing ? "Edit planned cable" : "Add planned cable"}
              </legend>
              <div className="bus-plan-grid">
                <Select
                  label="Cable endpoint A"
                  value={link.a}
                  options={[
                    ["", "Select connection"],
                    ...draft.devices.map(
                      (d: Data) => [d.id, d.label] as [string, string],
                    ),
                  ]}
                  onChange={(a) => editForm("link", { a })}
                />
                <Select
                  label="Cable endpoint B"
                  value={link.b}
                  options={[
                    ["", "Select connection"],
                    ...draft.devices.map(
                      (d: Data) => [d.id, d.label] as [string, string],
                    ),
                  ]}
                  onChange={(b) => editForm("link", { b })}
                />
                <Select
                  label="Cable or bridge kind"
                  value={link.kind}
                  options={[
                    ["unknown", "Unknown"],
                    ["terminal", "Ordinary screw-terminal trunk"],
                    ["modular", "Ordinary 6-pin SA modular cable"],
                    ["sensor-service", "Sensor service-port accessory leaf"],
                    ["repeater-bridge", "FC repeater side bridge"],
                  ]}
                  onChange={(kind) => editForm("link", { kind })}
                />
                <label>
                  Planned cable length metres
                  <input
                    aria-label="Planned cable length metres"
                    type="number"
                    min={0}
                    max={100000}
                    step="any"
                    value={link.length_m ?? ""}
                    onChange={(event) =>
                      editForm("link", {
                        length_m:
                          event.target.value === ""
                            ? null
                            : Number(event.target.value),
                      })
                    }
                  />
                </label>
                <Select
                  label="6-pin straight-through cable"
                  value={
                    link.straight_through === null
                      ? "unknown"
                      : String(link.straight_through)
                  }
                  options={[
                    ["unknown", "Unknown / not established"],
                    ["true", "Declared straight-through"],
                    ["false", "Declared crossover"],
                  ]}
                  onChange={(value) =>
                    editForm("link", {
                      straight_through:
                        value === "unknown" ? null : value === "true",
                    })
                  }
                />
              </div>
              <label>
                Cable evidence notes
                <textarea
                  aria-label="Cable evidence notes"
                  maxLength={2000}
                  value={link.notes}
                  onChange={(event) =>
                    editForm("link", { notes: event.target.value })
                  }
                />
              </label>
              <p>
                Ordinary trunk branches and cycles are checked separately from
                reviewed accessory leaves and FC repeater bridges. Only the
                exact reviewed refreshed NS8000/CWCVT service leaf is
                recognized; arbitrary RJ45/RJ12 stubs remain unresolved. No
                cable length, shield, power or termination is measured.
              </p>
              <button
                disabled={busy || draft.devices.length < 2}
                onClick={() => void apply("link")}
              >
                {linkEditing
                  ? "Apply cable edits"
                  : "Add planned cable to plan"}
              </button>
            </fieldset>
            <h3>Planned cables ({draft.links.length}/512)</h3>
            <div className="bus-plan-table">
              <table>
                <thead>
                  <tr>
                    <th>Endpoints</th>
                    <th>Kind / length</th>
                    <th>Pinout</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {draft.links.map((row: Data) => (
                    <tr key={row.id}>
                      <td>
                        {deviceName(row.a)} / {deviceName(row.b)}
                      </td>
                      <td>
                        {row.kind}
                        <small>{show(row.length_m)} m</small>
                      </td>
                      <td>{show(row.straight_through)}</td>
                      <td>
                        <button
                          aria-label={`Edit cable ${deviceName(row.a)} to ${deviceName(row.b)}`}
                          onClick={() => selectEdit("link", row)}
                        >
                          Edit
                        </button>
                        <button
                          aria-label={`Remove cable ${deviceName(row.a)} to ${deviceName(row.b)}`}
                          onClick={() => remove("links", row)}
                        >
                          Remove
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <button
              onClick={() => {
                invalidate();
                clearEditors(draft.buses[0]);
              }}
            >
              Clear all editors
            </button>
            {pending && (
              <p role="note">
                There are unapplied editor changes. Apply one editor or clear
                all editors before review/export. Applying a declaration clears
                the other editors.
              </p>
            )}
            {report && (
              <section aria-label="JCI bus review results">
                <h3>Bus review status: {report.status}</h3>
                <p>
                  {report.counts.error} conflicts · {report.counts.unknown}{" "}
                  unresolved · {report.counts.info} notes
                </p>
                <p>
                  Address checks: {report.checks.address} · Graph checks:{" "}
                  {report.checks.topology} · Engineering coverage:{" "}
                  {report.checks.engineering}
                </p>
                <p>{report.scope}</p>
                <p>
                  Displayed review captured {report.reviewed_at}. Export
                  calculates a fresh capture of this same guarded plan.
                </p>
                <p>
                  Plan SHA-256 <code>{report.plan_sha256}</code>
                  <br />
                  Review SHA-256 <code>{report.content_sha256}</code>
                </p>
                <ul className="bus-plan-findings">
                  {report.findings.map((f: Data) => (
                    <li key={f.id}>
                      <strong>
                        {f.severity}: {f.code}
                      </strong>
                      <p>{f.message}</p>
                      <p>
                        {f.bus_id
                          ? draft.buses.find((b: Data) => b.id === f.bus_id)
                              ?.name
                          : "Whole plan"}{" "}
                        · {f.category}
                      </p>
                      <p>{f.device_ids.map(deviceName).join(", ")}</p>
                    </li>
                  ))}
                </ul>
                <details>
                  <summary>Full submitted evidence</summary>
                  <pre>{JSON.stringify(report, null, 2)}</pre>
                </details>
              </section>
            )}
            <details>
              <summary>Bus profile sources and exact model scope</summary>
              <p>
                Catalog SHA-256 <code>{catalog.sha256}</code>. Hashes identify
                reviewed artifacts, not manufacturer-authenticated operator
                data. The sensor source is an extraction capture, not PDF bytes.
              </p>
              <pre>{JSON.stringify(catalog, null, 2)}</pre>
            </details>
            <p>
              Export this plan before leaving Connect. JSON import reopens it
              after restart; no server-side plan store is used. Source-guarded
              imports and fresh review exports reject stale catalogs. All editor
              changes invalidate the displayed review; pending results/downloads
              are ignored after newer edits, import, close or navigation.
            </p>
          </>
        )}
        {busy && <p role="status">Validating local bus declarations…</p>}
        {message && <p role="status">{message}</p>}
        {error && <p role="alert">{error}</p>}
      </section>
    </details>
  );
}
