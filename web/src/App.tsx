import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { useReactFlow, type Connection, type NodeChange } from "@xyflow/react";
import {
  CircuitBoard,
  Workflow,
  FileArchive,
  Network,
  Cpu,
  BookOpen,
  Save,
  FolderOpen,
  Undo2,
  Redo2,
  Download,
  Upload,
  Plus,
  Search,
  Settings2,
  CheckCircle2,
  AlertTriangle,
  Maximize,
  X,
  FlaskConical,
  Layers,
  Bell,
  Boxes,
  Activity,
  Code2,
  FileCheck2,
  BellRing,
  TableProperties,
} from "lucide-react";
import { api, download, initSession } from "./api";
import {
  blankProgram,
  type Block,
  type BmsNode,
  type Program,
  type Scan,
} from "./types";
import { Canvas } from "./Canvas";
import { Inspector, SimulationPanel } from "./Panels";
import { useSimulationClock } from "./useSimulationClock";
import { persistDraftRecovery } from "./draftRecovery";
import {
  sessionFromReceipt,
  retireSimulationSession,
  type SimulationSession,
} from "./simulationSessions";
import { SelectionPanel } from "./SelectionPanel";
import { ConversionPreview } from "./ConversionPreview";

const NativeCaf = lazy(() =>
  import("./NativeCaf").then((m) => ({ default: m.NativeCaf })),
);
const Connections = lazy(() =>
  import("./Connections").then((m) => ({ default: m.Connections })),
);
const RuntimePanel = lazy(() =>
  import("./Runtime").then((m) => ({ default: m.RuntimePanel })),
);
const Resources = lazy(() =>
  import("./Resources").then((m) => ({ default: m.Resources })),
);
const NativeSimulator = lazy(() =>
  import("./NativeSimulator").then((m) => ({ default: m.NativeSimulator })),
);
const TemcoSimulator = lazy(() =>
  import("./TemcoSimulator").then((m) => ({ default: m.TemcoSimulator })),
);
const SystemSimulation = lazy(() =>
  import("./SystemSimulation").then((m) => ({ default: m.SystemSimulation })),
);
const Observations = lazy(() =>
  import("./Observations").then((m) => ({ default: m.Observations })),
);
const MacroLibrary = lazy(() =>
  import("./MacroLibrary").then((m) => ({ default: m.MacroLibrary })),
);
const FieldTrends = lazy(() =>
  import("./FieldTrends").then((m) => ({ default: m.FieldTrends })),
);
const NiagaraInspector = lazy(() =>
  import("./NiagaraInspector").then((m) => ({ default: m.NiagaraInspector })),
);
const HardwareDefinitions = lazy(() =>
  import("./HardwareDefinitions").then((m) => ({
    default: m.HardwareDefinitions,
  })),
);
const IECVerifier = lazy(() =>
  import("./IECVerifier").then((m) => ({ default: m.IECVerifier })),
);
const CafComparison = lazy(() =>
  import("./CafComparison").then((m) => ({ default: m.CafComparison })),
);
const EquipmentWizard = lazy(() =>
  import("./EquipmentWizard").then((m) => ({ default: m.EquipmentWizard })),
);
const DeviceHistory = lazy(() =>
  import("./DeviceHistory").then((m) => ({ default: m.DeviceHistory })),
);
const ConformancePanel = lazy(() =>
  import("./ConformancePanel").then((m) => ({ default: m.ConformancePanel })),
);
const CafSimulationPanel = lazy(() =>
  import("./CafSimulationPanel").then((m) => ({
    default: m.CafSimulationPanel,
  })),
);
const TruthTableReview = lazy(() =>
  import("./TruthTableReview").then((m) => ({ default: m.TruthTableReview })),
);
const Notifications = lazy(() =>
  import("./Notifications").then((m) => ({ default: m.Notifications })),
);

