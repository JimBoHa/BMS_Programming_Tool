import { useEffect, useRef, useState } from "react";
import {
  api,
  apiBlobDocument,
  apiJsonDocument,
  apiKeepalive,
  saveBlob,
} from "./api";
import { controllerKey, type ControllerContext } from "./workflow";
import { NativeRuntimeCalibration } from "./NativeRuntimeCalibration";
import { NativeRuntimeParametersNotice } from "./NativeRuntimeParametersNotice";
import { NativeTerminalCopy } from "./NativeTerminalCopy";
import {
  inputTransferProfile,
  terminalTransferReview,
} from "./nativeTerminalTransferContract";

const base = "/bacnet/controller/native-application";
const profile = "native-local-universal-input-transfer/1";
const drafts = new Map<string, Work>();
type Work = { source: any; form: Form; receipt: any };
type Form = {
  action: string;
  object: string;
  slot: string;
  name: string;
  mode: string;
  input_low: string;
  input_high: string;
  output_low: string;
  output_high: string;
  units: string;
  minimum: string;
  maximum: string;
  origin: string;
};
const blank = (): Form => ({
  action: "allocate",
  object: "",
  slot: "1",
  name: "",
  mode: "voltage",
  input_low: "0",
  input_high: "10",
  output_low: "0",
  output_high: "100",
  units: "98",
  minimum: "0",
  maximum: "100",
  origin: "",
});
const canonical = (v: any): string =>
  JSON.stringify(v, (_k, x) =>
    x && typeof x === "object" && !Array.isArray(x)
      ? Object.fromEntries(
          Object.keys(x)
            .sort()
            .map((k) => [k, x[k]]),
        )
      : x,
  );
const same = (a: any, b: any) => canonical(a) === canonical(b);

