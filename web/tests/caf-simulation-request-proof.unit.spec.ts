import { test, expect } from "@playwright/test";
import { createHash } from "node:crypto";
import { simulationRequestSha256 } from "../src/cafSimulationProfile";
function vector(): any {
  return {
    format: "bms.caf-simulation-profile",
    version: 2,
    source_sha256: "a".repeat(64),
    entries: [
      { ref: 'é🙂/"\\', property_id: "3113", value: "\t\r\n/" },
      { ref: "opaque", property_id: "999", value: null },
      { ref: "input", property_id: "3113", value: "-0.0" },
    ],
  };
}
test("request hash matches independent literal compact UTF8 including supplementary Unicode, escapes and null", async () => {
  const literal =
    '{"entries":[{"property_id":"3113","ref":"é🙂/\\\"\\\\","value":"\\t\\r\\n/"},{"property_id":"999","ref":"opaque","value":null},{"property_id":"3113","ref":"input","value":"-0.0"}],"format":"bms.caf-simulation-profile","source_sha256":"' +
    "a".repeat(64) +
    '","version":2}';
  expect(JSON.parse(literal).entries).toEqual(vector().entries);
  expect(await simulationRequestSha256(vector())).toBe(
    createHash("sha256").update(literal, "utf8").digest("hex"),
  );
});
test("same source artifacts cannot share proposal identity across values, exact spelling, order or versions", async () => {
  const p = vector(),
    seen = new Set([await simulationRequestSha256(p)]);
  for (const mutate of [
    (p: any) => p.entries.reverse(),
    (p: any) => (p.version = 1),
    (p: any) => (p.source_sha256 = "b".repeat(64)),
    (p: any) => (p.entries[2].value = "0.0"),
    (p: any) => (p.entries[0].ref = 'é🙂/"\\'),
  ]) {
    const q = structuredClone(p);
    mutate(q);
    seen.add(await simulationRequestSha256(q));
  }
  expect(seen.size).toBe(6);
  for (const row of p.entries)
    row.display_metadata = "Not value or identity authority";
  expect(seen.has(await simulationRequestSha256(p))).toBe(true);
});
test("bounded typed descriptor rejects unknown versions, coercions, missing values, array records and lone surrogates", async () => {
  for (const mutate of [
    (p: any) => (p.format = "unknown"),
    (p: any) => (p.version = true),
    (p: any) => (p.version = "2"),
    (p: any) => (p.source_sha256 = "A".repeat(64)),
    (p: any) => (p.entries = {}),
    (p: any) => (p.entries[0] = []),
    (p: any) => (p.entries[0].ref = 3),
    (p: any) => (p.entries[0].property_id = null),
    (p: any) => (p.entries[0].value = false),
    (p: any) => delete p.entries[0].value,
    (p: any) => (p.entries[0].value = "\ud800"),
    (p: any) => (p.can_apply = true),
    (p: any) => (p.entries[0].value = "x".repeat(2 * 1024 * 1024)),
    (p: any) => (p.entries = Array(10001).fill(p.entries[0])),
  ]) {
    const p = vector();
    mutate(p);
    await expect(simulationRequestSha256(p)).rejects.toThrow();
  }
  const array = Object.assign([], { ...vector() });
  await expect(simulationRequestSha256(array as any)).rejects.toThrow();
});
test("raw invalid but valid-Unicode strings fingerprint unchanged without creating native admission", async () => {
  for (const raw of [
    "1e-",
    "On",
    "NaN",
    "01",
    "\u2028\u2029",
    "\u0000",
    "é🙂",
  ]) {
    const p = vector();
    p.entries[2].value = raw;
    expect(await simulationRequestSha256(p)).toMatch(/^[a-f0-9]{64}$/);
    expect(p.entries[2].value).toBe(raw);
  }
});
