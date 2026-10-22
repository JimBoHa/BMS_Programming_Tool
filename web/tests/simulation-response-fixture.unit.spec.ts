import { test, expect } from "@playwright/test";
import { ownedSimulationHandle } from "./simulationFixture";
const nonce = "a".repeat(32);
const proof = () => ({
  pageURL: "http://127.0.0.1:8766/",
  requestURL: "http://127.0.0.1:8766/api/simulation/step",
  responseURL: "http://127.0.0.1:8766/api/simulation/step",
  method: "POST",
  status: 200,
  requestBody: JSON.stringify({ session: null, operation_id: nonce }),
  responseBody: JSON.stringify({
    operation_id: nonce,
    session_creation_operation_id: nonce,
    session: "owned_session_12345678901234567890",
    retirement_token: "t".repeat(32),
  }),
});
test("only same-page actual HTTP source and exact creation nonce nominate fixture ownership", () => {
  expect(ownedSimulationHandle(proof())).toEqual({
    session: "owned_session_12345678901234567890",
    retirement_token: "t".repeat(32),
    creation_operation_id: nonce,
  });
});
for (const change of [
  { pageURL: "http://127.0.0.1:9999/" },
  { responseURL: "http://127.0.0.1:9999/api/simulation/step" },
  { responseURL: "http://127.0.0.1:8766/api/simulation/scenario" },
  { method: "GET" },
  { status: 503 },
  { requestBody: JSON.stringify({ session: "existing", operation_id: nonce }) },
  {
    requestBody: JSON.stringify({
      session: null,
      operation_id: "b".repeat(32),
    }),
  },
  {
    responseBody: JSON.stringify({
      operation_id: nonce,
      session_creation_operation_id: "b".repeat(32),
      session: "owned_session_12345678901234567890",
      retirement_token: "t".repeat(32),
    }),
  },
  { responseBody: "" },
  { requestBody: null },
])
  test(
    "fixture refuses unmatched source/nonce/status ownership: " +
      JSON.stringify(change),
    () => {
      expect(ownedSimulationHandle({ ...proof(), ...change })).toBeNull();
    },
  );
