import { apiKeepalive } from "./api";

export type SimulationSession = {
  session: string;
  retirement_token: string;
  creation_operation_id: string;
};

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