export function NativeInputs({
  controller,
  connected,
  onBusy,
  onVerified,
}: {
  controller: ControllerContext | null;
  connected: boolean;
  onBusy: (v: boolean) => void;
  onVerified: () => void;
}) {
  const owner = controller
    ? JSON.stringify([controllerKey(controller), controller.interfaceKey])
    : "offline-native-input-copy";
  const [work, setWork] = useState<Work>(
    () => drafts.get(owner) ?? { source: null, form: blank(), receipt: null },
  );
  const [sources, setSources] = useState<any[]>([]),
    [status, setStatus] = useState<any>(null);
  const [review, setReview] = useState<any>(null),
    [copyReview, setCopyReview] = useState<any>(null);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [wiring, setWiring] = useState(false),
    [input, setInput] = useState(false),
    [transfer, setTransfer] = useState(false);
  const [now, setNow] = useState(Date.now());
  const epoch = useRef(0),
    previousConnected = useRef(connected),
    mounted = useRef(true),
    active = useRef<string | null>(null),
    planOperation = useRef<string | null>(null);
  const target = {
    address: controller?.address,
    device: controller?.device,
    router: controller?.router || null,
    dnet: controller?.dnet ?? null,
  };
  const matchesTarget = (v: any) =>
    v?.address === target.address &&
    (v.router || null) === target.router &&
    (v.dnet ?? null) === target.dnet;
  const current = (e: number) => mounted.current && e === epoch.current;
  const capacity = () => drafts.has(owner) || drafts.size < 32;
  function retire() {
    if (planOperation.current)
      void apiKeepalive(base + "/cancel", {
        operation_id: planOperation.current,
      }).catch(() => {});
    planOperation.current = null;
    setReview(null);
    setWiring(false);
    setInput(false);
    setTransfer(false);
  }
  async function refresh(e: number) {
    const [s, records] = await Promise.all([
      api(base + "/input/sources"),
      api(base + "/status"),
    ]);
    if (current(e)) {
      setSources(s.sources);
      setStatus(records);
    }
  }
  useEffect(() => {
    mounted.current = true;
    void refresh(epoch.current).catch((e) => setError(String(e)));
    const leave = () => {
      epoch.current++;
      retire();
      if (active.current)
        void apiKeepalive(base + "/cancel", {
          operation_id: active.current,
        }).catch(() => {});
    };
    document.addEventListener("visibilitychange", leave);
    window.addEventListener("pagehide", leave);
    return () => {
      mounted.current = false;
      leave();
      document.removeEventListener("visibilitychange", leave);
      window.removeEventListener("pagehide", leave);
      onBusy(false);
    };
  }, []);
  useEffect(() => {
    if (!work.source && same(work.form, blank())) drafts.delete(owner);
    else if (capacity()) drafts.set(owner, work);
    else
      setError(
        "Input work is full (32 controllers). Save or discard an earlier local draft first. Receipts remain in History.",
      );
  }, [work, owner]);
  useEffect(() => {
    if (previousConnected.current && !connected) {
      epoch.current++;
      retire();
      if (active.current)
        void apiKeepalive(base + "/cancel", {
          operation_id: active.current,
        }).catch(() => {});
    }
    previousConnected.current = connected;
  }, [connected]);
  useEffect(() => {
    if (!review) return;
    const expires = Date.parse(review.expires_at);
    const expire = () => {
      epoch.current++;
      retire();
      setError("Input review expired. Review this change again.");
    };
    const t = window.setInterval(() => {
      const time = Date.now();
      if (time >= expires) expire();
      else setNow(time);
    }, 1000);
    const deadline = window.setTimeout(
      expire,
      Math.max(0, expires - Date.now()),
    );
    return () => {
      clearInterval(t);
      clearTimeout(deadline);
    };
  }, [review]);
  const source = work.source,
    form = work.form;
  const field = source?.inputs.find((r: any) => r.object_id === form.object);
  const sourceArgs = source && {
    capture_id: source.capture_id,
    snapshot_sha256: source.snapshot_sha256,
  };
  const fieldAllowed =
    connected &&
    matchesTarget(source?.target) &&
    source?.identity?.device === controller?.device;
  const fresh = review && Date.parse(review.expires_at) > now && fieldAllowed;
  function update(patch: Partial<Form>) {
    if (!capacity()) {
      setError(
        "Input work is full. Save or discard an earlier local draft first.",
      );
      return;
    }
    epoch.current++;
    retire();
    setCopyReview(null);
    setWork((w) => ({ ...w, form: { ...w.form, ...patch } }));
  }
  function edit() {
    const number = (key: keyof Form) => {
      const text = form[key].trim();
      const value = Number(text);
      if (!text || !Number.isFinite(value))
        throw new Error(`Enter a finite ${key.replaceAll("_", " ")}.`);
      return value;
    };
    if (form.action !== "allocate" && !field)
      throw new Error("Select an actual configured local input.");
    const result: any = {
      configuration_sha256: null,
      name: null,
      configuration: null,
      allocation_receipt: null,
      action: form.action,
      object_instance:
        form.action === "allocate"
          ? number("object")
          : Number(form.object.split(",")[1]),
      slot: ["allocate", "terminal"].includes(form.action)
        ? number("slot")
        : field.slot,
    };
    if (form.action === "allocate") result.name = form.name;
    else result.configuration_sha256 = field.configuration_sha256;
    if (form.action === "remove-allocated")
      result.allocation_receipt = form.origin;
    else if (form.action !== "terminal")
      result.configuration = {
        mode: form.mode,
        ...Object.fromEntries(
          [
            "input_low",
            "input_high",
            "output_low",
            "output_high",
            "units",
            "minimum",
            "maximum",
          ].map((k) => [k, number(k as keyof Form)]),
        ),
      };
    return result;
  }
  function sourceMatches(value: any, expected: any, expectedProfile = profile) {
    return (
      value.profile === expectedProfile &&
      value.capture_id === expected.capture_id &&
      value.snapshot_sha256 === expected.snapshot_sha256
    );
  }
  function receiptMatches(r: any) {
    return (
      r?.intent?.change_kind === "input" &&
      ["allocate", "mode", "remove-allocated", "terminal"].includes(
        r.intent.input_edit?.action,
      ) &&
      r.intent.operation_profile ===
        inputTransferProfile(r.intent.input_edit) &&
      matchesTarget(r.intent.target) &&
      r.intent.identity?.device === controller?.device &&
      /^[a-f0-9]{32}$/.test(r.intent.id)
    );
  }
  async function run(kind: string, id?: string) {
    if (busy) return;
    if (
      work.source &&
      !same(work.form, blank()) &&
      ((kind === "source" && id !== work.source.capture_id) ||
        (kind === "capture" &&
          (!matchesTarget(work.source.target) ||
            work.source.identity?.device !== controller?.device)))
    ) {
      setError(
        "Discard the local input draft before opening a different source. Save a native copy first if needed; existing work was kept.",
      );
      return;
    }
    if (
      ["capture", "review", "apply", "readback"].includes(kind) &&
      (!controller || !connected)
    ) {
      setError(
        "Open the exact captured controller and interface for a field operation.",
      );
      return;
    }
    if (!capacity() && !["retained", "readback"].includes(kind)) {
      setError(
        "Input work is full. Save or discard an earlier local draft first.",
      );
      return;
    }
    const e = ++epoch.current,
      operation_id = crypto.randomUUID();
    active.current = operation_id;
    setBusy(true);
    onBusy(true);
    setError("");
    try {
      if (kind === "capture" || kind === "source") {
        retire();
        setCopyReview(null);
        let expected: any;
        if (kind === "capture") {
          const c = await api(base + "/capture", { ...target, operation_id });
          if (!current(e)) return;
          if (
            !c.source_identity_matches ||
            !matchesTarget(c.target) ||
            c.device !== controller?.device
          )
            throw new Error(
              "Capture identity differs from the selected controller.",
            );
          expected = {
            capture_id: c.id,
            snapshot_sha256: c.snapshot_evidence_sha256,
          };
        } else {
          const c = sources.find((s) => s.capture_id === id);
          if (!c) throw new Error("Reopen the native source list.");
          expected = {
            capture_id: c.capture_id,
            snapshot_sha256: c.snapshot_sha256,
          };
        }
        let s = await api(base + "/input/source", expected);
        if (!current(e)) return;
        if (!sourceMatches(s, expected))
          throw new Error(
            "Input source differs from the requested retained capture.",
          );
        if (kind === "capture") {
          s = await api(base + "/input/support", {
            ...target,
            ...expected,
            operation_id: crypto.randomUUID(),
          });
          if (!current(e)) return;
          if (
            !sourceMatches(s, expected) ||
            !matchesTarget(s.target) ||
            s.identity?.device !== controller?.device
          )
            throw new Error("Live input support differs from this controller.");
        }
        setWork((w) => ({
          ...w,
          source: s,
          form: {
            ...w.form,
            slot: String(s.available_slots[0] ?? ""),
            ...(w.form.action === "allocate" &&
            !w.form.object &&
            s.next_available_instance != null
              ? { object: String(s.next_available_instance) }
              : {}),
          },
        }));
      } else if (kind === "local" || kind === "review" || kind === "save") {
        const proposed = edit();
        if (kind === "save") {
          if (!copyReview || !same(copyReview.edit, proposed))
            throw new Error("Review the local copy again.");
          const document = await apiBlobDocument(base + "/input/copy/export", {
            ...sourceArgs,
            edit: proposed,
            expected_review_sha256: copyReview.review_sha256,
          });
          const digest = Array.from(
            new Uint8Array(
              await crypto.subtle.digest(
                "SHA-256",
                await document.blob.arrayBuffer(),
              ),
            ),
          )
            .map((b) => b.toString(16).padStart(2, "0"))
            .join("");
          if (digest !== copyReview.output_sha256)
            throw new Error(
              "Saved native copy differs from the reviewed application bytes.",
            );
          if (current(e)) saveBlob(document.blob, "native-input-copy.moi");
        } else {
          retire();
          const path =
            base +
            (kind === "local" ? "/input/copy/preview" : "/input/preview");
          const request = {
            ...sourceArgs,
            edit: proposed,
            ...(kind === "review" ? { ...target, operation_id } : {}),
          };
          const document =
            proposed.action === "terminal"
              ? await apiJsonDocument(path, request)
              : null;
          const r = document ? document.data : await api(path, request);
          if (!current(e)) {
            if (kind === "review")
              void apiKeepalive(base + "/cancel", { operation_id }).catch(
                () => {},
              );
            return;
          }
          if (kind === "local") {
            if (
              !sourceMatches(r, sourceArgs, inputTransferProfile(proposed)) ||
              !same(r.edit, proposed) ||
              r.controller_queries !== false ||
              r.controller_writes !== false ||
              !/^[a-f0-9]{64}$/.test(r.review_sha256)
            )
              throw new Error("Local copy review differs from this draft.");
            if (
              document &&
              !(await terminalTransferReview(document, source, proposed, false))
            )
              throw new Error(
                "Local terminal copy proof differs from this exact source and move.",
              );
            if (!current(e)) return;
            setCopyReview(r);
          } else {
            planOperation.current = operation_id;
            if (
              r.profile !== "native-application-transfer/1" ||
              r.operation_profile !== inputTransferProfile(proposed) ||
              r.operation_id !== operation_id ||
              r.change_kind !== "input" ||
              !matchesTarget(r.target) ||
              r.identity?.device !== controller?.device ||
              r.capture_id !== source.capture_id ||
              r.snapshot_sha256 !== source.snapshot_sha256 ||
              !same(r.input_edit, {
                configuration_sha256: null,
                name: null,
                configuration: null,
                allocation_receipt: null,
                ...proposed,
              }) ||
              r.can_apply !== true ||
              !/^[A-Za-z0-9_-]{32}$/.test(r.token) ||
              !/^[a-f0-9]{64}$/.test(r.review_sha256) ||
              !(Date.parse(r.expires_at) > Date.now())
            ) {
              retire();
              throw new Error(
                "Controller input review differs from this draft.",
              );
            }
            if (
              document &&
              !(await terminalTransferReview(document, source, proposed, true))
            ) {
              retire();
              throw new Error(
                "Terminal transfer proof differs from this exact source and move.",
              );
            }
            if (!current(e)) {
              void apiKeepalive(base + "/cancel", { operation_id }).catch(
                () => {},
              );
              return;
            }
            setReview(r);
            setNow(Date.now());
          }
        }
      } else {
        const plan = review,
          prior = work.receipt?.intent;
        if (kind === "apply" && (!fresh || !wiring || !input || !transfer))
          throw new Error("Review and confirm the input change again.");
        if (kind === "apply") {
          planOperation.current = null;
          retire();
        }
        const r =
          kind === "retained"
            ? await api(base + "/receipts/" + id)
            : await api(
                base + (kind === "apply" ? "/input/apply" : "/readback"),
                kind === "apply"
                  ? {
                      operation_id,
                      token: plan.token,
                      review_sha256: plan.review_sha256,
                      physical_wiring_confirmed: wiring,
                      input_change_confirmed: input,
                      application_transfer_confirmed: transfer,
                    }
                  : { operation_id, receipt_id: prior.id },
              );
        if (!current(e)) return;
        if (
          r.intent &&
          (!receiptMatches(r) ||
            (kind === "apply"
              ? r.intent.operation_id !== operation_id ||
                r.intent.review_sha256 !== plan.review_sha256 ||
                r.intent.review_capture_id !== plan.capture_id ||
                !same(r.intent.input_edit, plan.input_edit)
              : kind === "readback" &&
                (r.intent.id !== prior.id ||
                  r.intent.evidence_sha256 !== prior.evidence_sha256)))
        )
          throw new Error(
            "Input receipt differs from this operation. Open the original retained transfer for readback.",
          );
        if (
          !r.intent &&
          !(
            kind === "apply" &&
            r.pending === false &&
            r.result?.status === "not_sent"
          )
        )
          throw new Error(
            "No attributable input transfer receipt was returned.",
          );
        setWork((w) => ({ ...w, receipt: r }));
        if (
          kind !== "retained" &&
          r.intent &&
          !r.pending &&
          ["verified", "recovered_original"].includes(
            (r.latest_readback || r.result)?.status,
          )
        )
          onVerified();
      }
    } catch (failure) {
      if (kind === "review")
        void apiKeepalive(base + "/cancel", { operation_id }).catch(() => {});
      if (current(e)) setError(String(failure));
    } finally {
      if (active.current === operation_id) active.current = null;
      if (mounted.current) {
        await refresh(epoch.current).catch(() => {});
        setBusy(false);
        onBusy(false);
      }
    }
  }
  const records =
    status?.receipts?.filter(
      (r: any) =>
        r.change_kind === "input" &&
        matchesTarget(r.target) &&
        r.identity?.device === controller?.device,
    ) ?? [];
  const observed = work.receipt?.latest_readback || work.receipt?.result;
  const numeric = [
    ["input_low", "Electrical range low"],
    ["input_high", "Electrical range high"],
    ["output_low", "Engineering range low"],
    ["output_high", "Engineering range high"],
    ["units", "Engineering unit code"],
    ["minimum", "Minimum present value"],
    ["maximum", "Maximum present value"],
  ];
  return (
    <section aria-label="Native input configuration">
      <h3>Input allocation & electrical modes</h3>
      {controller ? (
        <p>
          Capture the controller’s native application, select a configured input
          or a spare local terminal, then review one change. Applying transfers
          the application and can restart control.
        </p>
      ) : (
        <p>
          No controller selected. Open a retained native application to edit and
          save a local copy. Its source remains separate from the open CAF.
        </p>
      )}
      {controller && (
        <p>
          <strong>Selected controller:</strong> {controller.name} ·{" "}
          {controller.device} · {controller.router || controller.address} /
          network {controller.dnet ?? "local"} / station {controller.address}
        </p>
      )}
      <div className="button-row">
        <button
          disabled={!connected || busy || !status?.credentials_configured}
          onClick={() => void run("capture")}
        >
          Capture native inputs
        </button>
        <label>
          Retained native source
          <select
            aria-label="Retained native input source"
            disabled={busy}
            value={source?.capture_id || ""}
            onChange={(e) => {
              if (e.target.value) void run("source", e.target.value);
            }}
          >
            <option value="">Select a captured application</option>
            {sources.map((s) => (
              <option key={s.capture_id} value={s.capture_id}>
                {s.identity["object-name"]} · {s.identity.device} ·{" "}
                {s.captured_at}
              </option>
            ))}
          </select>
        </label>
      </div>
      {!status?.credentials_configured && (
        <p>
          Configure native backup/restore credentials in Settings before
          capturing or transferring. Retained copies remain available offline.
        </p>
      )}
      {error && (
        <p role="alert" className="inline-error">
          {error}
        </p>
      )}
      {busy && (
        <p role="status">Working on the selected native input operation…</p>
      )}
      {source && (
        <>
          <p>
            <strong>Captured source:</strong> {source.identity["object-name"]} ·{" "}
            {source.identity.device} ·{" "}
            {source.target.router || source.target.address} / network{" "}
            {source.target.dnet ?? "local"} / station {source.target.address}.
            Native format {source.format_versions.acs}/
            {source.format_versions.dmcs}. This is captured configuration;
            terminal wiring requires field confirmation.
          </p>
          {!fieldAllowed && (
            <p>
              Local editing and Save native copy are available. Open the exact
              captured controller and interface for a field review.
            </p>
          )}
          <p>
            Available local terminals:{" "}
            {source.available_slots
              .map((n: number) => `UI IN${n}`)
              .join(", ") || "None"}
            . Integral sensors and SA module allocations are excluded from this
            profile.
          </p>
          <fieldset disabled={busy}>
            <legend>Edit one input</legend>
            <label>
              Input operation
              <select
                aria-label="Input operation"
                value={form.action}
                onChange={(e) => update({ action: e.target.value, object: "" })}
              >
                <option value="allocate">Allocate a spare local input</option>
                <option value="mode">Edit a configured input</option>
                <option value="terminal">Move a configured analog input</option>
                <option value="remove-allocated">
                  Remove an input allocated by this app
                </option>
              </select>
            </label>
            {form.action === "allocate" ? (
              <div className="button-row">
                <label>
                  Terminal
                  <select
                    aria-label="Native input terminal"
                    value={form.slot}
                    onChange={(e) => update({ slot: e.target.value })}
                  >
                    <option value="">Select</option>
                    {source.available_slots.map((n: number) => (
                      <option key={n} value={n}>
                        UI IN{n}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Object instance
                  <input
                    aria-label="Native input object instance"
                    value={form.object}
                    onChange={(e) => update({ object: e.target.value })}
                  />
                </label>
                <label>
                  Input name
                  <input
                    aria-label="Native input name"
                    value={form.name}
                    onChange={(e) => update({ name: e.target.value })}
                  />
                </label>
              </div>
            ) : (
              <label>
                Configured local input
                <select
                  aria-label="Configured native input"
                  value={form.object}
                  onChange={(e) => {
                    const p = source.inputs.find(
                        (r: any) => r.object_id === e.target.value,
                      ),
                      c = p?.configuration;
                    update({
                      object: e.target.value,
                      ...(c
                        ? {
                            mode:
                              Object.keys(source.hardware.modes).find(
                                (k) =>
                                  source.hardware.modes[k].setup === c.setup,
                              ) || "voltage",
                            ...Object.fromEntries(
                              numeric.map(([k]) => [
                                k,
                                c[k] == null
                                  ? blank()[k as keyof Form]
                                  : String(c[k]),
                              ]),
                            ),
                          }
                        : {}),
                    });
                  }}
                >
                  <option value="">Select</option>
                  {source.inputs.map((p: any) => (
                    <option key={p.object_id} value={p.object_id}>
                      {p.name} · UI IN{p.slot} · {p.object_id}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {field && (
              <details>
                <summary>Captured input configuration</summary>
                <pre>{JSON.stringify(field.configuration, null, 2)}</pre>
              </details>
            )}
            {form.action === "terminal" ? (
              <>
                <p>
                  Move this existing analog input from{" "}
                  {field ? `UI IN${field.slot}` : "its captured terminal"}.
                  Electrical mode, scaling, identity and program connections
                  stay unchanged. Integral sensors, SA/cross-host and dedicated
                  binary terminals are excluded.
                </p>
                <label>
                  Destination universal terminal
                  <select
                    aria-label="Field terminal destination"
                    value={form.slot}
                    onChange={(e) => update({ slot: e.target.value })}
                  >
                    <option value="">Select a configured free terminal</option>
                    {source.available_slots.map((n: number) => (
                      <option key={n} value={n}>
                        UI IN{n}
                      </option>
                    ))}
                  </select>
                </label>
              </>
            ) : form.action === "remove-allocated" ? (
              <label>
                Original verified allocation receipt
                <select
                  aria-label="Input allocation origin"
                  value={form.origin}
                  onChange={(e) => update({ origin: e.target.value })}
                >
                  <option value="">Select original allocation</option>
                  {records
                    .filter(
                      (r: any) =>
                        r.input_edit?.action === "allocate" &&
                        r.status === "verified" &&
                        !r.pending,
                    )
                    .map((r: any) => (
                      <option key={r.id} value={r.id}>
                        {r.input_edit.name} · {r.created_at} · {r.id}
                      </option>
                    ))}
                </select>
              </label>
            ) : (
              <>
                <label>
                  Electrical mode
                  <select
                    aria-label="Native input electrical mode"
                    value={form.mode}
                    onChange={(e) => {
                      const m = source.hardware.modes[e.target.value];
                      update({
                        mode: e.target.value,
                        input_low: String(m.low),
                        input_high: String(m.high),
                      });
                    }}
                  >
                    {Object.entries(source.hardware.modes).map(
                      ([k, m]: [string, any]) => (
                        <option key={k} value={k}>
                          {m.label}
                        </option>
                      ),
                    )}
                  </select>
                </label>
                <div className="workflow-identity-grid">
                  {numeric.map(([key, label]) => (
                    <label key={key}>
                      {label}
                      <input
                        aria-label={label}
                        value={form[key as keyof Form]}
                        onChange={(e) => update({ [key]: e.target.value })}
                      />
                    </label>
                  ))}
                </div>
                <p>
                  Scaling maps the electrical range into engineering units. Use
                  native unit codes (98 = percent, 64 = °F, 62 = °C). The
                  reviewed values show native Real32 rounding.
                </p>
              </>
            )}
          </fieldset>
          <div className="button-row">
            <button
              className={!fieldAllowed && !copyReview ? "primary" : ""}
              disabled={busy}
              onClick={() => void run("local")}
            >
              Review local input copy
            </button>
            <button
              className={!fieldAllowed && copyReview ? "primary" : ""}
              disabled={busy || !copyReview}
              onClick={() => void run("save")}
            >
              Save native copy
            </button>
            <button
              className={fieldAllowed && !review ? "primary" : ""}
              disabled={
                busy || !fieldAllowed || !status?.credentials_configured
              }
              onClick={() => void run("review")}
            >
              Review controller input change
            </button>
          </div>
          {copyReview && (
            <p role="status">
              Local copy reviewed. Saving creates a separate native application
              file and does not write a controller.
            </p>
          )}
          {review && (
            <section aria-label="Input change review">
              <h4>Review input change</h4>
              <NativeRuntimeParametersNotice
                parameters={review.compilation.parameter_merge}
              />
              <p>
                Controller: {review.identity["object-name"]} ·{" "}
                {review.identity.device}. Action: {review.input_edit.action} ·
                UI IN{review.input_edit.slot} · analog-input,
                {review.input_edit.object_instance}.
              </p>
              {review.input_edit.action === "terminal" && (
                <p>
                  Move analog-input,{review.input_edit.object_instance} from UI
                  IN{review.compilation.terminal_compilation.old_slot} to UI IN
                  {review.input_edit.slot}. Preserve electrical mode, scaling,
                  identity and program connections. Applying transfers the
                  native application and may restart control.
                </p>
              )}
              <pre>
                {JSON.stringify(
                  review.compilation.stored_configuration || review.input_edit,
                  null,
                  2,
                )}
              </pre>
              <details>
                <summary>Exact native changes and preservation</summary>
                <pre>{JSON.stringify(review.compilation, null, 2)}</pre>
              </details>
              <label>
                <input
                  type="checkbox"
                  checked={wiring}
                  onChange={(e) => setWiring(e.target.checked)}
                />{" "}
                Wiring, sensor mode, common and any required jumpers match this
                terminal.
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={input}
                  onChange={(e) => setInput(e.target.checked)}
                />{" "}
                {review.input_edit.action === "terminal"
                  ? "I confirm this input terminal move with unchanged mode and scaling."
                  : "I confirm this input allocation/mode and scaling change."}
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={transfer}
                  onChange={(e) => setTransfer(e.target.checked)}
                />{" "}
                I confirm the application transfer and possible control restart.
              </label>
              <button
                className="primary"
                disabled={busy || !fresh || !wiring || !input || !transfer}
                onClick={() => void run("apply")}
              >
                Apply input change to controller
              </button>
              {!fresh && (
                <p>Review expired or its target changed. Review again.</p>
              )}
            </section>
          )}
          <button
            disabled={busy}
            onClick={() => {
              epoch.current++;
              retire();
              setCopyReview(null);
              setWork((w) => ({ ...w, source: null, form: blank() }));
            }}
          >
            Discard local input draft
          </button>
        </>
      )}
      <NativeTerminalCopy
        controller={controller}
        connected={connected}
        fieldBusy={busy}
      />
      <details>
        <summary>Retained input transfers</summary>
        {records.map((r: any) => (
          <p key={r.id}>
            {r.input_edit?.action} · {r.status} · {r.created_at}{" "}
            <button disabled={busy} onClick={() => void run("retained", r.id)}>
              Open input receipt {r.id.slice(0, 8)}
            </button>
          </p>
        ))}
      </details>
      {work.receipt && (
        <section aria-label="Input transfer result">
          <h4>
            {busy ? "Earlier input transfer" : "Input transfer"}:{" "}
            {observed?.status || "unknown"}
          </h4>
          <p>
            Receipt {work.receipt.intent?.id || "not sent"} ·{" "}
            {work.receipt.intent?.created_at || "No durable dispatch"}
          </p>
          <p>{observed?.error || observed?.errors?.join(" ")}</p>
          {work.receipt.intent && (
            <button
              disabled={busy || !connected}
              onClick={() => void run("readback")}
            >
              Read back input transfer
            </button>
          )}
          <details>
            <summary>Published input and preservation evidence</summary>
            <pre>{JSON.stringify(observed, null, 2)}</pre>
          </details>
          <NativeRuntimeCalibration
            report={observed?.runtime_calibration}
            preservation={observed?.preservation}
          />
        </section>
      )}
    </section>
  );
}
