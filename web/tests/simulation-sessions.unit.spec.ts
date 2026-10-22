import { test, expect } from "@playwright/test";
import {
  sessionFromReceipt,
  type SimulationSession,
} from "../src/simulationSessions";
const handle: SimulationSession = {
  session: "A".repeat(22),
  retirement_token: "T".repeat(32),
  creation_operation_id: "a".repeat(32),
};
const receipt = {
  ...handle,
  session_creation_operation_id: handle.creation_operation_id,
  operation_id: "a".repeat(32),
};
test("first ownership binds to exact creating operation; known ownership retains immutable creation identity", () => {
  expect(sessionFromReceipt(receipt, receipt.operation_id, null)).toEqual(
    handle,
  );
  expect(
    sessionFromReceipt(
      { ...receipt, operation_id: "b".repeat(32) },
      "b".repeat(32),
      handle,
    ),
  ).toEqual(handle);
});
for (const change of [
  { operation_id: "c".repeat(32) },
  { session: "B".repeat(22) },
  { retirement_token: "Q".repeat(32) },
  { session_creation_operation_id: "b".repeat(32) },
])
  test(`reject swapped known ownership ${Object.keys(change)[0]}`, () =>
    expect(() =>
      sessionFromReceipt(
        { ...receipt, ...change },
        receipt.operation_id,
        handle,
      ),
    ).toThrow());
test("new zero-commit receipt owns nothing and a known session cannot disappear silently", () => {
  expect(
    sessionFromReceipt(
      {
        operation_id: receipt.operation_id,
        session: null,
        retirement_token: null,
      },
      receipt.operation_id,
      null,
    ),
  ).toBeNull();
  expect(() =>
    sessionFromReceipt(
      {
        operation_id: receipt.operation_id,
        session: null,
        retirement_token: null,
      },
      receipt.operation_id,
      handle,
    ),
  ).toThrow();
});
