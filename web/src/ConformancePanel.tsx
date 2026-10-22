import { useEffect, useRef, useState } from "react";
import {
  api,
  apiJsonDocument,
  download,
  saveBlob,
  type JsonDocument,
} from "./api";
import type { Program } from "./types";
import "./conformance.css";
type Data = Record<string, any>;
const clock = () => "2026-01-05T00:00:00Z";
const identifier = (prefix: string) =>
  prefix + "_" + crypto.randomUUID().replaceAll("-", "").slice(0, 16);
function value(text: string, type: string) {
  if (type === "boolean") {
    if (text !== "true" && text !== "false")
      throw new Error("Enter exactly true or false for a Boolean value.");
    return text === "true";
  }
  if (!text.trim() || !Number.isFinite(Number(text)))
    throw new Error("Enter a finite numeric value.");
  // Reject integer literals before JSON/Number can silently round their value.
  if (
    /^[+-]?\d+(?:\.0*)?$/.test(text.trim()) &&
    BigInt(text.trim().split(".")[0]) !== BigInt(Number(text))
  )
    throw new Error("Integer value must be exactly representable as binary64.");
  return Number(text);
}
function freshCase(dt: number): Data {
  return {
    id: identifier("case"),
    name: "New test case",
    description: "",
    duration: 10,
    dt,
    start_clock: clock(),
    events: [],
    checks: [],
    expected_fault: null,
  };
}
function validCase(row: Data, expected: Data) {
  const arrays = [
    "asserted_outputs",
    "unasserted_outputs",
    "inputs_using_only_defaults",
  ];
  if (
    !row ||
    !expected ||
    row.id !== expected.id ||
    typeof row.name !== "string" ||
    !["passed", "failed"].includes(row.status) ||
    !Number.isInteger(row.successful_scans) ||
    row.successful_scans < 0 ||
    !Number.isInteger(row.attempted_scans) ||
    row.attempted_scans < row.successful_scans ||
    !Array.isArray(row.comparisons) ||
    !Array.isArray(row.not_run) ||
    !row.coverage ||
    typeof row.coverage.meaning !== "string" ||
    arrays.some(
      (key) =>
        !Array.isArray(row.coverage[key]) ||
        row.coverage[key].some((value: unknown) => typeof value !== "string"),
    )
  )
    return false;
  const checks = [...row.comparisons, ...row.not_run];
  if (
    checks.length !== expected.checks.length ||
    new Set(checks.map((check) => check?.id)).size !== checks.length
  )
    return false;
  if (
    !checks.every((check) => {
      const declared = expected.checks.find(
        (item: Data) => item.id === check?.id,
      );
      return (
        declared &&
        [
          "id",
          "time",
          "signal",
          "unit",
          "expected",
          "abs_tol",
          "rel_tol",
        ].every((key) => check[key] === declared[key])
      );
    })
  )
    return false;
  if (
    !row.comparisons.every(
      (check: Data) =>
        typeof check.passed === "boolean" &&
        (check.numeric_representation_error == null ||
          typeof check.numeric_representation_error === "string") &&
        typeof check.actual === typeof check.expected &&
        (typeof check.actual === "boolean" ||
          (typeof check.actual === "number" && Number.isFinite(check.actual))),
    )
  )
    return false;
  return (
    !row.fault ||
    (typeof row.fault.message === "string" &&
      typeof row.fault.snapshot_unchanged === "boolean" &&
      typeof row.fault.passed === "boolean")
  );
}
export function ConformancePanel({ program }: { program: Program }) {
  const [catalog, setCatalog] = useState<Data | null>(null);
  const [suite, setSuite] = useState<Data | null>(null);
  const [caseId, setCaseId] = useState("");
  const [saved, setSaved] = useState<Data[]>([]);
  const [selection, setSelection] = useState("");
  const [identity, setIdentity] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const [savedSignature, setSavedSignature] = useState("");
  const [report, setReport] = useState<
    (JsonDocument & { source: string; draft: string }) | null
  >(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [eventTime, setEventTime] = useState("0"),
    [input, setInput] = useState(""),
    [inputValue, setInputValue] = useState(""),
    [quality, setQuality] = useState("good");
  const [checkId, setCheckId] = useState(""),
    [checkTime, setCheckTime] = useState("1"),
    [signal, setSignal] = useState(""),
    [expected, setExpected] = useState(""),
    [absolute, setAbsolute] = useState("0"),
    [relative, setRelative] = useState("0"),
    [checkLabel, setCheckLabel] = useState("");
  const mounted = useRef(false),
    panel = useRef<HTMLElement>(null),
    generation = useRef(0),
    operation = useRef(false);
  const sourceSignature = JSON.stringify(program),
    signature = JSON.stringify(suite);
  const liveSource = useRef(sourceSignature),
    liveSuite = useRef(signature);
  liveSource.current = sourceSignature;
  liveSuite.current = signature;
  const active =
    suite?.cases.find((row: Data) => row.id === caseId) ?? suite?.cases[0];
  const signals: Data[] = suite?.signals ?? [];
  const inputs = signals.filter((row) => row.role === "input");
  const selectedInput = signals.find((row) => row.id === input),
    selectedSignal = signals.find((row) => row.id === signal);
  const stale =
    !catalog ||
    !suite ||
    suite.program_sha256 !== catalog.template.program_sha256 ||
    suite.program_revision !== program.revision;
  const disabled = busy || stale;
  function current(request: number, source: string, draft?: string) {
    return (
      mounted.current &&
      generation.current === request &&
      liveSource.current === source &&
      (draft === undefined || liveSuite.current === draft)
    );
  }
  function visible() {
    return !!(
      panel.current?.isConnected &&
      panel.current.getClientRects().length &&
      !panel.current.closest("details:not([open])")
    );
  }
  function update(next: Data) {
    generation.current++;
    setSuite(next);
    setReport(null);
    setError("");
    setMessage("");
  }
  function patchCase(change: Data) {
    if (!suite || !active) return;
    update({
      ...suite,
      cases: suite.cases.map((row: Data) =>
        row.id === active.id ? { ...row, ...change } : row,
      ),
    });
  }
  function discard() {
    return (
      !suite ||
      signature === savedSignature ||
      !suite.cases.some(
        (row: Data) =>
          row.events.length || row.checks.length || row.expected_fault,
      ) ||
      window.confirm("Discard the unsaved conformance suite draft?")
    );
  }
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      generation.current++;
    };
  }, []);
  useEffect(() => {
    const request = ++generation.current,
      source = sourceSignature;
    setReport(null);
    setCatalog(null);
    setBusy(true);
    setError("");
    api("/conformance/catalog", { program })
      .then((data) => {
        if (!current(request, source)) return;
        setCatalog(data);
        setSaved(data.saved);
        if (!suite) {
          setSuite(data.template);
          setCaseId(data.template.cases[0].id);
          setSavedSignature(JSON.stringify(data.template));
        }
      })
      .catch((failure) => {
        if (current(request, source)) setError(String(failure));
      })
      .finally(() => {
        if (current(request, source)) setBusy(false);
      });
  }, [sourceSignature]);
  async function perform(
    action: (request: number, source: string, draft: string) => Promise<void>,
  ) {
    if (operation.current) return;
    operation.current = true;
    const request = ++generation.current,
      source = sourceSignature,
      draft = signature;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await action(request, source, draft);
    } catch (failure) {
      if (current(request, source, draft)) setError(String(failure));
    } finally {
      operation.current = false;
      if (mounted.current && generation.current === request) setBusy(false);
    }
  }
  function apply(
    next: Data,
    id: string | null,
    version: number,
    clean: boolean,
  ) {
    setSuite(next);
    setCaseId(next.cases[0].id);
    setIdentity(id);
    setRevision(version);
    setReport(null);
    setSavedSignature(clean ? JSON.stringify(next) : "");
    setCheckId("");
  }
  async function refresh() {
    const data = await api("/conformance/catalog", { program });
    return data.saved;
  }
  function newSuite() {
    if (!catalog || !discard()) return;
    generation.current++;
    apply(structuredClone(catalog.template), null, 0, true);
    setMessage(
      "New suite bound to this exact program revision. Add explicit checks before running.",
    );
  }
  async function save() {
    if (!suite) return;
    await perform(async (request, source, draft) => {
      const result = await api("/conformance/save", {
        program,
        suite,
        id: identity,
        expected_revision: revision,
      });
      const rows = await refresh();
      if (!current(request, source, draft)) return;
      apply(result.suite, result.id, result.revision, true);
      setSelection(result.id);
      setSaved(rows);
      setMessage(`Saved conformance suite revision ${result.revision}.`);
    });
  }
  async function reopen() {
    if (!selection || !discard()) return;
    setReport(null);
    await perform(async (request, source, draft) => {
      const result = await api(`/conformance/saved/${selection}`, { program });
      if (!current(request, source, draft)) return;
      apply(result.suite, result.id, result.revision, true);
      setMessage(
        `Reopened exact-source conformance suite revision ${result.revision}.`,
      );
    });
  }
  async function remove() {
    if (!selection) return;
    const entry = saved.find((row) => row.id === selection);
    if (!entry) return;
    await perform(async (request, source, draft) => {
      await api(`/conformance/saved/${selection}/delete`, {
        program,
        expected_revision: entry.revision,
      });
      const rows = await refresh();
      if (!current(request, source, draft)) return;
      setSaved(rows);
      setSelection("");
      if (identity === entry.id) {
        setIdentity(null);
        setRevision(0);
        setSavedSignature("");
      }
      setMessage("Saved suite removed; current draft retained.");
    });
  }
  async function importSuite(file?: File) {
    if (!file || !discard()) return;
    setReport(null);
    await perform(async (request, source, draft) => {
      if (file.size > 2 * 1024 * 1024)
        throw new Error("Conformance import exceeds2MiB.");
      const result = await api("/conformance/import", {
        program,
        text: await file.text(),
      });
      if (!current(request, source, draft)) return;
      apply(result.suite, null, 0, false);
      setSelection("");
      setMessage(
        "Imported source-checked suite. Save locally to retain it after restart.",
      );
    });
  }
  async function exportSuite() {
    if (!suite) return;
    await perform(async (request, source, draft) => {
      const saved = await download(
        "/conformance/export",
        { program, suite },
        "graph-conformance-suite.json",
        () => current(request, source, draft) && visible(),
      );
      if (saved && current(request, source, draft))
        setMessage("Validated conformance suite JSON download requested.");
    });
  }
  async function run() {
    if (!suite) return;
    setReport(null);
    await perform(async (request, source, draft) => {
      const validated = await api("/conformance/validate", { program, suite });
      if (!current(request, source, draft)) return;
      const result = await apiJsonDocument("/conformance/run", {
        program,
        suite: validated.suite,
      });
      if (!current(request, source, draft) || !visible()) return;
      const data = result.data;
      if (
        data?.format !== "bms.graph-conformance-report" ||
        data.version !== 1 ||
        data.program_sha256 !== suite.program_sha256 ||
        data.program_id !== program.id ||
        data.program_revision !== program.revision ||
        data.execution_profile_sha256 !== suite.execution_profile_sha256 ||
        data.suite_sha256 !== validated.suite_sha256 ||
        !/^[a-f0-9]{64}$/.test(data.content_sha256) ||
        !["passed", "failed"].includes(data.status) ||
        typeof data.scope !== "string" ||
        data.native_execution !== false ||
        data.controller_writes !== false ||
        data.certification !== false ||
        !Array.isArray(data.cases) ||
        !data.cases.every((row: Data, index: number) =>
          validCase(row, validated.suite.cases[index]),
        ) ||
        JSON.stringify(data.cases.map((row: Data) => row.id)) !==
          JSON.stringify(suite.cases.map((row: Data) => row.id))
      )
        throw new Error(
          "Conformance report identity does not match this exact source suite.",
        );
      setReport({ ...result, source, draft });
      setMessage(
        `Declared checks ${data.status}. Unlisted conditions remain untested.`,
      );
    });
  }
  function addEvent() {
    try {
      if (!active || !selectedInput)
        throw new Error("Select an existing Input block.");
      const sample = { value: value(inputValue, selectedInput.type), quality };
      const time = value(eventTime, "number");
      const existing = active.events.find((row: Data) => row.time === time);
      const events = existing
        ? active.events.map((row: Data) =>
            row === existing
              ? { ...row, inputs: { ...row.inputs, [input]: sample } }
              : row,
          )
        : [...active.events, { time, inputs: { [input]: sample } }];
      patchCase({ events: events.sort((a: Data, b: Data) => a.time - b.time) });
    } catch (failure) {
      setError(String(failure));
    }
  }
  function addCheck() {
    try {
      if (!active || !selectedSignal)
        throw new Error("Select an existing block value.");
      const row = {
        id: checkId || identifier("check"),
        label: checkLabel,
        time: value(checkTime, "number"),
        signal,
        unit: selectedSignal.unit,
        expected: value(expected, selectedSignal.type),
        abs_tol:
          selectedSignal.type === "boolean" ? 0 : value(absolute, "number"),
        rel_tol:
          selectedSignal.type === "boolean" ? 0 : value(relative, "number"),
      };
      patchCase({
        checks: checkId
          ? active.checks.map((old: Data) => (old.id === checkId ? row : old))
          : [...active.checks, row],
      });
      setCheckId("");
      setExpected("");
      setCheckLabel("");
    } catch (failure) {
      setError(String(failure));
    }
  }
  function editCheck(row: Data) {
    setCheckId(row.id);
    setCheckTime(String(row.time));
    setSignal(row.signal);
    setExpected(String(row.expected));
    setAbsolute(String(row.abs_tol));
    setRelative(String(row.rel_tol));
    setCheckLabel(row.label);
  }
  return (
    <section
      className="conformance workspace-page"
      aria-label="Portable graph conformance tests"
      ref={panel}
    >
      <h1>Conformance tests</h1>
      <p>
        Declare timed inputs and expected block values, then test this exact
        Studio graph. Each case starts fresh. Passing these checks does not
        certify the full sequence, Title24, Guideline36 or a physical
        controller. Native CAF logic is not executed.
      </p>
      <p className="help-text">
        Stimuli apply at exact scan starts (zero, dt,2dt…). Checks observe
        successful scan ends. The final scan can be shorter than dt. Numeric
        checks use the larger of absolute tolerance and relative tolerance × the
        larger magnitude. Boolean checks are exact. No scripts or inferred unit
        conversions.
      </p>
      {catalog && (
        <p>
          Source {catalog.template.program_id} · revision{" "}
          {catalog.template.program_revision} · SHA256{" "}
          <code>{catalog.template.program_sha256}</code>
        </p>
      )}
      {stale && suite && (
        <p role="alert">
          Source program changed. This draft remains bound to its earlier
          source. Return to that exact program or start a new suite; existing
          expectations are not automatically transferred.
        </p>
      )}
      <div className="button-row">
        <button disabled={busy || !catalog} onClick={newSuite}>
          New conformance suite
        </button>
        <button disabled={disabled} onClick={() => void save()}>
          Save conformance suite
        </button>
        <button disabled={disabled} onClick={() => void run()}>
          Run declared checks
        </button>
        <button disabled={disabled} onClick={() => void exportSuite()}>
          Export conformance suite JSON
        </button>
        <label>
          Import conformance suite JSON
          <input
            aria-label="Import conformance suite JSON"
            type="file"
            accept=".json,application/json"
            disabled={busy || !catalog}
            onChange={(event) => {
              void importSuite(event.target.files?.[0]);
              event.target.value = "";
            }}
          />
        </label>
      </div>
      <div className="button-row">
        <label>
          Saved conformance suites
          <select
            aria-label="Saved conformance suites"
            value={selection}
            disabled={busy || !catalog}
            onChange={(event) => setSelection(event.target.value)}
          >
            <option value="">Choose a saved exact-source suite</option>
            {saved.map((row) => (
              <option key={row.id} value={row.id}>
                {row.name} · revision {row.revision}
              </option>
            ))}
          </select>
        </label>
        <button disabled={busy || !selection} onClick={() => void reopen()}>
          Reopen conformance suite
        </button>
        <button disabled={busy || !selection} onClick={() => void remove()}>
          Delete saved conformance suite
        </button>
      </div>
      {suite && (
        <>
          <fieldset disabled={disabled}>
            <legend>Suite definition</legend>
            <label>
              Suite name
              <input
                aria-label="Conformance suite name"
                value={suite.name}
                onChange={(event) =>
                  update({ ...suite, name: event.target.value })
                }
              />
            </label>
            <label>
              Description
              <textarea
                aria-label="Conformance suite description"
                value={suite.description}
                onChange={(event) =>
                  update({ ...suite, description: event.target.value })
                }
              />
            </label>
          </fieldset>
          <div className="button-row">
            <label>
              Test case
              <select
                aria-label="Conformance test case"
                value={active?.id ?? ""}
                disabled={busy}
                onChange={(event) => {
                  setCaseId(event.target.value);
                  setCheckId("");
                }}
              >
                {suite.cases.map((row: Data) => (
                  <option key={row.id} value={row.id}>
                    {row.name}
                  </option>
                ))}
              </select>
            </label>
            <button
              disabled={disabled || suite.cases.length >= 20}
              onClick={() => {
                const row = freshCase(program.scan_seconds);
                update({ ...suite, cases: [...suite.cases, row] });
                setCaseId(row.id);
              }}
            >
              Add test case
            </button>
            <button
              disabled={disabled || suite.cases.length <= 1}
              onClick={() => {
                const cases = suite.cases.filter(
                  (row: Data) => row.id !== active.id,
                );
                update({ ...suite, cases });
                setCaseId(cases[0].id);
              }}
            >
              Remove test case
            </button>
          </div>
          {active && (
            <>
              <fieldset disabled={disabled}>
                <legend>Independent test case</legend>
                <label>
                  Case name
                  <input
                    aria-label="Conformance case name"
                    value={active.name}
                    onChange={(event) =>
                      patchCase({ name: event.target.value })
                    }
                  />
                </label>
                <label>
                  Case description
                  <textarea
                    aria-label="Conformance case description"
                    value={active.description}
                    onChange={(event) =>
                      patchCase({ description: event.target.value })
                    }
                  />
                </label>
                <label>
                  Duration seconds
                  <input
                    aria-label="Conformance duration"
                    type="number"
                    step="any"
                    value={active.duration}
                    onChange={(event) =>
                      patchCase({ duration: Number(event.target.value) })
                    }
                  />
                </label>
                <label>
                  Scan dt seconds
                  <input
                    aria-label="Conformance scan dt"
                    type="number"
                    step="any"
                    value={active.dt}
                    onChange={(event) =>
                      patchCase({ dt: Number(event.target.value) })
                    }
                  />
                </label>
                <label>
                  Start clock UTC
                  <input
                    aria-label="Conformance start clock UTC"
                    type="datetime-local"
                    step="1"
                    value={active.start_clock.slice(0, 19)}
                    onChange={(event) =>
                      patchCase({ start_clock: event.target.value + "Z" })
                    }
                  />
                </label>
              </fieldset>
              <fieldset disabled={disabled}>
                <legend>Input stimuli</legend>
                <label>
                  Elapsed scan start
                  <input
                    aria-label="Stimulus scan start"
                    value={eventTime}
                    onChange={(event) => setEventTime(event.target.value)}
                  />
                </label>
                <label>
                  Input
                  <select
                    aria-label="Stimulus input"
                    value={input}
                    onChange={(event) => setInput(event.target.value)}
                  >
                    <option value="">Select an Input</option>
                    {inputs.map((row) => (
                      <option key={row.id} value={row.id}>
                        {row.label || row.id} · {row.id} · {row.type} ·{" "}
                        {row.unit || "unit unspecified"}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Value
                  <input
                    aria-label="Stimulus value"
                    value={inputValue}
                    placeholder={
                      selectedInput?.type === "boolean"
                        ? "true or false"
                        : "finite number"
                    }
                    onChange={(event) => setInputValue(event.target.value)}
                  />
                </label>
                <label>
                  Local quality
                  <select
                    aria-label="Stimulus quality"
                    value={quality}
                    onChange={(event) => setQuality(event.target.value)}
                  >
                    {[
                      "good",
                      "open-circuit",
                      "short-circuit",
                      "unreliable",
                      "out-of-service",
                    ].map((item) => (
                      <option key={item}>{item}</option>
                    ))}
                  </select>
                </label>
                <button onClick={addEvent}>Add or replace stimulus</button>
              </fieldset>
              <table aria-label="Conformance stimuli">
                <thead>
                  <tr>
                    <th>Scan start</th>
                    <th>Input</th>
                    <th>Value / quality</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {active.events.flatMap((row: Data) =>
                    Object.entries(row.inputs).map(
                      ([id, sample]: [string, any]) => (
                        <tr key={row.time + id}>
                          <td>{row.time}</td>
                          <td>{id}</td>
                          <td>
                            {String(sample.value)} / {sample.quality}
                          </td>
                          <td>
                            <button
                              disabled={disabled}
                              onClick={() => {
                                const events = active.events
                                  .map((old: Data) =>
                                    old === row
                                      ? {
                                          ...old,
                                          inputs: Object.fromEntries(
                                            Object.entries(old.inputs).filter(
                                              ([key]) => key !== id,
                                            ),
                                          ),
                                        }
                                      : old,
                                  )
                                  .filter(
                                    (item: Data) =>
                                      Object.keys(item.inputs).length,
                                  );
                                patchCase({ events });
                              }}
                            >
                              Remove stimulus
                            </button>
                          </td>
                        </tr>
                      ),
                    ),
                  )}
                </tbody>
              </table>
              <fieldset disabled={disabled}>
                <legend>Expected value checks</legend>
                <label>
                  Check label
                  <input
                    aria-label="Expected check label"
                    value={checkLabel}
                    onChange={(event) => setCheckLabel(event.target.value)}
                  />
                </label>
                <label>
                  Elapsed scan end
                  <input
                    aria-label="Expected scan end"
                    value={checkTime}
                    onChange={(event) => setCheckTime(event.target.value)}
                  />
                </label>
                <label>
                  Block value
                  <select
                    aria-label="Expected signal"
                    value={signal}
                    onChange={(event) => setSignal(event.target.value)}
                  >
                    <option value="">Select a block value</option>
                    {signals.map((row) => (
                      <option key={row.id} value={row.id}>
                        {row.label || row.id} · {row.id} · {row.role} ·{" "}
                        {row.type} · {row.unit || "unit unspecified"}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Expected value
                  <input
                    aria-label="Expected value"
                    value={expected}
                    placeholder={
                      selectedSignal?.type === "boolean"
                        ? "true or false"
                        : "enter your expected number"
                    }
                    onChange={(event) => setExpected(event.target.value)}
                  />
                </label>
                <label>
                  Absolute tolerance (
                  {selectedSignal?.unit || "unit unspecified"})
                  <input
                    aria-label="Expected absolute tolerance"
                    value={absolute}
                    disabled={selectedSignal?.type === "boolean"}
                    onChange={(event) => setAbsolute(event.target.value)}
                  />
                </label>
                <label>
                  Relative tolerance (0–1)
                  <input
                    aria-label="Expected relative tolerance"
                    value={relative}
                    disabled={selectedSignal?.type === "boolean"}
                    onChange={(event) => setRelative(event.target.value)}
                  />
                </label>
                <button onClick={addCheck}>
                  {checkId ? "Update expected check" : "Add expected check"}
                </button>
                {checkId && (
                  <button onClick={() => setCheckId("")}>
                    Cancel check edit
                  </button>
                )}
              </fieldset>
              <table aria-label="Conformance expectations">
                <thead>
                  <tr>
                    <th>Scan end</th>
                    <th>Signal</th>
                    <th>Expected</th>
                    <th>Tolerances</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {active.checks.map((row: Data) => (
                    <tr key={row.id}>
                      <td>{row.time}</td>
                      <td>
                        {row.signal} {row.label}
                      </td>
                      <td>
                        {String(row.expected)} {row.unit}
                      </td>
                      <td>
                        absolute {row.abs_tol}; relative {row.rel_tol}
                      </td>
                      <td>
                        <button
                          disabled={disabled}
                          onClick={() => editCheck(row)}
                        >
                          Edit expected check
                        </button>
                        <button
                          disabled={disabled}
                          onClick={() =>
                            patchCase({
                              checks: active.checks.filter(
                                (item: Data) => item.id !== row.id,
                              ),
                            })
                          }
                        >
                          Remove expected check
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <fieldset disabled={disabled}>
                <legend>Expected scan fault</legend>
                <label>
                  <input
                    aria-label="Expect final scan fault"
                    type="checkbox"
                    checked={!!active.expected_fault}
                    onChange={(event) =>
                      patchCase({
                        expected_fault: event.target.checked
                          ? { time: active.duration, contains: "" }
                          : null,
                      })
                    }
                  />
                  Expect the final attempted scan to fail without committing
                  state
                </label>
                {active.expected_fault && (
                  <>
                    <label>
                      Expected fault scan end
                      <input
                        aria-label="Expected fault time"
                        value={active.expected_fault.time}
                        onChange={(event) =>
                          patchCase({
                            expected_fault: {
                              ...active.expected_fault,
                              time: Number(event.target.value),
                            },
                          })
                        }
                      />
                    </label>
                    <label>
                      Literal error substring (optional)
                      <input
                        aria-label="Expected fault message"
                        value={active.expected_fault.contains}
                        onChange={(event) =>
                          patchCase({
                            expected_fault: {
                              ...active.expected_fault,
                              contains: event.target.value,
                            },
                          })
                        }
                      />
                    </label>
                  </>
                )}
              </fieldset>
            </>
          )}
        </>
      )}
      {busy && (
        <p role="status">
          Working on the local source-bound conformance suite…
        </p>
      )}
      {error && <p role="alert">{error}</p>}
      {message && <p role="status">{message}</p>}
      {report &&
        report.source === sourceSignature &&
        report.draft === signature && (
          <section aria-label="Conformance results">
            <h2>Declared checks: {report.data.status}</h2>
            <p>{report.data.scope}</p>
            <button
              onClick={() => {
                if (
                  !busy &&
                  mounted.current &&
                  visible() &&
                  report.source === liveSource.current &&
                  report.draft === liveSuite.current
                )
                  saveBlob(report.blob, "graph-conformance-report.json");
              }}
            >
              Download conformance report JSON
            </button>
            {report.data.cases.map((row: Data) => (
              <section key={row.id} aria-label={"Case result " + row.name}>
                <h3>
                  {row.name} · {row.status}
                </h3>
                <p>
                  {row.successful_scans} successful scans; {row.attempted_scans}{" "}
                  attempted.
                </p>
                {row.fault && (
                  <p>
                    Scan fault at {row.fault.time}: {row.fault.message}.
                    Snapshot unchanged: {String(row.fault.snapshot_unchanged)}.
                    Expected fault accepted: {String(row.fault.passed)}.
                  </p>
                )}
                {row.expected_fault_missing && (
                  <p>Expected final scan fault did not occur.</p>
                )}
                <table>
                  <thead>
                    <tr>
                      <th>Time</th>
                      <th>Signal</th>
                      <th>Expected</th>
                      <th>Actual</th>
                      <th>Result</th>
                    </tr>
                  </thead>
                  <tbody>
                    {row.comparisons.map((check: Data) => (
                      <tr key={check.id}>
                        <td>{check.time}</td>
                        <td>{check.signal}</td>
                        <td>
                          {String(check.expected)} {check.unit}
                        </td>
                        <td>
                          {String(check.actual)} {check.unit}
                        </td>
                        <td>
                          {check.passed ? "passed" : "failed"}
                          {check.numeric_representation_error && (
                            <span>: {check.numeric_representation_error}</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p>
                  Checks not run: {row.not_run.length}. Asserted outputs:{" "}
                  {row.coverage.asserted_outputs.join(", ") || "none"}.
                  Unasserted outputs:{" "}
                  {row.coverage.unasserted_outputs.join(", ") || "none"}. Inputs
                  using only defaults:{" "}
                  {row.coverage.inputs_using_only_defaults.join(", ") || "none"}
                  .
                </p>
                <p>{row.coverage.meaning}</p>
              </section>
            ))}
            <details>
              <summary>
                Exact source, declared conditions and full result evidence
              </summary>
              <pre>{JSON.stringify(report.data, null, 2)}</pre>
            </details>
          </section>
        )}
    </section>
  );
}
