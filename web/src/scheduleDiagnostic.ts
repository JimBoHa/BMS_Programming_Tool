import { sha256Digest } from "./browserCrypto";
import type { JsonDocument } from "./api";

export type ScheduleTraceFocus = {
  object_id: string;
  property: string;
  array_index: number | null;
};
const profile = "studio-readproperty-phase-trace/1";
function object(value: string) {
  const match = /^(device|calendar|schedule|8|6|17)[,:](\d+)$/.exec(value);
  if (!match) return value;
  return `${({ "8": "device", "6": "calendar", "17": "schedule" } as Record<string, string>)[match[1]] || match[1]},${Number(match[2])}`;
}
function endpoint(value: string | null) {
  return value && !value.includes(":") ? value + ":47808" : value;
}
async function sha256(text: string) {
  return Array.from(
    new Uint8Array(await sha256Digest(new TextEncoder().encode(text))),
    (byte) => byte.toString(16).padStart(2, "0"),
  ).join("");
}
export async function scheduleDiagnostic(
  document: JsonDocument,
  request: {
    operation_id: string;
    address: string;
    device: string;
    router: string | null;
    dnet: number | null;
  },
  focus: ScheduleTraceFocus,
  includeUdpIngress = false,
) {
  const value = document.data;
  let core: any,
    blob: Blob,
    trace: any = null,
    envelope: Blob | null = null;
  if (value?.format === "bms.native-read-diagnostic-envelope/1") {
    if (
      document.blob.size > 4 * 1024 * 1024 + 65536 + 4096 ||
      typeof value.core_report_json !== "string" ||
      !/^[a-f0-9]{64}$/.test(value.core_report_sha256 || "") ||
      value.trace_profile !== profile ||
      value.trace?.profile !== profile ||
      !["complete", "truncated", "unavailable"].includes(value.trace.state) ||
      !Array.isArray(value.trace.events) ||
      value.trace.events.length > 256 ||
      new TextEncoder().encode(JSON.stringify(value.trace)).length > 65536 ||
      !value.trace_focus ||
      value.trace_focus.object_id !== object(focus.object_id) ||
      value.trace_focus.property !== focus.property ||
      value.trace_focus.array_index !== focus.array_index ||
      value.include_udp_ingress !== includeUdpIngress ||
      (value.trace.state !== "unavailable" &&
        value.trace.udp_ingress_requested !== includeUdpIngress) ||
      (await sha256(value.core_report_json)) !== value.core_report_sha256
    )
      throw new Error(
        "Schedule diagnostic envelope, focus or exact core-response hash is invalid.",
      );
    core = JSON.parse(value.core_report_json);
    if (core.id !== value.core_report_id)
      throw new Error("Schedule diagnostics refer to another core report.");
    blob = new Blob([value.core_report_json], { type: "application/json" });
    trace = value.trace;
    envelope = document.blob;
  } else {
    if (document.headers?.get("X-Studio-Diagnostics") !== "unavailable")
      throw new Error(
        "Schedule diagnostic fallback lacks its explicit server state.",
      );
    core = value;
    blob = document.blob;
  }
  if (
    core?.profile !== "native-calendar-schedule-inventory/1" ||
    core.operation_id !== request.operation_id ||
    !/^[a-f0-9]{32}$/.test(core.id || "") ||
    !/^[a-f0-9]{64}$/.test(core.evidence_sha256 || "") ||
    !core.target ||
    core.target.device !== object(request.device) ||
    core.target.dnet !== request.dnet ||
    endpoint(core.target.router) !== endpoint(request.router) ||
    (request.router
      ? core.target.address !== request.address
      : endpoint(core.target.address) !== endpoint(request.address)) ||
    !Array.isArray(core.objects) ||
    core.objects.length > 16
  )
    throw new Error("Schedule diagnostic core does not match this inspection.");
  return {
    report: core,
    envelope,
    core: blob,
    trace,
    focus,
    includeUdpIngress,
  };
}
