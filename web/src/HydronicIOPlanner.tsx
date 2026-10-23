import { useEffect, useRef, useState } from "react";
import { api, apiBlobDocument, saveBlob } from "./api";
import {
  HYDRONIC_RULES,
  MONITORS,
  checkCSV,
  endpoint,
  fileDocument,
  plantDocument,
  profileResult,
  reviewResult,
  rolePlanResult,
  sha256,
  stable,
  type Binding,
  type Host,
  type Role,
} from "./hydronicIOContract";

type Draft = {
  loop: string;
  arrangement: string;
  chillers: string;
  primary: string;
  secondary: string;
  equalPrimary: boolean;
  equalSecondary: boolean;
  isolation: string;
  measurement: string;
  flow: string;
  pressure: string;
  temperature: string;
  monitoring: string[];
  prove: string[];
};
type Row = {
  endpoint: string;
  transport: string;
  host: string;
  mode: string;
  links: string[];
};
const emptyRow = (): Row => ({
  endpoint: "",
  transport: "",
  host: "",
  mode: "",
  links: [],
});
const initialDraft = (): Draft => ({
  loop: "primary-only",
  arrangement: "headered",
  chillers: "1",
  primary: "1",
  secondary: "1",
  equalPrimary: false,
  equalSecondary: false,
  isolation: "binary",
  measurement: "decoupler-flow",
  flow: "gpm",
  pressure: "psi",
  temperature: "degF",
  monitoring: [],
  prove: [],
});
const initialHost = () => ({
  label: "",
  plant: "",
  kind: "controller",
  model: "",
  parent: "",
  survey: false,
  surveyId: "",
  surveyHash: "",
  mac: "",
});
const count = (value: string) => {
  if (!/^[1-8]$/.test(value))
    throw new Error("Equipment counts require integers from 1 to 8.");
  return Number(value);
};
function topology(draft: Draft) {
  const headered = draft.arrangement === "headered",
    secondary = draft.loop === "primary-secondary";
  if (headered && !draft.equalPrimary)
    throw new Error("Explicitly confirm equally sized headered primary pumps.");
  if (secondary && !draft.equalSecondary)
    throw new Error("Explicitly confirm equally sized secondary pumps.");
  if (
    !secondary &&
    (draft.monitoring.some(
      (m) => m.startsWith("secondary-") || m === "decoupler-flow",
    ) ||
      draft.prove.includes("secondary"))
  )
    throw new Error(
      "Clear secondary/decoupler selections before deriving a primary-only layout.",
    );
  return {
    loop: draft.loop,
    primary_arrangement: draft.arrangement,
    chillers: count(draft.chillers),
    primary_pumps: headered ? count(draft.primary) : null,
    secondary_pumps: secondary ? count(draft.secondary) : null,
    primary_speed: "variable",
    equally_sized_primary: headered ? true : null,
    equally_sized_secondary: secondary ? true : null,
    isolation_command: headered ? draft.isolation : null,
    primary_speed_measurement: secondary ? draft.measurement : null,
    units: {
      flow: draft.flow,
      pressure: draft.pressure,
      temperature: draft.temperature,
    },
    monitoring: draft.monitoring,
    prove_on: draft.prove,
  };
}
function modes(role: Role) {
  if (role.direction === "input")
    return role.value_type === "boolean"
      ? ["input-contact"]
      : ["input-voltage", "input-current", "input-resistance"];
  return role.value_type === "boolean"
    ? ["output-triac", "output-fet", "output-relay"]
    : ["output-voltage", "output-current"];
}

