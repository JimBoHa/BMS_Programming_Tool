import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import {
  engineeringInventory,
  engineeringReport,
} from "../src/jciEngineeringContract";
import { connectionSeal } from "../src/nativeConnectionContract";
import {
  digest,
  engineeringSource,
  reportFor,
} from "./jci-engineering-fixture";

async function document(value: any, source: Buffer, name = "authored.caf") {
  const raw = JSON.stringify(value),
    blob = new Blob([raw]);
  return {
    doc: {
      data: value,
      blob,
      headers: new Headers({
        "X-BMS-Report-SHA256": digest(raw),
        "X-BMS-Source-SHA256": digest(source),
      }),
    },
    file: new File([source], name),
    expected: digest(source),
  };
}
test("inventory preserves 48 distinct parents and rejects an invented native capability", () => {
  const catalog = JSON.parse(
    readFileSync(
      "../backend/bms_tool/data/jciEngineeringInventory.json",
      "utf8",
    ),
  );
  expect(engineeringInventory(catalog)).toBe(true);
  expect(new Set(catalog.packages.map((r: any) => r.id)).size).toBe(48);
  const changed = structuredClone(catalog);
  changed.native_sct_archive_decoded = true;
  expect(engineeringInventory(changed)).toBe(false);
  changed.native_sct_archive_decoded = false;
  changed.packages[0].status = "complete";
  expect(engineeringInventory(changed)).toBe(false);
  const foreign = structuredClone(catalog);
  foreign.manual_sources[0].url = "javascript:alert(1)";
  expect(engineeringInventory(foreign)).toBe(false);
});
for (const kind of ["caf", "moi", "moz", "partial", "program"])
  test(
    "actual backend " +
      kind +
      " evidence admits only the matching source bytes",
    async () => {
      const source = engineeringSource(kind),
        name =
          "authored." +
          (kind === "caf" ? "caf" : kind === "program" ? "json" : "moi");
      const value = JSON.parse(reportFor(name, kind).toString()),
        d = await document(value, source, name);
      expect(await engineeringReport(d.doc, d.file, d.expected)).toBe(true);
      expect(
        await engineeringReport(
          d.doc,
          new File([Buffer.from("different")], name),
          digest("different"),
        ),
      ).toBe(false);
    },
  );
for (const fault of [
  "future",
  "source-hash",
  "source-name",
  "field-action",
  "native-support",
  "apply",
  "coverage",
  "extra-root",
  "unknown-reader",
  "operation-claim",
  "summary-claim",
  "summary-count",
  "class-coverage",
  "class-total",
  "class-duplicate",
  "trailing-seal",
  "header",
  "blob",
])
  test(
    "resealed malformed " + fault + " report grants no accepted projection",
    async () => {
      const source = engineeringSource(),
        value = JSON.parse(reportFor().toString());
      if (fault === "future")
        value.profile = "jci-engineering-source-inspection/2";
      if (fault === "source-hash") value.source.sha256 = "a".repeat(64);
      if (fault === "source-name") value.source.name = "another.caf";
      if (fault === "field-action") value.field_actions = true;
      if (fault === "native-support") value.native_sct_archive_decoded = true;
      if (fault === "apply") value.apply_authority = true;
      if (fault === "coverage") value.coverage.complete_native_semantics = true;
      if (fault === "extra-root") value.new_native_capability = true;
      if (fault === "unknown-reader")
        value.detected.reader_profile = "native-sct-archive/1";
      if (fault === "operation-claim")
        value.operations[3].status = "available-local";
      if (fault === "summary-claim")
        value.summary.complete_native_schema = true;
      if (fault === "summary-count") value.summary.objects = -1;
      if (fault === "class-coverage") value.summary.unrepresented_class_ids = 1;
      if (fault === "class-total") value.summary.classes[0].objects = 3;
      if (fault === "class-duplicate")
        value.summary.classes[1].id = value.summary.classes[0].id;
      const { report_sha256: omitted, ...body } = value;
      void omitted;
      value.report_sha256 = await connectionSeal(body);
      if (fault === "trailing-seal") value.report_sha256 += "\n";
      const d = await document(value, source);
      if (fault === "header")
        d.doc.headers.set("X-BMS-Report-SHA256", "b".repeat(64));
      if (fault === "blob") d.doc.blob = new Blob(["changed exact response"]);
      expect(await engineeringReport(d.doc, d.file, d.expected)).toBe(false);
    },
  );
test("a resealed portable revision with a trailing newline is refused", async () => {
  const source = engineeringSource("program"),
    name = "graph.json";
  const value = JSON.parse(reportFor(name, "program").toString());
  value.summary.revision_text += "\n";
  const { report_sha256: omitted, ...body } = value;
  void omitted;
  value.report_sha256 = await connectionSeal(body);
  const d = await document(value, source, name);
  expect(await engineeringReport(d.doc, d.file, d.expected)).toBe(false);
});
