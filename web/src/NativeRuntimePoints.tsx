import { useEffect, useRef, useState } from "react";
import {
  NativeContactFields,
  contactProposal,
  selectContact,
  type ContactCatalog,
  type ContactForm,
} from "./NativeContactFields";
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
  independent?: boolean;
};
type Receipt = { id: string; status: string; pending: boolean };
type Form = ContactForm & { move: boolean };
type Draft = {
  capture: Capture;
  outputs: Output[];
  contacts?: ContactCatalog;
  localReviewOnly?: boolean;
  form: Form;
};
const drafts = new Map<string, Draft>();
const blank: Form = {
  object: "",
  slot: "",
  instance: "",
  name: "",
  move: false,
  contactAction: "add",
  polarity: "normal",
};

function outputProposal(output: Output | undefined, f: Form) {
  if (!output || !output.available_slots.includes(Number(f.slot)))
    throw Error("Choose an output and a free terminal.");
  const sourceId = Number(output.object.split(",")[1]);
  if (
    !f.move &&
    (!f.name.trim() ||
      !/^\d+$/.test(f.instance) ||
      Number(f.instance) < 1 ||
      Number(f.instance) > 4194302)
  )
    throw Error("Enter a point name and valid unused instance.");
  if (output.independent) {
    if (f.move) throw Error("A new point requires an unused terminal.");
    return {
      action: "allocate-discrete-output",
      slot: Number(f.slot),
      object_instance: Number(f.instance),
      name: f.name.trim(),
    };
  }
  return {
    action: f.move
      ? output.mode + "-output-terminal"
      : "allocate-" + output.mode + "-output",
    expected_slot: output.slot,
    slot: Number(f.slot),
    object_instance: f.move ? sourceId : Number(f.instance),
    ...(f.move ? {} : { template_instance: sourceId, name: f.name.trim() }),
  };
}

