import { apiJsonDocument, type JsonDocument } from "./api";

type Profile = "trend-log" | "trend-log-multiple" | "event-log";
const profiles = {
  "trend-log": ["bacnet-trend-log-history/1", "device-history"],
  "trend-log-multiple": [
    "bacnet-trend-log-multiple-history/1",
    "device-history-trend-log-multiple",
  ],
  "event-log": ["bacnet-event-log-history/1", "device-history-event-log"],
};

/** The parsed display and downloadable bytes always come from one response. */
export async function historyEvidence<T = any>(
  path: string,
  profile: Profile,
  body?: Record<string, unknown>,
  captureId?: string,
): Promise<JsonDocument<T>> {
  const document = await apiJsonDocument<T>(path, body);
  const report = document.data as any;
  const [expectedProfile, sourceKind] = profiles[profile];
  if (
    !report ||
    typeof report !== "object" ||
    !/^[a-f0-9]{32}$/.test(report.id) ||
    (captureId !== undefined && report.id !== captureId) ||
    report.profile !== expectedProfile ||
    report.source_kind !== sourceKind ||
    !report.target ||
    typeof report.target.address !== "string" ||
    typeof report.target.object_id !== "string" ||
    !report.request ||
    typeof report.request !== "object" ||
    !Array.isArray(report.records) ||
    report.records.length > 1000 ||
    (profile !== "trend-log" && !/^[a-f0-9]{64}$/.test(report.evidence_sha256))
  )
    throw new Error(
      "History response does not identify the requested report or capture.",
    );
  // Single Trend Log preserves the submitted address verbatim. The other
  // profiles normalize addresses and retain a unique read operation identity.
  // Object aliases are normalized by the server; the request and target must
  // still identify the same object without guessing native parsing in JS.
  if (
    report.request.object_id !== report.target.object_id ||
    (profile === "trend-log" &&
      body?.address !== undefined &&
      (report.request.address !== body.address ||
        report.target.address !== body.address)) ||
    (body?.operation_id !== undefined &&
      report.request.operation_id !== body.operation_id)
  )
    throw new Error(
      "History response source differs from the submitted request.",
    );
  return document;
}

export function historyVisible(panel: HTMLElement | null) {
  return Boolean(
    panel?.isConnected &&
      panel.getClientRects().length &&
      !panel.closest("details:not([open])"),
  );
}
