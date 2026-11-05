import { test, expect } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fieldDocuments } from "./native-terminal-field-fixture";
import {
  terminalDocumentSeal,
  terminalTransferReview,
  inputTransferProfile,
} from "../src/nativeTerminalTransferContract";

let fixture: any;
const data = () => {
  fixture ??= fieldDocuments(
    mkdtempSync(path.join(tmpdir(), "bms-terminal-field-contract-")),
  );
  return fixture;
};
for (const field of [false, true]) {
  test(`${field ? "field" : "local"} exact actual review and preserved configuration pass`, async () => {
    const f = data(),
      text = field ? f.field_text : f.local_text;
    expect(await terminalDocumentSeal(new Blob([text]), field)).toBe(true);
    expect(
      await terminalTransferReview(
        { data: JSON.parse(text), blob: new Blob([text]) },
        f.source,
        f.edit,
        field,
      ),
    ).toBe(true);
  });
  for (const [name, change] of Object.entries({
    version: (v: any) => {
      if (field)
        v.operation_profile = "native-local-universal-input-transfer/1";
      else v.profile = "native-local-universal-input-transfer/1";
    },
    slot: (v: any) => (v.compilation.terminal_compilation.destination_slot = 2),
    mode: (v: any) => (v.compilation.stored_configuration.setup = 9),
    scaling: (v: any) => (v.compilation.stored_configuration.input_high = 5),
    root: (v: any) => (v.target.address = "127.0.0.2:47819"),
    snapshot: (v: any) => (v.snapshot_sha256 = "0".repeat(64)),
    compiler: (v: any) => (v.compilation.profile = "other/2"),
    source: (v: any) =>
      (v.compilation.terminal_compilation.source_sha256 = "0".repeat(64)),
    label: (v: any) =>
      (v.compilation.terminal_compilation.new_device_type = "BI IN3"),
    overlap: (v: any) =>
      (v.compilation.terminal_compilation.payloads[1].offset =
        v.compilation.terminal_compilation.payloads[0].offset),
    seal: (v: any) => (v.review_sha256 = "0".repeat(64)),
  })) {
    test(`${field ? "field" : "local"} review rejects ${name}`, async () => {
      const f = data(),
        v = JSON.parse(field ? f.field_text : f.local_text);
      change(v);
      expect(
        await terminalTransferReview(
          { data: v, blob: new Blob([JSON.stringify(v)]) },
          f.source,
          f.edit,
          field,
        ),
      ).toBe(false);
    });
  }
}
test("exact seal retains floats, negative zero, large integers, Unicode and numeric key sorting", async () => {
  const f = data();
  expect(await terminalDocumentSeal(new Blob([f.exact_text]), false)).toBe(
    true,
  );
  expect(
    await terminalDocumentSeal(
      new Blob([JSON.stringify(JSON.parse(f.exact_text))]),
      false,
    ),
  ).toBe(false);
});
test("only terminal actions select profile two", () => {
  expect(inputTransferProfile({ action: "terminal" })).toBe(
    "native-local-universal-input-transfer/2",
  );
  for (const action of ["allocate", "mode", "remove-allocated"])
    expect(inputTransferProfile({ action })).toBe(
      "native-local-universal-input-transfer/1",
    );
});
