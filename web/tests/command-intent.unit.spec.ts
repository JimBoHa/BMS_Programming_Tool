import { test } from "@playwright/test";
import assert from "node:assert/strict";
import {
  parseBacnetCommandIntent,
  verifyBacnetCommandPlan,
} from "../src/commandIntent";
import { sourceStringify } from "../src/programSource";

test("unsafe integer and malformed/nonfinite inputs never fall back to strings", () => {
  for (const text of [
    "9007199254740993",
    "-9007199254740993",
    "1" + "0".repeat(400),
    "1e999",
    "-1e999",
    "NaN",
    "Infinity",
    "-Infinity",
    "01",
    "+1",
    ".5",
    "1e",
    "-",
    "null",
    "[]",
    "{}",
    '"unterminated',
    "true false",
    "",
  ])
    assert.throws(() => parseBacnetCommandIntent(text));
});
test("exact integer, decimal profile and signedzero intent retain original tokens", () => {
  for (const token of [
    "9007199254740992",
    "1152921504606846976",
    "9007199254740994",
    "-1152921504606846976",
    "-0.0",
    "1.0",
    "1e-7",
    "9007199254740993.0",
  ])
    assert.equal(sourceStringify(parseBacnetCommandIntent(token)), token);
});
test("bare and quoted labels and Boolean remain distinct scalars", () => {
  for (const [text, value] of [
    ["active", "active"],
    ['"active"', "active"],
    ['"true"', "true"],
    ["true", true],
    ["false", false],
    ['"9007199254740993"', "9007199254740993"],
  ])
    assert.equal(parseBacnetCommandIntent(text), value);
});
test("lossless receipt verification refuses adjacent integer despite JS Number collision", () => {
  const value = parseBacnetCommandIntent("1152921504606846976"),
    request = {
      address: "127.0.0.1:47808",
      object_id: "analog-value,1",
      priority: 16,
      value,
    };
  const raw =
    '{"address":"127.0.0.1:47808","object":"analog-value,1","priority":16,"token":"proof","requested_value":1152921504606846976,"value":1.152921504606847e18}';
  verifyBacnetCommandPlan(request, JSON.parse(raw), raw);
  const wrong = raw.replace("1152921504606846976", "1152921504606846977");
  assert.equal(
    JSON.parse(wrong).requested_value,
    JSON.parse(raw).requested_value,
  );
  assert.throws(
    () => verifyBacnetCommandPlan(request, JSON.parse(wrong), wrong),
    /numeric intent/,
  );
});
test("native response canonical float spellings preserve type and negativezero", () => {
  const request = {
    address: "127.0.0.1:47808",
    object_id: "analog-value,1",
    priority: 16,
    value: parseBacnetCommandIntent("1e-7"),
  };
  const plan = {
    address: request.address,
    object: request.object_id,
    priority: 16,
    token: "proof",
  };
  verifyBacnetCommandPlan(
    request,
    plan,
    JSON.stringify({ ...plan, requested_value: 1e-7 }),
  );
  const zero = { ...request, value: parseBacnetCommandIntent("-0.0") };
  const raw = (value) =>
    JSON.stringify(plan).slice(0, -1) + ',"requested_value":' + value + "}";
  verifyBacnetCommandPlan(zero, plan, raw("-0.0"));
  assert.throws(
    () => verifyBacnetCommandPlan(zero, plan, raw("0.0")),
    /numeric intent/,
  );
  assert.throws(
    () =>
      verifyBacnetCommandPlan(
        { ...request, value: parseBacnetCommandIntent("1.0") },
        plan,
        raw("1"),
      ),
    /numeric intent/,
  );
});
test("preview response identities and original document remain jointly bound", () => {
  const request = {
    address: "127.0.0.1:47808",
    object_id: "binary-value,1",
    priority: 16,
    value: parseBacnetCommandIntent("true"),
  };
  const plan = {
    address: request.address,
    object: request.object_id,
    priority: 16,
    token: "proof",
    requested_value: true,
    value: 1,
  };
  verifyBacnetCommandPlan(request, plan, JSON.stringify(plan));
  for (const patch of [
    { address: "127.0.0.1:1" },
    { object: "binary-value,2" },
    { priority: 15 },
    { token: "" },
    { requested_value: "true" },
  ]) {
    const altered = { ...plan, ...patch };
    assert.throws(() =>
      verifyBacnetCommandPlan(request, altered, JSON.stringify(altered)),
    );
  }
  assert.throws(
    () =>
      verifyBacnetCommandPlan(
        request,
        plan,
        '{"receipt":' + JSON.stringify(plan) + "}",
      ),
    /identity/,
  );
  assert.throws(
    () =>
      verifyBacnetCommandPlan(
        request,
        plan,
        JSON.stringify({ ...plan, token: "another" }),
      ),
    /identity/,
  );
});
