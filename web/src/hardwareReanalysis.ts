export const hardwareReanalysisProfile = "saved-hardware-archive-reanalysis/1";
type Data = Record<string, any>;
const hash = (v: unknown) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
export function admittedHardwareReanalysis(child: Data, parent: Data) {
  const origin = child?.origin,
    source = child?.source;
  return (
    !!child &&
    typeof child.id === "string" &&
    /^[a-f0-9]{32}$/.test(child.id) &&
    child.id !== parent.id &&
    child.profile === "jci-moi-hardware-evidence/1" &&
    child.read_only === true &&
    !!source &&
    source.sha256 === parent.source?.sha256 &&
    hash(source.sha256) &&
    source.bytes === parent.source?.bytes &&
    Number.isSafeInteger(source.bytes) &&
    source.bytes > 0 &&
    source.bytes <= 2 * 1024 * 1024 &&
    source.filename === parent.source?.filename &&
    !!origin &&
    typeof origin === "object" &&
    !Array.isArray(origin) &&
    Object.keys(origin).length === 9 &&
    [
      "kind",
      "profile",
      "parent_archive_id",
      "parent_source_sha256",
      "parent_evidence_sha256",
      "parent_origin",
      "controller_queries",
      "controller_writes",
      "current_controller_identity_verified",
    ].every((k) => Object.hasOwn(origin, k)) &&
    origin.kind === "saved-archive-reanalysis" &&
    origin.profile === hardwareReanalysisProfile &&
    origin.parent_archive_id === parent.id &&
    origin.parent_source_sha256 === source.sha256 &&
    hash(origin.parent_evidence_sha256) &&
    origin.controller_queries === false &&
    origin.controller_writes === false &&
    origin.current_controller_identity_verified === false
  );
}
