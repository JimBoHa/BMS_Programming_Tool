import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";
import {
  admitSimulationSource,
  importProfile,
  carryLegacySimulation,
  signature,
} from "../src/cafSimulationProfile";
import type { Profile, Summary } from "../src/cafSimulationProfile";
const root = path.resolve("..");
function sources() {
  return JSON.parse(
    execFileSync(
      path.join(root, ".venv/bin/python"),
      [
        "-c",
        `
import json
from tests.test_caf_simulation import make_caf
from bms_tool.caf_simulation import CafSimulationProfile
print(json.dumps({str(v):{'profile':CafSimulationProfile(make_caf(),profile_version=v).export_profile(),'inventory':CafSimulationProfile(make_caf(),profile_version=v).summary()} for v in (1,2)}))
`,
      ],
      {
        cwd: root,
        env: {
          ...process.env,
          PYTHONPATH: [
            process.env.BMS_TEST_INSTALLED_TARGET || path.join(root, "backend"),
            root,
          ].join(path.delimiter),
        },
      },
    ).toString(),
  ) as Record<string, { profile: Profile; inventory: Summary }>;
}
const corpus = sources();
function original(v = 2) {
  return structuredClone(corpus[String(v)]);
}
test("independent backend v1/v2 records retain exact source, counts and Enum authority bounds", () => {
  for (const version of [1, 2] as const) {
    const { profile, inventory } = original(version);
    expect(
      admitSimulationSource(inventory, profile, profile.source_sha256, version),
    ).toEqual(profile);
    expect(profile.entries.filter((r) => r.editable)).toHaveLength(
      version === 1 ? 3 : 4,
    );
  }
});
test("source admission refuses version/source/complete-inventory mismatch before editing", () => {
  for (const fault of [
    "source",
    "version",
    "records",
    "counts",
    "duplicate",
    "shape",
    "name",
  ]) {
    const { profile, inventory } = original();
    if (fault === "source") profile.source_sha256 = "0".repeat(64);
    if (fault === "version") (profile as any).version = true;
    if (fault === "records") profile.entries.pop();
    if (fault === "counts") inventory.counts.editable++;
    if (fault === "duplicate") {
      profile.entries[0] = structuredClone(profile.entries[1]);
      inventory.records = structuredClone(profile.entries);
    }
    if (fault === "shape") {
      (profile.entries[3] as any).controller_write = true;
      inventory.records = structuredClone(profile.entries);
    }
    if (fault === "name") {
      (profile.entries[0] as any).name = 7;
      inventory.records = structuredClone(profile.entries);
    }
    expect(() =>
      admitSimulationSource(
        inventory,
        profile,
        corpus["2"].profile.source_sha256,
        2,
      ),
    ).toThrow();
  }
});
test("Enum editing requires observed class/version/tag/attributes and canonical original UInt32", () => {
  for (const update of [
    { class_id: "530" },
    { class_version: "2.0" },
    { kind: "property" },
    { property_id: "931" },
    { attributes: { set: "113", unknown: "x" } },
    { old: "01", value: "01" },
    { old: "4294967296", value: "4294967296" },
    { native_type: "unsignedLong" },
    { enum_semantics_verified: true },
    { maximum_code: 65535 },
  ]) {
    const { profile, inventory } = original();
    Object.assign(profile.entries[3], update);
    inventory.records = structuredClone(profile.entries);
    expect(() =>
      admitSimulationSource(inventory, profile, profile.source_sha256, 2),
    ).toThrow();
  }
});
test("v1 source cannot claim Enum editing even without version2 metadata", () => {
  const { profile, inventory } = original(1);
  profile.entries[3].editable = true;
  inventory.records = structuredClone(profile.entries);
  inventory.counts.editable++;
  inventory.counts.read_only--;
  expect(() =>
    admitSimulationSource(inventory, profile, profile.source_sha256, 1),
  ).toThrow();
});
test("profile import preserves invalid raw text for backend validation and normalizes record order", () => {
  const { profile } = original(),
    draft = structuredClone(profile);
  draft.entries[3].value = "1e-";
  draft.entries.reverse();
  const result = importProfile(draft, profile);
  expect(result.entries[3].value).toBe("1e-");
  expect(result.entries.map((r) => r.ref)).toEqual(
    profile.entries.map((r) => r.ref),
  );
  expect(signature(result)).not.toBe(signature(profile));
  expect(signature({ ...result, version: 1 })).not.toBe(signature(result));
});
test("imports refuse metadata/set/semantic changes, readonly edits and incomplete or duplicate records", () => {
  for (const fault of [
    "set",
    "semantics",
    "readonly",
    "duplicate",
    "missing",
    "extra",
    "type",
    "source",
  ]) {
    const { profile } = original(),
      draft = structuredClone(profile);
    if (fault === "set") draft.entries[3].attributes = { set: "114" };
    if (fault === "semantics")
      (draft.entries[3] as any).enum_semantics_verified = true;
    if (fault === "readonly") draft.entries[4].value = "1";
    if (fault === "duplicate")
      draft.entries[0] = structuredClone(draft.entries[1]);
    if (fault === "missing") draft.entries.pop();
    if (fault === "extra") (draft as any).can_apply = true;
    if (fault === "type") (draft.entries[3] as any).value = 2;
    if (fault === "source") draft.source_sha256 = "0".repeat(64);
    expect(() => importProfile(draft, profile)).toThrow();
  }
});
test("legacy import carries only permitted Float and Boolean drafts while resetting Enum to original", () => {
  const { profile: legacy } = original(1),
    { profile: current } = original();
  legacy.entries[0].value = "NaN";
  legacy.entries[2].value = "true";
  current.entries[3].value = "2";
  const result = carryLegacySimulation(
    importProfile(legacy, original(1).profile),
    current,
  );
  expect(result.entries.map((r) => r.value)).toEqual([
    "NaN",
    "25.000",
    "true",
    "1",
    null,
  ]);
  expect(result.version).toBe(2);
});
test("legacy adaptation rejects unknown source/class/type and attempts to widen Enum edit authority", () => {
  for (const fault of ["source", "class", "enum", "readonly", "duplicate"]) {
    const { profile: legacy } = original(1),
      { profile: current } = original();
    if (fault === "source") legacy.source_sha256 = "0".repeat(64);
    if (fault === "class") legacy.entries[0].class_id = "528";
    if (fault === "enum") legacy.entries[3].editable = true;
    if (fault === "readonly") legacy.entries[3].value = "2";
    if (fault === "duplicate")
      legacy.entries[0] = structuredClone(legacy.entries[1]);
    expect(() => carryLegacySimulation(legacy, current)).toThrow();
  }
});
