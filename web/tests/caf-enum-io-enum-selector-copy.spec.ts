import { test, expect } from "./nativeScheduleWriteFixture";
import {
  enter,
  source,
  inspect,
  logic,
} from "./caf-enum-io-enum-selector-fixture";
import { savedCopy, type Family } from "./caf-open-copy-fixture";
import { chooseWorkspaceTask } from "./workspace-navigation";
const family: Family = {
  name: "Enum I/O Enum-selector Multiplexer",
  kind: "multiplexer",
  primitive: true,
  source: () => source(),
};

test("Enum I/O with Enum selector exports typed bytes and continues from its new actual block", async ({
  page,
  request,
}) => {
  let editor = await enter(page);
  await expect(editor).toContainText("Enum inputs and output; Enum selector.");
  await editor
    .locator("details")
    .getByText("Recorded multiplexer ports", { exact: true })
    .click();
  await expect(
    editor.locator("p").filter({ hasText: "input port 961:" }),
  ).toContainText("Number Of States: 4. States Text code: 345");
  await expect(
    editor.locator("p").filter({ hasText: "output port 85:" }),
  ).toContainText("Number Of States: 2. States Text code: 418");
  await editor.getByLabel("New block X", { exact: true }).fill("170");
  const proof = await savedCopy(page, family, editor);
  expect(
    proof.creation.selection.children.map((r: any) => r.bacnet_type),
  ).toEqual([19, 19, 19, 19]);
  expect(proof.creation.selection.recorded_property_2381).toEqual([
    "0",
    "1",
    "0",
    "0",
  ]);
  await expect(editor.locator("button.primary:visible")).toHaveCount(1);
  await editor
    .getByRole("button", { name: "Open CAF copy", exact: true })
    .click();
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("enum-multiplexer-enum-multiplexer-copy.caf");
  const graph = await request.get(
    `/api/caf/${proof.creation.output_sha256}/graph?ref=${encodeURIComponent(proof.request.diagram_ref)}`,
  );
  expect(graph.status()).toBe(200);
  expect(
    (await graph.json()).blocks.some(
      (b: any) => b.ref === proof.creation.selection.new_ref,
    ),
  ).toBe(true);
  editor = await inspect(page);
  await expect(
    editor.getByLabel("Block prototype", { exact: true }),
  ).toHaveValue(proof.creation.selection.new_ref);
  await expect(
    editor.getByRole("region", {
      name: "Reviewed CAF block copy",
      exact: true,
    }),
  ).toHaveCount(0);
  await savedCopy(page, family, editor);
});

test("unfinished Enum-selector coordinates survive task ABA while saved Open authority retires", async ({
  page,
}) => {
  let editor = await enter(page);
  await editor.getByLabel("New block X", { exact: true }).fill("-");
  await chooseWorkspaceTask(page, "Overview");
  await logic(page);
  editor = await inspect(page);
  await expect(editor.getByLabel("New block X", { exact: true })).toHaveValue(
    "-",
  );
  await expect(
    editor.getByRole("button", { name: "Review block CAF copy", exact: true }),
  ).toBeDisabled();
  await editor.getByLabel("New block X", { exact: true }).fill("180");
  await savedCopy(page, family, editor);
  await chooseWorkspaceTask(page, "Overview");
  await logic(page);
  editor = await inspect(page);
  await expect(editor.getByLabel("New block X", { exact: true })).toHaveValue(
    "180",
  );
  await expect(
    editor.getByRole("button", { name: "Open CAF copy", exact: true }),
  ).toHaveCount(0);
});

test("compact Enum-selector authoring keeps one primary action and bounded controls", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const editor = await enter(page);
  await savedCopy(page, family, editor);
  await expect(editor.locator("button.primary:visible")).toHaveCount(1);
  expect(
    (await editor
      .getByRole("button", { name: "Open CAF copy", exact: true })
      .boundingBox())!.height,
  ).toBeGreaterThanOrEqual(36);
  expect((await editor.boundingBox())!.width).toBeLessThan(391);
});
