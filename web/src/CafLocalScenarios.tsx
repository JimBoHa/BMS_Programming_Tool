import { useEffect, useRef, useState } from "react";
import { api, download, saveBlob } from "./api";

type Input = {
  id: string;
  ref: string;
  property_id: string;
  class_id: string;
  class_version: string;
  name: string;
  native_type: string;
  units_native: unknown;
  unit_status: string;
  initial_value: string;
};
type Sample = { value: string; quality: string };
type Event = { time: number; values: Record<string, Sample> };
type Scenario = {
  format: string;
  version: number;
  source_sha256: string;
  profile_sha256: string;
  inputs: Input[];
  name: string;
  description: string;
  duration: number;
  dt: number;
  events: Event[];
};
type Saved = { id: string; revision: number; name: string; updated: string };
type Trace = {
  scope: string;
  frames: { time: number; inputs: Record<string, Sample> }[];
};

export function CafLocalScenarios({
  sha,
  filename,
  visible,
  parentBusy,
  onDirtyChange,
}: {
  sha: string;
  filename: string;
  visible: boolean;
  parentBusy: boolean;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const [template, setTemplate] = useState<Scenario | null>(null);
  const [draft, setDraft] = useState<Scenario | null>(null);
  const [savedSignature, setSavedSignature] = useState("");
  const [identity, setIdentity] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const [saved, setSaved] = useState<Saved[]>([]);
  const [selected, setSelected] = useState("");
  const [qualities, setQualities] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [input, setInput] = useState("");
  const [time, setTime] = useState("0");
  const [value, setValue] = useState("");
  const [quality, setQuality] = useState("good");
  const [trace, setTrace] = useState<Trace | null>(null);
  const [cursor, setCursor] = useState(0);
  const importer = useRef<HTMLInputElement>(null);
  const mounted = useRef(false);
  const visibleNow = useRef(visible);
  visibleNow.current = visible;
  const liveSignature = useRef("");
  const signature = JSON.stringify(draft);
  liveSignature.current = signature;
  const dirty = !!draft && signature !== savedSignature;
  const disabled = busy || parentBusy || !visible;
  const supported = !!draft?.inputs.length;
  const frame = trace?.frames[cursor];

  useEffect(() => {
    mounted.current = true;
    setBusy(true);
    api(`/caf/${sha}/local-scenarios`)
      .then((result) => {
        if (!mounted.current) return;
        setTemplate(result.template);
        setDraft(result.template);
        setSavedSignature(JSON.stringify(result.template));
        setSaved(result.saved);
        setQualities(result.contract.qualities);
        const first = result.template.inputs[0];
        if (first) {
          setInput(first.id);
          setValue(first.initial_value);
        }
      })
      .catch((e) => {
        if (mounted.current) setError(String(e.message || e));
      })
      .finally(() => {
        if (mounted.current) setBusy(false);
      });
    return () => {
      mounted.current = false;
    };
  }, [sha]);
  useEffect(() => {
    onDirtyChange(dirty);
    return () => onDirtyChange(false);
  }, [dirty, onDirtyChange]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  function update(next: Scenario) {
    setDraft(next);
    setTrace(null);
    setCursor(0);
    setError("");
    setMessage("");
  }
  function discard() {
    return (
      !dirty || window.confirm("Discard unsaved local input scenario changes?")
    );
  }
  async function perform(action: () => Promise<void>) {
    if (disabled) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await action();
    } catch (e) {
      if (mounted.current) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (mounted.current) setBusy(false);
    }
  }
  async function refresh() {
    const result = await api(`/caf/${sha}/local-scenarios`);
    if (mounted.current) setSaved(result.saved);
  }
  function addEvent() {
    if (!draft || disabled) return;
    const seconds = Number(time);
    if (
      !time.trim() ||
      !Number.isFinite(seconds) ||
      seconds < 0 ||
      seconds > draft.duration
    ) {
      setError("Event time must be finite and within the scenario duration.");
      return;
    }
    const events = draft.events.map((event) => ({
      ...event,
      values: { ...event.values },
    }));
    const event = events.find((row) => row.time === seconds);
    if (event) event.values[input] = { value, quality };
    else
      events.push({ time: seconds, values: { [input]: { value, quality } } });
    events.sort((a, b) => a.time - b.time);
    update({ ...draft, events });
  }
  function removeEvent(seconds: number, id: string) {
    if (!draft || disabled) return;
    update({
      ...draft,
      events: draft.events
        .map((event) => ({
          ...event,
          values: Object.fromEntries(
            Object.entries(event.values).filter(
              ([key]) => event.time !== seconds || key !== id,
            ),
          ),
        }))
        .filter((event) => Object.keys(event.values).length),
    });
  }
  function create() {
    if (!template || disabled || !discard()) return;
    update(structuredClone(template));
    setSavedSignature(JSON.stringify(template));
    setIdentity(null);
    setRevision(0);
    setSelected("");
  }
  async function save(copy: boolean) {
    if (!draft) return;
    const snapshot = draft;
    await perform(async () => {
      const result = await api(`/caf/${sha}/local-scenarios/save`, {
        scenario: snapshot,
        id: copy ? null : identity,
        expected_revision: copy ? 0 : revision,
      });
      if (!mounted.current) return;
      setIdentity(result.id);
      setRevision(result.revision);
      setSelected(result.id);
      setSavedSignature(JSON.stringify(snapshot));
      await refresh();
      if (mounted.current)
        setMessage(`Saved locally, revision ${result.revision}.`);
    });
  }
  async function reopen() {
    if (!selected || !discard()) return;
    await perform(async () => {
      const result = await api(`/caf/${sha}/local-scenarios/${selected}`);
      if (!mounted.current) return;
      update(result.scenario);
      setSavedSignature(JSON.stringify(result.scenario));
      setIdentity(result.id);
      setRevision(result.revision);
      setMessage(
        "Saved local input scenario reopened and revalidated against this CAF.",
      );
    });
  }
  async function removeSaved() {
    if (
      !identity ||
      !window.confirm(
        "Delete this saved local input scenario? The source CAF is unchanged.",
      )
    )
      return;
    await perform(async () => {
      await api(
        `/caf/${sha}/local-scenarios/${identity}`,
        { expected_revision: revision },
        "DELETE",
      );
      if (!mounted.current) return;
      setIdentity(null);
      setRevision(0);
      setSelected("");
      setSavedSignature("");
      await refresh();
      if (mounted.current)
        setMessage("Saved copy deleted. Draft remains available.");
    });
  }
  async function importFile(file?: File) {
    if (!file || !draft || !discard()) return;
    await perform(async () => {
      if (file.size > 2 * 1024 * 1024)
        throw new Error("Local input scenario exceeds 2 MiB.");
      const result = await api(`/caf/${sha}/local-scenarios/validate`, {
        scenario: JSON.parse(await file.text()),
      });
      if (!mounted.current) return;
      update(result.scenario);
      setIdentity(null);
      setRevision(0);
      setSelected("");
      setSavedSignature("");
      setMessage(
        "Imported local input scenario. Save locally to retain it after restart.",
      );
    });
  }
  async function exportJson() {
    if (!draft) return;
    const snapshot = draft;
    const expected = signature;
    await perform(async () => {
      const result = await api(`/caf/${sha}/local-scenarios/validate`, {
        scenario: snapshot,
      });
      if (
        !mounted.current ||
        !visibleNow.current ||
        liveSignature.current !== expected
      )
        return;
      saveBlob(
        new Blob([JSON.stringify(result.scenario, null, 2) + "\n"], {
          type: "application/json",
        }),
        "caf-local-input-scenario.json",
      );
      setMessage(
        "Validated local input scenario JSON download requested. This is not a native CCT scenario format.",
      );
    });
  }
  async function preview() {
    if (!draft) return;
    const snapshot = draft;
    const expected = signature;
    await perform(async () => {
      const result = await api(`/caf/${sha}/local-scenarios/preview`, {
        scenario: snapshot,
      });
      if (!mounted.current || liveSignature.current !== expected) return;
      setTrace(result);
      setCursor(0);
      setMessage(
        `${result.frames.length} input-stimulus frames prepared. No native logic or outputs executed.`,
      );
    });
  }
  async function exportStartup() {
    if (!draft || !frame) return;
    const snapshot = draft;
    const expected = signature;
    const current = () =>
      mounted.current &&
      visibleNow.current &&
      liveSignature.current === expected;
    await perform(async () => {
      const result = await api(`/caf/${sha}/local-scenarios/startup-profile`, {
        scenario: snapshot,
        time: frame.time,
      });
      if (!current()) return;
      const name =
        filename.replace(/\.caf$/i, "") + `-startup-${frame.time}s.caf`;
      const downloaded = await download(
        `/caf/${sha}/simulation`,
        { profile: result.profile },
        name,
        current,
      );
      if (downloaded && current())
        setMessage(
          "Startup CAF download requested through the guarded native scalar editor. No trajectory or quality structures encoded; CCT/PCT acceptance remains unverified.",
        );
    });
  }

  return (
    <section
      className="caf-local-scenarios"
      aria-label="Local CAF input scenarios"
    >
      <h2>Local CAF input scenarios</h2>
      <p>
        Save named value and quality trajectories for supported saved input
        records. Preview shows input stimuli only. Native CAF logic and
        controller outputs are not executed.
      </p>
      <p>
        Time starts at zero seconds. Values hold until an event, which applies
        at its exact time. Quality is local metadata. Unknown units stay
        unknown; values use native scalar text without conversion.
      </p>
      {error && (
        <div role="alert" className="caf-simulation-error">
          {error}
        </div>
      )}
      {message && (
        <div role="status" className="caf-simulation-message">
          {message}
        </div>
      )}
      {!draft ? (
        <p>Loading local input contract…</p>
      ) : !supported ? (
        <p>
          No supported saved Input Float or Input Boolean startup records.
          Output blocks, enums and unknown records cannot become local inputs.
        </p>
      ) : (
        <>
          <p>
            <code>Input profile SHA-256 {draft.profile_sha256}</code> ·{" "}
            {draft.inputs.length} supported inputs ·{" "}
            {identity ? `saved revision ${revision}` : "new scenario"}
            {dirty ? " · unsaved changes" : ""}
          </p>
          <div className="caf-simulation-toolbar">
            <button disabled={disabled} onClick={create}>
              New local scenario
            </button>
            <select
              aria-label="Saved local input scenarios"
              value={selected}
              disabled={disabled}
              onChange={(e) => setSelected(e.target.value)}
            >
              <option value="">Choose saved scenario</option>
              {saved.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name} · revision {item.revision}
                </option>
              ))}
            </select>
            <button
              disabled={disabled || !selected}
              onClick={() => void reopen()}
            >
              Reopen local scenario
            </button>
            <button disabled={disabled} onClick={() => void perform(refresh)}>
              Refresh saved scenarios
            </button>
          </div>
          <div className="caf-local-fields">
            <label>
              Scenario name
              <input
                aria-label="Local scenario name"
                maxLength={120}
                value={draft.name}
                disabled={disabled}
                onChange={(e) => update({ ...draft, name: e.target.value })}
              />
            </label>
            <label>
              Description
              <textarea
                aria-label="Local scenario description"
                maxLength={2000}
                value={draft.description}
                disabled={disabled}
                onChange={(e) =>
                  update({ ...draft, description: e.target.value })
                }
              />
            </label>
            <label>
              Duration, seconds
              <input
                aria-label="Local scenario duration"
                type="number"
                min="0.001"
                max="86400"
                value={draft.duration}
                disabled={disabled}
                onChange={(e) =>
                  update({ ...draft, duration: Number(e.target.value) })
                }
              />
            </label>
            <label>
              Preview interval, seconds
              <input
                aria-label="Local scenario interval"
                type="number"
                min="0.001"
                max="60"
                step="any"
                value={draft.dt}
                disabled={disabled}
                onChange={(e) =>
                  update({ ...draft, dt: Number(e.target.value) })
                }
              />
            </label>
          </div>
          <details>
            <summary>
              Exact input identities, initial values and native unit metadata
            </summary>
            <div className="caf-local-table">
              <table>
                <thead>
                  <tr>
                    <th>Input</th>
                    <th>Type and units</th>
                    <th>Initial stimulus</th>
                  </tr>
                </thead>
                <tbody>
                  {draft.inputs.map((row) => (
                    <tr key={row.id}>
                      <td>
                        {row.name}
                        <code>{row.id}</code>
                        <small>
                          Class {row.class_id} / {row.class_version}
                        </small>
                      </td>
                      <td>
                        {row.native_type}
                        <small>
                          {row.unit_status === "unknown"
                            ? "Units unknown"
                            : `Raw native units: ${JSON.stringify(row.units_native)}`}
                        </small>
                      </td>
                      <td>{row.initial_value} · locally assumed good</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
          <div className="caf-local-fields">
            <label>
              Event time, seconds
              <input
                aria-label="Local event time"
                type="number"
                step="any"
                value={time}
                disabled={disabled}
                onChange={(e) => setTime(e.target.value)}
              />
            </label>
            <label>
              Input
              <select
                aria-label="Local event input"
                value={input}
                disabled={disabled}
                onChange={(e) => {
                  setInput(e.target.value);
                  setValue(
                    draft.inputs.find((row) => row.id === e.target.value)!
                      .initial_value,
                  );
                }}
              >
                {draft.inputs.map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.ref} · {row.name} ({row.native_type})
                  </option>
                ))}
              </select>
            </label>
            <label>
              Native scalar text
              <input
                aria-label="Local event value"
                value={value}
                disabled={disabled}
                onChange={(e) => setValue(e.target.value)}
              />
            </label>
            <label>
              Local quality
              <select
                aria-label="Local event quality"
                value={quality}
                disabled={disabled}
                onChange={(e) => setQuality(e.target.value)}
              >
                {qualities.map((item) => (
                  <option key={item}>{item}</option>
                ))}
              </select>
            </label>
          </div>
          <button disabled={disabled} onClick={addEvent}>
            Add or replace input event
          </button>
          <p>
            Same time and input replaces that sample. Different inputs at the
            same time share one event. Save, preview and export validate scalar
            types and resource bounds.
          </p>
          <div className="caf-local-table">
            <table aria-label="Local scenario events">
              <thead>
                <tr>
                  <th>Seconds</th>
                  <th>Exact input</th>
                  <th>Value</th>
                  <th>Local quality</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {draft.events.flatMap((event) =>
                  Object.entries(event.values).map(([id, sample]) => (
                    <tr key={`${event.time}:${id}`}>
                      <td>{event.time}</td>
                      <td>
                        <code>{id}</code>
                      </td>
                      <td>{sample.value}</td>
                      <td>{sample.quality}</td>
                      <td>
                        <button
                          disabled={disabled}
                          onClick={() => {
                            setTime(String(event.time));
                            setInput(id);
                            setValue(sample.value);
                            setQuality(sample.quality);
                          }}
                        >
                          Edit sample
                        </button>
                        <button
                          disabled={disabled}
                          onClick={() => removeEvent(event.time, id)}
                        >
                          Remove sample
                        </button>
                      </td>
                    </tr>
                  )),
                )}
              </tbody>
            </table>
            {!draft.events.length && (
              <p>
                No events. Preview holds the CAF's saved input startup values.
              </p>
            )}
          </div>
          <div className="caf-simulation-toolbar">
            <button disabled={disabled} onClick={() => void save(false)}>
              Save local scenario
            </button>
            <button
              disabled={disabled || !identity}
              onClick={() => void save(true)}
            >
              Save local copy
            </button>
            <button
              disabled={disabled || !identity}
              onClick={() => void removeSaved()}
            >
              Delete saved scenario
            </button>
            <button disabled={disabled} onClick={() => void exportJson()}>
              Export local scenario JSON
            </button>
            <button
              disabled={disabled}
              onClick={() => importer.current?.click()}
            >
              Import local scenario JSON
            </button>
            <button disabled={disabled} onClick={() => void preview()}>
              Preview input stimuli
            </button>
          </div>
          <input
            hidden
            ref={importer}
            type="file"
            accept=".json,application/json"
            aria-label="Local input scenario JSON"
            onChange={(e) => {
              void importFile(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
          {trace && frame && (
            <div aria-label="Input stimulus preview" role="region">
              <p>
                <strong>{trace.scope}</strong>
              </p>
              <label>
                Preview frame
                <select
                  aria-label="Input stimulus frame"
                  disabled={disabled}
                  value={cursor}
                  onChange={(e) => setCursor(Number(e.target.value))}
                >
                  {trace.frames.map((row, index) => (
                    <option key={row.time} value={index}>
                      {row.time} seconds
                    </option>
                  ))}
                </select>
              </label>
              <div className="caf-local-table">
                <table>
                  <thead>
                    <tr>
                      <th>Exact input</th>
                      <th>Value</th>
                      <th>Local quality</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(frame.inputs).map(([id, sample]) => (
                      <tr key={id}>
                        <td>
                          <code>{id}</code>
                        </td>
                        <td>{sample.value}</td>
                        <td>{sample.quality}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="caf-simulation-toolbar">
                <button
                  disabled={disabled}
                  onClick={() =>
                    saveBlob(
                      new Blob([JSON.stringify(trace, null, 2) + "\n"], {
                        type: "application/json",
                      }),
                      "caf-local-input-preview.json",
                    )
                  }
                >
                  Export input preview JSON
                </button>
                <button
                  disabled={
                    disabled ||
                    Object.values(frame.inputs).some(
                      (sample) => sample.quality !== "good",
                    )
                  }
                  onClick={() => void exportStartup()}
                >
                  Export startup CAF at preview time
                </button>
              </div>
              <p>
                Startup CAF export copies only supported native scalar values
                from an all-good frame. Local quality and the trajectory are
                never encoded into the CAF. The existing saved-value editor
                validates the separate copy; matching CCT/PCT acceptance remains
                unverified.
              </p>
            </div>
          )}
          <p>
            Saved scenarios persist in this computer's local application data.
            Reopen this exact source CAF after an application restart to
            revalidate and reuse them. The scenario store does not retain the
            CAF itself.
          </p>
        </>
      )}
    </section>
  );
}
