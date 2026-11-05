import type { NativeArchiveSource } from "./NativeRecords";
import {
  terminalCapabilityEvidence as legacyEvidence,
  terminalCapabilityWitness,
} from "./nativeTerminalCapabilityContract";
type Data = Record<string, any>;
export const terminalCapabilityProfile =
  "native-backup-operation-capabilities/16";
const newIds = [
  "encoded-local-terminal-copy",
  "encoded-effective-local-terminal-copy",
];
export const terminalOperationIds = [...newIds, "analog-terminal-transfer"];
export function terminalCapabilityEvidence(
  data: Data,
  source: NativeArchiveSource,
) {
  try {
    if (
      data?.capability_profile !== terminalCapabilityProfile ||
      !Array.isArray(data.operations) ||
      data.operations.length !== 32 ||
      new Set(data.operations.map((r: Data) => r.id)).size !== 32
    )
      return false;
    const q = data.qualification,
      previous = { ...q };
    for (const basis of ["archive", "effective"]) {
      delete previous["encoded_" + basis + "_terminal"];
      delete previous["encoded_" + basis + "_terminal_error"];
    }
    if (
      !legacyEvidence(
        {
          ...data,
          capability_profile: "native-backup-operation-capabilities/15",
          qualification: previous,
          operations: data.operations.filter(
            (r: Data) => !newIds.includes(r.id),
          ),
        },
        source,
      )
    )
      return false;
    for (const [i, basis] of ["archive", "effective"].entries()) {
      const value = q["encoded_" + basis + "_terminal"],
        failure = q["encoded_" + basis + "_terminal_error"];
      if (value === null) {
        if (
          typeof failure !== "string" ||
          !failure.length ||
          Array.from(failure).length > 512
        )
          return false;
      } else {
        if (
          failure !== null ||
          !terminalCapabilityWitness(
            value,
            basis,
            source,
            q.native_identity?.root_ref,
            true,
          )
        )
          return false;
        if (
          basis === "effective" &&
          (q.recorded_identity_verified !== true ||
            q.identity_matches_snapshot !== true)
        )
          return false;
      }
      const rows = data.operations.filter((r: Data) => r.id === newIds[i]);
      if (
        rows.length !== 1 ||
        rows[0].status !==
          (value === null ? "unsupported-source" : "source-qualified") ||
        !["operation", "basis", "next_step"].every(
          (k) => typeof rows[0][k] === "string",
        )
      )
        return false;
    }
    return true;
  } catch {
    return false;
  }
}
