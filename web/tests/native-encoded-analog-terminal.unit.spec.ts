import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import {
  seedEncodedAnalog,
  encodedAnalogDocuments,
} from "./native-encoded-analog-terminal-fixture";
import {
  encodedAnalogTerminalSource,
  encodedAnalogTerminalEdit,
  encodedAnalogTerminalReview,
  encodedAnalogTerminalReceipt,
  encodedAnalogTerminalVerified,
} from "../src/nativeEncodedAnalogTerminalContract";
let local: any, field: any;
const data = () =>
  (local ??= seedEncodedAnalog(
    mkdtempSync(path.join(tmpdir(), "encoded-analog-local-")),
  ));
const live = () =>
  (field ??= encodedAnalogDocuments(
    mkdtempSync(path.join(tmpdir(), "encoded-analog-field-")),
  ));
test("actual local source and exact document retain paired absent output endpoints", async () => {
  const f = data();
  expect(encodedAnalogTerminalSource(f.source, f.parent)).toBe(true);
  expect(f.source.inputs[0].configuration.output_low).toBeNull();
  expect(
    f.source.inputs[0].configuration_storage.linear_output_endpoints_present,
  ).toBe(false);
  expect(encodedAnalogTerminalEdit(f.source, "analog-input,101", "3")).toEqual(
    f.edit,
  );
  expect(
    await encodedAnalogTerminalReview(
      { data: JSON.parse(f.text), blob: new Blob([f.text]) },
      f.source,
      f.edit,
      false,
    ),
  ).toBe(true);
});
for (const [name, change] of Object.entries({
  profile: (s: any) => (s.profile = "native-local-universal-input-transfer/2"),
  capture: (s: any) => (s.capture_id = "0".repeat(32)),
  target: (s: any) => (s.target.address = "127.0.0.1:47810"),
  guard: (s: any) => (s.inputs[0].configuration_sha256 = "bad"),
  instance: (s: any) => (s.inputs[0].object_id = "binary-input,101"),
  reference: (s: any) => (s.inputs[0].record_ref = "controller/3_101"),
  charset: (s: any) => (s.inputs[0].device_type_character_encoding = 5),
  boolCharset: (s: any) => (s.inputs[0].device_type_character_encoding = false),
  scaling: (s: any) => (s.inputs[0].configuration.input_low = 0.1),
  invented: (s: any) => (s.inputs[0].configuration.output_low = 0),
  endpoints: (s: any) => (s.inputs[0].stored_configuration.output_low = 0),
  storage: (s: any) =>
    (s.inputs[0].configuration_storage.linear_output_endpoints_present = true),
  presence: (s: any) =>
    (s.inputs[0].configuration_storage.present_properties = [true]),
  occupied: (s: any) => (s.available_slots = [1, 3]),
  duplicate: (s: any) => s.inputs.push(s.inputs[0]),
  live: (s: any) => (s.controller_queries = true),
}))
  test(`encoded analog source refuses ${name}`, () => {
    const f = data(),
      s = structuredClone(f.source);
    change(s);
    expect(encodedAnalogTerminalSource(s, f.parent)).toBe(false);
  });
test("actual field review and receipt require full preserved configuration and published absence", async () => {
  const f = live();
  expect(encodedAnalogTerminalSource(f.source, f.parent)).toBe(true);
  expect(
    await encodedAnalogTerminalReview(
      { data: JSON.parse(f.text), blob: new Blob([f.text]) },
      f.source,
      f.edit,
      true,
    ),
  ).toBe(true);
  expect(encodedAnalogTerminalReceipt(f.receipt, f.source)).toBe(true);
  expect(encodedAnalogTerminalVerified(f.receipt)).toBe(true);
});
for (const [name, change] of Object.entries({
  profile: (r: any) =>
    (r.intent.operation_profile = "native-local-universal-input-transfer/2"),
  action: (r: any) => (r.intent.input_edit.action = "terminal"),
  storage: (r: any) =>
    (r.intent.compilation.configuration_storage.linear_output_endpoints_present = true),
  config: (r: any) => (r.intent.compilation.stored_configuration.setup = true),
  endpoint: (r: any) =>
    (r.intent.compilation.stored_configuration.output_low = 0),
}))
  test(`encoded analog receipt refuses ${name}`, () => {
    const f = live(),
      r = structuredClone(f.receipt);
    change(r);
    expect(encodedAnalogTerminalReceipt(r, f.source)).toBe(false);
  });
for (const [name, change] of Object.entries({
  pending: (r: any) => (r.pending = true),
  operational: (r: any) => (r.result.operational = false),
  status: (r: any) => (r.result.system_status = 1),
  preservation: (r: any) =>
    (r.result.preservation.profile = "native-local-universal-input-transfer/1"),
  missing: (r: any) =>
    (r.result.published_input.properties =
      r.result.published_input.properties.filter(
        (p: any) => p.property !== 518,
      )),
  invented: (r: any) =>
    r.result.published_input.properties.push({
      property: 1295,
      actual: null,
      expected: null,
      matches: true,
    }),
  value: (r: any) =>
    (r.result.published_input.properties.find(
      (p: any) => p.property === 519,
    ).actual = 2),
  duplicate: (r: any) =>
    r.result.published_input.properties.push(
      r.result.published_input.properties[0],
    ),
}))
  test(`encoded analog verified outcome refuses ${name}`, () => {
    const r = structuredClone(live().receipt);
    change(r);
    expect(encodedAnalogTerminalVerified(r)).toBe(false);
  });
