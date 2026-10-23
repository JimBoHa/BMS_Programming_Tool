export type PowerLease = {
  id: string;
  operation: "temco-native-apply";
  provider: string;
  seconds: number;
  created_at: string;
  expires_at: string;
  finished_at: string | null;
  state: string;
  request_active: boolean;
  cleanup_confirmed: boolean;
  error: string | null;
};
export type PowerStatus = {
  profile: Record<string, any>;
  profile_sha256: string;
  provider: string;
  provider_available: boolean;
  accepting: boolean;
  active: PowerLease[];
  recent: PowerLease[];
  native_jci_transfer: false;
};
const PROFILE_SHA =
  "39f2f931b40402dc1e50240a5d5b1a23e85f860ce9ef3eb44bd1fa59ced88058";
const object = (value: any): value is Record<string, any> =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const exact = (value: Record<string, any>, keys: string[]) =>
  Object.keys(value).length === keys.length &&
  keys.every((key) => Object.hasOwn(value, key));
const text = (value: any, maximum: number) =>
  typeof value === "string" && value.length > 0 && value.length <= maximum;
const utc = (value: any) =>
  text(value, 40) &&
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(
    value,
  ) &&
  Number.isFinite(Date.parse(value));
const states = [
  "starting",
  "active",
  "releasing",
  "released",
  "expired",
  "failed",
  "cleanup_failed",
  "unavailable",
];
const rowKeys = [
  "id",
  "operation",
  "provider",
  "seconds",
  "created_at",
  "expires_at",
  "finished_at",
  "state",
  "request_active",
  "cleanup_confirmed",
  "error",
];
export async function powerBlobSha256(blob: Blob) {
  return Array.from(
    new Uint8Array(
      await crypto.subtle.digest("SHA-256", await blob.arrayBuffer()),
    ),
    (n) => n.toString(16).padStart(2, "0"),
  ).join("");
}
// This bounded profile contains ordinary configuration DTOs, never Program/source atoms.
function sorted(value: any): any {
  return Array.isArray(value)
    ? value.map(sorted)
    : object(value)
      ? Object.fromEntries(
          Object.keys(value)
            .sort()
            .map((key) => [key, sorted(value[key])]),
        )
      : value;
}
export async function checkPowerStatus(
  value: any,
  blob: Blob,
): Promise<PowerStatus> {
  if (
    blob.size > 256 * 1024 ||
    !object(value) ||
    !exact(value, [
      "profile",
      "profile_sha256",
      "provider",
      "provider_available",
      "accepting",
      "active",
      "recent",
      "native_jci_transfer",
    ]) ||
    !object(value.profile) ||
    value.profile.profile !== "studio-operation-idle-awake/1" ||
    value.profile_sha256 !== PROFILE_SHA ||
    value.profile.advisory !== true ||
    value.profile.idle_only !== true ||
    value.profile.maximum_seconds !== 1800 ||
    value.profile.temco_apply_seconds !== 900 ||
    value.profile.active_limit !== 8 ||
    value.profile.recent_limit !== 32 ||
    !text(value.provider, 128) ||
    typeof value.provider_available !== "boolean" ||
    typeof value.accepting !== "boolean" ||
    value.native_jci_transfer !== false ||
    !Array.isArray(value.active) ||
    value.active.length > 8 ||
    !Array.isArray(value.recent) ||
    value.recent.length > 32
  )
    throw new Error(
      "Power status is malformed or uses an unsupported advisory profile.",
    );
  if (
    (await powerBlobSha256(
      new Blob([JSON.stringify(sorted(value.profile))]),
    )) !== PROFILE_SHA
  )
    throw new Error(
      "Power status profile content does not match its supported rules hash.",
    );
  const ids = new Set<string>();
  for (const [group, rows] of [
    ["active", value.active],
    ["recent", value.recent],
  ] as const) {
    for (const row of rows) {
      if (
        !object(row) ||
        !exact(row, rowKeys) ||
        typeof row.id !== "string" ||
        !/^[a-f0-9]{32}$/.test(row.id) ||
        ids.has(row.id) ||
        row.operation !== "temco-native-apply" ||
        !text(row.provider, 128) ||
        !Number.isSafeInteger(row.seconds) ||
        row.seconds < 1 ||
        row.seconds > 1800 ||
        !utc(row.created_at) ||
        !utc(row.expires_at) ||
        !(row.finished_at === null || utc(row.finished_at)) ||
        !states.includes(row.state) ||
        typeof row.request_active !== "boolean" ||
        typeof row.cleanup_confirmed !== "boolean" ||
        !(
          row.error === null ||
          (typeof row.error === "string" && row.error.length <= 500)
        ) ||
        (group === "active") !==
          (["starting", "active", "releasing"].includes(row.state) ||
            row.request_active)
      )
        throw new Error(
          "Power lifecycle rows have invalid identities, bounds or active/recent classification.",
        );
      ids.add(row.id);
    }
  }
  return value as PowerStatus;
}
