import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { seedTerminalLabels } from "./native-terminal-label-fixture";
import {
  terminalBase,
  terminalSource,
  terminalReview,
} from "../src/nativeEncodedTerminalContract";
import { terminalSource as legacySource } from "../src/nativeTerminalCopyContract";
import { connectionSeal } from "../src/nativeConnectionContract";

let fixture: any;
const data = (basis: "archive" | "effective") =>
  structuredClone(
    (fixture ??= seedTerminalLabels(
      mkdtempSync(path.join(tmpdir(), "bms-terminal-labels-")),
    ))[basis],
  );
for (const basis of ["archive", "effective"] as const) {
  for (const fault of ["truncated", "duplicate", "array"] as const)
    test(`${basis} refuses ${fault} raw review document`, async () => {
      const f = data(basis),
        text =
          fault === "truncated"
            ? f.text.slice(0, -1)
            : fault === "array"
              ? "[]"
              : f.text.replace("{", '{"profile":"duplicate",');
      expect(
        await terminalReview(
          { data: f.review, blob: new Blob([text]) },
          f.archive,
          f.proposal,
          f.source,
          basis,
        ),
      ).toBe(false);
    });
  test(`${basis} UCS-2 source and exact original/nested document seals pass`, async () => {
    const f = data(basis);
    expect(terminalBase(basis)).toContain("/inputs/encoded-labels/");
    expect(terminalSource(f.source, f.archive, basis)).toBe(true);
    expect(legacySource(f.source, f.archive, basis)).toBe(false);
    for (const text of [f.text, f.numeric])
      expect(
        await terminalReview(
          { data: JSON.parse(text), blob: new Blob([text]) },
          f.archive,
          f.proposal,
          f.source,
          basis,
        ),
      ).toBe(true);
    const roundTrip = JSON.stringify(JSON.parse(f.numeric));
    expect(
      await terminalReview(
        { data: JSON.parse(roundTrip), blob: new Blob([roundTrip]) },
        f.archive,
        f.proposal,
        f.source,
        basis,
      ),
    ).toBe(false);
  });
  for (const [name, value] of Object.entries({
    missing: undefined,
    bool: true,
    string: "4",
    unsupported: 3,
    latin1: 5,
    nul: null,
  }))
    test(`${basis} source refuses ${name} charset evidence`, () => {
      const f = data(basis),
        p = f.source.inventory.inputs.find((p: any) => p.movable);
      p.device_type_character_encoding = value;
      expect(terminalSource(f.source, f.archive, basis)).toBe(false);
    });
  for (const fault of [
    "converted",
    "encoding",
    "preserved",
    "inner-seal",
    "blob-binding",
    "outer-version",
  ] as const)
    test(`${basis} review refuses ${fault} even with an outer seal`, async () => {
      const f = data(basis),
        v = f.review,
        edit =
          basis === "effective" ? v.compilation.terminal_edit : v.compilation;
      if (fault === "converted") edit.payloads[1].after = "00554920494e33";
      if (fault === "encoding") edit.device_type_character_encoding = 0;
      if (fault === "preserved") edit.device_type_encoding_preserved = false;
      if (fault === "inner-seal") edit.compilation_sha256 = "0".repeat(64);
      if (fault === "outer-version") v.profile = v.profile.replace("/2", "/1");
      if (fault === "blob-binding") v.output_sha256 = "0".repeat(64);
      const { review_sha256, ...body } = v;
      v.review_sha256 = await connectionSeal(body);
      const blob = new Blob([
        fault === "blob-binding" ? f.text : JSON.stringify(v),
      ]);
      expect(
        await terminalReview(
          { data: v, blob },
          f.archive,
          f.proposal,
          f.source,
          basis,
        ),
      ).toBe(false);
    });
}
