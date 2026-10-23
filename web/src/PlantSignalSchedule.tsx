import { useEffect, useRef, useState } from "react";
import { api, download, sourceApi } from "./api";
import { sourceStringify } from "./programSource";
import type { Program } from "./types";
import { HydronicIOPlanner } from "./HydronicIOPlanner";

const BASE = "/plant-signals";
const PROFILE = "distributed-plant-signals/1";
const roles = [
  "unassigned",
  "sensor",
  "command",
  "network-source",
  "network-destination",
] as const;
const subsystems = [
  "chiller",
  "pchwp",
  "cwp",
  "tower",
  "schwp",
  "other",
] as const;
type Signal = {
  node_id: string;
  label: string;
  direction: "input" | "output";
  value_type: "number" | "boolean";
  unit: string;
  terminal_hint: string | null;
};
type Source = {
  id: string;
  program_id: string;
  name: string;
  revision_text: string;
  canonical_sha256: string;
  source_bytes: number;
  scan_seconds_text: string;
  nodes: number;
  signals: Signal[];
};
type Host = { id: string; label: string; declared_model: string };
type Instance = {
  id: string;
  label: string;
  source_id: string;
  host_id: string;
  subsystems: string[];
};
type Endpoint = { instance_id: string; node_id: string };
type Assignment = Endpoint & {
  role: (typeof roles)[number];
  terminal_key: string;
};
type Link = { id: string; source: Endpoint; target: Endpoint };
type Plan = {
  format: "bms.plant-signal-plan/1";
  id: string;
  name: string;
  hosts: Host[];
  instances: Instance[];
  assignments: Assignment[];
  links: Link[];
};
const initialPlan = (): Plan => ({
  format: "bms.plant-signal-plan/1",
  id: "plant1",
  name: "Plant engineering schedule",
  hosts: [],
  instances: [],
  assignments: [],
  links: [],
});
const text = (v: any, max = 160): v is string =>
  typeof v === "string" && v.length <= max;
const hash = (v: any, length = 64): v is string =>
  typeof v === "string" && new RegExp(`^[a-f0-9]{${length}}$`).test(v);
const key = (v: any) =>
  typeof v === "string" && /^[A-Za-z][A-Za-z0-9_-]{0,39}$/.test(v);
const nodeKey = (v: any) =>
  typeof v === "string" && /^[A-Za-z][A-Za-z0-9_-]{0,79}$/.test(v);
const bounded = (v: any, n: number): v is any[] =>
  Array.isArray(v) && v.length <= n;
const count = (v: any, n: number) =>
  Number.isSafeInteger(v) && v >= 0 && v <= n;
const endpointKey = (v: Endpoint) => JSON.stringify([v.instance_id, v.node_id]);
const endpointValid = (v: any) => key(v?.instance_id) && nodeKey(v?.node_id);
const stable = (v: any): string =>
  Array.isArray(v)
    ? `[${v.map(stable).join(",")}]`
    : v && typeof v === "object"
      ? `{${Object.keys(v)
          .sort()
          .map((k) => `${JSON.stringify(k)}:${stable(v[k])}`)
          .join(",")}}`
      : JSON.stringify(v);
