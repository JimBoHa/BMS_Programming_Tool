import { apiKeepalive } from "./api";
import { parseSourceJSON } from "./programSource";

export type SimulationSession = {
  session: string;
  retirement_token: string;
  creation_operation_id: string;
};

export const SIMULATION_CLEANUP_KEY = "bms-studio-owned-simulation-cleanup/1";
type CleanupStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;
const cleanupHandle = (value: any): value is SimulationSession =>
  value !== null &&
  typeof value === "object" &&
  !Array.isArray(value) &&
  Object.keys(value).sort().join(",") ===
    "creation_operation_id,retirement_token,session" &&
  typeof value.session === "string" &&
  /^[A-Za-z0-9_-]{20,64}$/.test(value.session) &&
  typeof value.retirement_token === "string" &&
  /^[A-Za-z0-9_-]{32,64}$/.test(value.retirement_token) &&
  typeof value.creation_operation_id === "string" &&
  /^[a-f0-9]{32}$/.test(value.creation_operation_id);
const sameHandle = (a: SimulationSession, b: SimulationSession) =>
  a.session === b.session &&
  a.retirement_token === b.retirement_token &&
  a.creation_operation_id === b.creation_operation_id;

/** Pending deletion intent only: active or unknown sessions are never recorded. */
export function pendingSimulationCleanup(
  storage: CleanupStorage = window.sessionStorage,
): SimulationSession[] {
  const raw = storage.getItem(SIMULATION_CLEANUP_KEY);
  if (raw === null) return [];
  if (raw.length > 16384)
    throw new Error("Local cleanup record exceeds its bound.");
  const value = parseSourceJSON(raw);
  if (
    value?.format !== SIMULATION_CLEANUP_KEY ||
    Object.keys(value).sort().join(",") !== "format,handles" ||
    !Array.isArray(value.handles) ||
    value.handles.length > 32 ||
    !value.handles.every(cleanupHandle) ||
    new Set(value.handles.map((h: SimulationSession) => h.session)).size !==
      value.handles.length
  )
    throw new Error(
      "Local cleanup ownership record is malformed; it was not changed.",
    );
  return value.handles;
}

export function rememberSimulationCleanup(
  handle: SimulationSession,
  storage: CleanupStorage = window.sessionStorage,
) {
  if (!cleanupHandle(handle)) throw new Error("Invalid owned cleanup handle.");
  const handles = pendingSimulationCleanup(storage);
  const existing = handles.find((h) => h.session === handle.session);
  if (existing && !sameHandle(existing, handle))
    throw new Error(
      "Local cleanup ownership collision; existing record retained.",
    );
  if (existing) return;
  if (handles.length >= 32)
    throw new Error("Local cleanup ownership capacity reached.");
  const raw = JSON.stringify({
    format: SIMULATION_CLEANUP_KEY,
    handles: [...handles, handle],
  });
  if (raw.length > 16384)
    throw new Error("Local cleanup record exceeds its bound.");
  storage.setItem(SIMULATION_CLEANUP_KEY, raw);
}

export function finishSimulationCleanup(
  handle: SimulationSession,
  storage: CleanupStorage = window.sessionStorage,
) {
  if (!cleanupHandle(handle)) throw new Error("Invalid owned cleanup handle.");
  const handles = pendingSimulationCleanup(storage);
  const existing = handles.find((h) => h.session === handle.session);
  if (existing && !sameHandle(existing, handle))
    throw new Error(
      "Cleanup acknowledgement cannot remove another ownership record.",
    );
  const remaining = handles.filter((h) => h.session !== handle.session);
  if (remaining.length)
    storage.setItem(
      SIMULATION_CLEANUP_KEY,
      JSON.stringify({ format: SIMULATION_CLEANUP_KEY, handles: remaining }),
    );
  else storage.removeItem(SIMULATION_CLEANUP_KEY);
}

/** Accept ownership only from the exact creating request or the known session. */
export function sessionFromReceipt(
  receipt: any,
  operation: string,
  expected: SimulationSession | null,
): SimulationSession | null {
  if (receipt.operation_id !== operation)
    throw new Error(
      "Simulation receipt does not match its admitted operation.",
    );
  if (receipt.session === null) {
    if (expected || receipt.retirement_token !== null)
      throw new Error("Simulation receipt lost its known session ownership.");
    return null;
  }
  if (
    typeof receipt.session !== "string" ||
    !/^[A-Za-z0-9_-]{20,64}$/.test(receipt.session) ||
    typeof receipt.retirement_token !== "string" ||
    !/^[A-Za-z0-9_-]{32,64}$/.test(receipt.retirement_token) ||
    receipt.session_creation_operation_id !==
      (expected ? expected.creation_operation_id : operation) ||
    (expected &&
      (receipt.session !== expected.session ||
        receipt.retirement_token !== expected.retirement_token))
  )
    throw new Error("Simulation receipt does not match its session ownership.");
  return {
    session: receipt.session,
    retirement_token: receipt.retirement_token,
    creation_operation_id: receipt.session_creation_operation_id,
  };
}

export async function retireSimulationSession(session: SimulationSession) {
  const receipt = await apiKeepalive("/simulation/retire", session);
  if (
    receipt.session !== session.session ||
    typeof receipt.retired !== "boolean" ||
    receipt.recorded_evidence_unchanged !== true
  )
    throw new Error("Simulation retirement returned an unrelated receipt.");
}
