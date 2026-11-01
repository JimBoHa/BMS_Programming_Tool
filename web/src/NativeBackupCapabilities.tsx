import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { NativeArchiveSource } from "./NativeRecords";
import { controllerKey } from "./workflow";

type Operation = {
  id: string;
  operation: string;
  status: string;
  basis: string;
  next_step: string;
};
type Report = {
  operations: Operation[];
  qualification: Record<string, any>;
  scope: string;
};
const operationIds = [
  "archive-read",
  "diagram-read",
  "identity-compile",
  "name-compile",
  "saved-settings",
  "signal-default-copy",
  "boolean-default-copy",
  "wire-source-copy",
  "effective-wire-compile",
  "effective-boolean-compile",
  "effective-default-compile",
  "identity-transfer",
  "default-transfer",
  "boolean-default-transfer",
  "general-logic",
  "release-packages",
  "physical-acceptance",
];
const statuses = new Set([
  "source-qualified",
  "unavailable",
  "unsupported-source",
  "source-mismatch",
  "transport-unavailable",
  "preflight-required",
  "not-evaluated",
  "not-inferred",
]);

export function NativeBackupCapabilities({
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
  const ownerNow = useRef(owner),
    epoch = useRef(0),
    alive = useRef(true);
  if (ownerNow.current !== owner) {
    ownerNow.current = owner;
    epoch.current++;
  }
  type Owned<T> = { owner: string; epoch: number; value: T };
  const [loaded, setLoaded] = useState<Owned<Report> | null>(null);
  const [failure, setFailure] = useState<Owned<string> | null>(null);
  const [pending, setPending] = useState<Owned<boolean> | null>(null);
  const current = (key: string, ticket: number) =>
    alive.current && ownerNow.current === key && epoch.current === ticket;
  const report =
    loaded && current(loaded.owner, loaded.epoch) ? loaded.value : null;
  const error =
    failure && current(failure.owner, failure.epoch) ? failure.value : null;
  const busy = Boolean(pending && current(pending.owner, pending.epoch));
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      epoch.current++;
    };
  }, []);

  async function analyze() {
    const key = ownerNow.current,
      ticket = ++epoch.current;
    setLoaded(null);
    setFailure(null);
    setPending({ owner: key, epoch: ticket, value: true });
    try {
      const data = await api(
        "/bacnet/controller/native-application/inspection/capabilities",
        {
          capture_id: source.capture_id,
          snapshot_sha256: source.snapshot_sha256,
        },
      );
      if (
        data.profile !== "native-backup-record-inspection/1" ||
        data.capability_profile !== "native-backup-operation-capabilities/6" ||
        data.source_kind !== "native-backup-archive" ||
        data.capture_id !== source.capture_id ||
        data.snapshot_sha256 !== source.snapshot_sha256 ||
        data.sha256 !== source.sha256 ||
        data.files?.["3"]?.sha256 !== source.sha256 ||
        typeof data.target?.address !== "string" ||
        typeof data.target?.device !== "string" ||
        controllerKey(data.target) !== controllerKey(source.target) ||
        data.read_only !== true ||
        data.controller_queries !== false ||
        data.field_actions !== false ||
        data.can_apply !== false ||
        data.current_identity_verified !== false ||
        typeof data.qualification !== "object" ||
        data.qualification === null ||
        typeof data.scope !== "string" ||
        !Array.isArray(data.operations) ||
        data.operations.length !== operationIds.length ||
        !data.operations.every(
          (row: Operation, index: number) =>
            row?.id === operationIds[index] &&
            statuses.has(row.status) &&
            [row.operation, row.basis, row.next_step].every(
              (value) => typeof value === "string",
            ),
        )
      )
        throw new Error(
          "Native backup operation analysis differs from the selected source. Inspect this snapshot again.",
        );
      if (current(key, ticket))
        setLoaded({ owner: key, epoch: ticket, value: data });
    } catch (error) {
      if (current(key, ticket))
        setFailure({ owner: key, epoch: ticket, value: String(error) });
    } finally {
      if (current(key, ticket)) setPending(null);
    }
  }
  return (
    <details
      className="application-operation-support"
      aria-label="Native backup operation support"
      onToggle={(event) => {
        if (event.currentTarget.open && !report && !busy && !error)
          void analyze();
      }}
    >
      <summary>Operation support for this native backup</summary>
      <p>
        Source-qualified means installed software recognizes these retained
        bytes. A fresh controller review is still required for transfer. This
        analysis prepares no write and verifies no current connection.
      </p>
      {busy && <p role="status">Analyzing retained native files…</p>}
      {error && (
        <>
          <p role="alert">{error}</p>
          <button onClick={() => void analyze()}>
            Analyze retained files again
          </button>
        </>
      )}
      {report && (
        <>
          <p>
            Captured firmware:{" "}
            {String(report.qualification.captured_firmware ?? "not recorded")}.
            Native ACS code:{" "}
            {String(
              report.qualification.native_identity?.format_versions?.acs ??
                "not recognized",
            )}
            . Native DMCS code:{" "}
            {String(
              report.qualification.native_identity?.format_versions?.dmcs ??
                "not recognized",
            )}
            . These version namespaces are separate.
          </p>
          <div className="application-operation-table">
            <table aria-label="Native backup operations">
              <thead>
                <tr>
                  <th>Operation</th>
                  <th>Support</th>
                  <th>Evidence and next step</th>
                </tr>
              </thead>
              <tbody>
                {report.operations.map((row) => (
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
            <summary>Operation qualification evidence</summary>
            <pre>{JSON.stringify(report.qualification, null, 2)}</pre>
            <p>{report.scope}</p>
          </details>
        </>
      )}
    </details>
  );
}
