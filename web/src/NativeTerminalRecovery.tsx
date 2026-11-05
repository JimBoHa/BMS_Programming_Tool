import { useEffect, useRef, useState } from "react";
import { api, apiJsonDocument, saveBlob } from "./api";
import { terminalRecoveryDraft } from "./nativeTerminalRecoveryContract";
import { controllerKey } from "./workflow";

export type TerminalRecoveryDocument = { data: any; blob: Blob };
export function NativeTerminalRecovery({
  source,
  receipts,
  fieldBusy,
  draftKey,
  onUse,
}: {
  source: any;
  receipts: any[];
  fieldBusy: boolean;
  draftKey: string;
  onUse: (v: TerminalRecoveryDocument) => void;
}) {
  const [selected, setSelected] = useState("");
  const eligible = receipts.filter(
    (r) =>
      r.operation_profile === "native-local-universal-input-transfer/2" &&
      r.input_edit?.action === "terminal" &&
      controllerKey({ ...r.target, device: `device,${r.new_instance}` }) ===
        controllerKey({
          ...source.target,
          device: source.identity?.device ?? `device,${r.new_instance}`,
        }),
  );
  const owner = JSON.stringify([
    source.capture_id,
    source.snapshot_sha256,
    selected,
    draftKey,
  ]);
  const currentOwner = useRef(owner),
    epoch = useRef(0),
    alive = useRef(true);
  if (currentOwner.current !== owner) {
    currentOwner.current = owner;
    epoch.current++;
  }
  type State = {
    owner: string;
    epoch: number;
    document?: TerminalRecoveryDocument;
    error?: string;
    busy?: boolean;
  };
  const [state, setState] = useState<State | null>(null);
  const current = (key: string, ticket: number) =>
    alive.current && currentOwner.current === key && epoch.current === ticket;
  const shown = state && current(state.owner, state.epoch) ? state : null;
  useEffect(() => {
    alive.current = true;
    const leave = () => {
      epoch.current++;
      setState(null);
    };
    window.addEventListener("pagehide", leave);
    document.addEventListener("visibilitychange", leave);
    return () => {
      alive.current = false;
      epoch.current++;
      window.removeEventListener("pagehide", leave);
      document.removeEventListener("visibilitychange", leave);
    };
  }, []);
  async function prepare() {
    const key = currentOwner.current,
      ticket = ++epoch.current;
    setState({ owner: key, epoch: ticket, busy: true });
    try {
      if (!eligible.some((r) => r.id === selected))
        throw Error("Select a matching retained terminal transfer.");
      const receipt = await api(
        "/bacnet/controller/native-application/receipts/" + selected,
      );
      if (!current(key, ticket)) return;
      const parent = receipt.intent;
      if (parent?.id !== selected)
        throw Error(
          "The retained terminal receipt differs from this selection.",
        );
      const document = await apiJsonDocument(
        "/bacnet/controller/native-application/input/terminal-recovery/prepare",
        {
          receipt_id: selected,
          capture_id: source.capture_id,
          snapshot_sha256: source.snapshot_sha256,
        },
      );
      if (!(await terminalRecoveryDraft(document, source, parent)))
        throw Error(
          "Previous-terminal evidence differs from this exact source and receipt. Prepare again.",
        );
      if (current(key, ticket))
        setState({ owner: key, epoch: ticket, document });
    } catch (error) {
      if (current(key, ticket))
        setState({ owner: key, epoch: ticket, error: String(error) });
    }
  }
  const r = shown?.document?.data;
  return (
    <details aria-label="Previous analog input terminal">
      <summary>Previous input terminal</summary>
      <p>
        Choose a matching retained terminal transfer and this captured input
        source. Preparation reads local evidence; applying requires a fresh
        controller review.
      </p>
      <label>
        Original terminal transfer
        <select
          aria-label="Previous-terminal transfer receipt"
          disabled={fieldBusy || shown?.busy}
          value={selected}
          onChange={(e) => {
            epoch.current++;
            setState(null);
            setSelected(e.target.value);
          }}
        >
          <option value="">Select a matching terminal transfer</option>
          {eligible.map((r) => (
            <option key={r.id} value={r.id}>
              {r.id.slice(0, 8)} · {r.status} · {r.created_at}
            </option>
          ))}
        </select>
      </label>
      <button
        disabled={
          fieldBusy || shown?.busy || !eligible.some((r) => r.id === selected)
        }
        onClick={() => void prepare()}
      >
        Prepare previous input terminal
      </button>
      {shown?.busy && <p role="status">Checking retained terminal evidence…</p>}
      {shown?.error && <p role="alert">{shown.error}</p>}
      {r && (
        <>
          <p>
            {r.origin.object_id} · captured UI IN{r.origin.current_slot} ·
            previous UI IN{r.origin.previous_slot}.
          </p>
          {r.already_recorded ? (
            <p>
              The previous terminal is already recorded. No inverse proposal is
              available.
            </p>
          ) : (
            <button
              disabled={fieldBusy}
              onClick={() => {
                if (shown?.document && current(shown.owner, shown.epoch))
                  onUse(shown.document);
              }}
            >
              Use previous input terminal
            </button>
          )}
          <button
            onClick={() => {
              if (shown?.document && current(shown.owner, shown.epoch))
                saveBlob(
                  shown.document.blob,
                  "previous-terminal-evidence.json",
                );
            }}
          >
            Save previous-terminal evidence
          </button>
          <details>
            <summary>Previous-terminal source evidence</summary>
            <pre>{JSON.stringify(r, null, 2)}</pre>
          </details>
        </>
      )}
    </details>
  );
}
