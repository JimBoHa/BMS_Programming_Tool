import { test, expect } from "@playwright/test";
import { scenarioStartupProfile } from "../src/cafScenarioStartup";
import { python } from "./caf-simulation-fixture";
function fixture() {
  return JSON.parse(
    python(`
import json
from tests.test_caf_enum_scenarios import enum_scenario
from bms_tool.caf_simulation import CafSimulationProfile
a,s,i=enum_scenario()
print(json.dumps({'scenario':s,'original':a.template(),'baseline':CafSimulationProfile(a.archive,profile_version=2).export_profile(),'expected':a.startup_profile(s,1),'identity':i}))
`).toString(),
  );
}
test("version2 startup independently projects exact numeric Enum input while preserving all other records", () => {
  const f = fixture();
  expect(scenarioStartupProfile(f.scenario, 1, f.baseline, f.original)).toEqual(
    f.expected,
  );
});
for (const value of ["0", "65536", "4294967295"])
  test(`startup admits canonical Enum code ${value}`, () => {
    const f = fixture();
    f.scenario.events[0].values[f.identity].value = value;
    const profile = scenarioStartupProfile(
      f.scenario,
      1,
      f.baseline,
      f.original,
    );
    expect(profile.entries.find((r) => r.class_id === "528")!.value).toBe(
      value,
    );
    expect(profile.entries.find((r) => r.class_id === "527")!.value).toBe(
      "25.000",
    );
  });
for (const value of ["01", "+1", " 1", "-1", "1.0", "4294967296"])
  test(`startup refuses noncanonical or out-of-range Enum code ${value}`, () => {
    const f = fixture();
    f.scenario.events[0].values[f.identity].value = value;
    expect(() =>
      scenarioStartupProfile(f.scenario, 1, f.baseline, f.original),
    ).toThrow();
  });
for (const fault of [
  "set",
  "authority",
  "maximum",
  "output",
  "legacy-profile",
  "legacy-scenario",
  "quality",
])
  test(`startup refuses ${fault} substitution`, () => {
    const f = fixture();
    if (fault === "set") {
      f.scenario.inputs[2].enum_representation.attributes.set = "999";
      f.original.inputs[2].enum_representation.attributes.set = "999";
    }
    if (fault === "authority") {
      f.scenario.inputs[2].enum_representation.enum_semantics_verified = true;
      f.original.inputs[2].enum_representation.enum_semantics_verified = true;
    }
    if (fault === "maximum") {
      f.scenario.inputs[2].enum_representation.maximum_code = 65535;
      f.original.inputs[2].enum_representation.maximum_code = 65535;
    }
    if (fault === "output")
      f.baseline.entries.find((r: any) => r.class_id === "528").class_id =
        "529";
    if (fault === "legacy-profile") f.baseline.version = 1;
    if (fault === "legacy-scenario") {
      f.scenario.version = 1;
      f.original.version = 1;
    }
    if (fault === "quality")
      f.scenario.events[0].values[f.identity].quality = "open-circuit";
    expect(() =>
      scenarioStartupProfile(f.scenario, 1, f.baseline, f.original),
    ).toThrow();
  });