export function HydronicIOPlanner({ plantReview }: { plantReview: any }) {
  const [opened, setOpened] = useState(false),
    [authorityReady, setAuthorityReady] = useState(false),
    [profile, setProfile] = useState<any>(null),
    [catalog, setCatalog] = useState<any>(null),
    [plant, setPlant] = useState<Awaited<
      ReturnType<typeof plantDocument>
    > | null>(null),
    [draft, setDraft] = useState<Draft>(initialDraft),
    [rolePlan, setRolePlan] = useState<{
      data: any;
      blob: Blob;
      key: string;
    } | null>(null),
    [hosts, setHosts] = useState<Host[]>([]),
    [newHost, setNewHost] = useState(initialHost),
    [rows, setRows] = useState<Record<string, Row>>({}),
    [result, setResult] = useState<{
      data: any;
      blob: Blob;
      bytesSha: string;
      key: string;
    } | null>(null),
    [busy, setBusy] = useState(""),
    [error, setError] = useState("");
  const alive = useRef(true),
    epoch = useRef(0),
    working = useRef<number | null>(null),
    nextHost = useRef(1);
  const sourceKey = stable([
    plantReview.id,
    plantReview.content_sha256,
    plantReview.plan_sha256,
  ]);
  const deriveKey = stable([sourceKey, profile?.profile.sha256 ?? null, draft]);
  const key = stable([
    deriveKey,
    catalog?.catalog_sha256 ?? null,
    hosts,
    rows,
    plant?.raw_sha256 ?? null,
  ]);
  const now = useRef(key);
  now.current = key;
  const derived = rolePlan?.key === deriveKey ? rolePlan : null,
    reviewed = result?.key === key ? result : null;
  const current = (ticket: number, source: string) =>
    alive.current && epoch.current === ticket && now.current === source;
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      epoch.current++;
    };
  }, []);
  useEffect(() => {
    epoch.current++;
    setResult(null);
    setRolePlan(null);
    setRows({});
    setHosts([]);
    setPlant(null);
    setProfile(null);
    setCatalog(null);
    setOpened(false);
    setAuthorityReady(false);
    setError("");
  }, [sourceKey]);
  async function task(
    label: string,
    work: (valid: () => boolean) => Promise<void>,
  ) {
    if (working.current !== null) return;
    const ticket = ++epoch.current,
      source = now.current;
    working.current = ticket;
    setBusy(label);
    setError("");
    try {
      await work(() => current(ticket, source));
    } catch (failure) {
      if (current(ticket, source)) setError(String(failure));
    } finally {
      if (working.current === ticket) working.current = null;
      if (alive.current && epoch.current === ticket) setBusy("");
    }
  }
  function change(action: () => void, choices = false) {
    epoch.current++;
    working.current = null;
    setResult(null);
    setError("");
    setBusy("");
    if (choices) {
      setRolePlan(null);
      setRows({});
    }
    action();
  }
  function editDraft(patch: Partial<Draft>) {
    change(() => setDraft((d) => ({ ...d, ...patch })), true);
  }
  async function open() {
    setOpened(true);
    // A failed reload cannot retain earlier download authority. Typed choices
    // and explicit declarations stay in memory until supported rules return.
    setAuthorityReady(false);
    setRolePlan(null);
    setResult(null);
    await task("Loading exact local engineering authority", async (valid) => {
      const [rules, capacity, original] = await Promise.all([
        api("/hydronic-io/profile"),
        api("/hardware-capacity/catalog"),
        apiBlobDocument("/plant-signals/reviews/export/json", {
          id: plantReview.id,
          content_sha256: plantReview.content_sha256,
        }),
      ]);
      const supported = await profileResult(rules, capacity),
        exact = await plantDocument(original.blob, plantReview);
      if (valid()) {
        setProfile(supported);
        setCatalog(capacity);
        setPlant(exact);
        setAuthorityReady(true);
      }
    });
  }
  async function derive() {
    if (!profile) return;
    let selected: any;
    try {
      selected = topology(draft);
    } catch (e) {
      setError(String(e));
      return;
    }
    await task("Deriving hydraulic roles and dependencies", async (valid) => {
      const blob = await fileDocument(
          "/hydronic-io/derive",
          { profile_sha256: HYDRONIC_RULES, topology: selected },
          "json",
        ),
        value = await rolePlanResult(JSON.parse(await blob.text()), selected);
      if (valid()) {
        setRolePlan({ data: value, blob, key: deriveKey });
        setResult(null);
      }
    });
  }
  function addHost() {
    try {
      if (
        !newHost.label.trim() ||
        !newHost.model.trim() ||
        !plantReview.plan.hosts.some((h: any) => h.id === newHost.plant)
      )
        throw new Error(
          "Declare a label, exact PLANT host and physical model.",
        );
      if (hosts.length >= 32)
        throw new Error("At most 32 explicit physical hosts.");
      if (
        newHost.kind === "controller" &&
        hosts.some(
          (h) => h.plant_host_id === newHost.plant && h.kind === "controller",
        )
      )
        throw new Error("A PLANT host accepts one declared base controller.");
      if (
        newHost.kind === "module" &&
        !hosts.some(
          (h) =>
            h.id === newHost.parent &&
            h.kind === "controller" &&
            h.plant_host_id === newHost.plant,
        )
      )
        throw new Error(
          "Choose an explicit parent controller on the same PLANT host.",
        );
      let survey: Host["survey_reference"] = null;
      if (newHost.survey) {
        if (
          !/^[a-f0-9]{32}$/.test(newHost.surveyId) ||
          !/^[a-f0-9]{64}$/.test(newHost.surveyHash) ||
          (newHost.kind === "module" &&
            (!/^[1-9][0-9]{0,2}$/.test(newHost.mac) ||
              Number(newHost.mac) > 254))
        )
          throw new Error(
            "Survey references need exact stored ID/hash and module SA MAC 1–254.",
          );
        survey = {
          id: newHost.surveyId,
          content_sha256: newHost.surveyHash,
          host: newHost.kind === "module" ? "sa" : "base",
          sa_mac: newHost.kind === "module" ? Number(newHost.mac) : null,
        };
      }
      const host: Host = {
        id: "physical" + nextHost.current++,
        label: newHost.label,
        plant_host_id: newHost.plant,
        kind: newHost.kind as Host["kind"],
        model: newHost.model,
        parent_controller_id: newHost.kind === "module" ? newHost.parent : null,
        survey_reference: survey,
      };
      change(() => {
        setHosts((list) => [...list, host]);
        setNewHost(initialHost());
      });
    } catch (e) {
      setError(String(e));
    }
  }
  function editRow(id: string, row: Row) {
    change(() => setRows((v) => ({ ...v, [id]: row })));
  }
  function request() {
    if (!derived || !profile || !catalog || !plant)
      throw new Error(
        "Derive the current topology with exact PLANT authority first.",
      );
    const bindings: Binding[] = [];
    for (const role of derived.data.roles as Role[]) {
      const row = rows[role.id];
      if (!row?.endpoint) continue;
      const point = plantReview.analysis.io_schedule.find(
        (p: any) => endpoint(p) === row.endpoint,
      );
      if (!point || !["physical", "network"].includes(row.transport))
        throw new Error(`Select explicit transport for ${role.id}.`);
      if (
        row.transport === "physical" &&
        (!row.host || !modes(role).includes(row.mode))
      )
        throw new Error(
          `Declare a physical host and electrical mode for ${role.id}.`,
        );
      if (row.transport === "network" && !row.links.length)
        throw new Error(`Select exact existing network links for ${role.id}.`);
      bindings.push({
        role_id: role.id,
        instance_id: point.instance_id,
        node_id: point.node_id,
        transport: row.transport as Binding["transport"],
        physical_host_id: row.transport === "physical" ? row.host : null,
        mode: row.transport === "physical" ? row.mode : null,
        network_link_ids: row.transport === "network" ? row.links : [],
      });
    }
    if (new Set(bindings.map(endpoint)).size !== bindings.length)
      throw new Error(
        "An exact endpoint cannot bind two distinct hydraulic roles.",
      );
    return {
      profile_sha256: HYDRONIC_RULES,
      topology: topology(draft),
      plant_review: {
        id: plantReview.id,
        content_sha256: plantReview.content_sha256,
      },
      capacity_catalog_sha256: catalog.catalog_sha256,
      physical_hosts: hosts,
      bindings,
    };
  }
  async function review() {
    let declaration: any;
    try {
      declaration = request();
    } catch (e) {
      setError(String(e));
      return;
    }
    await task(
      "Reviewing explicit hydraulic bindings and capacity",
      async (valid) => {
        const blob = await fileDocument(
            "/hydronic-io/review",
            declaration,
            "json",
          ),
          value = await reviewResult(
            JSON.parse(await blob.text()),
            declaration,
            derived!.data,
            plant,
            profile.profile,
          ),
          bytesSha = await sha256(blob);
        if (valid()) setResult({ data: value, blob, bytesSha, key });
      },
    );
  }
  async function exportFile(kind: "json" | "csv", bound: boolean) {
    const selected = bound ? reviewed : derived;
    if (!selected) return;
    await task("Checking hydraulic export authority", async (valid) => {
      if (!bound && kind === "json") {
        if (valid()) saveBlob(selected.blob, "hydraulic-role-plan.json");
        return;
      }
      const body = bound
        ? { content_sha256: reviewed!.data.content_sha256 }
        : { profile_sha256: HYDRONIC_RULES, topology: topology(draft) };
      const blob = await fileDocument(
        bound
          ? `/hydronic-io/reviews/export/${kind}`
          : "/hydronic-io/derive/csv",
        body,
        kind,
      );
      if (kind === "csv")
        await checkCSV(blob, derived!.data, bound ? reviewed!.data : undefined);
      else if ((await sha256(blob)) !== reviewed!.bytesSha)
        throw new Error(
          "Retained hydraulic export changed its original bytes.",
        );
      if (valid())
        saveBlob(
          blob,
          `hydraulic-${bound ? "io-review" : "role-plan"}.${kind}`,
        );
    });
  }
  const secondary = draft.loop === "primary-secondary",
    headered = draft.arrangement === "headered";
  return (
    <section className="card" aria-label="Chilled-water hydraulic I/O planner">
      <div className="card-header">
        <h4>Chilled-water hydraulic I/O planner</h4>
      </div>
      <div className="card-body">
        {!opened ? (
          <button onClick={() => void open()}>
            Open hydraulic I/O planner
          </button>
        ) : (
          <>
            <p>
              Derive a hydraulic point schedule for parallel chillers with
              variable-speed pumps. Bind exact Program interfaces and explicit
              controller/module electrical modes. No control Program is
              generated.
            </p>
            <p>
              Current PLANT review: <code>{plantReview.id}</code>. Unit text
              must match exactly. Count fit covers this declared hydraulic
              subset; other application occupancy, spare terminals, wiring,
              whole-plant fit and native allocation remain unverified.
            </p>
            <div className="button-row wrap">
              <button disabled={!!busy} onClick={() => void open()}>
                Reload hydraulic authority
              </button>
              <button
                onClick={() => {
                  epoch.current++;
                  working.current = null;
                  setOpened(false);
                  setAuthorityReady(false);
                  setBusy("");
                  setProfile(null);
                  setCatalog(null);
                  setPlant(null);
                  setResult(null);
                  setRolePlan(null);
                }}
              >
                Close hydraulic planner
              </button>
              {busy && (
                <button
                  onClick={() => {
                    epoch.current++;
                    working.current = null;
                    setBusy("");
                    setResult(null);
                    setError(
                      "Pending response ignored. Local server computation may finish; no field operation was started.",
                    );
                  }}
                >
                  Cancel hydraulic response
                </button>
              )}
            </div>
            {busy && <p role="status">{busy}. No automatic retry.</p>}
            {error && <p role="alert">{error}</p>}
            {authorityReady && profile && catalog && plant && (
              <>
                <fieldset>
                  <legend>Hydraulic topology and units</legend>
                  <label>
                    Loop{" "}
                    <select
                      aria-label="Hydraulic loop"
                      value={draft.loop}
                      onChange={(e) => editDraft({ loop: e.target.value })}
                    >
                      <option value="primary-only">Primary only</option>
                      <option value="primary-secondary">
                        Primary secondary
                      </option>
                    </select>
                  </label>
                  <label>
                    Primary pumps{" "}
                    <select
                      aria-label="Hydraulic primary arrangement"
                      value={draft.arrangement}
                      onChange={(e) =>
                        editDraft({ arrangement: e.target.value })
                      }
                    >
                      <option value="headered">Headered</option>
                      <option value="dedicated">Dedicated to chillers</option>
                    </select>
                  </label>
                  <label>
                    Chillers{" "}
                    <input
                      aria-label="Hydraulic chiller count"
                      value={draft.chillers}
                      inputMode="numeric"
                      maxLength={1}
                      onChange={(e) => editDraft({ chillers: e.target.value })}
                    />
                  </label>
                  <p>
                    Primary speed: variable. Dedicated configuration assumes
                    exactly one pump per chiller.
                  </p>
                  {headered && (
                    <>
                      <label>
                        Primary pump count{" "}
                        <input
                          aria-label="Hydraulic primary pump count"
                          value={draft.primary}
                          inputMode="numeric"
                          maxLength={1}
                          onChange={(e) =>
                            editDraft({ primary: e.target.value })
                          }
                        />
                      </label>
                      <label>
                        <input
                          type="checkbox"
                          aria-label="Confirm equally sized primary pumps"
                          checked={draft.equalPrimary}
                          onChange={(e) =>
                            editDraft({ equalPrimary: e.target.checked })
                          }
                        />{" "}
                        I declare headered primary pumps equally sized
                      </label>
                      <label>
                        Isolation command{" "}
                        <select
                          aria-label="Hydraulic isolation command"
                          value={draft.isolation}
                          onChange={(e) =>
                            editDraft({ isolation: e.target.value })
                          }
                        >
                          <option value="binary">Binary</option>
                          <option value="modulating">Modulating percent</option>
                        </select>
                      </label>
                    </>
                  )}
                  {secondary && (
                    <>
                      <label>
                        Secondary pump count{" "}
                        <input
                          aria-label="Hydraulic secondary pump count"
                          value={draft.secondary}
                          inputMode="numeric"
                          maxLength={1}
                          onChange={(e) =>
                            editDraft({ secondary: e.target.value })
                          }
                        />
                      </label>
                      <label>
                        <input
                          type="checkbox"
                          aria-label="Confirm equally sized secondary pumps"
                          checked={draft.equalSecondary}
                          onChange={(e) =>
                            editDraft({ equalSecondary: e.target.checked })
                          }
                        />{" "}
                        I declare secondary pumps equally sized, headered and
                        variable speed
                      </label>
                      <label>
                        Primary speed measurement{" "}
                        <select
                          aria-label="Hydraulic primary speed measurement"
                          value={draft.measurement}
                          onChange={(e) =>
                            editDraft({ measurement: e.target.value })
                          }
                        >
                          <option value="decoupler-flow">
                            Direct decoupler flow
                          </option>
                          <option value="flow-difference">
                            Primary minus secondary flow
                          </option>
                          <option value="temperature-difference">
                            Primary/secondary supply temperature difference
                          </option>
                        </select>
                      </label>
                      <p>
                        Secondary staging still requires flow. Headered primary
                        staging also requires primary flow. A temperature-based
                        speed strategy does not make this whole plant
                        meter-free.
                      </p>
                    </>
                  )}
                  {(
                    [
                      ["flow", ["gpm", "L/s", "m3/h"]],
                      ["pressure", ["psi", "kPa", "bar"]],
                      ["temperature", ["degF", "degC", "°F", "°C"]],
                    ] as const
                  ).map(([name, units]) => (
                    <label key={name}>
                      {name} unit{" "}
                      <select
                        aria-label={`Hydraulic ${name} unit`}
                        value={draft[name]}
                        onChange={(e) => editDraft({ [name]: e.target.value })}
                      >
                        {units.map((unit) => (
                          <option key={unit}>{unit}</option>
                        ))}
                      </select>
                    </label>
                  ))}
                </fieldset>
                <details>
                  <summary>
                    Optional monitoring and selected prove-on sources
                  </summary>
                  <fieldset>
                    <legend>Monitoring adds declared logical roles</legend>
                    {MONITORS.map((name) => (
                      <label key={name}>
                        <input
                          type="checkbox"
                          aria-label={`Hydraulic monitor ${name}`}
                          checked={draft.monitoring.includes(name)}
                          disabled={
                            !secondary &&
                            (name.startsWith("secondary-") ||
                              name === "decoupler-flow") &&
                            !draft.monitoring.includes(name)
                          }
                          onChange={(e) =>
                            editDraft({
                              monitoring: e.target.checked
                                ? [...draft.monitoring, name]
                                : draft.monitoring.filter((v) => v !== name),
                            })
                          }
                        />
                        {name}
                      </label>
                    ))}
                  </fieldset>
                  <fieldset>
                    <legend>
                      Selected prove-on sources; sequence behavior stays outside
                      this planner
                    </legend>
                    {["chiller", "primary", "secondary"].map((name) => (
                      <label key={name}>
                        <input
                          type="checkbox"
                          aria-label={`Hydraulic prove-on ${name}`}
                          checked={draft.prove.includes(name)}
                          disabled={
                            name === "secondary" &&
                            !secondary &&
                            !draft.prove.includes(name)
                          }
                          onChange={(e) =>
                            editDraft({
                              prove: e.target.checked
                                ? [...draft.prove, name]
                                : draft.prove.filter((v) => v !== name),
                            })
                          }
                        />
                        {name}
                      </label>
                    ))}
                  </fieldset>
                </details>
                <button disabled={!!busy} onClick={() => void derive()}>
                  Derive hydraulic roles
                </button>
                {derived && (
                  <div aria-label="Derived hydraulic role schedule">
                    <p>
                      {derived.data.roles.length} logical roles ·{" "}
                      {derived.data.equipment_counts.chillers} chillers ·{" "}
                      {derived.data.equipment_counts.primary_pumps} primary
                      pumps · {derived.data.equipment_counts.secondary_pumps}{" "}
                      secondary pumps. No physical channels are consumed until
                      explicitly bound below.
                    </p>
                    <div className="button-row wrap">
                      <button
                        disabled={!!busy}
                        onClick={() => void exportFile("json", false)}
                      >
                        Download original hydraulic role JSON
                      </button>
                      <button
                        disabled={!!busy}
                        onClick={() => void exportFile("csv", false)}
                      >
                        Export hydraulic role CSV
                      </button>
                    </div>
                    <fieldset>
                      <legend>
                        Explicit physical controller and module declarations
                      </legend>
                      <p>
                        Declare each base and expansion separately. A parent
                        controller contributes no extra module capacity. Remove
                        unused physical declarations before reviewing.
                      </p>
                      <label>
                        Label{" "}
                        <input
                          aria-label="Hydraulic physical label"
                          maxLength={160}
                          value={newHost.label}
                          onChange={(e) =>
                            setNewHost((v) => ({ ...v, label: e.target.value }))
                          }
                        />
                      </label>
                      <label>
                        PLANT host{" "}
                        <select
                          aria-label="Hydraulic physical PLANT host"
                          value={newHost.plant}
                          onChange={(e) =>
                            setNewHost((v) => ({
                              ...v,
                              plant: e.target.value,
                              parent: "",
                            }))
                          }
                        >
                          <option value="">Choose exact host…</option>
                          {plantReview.plan.hosts.map((h: any) => (
                            <option key={h.id} value={h.id}>
                              {h.id} · {h.label} ·{" "}
                              {h.declared_model || "model undeclared"}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label>
                        Kind{" "}
                        <select
                          aria-label="Hydraulic physical kind"
                          value={newHost.kind}
                          onChange={(e) =>
                            setNewHost((v) => ({
                              ...v,
                              kind: e.target.value,
                              parent: "",
                              survey: false,
                            }))
                          }
                        >
                          <option value="controller">Base controller</option>
                          <option value="module">Expansion module</option>
                        </select>
                      </label>
                      <label>
                        Exact model{" "}
                        <input
                          aria-label="Hydraulic physical model"
                          list="hydraulic-models"
                          maxLength={80}
                          value={newHost.model}
                          onChange={(e) =>
                            setNewHost((v) => ({ ...v, model: e.target.value }))
                          }
                        />
                      </label>
                      <datalist id="hydraulic-models">
                        {catalog.models.map((m: any) => (
                          <option key={m.model} value={m.model} />
                        ))}
                      </datalist>
                      {newHost.kind === "module" && (
                        <label>
                          Explicit parent{" "}
                          <select
                            aria-label="Hydraulic module parent"
                            value={newHost.parent}
                            onChange={(e) =>
                              setNewHost((v) => ({
                                ...v,
                                parent: e.target.value,
                              }))
                            }
                          >
                            <option value="">Choose controller…</option>
                            {hosts
                              .filter(
                                (h) =>
                                  h.kind === "controller" &&
                                  h.plant_host_id === newHost.plant,
                              )
                              .map((h) => (
                                <option key={h.id} value={h.id}>
                                  {h.id} · {h.label}
                                </option>
                              ))}
                          </select>
                        </label>
                      )}
                      <label>
                        <input
                          aria-label="Bind exact hydraulic hardware survey"
                          type="checkbox"
                          checked={newHost.survey}
                          onChange={(e) =>
                            setNewHost((v) => ({
                              ...v,
                              survey: e.target.checked,
                            }))
                          }
                        />{" "}
                        Bind exact stored hardware survey (optional)
                      </label>
                      {newHost.survey && (
                        <>
                          <label>
                            Stored survey ID{" "}
                            <input
                              aria-label="Hydraulic survey ID"
                              maxLength={32}
                              value={newHost.surveyId}
                              onChange={(e) =>
                                setNewHost((v) => ({
                                  ...v,
                                  surveyId: e.target.value,
                                }))
                              }
                            />
                          </label>
                          <label>
                            Survey content SHA256{" "}
                            <input
                              aria-label="Hydraulic survey hash"
                              maxLength={64}
                              value={newHost.surveyHash}
                              onChange={(e) =>
                                setNewHost((v) => ({
                                  ...v,
                                  surveyHash: e.target.value,
                                }))
                              }
                            />
                          </label>
                          {newHost.kind === "module" && (
                            <label>
                              Exact SA MAC{" "}
                              <input
                                aria-label="Hydraulic survey SA MAC"
                                maxLength={3}
                                value={newHost.mac}
                                onChange={(e) =>
                                  setNewHost((v) => ({
                                    ...v,
                                    mac: e.target.value,
                                  }))
                                }
                              />
                            </label>
                          )}
                          <p>
                            Copy the exact stored survey ID/hash. The server
                            rechecks base/SA model evidence; this does not
                            establish occupancy or physical installation.
                          </p>
                        </>
                      )}
                      <button
                        disabled={!!busy || hosts.length >= 32}
                        onClick={addHost}
                      >
                        Add explicit hydraulic physical host
                      </button>
                      {hosts.map((h) => (
                        <div
                          key={h.id}
                          aria-label={`Hydraulic physical host ${h.id}`}
                        >
                          <p>
                            {h.id} · {h.label} · {h.kind} · {h.model} · PLANT
                            host {h.plant_host_id}
                            {h.parent_controller_id
                              ? ` · parent ${h.parent_controller_id}`
                              : ""}
                            {h.survey_reference
                              ? ` · ${h.survey_reference.host} survey ${h.survey_reference.id}`
                              : " · no survey binding"}
                          </p>
                          <button
                            disabled={
                              !!busy ||
                              hosts.some(
                                (other) => other.parent_controller_id === h.id,
                              )
                            }
                            onClick={() =>
                              change(() => {
                                setHosts((list) =>
                                  list.filter((v) => v.id !== h.id),
                                );
                                setRows((list) =>
                                  Object.fromEntries(
                                    Object.entries(list).map(([id, row]) => [
                                      id,
                                      row.host === h.id
                                        ? { ...row, host: "" }
                                        : row,
                                    ]),
                                  ),
                                );
                              })
                            }
                          >
                            Remove hydraulic physical host {h.id}
                          </button>
                        </div>
                      ))}
                    </fieldset>
                    <table aria-label="Hydraulic exact role bindings">
                      <thead>
                        <tr>
                          <th>Derived role and reasons</th>
                          <th>Exact PLANT endpoint</th>
                          <th>
                            Transport / physical mode / explicit network links
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {(derived.data.roles as Role[]).map((role) => {
                          const row = rows[role.id] ?? emptyRow(),
                            point = plantReview.analysis.io_schedule.find(
                              (p: any) => endpoint(p) === row.endpoint,
                            ),
                            links = point
                              ? plantReview.plan.links.filter(
                                  (link: any) =>
                                    endpoint(
                                      link[
                                        role.direction === "input"
                                          ? "target"
                                          : "source"
                                      ],
                                    ) === row.endpoint,
                                )
                              : [],
                            used = new Set(
                              Object.entries(rows)
                                .filter(([id]) => id !== role.id)
                                .map(([, r]) => r.endpoint),
                            );
                          return (
                            <tr key={role.id}>
                              <td>
                                <strong>{role.id}</strong>
                                <p>
                                  {role.label} · {role.direction} ·{" "}
                                  {role.value_type} ·{" "}
                                  {role.unit || "Boolean, no unit"}
                                </p>
                                {role.reasons.map((r, i) => (
                                  <p key={i}>
                                    {r.use} · LIT-12014531 PDF{" "}
                                    {r.pdf_pages.join(", ")}
                                  </p>
                                ))}
                              </td>
                              <td>
                                <select
                                  aria-label={`Hydraulic endpoint ${role.id}`}
                                  value={row.endpoint}
                                  onChange={(e) =>
                                    editRow(role.id, {
                                      ...emptyRow(),
                                      endpoint: e.target.value,
                                    })
                                  }
                                >
                                  <option value="">
                                    Unbound; no inferred assignment
                                  </option>
                                  {plantReview.analysis.io_schedule
                                    .filter(
                                      (p: any) =>
                                        p.direction === role.direction &&
                                        p.value_type === role.value_type &&
                                        p.unit === role.unit,
                                    )
                                    .map((p: any) => (
                                      <option
                                        key={endpoint(p)}
                                        value={endpoint(p)}
                                        disabled={used.has(endpoint(p))}
                                      >
                                        {p.instance_id}/{p.node_id} · {p.label}{" "}
                                        · {p.role}
                                      </option>
                                    ))}
                                </select>
                                {point && (
                                  <p>
                                    {point.program_name} · revision{" "}
                                    {point.revision_text} · host {point.host_id}
                                    <br />
                                    <code>{point.source_id}</code>
                                  </p>
                                )}
                              </td>
                              <td>
                                {point && (
                                  <>
                                    <select
                                      aria-label={`Hydraulic transport ${role.id}`}
                                      value={row.transport}
                                      onChange={(e) =>
                                        editRow(role.id, {
                                          ...row,
                                          transport: e.target.value,
                                          host: "",
                                          mode: "",
                                          links: [],
                                        })
                                      }
                                    >
                                      <option value="">
                                        Choose explicitly…
                                      </option>
                                      <option value="physical">
                                        Physical channel
                                      </option>
                                      <option value="network">
                                        Existing network link
                                      </option>
                                    </select>
                                    {row.transport === "physical" && (
                                      <>
                                        <select
                                          aria-label={`Hydraulic physical host ${role.id}`}
                                          value={row.host}
                                          onChange={(e) =>
                                            editRow(role.id, {
                                              ...row,
                                              host: e.target.value,
                                            })
                                          }
                                        >
                                          <option value="">
                                            Choose physical controller/module…
                                          </option>
                                          {hosts
                                            .filter(
                                              (h) =>
                                                h.plant_host_id ===
                                                point.host_id,
                                            )
                                            .map((h) => (
                                              <option key={h.id} value={h.id}>
                                                {h.id} · {h.kind} · {h.model}
                                              </option>
                                            ))}
                                        </select>
                                        <select
                                          aria-label={`Hydraulic electrical mode ${role.id}`}
                                          value={row.mode}
                                          onChange={(e) =>
                                            editRow(role.id, {
                                              ...row,
                                              mode: e.target.value,
                                            })
                                          }
                                        >
                                          <option value="">
                                            Choose electrical signal mode…
                                          </option>
                                          {modes(role).map((mode) => (
                                            <option key={mode} value={mode}>
                                              {catalog.modes[mode] ?? mode}
                                            </option>
                                          ))}
                                        </select>
                                      </>
                                    )}
                                    {row.transport === "network" && (
                                      <>
                                        {!links.length && (
                                          <p>
                                            No existing exact PLANT links for
                                            this endpoint.
                                          </p>
                                        )}
                                        {links.map((link: any) => (
                                          <label key={link.id}>
                                            <input
                                              type="checkbox"
                                              aria-label={`Hydraulic network ${role.id} ${link.id}`}
                                              checked={row.links.includes(
                                                link.id,
                                              )}
                                              onChange={(e) =>
                                                editRow(role.id, {
                                                  ...row,
                                                  links: e.target.checked
                                                    ? [...row.links, link.id]
                                                    : row.links.filter(
                                                        (id) => id !== link.id,
                                                      ),
                                                })
                                              }
                                            />
                                            {link.id}: {link.source.instance_id}
                                            /{link.source.node_id} to{" "}
                                            {link.target.instance_id}/
                                            {link.target.node_id}
                                          </label>
                                        ))}
                                      </>
                                    )}
                                  </>
                                )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                    <button disabled={!!busy} onClick={() => void review()}>
                      Review hydraulic bindings and capacity
                    </button>
                    <details>
                      <summary>
                        Derived dependencies and unresolved sequence assumptions
                      </summary>
                      {derived.data.dependencies.map((d: any) => (
                        <p key={d.id}>
                          {d.id}: {d.role_ids.join(", ")}
                        </p>
                      ))}
                      {derived.data.unresolved_sequence_assumptions.map(
                        (a: any) => (
                          <p key={a.id}>{a.meaning}</p>
                        ),
                      )}
                    </details>
                    <h5>Outside this hydraulic subset</h5>
                    {derived.data.outside_subset_dependencies.map(
                      (d: string) => (
                        <p key={d}>{d}</p>
                      ),
                    )}
                  </div>
                )}
                {reviewed && (
                  <div aria-label="Reviewed hydraulic bindings and capacity">
                    <h5>
                      {reviewed.data.status === "declared-subset-consistent"
                        ? "Declared hydraulic subset consistent; whole application remains unverified"
                        : "Unresolved hydraulic declarations"}
                    </h5>
                    <p>
                      Logical bindings complete:{" "}
                      {String(reviewed.data.logical_bindings_complete)}.
                      Hardware, terminal assignment, native allocation and
                      whole-application fit verified: false.
                    </p>
                    <div className="button-row wrap">
                      <button
                        disabled={!!busy}
                        onClick={() => void exportFile("json", true)}
                      >
                        Export original hydraulic review JSON
                      </button>
                      <button
                        disabled={!!busy}
                        onClick={() => void exportFile("csv", true)}
                      >
                        Export bound hydraulic CSV
                      </button>
                    </div>
                    {reviewed.data.diagnostics.map((d: any, i: number) => (
                      <p key={i}>
                        {d.code}
                        {d.role_id ? ` · ${d.role_id}` : ""}: {d.message}
                      </p>
                    ))}
                    {reviewed.data.capacity_reviews.map((r: any) => (
                      <div key={r.physical_host.id}>
                        <p>
                          {r.physical_host.label} · {r.physical_host.kind} ·{" "}
                          {r.physical_host.model}: {r.capacity_review.status} ·{" "}
                          {r.capacity_review.matched_channels}/
                          {r.capacity_review.declared_channels} declared
                          channels matched.
                        </p>
                        <p>
                          {r.capacity_scope}. Spare channels established: false.
                        </p>
                        {r.capacity_review.demands.map((d: any) => (
                          <p key={d.id}>
                            {d.mode}: {d.matched}/{d.quantity} ·{" "}
                            {d.pool_count_witness
                              .map((p: any) => `${p.pool} ${p.quantity}`)
                              .join(", ") || "no reviewed pool"}
                          </p>
                        ))}
                      </div>
                    ))}
                    <details>
                      <summary>
                        Exact hydraulic review display; downloads retain
                        original bytes
                      </summary>
                      <pre>{JSON.stringify(reviewed.data, null, 2)}</pre>
                    </details>
                  </div>
                )}
                <details>
                  <summary>Source profile and edition conflicts</summary>
                  <p>{profile.scope}</p>
                  {profile.profile.source_conflicts.map((c: any) => (
                    <p key={c.id}>{c.meaning}</p>
                  ))}
                  <p>
                    <code>{profile.profile.sha256}</code>
                  </p>
                </details>
              </>
            )}
          </>
        )}
      </div>
    </section>
  );
}
