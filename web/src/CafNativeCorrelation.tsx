import { useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import { api, apiJsonDocument, saveBlob } from "./api";
import { sha256Blob } from "./activityContracts";
import { controllerKey, type ControllerContext } from "./workflow";
import "./caf-native-correlation.css";

type Data = Record<string, any>;
const profile = "caf-native-source-correlation/1";
const hash = (value: unknown): value is string =>
  typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const statuses = new Set([
  "same-record-identity",
  "different-record-identity",
  "caf-only",
  "native-only",
  "identity-unavailable",
  "ambiguous-identity",
]);
const boundedInteger = (value: unknown, maximum: number) =>
  typeof value === "number" &&
  Number.isInteger(value) &&
  value >= 0 &&
  value <= maximum;
const recordedValue = (value: unknown) =>
  value === null ||
  (typeof value === "string" && value.length <= 4096) ||
  boundedInteger(value, 4194303);
const station = (row: Data) =>
  row.router
    ? `${row.router} / network ${row.dnet} / station ${row.address} · ${row.device}`
    : `${row.address} · ${row.device}`;

export function CafNativeCorrelation({
  id,
  filename,
  visible,
  controller,
  hasLocalProposals,
}: {
  id: string;
  filename: string;
  visible: boolean;
  controller?: ControllerContext | null;
  hasLocalProposals: boolean;
}) {
  const [sources, setSources] = useState<Data[]>([]);
  const [choice, setChoice] = useState("");
  const [query, setQuery] = useState("");
  const selected = sources.find((row) => row.id === choice);
  const target = selected
    ? { ...selected.target, device: selected.device }
    : null;
  const context = JSON.stringify([
    id,
    visible,
    controller && [
      controllerKey(controller),
      controller.interfaceKey,
      controller.interfaceOpen,
    ],
  ]);
  const owner = JSON.stringify([
    context,
    choice,
    selected?.evidence_sha256,
    target,
    query,
  ]);
  const ownerNow = useRef(owner),
    contextNow = useRef(context);
  const epoch = useRef(0),
    listEpoch = useRef(0),
    alive = useRef(true);
  if (ownerNow.current !== owner) {
    ownerNow.current = owner;
    epoch.current++;
  }
  if (contextNow.current !== context) {
    contextNow.current = context;
    listEpoch.current++;
  }
  const [pending, setPending] = useState<{
    owner: string;
    ticket: number;
  } | null>(null);
  const [listBusy, setListBusy] = useState(false);
  const [listError, setListError] = useState("");
  const [failure, setFailure] = useState<{
    owner: string;
    ticket: number;
    text: string;
  } | null>(null);
  const [loaded, setLoaded] = useState<{
    owner: string;
    ticket: number;
    data: Data;
    blob: Blob;
  } | null>(null);
  const shown =
    loaded?.owner === owner && loaded.ticket === epoch.current ? loaded : null;
  const error =
    failure?.owner === owner && failure.ticket === epoch.current
      ? failure.text
      : "";
  const busy = pending?.owner === owner && pending.ticket === epoch.current;
  const current = (key: string, ticket: number) =>
    alive.current && ownerNow.current === key && epoch.current === ticket;
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      epoch.current++;
      listEpoch.current++;
    };
  }, []);
  async function refresh() {
    const key = contextNow.current,
      ticket = ++listEpoch.current;
    epoch.current++;
    setLoaded(null);
    setFailure(null);
    setPending(null);
    setListBusy(true);
    setListError("");
    try {
      const result = await api(
        "/bacnet/controller/native-application/signal-default/sources",
      );
      if (
        result.profile !== "native-effective-signal-default-compiler/1" ||
        result.controller_queries !== false ||
        !Array.isArray(result.sources) ||
        result.sources.length > 128 ||
        new Set(result.sources.map((row: Data) => row.id)).size !==
          result.sources.length ||
        result.sources.some(
          (row: Data) =>
            !/^[a-f0-9]{32}$/.test(row.id || "") ||
            !hash(row.evidence_sha256) ||
            typeof row.target?.address !== "string" ||
            typeof row.device !== "string",
        )
      )
        throw new Error("Unsupported retained native backup list.");
      if (
        alive.current &&
        contextNow.current === key &&
        listEpoch.current === ticket
      ) {
        setSources(result.sources);
        setChoice((prior) =>
          result.sources.some((row: Data) => row.id === prior) ? prior : "",
        );
      }
    } catch (failure) {
      if (
        alive.current &&
        contextNow.current === key &&
        listEpoch.current === ticket
      )
        setListError(String(failure));
    } finally {
      if (
        alive.current &&
        contextNow.current === key &&
        listEpoch.current === ticket
      )
        setListBusy(false);
    }
  }
  useEffect(() => {
    if (visible) void refresh();
  }, [context]);
  async function compare(offset = 0) {
    if (!selected || !visible) return;
    const key = ownerNow.current,
      ticket = ++epoch.current;
    setLoaded(null);
    setFailure(null);
    setPending({ owner: key, ticket });
    const body = {
      source_sha256: id,
      capture_id: selected.id,
      snapshot_sha256: selected.evidence_sha256,
      query,
      offset,
      limit: 64,
    };
    try {
      const result = await apiJsonDocument(
        "/caf/" + id + "/native-correlation",
        body,
        true,
      );
      const data = result.data,
        native = data.native_backup;
      const expectedHash = result.headers?.get("X-Studio-Artifact-Sha256");
      if (
        data.profile !== profile ||
        data.caf?.sha256 !== id ||
        data.caf?.source !== "original-opened-archive" ||
        !data.request ||
        Object.keys(data.request).sort().join() !==
          Object.keys(body).sort().join() ||
        Object.entries(body).some(
          ([key, value]) => data.request[key] !== value,
        ) ||
        native?.profile !== "native-backup-record-inspection/1" ||
        native?.source_kind !== "native-backup-archive" ||
        native?.capture_id !== selected.id ||
        native?.snapshot_sha256 !== selected.evidence_sha256 ||
        !hash(native?.sha256) ||
        native?.files?.["3"]?.sha256 !== native.sha256 ||
        native?.read_only !== true ||
        native?.controller_queries !== false ||
        native?.field_actions !== false ||
        native?.identity_verified !== false ||
        native?.captured_at !== selected.captured_at ||
        controllerKey(native.target) !== controllerKey(target!) ||
        data.read_only !== true ||
        data.controller_queries !== false ||
        data.field_actions !== false ||
        data.full_program_match_verified !== false ||
        data.compiler_compatibility_verified !== false ||
        data.application_association_granted !== false ||
        data.can_apply !== false ||
        ![
          "recorded-identities-equal",
          "recorded-differences",
          "identity-incomplete",
        ].includes(data.classification) ||
        typeof data.recorded_acquisition_identity_verified !== "boolean" ||
        !Array.isArray(data.device_checks) ||
        data.device_checks.length !== 5 ||
        data.device_checks.map((row: Data) => row.field).join() !==
          "root_ref,root_class,instance,name,model" ||
        data.device_checks.some(
          (row: Data) =>
            !["equal", "different", "unavailable"].includes(row.status) ||
            !recordedValue(row.caf) ||
            !recordedValue(row.native),
        ) ||
        !data.coverage ||
        [
          "caf_objects",
          "native_engineering_records",
          "native_metadata_records",
          "union_references",
        ].some((key) => !boundedInteger(data.coverage[key], 40000)) ||
        !Array.isArray(data.coverage.not_compared) ||
        data.coverage.not_compared.length !== 4 ||
        data.coverage.not_compared.some(
          (value: unknown) => typeof value !== "string" || value.length > 4096,
        ) ||
        !Array.isArray(data.records) ||
        data.records.length > body.limit ||
        data.records.some(
          (row: Data) =>
            typeof row.ref !== "string" ||
            [...row.ref].length > 512 ||
            !statuses.has(row.status) ||
            [row.caf_class, row.native_class].some(
              (value) => value !== null && !boundedInteger(value, 65535),
            ) ||
            [row.caf_object_id, row.native_object_id].some(
              (value) => value !== null && !boundedInteger(value, 4194303),
            ),
        ) ||
        new Set(data.records.map((row: Data) => row.ref)).size !==
          data.records.length ||
        data.query !== query ||
        data.offset !== offset ||
        data.limit !== 64 ||
        !Number.isInteger(data.total_matches) ||
        data.total_matches > data.coverage.union_references ||
        data.total_matches < data.records.length ||
        (data.next_offset !== null && data.next_offset !== offset + 64) ||
        !hash(data.report_sha256) ||
        !hash(expectedHash) ||
        (await sha256Blob(result.blob)) !== expectedHash
      )
        throw new Error(
          "Comparison evidence does not match this CAF, retained source and request.",
        );
      if (current(key, ticket)) setLoaded({ owner: key, ticket, ...result });
    } catch (failure) {
      if (current(key, ticket))
        setFailure({ owner: key, ticket, text: String(failure) });
    } finally {
      if (current(key, ticket)) setPending(null);
    }
  }
  return (
    <section
      className="card caf-native-correlation"
      aria-label="CAF/native source comparison"
    >
      <details>
        <summary className="card-header">
          <h3>Compare CAF with retained native records</h3>
          <ChevronDown size={16} aria-hidden="true" />
        </summary>
        <div className="card-body">
          <p>
            Original opened CAF: <b>{filename}</b>. This comparison reads saved
            files on this computer.
          </p>
          <p>
            Device and literal record identities can help identify a reference
            file. Matching numbers do not establish matching logic or compiler
            compatibility.
          </p>
          {hasLocalProposals && (
            <p role="status">
              Local CAF proposals are excluded. Compare an exported copy by
              opening that file separately.
            </p>
          )}
          <label>
            Native backup for CAF comparison
            <span className="caf-native-select">
              <select
                aria-label="Native backup for CAF comparison"
                value={choice}
                disabled={!visible || listBusy}
                onChange={(event) => setChoice(event.target.value)}
              >
                <option value="">Select retained native backup</option>
                {sources.map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.identity?.["object-name"] || row.id} ·{" "}
                    {station({ ...row.target, device: row.device })} ·{" "}
                    {row.captured_at}
                  </option>
                ))}
              </select>
              <ChevronDown size={16} aria-hidden="true" />
            </span>
          </label>
          <div className="button-row">
            <button
              disabled={!visible || listBusy}
              onClick={() => void refresh()}
            >
              Refresh comparison backups
            </button>
          </div>
          {listBusy && <p role="status">Reading retained backup list…</p>}
          {listError && <p role="alert">{listError}</p>}
          {!listBusy && !sources.length && (
            <p>
              Read a native backup in Program's Native backup defaults tool,
              then refresh this list.
            </p>
          )}
          {target && (
            <p aria-label="Comparison source station">
              Retained source: {station(target)}.
            </p>
          )}
          {controller && target && (
            <p aria-label="Comparison workspace relation">
              {controllerKey(controller) === controllerKey(target)
                ? "The workspace and retained source name the same station."
                : "The workspace selects a different station."}{" "}
              Retained evidence does not verify its current program.
              {!controller.interfaceOpen &&
                " The workspace interface is closed."}
            </p>
          )}
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void compare();
            }}
          >
            <label>
              Find comparison records
              <input
                aria-label="Find comparison records"
                maxLength={256}
                value={query}
                disabled={!visible}
                onChange={(event) => setQuery(event.target.value)}
              />
            </label>
            <button
              className="primary"
              disabled={!visible || !selected || busy || listBusy}
              type="submit"
            >
              Compare original CAF and native archive
            </button>
          </form>
          {busy && <p role="status">Comparing recorded source identities…</p>}
          {error && <p role="alert">{error}</p>}
          {shown && (
            <section aria-label="CAF/native comparison result">
              <h4>
                {
                  (
                    {
                      "recorded-identities-equal":
                        "Recorded identities equal within the checked scope",
                      "recorded-differences":
                        "Recorded identity differences found",
                      "identity-incomplete":
                        "Recorded identity evidence is incomplete",
                    } as Record<string, string>
                  )[shown.data.classification]
                }
              </h4>
              <p>
                Full program match, compiler compatibility and a live
                application association remain unverified.
              </p>
              <p>
                Recorded acquisition identity:{" "}
                {shown.data.recorded_acquisition_identity_verified
                  ? "verified at capture"
                  : "unverified"}
                . Native archive captured {shown.data.native_backup.captured_at}
                .
              </p>
              <div className="table-scroll">
                <table aria-label="CAF/native Device identity checks">
                  <thead>
                    <tr>
                      <th>Field</th>
                      <th>CAF</th>
                      <th>Native archive</th>
                      <th>Observation</th>
                    </tr>
                  </thead>
                  <tbody>
                    {shown.data.device_checks.map((row: Data) => (
                      <tr key={row.field}>
                        <td>{row.field}</td>
                        <td>{row.caf ?? "Unavailable"}</td>
                        <td>{row.native ?? "Unavailable"}</td>
                        <td>{row.status}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p>
                {shown.data.coverage.caf_objects} CAF objects ·{" "}
                {shown.data.coverage.native_engineering_records} native
                engineering records ·{" "}
                {shown.data.coverage.native_metadata_records} native metadata
                records excluded from record identity comparison.
              </p>
              <div className="table-scroll">
                <table aria-label="CAF/native record identity observations">
                  <thead>
                    <tr>
                      <th>Reference</th>
                      <th>CAF class / ID</th>
                      <th>Native class / ID</th>
                      <th>Observation</th>
                    </tr>
                  </thead>
                  <tbody>
                    {shown.data.records.map((row: Data) => (
                      <tr key={row.ref}>
                        <td className="mono">{row.ref}</td>
                        <td>
                          {row.caf_class ?? "—"} / {row.caf_object_id ?? "—"}
                        </td>
                        <td>
                          {row.native_class ?? "—"} /{" "}
                          {row.native_object_id ?? "—"}
                        </td>
                        <td>{row.status}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p>
                {shown.data.total_matches} matching references · offset{" "}
                {shown.data.offset}.
              </p>
              <div className="button-row">
                <button
                  disabled={busy || shown.data.offset === 0}
                  onClick={() =>
                    void compare(Math.max(0, shown.data.offset - 64))
                  }
                >
                  Previous comparison records
                </button>
                <button
                  disabled={busy || shown.data.next_offset === null}
                  onClick={() => void compare(shown.data.next_offset)}
                >
                  Next comparison records
                </button>
                <button
                  onClick={() =>
                    saveBlob(shown.blob, "caf-native-source-comparison.json")
                  }
                >
                  Save exact source comparison
                </button>
              </div>
              <details>
                <summary>Comparison scope and source evidence</summary>
                <ul>
                  {shown.data.coverage.not_compared.map((row: string) => (
                    <li key={row}>{row}</li>
                  ))}
                </ul>
                <pre>
                  {JSON.stringify(
                    {
                      caf: shown.data.caf,
                      native_backup: shown.data.native_backup,
                      coverage: shown.data.coverage,
                      report_sha256: shown.data.report_sha256,
                    },
                    null,
                    2,
                  )}
                </pre>
              </details>
            </section>
          )}
        </div>
      </details>
    </section>
  );
}
