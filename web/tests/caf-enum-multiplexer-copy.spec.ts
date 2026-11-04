import { test, expect } from "./nativeScheduleWriteFixture";
import {
  kinds,
  enter,
  source,
  inspect,
  logic,
} from "./caf-enum-multiplexer-fixture";
import { savedCopy, type Family } from "./caf-open-copy-fixture";
import { chooseWorkspaceTask } from "./workspace-navigation";
const family: Family = {
  name: "Enum Multiplexer",
  kind: "multiplexer",
  primitive: true,
  source: () => source(),
};
for (const kind of kinds)
  test(`${kind} Enum Multiplexer exports exact typed bytes and continues from the copied block`, async ({
    page,
    request,
  }) => {
    let editor = await enter(page, kind);
    await expect(editor.locator("..").locator("summary").first()).toHaveText(
      "Copy a recorded Multiplexer",
    );
    await expect(editor).toContainText(
      "Enum inputs and output; Boolean selector.",
    );
    await editor
      .locator("details")
      .getByText("Recorded multiplexer ports", { exact: true })
      .click();
    if (kind === "two-no-text")
      await expect(editor).toContainText(
        "States Text code: omitted in source (encoding set omitted)",
      );
    else
      await expect(editor).toContainText(
        kind.startsWith("two")
          ? "States Text code: 418 (encoding set 802)"
          : "States Text code: 366 (encoding set 802)",
      );
    await editor.getByLabel("New block X", { exact: true }).fill("150");
    const proof = await savedCopy(page, family, editor);
    expect(proof.creation.selection.new_output_ref).toContain(".19_");
    expect(proof.creation.selection.enum_semantics_verified).toBe(false);
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

test("unfinished Enum Multiplexer coordinates survive task ABA while its review retires", async ({
  page,
}) => {
  let editor = await enter(page, "two-no-text");
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

test("compact Enum Multiplexer retains one primary action and explicit metadata omissions", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const editor = await enter(page, "two-no-text");
  await savedCopy(page, family, editor);
  await expect(editor.locator("button.primary:visible")).toHaveCount(1);
  expect(
    (await editor
      .getByRole("button", { name: "Open CAF copy", exact: true })
      .boundingBox())!.height,
  ).toBeGreaterThanOrEqual(36);
  expect((await editor.boundingBox())!.width).toBeLessThan(391);
});
