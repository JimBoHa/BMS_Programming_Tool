import { useEffect, useRef, useState } from "react";
import { apiJsonDocument, saveBlob } from "./api";
import {
  bundleInspectionBase,
  checkedBatchBundle,
  type CheckedBatchBundle,
} from "./nativeBatchBundleInspectionContract";
import { batchEvidenceLimit } from "./nativeDefaultBatchEvidenceContract";
import { batchMatchValue } from "./nativeDefaultBatchResultMatchContract";

type Selection = { file: File };
type Inspection = CheckedBatchBundle & {
  owner: string;
  epoch: number;
  selection: Selection;
  originalReport: Blob;
};
const text = (v: unknown) => (Object.is(v, -0) ? "-0" : String(v));

export function NativeBatchBundleInspection({
  contextKey,
}: {
  contextKey: string;
}) {
  const [file, setFile] = useState<File | null>(null),
    [pending, setPending] = useState(false),
    [error, setError] = useState(""),
    [inspection, setInspection] = useState<Inspection | null>(null);
  const picker = useRef<HTMLInputElement>(null),
    alive = useRef(true),
    present = useRef(true),
    surface = useRef(false),
    epoch = useRef(0),
    selected = useRef<Selection | null>(null),
    active = useRef<object | null>(null);
  // Disclosure/lifetime ownership changes synchronously through epoch. Native
  // toggle delivery is delayed and must not invalidate a newly selected file.
  const owner = contextKey;
  const actual = useRef(owner);
  if (actual.current !== owner) {
    actual.current = owner;
    epoch.current++;
    active.current = null;
  }
  function retire() {
    epoch.current++;
    active.current = null;
    setPending(false);
    setInspection(null);
    setError("");
  }
  const current = (key: string, ticket: number, choice: Selection) =>
    alive.current &&
    present.current &&
    surface.current &&
    window.document.visibilityState !== "hidden" &&
    actual.current === key &&
    epoch.current === ticket &&
    selected.current === choice;
  useEffect(() => {
    alive.current = true;
    const hide = () => {
      present.current = false;
      retire();
    };
    const show = () => {
      present.current = true;
      retire();
    };
    const visibility = () => {
      present.current = window.document.visibilityState !== "hidden";
      retire();
    };
    window.addEventListener("pagehide", hide);
    window.addEventListener("pageshow", show);
    window.document.addEventListener("visibilitychange", visibility);
    return () => {
      alive.current = false;
      epoch.current++;
      active.current = null;
      window.removeEventListener("pagehide", hide);
      window.removeEventListener("pageshow", show);
      window.document.removeEventListener("visibilitychange", visibility);
    };
  }, []);
  useEffect(() => {
    setPending(false);
    setInspection(null);
    setError("");
  }, [owner]);
  const shown =
    inspection &&
    current(inspection.owner, inspection.epoch, inspection.selection)
      ? inspection
      : null;

  async function inspect(choice: Selection) {
    retire();
    const ticket = epoch.current,
      key = actual.current;
    if (!current(key, ticket, choice)) return;
    if (
      !choice.file.size ||
      choice.file.size > batchEvidenceLimit ||
      choice.file.name.length > 1024
    ) {
      setError("Choose a comparison evidence ZIP of at most 20 MiB.");
      return;
    }
    const operation = {};
    active.current = operation;
    setPending(true);
    try {
      const form = new FormData();
      form.append("file", choice.file);
      const reply = await apiJsonDocument(bundleInspectionBase, form);
      if (!current(key, ticket, choice)) return;
      const checked = await checkedBatchBundle(reply.data, choice.file);
      if (!current(key, ticket, choice)) return;
      if (!checked)
        throw Error(
          "The inspection does not match this exact bundle. Choose the original exported comparison evidence ZIP again.",
        );
      setInspection({
        ...checked,
        owner: key,
        epoch: ticket,
        selection: choice,
        originalReport: reply.blob,
      });
    } catch (e) {
      if (current(key, ticket, choice)) setError(String(e));
    } finally {
      if (active.current === operation) {
        active.current = null;
        if (alive.current) setPending(false);
      }
    }
  }

  function saveMember(document: Inspection, name: string) {
    if (!current(document.owner, document.epoch, document.selection)) return;
    const entry = document.members.get(name);
    if (!entry) return;
    saveBlob(
      new Blob([Uint8Array.from(entry.content)], {
        type: name.endsWith(".zip") ? "application/zip" : "application/json",
      }),
      name.split("/").at(-1)!,
    );
  }

  return (
    <details
      aria-label="Portable comparison evidence inspection"
      onToggle={(event) => {
        const open = event.currentTarget.open;
        if (surface.current !== open) {
          surface.current = open;
          retire();
        }
      }}
    >
      <summary
        onClick={(event) => {
          surface.current =
            !event.currentTarget.parentElement!.hasAttribute("open");
          retire();
        }}
      >
        Inspect saved comparison evidence
      </summary>
      <p>
        Open a saved typed-batch comparison bundle on this computer. Inspection
        checks the bundled bytes and reconstructs their historical comparison in
        memory.
      </p>
      <input
        ref={picker}
        type="file"
        accept=".zip,application/zip"
        hidden
        aria-label="Comparison evidence ZIP"
        onChange={(event) => {
          const next = event.currentTarget.files?.[0];
          event.currentTarget.value = "";
          if (!next) return;
          const choice = { file: next };
          selected.current = choice;
          setFile(next);
          void inspect(choice);
        }}
      />
      <div className="button-row">
        <button
          className={!shown ? "primary" : ""}
          onClick={() => picker.current?.click()}
        >
          Open comparison evidence bundle
        </button>
        {file && !pending && (
          <button
            onClick={() => {
              if (selected.current) void inspect(selected.current);
            }}
          >
            Inspect selected bundle again
          </button>
        )}
        {pending && (
          <button onClick={retire}>Cancel evidence inspection</button>
        )}
      </div>
      {file && (
        <p>
          Local evidence file: {file.name} · {file.size} bytes. Controller
          selection is unchanged.
        </p>
      )}
      {pending && <p role="status">Checking comparison evidence…</p>}
      {error && <p role="alert">{error}</p>}
      {shown && (
        <section aria-label="Inspected comparison evidence">
          <p role="status">
            Bundle internally consistent. Historical application and values{" "}
            {shown.data.comparison.state === "application-and-values-match"
              ? "match the recorded result"
              : "have recorded differences"}
            .
          </p>
          <p>
            This is unsigned historical evidence. It does not verify the current
            controller, vendor provenance, complete backups or code acceptance.
            No capture, receipt, review or transfer was imported.
          </p>
          <dl>
            <dt>Original recorded controller</dt>
            <dd>
              {shown.data.comparison.recorded_identity["object-name"]} ·{" "}
              {shown.data.comparison.recorded_identity.device}
            </dd>
            <dt>Original recorded route</dt>
            <dd>
              {shown.data.comparison.recorded_target.address}
              {shown.data.comparison.recorded_target.router
                ? ` via ${shown.data.comparison.recorded_target.router} / DNET ${shown.data.comparison.recorded_target.dnet}`
                : ""}
            </dd>
            <dt>Compared capture route</dt>
            <dd>
              {shown.data.comparison.current_target.address}
              {shown.data.comparison.current_target.router
                ? ` via ${shown.data.comparison.current_target.router} / DNET ${shown.data.comparison.current_target.dnet}`
                : ""}
            </dd>
            <dt>Historical proof</dt>
            <dd>
              {shown.data.comparison.verified_proof.kind} ·{" "}
              {shown.data.comparison.verified_proof.time}
            </dd>
            <dt>Compared source time</dt>
            <dd>{shown.data.comparison.source.captured_at}</dd>
          </dl>
          <div className="change-ledger-table">
            <table aria-label="Bundled typed value comparison">
              <thead>
                <tr>
                  <th>Recorded field</th>
                  <th>Type</th>
                  <th>Recorded result</th>
                  <th>Bundled source</th>
                  <th>Comparison</th>
                </tr>
              </thead>
              <tbody>
                {shown.data.comparison.selected.map((row: any) => (
                  <tr key={row.record_ref}>
                    <td>{row.record_ref}</td>
                    <td>{row.kind}</td>
                    <td style={{ whiteSpace: "nowrap", textAlign: "right" }}>
                      {text(batchMatchValue(row.kind, row.expected))}
                    </td>
                    <td style={{ whiteSpace: "nowrap", textAlign: "right" }}>
                      {row.current
                        ? text(
                            batchMatchValue(
                              row.current.kind,
                              row.current.value,
                            ),
                          )
                        : "Not recorded"}
                    </td>
                    <td>{row.matches ? "Matches" : "Different"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="button-row">
            <button
              className="primary"
              onClick={() => {
                if (current(shown.owner, shown.epoch, shown.selection))
                  saveBlob(
                    shown.originalReport,
                    "native-batch-bundle-inspection.json",
                  );
              }}
            >
              Save inspection report
            </button>
            <button
              onClick={() => {
                if (current(shown.owner, shown.epoch, shown.selection))
                  saveBlob(
                    shown.selection.file,
                    "native-batch-evidence-original.zip",
                  );
              }}
            >
              Save original evidence bundle
            </button>
          </div>
          <details>
            <summary>Comparison details and original evidence</summary>
            <div className="change-ledger-table">
              <table aria-label="Bundled comparison checks">
                <thead>
                  <tr>
                    <th>Check</th>
                    <th>Recorded comparison</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(shown.data.comparison.comparisons).map(
                    ([name, matches]) => (
                      <tr key={name}>
                        <td>{name.replaceAll("_", " ")}</td>
                        <td>{matches ? "Matches" : "Different"}</td>
                      </tr>
                    ),
                  )}
                </tbody>
              </table>
            </div>
            <div className="change-ledger-table">
              <table aria-label="Original bundled evidence files">
                <thead>
                  <tr>
                    <th>Original member</th>
                    <th>Bytes</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.data.members.map((member: any) => (
                    <tr key={member.name}>
                      <td>{member.name}</td>
                      <td style={{ whiteSpace: "nowrap", textAlign: "right" }}>
                        {member.bytes}
                      </td>
                      <td>
                        <button onClick={() => saveMember(shown, member.name)}>
                          Save original {member.name}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </section>
      )}
    </details>
  );
}