export function App() {
  const [cafVisited, setCafVisited] = useState(false);
  const [cafSimulationVisited, setCafSimulationVisited] = useState(false);
  const [tab, setTab] = useState("editor"),
    [program, setProgramState] = useState<Program>(blankProgram),
    [blocks, setBlocks] = useState<Block[]>([]),
    [macroBlocks, setMacroBlocks] = useState<Block[]>([]),
    [macroEdit, setMacroEditState] = useState<{
      parent: Program;
      definition: string;
      undo: Program[];
      redo: Program[];
    } | null>(null),
    [templates, setTemplates] = useState<Program[]>([]),
    [projects, setProjects] = useState<any[]>([]),
    [issues, setIssues] = useState<any[]>([]),
    [validationStatus, setValidationStatus] = useState<
      "pending" | "complete" | "error"
    >("pending"),
    [selection, setSelection] = useState<string[]>([]),
    [search, setSearch] = useState(""),
    [format, setFormat] = useState("json"),
    [history, setHistory] = useState<Scan[]>([]),
    [inputs, setInputs] = useState<Record<string, any>>({}),
    [forces, setForces] = useState<Record<string, number | boolean>>({}),
    [simBusy, setSimBusy] = useState(false),
    [simUncertain, setSimUncertain] = useState(false),
    [simError, setSimError] = useState(""),
    [recordHistory, setRecordHistory] = useState(false),
    [recordingError, setRecordingError] = useState(""),
    [nextClock, setNextClock] = useState(""),
    [message, setMessage] = useState(""),
    [ready, setReady] = useState(false),
    [settings, setSettings] = useState(false),
    [equipmentWizard, setEquipmentWizard] = useState(false),
    [recoveryError, setRecoveryError] = useState(""),
    [versions, setVersions] = useState<any[]>([]),
    [showIssues, setShowIssues] = useState(false),
    [saving, setSaving] = useState(false),
    [lastSaved, setLastSaved] = useState<{
      id: string;
      name: string;
      revision: number;
    } | null>(null),
    [undoStack, setUndoStack] = useState<Program[]>([]),
    [redoStack, setRedoStack] = useState<Program[]>([]);
  const latestProgram = useRef(program);
  const latestMacroEdit = useRef(macroEdit);
  const recoveryReady = useRef(false);
  const recoveryReadBlocked = useRef(false);
  const recoveryMounted = useRef(false);
  function setMacroEdit(
    next: typeof macroEdit | ((current: typeof macroEdit) => typeof macroEdit),
  ) {
    const value =
      typeof next === "function" ? next(latestMacroEdit.current) : next;
    latestMacroEdit.current = value;
    setMacroEditState(value);
  }
  function persistRecovery(
    program: Program,
    macro: { parent: Program; definition: string } | null,
  ) {
    if (recoveryReadBlocked.current) return;
    try {
      persistDraftRecovery(localStorage, program, macro);
      if (recoveryMounted.current) setRecoveryError("");
    } catch (error) {
      if (recoveryMounted.current)
        setRecoveryError(
          `Browser draft recovery failed: ${String(error)}. Previous recovery data is retained when a write fails. Save or export current work before closing.`,
        );
    }
  }
  function flushRecovery() {
    if (recoveryReady.current)
      persistRecovery(latestProgram.current, latestMacroEdit.current);
  }
  useEffect(() => {
    recoveryMounted.current = true;
    const hidden = () => {
      if (document.visibilityState === "hidden") flushRecovery();
    };
    window.addEventListener("pagehide", flushRecovery);
    window.addEventListener("beforeunload", flushRecovery);
    document.addEventListener("visibilitychange", hidden);
    return () => {
      flushRecovery();
      recoveryMounted.current = false;
      window.removeEventListener("pagehide", flushRecovery);
      window.removeEventListener("beforeunload", flushRecovery);
      document.removeEventListener("visibilitychange", hidden);
    };
  }, []);
  const latestForces = useRef(forces);
  latestForces.current = forces;
  const simulationEpoch = useRef(0);
  const draftEpoch = useRef(0),
    loadEpoch = useRef(0),
    validationEpoch = useRef(0),
    versionsEpoch = useRef(0),
    projectsEpoch = useRef(0),
    saveActive = useRef(false);
  useEffect(
    () => () => {
      simulationEpoch.current++;
    },
    [],
  );
  const renderedDraftEpoch = draftEpoch.current;
  const renderedNavigationEpoch = loadEpoch.current;
  function setProgram(next: Program | ((current: Program) => Program)) {
    const updated =
      typeof next === "function" ? next(latestProgram.current) : next;
    if (updated === latestProgram.current) return;
    simulationEpoch.current++;
    detachSimulationSession();
    latestProgram.current = updated;
    draftEpoch.current++;
    setProgramState(updated);
  }
  async function refreshProjects() {
    const epoch = ++projectsEpoch.current;
    const rows = await api("/projects");
    if (epoch === projectsEpoch.current) setProjects(rows);
  }
  async function refreshVersions(id: string) {
    const epoch = ++versionsEpoch.current;
    const rows = await api(`/projects/${id}/versions`);
    if (epoch === versionsEpoch.current && latestProgram.current.id === id)
      setVersions(rows);
  }
  const session = useRef<SimulationSession | null>(null),
    busy = useRef(false),
    importInput = useRef<HTMLInputElement>(null);
  const retirePending = useRef(new Map<string, Promise<void>>());
  const retireFailed = useRef(
    new Map<string, { handle: SimulationSession; error: string }>(),
  );
  const retired = useRef(new Set<string>());
  const simulationMounted = useRef(false);
  const [cleanupStatus, setCleanupStatus] = useState({
    pending: 0,
    failed: 0,
    error: "",
  });
  const [unknownSession, setUnknownSession] = useState(false);
  const [cacheStatus, setCacheStatus] = useState("");
  function publishCleanup() {
    if (simulationMounted.current)
      setCleanupStatus({
        pending: retirePending.current.size,
        failed: retireFailed.current.size,
        error: [...retireFailed.current.values()]
          .map((row) => row.error)
          .join("; ")
          .slice(0, 1500),
      });
  }
  function cleanupBlocked() {
    return retirePending.current.size > 0 || retireFailed.current.size > 0;
  }
  function retireOwnedSimulation(
    handle: SimulationSession,
    explicitRetry = false,
  ): Promise<void> {
    if (retired.current.has(handle.session)) return Promise.resolve();
    const existing = retirePending.current.get(handle.session);
    if (existing) return existing;
    if (retireFailed.current.has(handle.session) && !explicitRetry)
      return Promise.resolve();
    retireFailed.current.delete(handle.session);
    const pending = (async () => {
      try {
        await retireSimulationSession(handle);
        retired.current.add(handle.session);
        if (retired.current.size > 128)
          retired.current.delete(retired.current.values().next().value!);
        retireFailed.current.delete(handle.session);
      } catch (error) {
        retireFailed.current.set(handle.session, {
          handle,
          error: String(error).slice(0, 1000),
        });
      } finally {
        retirePending.current.delete(handle.session);
        publishCleanup();
      }
    })();
    retirePending.current.set(handle.session, pending);
    publishCleanup();
    return pending;
  }
  function detachSimulationSession() {
    const known = session.current;
    session.current = null;
    if (known) void retireOwnedSimulation(known);
  }
  function noteUnknownSession() {
    if (simulationMounted.current) setUnknownSession(true);
  }
  function retrySimulationCleanup() {
    for (const { handle } of [...retireFailed.current.values()])
      void retireOwnedSimulation(handle, true);
  }
  async function checkSimulationCache() {
    try {
      const value = await api("/simulation/sessions/status");
      if (
        !Number.isInteger(value.cached_sessions) ||
        value.cached_sessions < 0 ||
        value.cached_sessions > value.limit ||
        value.limit !== 25 ||
        value.idle_expiry_seconds !== 3600
      )
        throw new Error("Invalid local session cache status.");
      if (simulationMounted.current)
        setCacheStatus(
          `Local cache snapshot: ${value.cached_sessions}/${value.limit} calculation sessions; unknown idle sessions expire after ${value.idle_expiry_seconds} seconds.`,
        );
    } catch (error) {
      if (simulationMounted.current) setCacheStatus(String(error));
    }
  }
  useEffect(() => {
    simulationMounted.current = true;
    const pagehide = (event: PageTransitionEvent) => {
      if (event.persisted) return;
      simulationEpoch.current++;
      detachSimulationSession();
    };
    window.addEventListener("pagehide", pagehide);
    return () => {
      simulationMounted.current = false;
      simulationEpoch.current++;
      detachSimulationSession();
      window.removeEventListener("pagehide", pagehide);
    };
  }, []);
  const flow = useReactFlow();
  const specs = [...blocks, ...macroBlocks];
  const specKey = (b: Block) =>
    b.kind === "Macro" ? "macro:" + b.parameters.definition : b.kind;
  const selected = selection.at(-1) || null;
  const clipboard = useRef<{
    nodes: BmsNode[];
    edges: Program["edges"];
    source: Program;
  } | null>(null);
  function setSelected(id: string | null) {
    setSelection(id ? [id] : []);
  }
  useEffect(() => {
    setSelection((ids) =>
      ids.filter((id) => program.nodes.some((n) => n.id === id)),
    );
  }, [program.nodes]);
  useEffect(() => {
    let live = true;
    if (!ready) return;
    const timer = setTimeout(
      () =>
        api("/macros/catalog", { program })
          .then((r) => {
            if (live)
              setMacroBlocks(
                r.definitions.map((d: any) => ({ ...d, stateful: true })),
              );
          })
          .catch(() => {
            if (live) setMacroBlocks([]);
          }),
      150,
    );
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [program.metadata.macros, ready]);
  useEffect(() => {
    let live = true;
    initSession()
      .then(() =>
        Promise.all([api("/blocks"), api("/templates"), api("/projects")]),
      )
      .then(([b, t, p]) => {
        if (!live) return;
        setBlocks(b);
        setTemplates(t);
        setProjects(p);
        let initial = t[0];
        const blockUnreadRecovery = () => {
          recoveryReadBlocked.current = true;
          setRecoveryError(
            "Browser draft recovery unavailable. Automatic recovery writes are paused for this page to preserve existing data. Saved revisions, import and export remain available; reload to retry.",
          );
        };
        try {
          const saved = localStorage.getItem("bms-studio-draft-v1");
          if (saved) {
            const parsed = JSON.parse(saved);
            if (
              parsed.schema_version === 1 &&
              Array.isArray(parsed.nodes) &&
              Array.isArray(parsed.edges)
            )
              initial = parsed;
            else throw new Error("Unsupported browser draft recovery.");
          }
        } catch {
          blockUnreadRecovery();
        }
        try {
          const raw = localStorage.getItem("bms-studio-macro-edit-v1");
          const draft = JSON.parse(raw || "null");
          if (
            draft?.parent?.schema_version === 1 &&
            draft?.draft?.schema_version === 1 &&
            Array.isArray(draft.parent.nodes) &&
            Array.isArray(draft.parent.edges) &&
            Array.isArray(draft.draft.nodes) &&
            Array.isArray(draft.draft.edges) &&
            typeof draft.definition === "string"
          ) {
            setMacroEdit({
              parent: draft.parent,
              definition: draft.definition,
              undo: [],
              redo: [],
            });
            initial = draft.draft;
          } else if (raw && draft !== null)
            throw new Error("Unsupported macro draft recovery.");
        } catch {
          blockUnreadRecovery();
        }
        setProgram(initial);
        recoveryReady.current = true;
        setReady(true);
      })
      .catch((e) => setMessage(e.message));
    return () => {
      live = false;
    };
  }, []);
  useEffect(() => {
    if (!ready) return;
    const epoch = ++validationEpoch.current;
    let live = true;
    setIssues([]);
    setValidationStatus("pending");
    detachSimulationSession();
    setSimUncertain(false);
    setHistory([]);
    setForces({});
    setSimError("");
    setRecordingError("");
    const timer = setTimeout(() => {
      flushRecovery();
      api("/validate", program)
        .then((r) => {
          if (
            live &&
            epoch === validationEpoch.current &&
            latestProgram.current === program
          ) {
            setIssues(r.issues);
            setValidationStatus("complete");
          }
        })
        .catch((e) => {
          if (
            live &&
            epoch === validationEpoch.current &&
            latestProgram.current === program
          ) {
            setValidationStatus("error");
            setMessage(e.message);
          }
        });
    }, 200);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [program, ready, macroEdit]);
  const remember = useCallback(() => {
    setUndoStack((s) => [...s.slice(-49), structuredClone(program)]);
    setRedoStack([]);
  }, [program]);
  function change(p: Program, record = true) {
    if (record) remember();
    setProgram(p);
    setMessage("");
  }
  function undo() {
    if (!undoStack.length) return;
    setRedoStack((s) => [...s, structuredClone(program)]);
    setProgram(undoStack.at(-1)!);
    setUndoStack((s) => s.slice(0, -1));
  }
  function redo() {
    if (!redoStack.length) return;
    setUndoStack((s) => [...s, structuredClone(program)]);
    setProgram(redoStack.at(-1)!);
    setRedoStack((s) => s.slice(0, -1));
  }
  function recordSaved(
    p: Program,
    snapshot: Program,
    epoch: number,
    navigation: number,
    native = false,
  ) {
    const current = latestProgram.current;
    const unchanged =
      current === snapshot &&
      draftEpoch.current === epoch &&
      loadEpoch.current === navigation;
    if (unchanged) setProgram(p);
    else if (
      loadEpoch.current === navigation &&
      current.id === snapshot.id &&
      p.id === snapshot.id &&
      current.revision === snapshot.revision
    ) {
      // The saved base advanced, while the user's later content stays intact.
      // Keeping this revision also allows the next save without a false conflict.
      setProgram({ ...current, revision: p.revision });
    }
    if (loadEpoch.current === navigation && p.id === snapshot.id) {
      const advance = (rows: Program[]) =>
        rows.map((row) =>
          row.id === p.id && row.revision === snapshot.revision
            ? { ...row, revision: p.revision }
            : row,
        );
      setUndoStack(advance);
      setRedoStack(advance);
      setMacroEdit((draft) =>
        draft &&
        draft.parent.id === p.id &&
        draft.parent.revision === snapshot.revision
          ? {
              ...draft,
              parent: { ...draft.parent, revision: p.revision },
              undo: advance(draft.undo),
              redo: advance(draft.redo),
            }
          : draft,
      );
    }
    setLastSaved({ id: p.id, name: p.name, revision: p.revision });
    const outcome =
      (native
        ? `Saved native revision ${p.revision} locally. ${p.name}.`
        : `Saved revision ${p.revision} of ${p.name} locally.`) +
      (unchanged ? "" : " Current draft edits were kept.");
    setMessage(outcome);
    return outcome;
  }
  async function save() {
    if (tab === "truth-tables") {
      setMessage("Use Export table in the truth-table workspace.");
      return;
    }
    if (macroEdit) {
      await applyMacroEdit();
      return;
    }
    if (tab === "system") {
      window.dispatchEvent(new Event("studio:save-workspace"));
      return;
    }
    if (saveActive.current) return;
    saveActive.current = true;
    setSaving(true);
    const snapshot = latestProgram.current;
    const epoch = draftEpoch.current,
      navigation = loadEpoch.current;
    try {
      const native = tab === "native" ? await api("/native/status") : null;
      const p = native?.running
        ? await api("/native/save", {
            expected_revision: native.program.revision,
          })
        : await api("/projects", {
            program: snapshot,
            expected_revision: snapshot.revision,
          });
      const outcome = recordSaved(
        p,
        snapshot,
        epoch,
        navigation,
        !!native?.running,
      );
      const refreshed = await Promise.allSettled([
        refreshProjects(),
        refreshVersions(p.id),
      ]);
      if (
        refreshed.some((result) => result.status === "rejected") &&
        latestProgram.current.id === p.id
      )
        setMessage(outcome + " Saved-project details could not be refreshed.");
    } catch (e) {
      setMessage(`Could not save ${snapshot.name}: ${String(e)}`);
    } finally {
      saveActive.current = false;
      setSaving(false);
    }
  }
  async function openMacroEdit(definition: string) {
    if (macroEdit) return;
    const parent = program;
    try {
      const draft = await api("/macros/definition", {
        program: parent,
        definition,
      });
      if (latestProgram.current !== parent) {
        setMessage(
          "Program changed while loading the definition. Open it again.",
        );
        return;
      }
      persistRecovery(parent, null);
      setMacroEdit({ parent, definition, undo: undoStack, redo: redoStack });
      setProgram(draft);
      setUndoStack([]);
      setRedoStack([]);
      setSelected(null);
      setTab("editor");
    } catch (e) {
      setMessage(String(e));
    }
  }
  async function applyMacroEdit() {
    if (!macroEdit) return;
    const draft = program;
    try {
      const updated = await api("/macros/update", {
        program: macroEdit.parent,
        definition: macroEdit.definition,
        replacement: draft,
      });
      if (latestProgram.current !== draft) {
        setMessage(
          "Definition changed while applying. Apply the current draft again.",
        );
        return;
      }
      setProgram(updated);
      setUndoStack([...macroEdit.undo.slice(-48), macroEdit.parent]);
      setRedoStack([]);
      setMacroEdit(null);
      setSelected(null);
      flushRecovery();
      setMessage(
        "Definition updated in all instances. Save a revision to retain the project.",
      );
    } catch (e) {
      setMessage(String(e));
    }
  }
  function discardMacroEdit() {
    if (!macroEdit) return;
    setProgram(macroEdit.parent);
    setUndoStack(macroEdit.undo);
    setRedoStack(macroEdit.redo);
    setMacroEdit(null);
    setSelected(null);
    flushRecovery();
    setMessage("Definition edits discarded.");
  }
  const step = useCallback(
    async (steps = 1) => {
      if (busy.current || simUncertain || cleanupBlocked()) return;
      busy.current = true;
      setSimBusy(true);
      const epoch = simulationEpoch.current;
      const operation = crypto.randomUUID().replaceAll("-", "");
      const expectedSession = session.current;
      try {
        const r = await api("/simulation/step", {
          program,
          inputs,
          forces,
          steps,
          session: expectedSession?.session || null,
          record: recordHistory,
          operation_id: operation,
          clock: nextClock
            ? new Date(nextClock + "Z").toISOString()
            : undefined,
        });
        if (
          r.operation_id !== operation ||
          r.requested_steps !== steps ||
          r.program_id !== program.id ||
          r.program_revision !== program.revision ||
          r.applied_dt !== program.scan_seconds ||
          (r.scan_error !== null && typeof r.scan_error !== "string") ||
          (r.recording_error !== null &&
            typeof r.recording_error !== "string") ||
          !Number.isInteger(r.completed_steps) ||
          r.completed_steps < 0 ||
          r.completed_steps > steps ||
          (r.completed_steps === 0
            ? !r.scan_error ||
              r.last !== null ||
              (expectedSession === null
                ? r.session !== null
                : typeof r.session !== "string")
            : typeof r.session !== "string" || !r.last) ||
          !Array.isArray(r.history) ||
          r.history.length > 300 ||
          !r.history.every(
            (row: Scan) =>
              row &&
              Number.isFinite(row.time) &&
              typeof row.clock === "string" &&
              row.values &&
              row.outputs,
          ) ||
          (r.completed_steps < steps && !r.scan_error) ||
          !r.snapshot ||
          (expectedSession && expectedSession.session !== r.session)
        )
          throw new Error(
            "Simulation batch receipt does not match its exact request. Reset before running again.",
          );
        const owned = sessionFromReceipt(r, operation, expectedSession);
        if (
          latestProgram.current !== program ||
          simulationEpoch.current !== epoch
        ) {
          if (owned) void retireOwnedSimulation(owned);
          return;
        }
        session.current = owned;
        setHistory(r.history);
        setSimError(r.scan_error || "");
        setRecordingError(r.recording_error || "");
        if (r.completed_steps > 0) setNextClock("");
        return r;
      } catch (e) {
        if (!expectedSession) noteUnknownSession();
        if (
          latestProgram.current !== program ||
          simulationEpoch.current !== epoch
        )
          return;
        setSimUncertain(true);
        setSimError(
          String(e) +
            " An admitted request may have committed scans. Reset is required; no automatic retry.",
        );
        throw e;
      } finally {
        busy.current = false;
        setSimBusy(false);
      }
    },
    [program, inputs, forces, recordHistory, nextClock, simUncertain],
  );
  const pacing = useSimulationClock({
    source: program,
    active: tab === "editor",
    scanSeconds: program.scan_seconds,
    blocked:
      simBusy ||
      simUncertain ||
      cleanupStatus.pending > 0 ||
      cleanupStatus.failed > 0 ||
      !!nextClock,
    batch: step,
  });
  async function runSimulationScenario(events: unknown, duration: number) {
    if (busy.current || simUncertain || cleanupBlocked()) return;
    busy.current = true;
    setSimBusy(true);
    pacing.retire();
    const epoch = ++simulationEpoch.current;
    const source = program;
    const admittedForces = forces;
    try {
      const result = await api("/simulation/scenario", {
        program: source,
        events,
        duration,
        forces,
      });
      if (simulationEpoch.current !== epoch || latestProgram.current !== source)
        return;
      if (!Array.isArray(result.history))
        throw new Error("Scenario response has no valid bounded history.");
      detachSimulationSession();
      setHistory(result.history);
      if (latestForces.current === admittedForces)
        setForces(result.history.at(-1)?.forces || {});
      setSimError("");
      setRecordingError("");
    } catch (error) {
      if (simulationEpoch.current === epoch && latestProgram.current === source)
        setSimError(String(error));
    } finally {
      busy.current = false;
      setSimBusy(false);
    }
  }
  function resetSimulation() {
    simulationEpoch.current++;
    pacing.retire();
    setSimUncertain(false);
    detachSimulationSession();
    setHistory([]);
    setSimError("");
    setRecordingError("");
    setForces({});
  }
  useEffect(() => {
    function keyboard(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "s") {
        e.preventDefault();
        save();
        return;
      }
      if (tab !== "editor") return;
      if (
        ["INPUT", "SELECT", "TEXTAREA"].includes(
          (e.target as HTMLElement).tagName,
        )
      )
        return;
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z") {
        e.preventDefault();
        e.shiftKey ? redo() : undo();
      }
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "a") {
        e.preventDefault();
        setSelection(program.nodes.map((n) => n.id));
      }
      if (
        (e.metaKey || e.ctrlKey) &&
        e.key.toLowerCase() === "c" &&
        selection.length
      ) {
        e.preventDefault();
        copySelection();
      }
      if (
        (e.metaKey || e.ctrlKey) &&
        e.key.toLowerCase() === "v" &&
        clipboard.current
      ) {
        e.preventDefault();
        pasteSelection();
      }
      if (
        (e.metaKey || e.ctrlKey) &&
        e.key.toLowerCase() === "d" &&
        selection.length
      ) {
        e.preventDefault();
        duplicate();
      }
      if (["Delete", "Backspace"].includes(e.key) && selection.length) {
        e.preventDefault();
        remove();
      }
    }
    window.addEventListener("keydown", keyboard);
    return () => window.removeEventListener("keydown", keyboard);
  });
  function add(kind: string, x?: number, y?: number) {
    const b = specs.find((b) => specKey(b) === kind);
    if (!b) return;
    const placedByClick = x === undefined || y === undefined;
    if (placedByClick) {
      const height = Math.max(108, b.inputs.length * 29 + 55);
      for (let slot = 0; slot < 20000; slot++) {
        x = 100 + (slot % 4) * 280;
        y = 100 + Math.floor(slot / 4) * 220;
        const overlaps = program.nodes.some((old) => {
          const spec = specs.find(
            (s) =>
              s.kind === old.kind &&
              (s.kind !== "Macro" ||
                s.parameters.definition === old.params.definition),
          );
          const oldHeight = Math.max(108, (spec?.inputs.length || 0) * 29 + 55);
          return (
            x! < old.x + 252 &&
            x! + 252 > old.x &&
            y! < old.y + oldHeight + 32 &&
            y! + height + 32 > old.y
          );
        });
        if (!overlaps) break;
      }
    }
    const n: BmsNode = {
      id: b.kind.toLowerCase() + "_" + crypto.randomUUID().replaceAll("-", ""),
      kind: b.kind,
      label: b.title,
      x: x ?? 100 + (program.nodes.length % 4) * 240,
      y: y ?? 100 + Math.floor(program.nodes.length / 4) * 180,
      params: structuredClone(b.parameters),
      unit: b.unit || "",
      value_type: b.output === "boolean" ? "boolean" : "number",
    };
    change({ ...program, nodes: [...program.nodes, n] });
    setSelected(n.id);
  }
  function edit(n: BmsNode) {
    change({
      ...program,
      nodes: program.nodes.map((old) => (old.id === n.id ? n : old)),
    });
  }
  function remove() {
    if (!selection.length) return;
    change({
      ...program,
      nodes: program.nodes.filter((n) => !selection.includes(n.id)),
      edges: program.edges.filter(
        (e) => !selection.includes(e.source) && !selection.includes(e.target),
      ),
    });
    setSelected(null);
  }
  function duplicate() {
    copySelection();
    pasteSelection();
  }
  function copySelection() {
    clipboard.current = structuredClone({
      source: program,
      nodes: program.nodes.filter((n) => selection.includes(n.id)),
      edges: program.edges.filter(
        (e) => selection.includes(e.source) && selection.includes(e.target),
      ),
    });
    setMessage(
      `Copied ${clipboard.current.nodes.length} blocks and internal wires.`,
    );
  }
  async function pasteSelection() {
    const clip = clipboard.current;
    if (!clip?.nodes.length) return;
    if (
      program.nodes.length + clip.nodes.length > 2000 ||
      program.edges.length + clip.edges.length > 10000
    ) {
      setMessage("Paste exceeds the project graph size limit.");
      return;
    }
    let base = program;
    try {
      const definitions = new Set(
        clip.nodes
          .filter((n) => n.kind === "Macro")
          .map((n) => n.params.definition),
      );
      for (const definition of definitions) {
        const bundle = await api("/macros/export", {
          program: clip.source,
          definition,
        });
        base = await api("/macros/import", { program: base, bundle });
      }
      if (latestProgram.current !== program) {
        setMessage(
          "Program changed while pasting. Paste again into the current graph.",
        );
        return;
      }
    } catch (e) {
      setMessage(String(e));
      return;
    }
    const ids = Object.fromEntries(
      clip.nodes.map((n) => [
        n.id,
        "copy_" + crypto.randomUUID().replaceAll("-", ""),
      ]),
    );
    const nodes = clip.nodes.map((n) => ({
      ...structuredClone(n),
      id: ids[n.id],
      label: (n.label + " copy").slice(0, 200),
      x: n.x + 50,
      y: n.y + 100,
    }));
    const edges = clip.edges.map((e) => ({
      ...e,
      id: "wire_" + crypto.randomUUID(),
      source: ids[e.source],
      target: ids[e.target],
    }));
    change({
      ...base,
      nodes: [...program.nodes, ...nodes],
      edges: [...program.edges, ...edges],
    });
    setSelection(nodes.map((n) => n.id));
  }
  function alignSelection(axis: "x" | "y") {
    const nodes = program.nodes.filter((n) => selection.includes(n.id));
    if (nodes.length < 2) return;
    const coordinate = Math.min(...nodes.map((n) => n[axis]));
    change({
      ...program,
      nodes: program.nodes.map((n) =>
        selection.includes(n.id) ? { ...n, [axis]: coordinate } : n,
      ),
    });
  }
  function connect(c: Connection) {
    if (!c.source || !c.target || !c.targetHandle) return;
    change({
      ...program,
      edges: [
        ...program.edges,
        {
          id: "wire_" + crypto.randomUUID(),
          source: c.source,
          target: c.target,
          source_port: c.sourceHandle || "out",
          target_port: c.targetHandle,
        },
      ],
    });
  }
  function nodeChanges(changes: NodeChange[]) {
    const selections = changes.filter((c) => c.type === "select");
    if (selections.length)
      setSelection((current) => {
        const ids = new Set(current);
        for (const c of selections)
          if (c.type === "select") {
            if (c.selected) ids.add(c.id);
            else ids.delete(c.id);
          }
        return [...ids];
      });
    if (!changes.some((c) => c.type === "position" && c.position)) return;
    setProgram((current) => {
      let moved = false;
      const nodes = current.nodes.map((n) => {
        const p = changes.find((c) => c.type === "position" && c.id === n.id);
        if (
          p &&
          p.type === "position" &&
          p.position &&
          (n.x !== p.position.x || n.y !== p.position.y)
        ) {
          moved = true;
          return { ...n, x: p.position.x, y: p.position.y };
        }
        return n;
      });
      return moved ? { ...current, nodes } : current;
    });
  }
  async function loadProject(id: string, revision?: number) {
    if (macroEdit) {
      setMessage("Apply or discard definition edits first.");
      return;
    }
    if (!id) return;
    const request = ++loadEpoch.current,
      epoch = draftEpoch.current;
    const snapshot = latestProgram.current;
    try {
      const loaded = await api(
        `/projects/${id}${revision ? "?revision=" + revision : ""}`,
      );
      if (request !== loadEpoch.current) return;
      if (epoch !== draftEpoch.current || latestProgram.current !== snapshot) {
        setMessage(
          "Current draft changed while loading. Open the project again to replace it.",
        );
        return;
      }
      change(loaded);
      setSelected(null);
      setVersions([]);
      await refreshVersions(id);
    } catch (e) {
      if (request === loadEpoch.current && latestProgram.current === snapshot)
        setMessage(String(e));
    }
  }
  async function importProgram(file?: File) {
    if (macroEdit) {
      setMessage("Apply or discard definition edits first.");
      return;
    }
    if (!file) return;
    const request = ++loadEpoch.current,
      epoch = draftEpoch.current;
    const snapshot = latestProgram.current;
    try {
      const f = new FormData();
      f.append("file", file);
      const imported = await api("/import", f);
      if (request !== loadEpoch.current) return;
      if (epoch !== draftEpoch.current || latestProgram.current !== snapshot) {
        setMessage(
          "Current draft changed while importing. Import the file again to replace it.",
        );
        return;
      }
      change({
        ...imported,
        id: imported.id.slice(0, 50) + "-import-" + Date.now().toString(36),
        revision: 0,
      });
      setSelected(null);
      setVersions([]);
      if (imported.metadata?.conversion?.review_required) setSettings(true);
      setMessage("Imported as a new local project.");
    } catch (e) {
      if (request === loadEpoch.current && latestProgram.current === snapshot)
        setMessage(String(e));
    }
  }
  const active = program.nodes.find((n) => n.id === selected),
    errors = issues.filter((d) => d.level === "error"),
    palette = specs.filter((b) =>
      (b.title + " " + b.kind + " " + b.category)
        .toLowerCase()
        .includes(search.toLowerCase()),
    );
  const tabs = [
    { id: "editor", title: "Program", icon: Workflow },
    { id: "truth-tables", title: "Truth tables", icon: TableProperties },
    { id: "caf", title: "CAF files", icon: FileArchive },
    { id: "caf-compare", title: "CAF compare", icon: FileCheck2 },
    { id: "caf-simulation", title: "CAF simulation", icon: FlaskConical },
    { id: "conformance", title: "Conformance tests", icon: FlaskConical },
    { id: "bog", title: "BOG files", icon: FileArchive },
    { id: "hardware", title: "JCI hardware", icon: CircuitBoard },
    { id: "connections", title: "Connect", icon: Network },
    { id: "runtime", title: "Runtime", icon: Cpu },
    { id: "native", title: "Native sim", icon: FlaskConical },
    { id: "temco", title: "Temco native", icon: Cpu },
    { id: "iec", title: "IEC native", icon: Code2 },
    { id: "system", title: "System sim", icon: Layers },
    { id: "observations", title: "Trends & alarms", icon: Bell },
    { id: "notifications", title: "Alarm delivery", icon: BellRing },
    { id: "field-trends", title: "Field trends", icon: Activity },
    { id: "device-history", title: "Device history", icon: Activity },
    { id: "macros", title: "Macros", icon: Boxes },
    { id: "resources", title: "Reference", icon: BookOpen },
  ];
  if (!ready)
    return (
      <div className="loading">
        <CircuitBoard size={38} />
        <h2>BMS Studio</h2>
        <p>{message || "Opening local workspace…"}</p>
      </div>
    );
  return (
    <div className="app">
      <header className="app-header">
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setTab("editor");
          }}
        >
          <CircuitBoard size={27} />
          <span>
            BMS <b>Studio</b>
            <small>CONTROLLER PROGRAMMING</small>
          </span>
        </a>
        <div className="project-title">
          <input
            aria-label="Program name"
            disabled={tab === "truth-tables"}
            value={program.name}
            onChange={(e) => change({ ...program, name: e.target.value })}
          />
          <span className="pill">LOCAL WORKSPACE</span>
        </div>
        <button
          className="save-button primary"
          onClick={save}
          disabled={saving || tab === "truth-tables"}
          title={
            tab === "truth-tables"
              ? "Use Export table in the truth-table workspace."
              : undefined
          }
        >
          <Save size={15} />{" "}
          {macroEdit
            ? "Apply definition"
            : tab === "system"
              ? "Save workspace"
              : "Save revision"}
        </button>
      </header>
      <div className="app-body">
        <nav className="nav-rail" aria-label="Workspaces">
          {tabs.map((t) => (
            <button
              key={t.id}
              className={tab === t.id ? "active" : ""}
              disabled={!!macroEdit && t.id !== "editor"}
              onClick={() => {
                if (t.id === "caf") setCafVisited(true);
                if (t.id === "caf-simulation") setCafSimulationVisited(true);
                setTab(t.id);
              }}
              title={t.title}
            >
              <t.icon size={21} />
              <span>{t.title}</span>
            </button>
          ))}
          <div className="rail-bottom">
            <span className="status-dot on" />
            <small>LOCAL</small>
          </div>
        </nav>
        <main>
          {cafVisited && (
            <div
              hidden={tab !== "caf"}
              style={{ display: tab === "caf" ? undefined : "none" }}
            >
              <Suspense
                fallback={<div className="loading">Opening CAF workspace…</div>}
              >
                <NativeCaf visible={tab === "caf"} />
              </Suspense>
            </div>
          )}
          {cafSimulationVisited && (
            <div
              hidden={tab !== "caf-simulation"}
              style={{ display: tab === "caf-simulation" ? undefined : "none" }}
            >
              <Suspense
                fallback={
                  <div className="loading">
                    Opening CAF simulation workspace…
                  </div>
                }
              >
                <CafSimulationPanel visible={tab === "caf-simulation"} />
              </Suspense>
            </div>
          )}
          <Suspense
            key={tab}
            fallback={<div className="loading">Opening workspace…</div>}
          >
            {tab === "caf" || tab === "caf-simulation" ? null : tab ===
              "editor" ? (
              <>
                {macroEdit && (
                  <div className="macro-edit-banner">
                    <strong>Editing definition: {macroEdit.definition}</strong>
                    <span>
                      Changes apply to every instance. Keep input identifiers,
                      types and units unchanged.
                    </span>
                    <button className="primary" onClick={applyMacroEdit}>
                      Apply definition changes
                    </button>
                    <button onClick={discardMacroEdit}>
                      Discard definition changes
                    </button>
                  </div>
                )}
                <div className="editor-toolbar">
                  <div className="button-row">
                    <button
                      title="New program"
                      aria-label="New program"
                      disabled={!!macroEdit}
                      onClick={() => {
                        change(blankProgram());
                        setSelected(null);
                        setVersions([]);
                      }}
                    >
                      <Plus size={15} /> New
                    </button>
                    <button
                      disabled={!!macroEdit || saving}
                      onClick={() => setEquipmentWizard(true)}
                    >
                      Equipment wizard
                    </button>
                    <select
                      aria-label="Open saved project"
                      disabled={!!macroEdit}
                      value=""
                      onChange={(e) => loadProject(e.target.value)}
                    >
                      <option value="">Open project…</option>
                      {projects.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name} · r{p.revision}
                        </option>
                      ))}
                    </select>
                    <select
                      aria-label="Choose VAV template"
                      disabled={!!macroEdit}
                      value=""
                      onChange={(e) => {
                        const p = templates.find(
                          (p) => p.id === e.target.value,
                        );
                        if (p) {
                          change({
                            ...structuredClone(p),
                            id: p.id + "-" + Date.now().toString(36),
                          });
                          setSelected(null);
                          setVersions([]);
                          setInputs({});
                          setTimeout(() => flow.fitView({ padding: 0.2 }), 100);
                        }
                      }}
                    >
                      <option value="">VAV templates…</option>
                      {templates.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name}
                        </option>
                      ))}
                    </select>
                    <span className="toolbar-divider" />
                    <button
                      title="Undo"
                      disabled={!undoStack.length}
                      onClick={undo}
                    >
                      <Undo2 size={15} />
                    </button>
                    <button
                      title="Redo"
                      disabled={!redoStack.length}
                      onClick={redo}
                    >
                      <Redo2 size={15} />
                    </button>
                    <button
                      title="Fit view"
                      onClick={() => flow.fitView({ padding: 0.2 })}
                    >
                      <Maximize size={15} />
                    </button>
                    <button
                      title="Program settings"
                      onClick={() => {
                        setSettings(true);
                        refreshVersions(program.id).catch(() => {});
                      }}
                    >
                      <Settings2 size={15} />
                    </button>
                  </div>
                  <div className="button-row">
                    <button onClick={() => importInput.current?.click()}>
                      <Upload size={15} /> Import
                    </button>
                    <input
                      hidden
                      type="file"
                      accept=".json,.st,.xml,.graphml,.sedona.zip,.sax,.sab,.bog,.bas"
                      ref={importInput}
                      onChange={(e) => {
                        importProgram(e.target.files?.[0]);
                        e.target.value = "";
                      }}
                    />
                    <select
                      aria-label="Export format"
                      value={format}
                      onChange={(e) => setFormat(e.target.value)}
                    >
                      <option value="json">BMS project</option>
                      <option value="st">Structured Text</option>
                      <option value="plcopen">PLCopen XML</option>
                      <option value="graphml">GraphML</option>
                      <option value="bog">
                        Niagara BOG (primitive profile)
                      </option>
                      <option value="temco-bas">Temco Control Basic</option>
                      <option value="sedona">Native Sedona bundle</option>
                      <option value="sedona-sax">
                        Sedona SAX (kit required)
                      </option>
                      <option value="sedona-sab">
                        Sedona SAB (kit required)
                      </option>
                    </select>
                    <button
                      onClick={async () => {
                        try {
                          await download(
                            "/export",
                            { program, format },
                            program.id +
                              "." +
                              {
                                json: "bms.json",
                                st: "st",
                                plcopen: "xml",
                                graphml: "graphml",
                                bog: "bog",
                                "temco-bas": "bas",
                                sedona: "sedona.zip",
                                "sedona-sax": "sax",
                                "sedona-sab": "sab",
                              }[format],
                          );
                          setMessage(
                            format === "bog"
                              ? "Exported native Niagara BOG primitives. Review event, status and priority semantics in Niagara; native runtime acceptance is unverified."
                              : format === "temco-bas"
                                ? "Exported Control Basic source. Compile, verify with the native interpreter and review a separate controller transfer in Temco native."
                                : "Exported " +
                                  format +
                                  ". Review target compatibility before deployment.",
                          );
                        } catch (e) {
                          setMessage(String(e));
                        }
                      }}
                    >
                      <Download size={15} /> Export
                    </button>
                  </div>
                </div>
                <ConversionPreview program={program} />
                <div className="editor-layout">
                  <aside className="palette">
                    <div className="panel-heading">
                      <Workflow size={16} /> BLOCK LIBRARY{" "}
                      <span>{specs.length}</span>
                    </div>
                    <div className="search">
                      <Search size={15} />
                      <input
                        aria-label="Search blocks"
                        placeholder="Search blocks…"
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                      />
                    </div>
                    <div className="palette-scroll">
                      {[
                        "I/O",
                        "Math",
                        "Logic",
                        "Control",
                        "Supervision",
                        "Macros",
                      ].map((category) => (
                        <div className="palette-group" key={category}>
                          <div className="small-heading">{category}</div>
                          {palette
                            .filter((b) => b.category === category)
                            .map((b) => (
                              <button
                                className="palette-block"
                                key={specKey(b)}
                                draggable
                                onDragStart={(e) => {
                                  e.dataTransfer.setData(
                                    "application/bms-kind",
                                    specKey(b),
                                  );
                                  e.dataTransfer.effectAllowed = "copy";
                                }}
                                onClick={() => add(specKey(b))}
                                title={b.help || b.title}
                              >
                                <span
                                  className={
                                    "block-mark category-" +
                                    category.toLowerCase().replace("/", "")
                                  }
                                >
                                  {b.stateful
                                    ? "↻"
                                    : b.kind === "Input"
                                      ? "I"
                                      : b.kind === "Output"
                                        ? "O"
                                        : b.title.slice(0, 1)}
                                </span>
                                <span>
                                  {b.title}
                                  <small>
                                    {b.inputs.length
                                      ? b.inputs.length + " inputs"
                                      : "source"}
                                  </small>
                                </span>
                                <Plus size={13} />
                              </button>
                            ))}
                        </div>
                      ))}
                    </div>
                    <div className="palette-footer">
                      Drag a block onto the wiresheet.
                      <br />
                      Click a block to add it.
                    </div>
                  </aside>
                  <div className="editor-center">
                    <Canvas
                      program={program}
                      blocks={specs}
                      last={history.at(-1)}
                      issues={issues}
                      selected={selection}
                      onSelect={setSelected}
                      onChange={nodeChanges}
                      onBeginDrag={remember}
                      onConnect={connect}
                      onAdd={add}
                      onRemoveWire={(id) =>
                        change({
                          ...program,
                          edges: program.edges.filter((e) => e.id !== id),
                        })
                      }
                    />
                    <SimulationPanel
                      program={program}
                      history={history}
                      inputs={inputs}
                      setInputs={setInputs}
                      forces={forces}
                      onReleaseForces={() => setForces({})}
                      running={pacing.running}
                      setRunning={(value) =>
                        value ? pacing.run() : pacing.pause()
                      }
                      pacing={pacing}
                      simBusy={
                        simBusy ||
                        simUncertain ||
                        cleanupStatus.pending > 0 ||
                        cleanupStatus.failed > 0
                      }
                      cleanup={{
                        ...cleanupStatus,
                        unknown: unknownSession,
                        cache: cacheStatus,
                        retry: retrySimulationCleanup,
                        check: checkSimulationCache,
                      }}
                      onStep={() => {
                        pacing.retire();
                        void step().catch(() => {});
                      }}
                      onReset={resetSimulation}
                      onRunScenario={runSimulationScenario}
                      error={simError}
                      recordHistory={recordHistory}
                      setRecordHistory={setRecordHistory}
                      recordingError={recordingError}
                      nextClock={nextClock}
                      setNextClock={setNextClock}
                    />
                  </div>
                  {selection.length > 1 ? (
                    <SelectionPanel
                      nodes={program.nodes.filter((n) =>
                        selection.includes(n.id),
                      )}
                      onSelect={setSelected}
                      onCopy={copySelection}
                      onDuplicate={duplicate}
                      onDelete={remove}
                      onAlign={alignSelection}
                    />
                  ) : (
                    <Inspector
                      node={active}
                      block={specs.find(
                        (b) =>
                          b.kind === active?.kind &&
                          (b.kind !== "Macro" ||
                            b.parameters.definition ===
                              active?.params.definition),
                      )}
                      onEdit={edit}
                      onDelete={remove}
                      onDuplicate={duplicate}
                      program={program}
                      onSelect={setSelected}
                      forces={forces}
                      onForceChange={setForces}
                      last={history.at(-1)}
                    />
                  )}
                </div>
                <div className="validation-bar">
                  <button
                    className={
                      validationStatus === "complete"
                        ? errors.length
                          ? "validation-error"
                          : "validation-ok"
                        : ""
                    }
                    onClick={() => setShowIssues(!showIssues)}
                  >
                    {validationStatus !== "complete" || errors.length ? (
                      <AlertTriangle size={14} />
                    ) : (
                      <CheckCircle2 size={14} />
                    )}{" "}
                    {validationStatus === "pending"
                      ? "Checking graph…"
                      : validationStatus === "error"
                        ? "Graph check unavailable"
                        : errors.length
                          ? errors.length + " graph errors"
                          : "Graph checks passed"}{" "}
                    <span>
                      {issues.filter((d) => d.level === "warning").length}{" "}
                      notices
                    </span>
                  </button>
                  <span>
                    {program.nodes.length} blocks · {program.edges.length} wires
                    · {program.scan_seconds}s scan · r{program.revision}
                  </span>
                </div>
                {showIssues && (
                  <div className="diagnostics">
                    {issues.length ? (
                      issues.map((d, i) => (
                        <button key={i} onClick={() => setSelected(d.node)}>
                          <span
                            className={
                              "pill " + (d.level === "error" ? "pending" : "")
                            }
                          >
                            {d.level}
                          </span>
                          <b>{d.node || "Program"}</b>
                          {d.message}
                        </button>
                      ))
                    ) : (
                      <p>
                        {validationStatus === "pending"
                          ? "Checking the current graph…"
                          : validationStatus === "error"
                            ? "Graph checks did not complete."
                            : "All graph checks passed. This checks our graph semantics, not native firmware compatibility."}
                      </p>
                    )}
                  </div>
                )}
              </>
            ) : tab === "caf-compare" ? (
              <CafComparison />
            ) : tab === "bog" ? (
              <NiagaraInspector />
            ) : tab === "truth-tables" ? (
              <TruthTableReview />
            ) : tab === "hardware" ? (
              <HardwareDefinitions />
            ) : tab === "connections" ? (
              <Connections />
            ) : tab === "runtime" ? (
              <RuntimePanel program={program} inputs={inputs} />
            ) : tab === "native" ? (
              <NativeSimulator
                program={program}
                onSaved={(p) => {
                  recordSaved(
                    p,
                    program,
                    renderedDraftEpoch,
                    renderedNavigationEpoch,
                    true,
                  );
                  refreshProjects().catch((e) => setMessage(String(e)));
                }}
              />
            ) : tab === "temco" ? (
              <TemcoSimulator program={program} />
            ) : tab === "iec" ? (
              <IECVerifier program={program} />
            ) : tab === "system" ? (
              <SystemSimulation program={program} />
            ) : tab === "observations" ? (
              <Observations />
            ) : tab === "notifications" ? (
              <Notifications />
            ) : tab === "field-trends" ? (
              <FieldTrends />
            ) : tab === "device-history" ? (
              <DeviceHistory />
            ) : tab === "conformance" ? (
              <ConformancePanel program={program} />
            ) : tab === "macros" ? (
              <MacroLibrary
                program={program}
                selectedIds={selection}
                onChange={change}
                onSelect={setSelected}
                onEditDefinition={openMacroEdit}
              />
            ) : (
              <Resources />
            )}
          </Suspense>
        </main>
      </div>
      {equipmentWizard && tab === "editor" && !macroEdit && (
        <Suspense fallback={<div>Opening equipment wizard…</div>}>
          <EquipmentWizard
            source={program}
            onClose={() => setEquipmentWizard(false)}
            onCreate={(generated, sourceKey) => {
              if (
                JSON.stringify(latestProgram.current) !== sourceKey ||
                macroEdit ||
                tab !== "editor"
              )
                return false;
              loadEpoch.current++;
              versionsEpoch.current++;
              change(generated);
              setSelected(null);
              setVersions([]);
              setInputs({});
              setTimeout(() => flow.fitView({ padding: 0.2 }), 100);
              return true;
            }}
          />
        </Suspense>
      )}
      {recoveryError && (
        <div className="draft-recovery-error" role="alert">
          {recoveryError}
        </div>
      )}
      <footer className="app-footer">
        <span>
          <span className="status-dot on" /> Local storage · configured alarm
          delivery
        </span>
        {lastSaved && (
          <span
            role="status"
            aria-label="Last saved revision"
            title={lastSaved.id}
          >
            Saved {lastSaved.name} · r{lastSaved.revision}
          </span>
        )}
        <span>
          BMS Studio 0.1 · Development build · Native vendor adapters pending
        </span>
      </footer>
      {message && (
        <div className="toast" role="status">
          <span>{message}</span>
          <button aria-label="Dismiss message" onClick={() => setMessage("")}>
            <X size={16} />
          </button>
        </div>
      )}
      {settings && (
        <div className="modal-backdrop">
          <div className="modal">
            <div className="card-header">
              <h2>Program settings</h2>
              <button
                aria-label="Close settings"
                onClick={() => setSettings(false)}
              >
                <X size={18} />
              </button>
            </div>
            <div className="card-body">
              <label>
                Project identifier
                <input
                  value={program.id}
                  onChange={(e) =>
                    change({ ...program, id: e.target.value, revision: 0 })
                  }
                />
              </label>
              <label>
                Description
                <textarea
                  value={program.description}
                  onChange={(e) =>
                    change({ ...program, description: e.target.value })
                  }
                />
              </label>
              <div className="form-grid">
                <label>
                  Scan interval (seconds)
                  <input
                    type="number"
                    min={0.01}
                    max={60}
                    step={0.01}
                    value={program.scan_seconds}
                    onChange={(e) =>
                      change({
                        ...program,
                        scan_seconds: Number(e.target.value),
                      })
                    }
                  />
                </label>
                <label>
                  Target family
                  <select
                    value={program.target.family}
                    onChange={(e) =>
                      change({
                        ...program,
                        target: { ...program.target, family: e.target.value },
                      })
                    }
                  >
                    <option value="universal-runtime">
                      BMS Studio runtime
                    </option>
                    <option value="johnson-fx">Johnson Controls FX</option>
                    <option value="johnson-metasys">
                      Johnson Controls Metasys
                    </option>
                  </select>
                </label>
                <label>
                  Controller model
                  <input
                    value={program.target.model}
                    onChange={(e) =>
                      change({
                        ...program,
                        target: { ...program.target, model: e.target.value },
                      })
                    }
                  />
                </label>
                <label>
                  Firmware
                  <input
                    value={program.target.firmware}
                    onChange={(e) =>
                      change({
                        ...program,
                        target: { ...program.target, firmware: e.target.value },
                      })
                    }
                  />
                </label>
                <label>
                  CAF release mode
                  <input
                    value={program.target.release_mode}
                    onChange={(e) =>
                      change({
                        ...program,
                        target: {
                          ...program.target,
                          release_mode: e.target.value,
                        },
                      })
                    }
                  />
                </label>
              </div>
              <p className="help-text">
                Selecting a vendor records the target; it does not supply a
                native compiler or certify the graph.
              </p>
              <h3>Saved revisions</h3>
              {program.metadata?.conversion && (
                <details open className="conversion-report">
                  <summary>Native conversion report · review required</summary>
                  <pre>
                    {JSON.stringify(program.metadata.conversion, null, 2)}
                  </pre>
                </details>
              )}
              {versions.map((v) => (
                <button
                  className="version-row"
                  key={v.revision}
                  onClick={() => loadProject(program.id, v.revision)}
                >
                  Revision {v.revision}
                  <small>{v.created}</small>
                  <FolderOpen size={14} />
                </button>
              ))}
              {!versions.length && <p>No saved revisions for this project.</p>}
              <button className="primary" onClick={() => setSettings(false)}>
                Done
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
