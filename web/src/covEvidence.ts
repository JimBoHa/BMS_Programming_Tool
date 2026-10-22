/** Original GET response bytes, separate from the parsed display projection. */
async function document(path: string) {
  const response = await fetch("/api" + path);
  if (!response.ok) {
    let message = response.statusText;
    try {
      const value = await response.json();
      message =
        typeof value.detail === "string"
          ? value.detail
          : JSON.stringify(value.detail);
    } catch {
      /* Retain the HTTP failure when its body is not JSON. */
    }
    throw new Error(message);
  }
  const blob = await response.blob();
  return { data: JSON.parse(await blob.text()), blob };
}
export type CovDocument = { data: any; blob: Blob };
const integer = (value: any) => Number.isSafeInteger(value) && value >= 0;
function stable(value: any): any {
  if (Array.isArray(value)) return value.map(stable);
  if (value && typeof value === "object")
    return Object.fromEntries(
      Object.keys(value)
        .sort()
        .map((key) => [key, stable(value[key])]),
    );
  return value;
}
export function covRecordingKey(recording: any) {
  const meta = recording?.metadata;
  if (
    !meta?.config ||
    typeof meta.source_store_id !== "string" ||
    meta.acquisition_kind !== "bacnet-cov" ||
    meta.clock_basis !== "receipt"
  )
    return null;
  return JSON.stringify(
    stable([
      recording.monitor,
      recording.source,
      meta.monitor_id,
      meta.source_store_id,
      meta.process_id,
      meta.config,
      meta.connector_config,
    ]),
  );
}
export function covJobKey(job: any) {
  return job?.config
    ? JSON.stringify(
        stable([job.id, job.process_id, job.config, job.connector_config]),
      )
    : null;
}
export async function covPage(
  monitor: string,
  after: number,
  limit: number,
  expectedKey: string | null,
): Promise<CovDocument> {
  const result = await document(
    `/bacnet/cov/recordings/${encodeURIComponent(monitor)}/page?after=${after}&limit=${limit}`,
  );
  const { recording, page, events, retention } = result.data ?? {};
  const key = covRecordingKey(recording);
  if (
    result.data?.format !== "bms.cov-saved-page" ||
    result.data.version !== 1 ||
    recording?.monitor !== monitor ||
    recording?.source !== "cov/" + monitor ||
    recording?.metadata?.monitor_id !== monitor ||
    !key ||
    key !== expectedKey ||
    page?.after !== after ||
    page?.limit !== limit ||
    !Array.isArray(events) ||
    page.count !== events.length ||
    events.length > limit ||
    !integer(retention?.events_retained) ||
    retention.events_retained < events.length ||
    retention.events_retained !== recording.events_retained ||
    (retention.events_retained === 0
      ? retention.first_retained_sequence !== null ||
        retention.last_retained_sequence !== null
      : !integer(retention.first_retained_sequence) ||
        !integer(retention.last_retained_sequence) ||
        retention.first_retained_sequence > retention.last_retained_sequence) ||
    retention.cursor_before_first_retained !==
      (retention.first_retained_sequence !== null &&
        after < retention.first_retained_sequence) ||
    !integer(retention.events_evicted) ||
    retention.events_evicted !== recording.events_evicted ||
    typeof result.data.snapshot_at !== "string"
  )
    throw new Error(
      "Saved COV page identity, source or requested cursor does not match.",
    );
  let previous = after;
  for (const event of events) {
    if (
      !integer(event.sequence) ||
      event.sequence <= previous ||
      event.source !== recording.source ||
      event.acquisition_kind !== "bacnet-cov" ||
      event.clock_basis !== "receipt" ||
      event.source_clock !== null ||
      !event.evidence ||
      typeof event.evidence !== "object"
    )
      throw new Error(
        "Saved COV receipt source or sequence does not match this page.",
      );
    previous = event.sequence;
  }
  if (
    page.first_sequence !== (events[0]?.sequence ?? null) ||
    page.last_sequence !== (events.at(-1)?.sequence ?? null) ||
    (events.length &&
      (!integer(retention.first_retained_sequence) ||
        !integer(retention.last_retained_sequence) ||
        retention.first_retained_sequence > events[0].sequence ||
        retention.last_retained_sequence < previous))
  )
    throw new Error(
      "Saved COV page boundaries do not match the returned receipts.",
    );
  return result;
}
export async function covJob(
  id: string,
  expectedKey: string | null,
): Promise<CovDocument> {
  const result = await document(`/bacnet/cov/jobs/${encodeURIComponent(id)}`);
  const job = result.data;
  if (
    job?.id !== id ||
    !expectedKey ||
    covJobKey(job) !== expectedKey ||
    !Array.isArray(job.events) ||
    job.events.length > 100 ||
    job.events_retained !== job.events.length ||
    !integer(job.received) ||
    job.received < job.events.length
  )
    throw new Error("COV job identity or original source does not match.");
  let previous = 0;
  for (const event of job.events) {
    if (
      event.device !== job.config.device ||
      event.object !== job.config.object_id ||
      event.process_id !== job.process_id ||
      event.confirmed !== job.config.confirmed ||
      !integer(event.sequence) ||
      event.sequence <= previous ||
      event.sequence > job.received ||
      event.route?.router !== job.config.router ||
      event.route?.dnet !== job.config.dnet ||
      (job.config.router
        ? event.route.source !== job.config.address
        : event.source !== job.config.address)
    )
      throw new Error("COV receipt source differs from the selected job.");
    previous = event.sequence;
  }
  return result;
}
export function covVisible(panel: HTMLElement | null) {
  return Boolean(
    panel?.isConnected &&
      panel.getClientRects().length &&
      !panel.closest("details:not([open])"),
  );
}
