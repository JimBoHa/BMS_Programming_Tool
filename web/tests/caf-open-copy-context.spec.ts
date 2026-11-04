import { test, expect } from "./nativeScheduleWriteFixture";
import {
  families,
  enterFamily,
  inspectFamily,
  savedCopy,
  python,
  logic,
} from "./caf-open-copy-fixture";
import { enter as enterMixed } from "./caf-enum-selector-multiplexer-fixture";

test("mixed diagrams retain the copied kind and new prototype instead of the first kind", async ({
  page,
}) => {
  const family = families[11],
    editor = await enterMixed(page, "mixed");
  const proof = await savedCopy(page, family, editor);
  await editor
    .getByRole("button", { name: "Open CAF copy", exact: true })
    .click();
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("enum-selector-float-multiplexer-copy.caf");
  await expect(
    page.getByLabel("Recorded block type", { exact: true }),
  ).toHaveValue("multiplexer");
  const next = await inspectFamily(page, family);
  await expect(next.getByLabel("Block prototype", { exact: true })).toHaveValue(
    proof.creation.selection.new_ref,
  );
});

test("a copied nested diagram stays selected after the proven file opens", async ({
  page,
}) => {
  const nested = "source/536_9.575_1";
  const buffer = python(`
import sys
from tests.test_caf_constant_copy import example,packed,prop,record,shorts,REF
from bms_tool.caf import CafArchive
from bms_tool.caf_graph import CafGraph
xml=CafArchive(example(zero=True)).xml.decode().replace(REF,'source/536_9.575_1')
root='<object classid="536" classVersion="1.0" ref="source/536_9" objectid="9">'
root+=prop(3375,'<array><BACoid id="575">1</BACoid></array>')+prop(3117,'<array>'+shorts(0)+'</array>')
root+=prop(3383,'<listof>'+record('<float>0</float>','<float>0</float>','<unsignedShort>12</unsignedShort>')+'</listof>')
root+=prop(3118,'<array />')+prop(3384,'<listof />')+prop(3373,'<boolean>true</boolean>')+'</object>'
xml=xml.replace('<object classid="575"',root+'<object classid="575"',1)
xml=xml.replace('ref="source/536_9.575_1" objectid="1">','ref="source/536_9.575_1" objectid="1">'+prop(75,'<BACoid id="575">1</BACoid>'),1)
data=packed(xml,zero=True);g=CafGraph(data)
assert g.diagrams()['diagrams'][0]['ref']=='source/536_9'
assert len(g.diagram('source/536_9.575_1')['blocks'])==3
sys.stdout.buffer.write(data)
`);
  await page.goto("/");
  await page
    .getByLabel("Open local CAF application", { exact: true })
    .setInputFiles({
      name: "nested.caf",
      mimeType: "application/octet-stream",
      buffer,
    });
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("nested.caf");
  await logic(page);
  await page
    .getByLabel("Native CAF diagram", { exact: true })
    .selectOption(nested);
  const editor = await inspectFamily(page, families[0]);
  const proof = await savedCopy(page);
  await editor
    .getByRole("button", { name: "Open CAF copy", exact: true })
    .click();
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("nested-constant-copy.caf");
  await expect(
    page.getByLabel("Native CAF diagram", { exact: true }),
  ).toHaveValue(nested);
  const next = await inspectFamily(page, families[0]);
  await expect(
    next.getByLabel("Constant prototype", { exact: true }),
  ).toHaveValue(proof.creation.selection.new_ref);
});

