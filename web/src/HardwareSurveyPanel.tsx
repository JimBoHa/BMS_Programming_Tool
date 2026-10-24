import { useEffect, useMemo, useRef, useState } from "react";
import { Download, FileSearch, RefreshCw, Search, Upload } from "lucide-react";
import { api, saveBlob } from "./api";
import "./hardware-survey.css";
import { SensorSupplyPanel } from "./SensorSupplyPanel";
import { PhysicalCapacityPanel } from "./PhysicalCapacityPanel";
import {
  ModelTransportJobEvidence,
  ModelTransportPanel,
} from "./ModelTransportPanel";
import type { Qualification } from "./modelTransportContract";

type RecordValue = Record<string, any>;
type Target = {
  transport?: "bacnet-ip" | "direct-mstp";
  address: string;
  device: string;
  router?: string;
  dnet?: number | null;
};
type SurveyInput = {
  object: string;
  name?: string;
  description?: string;
  device_type?: string;
  slot?: number | null;
  sa_mac?: number | null;
  host?: unknown;
  setup_raw?: unknown;
  present_value?: unknown;
  units?: unknown;
  reliability?: unknown;
  status_flags?: unknown;
  out_of_service?: unknown;
  errors?: unknown[];
  [key: string]: any;
};
type SurveyReport = {
  id: string;
  profile?: string;
  imported?: boolean;
  started_at?: string;
  finished_at?: string;
  target: Target;
  identity?: RecordValue;
  inventory?: {
    complete?: boolean;
    total?: number;
    read?: number;
    errors?: unknown[];
  };
  inputs: SurveyInput[];
  modules?: RecordValue[];
  candidates?: RecordValue[];
  occupancy?: unknown;
  warnings?: unknown[];
  errors?: unknown[];
  scope?: string;
  [key: string]: any;
};
type Job = {
  id: string;
  status: string;
  report_id?: string;
  report?: SurveyReport;
  archive_id?: string;
  archive?: RecordValue;
  kind?: string;
  error?: string;
  progress?: unknown;
  target?: Target;
  connector_config?: RecordValue;
};
type HardwareStatus = {
  limits?: RecordValue;
  jobs?: Job[];
  reports?: RecordValue[];
  archives?: RecordValue[];
  captures?: RecordValue[];
};
const base = "/bacnet/hardware";
const terminalStatuses = new Set([
  "completed",
  "complete",
  "succeeded",
  "partial",
  "interrupted",
  "cancelled",
  "canceled",
  "failed",
  "error",
]);
function text(value: unknown): string {
  if (value === undefined || value === null || value === "") return "—";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}
function sourceLabel(target?: Target, connector?: RecordValue) {
  if (!target) return "Source unavailable";
  const serial = target.transport === "direct-mstp";
  const link =
    serial && connector
      ? ` · ${connector.port} · ${connector.baudrate} baud · client MAC ${connector.mac} · instance ${connector.instance} · max master ${connector.max_master} · max info frames ${connector.max_info_frames}`
      : "";
  return `${serial ? "Direct MS/TP MAC " : ""}${target.address} / ${target.device}${target.router ? ` via ${target.router}` : ""}${target.dnet != null ? ` · DNET ${target.dnet}` : ""}${link}`;
}
function hostLabel(input: Pick<SurveyInput, "sa_mac" | "host">) {
  if (input.sa_mac != null) return `SA ${input.sa_mac}`;
  if (input.host && typeof input.host === "object") {
    const host = input.host as RecordValue;
    if (host.kind === "sa" && host.sa_mac != null) return `SA ${host.sa_mac}`;
    if (["local", "local-inferred", "local-configured"].includes(host.kind))
      return "Base controller";
    return "Unknown host";
  }
  if (
    typeof input.host === "string" &&
    !["base", "local", "controller"].includes(input.host)
  )
    return input.host;
  return ["base", "local", "controller"].includes(String(input.host))
    ? "Base controller"
    : "Unknown host";
}
function messages(items: unknown[] | undefined) {
  return (items || []).map(text).join(" · ");
}
function capacityLabel(capacity: unknown) {
  if (!capacity || typeof capacity !== "object")
    return "Unknown input capacity";
  const values = capacity as RecordValue;
  const slots = (items: unknown) =>
    Array.isArray(items)
      ? items.map((slot) => `IN${slot}`).join(", ") || "none"
      : "unknown";
  return `Physical universal inputs: ${slots(values.universal_inputs)} · Dedicated binary inputs: ${slots(values.binary_inputs)}${values.voltage_input_range ? ` · ${values.voltage_input_range}` : ""}`;
}
function CapacityEvidence({ capacity }: { capacity: unknown }) {
  if (!capacity || typeof capacity !== "object") return null;
  const values = capacity as RecordValue;
  const source = values.source_document as RecordValue | undefined;
  const label = source
    ? `${source.document_number} Rev ${source.revision} (${source.date}), PDF pages ${(source.pdf_pages || []).join(", ")}`
    : "Manufacturer capacity reference";
  const url = source?.url || values.source;
  const trustedUrl =
    typeof url === "string" &&
    url.startsWith("https://docs.johnsoncontrols.com/")
      ? url
      : null;
  return (
    <>
      {values.physical_terminal_scope && (
        <p className="help-text">{text(values.physical_terminal_scope)}</p>
      )}
      {trustedUrl && (
        <p className="help-text">
          <a href={trustedUrl} target="_blank" rel="noopener noreferrer">
            {label}
          </a>
        </p>
      )}
    </>
  );
}
function isBinaryOnUniversal(input: SurveyInput) {
  return (
    input.object?.startsWith("binary-input,") &&
    /^UI\b/i.test(input.device_type || "")
  );
}