export function NativeRuntimePoints({
  direction,
  controller,
  connected,
  onBusy,
  onVerified,
}: {
  direction: "input" | "output";
  controller: ControllerContext;
  connected: boolean;
  onBusy: (busy: boolean) => void;
  onVerified: () => void;
}) {
  const contactsMode = direction === "input";
  const owner = JSON.stringify([
    controllerKey(controller),
    controller.interfaceKey,
    direction,
  ]);
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
          "Discard a saved I/O draft before opening another controller draft.",
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
    const result = await api(
      route + (contactsMode ? "/contact-sources" : "/output-sources"),
      target,
    );
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
        setNotice("Review expired. Review the " + direction + " change again.");
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
    const operation_id = direction + "-" + kind + "-" + Date.now().toString(36);
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
        const q = await api(route + (contactsMode ? "/contacts" : "/outputs"), {
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
          throw Error(
            "The saved application differs from the selected controller.",
          );
        const contacts: ContactCatalog | undefined = contactsMode
          ? { contacts: q.contacts, available_slots: q.available_slots }
          : undefined;
        const outputs: Output[] = [...(q.outputs ?? [])];
        if (!contactsMode && q.discrete_terminals?.length) {
          outputs.push({
            object: "new-discrete",
            name: "New two-state output",
            mode: "binary",
            slot: 0,
            available_slots: q.discrete_terminals,
            terminal_signals: q.discrete_terminal_signals,
            independent: true,
          });
        }
        const first: Output | undefined = outputs.find(
          (o: Output) => o.available_slots.length,
        );
        let suggestion: number | null = q.suggested_instance;
        let allocatorMessage = "";
        if (kind === "capture" && !q.local_review_only) {
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
          outputs,
          contacts,
          localReviewOnly: q.local_review_only === true,
          form: {
            ...blank,
            object: first?.object || "",
            slot: String(first?.available_slots[0] ?? ""),
            ...(contacts
              ? selectContact(
                  contacts,
                  contacts.available_slots.length ? "add" : "polarity",
                )
              : {}),
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
          throw Error("Review the change and confirm the wiring and transfer.");
        const reviewed = plan;
        retire();
        setLocal(false);
        const r =
          kind === "apply"
            ? await api(route + "/apply", {
                token: reviewed!.token,
                review_sha256: reviewed!.review_sha256,
                local_io_testing_confirmed: true,
                ...(contactsMode
                  ? { input_wiring_confirmed: wiring }
                  : { output_wiring_confirmed: wiring }),
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
          const contactState = result.published_io?.present_value;
          if (contactsMode && contactState !== 0 && contactState !== 1) {
            throw Error(
              "The receipt has no valid contact state. Read back the transfer again.",
            );
          }
          save(null);
          setNotice(
            contactsMode
              ? "Controller configuration and input readback verified. Contact state at readback was " +
                  (contactState === 1 ? "active." : "inactive.")
              : "Controller configuration and output readback verified. Refresh the point inventory to command a point.",
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
        if (!draft) throw Error("Choose a saved application.");
        const f = draft.form;
        const change = draft.contacts
          ? contactProposal(draft.contacts, f)
          : outputProposal(output, f);
        const args = {
          ...target,
          operation_id,
          capture_id: draft.capture.capture_id,
          snapshot_sha256: draft.capture.snapshot_sha256,
          edit: change,
        };
        const q = await api(
          route + (kind === "local" ? "/source" : "/preview"),
          args,
        );
        if (!current()) return;
        const c = q.compilation?.changes?.[0];
        const type = contactsMode
          ? "binary-input"
          : output?.mode === "binary"
            ? "binary-output"
            : "analog-output";
        const op = contactsMode ? f.contactAction : f.move ? "move" : "add";
        const sourceId =
          kind === "local" ? q.capture_id : q.request?.capture_id;
        if (
          sourceId !== draft.capture.capture_id ||
          c?.after_slot !== change.slot ||
          c?.object !== type + "," + change.object_instance ||
          ("expected_slot" in change &&
            c?.before_slot !== change.expected_slot) ||
          ("polarity" in change &&
            change.polarity &&
            c?.polarity !== change.polarity) ||
          c?.operation !== (op === "add" ? "allocate" : op)
        )
          throw Error("Returned change differs from the selected point.");
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
            "Controller identity and " +
              direction +
              " assignment verified for this review.",
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
      className="native-runtime-points"
      aria-label={
        contactsMode
          ? "Dry contact configuration"
          : "Native output configuration"
      }
    >
      <h3>
        {contactsMode ? "Configure dry contacts" : "Configure output points"}
      </h3>
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
            {contactsMode ? "Inspect saved inputs" : "Inspect saved outputs"}
          </button>
          <button disabled={!connected} onClick={() => void action("capture")}>
            Capture current application
          </button>
        </div>
        <p>A fresh backup can briefly interrupt controller processing.</p>
      </fieldset>
      {draft && (
        <fieldset className="output-assignment" disabled={busy}>
          <legend>
            {contactsMode ? "Dry contact assignment" : "Output assignment"}
          </legend>
          <p>
            Saved application {draft.capture.capture_id.slice(0, 8)} ·{" "}
            {controller.name}
          </p>
          {draft.localReviewOnly && (
            <p>This controller application supports local I/O review only.</p>
          )}
          {draft.contacts ? (
            <NativeContactFields
              catalog={draft.contacts}
              form={draft.form}
              edit={edit}
            />
          ) : (
            <>
              <label>
                Output source{" "}
                <select
                  value={draft.form.object}
                  onChange={(e) => {
                    const o = draft.outputs.find(
                      (v) => v.object === e.target.value,
                    );
                    edit({
                      object: e.target.value,
                      slot: String(o?.available_slots[0] ?? ""),
                      move: o?.independent ? false : draft.form.move,
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
                      {o.independent
                        ? o.name
                        : `${o.name} · OUT${o.slot} · ${o.mode}`}
                      {o.unavailable_reason ? " · " + o.unavailable_reason : ""}
                    </option>
                  ))}
                </select>
              </label>
              {output && (
                <>
                  {!output.independent && (
                    <label>
                      Operation{" "}
                      <select
                        value={draft.form.move ? "move" : "add"}
                        onChange={(e) =>
                          edit({ move: e.target.value === "move" })
                        }
                      >
                        <option value="add">Add independent point</option>
                        <option value="move">Move existing point</option>
                      </select>
                    </label>
                  )}
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
                      : output.independent
                        ? `Add an independent two-state command on OUT${draft.form.slot}.`
                        : `Add a ${output.mode} point on OUT${draft.form.slot}. ${output.name} keeps OUT${output.slot}.`}
                  </p>
                </>
              )}
              {!draft.outputs.some((o) => o.available_slots.length > 0) && (
                <p>
                  This capture has no compatible source point with a free output
                  terminal.
                </p>
              )}
            </>
          )}
          {(draft.contacts
            ? draft.form.contactAction === "add"
              ? draft.contacts.available_slots.length > 0
              : !!draft.form.object
            : !!output) && (
            <>
              {!local && (
                <button
                  className="primary"
                  onClick={() => void action("local")}
                >
                  Review local {direction} edit
                </button>
              )}
              {local && !plan && !draft.localReviewOnly && (
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
          <button onClick={() => save(null)}>
            Discard local {direction} draft
          </button>
        </fieldset>
      )}
      {plan && (
        <fieldset disabled={busy || !connected}>
          <legend>Apply reviewed {direction} change</legend>
          <label>
            <input
              type="checkbox"
              checked={wiring}
              onChange={(e) => setWiring(e.target.checked)}
            />
            {contactsMode
              ? "I verified the input terminal, contact wiring and intended polarity."
              : "I verified the connected load, terminal wiring and signal type."}
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
            Apply {direction} change
          </button>
        </fieldset>
      )}
      {receipts.length > 0 && (
        <details open={receipts.some((r) => r.pending)}>
          <summary>Recorded {direction} transfers</summary>
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
      <p role="status">
        {busy ? "Checking " + direction + " configuration…" : notice}
      </p>
      {error && (
        <p className="inline-error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
