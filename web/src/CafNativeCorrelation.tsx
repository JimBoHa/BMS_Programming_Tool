import { useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import { apiJsonDocument, saveBlob } from "./api";
import { sha256Blob } from "./activityContracts";
import { controllerKey, type ControllerContext } from "./workflow";
import {
  comparisonSources,
  comparisonRequest,
  comparisonReportSource,
  comparisonIdentityFlag,
  comparisonSourceMatches,
  type ComparisonSource,
  type ComparisonSourceKind,
} from "./cafNativeCorrelationSources";
import "./caf-native-correlation.css";

type Data = Record<string, any>;
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
  const [kind, setKind] = useState<ComparisonSourceKind>("backup");
  const [sourceCache, setSourceCache] = useState<
    Record<ComparisonSourceKind, ComparisonSource[]>
  >({ backup: [], file: [] });
  const [choices, setChoices] = useState<Record<ComparisonSourceKind, string>>({
    backup: "",
    file: "",
  });
  const sources = sourceCache[kind],
    choice = choices[kind],
    backup = kind === "backup";
  const setChoice = (value: string) =>
    setChoices((prior) => ({ ...prior, [kind]: value }));
  const [query, setQuery] = useState("");
  const selected = sources.find((row) => row.id === choice);
  const target = selected?.target || null;
  const context = JSON.stringify([
    id,
    visible,
    kind,
    controller && [
      controllerKey(controller),
      controller.interfaceKey,
      controller.interfaceOpen,
    ],
  ]);
  const owner = JSON.stringify([
    context,
    choice,
    selected?.signature,
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
  const [listFailure, setListFailure] = useState<{
    context: string;
    text: string;
  } | null>(null);
  const listError = listFailure?.context === context ? listFailure.text : "";
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
  const shownSource = shown ? comparisonReportSource(shown.data, kind) : null;
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
    setListFailure(null);
    try {
      const rows = await comparisonSources(kind);
      if (
        alive.current &&
        contextNow.current === key &&
        listEpoch.current === ticket
      ) {
        setSourceCache((prior) => ({ ...prior, [kind]: rows }));
        setChoices((prior) => ({
          ...prior,
          [kind]: rows.some((row) => row.id === prior[kind]) ? prior[kind] : "",
        }));
      }
    } catch (failure) {
      if (
        alive.current &&
        contextNow.current === key &&
        listEpoch.current === ticket
      )
        setListFailure({ context: key, text: String(failure) });
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
    const body = comparisonRequest(selected, id, query, offset);
    try {
      const result = await apiJsonDocument(
        "/caf/" +
          id +
          (backup ? "/native-correlation" : "/native-file-correlation"),
        body,
        true,
      );
      const data = result.data;
      const expectedHash = result.headers?.get("X-Studio-Artifact-Sha256");
      if (
        !comparisonSourceMatches(data, selected) ||
        data.caf?.sha256 !== id ||
        data.caf?.source !== "original-opened-archive" ||
        !data.request ||
        Object.keys(data.request).sort().join() !==
          Object.keys(body).sort().join() ||
        Object.entries(body).some(
          ([key, value]) => data.request[key] !== value,
        ) ||
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
            Comparison source type
            <span className="caf-native-select">
              <select
                aria-label="Comparison source type"
                value={kind}
                disabled={!visible}
                onChange={(event) =>
                  setKind(event.target.value as ComparisonSourceKind)
                }
              >
                <option value="backup">Native backup (Files 3/11/12)</option>
                <option value="file">Captured BACnet File</option>
              </select>
              <ChevronDown size={16} aria-hidden="true" />
            </span>
          </label>
          {!backup && (
            <p>
              Compare actual recognized native bytes from a retained File
              capture. Paired saved-setting files and atomic-backup evidence are
              unavailable.
            </p>
          )}
          <label>
            {backup
              ? "Native backup for CAF comparison"
              : "Captured File for CAF comparison"}
            <span className="caf-native-select">
              <select
                aria-label={
                  backup
                    ? "Native backup for CAF comparison"
                    : "Captured File for CAF comparison"
                }
                value={choice}
                disabled={!visible || listBusy}
                onChange={(event) => setChoice(event.target.value)}
              >
                <option value="">
                  {backup
                    ? "Select retained native backup"
                    : "Select retained BACnet File"}
                </option>
                {sources.map((row) => (
                  <option key={row.id} value={row.id}>
                    {typeof row.identity?.["object-name"] === "string"
                      ? row.identity["object-name"]
                      : row.id}{" "}
                    · {station(row.target)} ·{" "}
                    {!backup &&
                      `${row.raw.file_object} · ${typeof row.raw.format_hint === "string" ? row.raw.format_hint : "unlabelled format"} · `}
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
              {backup ? "Refresh comparison backups" : "Refresh captured files"}
            </button>
          </div>
          {listBusy && (
            <p role="status">
              {backup
                ? "Reading retained backup list…"
                : "Reading retained File list…"}
            </p>
          )}
          {listError && <p role="alert">{listError}</p>}
          {!listBusy && !sources.length && (
            <p>
              {backup
                ? "Read a native backup in Program's Native backup defaults tool, then refresh this list."
                : "Read an existing BACnet application File from the controller workspace, then refresh this list."}
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
                ? backup
                  ? "The workspace and retained source name the same station."
                  : "Workspace and captured File have matching recorded addresses."
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
                {backup
                  ? "Recorded acquisition identity: "
                  : "Recorded File device identity agrees with archive: "}
                {backup
                  ? comparisonIdentityFlag(shown.data, kind)
                    ? "verified at capture"
                    : "unverified"
                  : comparisonIdentityFlag(shown.data, kind)
                    ? "yes"
                    : "no"}
                . Native archive captured {shownSource?.captured_at}.
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
                      [backup ? "native_backup" : "native_file"]: shownSource,
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