export function HardwareSurveyPanel({
  connected,
  defaultAddress,
  defaultDevice,
  defaultRouter = "",
  defaultDnet = null,
  defaultTransport = "bacnet-ip",
  interfaceConfig,
}: {
  connected: boolean;
  defaultAddress: string;
  defaultDevice: string;
  defaultRouter?: string;
  defaultDnet?: number | null;
  defaultTransport?: "bacnet-ip" | "direct-mstp";
  interfaceConfig?: RecordValue;
}) {
  const [transport, setTransport] = useState(defaultTransport);
  const [address, setAddress] = useState(defaultAddress);
  const [device, setDevice] = useState(defaultDevice);
  const [router, setRouter] = useState(defaultRouter);
  const [dnet, setDnet] = useState(
    defaultDnet == null ? "" : String(defaultDnet),
  );
  const [deadline, setDeadline] = useState("120");
  const [objectLimit, setObjectLimit] = useState("512");
  const [inputLimit, setInputLimit] = useState("256");
  const [status, setStatus] = useState<HardwareStatus>({});
  const [job, setJob] = useState<Job | null>(null);
  const [report, setReport] = useState<SurveyReport | null>(null);
  const [archiveId, setArchiveId] = useState("");
  const [archiveEvidence, setArchiveEvidence] = useState<RecordValue | null>(
    null,
  );
  const [archiveFileObject, setArchiveFileObject] = useState("");
  const [captureId, setCaptureId] = useState("");
  const [reportId, setReportId] = useState("");
  const [jobId, setJobId] = useState("");
  const [query, setQuery] = useState("");
  const [host, setHost] = useState("all");
  const [kind, setKind] = useState("all");
  const [onlySpareHosts, setOnlySpareHosts] = useState(false);
  const [sourceObject, setSourceObject] = useState("");
  const [destinationSa, setDestinationSa] = useState("");
  const [destinationSlot, setDestinationSlot] = useState("");
  const [plan, setPlan] = useState<RecordValue | null>(null);
  const [sensorPlan, setSensorPlan] = useState<RecordValue | null>(null);
  const [useRelocation, setUseRelocation] = useState(false);
  const [channels, setChannels] = useState([
    {
      name: "Outdoor-air temperature",
      sa: "",
      slot: "",
      signalHigh: "5",
      engineeringLow: "-40",
      engineeringHigh: "160",
      units: "degF",
    },
    {
      name: "Outdoor-air humidity",
      sa: "",
      slot: "",
      signalHigh: "5",
      engineeringLow: "0",
      engineeringHigh: "100",
      units: "%RH",
    },
  ]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [outcome, setOutcome] = useState("");
  const [qualifyModel, setQualifyModel] = useState(false);
  const [qualification, setQualification] = useState<Qualification | null>(
    null,
  );
  const mounted = useRef(false);
  const epoch = useRef(0);
  const refreshEpoch = useRef(0);
  const running = useRef<Job | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const current = (generation: number) =>
    mounted.current && epoch.current === generation;
  const polling = !!job && !terminalStatuses.has(job.status);

  useEffect(() => {
    mounted.current = true;
    void refresh();
    return () => {
      mounted.current = false;
      epoch.current++;
      refreshEpoch.current++;
      if (timer.current) clearTimeout(timer.current);
    };
  }, []);
  // Interface readiness retires owned work without replacing local target intent.
  useEffect(() => {
    invalidate();
  }, [connected]);
  // Retire optional admission while preserving historical generic reports and
  // their existing archive/interface mismatch evidence.
  useEffect(() => {
    setQualification(null);
  }, [JSON.stringify(interfaceConfig ?? null)]);
  useEffect(() => {
    invalidate();
    setTransport(defaultTransport);
    setAddress(defaultAddress);
    setDevice(defaultDevice);
    setRouter(defaultRouter);
    setDnet(defaultDnet == null ? "" : String(defaultDnet));
  }, [
    defaultAddress,
    defaultDevice,
    defaultRouter,
    defaultDnet,
    defaultTransport,
  ]);
  useEffect(() => {
    let active = true;
    setArchiveEvidence(null);
    if (archiveId)
      void api(`${base}/archives/${encodeURIComponent(archiveId)}`)
        .then((next) => {
          if (active && mounted.current) setArchiveEvidence(next);
        })
        .catch((e) => {
          if (active && mounted.current)
            setError(e instanceof Error ? e.message : String(e));
        });
    return () => {
      active = false;
    };
  }, [archiveId]);

  function invalidate() {
    epoch.current++;
    if (timer.current) clearTimeout(timer.current);
    const previous = running.current;
    running.current = null;
    if (previous && !terminalStatuses.has(previous.status))
      void api(
        `${base}/jobs/${encodeURIComponent(previous.id)}/cancel`,
        {},
      ).catch(() => {});
    setJob(null);
    setReport(null);
    setPlan(null);
    setSensorPlan(null);
    setUseRelocation(false);
    setSourceObject("");
    setArchiveFileObject("");
    setBusy(false);
    setError("");
    setOutcome("");
    setHost("all");
    setQualification(null);
  }
  function edit(change: () => void) {
    invalidate();
    change();
  }
  async function refresh(generation?: number) {
    const refreshId = ++refreshEpoch.current;
    try {
      const next = await api(`${base}/status`);
      if (
        mounted.current &&
        refreshId === refreshEpoch.current &&
        (generation === undefined || current(generation))
      )
        setStatus(next);
    } catch (e) {
      if (
        mounted.current &&
        refreshId === refreshEpoch.current &&
        (generation === undefined || current(generation))
      )
        setError(e instanceof Error ? e.message : String(e));
    }
  }
  async function action(work: (generation: number) => Promise<void>) {
    if (busy || polling) return;
    const generation = ++epoch.current;
    setBusy(true);
    setError("");
    setOutcome("");
    try {
      await work(generation);
    } catch (e) {
      if (current(generation))
        setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (current(generation)) setBusy(false);
    }
  }
  function showReport(next: SurveyReport) {
    setReport(next);
    setArchiveFileObject("");
    setReportId(next.id);
    setPlan(null);
    setSensorPlan(null);
    setUseRelocation(false);
    setSourceObject("");
    setHost("all");
  }
  async function observe(next: Job, generation: number) {
    if (!current(generation)) {
      if (!terminalStatuses.has(next.status))
        void api(
          `${base}/jobs/${encodeURIComponent(next.id)}/cancel`,
          {},
        ).catch(() => {});
      return;
    }
    running.current = next;
    setJob(next);
    if (terminalStatuses.has(next.status)) {
      running.current = null;
      if (next.archive_id) setArchiveId(next.archive_id);
      if (next.report) showReport(next.report);
      else if (next.report_id) {
        const saved = await api(
          `${base}/reports/${encodeURIComponent(next.report_id)}`,
        );
        if (current(generation)) showReport(saved);
      }
      if (current(generation)) {
        if (next.error) setError(next.error);
        setOutcome(
          `${next.kind === "read-archive" || next.kind === "archive-read" || next.archive_id ? "Controller archive read" : "Survey"} ${next.status}. Results retain incomplete reads and property errors.`,
        );
        await refresh(generation);
      }
      return;
    }
    timer.current = setTimeout(async () => {
      try {
        await observe(
          await api(`${base}/jobs/${encodeURIComponent(next.id)}`),
          generation,
        );
      } catch (e) {
        if (current(generation)) {
          setError(
            `Progress unavailable: ${e instanceof Error ? e.message : String(e)}. Cancel or refresh the saved job before starting another survey.`,
          );
        }
      }
    }, 500);
  }
  async function survey() {
    if (busy || polling || !connected) return;
    if (qualifyModel && !qualification) return;
    const generation = ++epoch.current;
    setBusy(true);
    setError("");
    setOutcome("");
    setReport(null);
    setPlan(null);
    try {
      const integer = (
        value: string,
        label: string,
        minimum: number,
        maximum: number,
      ) => {
        const parsed = Number(value);
        if (
          !value.trim() ||
          !Number.isInteger(parsed) ||
          parsed < minimum ||
          parsed > maximum
        )
          throw new Error(
            `${label} must be an integer from ${minimum} to ${maximum}.`,
          );
        return parsed;
      };
      if (!address.trim() || !/^device,\d+$/.test(device.trim()))
        throw new Error(
          "Enter the explicit controller address and Device object, such as device,1234.",
        );
      if (
        transport === "direct-mstp" &&
        (!/^(?:0|[1-9][0-9]{0,2})$/.test(address) ||
          Number(address) > 254 ||
          Number(address) === interfaceConfig?.mac)
      )
        throw new Error(
          "Select a remote decimal MS/TP MAC from 0 through 254, excluding this client's own station.",
        );
      if (Boolean(router.trim()) !== Boolean(dnet.trim()))
        throw new Error(
          "Supply both router and destination network for a routed target, or leave both empty for a direct target.",
        );
      const next = await api(`${base}/survey`, {
        transport,
        address: address.trim(),
        device: device.trim(),
        ...(router.trim()
          ? {
              router: router.trim(),
              dnet: integer(dnet, "Destination network", 1, 65534),
            }
          : {}),
        max_objects: integer(objectLimit, "Object limit", 1, 4096),
        max_inputs: integer(inputLimit, "Input limit", 1, 1024),
        timeout_seconds: integer(deadline, "Survey deadline", 1, 180),
        property_timeout: 1.5,
        ...(qualifyModel ? { model_qualification: qualification } : {}),
      });
      await observe(next, generation);
    } catch (e) {
      if (current(generation))
        setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (current(generation)) setBusy(false);
    }
  }
  async function cancel() {
    const active = running.current || job;
    if (!active || terminalStatuses.has(active.status)) return;
    const generation = epoch.current;
    if (timer.current) clearTimeout(timer.current);
    setError("");
    try {
      await observe(
        await api(`${base}/jobs/${encodeURIComponent(active.id)}/cancel`, {}),
        generation,
      );
    } catch (e) {
      if (current(generation))
        setError(e instanceof Error ? e.message : String(e));
    }
  }
  async function refreshJobProgress() {
    if (!job || busy) return;
    const generation = epoch.current;
    if (timer.current) clearTimeout(timer.current);
    setError("");
    try {
      await observe(
        await api(`${base}/jobs/${encodeURIComponent(job.id)}`),
        generation,
      );
    } catch (e) {
      if (current(generation))
        setError(e instanceof Error ? e.message : String(e));
    }
  }
  async function readArchive() {
    if (!report || !connected || busy || polling) return;
    const generation = ++epoch.current;
    setBusy(true);
    setError("");
    setOutcome("");
    try {
      if (
        archiveFileObject.trim() &&
        !/^file,\d+$/.test(archiveFileObject.trim())
      )
        throw new Error(
          "Use a BACnet File identifier such as file,1, or leave it empty for advertised archive detection.",
        );
      await observe(
        await api(`${base}/read-archive`, {
          report_id: report.id,
          ...(archiveFileObject.trim()
            ? { file_object: archiveFileObject.trim() }
            : {}),
        }),
        generation,
      );
    } catch (e) {
      if (current(generation))
        setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (current(generation)) setBusy(false);
    }
  }
  async function upload(file: File | undefined, archive: boolean) {
    if (!file) return;
    await action(async (generation) => {
      const form = new FormData();
      form.append("file", file);
      const next = await api(
        `${base}/${archive ? "archive" : "import-report"}`,
        form,
      );
      if (!current(generation)) return;
      if (archive) {
        setArchiveId(next.id);
        setOutcome(
          `Read configured hardware from ${file.name}. Physical module labels remain unverified.`,
        );
      } else {
        showReport(next);
        setOutcome(
          "Opened the saved survey with its original target and completeness evidence. No network reads were started.",
        );
      }
      await refresh(generation);
    });
  }
  async function loadReport() {
    if (!reportId) return;
    await action(async (generation) => {
      const next = await api(`${base}/reports/${encodeURIComponent(reportId)}`);
      if (current(generation)) showReport(next);
    });
  }
  async function useCapture() {
    if (!captureId) return;
    await action(async (generation) => {
      const next = await api(`${base}/archive/capture`, {
        capture_id: captureId,
      });
      if (!current(generation)) return;
      setArchiveId(next.id);
      setOutcome(
        "Read the saved file capture locally. An opaque capture is not assumed to be a native application or a current controller backup.",
      );
      await refresh(generation);
    });
  }
  async function loadJob() {
    if (!jobId) return;
    await action(async (generation) => {
      const next = await api(`${base}/jobs/${encodeURIComponent(jobId)}`);
      await observe(next, generation);
    });
  }
  async function removeSaved(
    kind: "reports" | "archives" | "jobs",
    id: string,
  ) {
    if (!id) return;
    await action(async (generation) => {
      await api(
        `${base}/${kind}/${encodeURIComponent(id)}`,
        undefined,
        "DELETE",
      );
      if (!current(generation)) return;
      if (kind === "reports") {
        setReportId("");
        if (report?.id === id) {
          setReport(null);
          setPlan(null);
          setSensorPlan(null);
        }
      }
      if (kind === "archives") setArchiveId("");
      if (kind === "jobs") {
        setJobId("");
        if (job?.id === id) setJob(null);
      }
      setOutcome(
        `Removed the saved ${kind === "reports" ? "survey report" : kind === "archives" ? "archive evidence" : "finished job"} locally. Controllers were not changed.`,
      );
      await refresh(generation);
    });
  }
  async function enrich() {
    if (!report || !archiveId) return;
    await action(async (generation) => {
      const next = await api(`${base}/enrich`, {
        report_id: report.id,
        archive_id: archiveId,
      });
      if (!current(generation)) return;
      showReport(next);
      setOutcome(
        "Correlated archive hardware with the saved input survey. Configured models and unassigned terminals require physical verification.",
      );
      await refresh(generation);
    });
  }
  async function exportReport(format: "json" | "csv") {
    if (!report) return;
    const selected = report;
    await action(async (generation) => {
      const response = await fetch(
        `/api${base}/reports/${encodeURIComponent(selected.id)}/export?format=${format}`,
      );
      if (!response.ok) {
        const body = await response.json();
        throw new Error(
          typeof body.detail === "string"
            ? body.detail
            : JSON.stringify(body.detail),
        );
      }
      const blob = await response.blob();
      if (!current(generation)) return;
      saveBlob(blob, `hardware-inputs-${selected.id}.${format}`);
      setOutcome(
        `Downloaded ${format.toUpperCase()} for ${sourceLabel(selected.target)}.`,
      );
    });
  }
  async function exportArchive(format: "source" | "json") {
    if (!archiveId) return;
    const selected =
      archiveEvidence?.id === archiveId
        ? archiveEvidence
        : (status.archives || []).find((archive) => archive.id === archiveId);
    await action(async (generation) => {
      const response = await fetch(
        `/api${base}/archives/${encodeURIComponent(archiveId)}/export?format=${format}`,
      );
      if (!response.ok) {
        const body = await response.json();
        throw new Error(
          typeof body.detail === "string"
            ? body.detail
            : JSON.stringify(body.detail),
        );
      }
      const blob = await response.blob();
      if (!current(generation)) return;
      const filename =
        format === "json"
          ? `hardware-archive-${archiveId}.json`
          : (
              selected?.source?.filename ||
              `hardware-archive-${archiveId}.${String(selected?.archive_format).toUpperCase() === "CAF" ? "caf" : "moi"}`
            )
              .split(/[\\/]/)
              .at(-1)!;
      saveBlob(blob, filename);
      setOutcome(
        format === "source"
          ? "Downloaded the preserved original archive bytes. Native application recovery remains unverified."
          : "Downloaded configured hardware evidence and provenance JSON.",
      );
    });
  }
  async function exportJob() {
    if (!jobId) return;
    await action(async (generation) => {
      const response = await fetch(
        `/api${base}/jobs/${encodeURIComponent(jobId)}/export`,
      );
      if (!response.ok) {
        const body = await response.json();
        throw new Error(
          typeof body.detail === "string"
            ? body.detail
            : JSON.stringify(body.detail),
        );
      }
      const blob = await response.blob();
      if (current(generation)) saveBlob(blob, `hardware-job-${jobId}.json`);
    });
  }
  async function relocate() {
    if (!report || !sourceObject) return;
    await action(async (generation) => {
      const slot = Number(destinationSlot),
        sa = Number(destinationSa);
      if (
        !destinationSlot.trim() ||
        !Number.isInteger(slot) ||
        slot < 1 ||
        slot > 64
      )
        throw new Error("Choose a destination input slot from 1 to 64.");
      if (destinationSa.trim() && (!Number.isInteger(sa) || sa < 4 || sa > 127))
        throw new Error(
          "Choose a destination SA module address from 4 through 127, or leave it empty for the base controller.",
        );
      setPlan(null);
      setSensorPlan(null);
      const next = await api(`${base}/relocation`, {
        report_id: report.id,
        source_object: sourceObject,
        destination_sa_mac: destinationSa.trim() ? sa : null,
        destination_slot: slot,
      });
      if (current(generation)) setPlan(next);
    });
  }
  async function reviewSensors() {
    if (!report) return;
    await action(async (generation) => {
      const numeric = (value: string, label: string) => {
        const parsed = Number(value);
        if (!value.trim() || !Number.isFinite(parsed))
          throw new Error(`${label} requires a finite number.`);
        return parsed;
      };
      const payload: RecordValue = {
        report_id: report.id,
        channels: channels.map((channel) => ({
          name: channel.name,
          sa_mac: channel.sa.trim()
            ? numeric(channel.sa, `${channel.name} SA address`)
            : null,
          slot: numeric(channel.slot, `${channel.name} input slot`),
          signal_low: 0,
          signal_high: numeric(channel.signalHigh, "Signal maximum"),
          engineering_low: numeric(
            channel.engineeringLow,
            "Engineering minimum",
          ),
          engineering_high: numeric(
            channel.engineeringHigh,
            "Engineering maximum",
          ),
          units: channel.units,
        })),
      };
      if (useRelocation) {
        if (
          !sourceObject ||
          !destinationSlot ||
          plan?.status !== "review-required"
        )
          throw new Error(
            "First obtain a relocation review that is ready for physical and native-program checks.",
          );
        payload.relocation = {
          source_object: sourceObject,
          destination_sa_mac: destinationSa.trim()
            ? Number(destinationSa)
            : null,
          destination_slot: Number(destinationSlot),
        };
      }
      setSensorPlan(null);
      const next = await api(`${base}/sensor-plan`, payload);
      if (current(generation)) setSensorPlan(next);
    });
  }
  const candidates = Array.isArray(report?.candidates) ? report.candidates : [];
  const candidateHosts = new Set(candidates.map(hostLabel));
  const hosts = [...new Set((report?.inputs || []).map(hostLabel))].sort();
  const inputs = useMemo(
    () =>
      (report?.inputs || []).filter(
        (input) =>
          (host === "all" || hostLabel(input) === host) &&
          (kind === "all" || input.object.startsWith(kind)) &&
          (!onlySpareHosts || candidateHosts.has(hostLabel(input))) &&
          JSON.stringify(input).toLowerCase().includes(query.toLowerCase()),
      ),
    [report, host, kind, onlySpareHosts, query],
  );
  const groups = [...new Set(inputs.map(hostLabel))].sort();
  const relocationSources = (report?.inputs || []).filter(isBinaryOnUniversal);
  const disabled = busy || polling;
  const archiveInterfaceReady =
    !report ||
    (report.target.transport === "direct-mstp"
      ? interfaceConfig?.transport === "mstp" &&
        !!report.connector_config &&
        [
          "transport",
          "port",
          "mac",
          "instance",
          "baudrate",
          "max_master",
          "max_info_frames",
        ].every((key) => report.connector_config[key] === interfaceConfig[key])
      : interfaceConfig?.transport !== "mstp");
  const selectedArchive =
    archiveEvidence?.id === archiveId
      ? archiveEvidence
      : (status.archives || []).find((archive) => archive.id === archiveId);
  const selectedJob =
    (status.jobs || []).find((saved) => saved.id === jobId) ||
    (job?.id === jobId ? job : null);

  return (
    <section
      className="card hardware-survey"
      aria-label="Controller hardware and input survey"
    >
      <div className="card-header">
        <h3>
          <FileSearch size={17} /> Hardware and input survey
        </h3>
        <button onClick={() => void refresh()} disabled={busy}>
          <RefreshCw size={14} /> Refresh saved hardware records
        </button>
      </div>
      <div className="card-body">
        <p>
          Read a selected controller’s exposed analog and binary inputs,
          identify configured I/O modules from a native archive, and review
          spare terminals. Surveys read BACnet properties; archive imports and
          plans run locally.
        </p>
        <p className="help-text">
          Surveys and existing archive reads use the already-open BACnet/IP
          interface or an explicitly selected direct serial MS/TP link. Serial
          targets use a remote decimal MAC; no router or connection is opened
          automatically. Physical USB/RS-485 timing and BTCVT remain unverified.
        </p>
        {interfaceConfig?.transport === "mstp" && (
          <p aria-label="Hardware serial interface">
            Open serial interface: {interfaceConfig.port} ·{" "}
            {interfaceConfig.baudrate} baud · client MAC {interfaceConfig.mac} ·
            instance {interfaceConfig.instance} · max master{" "}
            {interfaceConfig.max_master} · max info frames{" "}
            {interfaceConfig.max_info_frames}
          </p>
        )}
        <div className="hardware-target form-grid">
          <label>
            Hardware transport
            <select
              aria-label="Hardware transport"
              value={transport}
              onChange={(e) =>
                edit(() => {
                  const next = e.target.value as "bacnet-ip" | "direct-mstp";
                  setTransport(next);
                  if (next === "direct-mstp") {
                    setRouter("");
                    setDnet("");
                  }
                })
              }
            >
              <option value="bacnet-ip">BACnet/IP or IP-routed MS/TP</option>
              <option value="direct-mstp">Direct serial MS/TP</option>
            </select>
          </label>
          <label>
            Hardware controller address
            <input
              value={address}
              onChange={(e) => edit(() => setAddress(e.target.value))}
            />
          </label>
          <label>
            Hardware Device object
            <input
              value={device}
              placeholder="device,1234"
              onChange={(e) => edit(() => setDevice(e.target.value))}
            />
          </label>
          <label>
            Hardware router (optional)
            <input
              value={router}
              disabled={transport === "direct-mstp"}
              onChange={(e) => edit(() => setRouter(e.target.value))}
            />
          </label>
          <label>
            Hardware destination network (optional)
            <input
              value={dnet}
              disabled={transport === "direct-mstp"}
              type="number"
              min={1}
              max={65534}
              onChange={(e) => edit(() => setDnet(e.target.value))}
            />
          </label>
        </div>
        <label className="hardware-checkbox">
          <input
            type="checkbox"
            checked={qualifyModel}
            onChange={(e) => edit(() => setQualifyModel(e.target.checked))}
          />
          Qualify this hardware read by exact model and protocol
        </label>
        {qualifyModel && (
          <ModelTransportPanel
            context={{
              connected,
              config: interfaceConfig ?? null,
              target: {
                transport,
                address: address.trim(),
                device: device.trim(),
                router: router.trim() || null,
                dnet: dnet.trim() ? Number(dnet) : null,
              },
            }}
            onAdmit={setQualification}
          />
        )}
        <details>
          <summary>Survey read limits</summary>
          <div className="form-grid hardware-limit-grid">
            <label>
              Hardware object limit
              <input
                type="number"
                min={1}
                max={4096}
                disabled={disabled}
                value={objectLimit}
                onChange={(e) => setObjectLimit(e.target.value)}
              />
            </label>
            <label>
              Hardware input limit
              <input
                type="number"
                min={1}
                max={1024}
                disabled={disabled}
                value={inputLimit}
                onChange={(e) => setInputLimit(e.target.value)}
              />
            </label>
            <label>
              Hardware deadline (seconds)
              <input
                type="number"
                min={1}
                max={180}
                disabled={disabled}
                value={deadline}
                onChange={(e) => setDeadline(e.target.value)}
              />
            </label>
          </div>
          <p className="help-text">
            Reads have a 1.5-second property deadline. Limits bound the survey;
            missing, hidden, and failed reads remain unknown.
          </p>
        </details>
        <div className="button-row">
          <button
            className="primary"
            disabled={
              !connected || disabled || (qualifyModel && !qualification)
            }
            onClick={survey}
          >
            <Search size={14} /> Survey controller inputs
          </button>
          <button disabled={!polling} onClick={cancel}>
            Cancel hardware survey
          </button>
        </div>
        {!connected && (
          <p className="help-text">
            Open a healthy BACnet/IP or direct serial MS/TP interface and select
            an exact Device object to run a survey. Saved reports and archive
            analysis remain available offline.
          </p>
        )}
        {job && (
          <div className="hardware-job" role="status">
            <strong>Survey {job.status}</strong> · {job.id}
            {job.target && (
              <p>{sourceLabel(job.target, job.connector_config)}</p>
            )}
            {job.progress != null && <pre>{text(job.progress)}</pre>}
            <ModelTransportJobEvidence job={job} />
            <button disabled={busy} onClick={refreshJobProgress}>
              Refresh hardware job progress
            </button>
          </div>
        )}
        <div className="hardware-saved-jobs">
          <label>
            Saved hardware job
            <select
              aria-label="Saved hardware job"
              value={jobId}
              disabled={disabled}
              onChange={(e) => setJobId(e.target.value)}
            >
              <option value="">Choose a running or finished job</option>
              {(status.jobs || []).map((saved) => (
                <option key={saved.id} value={saved.id}>
                  {saved.id} · {saved.status} ·{" "}
                  {sourceLabel(saved.target, saved.connector_config)}
                </option>
              ))}
            </select>
          </label>
          <div className="button-row">
            <button disabled={!jobId || disabled} onClick={loadJob}>
              View or resume hardware job
            </button>
            <button
              disabled={
                !jobId ||
                disabled ||
                !selectedJob ||
                !terminalStatuses.has(selectedJob.status)
              }
              onClick={exportJob}
            >
              <Download size={14} /> Download hardware job JSON
            </button>
            <button
              disabled={
                !jobId ||
                disabled ||
                !selectedJob ||
                !terminalStatuses.has(selectedJob.status)
              }
              onClick={() => void removeSaved("jobs", jobId)}
            >
              Remove finished hardware job
            </button>
          </div>
          <p className="help-text">
            Reopen a running job to follow progress and cancel it. Removing
            saved records affects local evidence only; exported files and
            controller settings are unchanged.
          </p>
        </div>
        <div className="hardware-saved-grid">
          <div>
            <h4>Saved survey</h4>
            <label>
              Saved hardware report
              <select
                aria-label="Saved hardware report"
                value={reportId}
                disabled={disabled}
                onChange={(e) => setReportId(e.target.value)}
              >
                <option value="">Choose a report</option>
                {(status.reports || []).map((saved) => (
                  <option key={saved.id} value={saved.id}>
                    {saved.identity?.name ||
                      saved.identity?.["object-name"] ||
                      saved.identity?.object_name ||
                      "Controller survey"}
                    {" · "}
                    {sourceLabel(saved.target, saved.connector_config)}
                    {" · "}
                    {saved.saved_at || saved.finished_at || "Time unavailable"}
                    {saved.imported === true ? " · Imported" : ""}
                    {" · "}
                    {saved.id}
                  </option>
                ))}
              </select>
            </label>
            <div className="button-row">
              <button disabled={!reportId || disabled} onClick={loadReport}>
                Open saved hardware report
              </button>
              <button
                disabled={!reportId || disabled}
                onClick={() => void removeSaved("reports", reportId)}
              >
                Remove saved hardware report
              </button>
              <label
                className={`hardware-file-button ${disabled ? "disabled" : ""}`}
              >
                <Upload size={14} /> Import survey JSON
                <input
                  type="file"
                  aria-label="Import hardware survey JSON"
                  accept=".json,application/json"
                  disabled={disabled}
                  onChange={(e) => {
                    void upload(e.target.files?.[0], false);
                    e.target.value = "";
                  }}
                />
              </label>
            </div>
          </div>
          <div>
            <h4>Native hardware archive</h4>
            <label
              className={`hardware-file-button ${disabled ? "disabled" : ""}`}
            >
              <Upload size={14} /> Read MOI or CAF archive
              <input
                type="file"
                aria-label="Import native hardware archive"
                accept=".moi,.caf,.zip,.bin"
                disabled={disabled}
                onChange={(e) => {
                  void upload(e.target.files?.[0], true);
                  e.target.value = "";
                }}
              />
            </label>
            <label>
              Saved BACnet file capture
              <select
                aria-label="Saved BACnet file capture"
                value={captureId}
                disabled={disabled}
                onChange={(e) => setCaptureId(e.target.value)}
              >
                <option value="">Choose an existing capture</option>
                {(status.captures || []).map((capture) => (
                  <option key={capture.id} value={capture.id}>
                    {capture.id} · {capture.bytes ?? "?"} bytes ·{" "}
                    {sourceLabel(capture.target)}
                  </option>
                ))}
              </select>
            </label>
            <button disabled={!captureId || disabled} onClick={useCapture}>
              Identify modules from saved capture
            </button>
          </div>
        </div>
        <div className="hardware-archive-choice">
          <label>
            Configured hardware archive
            <select
              aria-label="Configured hardware archive"
              value={archiveId}
              disabled={disabled}
              onChange={(e) => {
                setArchiveId(e.target.value);
                setPlan(null);
                setSensorPlan(null);
                setUseRelocation(false);
              }}
            >
              <option value="">Choose a parsed archive</option>
              {(status.archives || []).map((archive) => (
                <option key={archive.id} value={archive.id}>
                  {archive.source?.filename ||
                    archive.filename ||
                    archive.name ||
                    archive.id}{" "}
                  · {archive.id}
                </option>
              ))}
            </select>
          </label>
          <button disabled={!report || !archiveId || disabled} onClick={enrich}>
            Correlate archive with input survey
          </button>
        </div>
        {selectedArchive && (
          <details>
            <summary>Archive provenance and configured hardware</summary>
            <div className="button-row">
              <button
                disabled={disabled}
                onClick={() => void exportArchive("source")}
              >
                <Download size={14} /> Download original controller archive
              </button>
              <button
                disabled={disabled}
                onClick={() => void exportArchive("json")}
              >
                <Download size={14} /> Download archive evidence JSON
              </button>
              <button
                disabled={disabled}
                onClick={() => void removeSaved("archives", archiveId)}
              >
                Remove saved hardware archive
              </button>
            </div>
            {Array.isArray(selectedArchive.modules) && (
              <div className="hardware-table">
                <table>
                  <thead>
                    <tr>
                      <th scope="col">Configured host</th>
                      <th scope="col">Configured module model</th>
                      <th scope="col">Name</th>
                      <th scope="col">Input capacity</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selectedArchive.modules.map(
                      (module: RecordValue, index: number) => (
                        <tr key={index}>
                          <td>{hostLabel(module)}</td>
                          <td>
                            {text(module.configured_model || module.model)}
                          </td>
                          <td>{text(module.name)}</td>
                          <td>
                            {capacityLabel(module.capacity)}
                            <CapacityEvidence capacity={module.capacity} />
                          </td>
                        </tr>
                      ),
                    )}
                  </tbody>
                </table>
              </div>
            )}
            <p className="help-text">
              Configured hardware from this archive; installed labels, physical
              wiring, and whether this archive matches the running controller
              remain unverified.
            </p>
            <pre>{JSON.stringify(selectedArchive, null, 2)}</pre>
          </details>
        )}
        {error && (
          <p className="inline-error" role="alert">
            {error}
          </p>
        )}
        {outcome && <p role="status">{outcome}</p>}
        {report && (
          <section
            className="hardware-report"
            aria-label="Hardware survey results"
          >
            <div className="hardware-heading">
              <h4>
                {text(
                  report.identity?.name ||
                    report.identity?.["object-name"] ||
                    report.identity?.object_name ||
                    "Controller input survey",
                )}
              </h4>
              <div className="button-row">
                <button
                  disabled={disabled}
                  onClick={() => void exportReport("csv")}
                >
                  <Download size={14} /> Download hardware CSV
                </button>
                <button
                  disabled={disabled}
                  onClick={() => void exportReport("json")}
                >
                  <Download size={14} /> Download hardware JSON
                </button>
              </div>
            </div>
            <p className="hardware-source">
              <strong>Report source:</strong>{" "}
              {sourceLabel(report.target, report.connector_config)}
            </p>
            <p aria-label="Hardware report provenance">
              {report.imported === true
                ? "Imported report — user-supplied historical evidence. Its values have not been freshly verified against the controller."
                : "Captured survey readings — a saved snapshot. Values do not update live."}
            </p>
            <p className="help-text" aria-label="Hardware survey capture time">
              {report.started_at || report.finished_at ? (
                <>
                  Capture started:{" "}
                  <time dateTime={report.started_at}>
                    {text(report.started_at)}
                  </time>
                  {" · "}Capture finished:{" "}
                  <time dateTime={report.finished_at}>
                    {text(report.finished_at)}
                  </time>
                </>
              ) : (
                "Capture time unavailable."
              )}
            </p>
            <p className="help-text">
              Model:{" "}
              {text(report.identity?.model || report.identity?.["model-name"])}{" "}
              · Firmware:{" "}
              {text(
                report.identity?.firmware ||
                  report.identity?.["firmware-revision"],
              )}
            </p>
            <div className="hardware-controller-archive-read">
              <label>
                Controller archive File object (optional)
                <input
                  disabled={disabled}
                  placeholder="Detect advertised native archive"
                  value={archiveFileObject}
                  onChange={(e) => setArchiveFileObject(e.target.value)}
                />
              </label>
              <button
                disabled={!connected || disabled || !archiveInterfaceReady}
                onClick={readArchive}
              >
                Read controller archive
              </button>
              {!archiveInterfaceReady && (
                <p
                  className="help-text"
                  aria-label="Archive interface mismatch"
                >
                  Open the saved report's matching transport and exact serial
                  port, baud, station and master policy, or run a new survey on
                  the current interface.
                </p>
              )}
              <p className="help-text">
                Explicitly read the selected report’s advertised native archive
                and correlate its configured hardware. Source identity is
                verified again. An opaque BACnet file is not assumed to be a
                recoverable CAF; no backup session, download, or controller
                write is started.
              </p>
            </div>
            <p>
              {report.inventory?.complete
                ? "Complete exposed object inventory"
                : "Incomplete or unverified exposed object inventory"}{" "}
              · {report.inventory?.read ?? "?"} /{" "}
              {report.inventory?.total ?? "?"} objects · {report.inputs.length}{" "}
              observed input objects. Physical wiring and hidden program
              assignments remain unverified.
            </p>
            {report.scope && <p className="help-text">{report.scope}</p>}
            {!!report.inventory?.errors?.length && (
              <p className="inline-error">
                Inventory errors: {messages(report.inventory.errors)}
              </p>
            )}
            {!!report.errors?.length && (
              <p className="inline-error">
                Survey errors: {messages(report.errors)}
              </p>
            )}
            {!!report.warnings?.length && (
              <p className="help-text">{messages(report.warnings)}</p>
            )}
            <h4>Configured modules and capacity</h4>
            <p className="help-text">
              A configured model identifies the application’s intended hardware.
              Verify physical labels, wiring, archive freshness, and native
              point assignments before treating a terminal as available.
            </p>
            {(report.modules || []).length ? (
              <div className="hardware-table">
                <table>
                  <thead>
                    <tr>
                      <th scope="col">Host</th>
                      <th scope="col">Configured model</th>
                      <th scope="col">Name</th>
                      <th scope="col">Input capacity</th>
                      <th scope="col">Evidence / limitations</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(report.modules || []).map((module, index) => (
                      <tr key={`${module.sa_mac}-${index}`}>
                        <td>{hostLabel(module)}</td>
                        <td>{text(module.configured_model || module.model)}</td>
                        <td>{text(module.name)}</td>
                        <td>
                          {capacityLabel(
                            module.capacity || module.input_capacity,
                          )}
                          <CapacityEvidence
                            capacity={module.capacity || module.input_capacity}
                          />
                        </td>
                        <td>
                          {text(
                            module.model_evidence ||
                              module.evidence ||
                              module.source ||
                              module.warnings ||
                              "Physical hardware unverified",
                          )}
                          {!!module.unmapped_input_objects?.length && (
                            <p className="help-text">
                              Unmapped input assignments:{" "}
                              {module.unmapped_input_objects.join(", ")}. These
                              are retained as evidence; spare terminals remain
                              unverified.
                            </p>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p>
                Module models and capacities are unknown. Missing input objects
                do not establish spare terminals.
              </p>
            )}
            <div
              className="hardware-candidates"
              role="region"
              aria-label="Candidate spare input terminals"
            >
              <h4>Candidate spare input terminals</h4>
              {candidates.length ? (
                <div className="hardware-table">
                  <table>
                    <thead>
                      <tr>
                        <th scope="col">Host</th>
                        <th scope="col">Terminal</th>
                        <th scope="col">Input type</th>
                        <th scope="col">Candidate evidence</th>
                      </tr>
                    </thead>
                    <tbody>
                      {candidates.map((candidate, index) => (
                        <tr key={index}>
                          <td>{hostLabel(candidate)}</td>
                          <td>
                            {text(
                              candidate.terminal ||
                                (candidate.slot != null
                                  ? `IN${candidate.slot}`
                                  : undefined),
                            )}
                          </td>
                          <td>
                            {text(
                              candidate.terminal_type ||
                                candidate.kind ||
                                candidate.input_type ||
                                candidate.type,
                            )}
                            {candidate.voltage_capable === true
                              ? " · voltage capable"
                              : candidate.voltage_capable === false
                                ? " · not a voltage input"
                                : ""}
                          </td>
                          <td>
                            {text(candidate.status)} ·{" "}
                            {text(
                              candidate.reason ||
                                candidate.evidence ||
                                candidate.warnings ||
                                "No assignment observed; verify native program and wiring",
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p>
                  No spare terminals established by this report. Unknown
                  capacity or incomplete evidence is not proof that every
                  terminal is occupied.
                </p>
              )}
            </div>
            <div className="hardware-filter-grid">
              <label>
                Search hardware inputs
                <input
                  type="search"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Name, description, terminal, object, error…"
                />
              </label>
              <label>
                Hardware input host
                <select
                  aria-label="Hardware input host"
                  value={host}
                  onChange={(e) => setHost(e.target.value)}
                >
                  <option value="all">All hosts</option>
                  {hosts.map((name) => (
                    <option key={name}>{name}</option>
                  ))}
                </select>
              </label>
              <label>
                Hardware input object type
                <select
                  aria-label="Hardware input object type"
                  value={kind}
                  onChange={(e) => setKind(e.target.value)}
                >
                  <option value="all">Analog and binary inputs</option>
                  <option value="analog-input,">Analog inputs</option>
                  <option value="binary-input,">Binary inputs</option>
                </select>
              </label>
              <label className="hardware-checkbox">
                <input
                  type="checkbox"
                  checked={onlySpareHosts}
                  onChange={(e) => setOnlySpareHosts(e.target.checked)}
                />{" "}
                Hosts with candidate spare inputs
              </label>
            </div>
            <p className="help-text">
              Binary objects can occupy universal input terminals. Their
              terminals count as occupied even when no analog-input object
              exists.
            </p>
            {groups.map((group) => (
              <section
                className="hardware-input-group"
                key={group}
                aria-label={`${group} input assignments`}
              >
                <h4>{group}</h4>
                <div className="hardware-table">
                  <table>
                    <thead>
                      <tr>
                        <th scope="col">Terminal / object</th>
                        <th scope="col">Point / description</th>
                        <th scope="col">Value / units</th>
                        <th scope="col">Quality</th>
                        <th scope="col">Binding evidence / errors</th>
                      </tr>
                    </thead>
                    <tbody>
                      {inputs
                        .filter((input) => hostLabel(input) === group)
                        .map((input) => (
                          <tr key={input.object}>
                            <td>
                              <strong>{text(input.device_type)}</strong>
                              <br />
                              <code>{input.object}</code>
                              <br />
                              Slot {text(input.slot)} · SA {text(input.sa_mac)}
                            </td>
                            <td>
                              <strong>{text(input.name)}</strong>
                              <br />
                              {text(input.description)}
                              {isBinaryOnUniversal(input) && (
                                <p className="hardware-ui-binary">
                                  Binary object occupying a universal input
                                </p>
                              )}
                            </td>
                            <td>
                              {text(input.present_value)}
                              <br />
                              <span className="help-text">
                                Units: {text(input.units)}
                              </span>
                            </td>
                            <td>
                              Reliability: {text(input.reliability)}
                              <br />
                              Flags: {text(input.status_flags)}
                              <br />
                              Out of service: {text(input.out_of_service)}
                            </td>
                            <td>
                              Setup (raw): {text(input.setup_raw)}
                              {input.properties && (
                                <details>
                                  <summary>Raw binding properties</summary>
                                  <pre>
                                    {JSON.stringify(
                                      {
                                        host: input.host,
                                        properties: input.properties,
                                      },
                                      null,
                                      2,
                                    )}
                                  </pre>
                                </details>
                              )}
                              {input.errors?.length ? (
                                <p className="inline-error">
                                  {messages(input.errors)}
                                </p>
                              ) : (
                                <p className="help-text">
                                  No reported property errors
                                </p>
                              )}
                            </td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
              </section>
            ))}
            {!inputs.length && <p>No observed inputs match the filters.</p>}
            <details className="hardware-relocation">
              <summary>
                Review moving a binary signal off a universal input
              </summary>
              <p>
                Choose an existing binary object bound to a universal input and
                a candidate dedicated binary terminal. The review checks known
                assignments and capacity. Confirm dry-contact compatibility,
                alarm polarity, delays, logic references, and physical wiring
                separately.
              </p>
              <div className="form-grid">
                <label>
                  Binary signal to relocate
                  <select
                    aria-label="Binary signal to relocate"
                    value={sourceObject}
                    disabled={disabled}
                    onChange={(e) => {
                      setSourceObject(e.target.value);
                      setPlan(null);
                      setSensorPlan(null);
                      setUseRelocation(false);
                    }}
                  >
                    <option value="">
                      Choose a binary object on a universal input
                    </option>
                    {relocationSources.map((input) => (
                      <option key={input.object} value={input.object}>
                        {input.name || input.object} · {hostLabel(input)} ·{" "}
                        {input.device_type}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Destination SA address (empty for base)
                  <input
                    value={destinationSa}
                    disabled={disabled}
                    type="number"
                    min={4}
                    max={127}
                    onChange={(e) => {
                      setDestinationSa(e.target.value);
                      setPlan(null);
                      setSensorPlan(null);
                      setUseRelocation(false);
                    }}
                  />
                </label>
                <label>
                  Destination binary input slot
                  <input
                    value={destinationSlot}
                    disabled={disabled}
                    type="number"
                    min={1}
                    max={64}
                    onChange={(e) => {
                      setDestinationSlot(e.target.value);
                      setPlan(null);
                      setSensorPlan(null);
                      setUseRelocation(false);
                    }}
                  />
                </label>
              </div>
              <button
                disabled={!sourceObject || !destinationSlot || disabled}
                onClick={relocate}
              >
                Review input relocation
              </button>
              {!relocationSources.length && (
                <p>
                  No binary objects with a verified universal-input terminal
                  label were found.
                </p>
              )}
              {plan && (
                <div
                  className="hardware-plan"
                  role="region"
                  aria-label="Input relocation review"
                >
                  <strong>Review only — no controller changes applied</strong>
                  <pre>{JSON.stringify(plan, null, 2)}</pre>
                  <button
                    disabled={disabled}
                    onClick={() =>
                      saveBlob(
                        new Blob([JSON.stringify(plan, null, 2)], {
                          type: "application/json",
                        }),
                        `input-relocation-${report.id}.json`,
                      )
                    }
                  >
                    <Download size={14} /> Download relocation review JSON
                  </button>
                </div>
              )}
              <p className="help-text">
                Native JCI application compilation and download are unsupported
                here. Applying this relocation requires supported vendor
                engineering software and physical rewiring. This interface does
                not claim a native controller update.
              </p>
            </details>
            <details className="hardware-sensor-plan">
              <summary>
                Plan voltage sensor input assignments and scaling
              </summary>
              <p>
                This offline plan assigns two active voltage channels to
                candidate universal inputs. Choose sensor output jumpers and
                engineering ranges to match these values. No input mode, point,
                logic, or running controller is changed.
              </p>
              <p className="help-text">
                For a Belimo 22UTH-510X, AOU1 provides humidity when RH is
                selected; AOU2 provides temperature. Verify the sensor’s
                installed revision, selector settings, supply, signal common,
                and both modules’ voltage-input settings.
              </p>
              {channels.map((channel, index) => (
                <fieldset key={index}>
                  <legend>{channel.name}</legend>
                  <div className="form-grid">
                    {(
                      [
                        ["sa", "SA address (empty for base)"],
                        ["slot", "Universal input slot"],
                        ["engineeringLow", "Engineering minimum"],
                        ["engineeringHigh", "Engineering maximum"],
                        ["units", "Engineering units"],
                      ] as const
                    ).map(([key, label]) => (
                      <label key={key}>
                        {channel.name} — {label}
                        <input
                          disabled={disabled}
                          type={key === "units" ? "text" : "number"}
                          value={channel[key]}
                          onChange={(e) => {
                            setChannels((previous) =>
                              previous.map((item, itemIndex) =>
                                itemIndex === index
                                  ? { ...item, [key]: e.target.value }
                                  : item,
                              ),
                            );
                            setSensorPlan(null);
                          }}
                        />
                      </label>
                    ))}
                    <label>
                      {channel.name} — Signal range
                      <select
                        aria-label={`${channel.name} — Signal range`}
                        disabled={disabled}
                        value={channel.signalHigh}
                        onChange={(e) => {
                          setChannels((previous) =>
                            previous.map((item, itemIndex) =>
                              itemIndex === index
                                ? { ...item, signalHigh: e.target.value }
                                : item,
                            ),
                          );
                          setSensorPlan(null);
                        }}
                      >
                        <option value="5">0–5 V</option>
                        <option value="10">0–10 V</option>
                      </select>
                    </label>
                  </div>
                  <p className="help-text">
                    Preview: 0 V = {channel.engineeringLow} {channel.units};{" "}
                    {Number(channel.signalHigh) / 2} V ={" "}
                    {(Number(channel.engineeringLow) +
                      Number(channel.engineeringHigh)) /
                      2}{" "}
                    {channel.units}; {channel.signalHigh} V ={" "}
                    {channel.engineeringHigh} {channel.units}. Confirm the
                    sensor range; these are editable planning values.
                  </p>
                </fieldset>
              ))}
              <label className="hardware-checkbox">
                <input
                  type="checkbox"
                  disabled={disabled || plan?.status !== "review-required"}
                  checked={useRelocation}
                  onChange={(e) => {
                    setUseRelocation(e.target.checked);
                    setSensorPlan(null);
                  }}
                />{" "}
                Include the reviewed binary relocation as a condition for
                freeing its universal input
              </label>
              <button disabled={disabled} onClick={reviewSensors}>
                Review voltage sensor assignments
              </button>
              {sensorPlan && (
                <div
                  className="hardware-plan"
                  role="region"
                  aria-label="Voltage sensor assignment review"
                >
                  <strong>
                    Offline sensor plan — native apply unavailable
                  </strong>
                  <pre>{JSON.stringify(sensorPlan, null, 2)}</pre>
                  <button
                    disabled={disabled}
                    onClick={() =>
                      saveBlob(
                        new Blob([JSON.stringify(sensorPlan, null, 2)], {
                          type: "application/json",
                        }),
                        `sensor-input-plan-${report.id}.json`,
                      )
                    }
                  >
                    <Download size={14} /> Download sensor input plan JSON
                  </button>
                </div>
              )}
            </details>
          </section>
        )}
        <PhysicalCapacityPanel
          survey={
            report?.content_sha256
              ? {
                  id: report.id,
                  content_sha256: report.content_sha256,
                  models: [
                    ...(typeof report.identity?.model === "string"
                      ? [
                          {
                            host: "base" as const,
                            model: report.identity.model,
                          },
                        ]
                      : []),
                    ...(report.modules || [])
                      .filter(
                        (module) =>
                          module.host === "sa" &&
                          Number.isInteger(module.sa_mac) &&
                          typeof module.configured_model === "string",
                      )
                      .map((module) => ({
                        host: "sa" as const,
                        sa_mac: module.sa_mac,
                        model: module.configured_model,
                      })),
                  ],
                }
              : null
          }
        />
        <details className="hardware-supply-planner">
          <summary>Sensor power supply budget</summary>
          <SensorSupplyPanel
            reference={
              report?.content_sha256
                ? { id: report.id, content_sha256: report.content_sha256 }
                : null
            }
          />
        </details>
      </div>
    </section>
  );
}