test("copy B keeps an unfinished raw creation draft when original A is reopened", async ({
  page,
}) => {
  let editor = await enterFamily(page);
  const proof = await savedCopy(page);
  const copy = python(
    `from tests.test_caf_constant_copy import example;from bms_tool.caf_constant_copy import CafConstantCopies;import sys,json;c=CafConstantCopies(example(zero=True));q=json.loads(sys.argv[1]);q.pop('source_sha256');sys.stdout.buffer.write(c.compile(**q)[0])`,
    JSON.stringify(proof.request),
  );
  await editor
    .getByRole("button", { name: "Open CAF copy", exact: true })
    .click();
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("authored-constant-copy.caf");
  await logic(page);
  editor = await inspectFamily(page, families[0]);
  await editor.getByLabel("New constant X", { exact: true }).fill("-");
  page.on("dialog", (d) => d.accept());
  await page
    .getByLabel("Open local CAF application", { exact: true })
    .setInputFiles({
      name: "original.caf",
      mimeType: "application/octet-stream",
      buffer: families[0].source(),
    });
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("original.caf");
  await logic(page);
  editor = await inspectFamily(page, families[0]);
  await editor.getByLabel("New constant X", { exact: true }).fill(".");
  await page
    .getByLabel("Open local CAF application", { exact: true })
    .setInputFiles({
      name: "copy.caf",
      mimeType: "application/octet-stream",
      buffer: copy,
    });
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("copy.caf");
  await logic(page);
  editor = await inspectFamily(page, families[0]);
  await expect(
    editor.getByLabel("New constant X", { exact: true }),
  ).toHaveValue("-");
  await page
    .getByLabel("Open local CAF application", { exact: true })
    .setInputFiles({
      name: "again.caf",
      mimeType: "application/octet-stream",
      buffer: families[0].source(),
    });
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("again.caf");
  await logic(page);
  editor = await inspectFamily(page, families[0]);
  await expect(
    editor.getByLabel("New constant X", { exact: true }),
  ).toHaveValue(".");
});

test("cancel keeps other pending edits and accepted handoff clears them explicitly", async ({
  page,
}) => {
  let editor = await enterFamily(page);
  const objects = page
    .getByRole("navigation", { name: "CAF application tasks", exact: true })
    .getByRole("button", { name: "Objects & parameters", exact: true });
  await objects.click();
  await page
    .locator(".caf-layout tbody tr")
    .filter({ hasText: "8-1/575_1.551_10.2_11" })
    .click();
  await page.getByLabel("CAF property 3113", { exact: true }).fill("42");
  await logic(page);
  await logic(page);
  editor = await inspectFamily(page, families[0]);
  await savedCopy(page);
  let uploads = 0;
  page.on("request", (r) => {
    if (new URL(r.url()).pathname === "/api/caf" && r.method() === "POST")
      uploads++;
  });
  page.once("dialog", async (d) => {
    expect(d.message()).toContain("Other unexported CAF edits will be cleared");
    await d.dismiss();
  });
  await editor
    .getByRole("button", { name: "Open CAF copy", exact: true })
    .click();
  await expect(
    editor.getByRole("button", { name: "Open CAF copy", exact: true }),
  ).toBeEnabled();
  expect(uploads).toBe(0);
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("authored.caf");
  await objects.click();
  await expect(
    page.getByLabel("CAF property 3113", { exact: true }),
  ).toHaveValue("42");
  await logic(page);
  await logic(page);
  editor = await inspectFamily(page, families[0]);
  await savedCopy(page);
  page.once("dialog", async (d) => {
    expect(d.message()).toContain("Other unexported CAF edits will be cleared");
    await d.accept();
  });
  await editor
    .getByRole("button", { name: "Open CAF copy", exact: true })
    .click();
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("authored-constant-copy.caf");
  expect(uploads).toBe(1);
  await objects.click();
  await expect(
    page.getByRole("region", { name: "CAF archive summary", exact: true }),
  ).toContainText("LOCAL EDITS0");
  await page
    .locator(".caf-layout tbody tr")
    .filter({ hasText: "8-1/575_1.551_10.2_11" })
    .click();
  await expect(
    page.getByLabel("CAF property 3113", { exact: true }),
  ).toHaveValue("1.000000");
});
