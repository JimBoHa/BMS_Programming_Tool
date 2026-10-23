export const MODEL_TRANSPORT_PROFILE = "studio-jci-model-target-transport/1";
// This source-qualified profile is separate from the unchanged survey profile.
export const MODEL_TRANSPORT_SHA =
  "f6f5cb6730c89bd0d2b9cba6227e55b4bd095a16951eb5a7d0c56b373412b4bb";
export type Qualification = {
  profile_sha256: string;
  model: string;
  current_protocol: string;
};
export type ModelTarget = {
  transport: string;
  address: string;
  device: string;
  router: string | null;
  dnet: number | null;
};
export type ModelContext = {
  connected: boolean;
  config: Record<string, unknown> | null;
  target: ModelTarget;
};
export type ModelCatalog = { profile: any; profile_sha256: string };
export const documentedModel = (catalog: ModelCatalog | null, model: string) =>
  catalog && Object.hasOwn(catalog.profile.models, model)
    ? catalog.profile.models[model]
    : null;
const record = (v: any) =>
  v !== null && typeof v === "object" && !Array.isArray(v);
export function canonical(value: any): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (record(value))
    return `{${Object.keys(value)
      .sort()
      .map((k) => `${JSON.stringify(k)}:${canonical(value[k])}`)
      .join(",")}}`;
  if (typeof value === "number" && !Number.isSafeInteger(value))
    throw new Error("Unsupported model metadata number.");
  return JSON.stringify(value);
}
export const equal = (a: any, b: any) => canonical(a) === canonical(b);
async function sha(value: any) {
  return Array.from(
    new Uint8Array(
      await crypto.subtle.digest(
        "SHA-256",
        new TextEncoder().encode(canonical(value)),
      ),
    ),
  )
    .map((v) => v.toString(16).padStart(2, "0"))
    .join("");
}
export async function checkCatalog(value: any): Promise<ModelCatalog> {
  if (
    !record(value) ||
    value.format !== "bms.jci-model-target-transport-catalog/1" ||
    value.profile_sha256 !== MODEL_TRANSPORT_SHA ||
    value.profile?.profile !== MODEL_TRANSPORT_PROFILE ||
    value.controller_writes !== false ||
    (await sha(value.profile)) !== MODEL_TRANSPORT_SHA
  )
    throw new Error(
      "Unsupported or altered model transport profile. Refresh a supported source profile.",
    );
  return value;
}
function ipv4(value: string) {
  const m =
    /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?::([0-9]{1,5}))?$/.exec(
      value,
    );
  if (
    !m ||
    m.slice(1, 5).some((n) => Number(n) > 255 || String(Number(n)) !== n)
  )
    throw new Error("Use an explicit IPv4 endpoint for model review.");
  const port = m[5] === undefined ? 47808 : Number(m[5]);
  if (port < 1 || port > 65535)
    throw new Error("Use a valid explicit IPv4 port.");
  return `${m.slice(1, 5).join(".")}${port === 47808 ? "" : `:${port}`}`;
}
/** Normalize only documented existing literal forms; generic survey inputs are unchanged. */
export function normalizedTarget(t: ModelTarget): ModelTarget {
  const dev = /^device,([0-9]{1,7})$/.exec(t.device.trim());
  if (!dev || Number(dev[1]) > 4194302)
    throw new Error("Enter an exact Device object for model review.");
  const device = `device,${Number(dev[1])}`;
  if (t.transport === "direct-mstp") {
    if (
      t.router !== null ||
      t.dnet !== null ||
      !/^(?:0|[1-9][0-9]{0,2})$/.test(t.address) ||
      Number(t.address) > 254
    )
      throw new Error(
        "Use a direct remote decimal MS/TP MAC without router fields.",
      );
    return { ...t, device };
  }
  if (t.transport !== "bacnet-ip")
    throw new Error("Unsupported selected target transport.");
  if (t.router === null && t.dnet === null)
    return { ...t, device, address: ipv4(t.address.trim()) };
  if (!t.router || !Number.isInteger(t.dnet) || t.dnet! < 1 || t.dnet! > 65534)
    throw new Error("Supply both an explicit router and destination network.");
  const m = /^(\d+):(0x[0-9a-fA-F]{2,16}|\d{1,3})$/.exec(t.address.trim());
  if (!m || Number(m[1]) !== t.dnet)
    throw new Error(
      "Use a DNET:MAC matching the explicit destination network.",
    );
  let mac = m[2];
  if (mac.startsWith("0x")) {
    if (mac.length % 2) throw new Error("Use whole remote MAC octets.");
    mac = mac.toLowerCase();
    if (mac.length === 4) mac = String(parseInt(mac.slice(2), 16));
    else if (mac.length === 14) {
      const port = parseInt(mac.slice(-4), 16);
      if (port >= 47808 && port <= 47810)
        mac = `${[2, 4, 6, 8].map((i) => parseInt(mac.slice(i, i + 2), 16)).join(".")}${port === 47808 ? "" : `:${port}`}`;
    }
  } else if (Number(mac) > 254) throw new Error("Select a unicast remote MAC.");
  else mac = String(Number(mac));
  if (mac === "255") throw new Error("Select a unicast remote MAC.");
  return {
    ...t,
    device,
    address: `${t.dnet}:${mac}`,
    router: ipv4(t.router.trim()),
  };
}
export function checkReview(
  value: any,
  catalog: ModelCatalog,
  q: Qualification,
  context: ModelContext,
) {
  const target = normalizedTarget(context.target),
    model = documentedModel(catalog, q.model);
  const path =
    target.transport === "direct-mstp"
      ? "direct-mstp"
      : target.router
        ? "routed-explicit"
        : "direct-ipv4";
  if (
    !record(value) ||
    value.format !== "bms.jci-model-target-transport-review/1" ||
    value.profile !== MODEL_TRANSPORT_PROFILE ||
    value.profile_sha256 !== MODEL_TRANSPORT_SHA ||
    !equal(value.source, catalog.profile.source) ||
    !equal(value.declaration, q) ||
    !equal(value.target, target) ||
    !equal(value.interface, {
      connected: context.connected,
      config: context.config,
    }) ||
    value.path !== path ||
    !equal(value.documented_model, model) ||
    !equal(value.documented_protocols, model?.native_protocols ?? []) ||
    value.adapter_implemented !==
      (catalog.profile.adapters[q.current_protocol] ?? false) ||
    value.native_compatibility_verified !== false ||
    value.controller_writes !== false ||
    !Array.isArray(value.findings) ||
    value.findings.length > 32 ||
    !value.findings.every(
      (f: any) =>
        record(f) &&
        typeof f.code === "string" &&
        /^[a-z_]{1,80}$/.test(f.code) &&
        typeof f.message === "string" &&
        f.message.length <= 2000,
    ) ||
    typeof value.dispatch_admitted !== "boolean" ||
    value.dispatch_admitted !== (value.findings.length === 0)
  )
    throw new Error(
      "Model review does not match the current declaration, target, interface or supported profile.",
    );
  const allowed =
    context.connected &&
    context.config !== null &&
    !!model &&
    model.native_protocols.includes(q.current_protocol) &&
    catalog.profile.adapters[q.current_protocol] === true &&
    (context.config.transport === "mstp") === (path === "direct-mstp") &&
    (q.current_protocol === "bacnet-ip"
      ? path === "direct-ipv4"
      : q.current_protocol === "bacnet-mstp" &&
        (path === "direct-mstp"
          ? Number(target.address) !== context.config.mac
          : path === "routed-explicit" &&
            /^\d+:\d{1,3}$/.test(target.address)));
  if (value.dispatch_admitted && !allowed)
    throw new Error(
      "Model review incorrectly admits an unsupported or unresolved path.",
    );
  return value;
}
