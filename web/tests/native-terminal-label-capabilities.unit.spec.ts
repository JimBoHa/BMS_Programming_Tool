import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { seedLabelCapabilities } from "./native-terminal-label-capability-fixture";
import { terminalCapabilityEvidence } from "../src/nativeEncodedTerminalCapabilityContract";
import { terminalCapabilityEvidence as legacyEvidence } from "../src/nativeTerminalCapabilityContract";
let fixture: any;
const data = () =>
  (fixture ??= seedLabelCapabilities(
    mkdtempSync(path.join(tmpdir(), "bms-label-capability-")),
  ));
for (const kind of [
  "ucs2",
  "unknown",
  "unverified",
  "output",
  "serial",
  "ascii",
])
  test(`${kind} source admits actual encoded capability witnesses and independent old evidence`, () => {
    const f = data()[kind];
    expect(terminalCapabilityEvidence(f.report, f.archive)).toBe(true);
    expect(legacyEvidence(f.report, f.archive)).toBe(false);
  });
for (const fault of [
  "charset",
  "bool",
  "missing",
  "preserved",
  "compiler",
  "guard",
  "authority",
  "error",
  "legacy",
  "row",
  "status",
  "root",
] as const)
  test(`encoded terminal capability rejects ${fault}`, () => {
    const f = data().ucs2,
      r = structuredClone(f.report),
      w = r.qualification.encoded_archive_terminal;
    if (fault === "charset") w.device_type_character_encoding = 3;
    if (fault === "bool") w.device_type_character_encoding = true;
    if (fault === "missing") delete w.device_type_character_encoding;
    if (fault === "preserved") w.device_type_encoding_preserved = false;
    if (fault === "compiler")
      w.compiler_profile = "tagged-moi-local-terminal-copy/1";
    if (fault === "guard") w.device_type_property_sha256 = "bad";
    if (fault === "authority") w.field_transfer_enabled = true;
    if (fault === "error")
      r.qualification.encoded_archive_terminal_error = "Contradiction";
    if (fault === "legacy") r.qualification.archive_terminal_error = null;
    if (fault === "row") r.operations.push(r.operations.at(-1));
    if (fault === "status") r.operations.at(-1).status = "preflight-required";
    if (fault === "root") r.qualification.native_identity.root_ref = undefined;
    expect(terminalCapabilityEvidence(r, f.archive)).toBe(false);
  });
