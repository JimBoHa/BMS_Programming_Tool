import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { seedBinary, binaryDocuments } from "./native-binary-terminal-fixture";
import {
  binaryTerminalEdit,
  binaryTerminalSource,
  binaryTerminalReview,
  binaryTerminalReceipt,
  binaryTerminalVerified,
} from "../src/nativeBinaryTerminalContract";
let fixture: any;
let fieldFixture: any;
const fieldData = () =>
  (fieldFixture ??= binaryDocuments(
    mkdtempSync(path.join(tmpdir(), "bms-binary-field-contract-")),
  ));
const data = () =>
  (fixture ??= seedBinary(
    mkdtempSync(path.join(tmpdir(), "bms-binary-contract-")),
  ));
test("observed source without redundant Device field and exact local proof pass", async () => {
  const f = data();
  expect(binaryTerminalSource(f.source, f.parent)).toBe(true);
  expect(binaryTerminalEdit(f.source, "binary-input,101", "3")).toEqual(f.edit);
  expect(
    await binaryTerminalReview(
      { data: JSON.parse(f.text), blob: new Blob([f.text]) },
      f.source,
      f.edit,
      false,
    ),
  ).toBe(true);
});
test("actual field review and verified binary receipt keep independent typed evidence", async () => {
  const f = fieldData();
  expect(binaryTerminalSource(f.source, f.parent)).toBe(true);
  expect(
    await binaryTerminalReview(
      { data: JSON.parse(f.text), blob: new Blob([f.text]) },
      f.source,
      f.edit,
      true,
    ),
  ).toBe(true);
  expect(binaryTerminalReceipt(f.receipt, f.source)).toBe(true);
  expect(binaryTerminalVerified(f.receipt)).toBe(true);
});
for (const fault of [
  "configuration",
  "profile",
  "guard",
  "identity",
  "slot",
  "pending",
  "published",
  "duplicate",
  "preservation",
] as const)
  test(`binary receipt does not promote ${fault} evidence`, () => {
    const f = fieldData(),
      r = structuredClone(f.receipt);
    if (fault === "configuration")
      r.intent.input_edit.configuration = { mode: "voltage" };
    if (fault === "profile")
      r.intent.operation_profile = "native-local-universal-input-transfer/2";
    if (fault === "guard")
      r.intent.compilation.configuration_sha256 = "0".repeat(64);
    if (fault === "identity") r.intent.identity.device = "device,5137";
    if (fault === "slot")
      r.intent.compilation.terminal_compilation.destination_slot = 2;
    if (fault === "pending") r.pending = true;
    if (fault === "published")
      r.result.published_input.properties.find(
        (p: any) => p.property === 519,
      ).actual = 2;
    if (fault === "duplicate")
      r.result.published_input.properties.push(
        r.result.published_input.properties[0],
      );
    if (fault === "preservation")
      r.result.preservation.identity_unchanged = false;
    if (
      ["configuration", "profile", "guard", "identity", "slot"].includes(fault)
    )
      expect(binaryTerminalReceipt(r, f.source)).toBe(false);
    else expect(binaryTerminalVerified(r)).toBe(false);
  });
for (const fault of [
  "guard",
  "charset",
  "vendor",
  "parent",
  "free",
  "live",
  "schema",
  "alias",
] as const)
  test(`binary source rejects ${fault}`, () => {
    const f = data(),
      s = structuredClone(f.source);
    if (fault === "guard") s.inputs[0].configuration_sha256 = "bad";
    if (fault === "charset") s.inputs[0].device_type_character_encoding = 3;
    if (fault === "vendor") s.identity["vendor-identifier"] = 99;
    if (fault === "parent") s.inputs[0].record_ref = "other/3_101";
    if (fault === "free") s.available_slots = [1, 3];
    if (fault === "live") s.counter_values_are_live = true;
    if (fault === "schema") s.inputs[0].configuration = { input_high: 10 };
    if (fault === "alias") s.inputs[0].configuration.polarity = true;
    expect(binaryTerminalSource(s, f.parent)).toBe(false);
  });
for (const fault of [
  "mode",
  "polarity",
  "profile",
  "encoding",
  "payload",
  "blob",
  "guard",
  "seal",
] as const)
  test(`binary review rejects ${fault}`, async () => {
    const f = data(),
      v = JSON.parse(f.text),
      c = v.compilation,
      p = c.terminal_compilation;
    if (fault === "mode") c.stored_configuration = { setup: 1 };
    if (fault === "polarity") c.stored_configuration.polarity = 0;
    if (fault === "profile")
      v.profile = "native-local-universal-input-transfer/2";
    if (fault === "encoding") p.device_type_character_encoding = 0;
    if (fault === "payload") p.payloads[1].after = "00554920494e33";
    if (fault === "guard") c.configuration_sha256 = "0".repeat(64);
    if (fault === "seal") v.review_sha256 = "0".repeat(64);
    const text = fault === "blob" ? f.text.slice(0, -1) : JSON.stringify(v);
    expect(
      await binaryTerminalReview(
        { data: v, blob: new Blob([text]) },
        f.source,
        f.edit,
        false,
      ),
    ).toBe(false);
  });