function sourceResult(v: any): Source {
  if (
    !hash(v?.id) ||
    !text(v.program_id) ||
    !text(v.name, 200) ||
    !text(v.revision_text, 4300) ||
    !/^\d+$/.test(v.revision_text) ||
    !hash(v.canonical_sha256) ||
    !count(v.source_bytes, 1048576) ||
    !v.source_bytes ||
    !count(v.nodes, 2000) ||
    !text(v.scan_seconds_text, 100) ||
    !bounded(v.signals, 1024) ||
    !v.signals.length ||
    v.signals.some(
      (s: any) =>
        !nodeKey(s?.node_id) ||
        !text(s.label, 200) ||
        !["input", "output"].includes(s.direction) ||
        !["number", "boolean"].includes(s.value_type) ||
        !text(s.unit, 80) ||
        (s.terminal_hint !== null && !text(s.terminal_hint)),
    ) ||
    new Set(v.signals.map((s: any) => s.node_id)).size !== v.signals.length
  )
    throw new Error(
      "Plant Program source summary is malformed or unsupported.",
    );
  return v;
}
function captureResult(v: any) {
  if (
    !hash(v?.id) ||
    !hash(v.report_id, 32) ||
    !hash(v.content_sha256) ||
    !text(v.name) ||
    !text(v.ingested_at, 48) ||
    !Number.isFinite(Date.parse(v.ingested_at)) ||
    !["local-review", "import"].includes(v.origin) ||
    !count(v.bytes, 8388608) ||
    !v.bytes
  )
    throw new Error("Plant capture summary is malformed or unsupported.");
  return v;
}
function profileResult(v: any) {
  if (
    v?.profile?.id !== PROFILE ||
    !hash(v.profile.sha256) ||
    !text(v.scope, 4096) ||
    v.field_queries !== false ||
    v.field_writes !== false ||
    !bounded(v.sources, 32) ||
    !bounded(v.captures, 32)
  )
    throw new Error("Plant schedule profile is malformed or unsupported.");
  v.sources.forEach(sourceResult);
  v.captures.forEach(captureResult);
  if (
    new Set(v.sources.map((s: Source) => s.id)).size !== v.sources.length ||
    new Set(v.captures.map((c: any) => c.id)).size !== v.captures.length
  )
    throw new Error("Plant catalog has duplicate identities.");
  return v;
}
function planResult(v: any): Plan {
  if (
    v?.format !== "bms.plant-signal-plan/1" ||
    !key(v.id) ||
    !text(v.name) ||
    !v.name.length ||
    !bounded(v.hosts, 16) ||
    !v.hosts.length ||
    v.hosts.some(
      (h: any) =>
        !key(h?.id) ||
        !text(h.label) ||
        !h.label.length ||
        !text(h.declared_model, 80),
    ) ||
    !bounded(v.instances, 16) ||
    !v.instances.length ||
    v.instances.some(
      (i: any) =>
        !key(i?.id) ||
        !text(i.label) ||
        !i.label.length ||
        !hash(i.source_id) ||
        !key(i.host_id) ||
        !bounded(i.subsystems, 6) ||
        !i.subsystems.length ||
        i.subsystems.some((s: any) => !subsystems.includes(s)) ||
        new Set(i.subsystems).size !== i.subsystems.length,
    ) ||
    !bounded(v.assignments, 1024) ||
    v.assignments.some(
      (a: any) =>
        !endpointValid(a) ||
        !roles.includes(a.role) ||
        !text(a.terminal_key, 80),
    ) ||
    !bounded(v.links, 1024) ||
    v.links.some(
      (l: any) =>
        !key(l?.id) || !endpointValid(l.source) || !endpointValid(l.target),
    )
  )
    throw new Error("Plant declaration plan is malformed or unsupported.");
  for (const list of [v.hosts, v.instances, v.links])
    if (new Set(list.map((r: any) => r.id)).size !== list.length)
      throw new Error("Plant declaration identities are duplicated.");
  return v;
}
function reviewResult(v: any, rules: string, expected?: Plan) {
  if (
    v?.format !== "bms.plant-signal-review/1" ||
    !hash(v.id, 32) ||
    !hash(v.content_sha256) ||
    !hash(v.plan_sha256) ||
    v.profile?.id !== PROFILE ||
    v.profile.sha256 !== rules ||
    !text(v.reviewed_at, 48) ||
    !Number.isFinite(Date.parse(v.reviewed_at)) ||
    v.field_queries !== false ||
    v.field_writes !== false ||
    !text(v.scope, 4096) ||
    !bounded(v.sources, 16) ||
    !v.sources.length
  )
    throw new Error(
      "Plant review identity/profile is malformed or unsupported.",
    );
  planResult(v.plan);
  v.sources.forEach(sourceResult);
  const sources = new Map<string, Source>(
    v.sources.map((s: Source) => [s.id, s]),
  );
  const instances = new Map<string, Instance>(
    v.plan.instances.map((i: Instance) => [i.id, i]),
  );
  const required = new Set<string>(
    v.plan.instances.map((i: Instance) => i.source_id),
  );
  if (
    sources.size !== v.sources.length ||
    sources.size !== required.size ||
    [...required].some((id) => !sources.has(id)) ||
    v.sources.reduce((sum: number, s: Source) => sum + s.source_bytes, 0) >
      8388608
  )
    throw new Error("Plant review sources do not exactly match its instances.");
  if (expected && stable(v.plan) !== stable(expected))
    throw new Error("Plant review belongs to an earlier declaration.");
  const a = v.analysis;
  if (
    !["unresolved", "software_consistent"].includes(a?.status) ||
    a.hardware_verified !== false ||
    a.native_mapping_verified !== false ||
    !count(a.errors, 4096) ||
    !count(a.warnings, 4096) ||
    !bounded(a.io_schedule, 1024) ||
    a.io_schedule.some(
      (r: any) =>
        !key(r?.instance_id) ||
        !key(r.host_id) ||
        !nodeKey(r.node_id) ||
        !text(r.label, 200) ||
        !["input", "output"].includes(r.direction) ||
        !["number", "boolean"].includes(r.value_type) ||
        !text(r.unit, 80) ||
        !roles.includes(r.role) ||
        !text(r.terminal_key, 80) ||
        !hash(r.source_id) ||
        !hash(r.canonical_sha256) ||
        r.hardware_verified !== false,
    ) ||
    !bounded(a.network_schedule, 1024) ||
    a.network_schedule.some(
      (r: any) =>
        !key(r?.id) ||
        !endpointValid(r.source) ||
        !endpointValid(r.target) ||
        !["unresolved", "software_consistent"].includes(r.status) ||
        !count(r.fanout, 1024) ||
        !bounded(r.findings, 20) ||
        r.findings.some((f: any) => !text(f)) ||
        r.native_mapping_verified !== false,
    ) ||
    !bounded(a.diagnostics, 4096) ||
    a.diagnostics.some(
      (r: any) =>
        !["error", "warning"].includes(r?.severity) ||
        !text(r.code) ||
        !text(r.message, 4096),
    ) ||
    a.errors + a.warnings !== a.diagnostics.length
  )
    throw new Error("Plant review analysis is malformed or unsupported.");
  const expectedPorts = v.plan.instances.reduce(
    (n: number, i: Instance) => n + sources.get(i.source_id)!.signals.length,
    0,
  );
  if (
    a.io_schedule.length !== expectedPorts ||
    new Set(a.io_schedule.map(endpointKey)).size !== expectedPorts ||
    a.io_schedule.some((row: any) => {
      const instance = instances.get(row.instance_id),
        source = instance && sources.get(instance.source_id),
        signal = source?.signals.find((s) => s.node_id === row.node_id);
      return (
        !instance ||
        !source ||
        !signal ||
        row.host_id !== instance.host_id ||
        row.source_id !== source.id ||
        row.canonical_sha256 !== source.canonical_sha256 ||
        row.direction !== signal.direction ||
        row.value_type !== signal.value_type ||
        row.unit !== signal.unit
      );
    }) ||
    a.network_schedule.length !== v.plan.links.length ||
    new Set(a.network_schedule.map((r: any) => r.id)).size !==
      a.network_schedule.length ||
    a.network_schedule.some((row: any) => {
      const link = v.plan.links.find((l: Link) => l.id === row.id);
      return (
        !link ||
        endpointKey(row.source) !== endpointKey(link.source) ||
        endpointKey(row.target) !== endpointKey(link.target)
      );
    }) ||
    (a.status === "software_consistent") !== (a.errors === 0)
  )
    throw new Error(
      "Plant review rows do not bind the exact declared source interfaces and links.",
    );
  return v;
}
function nextKey(prefix: string, rows: { id: string }[]) {
  let n = 1;
  while (rows.some((r) => r.id === prefix + n)) n++;
  return prefix + n;
}

