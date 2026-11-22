import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { controllerKey, type ControllerContext } from "./workflow";

const base = "/bacnet/controller/native-application";
const route = base + "/runtime-io";
type Capture = {
  capture_id: string;
  snapshot_sha256: string;
  captured_at: string;
};
type Output = {
  object: string;
  name: string;
  mode: "binary" | "proportional";
  slot: number;
  available_slots: number[];
  terminal_signals?: Record<number, string>;
  unavailable_reason?: string | null;
};
type Receipt = { id: string; status: string; pending: boolean };
type Form = {
  object: string;
  slot: string;
  instance: string;
  name: string;
  move: boolean;
};
type Draft = { capture: Capture; outputs: Output[]; form: Form };
const drafts = new Map<string, Draft>();
const blank: Form = {
  object: "",
  slot: "",
  instance: "",
  name: "",
  move: false,
};

export function NativeOutputPoints({
  controller,
  connected,
  onBusy,
  onVerified,
}: {
  controller: ControllerContext;
  connected: boolean;
  onBusy: (busy: boolean) => void;
  onVerified: () => void;
}) {
  const owner = controllerKey(controller) + controller.interfaceKey;
  const target = {
    address: controller.address,
    device: controller.device,
    router: controller.router || null,
    dnet: controller.dnet ?? null,
  };
  const [draft, setDraft] = useState<Draft | null>(
    () => drafts.get(owner) ?? null,
  );
  const [sources, setSources] = useState<Capture[]>([]);
  const [receipts, setReceipts] = useState<Receipt[]>([]);
  const [chosen, setChosen] = useState(draft?.capture.capture_id || "");
  const [local, setLocal] = useState(false);
  const [plan, setPlan] = useState<{
    token: string;
    review_sha256: string;
    until: number;
  } | null>(null);
  const [wiring, setWiring] = useState(false),
    [transfer, setTransfer] = useState(false);
  const [notice, setNotice] = useState(""),
    [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const epoch = useRef(0),
    running = useRef(false);
  const parent = useRef({ onBusy, onVerified });
  parent.current = { onBusy, onVerified };
  const output = draft?.outputs.find((o) => o.object === draft.form.object);

  function retire() {
    setPlan(null);
    setWiring(false);
    setTransfer(false);
  }
  function save(value: Draft | null) {
    if (value) {
      if (!drafts.has(owner) && drafts.size >= 32)
        throw Error(
          "Discard a saved output draft before opening another controller draft.",
        );
      drafts.set(owner, value);
    } else drafts.delete(owner);
    setDraft(value);
    setLocal(false);
    retire();
    setNotice("");
    setError("");
  }
  function edit(patch: Partial<Form>) {
    if (draft) save({ ...draft, form: { ...draft.form, ...patch } });
  }
  async function catalog(e: number) {
    const result = await api(route + "/output-sources", target);
    if (epoch.current !== e) return;
    setSources(result.sources);
    setReceipts(result.receipts);
    setChosen((current) =>
      result.sources.some((s: Capture) => s.capture_id === current)
        ? current
        : result.sources[0]?.capture_id || "",
    );
  }
  useEffect(() => {
    const e = ++epoch.current;
    setBusy(false);
    retire();
    setLocal(false);
    void catalog(e).catch((f) => {
      if (epoch.current === e) setError(String(f));
    });
    return () => {
      epoch.current++;
      if (running.current) parent.current.onBusy(false);
      running.current = false;
    };
  }, [owner, connected]);
  useEffect(() => {
    if (!plan) return;
    const timer = window.setTimeout(
      () => {
        retire();
        setNotice("Review expired. Review the output change again.");
      },
      Math.max(0, plan.until - Date.now()),
    );
    return () => window.clearTimeout(timer);
  }, [plan]);

  async function action(
    kind: "saved" | "capture" | "local" | "review" | "apply" | "readback",
    receiptId?: string,
  ) {
    if (running.current) return;
    const e = ++epoch.current;
    running.current = true;
    setBusy(true);
    parent.current.onBusy(true);
    setError("");
    setNotice("");
    const current = () => epoch.current === e;
    const operation_id = "output-" + kind + "-" + Date.now().toString(36);
    try {
      if (kind === "saved" || kind === "capture") {
        let capture = sources.find((s) => s.capture_id === chosen);
        if (kind === "capture") {
          const c = await api(base + "/capture", { ...target, operation_id });
          if (!current()) return;
          if (
            controllerKey({ ...c.target, device: c.device }) !==
            controllerKey(controller)
          )
            throw Error("Capture target changed.");
          capture = {
            capture_id: c.id,
            snapshot_sha256: c.snapshot_evidence_sha256,
            captured_at: c.captured_at,
          };
        }
        if (!capture) throw Error("Select a retained controller capture.");
        const q = await api(route + "/outputs", {
          ...target,
          operation_id,
          capture_id: capture.capture_id,
          snapshot_sha256: capture.snapshot_sha256,
        });
        if (!current()) return;
        if (
          q.capture_id !== capture.capture_id ||
          controllerKey({ ...q.target, device: q.identity.device }) !==
            controllerKey(controller)
        )
          throw Error("Output source differs from the selected controller.");
        const first: Output | undefined = q.outputs.find(
          (o: Output) => o.available_slots.length,
        );
        let suggestion: number | null = q.suggested_instance;
        let allocatorMessage = "";
        if (kind === "capture") {
          try {
            const live = await api("/bacnet/controller/properties", {
              ...target,
              object_ids: [controller.device],
              properties: ["787"],
            });
            const point = live.objects?.[0],
              allocator = point?.properties?.["787"];
            if (
              !live.identity_verified ||
              controllerKey(live.target) !== controllerKey(controller) ||
              !point?.identity_verified ||
              point.object !== controller.device ||
              allocator?.status !== "ok" ||
              !Number.isSafeInteger(allocator.value) ||
              allocator.value < 1 ||
              allocator.value > 4194302
            )
              throw Error("The controller allocator could not be verified.");
            if (suggestion !== null)
              suggestion = Math.max(suggestion, allocator.value);
          } catch {
            allocatorMessage =
              "The suggested instance comes from the saved application. Field review will check the controller allocator.";
          }
          if (!current()) return;
        }
        save({
          capture,
          outputs: q.outputs,
          form: {
            ...blank,
            object: first?.object || "",
            slot: String(first?.available_slots[0] ?? ""),
            instance: String(suggestion ?? ""),
          },
        });
        setChosen(capture.capture_id);
        if (allocatorMessage) setNotice(allocatorMessage);
        await catalog(e);
      } else if (kind === "apply" || kind === "readback") {
        if (
          kind === "apply" &&
          (!plan ||
            !connected ||
            !wiring ||
            !transfer ||
            Date.now() >= plan.until)
        )
          throw Error(
            "Review the change and confirm the connected load and transfer.",
          );
        const reviewed = plan;
        retire();
        setLocal(false);
        const r =
          kind === "apply"
            ? await api(route + "/apply", {
                token: reviewed!.token,
                review_sha256: reviewed!.review_sha256,
                local_io_testing_confirmed: true,
                output_wiring_confirmed: wiring,
                application_transfer_confirmed: transfer,
              })
            : await api(route + "/readback", {
                ...target,
                operation_id,
                receipt_id: receiptId,
              });
        if (!current()) return;
        const result = r.latest_readback || r.result;
        if (result?.status === "verified") {
          save(null);
          setNotice(
            "Controller configuration and output readback verified. Refresh the point inventory to command a point.",
          );
          parent.current.onVerified();
        } else
          setNotice(
            [
              result?.status || "Unknown outcome",
              ...(result?.errors || []),
              r.pending
                ? "Read back the retained transfer before further changes."
                : "",
            ]
              .filter(Boolean)
              .join(". "),
          );
        await catalog(e);
      } else {
        if (!draft || !output)
          throw Error("Choose a configured source and free output terminal.");
        const f = draft.form,
          sourceId = Number(output.object.split(",")[1]);
        if (
          !f.move &&
          (!f.name.trim() ||
            !/^\d+$/.test(f.instance) ||
            Number(f.instance) < 1 ||
            Number(f.instance) > 4194302)
        )
          throw Error("Enter a point name and valid unused instance.");
        const args = {
          ...target,
          operation_id,
          capture_id: draft.capture.capture_id,
          snapshot_sha256: draft.capture.snapshot_sha256,
          edit: {
            action: f.move
              ? output.mode + "-output-terminal"
              : "allocate-" + output.mode + "-output",
            expected_slot: output.slot,
            slot: Number(f.slot),
            object_instance: f.move ? sourceId : Number(f.instance),
            ...(f.move
              ? {}
              : { template_instance: sourceId, name: f.name.trim() }),
          },
        };
        const q = await api(
          route + (kind === "local" ? "/source" : "/preview"),
          args,
        );
        if (!current()) return;
        const c = q.compilation?.changes?.[0];
        if (
          c?.after_slot !== args.edit.slot ||
          c?.object !==
            (output.mode === "binary" ? "binary-output," : "analog-output,") +
              args.edit.object_instance ||
          c?.before_slot !== output.slot ||
          c?.operation !== (f.move ? "move" : "allocate")
        )
          throw Error("Returned change differs from the selected output.");
        if (kind === "local") {
          setLocal(true);
          setNotice("Local change checked against the saved application.");
        } else {
          setPlan({
            token: q.token,
            review_sha256: q.review_sha256,
            until: Date.now() + q.expires_seconds * 1000,
          });
          setNotice(
            "Controller identity and output assignment verified for this review.",
          );
        }
      }
    } catch (f) {
      if (current()) {
        retire();
        setError(String(f));
        if (kind === "apply" || kind === "readback") {
          setLocal(false);
          void catalog(e).catch(() => {});
        }
      }
    } finally {
      if (current()) {
        running.current = false;
        setBusy(false);
        parent.current.onBusy(false);
      }
    }
  }
  return (
    <section
      className="native-output-points"
      aria-label="Native output configuration"
    >
      <h3>Configure output points</h3>
      <fieldset disabled={busy}>
        <legend>Controller application</legend>
        <label>
          Saved capture{" "}
          <select
            value={chosen}
            onChange={(e) => {
              setChosen(e.target.value);
              save(null);
            }}
          >
            <option value="">Choose a capture</option>
            {sources.map((c) => (
              <option value={c.capture_id} key={c.capture_id}>
                {new Date(c.captured_at).toLocaleString()} ·{" "}
                {c.capture_id.slice(0, 8)}
              </option>
            ))}
          </select>
        </label>
        <div className="button-row">
          <button disabled={!chosen} onClick={() => void action("saved")}>
            Inspect saved outputs
          </button>
          <button disabled={!connected} onClick={() => void action("capture")}>
            Capture current application
          </button>
        </div>
        <p>A fresh backup can briefly interrupt controller processing.</p>
      </fieldset>
      {draft && (
        <fieldset className="output-assignment" disabled={busy}>
          <legend>Output assignment</legend>
          <p>
            Saved application {draft.capture.capture_id.slice(0, 8)} ·{" "}
            {controller.name}
          </p>
          <label>
            Configured source point{" "}
            <select
              value={draft.form.object}
              onChange={(e) => {
                const o = draft.outputs.find(
                  (v) => v.object === e.target.value,
                );
                edit({
                  object: e.target.value,
                  slot: String(o?.available_slots[0] ?? ""),
                });
              }}
            >
              <option value="">Select a compatible point</option>
              {draft.outputs.map((o) => (
                <option
                  key={o.object}
                  value={o.object}
                  disabled={!o.available_slots.length}
                >
                  {o.name} · OUT{o.slot} · {o.mode}
                  {o.unavailable_reason ? " · " + o.unavailable_reason : ""}
                </option>
              ))}
            </select>
          </label>
          {output && (
            <>
              <label>
                Operation{" "}
                <select
                  value={draft.form.move ? "move" : "add"}
                  onChange={(e) => edit({ move: e.target.value === "move" })}
                >
                  <option value="add">Add independent point</option>
                  <option value="move">Move existing point</option>
                </select>
              </label>
              <label>
                Destination terminal{" "}
                <select
                  value={draft.form.slot}
                  onChange={(e) => edit({ slot: e.target.value })}
                >
                  {output.available_slots.map((n) => (
                    <option key={n} value={n}>
                      OUT{n} · {output.terminal_signals?.[n] ?? output.mode}
                    </option>
                  ))}
                </select>
              </label>
              {!draft.form.move && (
                <>
                  <label>
                    New point name{" "}
                    <input
                      maxLength={128}
                      value={draft.form.name}
                      onChange={(e) => edit({ name: e.target.value })}
                    />
                  </label>
                  <label>
                    New point instance{" "}
                    <input
                      inputMode="numeric"
                      value={draft.form.instance}
                      onChange={(e) => edit({ instance: e.target.value })}
                    />
                  </label>
                </>
              )}
              <p>
                {draft.form.move
                  ? `Move ${output.name} from OUT${output.slot} to OUT${draft.form.slot} with its control logic.`
                  : `Add a ${output.mode} point on OUT${draft.form.slot}. ${output.name} keeps OUT${output.slot}.`}
              </p>
              {!local && (
                <button
                  className="primary"
                  onClick={() => void action("local")}
                >
                  Review local output edit
                </button>
              )}
              {local && !plan && (
                <button
                  className="primary"
                  disabled={!connected}
                  onClick={() => void action("review")}
                >
                  Review on controller
                </button>
              )}
            </>
          )}
          {!draft.outputs.some((o) => o.available_slots.length > 0) && (
            <p>
              This capture has no compatible source point with a free output
              terminal.
            </p>
          )}
          <button onClick={() => save(null)}>Discard local output draft</button>
        </fieldset>
      )}
      {plan && (
        <fieldset disabled={busy || !connected}>
          <legend>Apply reviewed output change</legend>
          <label>
            <input
              type="checkbox"
              checked={wiring}
              onChange={(e) => setWiring(e.target.checked)}
            />
            I verified the connected load, terminal wiring and signal type.
          </label>
          <label>
            <input
              type="checkbox"
              checked={transfer}
              onChange={(e) => setTransfer(e.target.checked)}
            />
            The controller can restart during this application transfer.
          </label>
          <button
            className="primary"
            disabled={!wiring || !transfer}
            onClick={() => void action("apply")}
          >
            Apply output change
          </button>
        </fieldset>
      )}
      {receipts.length > 0 && (
        <details open={receipts.some((r) => r.pending)}>
          <summary>Recorded output transfers</summary>
          {receipts.map((r) => (
            <p key={r.id}>
              {r.id.slice(0, 8)} · {r.status}{" "}
              <button
                disabled={busy || !connected}
                onClick={() => void action("readback", r.id)}
              >
                Read back transfer
              </button>
            </p>
          ))}
        </details>
      )}
      <p role="status">{busy ? "Checking output configuration…" : notice}</p>
      {error && (
        <p className="inline-error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
