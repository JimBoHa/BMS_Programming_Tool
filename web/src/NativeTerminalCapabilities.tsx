import { useEffect, useRef, useState } from "react";
import { apiJsonDocument, saveBlob } from "./api";
import type { NativeArchiveSource } from "./NativeRecords";
import { controllerKey } from "./workflow";
import {
  terminalCapabilityEvidence,
  terminalCapabilityProfile,
  terminalOperationIds,
} from "./nativeBinaryTerminalCapabilityContract";

export function NativeTerminalCapabilities({
  source,
}: {
  source: NativeArchiveSource;
}) {
  const owner = JSON.stringify([
    source.capture_id,
    source.snapshot_sha256,
    source.sha256,
    controllerKey(source.target),
  ]);
  const currentOwner = useRef(owner),
    epoch = useRef(0),
    alive = useRef(true);
  if (currentOwner.current !== owner) {
    currentOwner.current = owner;
    epoch.current++;
  }
  type Owned = {
    owner: string;
    epoch: number;
    data?: any;
    blob?: Blob;
    error?: string;
    busy?: boolean;
  };
  const [state, setState] = useState<Owned | null>(null);
  const current = (key: string, ticket: number) =>
    alive.current && currentOwner.current === key && epoch.current === ticket;
  const shown = state && current(state.owner, state.epoch) ? state : null;
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      epoch.current++;
    };
  }, []);
  async function analyze() {
    const key = currentOwner.current,
      ticket = ++epoch.current;
    setState({ owner: key, epoch: ticket, busy: true });
    try {
      const document = await apiJsonDocument(
          "/bacnet/controller/native-application/inspection/capabilities",
          {
            capture_id: source.capture_id,
            snapshot_sha256: source.snapshot_sha256,
            capability_profile: terminalCapabilityProfile,
          },
        ),
        d = document.data;
      if (
        d.profile !== "native-backup-record-inspection/1" ||
        d.source_kind !== "native-backup-archive" ||
        d.capture_id !== source.capture_id ||
        d.snapshot_sha256 !== source.snapshot_sha256 ||
        d.sha256 !== source.sha256 ||
        !(["3", "11", "12"] as const).every(
          (k) =>
            d.files?.[k]?.sha256 === source.files[k].sha256 &&
            d.files[k].bytes === source.files[k].bytes,
        ) ||
        typeof d.target?.address !== "string" ||
        typeof d.target?.device !== "string" ||
        controllerKey(d.target) !== controllerKey(source.target) ||
        d.read_only !== true ||
        d.controller_queries !== false ||
        d.field_actions !== false ||
        d.can_apply !== false ||
        d.current_identity_verified !== false ||
        !terminalCapabilityEvidence(d, source)
      )
        throw new Error(
          "Terminal operation analysis differs from this retained source. Analyze this snapshot again.",
        );
      if (current(key, ticket))
        setState({ owner: key, epoch: ticket, data: d, blob: document.blob });
    } catch (error) {
      if (current(key, ticket))
        setState({ owner: key, epoch: ticket, error: String(error) });
    }
  }
  return (
    <details
      aria-label="Native terminal operation support"
      onToggle={(e) => {
        if (e.currentTarget.open && !shown) void analyze();
      }}
    >
      <summary>Terminal copy and transfer support</summary>
      <p>
        Analyze captured inputs and unassigned universal terminals. Captured
        availability does not confirm physical wiring. This local analysis
        prepares no change.
      </p>
      {shown?.busy && (
        <p role="status">Analyzing retained terminal operations…</p>
      )}
      {shown?.error && <p role="alert">{shown.error}</p>}
      {shown?.data && (
        <>
          <div className="application-operation-table">
            <table aria-label="Native terminal operations">
              <thead>
                <tr>
                  <th>Operation</th>
                  <th>Support</th>
                  <th>Evidence and next step</th>
                </tr>
              </thead>
              <tbody>
                {shown.data.operations
                  .filter((r: any) => terminalOperationIds.includes(r.id))
                  .sort(
                    (a: any, b: any) =>
                      terminalOperationIds.indexOf(a.id) -
                      terminalOperationIds.indexOf(b.id),
                  )
                  .map((row: any) => (
                    <tr key={row.id} data-operation={row.id}>
                      <th scope="row">{row.operation}</th>
                      <td>{row.status.replaceAll("-", " ")}</td>
                      <td>
                        <p>{row.basis}</p>
                        <p>{row.next_step}</p>
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
          <details>
            <summary>Terminal source qualification evidence</summary>
            <pre>
              {JSON.stringify(
                Object.fromEntries(
                  Object.entries(shown.data.qualification).filter(([k]) =>
                    /_terminal(_error)?$/.test(k),
                  ),
                ),
                null,
                2,
              )}
            </pre>
          </details>
          <button
            onClick={() => {
              if (shown.blob && current(shown.owner, shown.epoch))
                saveBlob(shown.blob, "native-terminal-operation-analysis.json");
            }}
          >
            Save exact terminal analysis
          </button>
        </>
      )}
      {!shown?.busy && (
        <button onClick={() => void analyze()}>
          Analyze terminal support again
        </button>
      )}
    </details>
  );
}
