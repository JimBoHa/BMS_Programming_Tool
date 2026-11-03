import { test, expect } from "@playwright/test";
import {
  scenarioStartupProfile,
  admitStartupProfile,
} from "../src/cafScenarioStartup";
import {
  simulationCopyVerifier,
  simulationRequestSha256,
} from "../src/cafSimulationProfile";
import { sha256Blob } from "../src/activityContracts";
import { python } from "./caf-simulation-fixture";
function corpus() {
  return JSON.parse(
    python(`
import json,copy
from tests.test_caf_simulation import make_caf,pack
from bms_tool.caf import CafArchive
from bms_tool.caf_simulation import CafSimulationProfile
from bms_tool.caf_scenarios import CafInputScenarios
out=[]
for unicode in (False,True):
 raw=make_caf()
 if unicode:raw=pack(CafArchive(raw).xml.replace(b'8-1/526_1','é🙂/526_1'.encode()))
 adapter=CafInputScenarios(CafArchive(raw));original=adapter.template();scenario=copy.deepcopy(original);a,b=[row['id'] for row in scenario['inputs']]
 scenario.update(duration=1,dt=.1,events=[{'time':0,'values':{a:{'value':'-0.0','quality':'good'}}},{'time':.25,'values':{a:{'value':'-5.25','quality':'good'},b:{'value':'true','quality':'open-circuit'}}},{'time':.3,'values':{b:{'value':'false','quality':'good'}}},{'time':.7,'values':{a:{'value':'+7.25e1','quality':'good'}}}])
 rows=[]
 for time in (0,.1,.25,.3,.6,.7,1):
  try:rows.append({'time':time,'expected':adapter.startup_profile(scenario,time)})
  except ValueError:rows.append({'time':time,'quality_refused':True})
 out.append({'original':original,'scenario':scenario,'baseline':CafSimulationProfile(raw).export_profile(),'frames':rows})
print(json.dumps(out))
`).toString(),
  );
}
const examples = corpus();
function source() {
  return structuredClone(examples[0]);
}
test("independent Python startup profiles match inclusive hold, exact decimal boundaries, quality restoration and Unicode inputs", () => {
  for (const c of examples)
    for (const f of c.frames) {
      if (f.quality_refused)
        expect(() =>
          scenarioStartupProfile(c.scenario, f.time, c.baseline, c.original),
        ).toThrow("all-good");
      else
        expect(
          scenarioStartupProfile(c.scenario, f.time, c.baseline, c.original),
        ).toEqual(f.expected);
    }
});
test("source/template/input identity/type/initial value and semantic contract changes cannot create startup values", () => {
  for (const fault of [
    "source",
    "profile",
    "version",
    "input-id",
    "input-class",
    "input-old",
    "input-units",
    "missing-input",
    "Enum",
    "baseline-version",
  ]) {
    const c = source();
    if (fault === "source") c.scenario.source_sha256 = "0".repeat(64);
    if (fault === "profile") c.scenario.profile_sha256 = "0".repeat(64);
    if (fault === "version") c.scenario.version = true;
    if (fault === "input-id") c.scenario.inputs[0].id = "other";
    if (fault === "input-class") c.scenario.inputs[0].class_id = "529";
    if (fault === "input-old") c.scenario.inputs[0].initial_value = "1";
    if (fault === "input-units")
      c.scenario.inputs[0].units_native = { text: "changed" };
    if (fault === "missing-input") c.scenario.inputs.pop();
    if (fault === "Enum") {
      c.original.inputs[0].native_type = c.scenario.inputs[0].native_type =
        "enum";
    }
    if (fault === "baseline-version") c.baseline.version = 2;
    expect(() =>
      scenarioStartupProfile(c.scenario, 0, c.baseline, c.original),
    ).toThrow();
  }
});
test("unsupported times, event order, identities, sample shape, quality and native text are refused without coercion", () => {
  for (const fault of [
    "time",
    "dt",
    "duration",
    "order",
    "same-time",
    "unknown-input",
    "sample-extra",
    "quality",
    "float",
    "underflow",
    "overflow",
    "boolean",
    "records",
    "sample-coercion",
  ]) {
    const c = source();
    let time = 0;
    if (fault === "time") time = 0.35;
    if (fault === "dt") c.scenario.dt = 0;
    if (fault === "duration") c.scenario.duration = 0;
    if (fault === "order") c.scenario.events.reverse();
    if (fault === "same-time") c.scenario.events[1].time = 0;
    if (fault === "unknown-input")
      c.scenario.events[0].values = { other: { value: "1", quality: "good" } };
    if (fault === "sample-extra")
      Object.values(c.scenario.events[0].values).forEach(
        (s: any) => (s.grant = true),
      );
    if (fault === "quality")
      Object.values(c.scenario.events[0].values).forEach(
        (s: any) => (s.quality = "verified"),
      );
    if (fault === "float")
      Object.values(c.scenario.events[0].values).forEach(
        (s: any) => (s.value = "1e-"),
      );
    if (fault === "underflow")
      Object.values(c.scenario.events[0].values).forEach(
        (s: any) => (s.value = "1e-400"),
      );
    if (fault === "overflow")
      Object.values(c.scenario.events[0].values).forEach(
        (s: any) => (s.value = "3.5e38"),
      );
    if (fault === "sample-coercion")
      Object.values(c.scenario.events[0].values).forEach(
        (s: any) => (s.value = false),
      );
    if (fault === "boolean")
      c.scenario.events[2].values[c.scenario.inputs[1].id].value = "True";
    if (fault === "records")
      c.scenario.events = Array(2001).fill(c.scenario.events[0]);
    expect(() =>
      scenarioStartupProfile(c.scenario, time, c.baseline, c.original),
    ).toThrow();
  }
});
test("a future fault does not contaminate an earlier frame; all untouched output Enum and opaque records retain originals", () => {
  const c = source(),
    p = scenarioStartupProfile(c.scenario, 0.1, c.baseline, c.original);
  expect(p.entries[0].value).toBe("-0.0");
  expect(p.entries[2].value).toBe("0");
  for (const index of [1, 3, 4])
    expect(p.entries[index]).toEqual(c.baseline.entries[index]);
});
test("prepared profile must match the independently selected frame and every original record guard", () => {
  const c = source(),
    expected = scenarioStartupProfile(c.scenario, 0.3, c.baseline, c.original);
  for (const fault of [
    "input",
    "output",
    "Enum",
    "metadata",
    "source",
    "version",
    "missing",
    "duplicate",
  ]) {
    const p = structuredClone(expected);
    if (fault === "input") p.entries[0].value = "73.25";
    if (fault === "output") p.entries[1].value = "73.25";
    if (fault === "Enum") p.entries[3].value = "2";
    if (fault === "metadata") p.entries[0].class_id = "527";
    if (fault === "source") p.source_sha256 = "0".repeat(64);
    if (fault === "version") p.version = 2;
    if (fault === "missing") p.entries.pop();
    if (fault === "duplicate") p.entries[0] = structuredClone(p.entries[1]);
    expect(() => admitStartupProfile(p, expected, c.baseline)).toThrow();
  }
  const reversed = structuredClone(expected);
  reversed.entries.reverse();
  expect(admitStartupProfile(reversed, expected, c.baseline)).toEqual(expected);
});
test("shared copy verifier captures the original request, version and source before dispatch", async () => {
  const c = source(),
    p = scenarioStartupProfile(c.scenario, 0.3, c.baseline, c.original),
    body = new Blob(["independently authored output bytes"]);
  const headers = new Headers({
    "X-Studio-Source-Sha256": p.source_sha256,
    "X-Studio-Simulation-Version": "1",
    "X-Studio-Simulation-Request-Sha256": await simulationRequestSha256(p),
    "X-Studio-Artifact-Sha256": await sha256Blob(body),
  });
  const verify = await simulationCopyVerifier(p, p.source_sha256);
  await verify({ blob: body, headers });
  p.entries[0].value = "1";
  p.version = 2;
  await verify({ blob: body, headers });
  for (const field of [
    "X-Studio-Source-Sha256",
    "X-Studio-Simulation-Version",
    "X-Studio-Simulation-Request-Sha256",
    "X-Studio-Artifact-Sha256",
  ]) {
    const h = new Headers(headers);
    h.delete(field);
    await expect(verify({ blob: body, headers: h })).rejects.toThrow(
      "artifact digest",
    );
  }
  await expect(verify({ blob: new Blob(["other"]), headers })).rejects.toThrow(
    "artifact digest",
  );
  await expect(
    simulationCopyVerifier(c.baseline, "0".repeat(64)),
  ).rejects.toThrow("selected source");
});
