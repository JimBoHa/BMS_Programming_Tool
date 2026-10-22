import { test, expect } from "@playwright/test";
import { createHash } from "node:crypto";
import {
  projectedSourceFixture,
  sourceFixtureData,
  resealSourceFixture,
  requestProgram,
} from "./sourceTransportFixtures";
import { numericToken, sourceStringify } from "../src/programSource";

const raw =
  '{"schema_version":1,"id":"fixture-source","name":"Actual source","description":"","revision":7,"scan_seconds":1.0,"target":{"family":"universal-runtime","model":"","firmware":"","release_mode":"","max_nodes":2000,"physical_inputs":null,"physical_outputs":null},"nodes":[{"id":"a","kind":"Constant","label":"","x":0.0,"y":-0.0,"params":{"value":1.0,"unrelated":[-0.0,9007199254740993,1e-7]},"unit":"","value_type":"number"}],"edges":[],"metadata":{"opaque":[9007199254740993,-0.0,1.0]}}';
const envelope = () => ({
  format: "bms.program-source-response/1",
  source_json: raw,
  source_sha256: createHash("sha256").update(raw).digest("hex"),
  programs: [
    {
      path: [],
      program_id: "fixture-source",
      revision_text: "7",
      canonical_sha256: "a".repeat(64),
      canonical_format: "canonical-json/1",
    },
  ],
});
test("capture projection reads structural revision without rounding opaque source tokens", () => {
  const wrapped = envelope(),
    projected = projectedSourceFixture(wrapped);
  expect(projected.revision).toBe(7);
  expect(projected.scan_seconds).toBe(1);
  expect(projected.nodes).toHaveLength(1);
  expect(sourceStringify(projected.nodes[0].params)).toBe(
    '{"value":1.0,"unrelated":[-0.0,9007199254740993,1e-7]}',
  );
  expect(sourceStringify(projected.metadata)).toBe(
    '{"opaque":[9007199254740993,-0.0,1.0]}',
  );
  expect(wrapped.source_json).toBe(raw);
});
test("response fixture reseals an intended non-Program fault and keeps every unrelated atom", () => {
  const wrapperRaw = '{"profile":{"id":"expected"},"program":' + raw + "}",
    wrapped = { ...envelope(), source_json: wrapperRaw },
    data = sourceFixtureData(wrapped);
  data.profile.id = "wrong-profile";
  const altered = resealSourceFixture(wrapped, data),
    decoded = sourceFixtureData(altered);
  expect(decoded.profile.id).toBe("wrong-profile");
  expect(sourceStringify(decoded.program)).toBe(raw);
  expect(altered.source_sha256).toBe(
    createHash("sha256").update(altered.source_json).digest("hex"),
  );
  expect(numericToken(decoded.program.nodes[0].params.value)).toBe("1.0");
  expect(wrapped.source_json).toBe(wrapperRaw);
});
test("UI request shape predicate accepts an envelope and legacy API stays plain", () => {
  const request = { format: "bms.program-source/1", source_json: raw };
  expect(requestProgram(request).nodes).toHaveLength(1);
  expect(requestProgram(request).name).toBe("Actual source");
  expect(projectedSourceFixture(request).revision).toBe(7);
  expect(sourceStringify(projectedSourceFixture(request).metadata)).toBe(
    '{"opaque":[9007199254740993,-0.0,1.0]}',
  );
  expect(request.source_json).toBe(raw);
  const legacy = { revision: 7, nodes: [] };
  expect(projectedSourceFixture(legacy)).toEqual(legacy);
  expect(sourceFixtureData(legacy)).toBe(legacy);
});
