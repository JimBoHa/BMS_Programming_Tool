import { api } from "./api";
import { controllerKey, type ControllerTarget } from "./workflow";

type Data = Record<string, any>;
export type ComparisonSourceKind = "backup" | "file";
export type ComparisonSource = {
  kind: ComparisonSourceKind;
  id: string;
  signature: string;
  target: ControllerTarget;
  captured_at: string;
  identity: Data;
  raw: Data;
};
const hash = (value: unknown): value is string =>
  typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
export const correlationProfile = (kind: ComparisonSourceKind) =>
  kind === "backup"
    ? "caf-native-source-correlation/1"
    : "caf-native-file-source-correlation/1";

export async function comparisonSources(
  kind: ComparisonSourceKind,
): Promise<ComparisonSource[]> {
  const backup = kind === "backup";
  const result = await api(
    backup
      ? "/bacnet/controller/native-application/signal-default/sources"
      : "/caf/native-file-sources",
  );
  if (
    result.profile !==
      (backup
        ? "native-effective-signal-default-compiler/1"
        : "caf-native-file-comparison-sources/1") ||
    result.controller_queries !== false ||
    !Array.isArray(result.sources) ||
    result.sources.length > (backup ? 128 : 32) ||
    (!backup &&
      (result.source_limit !== 32 ||
        result.read_only !== true ||
        result.field_actions !== false))
  )
    throw new Error("Unsupported retained comparison source list.");
  const rows: ComparisonSource[] = result.sources.map((row: Data) => {
    const id = backup ? row.id : row.capture_id;
    const signature = backup ? row.evidence_sha256 : row.receipt_sha256;
    const target = backup ? { ...row.target, device: row.device } : row.target;
    if (
      !/^[a-f0-9]{32}$/.test(id || "") ||
      !hash(signature) ||
      typeof target?.address !== "string" ||
      typeof target?.device !== "string" ||
      typeof row.captured_at !== "string" ||
      (!backup &&
        (!hash(row.sha256) ||
          !hash(row.connector_sha256) ||
          typeof row.file_object !== "string" ||
          !Number.isInteger(row.bytes) ||
          row.bytes < 1 ||
          row.bytes > 2097152))
    )
      throw new Error("Unsupported retained comparison source identity.");
    return {
      kind,
      id,
      signature,
      target,
      captured_at: row.captured_at,
      identity: row.identity || {},
      raw: row,
    };
  });
  if (new Set(rows.map((row) => row.id)).size !== rows.length)
    throw new Error("Retained comparison source identifiers are duplicated.");
  return rows;
}

export function comparisonRequest(
  source: ComparisonSource,
  caf: string,
  query: string,
  offset: number,
): Data {
  const common = {
    source_sha256: caf,
    capture_id: source.id,
    query,
    offset,
    limit: 64,
  };
  return source.kind === "backup"
    ? { ...common, snapshot_sha256: source.signature }
    : {
        ...common,
        receipt_sha256: source.signature,
        file_sha256: source.raw.sha256,
      };
}
export function comparisonReportSource(
  data: Data,
  kind: ComparisonSourceKind,
): Data {
  return kind === "backup" ? data.native_backup : data.native_file;
}
export function comparisonIdentityFlag(
  data: Data,
  kind: ComparisonSourceKind,
): unknown {
  return kind === "backup"
    ? data.recorded_acquisition_identity_verified
    : data.recorded_device_identity_agrees;
}
export function comparisonSourceMatches(
  data: Data,
  selected: ComparisonSource,
) {
  const source = comparisonReportSource(data, selected.kind);
  if (
    data.profile !== correlationProfile(selected.kind) ||
    !source ||
    source.capture_id !== selected.id ||
    !hash(source.sha256) ||
    source.captured_at !== selected.captured_at ||
    controllerKey(source.target) !== controllerKey(selected.target) ||
    source.read_only !== true ||
    source.controller_queries !== false ||
    source.field_actions !== false ||
    source.identity_verified !== false ||
    typeof comparisonIdentityFlag(data, selected.kind) !== "boolean"
  )
    return false;
  if (selected.kind === "backup")
    return (
      data.native_file === undefined &&
      source.profile === "native-backup-record-inspection/1" &&
      source.source_kind === "native-backup-archive" &&
      source.snapshot_sha256 === selected.signature &&
      source.files?.["3"]?.sha256 === source.sha256
    );
  return (
    data.native_backup === undefined &&
    source.profile === "retained-native-file-comparison-source/1" &&
    source.source_kind === "controller-file-capture" &&
    source.receipt_sha256 === selected.signature &&
    source.sha256 === selected.raw.sha256 &&
    source.connector_sha256 === selected.raw.connector_sha256 &&
    source.file_object === selected.raw.file_object &&
    source.bytes === selected.raw.bytes &&
    source.metadata?.object_id === source.file_object &&
    source.metadata?.file_size === source.bytes &&
    source.full_native_backup === false &&
    source.saved_settings_available === false
  );
}
