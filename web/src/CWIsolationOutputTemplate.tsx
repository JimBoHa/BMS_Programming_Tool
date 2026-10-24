import { useEffect, useRef, useState } from "react";
import { api, programJsonDocument, saveBlob, sourceJsonDocument } from "./api";
import {
  parseSourceDocument,
  sourceEqual,
  sourceStringify,
} from "./programSource";
import { sha256Blob } from "./activityContracts";
import {
  CW_BASE,
  cwCatalog,
  cwDescriptors,
  cwPreview,
  readCWChoices,
  type CWChoices,
  type CWImport,
  type Data,
} from "./cwIsolationOutputContract";
import type { Program } from "./types";
import "./cw-isolation-output.css";

type Review = {
  data: Data;
  key: string;
  sourceKey: string;
  choices: CWChoices;
  blob: Blob;
};
export function CWIsolationOutputTemplate({
  program,
  sourceEpoch,
  authorityReady,
  disabled,
  onImport,
}: {
  program: Program;
  sourceEpoch: number;
  authorityReady: boolean;
  disabled: boolean;
  onImport: (
    request: CWImport,
    sourceKey: string,
    definition: string,
    expectedDefinition: Data,
    owned: () => boolean,
  ) => Promise<boolean>;
}) {
  const [catalog, setCatalog] = useState<Data | null>(null),
    [minimum, setMinimum] = useState("0.0"),
    [stroke, setStroke] = useState("60"),
    [scan, setScan] = useState("1"),
    [review, setReview] = useState<Review | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const mounted = useRef(false),
    epoch = useRef(0),
    sourceKey = sourceEpoch + ":" + sourceStringify(program),
    key = JSON.stringify({
      minimum,
      stroke,
      scan,
      sourceKey,
      authorityReady,
      profile: catalog?.profile_sha256,
    }),
    live = useRef(key);
  live.current = key;
  const current = (mine: number, owned: string) =>
    mounted.current && epoch.current === mine && live.current === owned;
  async function reload() {
    const mine = ++epoch.current;
    setCatalog(null);
    setReview(null);
    setBusy(true);
    setError("");
    try {
      const data = await cwCatalog(await api(CW_BASE + "/catalog"));
      if (mounted.current && epoch.current === mine) setCatalog(data);
    } catch (e) {
      if (mounted.current && epoch.current === mine) setError(String(e));
    } finally {
      if (mounted.current && epoch.current === mine) setBusy(false);
    }
  }
  useEffect(() => {
    mounted.current = true;
    void reload();
    return () => {
      mounted.current = false;
      epoch.current++;
    };
  }, []);
  const previousSource = useRef(sourceKey);
  useEffect(() => {
    if (previousSource.current === sourceKey) return;
    previousSource.current = sourceKey;
    epoch.current++;
    setReview(null);
    setBusy(false);
    setError("");
  }, [sourceKey]);
  const previousAuthority = useRef(authorityReady);
  useEffect(() => {
    const wasReady = previousAuthority.current;
    previousAuthority.current = authorityReady;
    if (!wasReady || authorityReady) return;
    epoch.current++;
    setReview(null);
    setBusy(false);
    setError(
      "Activity criteria authority was retired. Review the current template again after recovery.",
    );
  }, [authorityReady]);
  function edit(which: "minimum" | "stroke" | "scan", text: string) {
    epoch.current++;
    ({ minimum: setMinimum, stroke: setStroke, scan: setScan })[which](text);
    setReview(null);
    setBusy(false);
    setError("");
  }
  async function preview() {
    if (!catalog || busy || disabled) return;
    const mine = ++epoch.current,
      owned = key,
      parent = program,
      source = sourceKey;
    setBusy(true);
    setReview(null);
    setError("");
    try {
      const choices = readCWChoices(minimum, stroke, scan);
      if (choices.scan_seconds !== parent.scan_seconds)
        throw new Error(
          "CW isolation scan must equal the current parent Program scan. Change the declaration or parent explicitly, then review again.",
        );
      const doc = await sourceJsonDocument(CW_BASE + "/preview", {
          program: parent,
          choices,
        }),
        data = cwPreview(doc.data, choices, parent, catalog);
      cwDescriptors(JSON.parse(await doc.blob.text()), data);
      if (current(mine, owned))
        setReview({
          data,
          key: owned,
          sourceKey: source,
          choices,
          blob: doc.blob,
        });
    } catch (e) {
      if (current(mine, owned)) setError(String(e));
    } finally {
      if (mounted.current && epoch.current === mine) setBusy(false);
    }
  }
  async function download(format: "review" | "bundle") {
    if (!review || review.key !== key || !catalog || busy || disabled) return;
    const accepted = review,
      mine = ++epoch.current,
      owned = key,
      parent = program;
    setBusy(true);
    setError("");
    try {
      const doc = await programJsonDocument(
          CW_BASE + "/export",
          { program: parent, choices: accepted.choices, format },
          true,
        ),
        digest = await sha256Blob(doc.blob),
        value = parseSourceDocument(await doc.blob.text());
      if (
        doc.blob.size > 8 * 1024 * 1024 ||
        doc.headers?.get("X-File-SHA256") !== digest
      )
        throw new Error(
          "CW isolation original export failed its byte-digest check.",
        );
      if (format === "review") {
        const checked = cwPreview(value, accepted.choices, parent, catalog);
        if (!sourceEqual(checked, accepted.data))
          throw new Error(
            "CW isolation review changed after the exact preview.",
          );
      } else if (
        digest !== accepted.data.bundle_sha256 ||
        !sourceEqual(value, accepted.data.bundle)
      )
        throw new Error(
          "CW isolation activity bundle differs from the reviewed definition.",
        );
      if (current(mine, owned))
        saveBlob(
          doc.blob,
          accepted.data.definition_id +
            (format === "review"
              ? ".cw-iso-review.json"
              : ".bms-activities.json"),
        );
    } catch (e) {
      if (current(mine, owned)) setError(String(e));
    } finally {
      if (mounted.current && epoch.current === mine) setBusy(false);
    }
  }
  async function adopt() {
    if (
      !review ||
      review.key !== key ||
      !review.data.can_import ||
      !catalog ||
      busy ||
      disabled
    )
      return;
    const accepted = review;
    if (
      !window.confirm(
        `Add “${accepted.data.program.name}” to the activity library of “${program.name}” at its current ${program.scan_seconds}s scan? Source conflicts will not be replaced. This creates no instance, saves no revision and changes no controller.`,
      )
    )
      return;
    const mine = ++epoch.current,
      owned = key;
    setBusy(true);
    setError("");
    try {
      const imported = await onImport(
        {
          choices: accepted.choices,
          profile_sha256: catalog.profile_sha256,
          reviewed_parent_sha256: accepted.data.parent_reference.program_sha256,
        },
        accepted.sourceKey,
        accepted.data.definition_id,
        accepted.data.bundle.library.definitions[0],
        () => current(mine, owned),
      );
      if (current(mine, owned) && imported) setReview(null);
    } catch (e) {
      if (current(mine, owned)) setError(String(e));
    } finally {
      if (mounted.current && epoch.current === mine) setBusy(false);
    }
  }
  const shown = review?.key === key ? review : null;
  return (
    <section
      className="macro-card cw-isolation-template"
      aria-label="CW isolation output template"
    >
      <h2>CW isolation output template</h2>
      <p>
        One shared editable graph publishes logical on/off and percent command.
        Enabled commands ramp up and down at the same rate; a committed disable
        immediately selects zero and resets ramp memory.
      </p>
      <div className="cw-isolation-fields">
        <label>
          Minimum target command %
          <input
            aria-label="CW minimum target command"
            type="text"
            inputMode="decimal"
            value={minimum}
            disabled={busy || disabled}
            onChange={(e) => edit("minimum", e.target.value)}
          />
        </label>
        <label>
          Full-stroke seconds
          <input
            aria-label="CW stroke seconds"
            type="number"
            min="1"
            max="86400"
            step="1"
            value={stroke}
            disabled={busy || disabled}
            onChange={(e) => edit("stroke", e.target.value)}
          />
        </label>
        <label>
          Declared scan seconds
          <input
            aria-label="CW scan seconds"
            type="number"
            min="1"
            max="60"
            step="1"
            value={scan}
            disabled={busy || disabled}
            onChange={(e) => edit("scan", e.target.value)}
          />
        </label>
      </div>
      <p className="help-text">
        Current parent: <b>{program.name}</b> · {program.scan_seconds}s scan.
        Stroke must be a whole multiple of that declared scan. The definition
        uses the parent clock; later edits or dt overrides can leave this
        qualification.
      </p>
      <p className="help-text">
        Minimum is an enabled target floor, so ramp transients may be below it.
        Logical on/off can be true at zero command. It is not flow, pump-running
        or valve-position proof.
      </p>
      <div className="button-row">
        <button
          disabled={busy || disabled || !catalog}
          onClick={() => void preview()}
        >
          Preview CW isolation output
        </button>
        <button disabled={busy || disabled} onClick={() => void reload()}>
          Reload CW isolation criteria
        </button>
        {busy && (
          <button
            onClick={() => {
              epoch.current++;
              setBusy(false);
              setReview(null);
              setError(
                "Pending CW isolation response discarded. No field operation was started.",
              );
            }}
          >
            Discard pending CW isolation response
          </button>
        )}
      </div>
      {busy && <p role="status">Preparing local CW isolation evidence…</p>}
      {error && <p role="alert">{error}</p>}
      {shown && (
        <section aria-label="CW isolation output preview">
          <h3>{shown.data.program.name}</h3>
          <p>
            13 editable blocks · 14 wires · 2 required inputs · 2 named
            mixed-type outputs · 1 shared Delay.
          </p>
          <table
            className="macro-table"
            aria-label="CW isolation template ports"
          >
            <thead>
              <tr>
                <th>Role</th>
                <th>Port</th>
                <th>Type</th>
                <th>Unit</th>
              </tr>
            </thead>
            <tbody>
              {shown.data.inputs.map((port: Data) => (
                <tr key={"in:" + port.id}>
                  <td>Required input</td>
                  <td>
                    {port.id} · {port.label}
                  </td>
                  <td>{port.value_type}</td>
                  <td>{port.unit || "—"}</td>
                </tr>
              ))}
              {shown.data.outputs.map((port: Data) => (
                <tr key={"out:" + port.id}>
                  <td>Named output</td>
                  <td>
                    {port.id} · {port.label}
                  </td>
                  <td>{port.value_type}</td>
                  <td>{port.unit || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <details>
            <summary>Ordinary control graph</summary>
            <table
              className="macro-table"
              aria-label="CW isolation ordinary graph"
            >
              <thead>
                <tr>
                  <th>Block</th>
                  <th>Kind</th>
                  <th>Parameters</th>
                </tr>
              </thead>
              <tbody>
                {shown.data.program.nodes.map((node: Data) => (
                  <tr key={node.id}>
                    <td>
                      {node.id} · {node.label}
                    </td>
                    <td>{node.kind}</td>
                    <td>
                      <code>{sourceStringify(node.params)}</code>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <ul>
              {shown.data.program.edges.map((edge: Data) => (
                <li key={edge.id}>
                  {edge.source} → {edge.target}.{edge.target_port}
                </li>
              ))}
            </ul>
          </details>
          <p className="cw-isolation-retention">
            Bad input quality or another scan fault retains the entire previous
            transaction, including a positive command and true on/off. A bad
            command sample with false enable does not guarantee shutdown.
          </p>
          <p className="help-text">
            The published output aliases are terminal in this template. Portable
            output forcing does not rewrite internal ramp memory. No native or
            physical forcing support is implied.
          </p>
          <details>
            <summary>Source and limits</summary>
            <p>
              {shown.data.profile.source.title}{" "}
              {shown.data.profile.source.edition}, PDF pages 905–906. The
              numerical ramp, Boolean proxy, target floor and reset policy are
              authored substitutions. Nominal stroke rate does not promise exact
              finite-width completion or physical actuation.
            </p>
            <ul>
              {shown.data.profile.gaps.map((gap: string) => (
                <li key={gap}>{gap}</li>
              ))}
            </ul>
          </details>
          <p className="cw-isolation-digests">
            Definition <code>{shown.data.definition_id}</code>
            <br />
            Program SHA-256 <code>{shown.data.program_sha256}</code>
            <br />
            Parent SHA-256{" "}
            <code>{shown.data.parent_reference.program_sha256}</code>
          </p>
          {shown.data.diagnostics.map((diagnostic: Data, i: number) => (
            <p key={i}>
              {diagnostic.level}: {diagnostic.message}
            </p>
          ))}
          <div className="button-row">
            <button
              disabled={busy || disabled}
              onClick={() => void download("review")}
            >
              Export original CW isolation review JSON
            </button>
            <button
              disabled={busy || disabled}
              onClick={() => void download("bundle")}
            >
              Export original CW isolation activity bundle
            </button>
            <button
              disabled={busy || disabled || !shown.data.can_import}
              onClick={() => void adopt()}
            >
              Import reviewed CW isolation definition
            </button>
            <button
              disabled={busy || disabled}
              onClick={() => {
                if (mounted.current && shown.key === live.current)
                  saveBlob(
                    shown.blob,
                    shown.data.definition_id + ".cw-iso-preview-response.json",
                  );
              }}
            >
              Download original CW isolation preview response
            </button>
            <button
              disabled={busy || disabled}
              onClick={() => {
                epoch.current++;
                setReview(null);
              }}
            >
              Dismiss CW isolation review
            </button>
          </div>
          <p className="help-text">
            Import adds only the reviewed reusable definition. Add and wire an
            instance separately. Source digests bind server-produced evidence;
            they are not manufacturer authentication or native JCI/G36/Title 24
            acceptance.
          </p>
        </section>
      )}
    </section>
  );
}
