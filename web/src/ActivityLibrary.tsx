import { useEffect, useRef, useState } from "react";
import {
  programApi,
  programJsonDocument,
  saveBlob,
  sourceApi,
  sourceJsonDocument,
} from "./api";
import {
  cloneSource,
  parseSourceDocument,
  projectSourceDocument,
  sourceEqual,
  sourceStringify,
} from "./programSource";
import {
  ACTIVITY_BASE,
  activityCatalog,
  activityProfile,
  activitySource,
  hash,
  libraryVersion,
  manifestSha256,
  sha256Blob,
  type Data,
} from "./activityContracts";
import type { Program } from "./types";
import type { ReusableLibraryProps } from "./ReusableLibrary";
import { CWIsolationOutputTemplate } from "./CWIsolationOutputTemplate";
import { CW_BASE, type CWImport } from "./cwIsolationOutputContract";

type Promotion = {
  original: File;
  bundle: Data;
  data: Data;
  blob: Blob;
  key: string;
};
export function ActivityLibrary({
  program,
  selectedIds,
  sourceEpoch,
  onAdopt,
  onSelect,
  onEditDefinition,
  onActivityCatalog,
}: ReusableLibraryProps & { onAdopt: (program: Program) => boolean }) {
  const [catalog, setCatalog] = useState<{ data: Data; key: string } | null>(
      null,
    ),
    [selected, setSelected] = useState(""),
    [name, setName] = useState(""),
    [x, setX] = useState("320"),
    [y, setY] = useState("160"),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [inspection, setInspection] = useState<Program | null>(null),
    [promotion, setPromotion] = useState<Promotion | null>(null);
  const input = useRef<HTMLInputElement>(null),
    mounted = useRef(false),
    epoch = useRef(0),
    key = sourceEpoch + ":" + sourceStringify(program),
    live = useRef(key);
  live.current = key;
  const valid = (mine: number, owned: string) =>
    mounted.current && epoch.current === mine && live.current === owned;
  async function reload(explicit = false) {
    const mine = ++epoch.current,
      owned = key,
      parent = program;
    setCatalog(null);
    if (explicit) onActivityCatalog?.(null);
    setInspection(null);
    setPromotion(null);
    setBusy(true);
    setError("");
    try {
      const data = await activityCatalog(
        await programApi(ACTIVITY_BASE + "/catalog", { program: parent }),
        parent,
      );
      if (valid(mine, owned)) {
        setCatalog({ data, key: owned });
        onActivityCatalog?.(data);
      }
    } catch (e) {
      if (valid(mine, owned)) {
        setError(String(e));
        onActivityCatalog?.(null, String(e));
      }
    } finally {
      if (mounted.current && epoch.current === mine) setBusy(false);
    }
  }
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      epoch.current++;
    };
  }, []);
  useEffect(() => {
    void reload();
  }, [key]);
  const shown = catalog?.key === key ? catalog.data : null,
    definitions: Data[] = shown?.definitions || [],
    item = definitions.find((definition) => definition.id === selected);
  async function mutate(
    path: string,
    fields: Data,
    message: string,
    choose?: string,
  ) {
    if (!shown || busy) return false;
    const mine = ++epoch.current,
      owned = key,
      parent = program;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const next: Program = await sourceApi(ACTIVITY_BASE + path, {
        program: parent,
        ...fields,
      });
      if (
        next.id !== parent.id ||
        next.revision !== parent.revision ||
        next.name !== parent.name ||
        next.description !== parent.description ||
        next.scan_seconds !== parent.scan_seconds ||
        !sourceEqual(next.target, parent.target) ||
        libraryVersion(next) !== 2
      )
        throw new Error(
          "Activity mutation returned a different parent identity, clock or target.",
        );
      activitySource(next);
      if (valid(mine, owned) && onAdopt(next)) {
        if (choose !== undefined) setSelected(choose);
        else if (path === "/create") {
          const oldDefinitions = new Set(
            (parent.metadata.macros?.definitions || []).map(
              (definition: Data) => definition.id,
            ),
          );
          const added = next.metadata.macros?.definitions?.find(
            (definition: Data) => !oldDefinitions.has(definition.id),
          );
          if (added) setSelected(added.id);
        } else if (
          path === "/import" &&
          typeof fields.bundle?.root === "string"
        ) {
          setSelected(fields.bundle.root);
        }
        if (path === "/create" || path === "/instantiate") {
          const oldNodes = new Set(parent.nodes.map((node) => node.id));
          const added = next.nodes.find(
            (node) => node.kind === "Activity" && !oldNodes.has(node.id),
          );
          if (added) onSelect?.(added.id);
        }
        setNotice(message);
        setInspection(null);
        setPromotion(null);
        return true;
      }
    } catch (e) {
      if (valid(mine, owned)) setError(String(e));
    } finally {
      if (mounted.current && epoch.current === mine) setBusy(false);
    }
    return false;
  }
  async function create() {
    if (!selectedIds.length || !name.trim()) return;
    await mutate(
      "/create",
      { selected_ids: selectedIds, name },
      "Reusable activity created from the selection. No revision was saved.",
    );
  }
  async function importCWTemplate(
    request: CWImport,
    sourceKey: string,
    definition: string,
    expectedDefinition: Data,
    owned: () => boolean,
  ) {
    if (!shown || busy) return false;
    const mine = ++epoch.current,
      accepted = key,
      parent = program;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      if (
        !owned() ||
        sourceKey !== accepted ||
        parent.scan_seconds !== request.choices.scan_seconds
      )
        throw new Error(
          "The current activity editor or clock changed. Preview the CW isolation template again.",
        );
      const next: Program = await sourceApi(CW_BASE + "/import", {
        program: parent,
        ...request,
      });
      if (!valid(mine, accepted) || !owned()) return false;
      activitySource(next);
      const nextDefinitions: Data[] = next.metadata.macros.definitions,
        previousDefinitions: Data[] = parent.metadata.macros.definitions,
        received = nextDefinitions.find((item) => item.id === definition),
        expectedIds = new Set([
          ...previousDefinitions.map((item) => item.id),
          definition,
        ]);
      const structuralNodes = (value: Program) =>
        value.nodes.map((node) => ({
          id: node.id,
          kind: node.kind,
          label: node.label,
          x: node.x,
          y: node.y,
          unit: node.unit,
          value_type: node.value_type,
        }));
      if (
        next.id !== parent.id ||
        next.revision !== parent.revision ||
        next.name !== parent.name ||
        next.description !== parent.description ||
        next.scan_seconds !== parent.scan_seconds ||
        !sourceEqual(next.target, parent.target) ||
        !sourceEqual(structuralNodes(next), structuralNodes(parent)) ||
        !sourceEqual(next.edges, parent.edges) ||
        nextDefinitions.length !== expectedIds.size ||
        nextDefinitions.some((item) => !expectedIds.has(item.id)) ||
        previousDefinitions.some(
          (item) =>
            !nextDefinitions.some(
              (nextItem) =>
                nextItem.id === item.id && nextItem.name === item.name,
            ),
        ) ||
        !received ||
        !sourceEqual(
          projectSourceDocument(cloneSource(received)),
          projectSourceDocument(cloneSource(expectedDefinition)),
        )
      )
        throw new Error(
          "CW isolation import differs from the reviewed definition or current parent structure.",
        );
      // The backend rechecks the exact supplied canonical parent before merging.
      // Do not Number-project opaque existing atoms to compare Python spellings.
      if (onAdopt(next)) {
        setSelected(definition);
        setInspection(null);
        setPromotion(null);
        setNotice(
          "Reviewed CW isolation definition added at the parent clock. Add and wire an instance separately; no revision was saved.",
        );
        return true;
      }
    } catch (e) {
      if (valid(mine, accepted)) setError(String(e));
    } finally {
      if (mounted.current && epoch.current === mine) setBusy(false);
    }
    return false;
  }
  async function instantiate() {
    const px = Number(x),
      py = Number(y);
    if (
      !x.trim() ||
      !y.trim() ||
      !Number.isFinite(px) ||
      !Number.isFinite(py)
    ) {
      setError("Canvas coordinates must be finite numbers.");
      return;
    }
    await mutate(
      "/instantiate",
      { definition: selected, x: px, y: py },
      "Activity instance added. Connect every required input.",
      selected,
    );
  }
  async function inspect() {
    if (!shown || !item || busy) return;
    const mine = ++epoch.current,
      owned = key,
      parent = program;
    setBusy(true);
    setError("");
    setInspection(null);
    try {
      const doc = await sourceJsonDocument(ACTIVITY_BASE + "/definition", {
        program: parent,
        definition: selected,
      });
      if (
        doc.data.scan_seconds !== parent.scan_seconds ||
        !sourceEqual(doc.data.target, parent.target) ||
        libraryVersion(doc.data) !== 2
      )
        throw new Error(
          "Activity inspection changed the parent clock or library context.",
        );
      if (valid(mine, owned)) setInspection(doc.data);
    } catch (e) {
      if (valid(mine, owned)) setError(String(e));
    } finally {
      if (mounted.current && epoch.current === mine) setBusy(false);
    }
  }
  async function checkedArchive(
    path: string,
    body: Data,
    expected?: Data,
    expectedDigest?: string,
  ) {
    const doc = await programJsonDocument(ACTIVITY_BASE + path, body, true);
    const digest = await sha256Blob(doc.blob);
    if (
      doc.blob.size > 8 * 1024 * 1024 ||
      digest !== doc.headers?.get("X-File-SHA256") ||
      (expectedDigest && digest !== expectedDigest)
    )
      throw new Error(
        "Original activity archive failed its byte SHA-256 check.",
      );
    const bundle = parseSourceDocument(await doc.blob.text());
    if (
      bundle?.format !== "bms-macro-library/2" ||
      bundle.library?.version !== 2 ||
      !Array.isArray(bundle.library.definitions) ||
      bundle.library.definitions.length > 64 ||
      (expected && !sourceEqual(bundle, expected))
    )
      throw new Error(
        "Activity archive differs from the reviewed version-two source.",
      );
    return { ...doc, bundle };
  }
  async function exportDefinition() {
    if (!shown || !item || busy) return;
    const mine = ++epoch.current,
      owned = key,
      parent = program,
      id = selected;
    setBusy(true);
    setError("");
    try {
      const doc = await checkedArchive(
        "/export",
        { program: parent, definition: id },
        undefined,
        item.archive_sha256,
      );
      if (doc.bundle.root !== id)
        throw new Error("Activity archive has a different root definition.");
      if (valid(mine, owned)) saveBlob(doc.blob, id + ".bms-activities.json");
    } catch (e) {
      if (valid(mine, owned)) setError(String(e));
    } finally {
      if (mounted.current && epoch.current === mine) setBusy(false);
    }
  }
  async function importFile(file: File) {
    if (!shown || busy) return;
    const mine = ++epoch.current,
      owned = key;
    setBusy(true);
    setError("");
    setPromotion(null);
    let bundle: Data;
    try {
      if (file.size > 8 * 1024 * 1024)
        throw new Error("Activity archive exceeds the 8 MiB import limit.");
      bundle = parseSourceDocument(await file.text());
      if (bundle.format === "bms-macro-library/1") {
        const doc = await sourceJsonDocument(
          ACTIVITY_BASE + "/migration/bundle-preview",
          { bundle },
        );
        const data = await activityProfile(doc.data);
        const manifest = {
          format: data.format,
          version: 1,
          profile_sha256: data.profile_sha256,
          source_bundle_sha256: data.source_bundle_sha256,
          bundle_sha256: data.bundle_sha256,
          rewrites_sha256: data.rewrites_sha256,
        };
        if (
          data.format !== "bms.activity-bundle-migration-preview" ||
          data.version !== 1 ||
          data.can_apply !== true ||
          !hash(data.source_bundle_sha256) ||
          !hash(data.bundle_sha256) ||
          !hash(data.rewrites_sha256) ||
          !hash(data.review_sha256) ||
          !Array.isArray(data.rewrites) ||
          data.rewrites.length > 20000 ||
          (await manifestSha256(data.rewrites)) !== data.rewrites_sha256 ||
          (await manifestSha256(manifest)) !== data.review_sha256 ||
          data.bundle?.format !== "bms-macro-library/2" ||
          data.bundle.root !== bundle.root ||
          data.bundle.library?.version !== 2
        )
          throw new Error(
            "Bundle promotion review does not match the supported source/profile contract.",
          );
        if (valid(mine, owned))
          setPromotion({
            original: file,
            bundle,
            data,
            blob: doc.blob,
            key: owned,
          });
        return;
      }
      if (bundle.format !== "bms-macro-library/2")
        throw new Error(
          "Choose a supported version-one or version-two reusable library archive.",
        );
    } catch (e) {
      if (valid(mine, owned)) setError(String(e));
      return;
    } finally {
      if (mounted.current && epoch.current === mine) setBusy(false);
    }
    if (valid(mine, owned))
      await mutate(
        "/import",
        { bundle },
        "Version-two activity archive imported. Existing conflicts were preserved.",
      );
  }
  async function promote(download: boolean) {
    if (!shown || !promotion || promotion.key !== key || busy) return;
    const accepted = promotion,
      mine = ++epoch.current,
      owned = key;
    setBusy(true);
    setError("");
    let bundle: Data | undefined;
    try {
      const doc = await checkedArchive(
        "/migration/bundle-export",
        {
          bundle: accepted.bundle,
          profile_sha256: accepted.data.profile_sha256,
          review_sha256: accepted.data.review_sha256,
        },
        accepted.data.bundle,
        accepted.data.bundle_sha256,
      );
      if (valid(mine, owned)) {
        if (download)
          saveBlob(doc.blob, doc.bundle.root + ".bms-activities.json");
        else bundle = doc.bundle;
      }
    } catch (e) {
      if (valid(mine, owned)) setError(String(e));
    } finally {
      if (mounted.current && epoch.current === mine) setBusy(false);
    }
    if (bundle && valid(mine, owned))
      await mutate(
        "/import",
        { bundle },
        "Explicitly promoted version-one bundle imported as activities.",
      );
  }
  const references = (id: string) =>
    [
      program,
      ...(program.metadata.macros?.definitions || []).map(
        (definition: Data) => definition.program,
      ),
    ].some((graph: Data) =>
      graph.nodes?.some(
        (node: Data) =>
          node.kind === "Activity" && node.params?.definition === id,
      ),
    );
  return (
    <section
      className="activity-library"
      aria-label="Reusable multi-output activities"
    >
      <header className="macro-library-header">
        <div>
          <span className="macro-eyebrow">NAMED OUTPUTS · VERSION 2</span>
          <h1>Reusable activities</h1>
          <p>
            One shared control graph can publish several named numeric or
            Boolean outputs. Instances retain independent state.
          </p>
        </div>
        <div className="button-row">
          <input
            ref={input}
            hidden
            type="file"
            accept=".json,.bms-macro.json,.bms-activities.json,application/json"
            aria-label="Import activity bundle file"
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (file) void importFile(file);
            }}
          />
          <button
            disabled={!shown || busy}
            onClick={() => input.current?.click()}
          >
            Import activity archive
          </button>
          <button disabled={busy} onClick={() => void reload(true)}>
            Reload activity criteria
          </button>
          <span className="activity-count">
            {definitions.length}{" "}
            {definitions.length === 1 ? "definition" : "definitions"}
          </span>
        </div>
      </header>
      {busy && (
        <div className="button-row">
          <p role="status">Preparing local activity source…</p>
          <button
            onClick={() => {
              epoch.current++;
              setBusy(false);
              setPromotion(null);
              setInspection(null);
              setError("Pending activity response discarded.");
            }}
          >
            Discard pending activity response
          </button>
        </div>
      )}
      {error && (
        <p className="macro-message macro-error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="macro-message macro-notice" role="status">
          {notice}
        </p>
      )}
      {shown?.diagnostics.map((diagnostic: Data, index: number) => (
        <p key={index}>
          {diagnostic.level}: {diagnostic.message}
        </p>
      ))}
      {shown && !shown.bindings && (
        <p className="help-text">
          This graph is unfinished or not executable. Declared ports remain
          visible; output force authority is unavailable until validation
          succeeds.
        </p>
      )}
      <CWIsolationOutputTemplate
        program={program}
        sourceEpoch={sourceEpoch}
        authorityReady={!!shown}
        disabled={!shown || busy}
        onImport={importCWTemplate}
      />
      {promotion?.key === key && (
        <section
          className="macro-card"
          aria-label="Version-one bundle promotion review"
        >
          <h2>Review version-one bundle promotion</h2>
          <p>
            {promotion.data.rewrites.length} explicit container/port rewrites.
            Source archive: <code>{promotion.data.source_bundle_sha256}</code>
          </p>
          <details>
            <summary>Bundle source rewrites</summary>
            <pre>{sourceStringify(promotion.data.rewrites, 2)}</pre>
          </details>
          <p>
            Promotion changes the archive format deliberately. It imports no
            live state, forces or hardware association.
          </p>
          <div className="button-row">
            <button disabled={busy} onClick={() => void promote(false)}>
              Promote and import reviewed bundle
            </button>
            <button disabled={busy} onClick={() => void promote(true)}>
              Download original promoted bundle
            </button>
            <button
              onClick={() =>
                saveBlob(
                  promotion.blob,
                  "activity-bundle-promotion-response.json",
                )
              }
            >
              Download original promotion response
            </button>
            <button
              onClick={() =>
                saveBlob(promotion.original, promotion.original.name)
              }
            >
              Download original version-one bundle
            </button>
            <button disabled={busy} onClick={() => setPromotion(null)}>
              Dismiss bundle promotion
            </button>
          </div>
        </section>
      )}
      <div className="macro-library-layout">
        <aside className="macro-library-sidebar">
          <section className="macro-card">
            <h2>Create from selection</h2>
            <p>
              {selectedIds.length} selected blocks. Keep root Input and Output
              blocks outside the selection. Each distinct outgoing result
              becomes a named output.
            </p>
            <label>
              Activity name
              <input
                aria-label="Activity name"
                value={name}
                maxLength={200}
                onChange={(event) => setName(event.target.value)}
              />
            </label>
            <button
              className="primary"
              disabled={!shown || busy || !selectedIds.length || !name.trim()}
              onClick={() => void create()}
            >
              Create multi-output activity
            </button>
          </section>
          <section className="macro-card">
            <h2>Definitions</h2>
            {definitions.map((definition) => (
              <button
                key={definition.id}
                className={
                  selected === definition.id
                    ? "activity-definition selected"
                    : "activity-definition"
                }
                onClick={() => {
                  setSelected(definition.id);
                  setInspection(null);
                  setError("");
                }}
              >
                <b>{definition.name}</b>
                <code>{definition.id}</code>
                <small>
                  {definition.input_contracts.length} required inputs ·{" "}
                  {definition.outputs.length} outputs
                </small>
              </button>
            ))}
          </section>
        </aside>
        <div className="macro-library-detail">
          {item ? (
            <section
              className="macro-card"
              aria-label="Selected activity definition"
            >
              <h2>{item.name}</h2>
              <code>{item.id}</code>
              <table
                className="macro-table"
                aria-label="Activity port contracts"
              >
                <thead>
                  <tr>
                    <th>Direction</th>
                    <th>Port</th>
                    <th>Type</th>
                    <th>Unit</th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    ...item.input_contracts.map((port: Data) => ({
                      ...port,
                      direction: "Required input",
                    })),
                    ...item.outputs.map((port: Data) => ({
                      ...port,
                      direction: "Output",
                    })),
                  ].map((port: Data) => (
                    <tr key={port.direction + port.id}>
                      <td>{port.direction}</td>
                      <td>
                        <code>{port.id}</code> · {port.label}
                      </td>
                      <td>{port.value_type}</td>
                      <td>{port.unit || "dimensionless"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="form-grid">
                <label>
                  Activity canvas X
                  <input
                    aria-label="Activity canvas X"
                    value={x}
                    type="number"
                    onChange={(event) => setX(event.target.value)}
                  />
                </label>
                <label>
                  Activity canvas Y
                  <input
                    aria-label="Activity canvas Y"
                    value={y}
                    type="number"
                    onChange={(event) => setY(event.target.value)}
                  />
                </label>
              </div>
              <div className="button-row">
                <button disabled={busy} onClick={() => void instantiate()}>
                  Add activity instance to program
                </button>
                <button disabled={busy} onClick={() => void inspect()}>
                  Inspect activity graph
                </button>
                <button
                  disabled={busy}
                  onClick={() => onEditDefinition?.(item.id)}
                >
                  Edit activity graph
                </button>
                <button disabled={busy} onClick={() => void exportDefinition()}>
                  Export original activity archive
                </button>
                <button
                  className="danger"
                  disabled={busy || references(item.id)}
                  onClick={() => {
                    if (
                      window.confirm(`Delete unused activity “${item.name}”?`)
                    )
                      void mutate(
                        "/delete",
                        { definition: item.id },
                        "Unused activity definition deleted.",
                        "",
                      );
                  }}
                >
                  Delete unused activity
                </button>
              </div>
              {inspection && (
                <section aria-label="Activity graph inspection">
                  <h3>{inspection.name}</h3>
                  <table className="macro-table">
                    <thead>
                      <tr>
                        <th>Block</th>
                        <th>Kind</th>
                        <th>Parameters</th>
                      </tr>
                    </thead>
                    <tbody>
                      {inspection.nodes.map((node) => (
                        <tr key={node.id} onClick={() => onSelect?.(node.id)}>
                          <td>{node.id}</td>
                          <td>{node.kind}</td>
                          <td>
                            <code>{sourceStringify(node.params)}</code>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <details>
                    <summary>Activity connections</summary>
                    <pre>{sourceStringify(inspection.edges, 2)}</pre>
                  </details>
                </section>
              )}
            </section>
          ) : (
            <section className="macro-card">
              <h2>Select an activity</h2>
              <p>
                Create a reusable selection or import an explicit version-two
                archive. Version-one archives require a reviewed promotion.
              </p>
            </section>
          )}
          <section className="macro-card">
            <h2>Source and execution limits</h2>
            <p>
              Each Activity is a container, with no default scalar output. Wire
              named output handles and inspect or force each port separately in
              the Program editor after validation. Root outputs alone are
              published.
            </p>
            <p>
              Quality faults retain the prior committed state and outputs.
              Source edits reset the editor's local simulation and retire stale
              force aliases. Native host internal-port forcing, physical IO and
              native JCI/ALC deployment are not established.
            </p>
            <p>
              Reloading activity criteria retires the local calculation session
              and clears its time, history and forces before new output
              authority is accepted.
            </p>
            {shown && (
              <details>
                <summary>Activity criteria</summary>
                <code>{shown.profile_sha256}</code>
                <pre>{sourceStringify(shown.profile, 2)}</pre>
              </details>
            )}
          </section>
        </div>
      </div>
    </section>
  );
}