export function PlantSignalSchedule({ program }: { program: Program }) {
  const [opened, setOpened] = useState(false),
    [profile, setProfile] = useState<any>(null),
    [projects, setProjects] = useState<any[]>([]),
    [plan, setPlan] = useState<Plan>(initialPlan),
    [review, setReview] = useState<any>(null),
    [reviewKey, setReviewKey] = useState(""),
    [dirty, setDirty] = useState(false),
    [busy, setBusy] = useState(""),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const [newHost, setNewHost] = useState({ label: "", declared_model: "" }),
    [newInstance, setNewInstance] = useState({
      label: "",
      source_id: "",
      host_id: "",
      subsystems: [] as string[],
    }),
    [linkSource, setLinkSource] = useState(""),
    [linkTarget, setLinkTarget] = useState("");
  const alive = useRef(true),
    active = useRef(false),
    sequence = useRef(0),
    sourceFile = useRef<HTMLInputElement>(null),
    captureFile = useRef<HTMLInputElement>(null);
  let currentSource = "",
    sourceError = "";
  try {
    currentSource = sourceStringify(program);
    if (new Blob([currentSource]).size > 1048576)
      sourceError = "Current Program exceeds the 1 MiB plant source profile.";
  } catch (failure) {
    sourceError = String(failure);
  }
  const authority = stable([
      plan,
      currentSource,
      profile?.profile?.sha256 ?? null,
    ]),
    now = useRef(authority);
  now.current = authority;
  useEffect(() => {
    setReview(null);
    setReviewKey("");
  }, [currentSource]);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      sequence.current++;
    };
  }, []);
  const current = (ticket: number, binding: string) =>
    alive.current && ticket === sequence.current && binding === now.current;
  const reviewed =
    review &&
    reviewKey === authority &&
    review.profile.sha256 === profile?.profile.sha256;
  function edit(next: Plan) {
    sequence.current++;
    setPlan(next);
    setDirty(true);
    setReview(null);
    setReviewKey("");
    setNotice("");
  }
  async function task(
    label: string,
    work: (valid: () => boolean) => Promise<void>,
  ) {
    if (active.current) return;
    active.current = true;
    const ticket = ++sequence.current,
      binding = now.current;
    setBusy(label);
    setError("");
    setNotice("");
    try {
      await work(() => current(ticket, binding));
    } catch (failure) {
      if (current(ticket, binding)) setError(String(failure));
    } finally {
      active.current = false;
      if (alive.current) setBusy("");
    }
  }
  async function refresh(valid: () => boolean) {
    const value = profileResult(await api(BASE + "/profile"));
    if (valid()) setProfile(value);
  }
  async function uploadSource(file: File, valid: () => boolean) {
    if (!file.size || file.size > 1048576)
      throw new Error("Portable Program sources require 1..1048576 bytes.");
    const form = new FormData();
    form.append("file", file);
    const value = sourceResult(await api(BASE + "/sources/import", form));
    const digest = Array.from(
      new Uint8Array(
        await crypto.subtle.digest("SHA-256", await file.arrayBuffer()),
      ),
      (b) => b.toString(16).padStart(2, "0"),
    ).join("");
    if (value.id !== digest || value.source_bytes !== file.size)
      throw new Error(
        "Imported source identity does not match the exact uploaded bytes.",
      );
    if (valid()) {
      setProfile((p: any) => ({
        ...p,
        sources: [...p.sources.filter((s: Source) => s.id !== value.id), value],
      }));
      setReview(null);
      setReviewKey("");
      setNotice(
        "Exact Program source retained. Select its immutable identity for an instance; no roles or links were inferred.",
      );
    }
  }
  function replaceInstance(id: string, patch: Partial<Instance>) {
    const changingSource =
      patch.source_id !== undefined &&
      patch.source_id !== plan.instances.find((i) => i.id === id)?.source_id;
    if (
      changingSource &&
      !window.confirm(
        "Changing this instance source removes its declared roles and links. Continue?",
      )
    )
      return;
    edit({
      ...plan,
      instances: plan.instances.map((i) =>
        i.id === id ? { ...i, ...patch } : i,
      ),
      ...(changingSource
        ? {
            assignments: plan.assignments.filter((a) => a.instance_id !== id),
            links: plan.links.filter(
              (l) => l.source.instance_id !== id && l.target.instance_id !== id,
            ),
          }
        : {}),
    });
  }
  function assign(
    instance_id: string,
    node_id: string,
    patch: Partial<Assignment>,
  ) {
    const previous = plan.assignments.find(
      (a) => a.instance_id === instance_id && a.node_id === node_id,
    ) ?? {
      instance_id,
      node_id,
      role: "unassigned" as const,
      terminal_key: "",
    };
    edit({
      ...plan,
      assignments: [
        ...plan.assignments.filter(
          (a) => a.instance_id !== instance_id || a.node_id !== node_id,
        ),
        { ...previous, ...patch },
      ],
    });
  }
  const ports = plan.instances.flatMap((instance) =>
    (
      profile?.sources.find((s: Source) => s.id === instance.source_id)
        ?.signals ?? []
    ).map((signal: Signal) => ({
      instance,
      signal,
      endpoint: { instance_id: instance.id, node_id: signal.node_id },
    })),
  );
  const portLabel = (row: (typeof ports)[number]) =>
    `${row.instance.id}/${row.signal.node_id} · ${row.signal.label} · ${row.signal.value_type}${row.signal.unit ? ` (${row.signal.unit})` : row.signal.value_type === "number" ? " (unit unknown)" : ""}`;
  const exportReview = (kind: "json" | "csv") =>
    task("Exporting reviewed schedule", async (valid) => {
      if (!reviewed) return;
      const saved = await download(
        BASE + "/reviews/export/" + kind,
        { id: review.id, content_sha256: review.content_sha256 },
        `plant-review-${review.id}.${kind}`,
        valid,
      );
      if (saved && valid() && kind === "json") setDirty(false);
    });
  return (
    <section
      className="card"
      aria-label="Plant I/O and network engineering schedule"
    >
      <div className="card-header">
        <h3>Plant I/O and network engineering schedule</h3>
      </div>
      <div className="card-body">
        {!opened ? (
          <button
            onClick={() => {
              setOpened(true);
              void task("Opening local plant catalog", async (valid) => {
                // Adopt both bootstrap results together. Committing the rules
                // hash first would invalidate this task's captured authority
                // before its saved-project response can be admitted.
                const catalog = profileResult(await api(BASE + "/profile"));
                let projectRows: any[] = [],
                  projectFailure = "";
                try {
                  const rows = await api("/projects");
                  if (
                    !bounded(rows, 1000) ||
                    rows.some(
                      (r: any) =>
                        !text(r?.id, 80) ||
                        !text(r.name, 200) ||
                        !Number.isSafeInteger(r.revision) ||
                        r.revision < 1,
                    )
                  )
                    throw new Error(
                      "Saved project revisions cannot be represented safely; current/file source imports remain available.",
                    );
                  projectRows = rows;
                } catch (failure) {
                  projectFailure = String(failure);
                }
                if (valid()) {
                  setProfile(catalog);
                  setProjects(projectRows);
                  if (projectFailure) setError(projectFailure);
                }
              });
            }}
          >
            Open offline plant engineering schedule
          </button>
        ) : (
          <>
            <p>
              Declare plant hosts, subsystem instances, physical I/O roles and
              exact network links from portable Program sources. A
              software-consistent review does not verify hardware, native
              controller allocation or commissioning. No field queries, writes,
              source execution or simulation.
            </p>
            <div className="button-row wrap">
              <button
                disabled={!!busy}
                onClick={() =>
                  void task("Refreshing local plant catalog", refresh)
                }
              >
                Refresh local plant catalog
              </button>
              <button
                disabled={!!busy}
                onClick={() => {
                  if (
                    dirty &&
                    !window.confirm(
                      "Discard unexported plant declarations and start a new plan? Retained sources and saved captures remain available.",
                    )
                  )
                    return;
                  edit(initialPlan());
                  setNewHost({ label: "", declared_model: "" });
                  setNewInstance({
                    label: "",
                    source_id: "",
                    host_id: "",
                    subsystems: [],
                  });
                  setLinkSource("");
                  setLinkTarget("");
                }}
              >
                New plant declaration plan
              </button>
              <button
                onClick={() => {
                  sequence.current++;
                  setOpened(false);
                  setReview(null);
                  setReviewKey("");
                }}
              >
                Close plant engineering workspace
              </button>
            </div>
            {busy && <p role="status">{busy}. No automatic retry.</p>}
            {error && <p role="alert">{error}</p>}
            {notice && <p role="status">{notice}</p>}
            <p>
              Declarations and unexported changes stay in workspace memory.
              Review and explicitly save a capture or export before leaving.
            </p>
            {profile && (
              <>
                <h4>Exact Program sources</h4>
                {sourceError && <p role="alert">{sourceError}</p>}
                <div className="button-row wrap">
                  <button
                    disabled={!!busy || !!sourceError}
                    onClick={() =>
                      void task("Retaining current Program source", (valid) =>
                        uploadSource(
                          new File([currentSource], "current-program.json", {
                            type: "application/json",
                          }),
                          valid,
                        ),
                      )
                    }
                  >
                    Retain exact current Program source
                  </button>
                  <select
                    aria-label="Retain saved Program revision"
                    value=""
                    disabled={!!busy}
                    onChange={(e) => {
                      const selected = projects.find(
                        (p) => p.id === e.target.value,
                      );
                      if (selected)
                        void task(
                          "Retaining saved Program revision",
                          async (valid) => {
                            const exact = await sourceApi(
                              `/projects/${encodeURIComponent(selected.id)}?revision=${selected.revision}`,
                            );
                            if (
                              exact.id !== selected.id ||
                              exact.revision !== selected.revision
                            )
                              throw new Error(
                                "Saved Program response does not match the selected exact revision.",
                              );
                            if (valid())
                              await uploadSource(
                                new File(
                                  [sourceStringify(exact)],
                                  "saved-program.json",
                                  { type: "application/json" },
                                ),
                                valid,
                              );
                          },
                        );
                    }}
                  >
                    <option value="">Select saved Program revision…</option>
                    {projects.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name} · r{p.revision}
                      </option>
                    ))}
                  </select>
                  <button
                    disabled={!!busy}
                    onClick={() => sourceFile.current?.click()}
                  >
                    Import portable Program source
                  </button>
                  <input
                    ref={sourceFile}
                    type="file"
                    accept=".json"
                    hidden
                    aria-label="Plant Program source file"
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      e.target.value = "";
                      if (file)
                        void task("Importing exact Program source", (valid) =>
                          uploadSource(file, valid),
                        );
                    }}
                  />
                </div>
                <table aria-label="Retained plant Program sources">
                  <thead>
                    <tr>
                      <th>Program / revision</th>
                      <th>Exact identity</th>
                      <th>Interfaces</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {profile.sources.map((s: Source) => (
                      <tr key={s.id}>
                        <td>
                          {s.name} · r{s.revision_text}
                          <br />
                          {s.program_id} · scan {s.scan_seconds_text}s
                        </td>
                        <td>
                          <code>{s.id}</code>
                          <details>
                            <summary>Canonical hash and source size</summary>
                            <code>{s.canonical_sha256}</code> · {s.source_bytes}{" "}
                            bytes
                          </details>
                        </td>
                        <td>{s.signals.length}</td>
                        <td>
                          <button
                            disabled={!!busy}
                            onClick={() =>
                              void task(
                                "Exporting exact Program source",
                                (valid) =>
                                  download(
                                    BASE + "/sources/export",
                                    { id: s.id },
                                    `plant-program-${s.id}.json`,
                                    valid,
                                  ).then(() => {}),
                              )
                            }
                          >
                            Export source {s.id.slice(0, 8)}
                          </button>
                          <button
                            disabled={
                              !!busy ||
                              plan.instances.some((i) => i.source_id === s.id)
                            }
                            onClick={() => {
                              if (
                                window.confirm(
                                  "Remove this unused source from the session catalog? Saved captures retain their own source bytes.",
                                )
                              )
                                void task(
                                  "Removing session Program source",
                                  async (valid) => {
                                    const value = await api(
                                      BASE + "/sources/remove",
                                      { id: s.id },
                                    );
                                    if (
                                      value.removed !== s.id ||
                                      value.field_queries !== false
                                    )
                                      throw new Error(
                                        "Source removal reply does not match.",
                                      );
                                    await refresh(valid);
                                  },
                                );
                            }}
                          >
                            Remove source {s.id.slice(0, 8)}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <h4>Declared plant configuration</h4>
                <label>
                  Plant schedule name
                  <input
                    aria-label="Plant schedule name"
                    maxLength={160}
                    value={plan.name}
                    onChange={(e) => edit({ ...plan, name: e.target.value })}
                  />
                </label>
                <h5>Hosts</h5>
                {plan.hosts.map((h) => (
                  <div className="form-grid" key={h.id}>
                    <strong>{h.id}</strong>
                    <label>
                      Host label
                      <input
                        aria-label={`Plant host label ${h.id}`}
                        value={h.label}
                        maxLength={160}
                        onChange={(e) =>
                          edit({
                            ...plan,
                            hosts: plan.hosts.map((row) =>
                              row.id === h.id
                                ? { ...row, label: e.target.value }
                                : row,
                            ),
                          })
                        }
                      />
                    </label>
                    <label>
                      Declared model
                      <input
                        aria-label={`Declared plant model ${h.id}`}
                        value={h.declared_model}
                        maxLength={80}
                        onChange={(e) =>
                          edit({
                            ...plan,
                            hosts: plan.hosts.map((row) =>
                              row.id === h.id
                                ? { ...row, declared_model: e.target.value }
                                : row,
                            ),
                          })
                        }
                      />
                    </label>
                    <button
                      onClick={() => {
                        if (
                          window.confirm(
                            "Remove this declared host? Instance references remain explicit and will be diagnosed as missing.",
                          )
                        )
                          edit({
                            ...plan,
                            hosts: plan.hosts.filter((row) => row.id !== h.id),
                          });
                      }}
                    >
                      Remove host {h.id}
                    </button>
                  </div>
                ))}
                <div className="button-row wrap">
                  <input
                    aria-label="New plant host label"
                    placeholder="Host label"
                    maxLength={160}
                    value={newHost.label}
                    onChange={(e) =>
                      setNewHost({ ...newHost, label: e.target.value })
                    }
                  />
                  <input
                    aria-label="New plant host model"
                    placeholder="Declared model (optional)"
                    maxLength={80}
                    value={newHost.declared_model}
                    onChange={(e) =>
                      setNewHost({ ...newHost, declared_model: e.target.value })
                    }
                  />
                  <button
                    disabled={plan.hosts.length >= 16 || !newHost.label.trim()}
                    onClick={() => {
                      edit({
                        ...plan,
                        hosts: [
                          ...plan.hosts,
                          {
                            id: nextKey("host", plan.hosts),
                            ...newHost,
                            label: newHost.label.trim(),
                          },
                        ],
                      });
                      setNewHost({ label: "", declared_model: "" });
                    }}
                  >
                    Add declared plant host
                  </button>
                </div>
                <h5>Source-bound subsystem instances</h5>
                {plan.instances.map((i) => (
                  <fieldset key={i.id}>
                    <legend>{i.id}</legend>
                    <label>
                      Instance label
                      <input
                        aria-label={`Plant instance label ${i.id}`}
                        value={i.label}
                        maxLength={160}
                        onChange={(e) =>
                          replaceInstance(i.id, { label: e.target.value })
                        }
                      />
                    </label>
                    <label>
                      Exact source
                      <select
                        aria-label={`Plant instance source ${i.id}`}
                        value={i.source_id}
                        onChange={(e) =>
                          replaceInstance(i.id, { source_id: e.target.value })
                        }
                      >
                        {!profile.sources.some(
                          (s: Source) => s.id === i.source_id,
                        ) && (
                          <option value={i.source_id}>
                            Missing source {i.source_id}
                          </option>
                        )}
                        {profile.sources.map((s: Source) => (
                          <option key={s.id} value={s.id}>
                            {s.name} · r{s.revision_text} · {s.id.slice(0, 12)}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      Declared host
                      <select
                        aria-label={`Plant instance host ${i.id}`}
                        value={i.host_id}
                        onChange={(e) =>
                          replaceInstance(i.id, { host_id: e.target.value })
                        }
                      >
                        {!plan.hosts.some((h) => h.id === i.host_id) && (
                          <option value={i.host_id}>
                            Missing host {i.host_id}
                          </option>
                        )}
                        {plan.hosts.map((h) => (
                          <option key={h.id} value={h.id}>
                            {h.id} · {h.label}
                          </option>
                        ))}
                      </select>
                    </label>
                    <div>
                      {subsystems.map((s) => (
                        <label key={s}>
                          <input
                            type="checkbox"
                            aria-label={`${i.id} subsystem ${s}`}
                            checked={i.subsystems.includes(s)}
                            onChange={(e) =>
                              replaceInstance(i.id, {
                                subsystems: e.target.checked
                                  ? [...i.subsystems, s]
                                  : i.subsystems.filter((v) => v !== s),
                              })
                            }
                          />
                          {s}
                        </label>
                      ))}
                    </div>
                    <button
                      onClick={() => {
                        if (
                          window.confirm(
                            "Remove this instance and its declared roles and links?",
                          )
                        )
                          edit({
                            ...plan,
                            instances: plan.instances.filter(
                              (row) => row.id !== i.id,
                            ),
                            assignments: plan.assignments.filter(
                              (a) => a.instance_id !== i.id,
                            ),
                            links: plan.links.filter(
                              (l) =>
                                l.source.instance_id !== i.id &&
                                l.target.instance_id !== i.id,
                            ),
                          });
                      }}
                    >
                      Remove instance {i.id}
                    </button>
                  </fieldset>
                ))}
                <div className="form-grid">
                  <input
                    aria-label="New plant instance label"
                    placeholder="Instance label"
                    value={newInstance.label}
                    maxLength={160}
                    onChange={(e) =>
                      setNewInstance({ ...newInstance, label: e.target.value })
                    }
                  />
                  <select
                    aria-label="New plant instance source"
                    value={newInstance.source_id}
                    onChange={(e) =>
                      setNewInstance({
                        ...newInstance,
                        source_id: e.target.value,
                      })
                    }
                  >
                    <option value="">Select exact source…</option>
                    {profile.sources.map((s: Source) => (
                      <option key={s.id} value={s.id}>
                        {s.name} · r{s.revision_text} · {s.id.slice(0, 12)}
                      </option>
                    ))}
                  </select>
                  <select
                    aria-label="New plant instance host"
                    value={newInstance.host_id}
                    onChange={(e) =>
                      setNewInstance({
                        ...newInstance,
                        host_id: e.target.value,
                      })
                    }
                  >
                    <option value="">Select declared host…</option>
                    {plan.hosts.map((h) => (
                      <option key={h.id} value={h.id}>
                        {h.id} · {h.label}
                      </option>
                    ))}
                  </select>
                  {subsystems.map((s) => (
                    <label key={s}>
                      <input
                        type="checkbox"
                        aria-label={`New plant subsystem ${s}`}
                        checked={newInstance.subsystems.includes(s)}
                        onChange={(e) =>
                          setNewInstance({
                            ...newInstance,
                            subsystems: e.target.checked
                              ? [...newInstance.subsystems, s]
                              : newInstance.subsystems.filter((v) => v !== s),
                          })
                        }
                      />
                      {s}
                    </label>
                  ))}
                  <button
                    disabled={
                      plan.instances.length >= 16 ||
                      !newInstance.label.trim() ||
                      !newInstance.source_id ||
                      !newInstance.host_id ||
                      !newInstance.subsystems.length
                    }
                    onClick={() => {
                      edit({
                        ...plan,
                        instances: [
                          ...plan.instances,
                          {
                            id: nextKey("instance", plan.instances),
                            ...newInstance,
                            label: newInstance.label.trim(),
                          },
                        ],
                      });
                      setNewInstance({
                        label: "",
                        source_id: "",
                        host_id: "",
                        subsystems: [],
                      });
                    }}
                  >
                    Add source-bound plant instance
                  </button>
                </div>
                <h5>Explicit interface roles</h5>
                <p>
                  Source terminal hints are unverified text. Physical terminal
                  keys are separate operator declarations; nothing is filled
                  from a name or hint.
                </p>
                <table aria-label="Declared plant interface roles">
                  <thead>
                    <tr>
                      <th>Exact interface</th>
                      <th>Source type / unit</th>
                      <th>Declared role</th>
                      <th>Declared physical terminal</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ports.map((row) => {
                      const a = plan.assignments.find(
                        (a) => endpointKey(a) === endpointKey(row.endpoint),
                      );
                      return (
                        <tr key={endpointKey(row.endpoint)}>
                          <td>
                            {row.instance.id}/{row.signal.node_id} ·{" "}
                            {row.signal.label}
                            {row.signal.terminal_hint && (
                              <p>
                                Source hint only: {row.signal.terminal_hint}
                              </p>
                            )}
                          </td>
                          <td>
                            {row.signal.direction} · {row.signal.value_type} ·{" "}
                            {row.signal.unit ||
                              (row.signal.value_type === "number"
                                ? "unit unknown"
                                : "unit not applicable")}
                          </td>
                          <td>
                            <select
                              aria-label={`Plant role ${row.instance.id}/${row.signal.node_id}`}
                              value={a?.role ?? "unassigned"}
                              onChange={(e) =>
                                assign(row.instance.id, row.signal.node_id, {
                                  role: e.target.value as Assignment["role"],
                                })
                              }
                            >
                              {roles.map((r) => (
                                <option key={r}>{r}</option>
                              ))}
                            </select>
                          </td>
                          <td>
                            <input
                              aria-label={`Plant terminal ${row.instance.id}/${row.signal.node_id}`}
                              value={a?.terminal_key ?? ""}
                              maxLength={80}
                              onChange={(e) =>
                                assign(row.instance.id, row.signal.node_id, {
                                  terminal_key: e.target.value,
                                })
                              }
                            />
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                <h5>Explicit network signal links</h5>
                <div className="button-row wrap">
                  <select
                    aria-label="Plant link source"
                    value={linkSource}
                    onChange={(e) => setLinkSource(e.target.value)}
                  >
                    <option value="">Select exact Output…</option>
                    {ports
                      .filter((p) => p.signal.direction === "output")
                      .map((p) => (
                        <option
                          key={endpointKey(p.endpoint)}
                          value={endpointKey(p.endpoint)}
                        >
                          {portLabel(p)}
                        </option>
                      ))}
                  </select>
                  <select
                    aria-label="Plant link target"
                    value={linkTarget}
                    onChange={(e) => setLinkTarget(e.target.value)}
                  >
                    <option value="">Select exact Input…</option>
                    {ports
                      .filter((p) => p.signal.direction === "input")
                      .map((p) => (
                        <option
                          key={endpointKey(p.endpoint)}
                          value={endpointKey(p.endpoint)}
                        >
                          {portLabel(p)}
                        </option>
                      ))}
                  </select>
                  <button
                    disabled={
                      !linkSource || !linkTarget || plan.links.length >= 1024
                    }
                    onClick={() => {
                      const src = ports.find(
                          (p) => endpointKey(p.endpoint) === linkSource,
                        ),
                        dst = ports.find(
                          (p) => endpointKey(p.endpoint) === linkTarget,
                        );
                      if (!src || !dst) return;
                      edit({
                        ...plan,
                        links: [
                          ...plan.links,
                          {
                            id: nextKey("link", plan.links),
                            source: src.endpoint,
                            target: dst.endpoint,
                          },
                        ],
                      });
                      setLinkSource("");
                      setLinkTarget("");
                    }}
                  >
                    Add explicit plant link
                  </button>
                </div>
                {plan.links.map((l) => (
                  <p key={l.id}>
                    {l.id}: {l.source.instance_id}/{l.source.node_id} →{" "}
                    {l.target.instance_id}/{l.target.node_id}{" "}
                    <button
                      onClick={() =>
                        edit({
                          ...plan,
                          links: plan.links.filter((row) => row.id !== l.id),
                        })
                      }
                    >
                      Remove plant link {l.id}
                    </button>
                  </p>
                ))}
                <button
                  disabled={
                    !!busy || !plan.hosts.length || !plan.instances.length
                  }
                  onClick={() =>
                    void task(
                      "Reviewing declared plant schedule",
                      async (valid) => {
                        const value = reviewResult(
                          await api(BASE + "/review", {
                            profile_sha256: profile.profile.sha256,
                            plan,
                          }),
                          profile.profile.sha256,
                          plan,
                        );
                        if (valid()) {
                          setReview(value);
                          setReviewKey(now.current);
                        }
                      },
                    )
                  }
                >
                  Review plant I/O and network schedule
                </button>
                {reviewed && (
                  <div aria-label="Reviewed plant engineering schedule">
                    <h4>
                      {review.analysis.status === "software_consistent"
                        ? "Software-consistent declarations; hardware remains unverified"
                        : "Unresolved plant declarations"}
                    </h4>
                    <p>
                      {review.analysis.errors} errors ·{" "}
                      {review.analysis.warnings} warnings · review {review.id}
                    </p>
                    <p>
                      Exact plan hash: <code>{review.plan_sha256}</code>.
                      Hardware and native mapping verified: false.
                    </p>
                    <div className="button-row wrap">
                      <button
                        disabled={!!busy}
                        onClick={() => void exportReview("json")}
                      >
                        Export sealed plant review JSON
                      </button>
                      <button
                        disabled={!!busy}
                        onClick={() => void exportReview("csv")}
                      >
                        Export plant I/O and network CSV
                      </button>
                      <button
                        disabled={!!busy}
                        onClick={() =>
                          void task("Saving plant capture", async (valid) => {
                            const value = captureResult(
                              await api(BASE + "/captures/save", {
                                id: review.id,
                                content_sha256: review.content_sha256,
                              }),
                            );
                            if (
                              value.report_id !== review.id ||
                              value.content_sha256 !== review.content_sha256
                            )
                              throw new Error(
                                "Saved capture does not bind the selected review.",
                              );
                            if (valid()) {
                              setDirty(false);
                              setNotice(
                                "Sealed plant capture saved locally. No field operations occurred.",
                              );
                              await refresh(valid);
                            }
                          })
                        }
                      >
                        Save reviewed plant capture locally
                      </button>
                    </div>
                    <table aria-label="Reviewed plant I/O schedule">
                      <thead>
                        <tr>
                          <th>Instance / host / node</th>
                          <th>Role / terminal</th>
                          <th>Native mapping</th>
                        </tr>
                      </thead>
                      <tbody>
                        {review.analysis.io_schedule.map(
                          (r: any, n: number) => (
                            <tr key={n}>
                              <td>
                                {r.instance_id} / {r.host_id} / {r.node_id} ·{" "}
                                {r.label}
                              </td>
                              <td>
                                {r.role} · {r.terminal_key || "undeclared"}
                              </td>
                              <td>
                                Unverified · <code>{r.canonical_sha256}</code>
                              </td>
                            </tr>
                          ),
                        )}
                      </tbody>
                    </table>
                    <table aria-label="Reviewed plant network schedule">
                      <thead>
                        <tr>
                          <th>Link / exact endpoints</th>
                          <th>Result / fanout</th>
                          <th>Findings</th>
                        </tr>
                      </thead>
                      <tbody>
                        {review.analysis.network_schedule.map((r: any) => (
                          <tr key={r.id}>
                            <td>
                              {r.id}: {r.source.instance_id}/{r.source.node_id}{" "}
                              → {r.target.instance_id}/{r.target.node_id}
                            </td>
                            <td>
                              {r.status} · fanout {r.fanout}
                            </td>
                            <td>
                              {r.findings.join(", ") ||
                                "No software mapping finding; native mapping unverified"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {review.analysis.diagnostics.map((r: any, i: number) => (
                      <p key={i}>
                        {r.severity} · {r.code}: {r.message}
                        {r.instance_id
                          ? ` (${r.instance_id}${r.node_id ? "/" + r.node_id : ""})`
                          : r.link_id
                            ? ` (${r.link_id})`
                            : ""}
                      </p>
                    ))}
                    <HydronicIOPlanner
                      key={review.content_sha256}
                      plantReview={review}
                    />
                  </div>
                )}
                <h4>Durable local plant captures</h4>
                <p>
                  Import retains a verified archive; Open explicitly replaces
                  the current declaration and restores its exact sources. No
                  automatic source binding or field access.
                </p>
                <button
                  disabled={!!busy}
                  onClick={() => captureFile.current?.click()}
                >
                  Import sealed plant capture
                </button>
                <input
                  ref={captureFile}
                  type="file"
                  hidden
                  accept=".json"
                  aria-label="Sealed plant capture file"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    e.target.value = "";
                    if (file)
                      void task(
                        "Importing sealed plant capture",
                        async (valid) => {
                          if (!file.size || file.size > 8388608)
                            throw new Error(
                              "Plant capture requires 1..8388608 bytes.",
                            );
                          const data = new FormData();
                          data.append("file", file);
                          captureResult(
                            await api(BASE + "/captures/import", data),
                          );
                          if (valid()) {
                            await refresh(valid);
                            setNotice(
                              "Capture retained. Open it below to select its declaration and source bindings.",
                            );
                          }
                        },
                      );
                  }}
                />
                <table aria-label="Saved plant captures">
                  <thead>
                    <tr>
                      <th>Capture</th>
                      <th>Provenance</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {profile.captures.map((c: any) => (
                      <tr key={c.id}>
                        <td>
                          {c.name}
                          <br />
                          <code>{c.id}</code>
                        </td>
                        <td>
                          {c.origin} · {c.ingested_at} · {c.bytes} bytes
                        </td>
                        <td>
                          <button
                            disabled={!!busy}
                            onClick={() => {
                              if (
                                dirty &&
                                !window.confirm(
                                  "Replace current plant declarations with this saved capture? Unexported changes will be discarded.",
                                )
                              )
                                return;
                              void task(
                                "Opening saved plant capture",
                                async (valid) => {
                                  const value = await api(
                                    BASE + "/captures/open",
                                    { id: c.id },
                                  );
                                  const summary = captureResult(value.capture),
                                    report = reviewResult(
                                      value.review,
                                      profile.profile.sha256,
                                    );
                                  if (
                                    summary.id !== c.id ||
                                    summary.report_id !== report.id ||
                                    summary.content_sha256 !==
                                      report.content_sha256
                                  )
                                    throw new Error(
                                      "Opened capture identity does not match its sealed review.",
                                    );
                                  if (valid()) {
                                    const nextProfile = {
                                      ...profile,
                                      sources: [
                                        ...profile.sources.filter(
                                          (s: Source) =>
                                            !report.sources.some(
                                              (r: Source) => r.id === s.id,
                                            ),
                                        ),
                                        ...report.sources,
                                      ],
                                    };
                                    profileResult(nextProfile);
                                    setProfile(nextProfile);
                                    setPlan(report.plan);
                                    setReview(report);
                                    setReviewKey(
                                      stable([
                                        report.plan,
                                        currentSource,
                                        profile.profile.sha256,
                                      ]),
                                    );
                                    setDirty(false);
                                    setLinkSource("");
                                    setLinkTarget("");
                                    setNotice(
                                      "Saved declaration opened with exact source identities. Hardware and native allocation remain unverified.",
                                    );
                                  }
                                },
                              );
                            }}
                          >
                            Open plant capture {c.id.slice(0, 8)}
                          </button>
                          {(["json", "csv"] as const).map((kind) => (
                            <button
                              key={kind}
                              disabled={!!busy}
                              onClick={() =>
                                void task(
                                  "Exporting original plant capture",
                                  (valid) =>
                                    download(
                                      BASE + "/captures/export/" + kind,
                                      { id: c.id },
                                      `plant-capture-${c.id}.${kind}`,
                                      valid,
                                    ).then(() => {}),
                                )
                              }
                            >
                              Export capture {kind.toUpperCase()}{" "}
                              {c.id.slice(0, 8)}
                            </button>
                          ))}
                          <button
                            disabled={!!busy}
                            onClick={() => {
                              if (
                                window.confirm(
                                  "Delete this selected local plant capture? Export it first if needed; no other capture or field device is changed.",
                                )
                              )
                                void task(
                                  "Deleting selected plant capture",
                                  async (valid) => {
                                    const value = await api(
                                      BASE + "/captures/remove",
                                      { id: c.id },
                                    );
                                    if (
                                      value.removed !== c.id ||
                                      value.field_queries !== false
                                    )
                                      throw new Error(
                                        "Capture removal reply does not match.",
                                      );
                                    if (valid()) await refresh(valid);
                                  },
                                );
                            }}
                          >
                            Delete plant capture {c.id.slice(0, 8)}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </>
        )}
      </div>
    </section>
  );
}
