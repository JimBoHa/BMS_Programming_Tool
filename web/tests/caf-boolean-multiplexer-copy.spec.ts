import { test, expect } from "./nativeScheduleWriteFixture";
import { readFileSync } from "node:fs";
import {
  enter,
  source,
  inspect,
  logic,
  sourceForms,
  python,
} from "./caf-boolean-multiplexer-fixture";
import { savedCopy, type Family } from "./caf-open-copy-fixture";
import { chooseWorkspaceTask } from "./workspace-navigation";
const family: Family = {
  name: "Boolean Multiplexer",
  kind: "multiplexer",
  primitive: true,
  source: () => source(),
};
for (const kind of sourceForms)
  test(`${kind} Boolean-output copy preserves actual bytes and opens its new typed prototype`, async ({
    page,
    request,
  }) => {
    let editor = await enter(page, kind);
    const enumeration = kind !== "boolean",
      expectedValue = enumeration ? kind.split(":")[1] : null;
    await expect(editor).toContainText(
      `Boolean inputs and output; ${enumeration ? "Enum" : "Boolean"} selector.`,
    );
    await editor
      .getByText("Recorded multiplexer ports", { exact: true })
      .click();
    await expect(
      editor.locator("p").filter({ hasText: "input port 7001:" }),
    ).toContainText(
      expectedValue === null
        ? "default omitted in source"
        : `recorded default ${expectedValue};`,
    );
    await expect(
      editor.locator("p").filter({ hasText: "output port 85:" }),
    ).not.toContainText("Number Of States");
    if (enumeration)
      await expect(
        editor.locator("p").filter({ hasText: "input port 961:" }),
      ).toContainText(
        `Number Of States: ${kind.startsWith("enum-two") ? 2 : 5}. States Text code: ${kind.startsWith("enum-two") ? 350 : kind.startsWith("enum-five-a") ? 1347 : 359}`,
      );
    await editor.getByLabel("New block X", { exact: true }).fill("170");
    const downloading = page.waitForEvent("download"),
      proof = await savedCopy(page, family, editor),
      download = await downloading;
    expect(download.suggestedFilename()).toBe(
      "boolean-multiplexer-boolean-multiplexer-copy.caf",
    );
    expect(
      proof.creation.selection.children.map((r: any) => r.bacnet_type),
    ).toEqual([5, enumeration ? 19 : 5, 5, 5]);
    const file = (await download.path())!;
    expect(readFileSync(file).length).toBeGreaterThan(0);
    const artifact = JSON.parse(
      python(
        "from pathlib import Path;import sys,json;from bms_tool.caf import CafArchive;a=CafArchive(Path(sys.argv[1]).read_bytes());p=sys.argv[2];children=[r for r in a.objects if r.startswith(p+'.')];print(json.dumps({'hash':a.hash,'children':children,'defaults':[next((v['scalar'] for v in a.properties(r) if v['id']=='3113'),None) for r in children],'external_attr':a.info.external_attr}))",
        file,
        proof.creation.selection.new_ref,
      ).toString(),
    );
    expect(artifact).toEqual({
      hash: proof.creation.output_sha256,
      children: proof.creation.selection.children.map((r: any) => r.new_ref),
      defaults: [
        null,
        null,
        null,
        expectedValue === null
          ? null
          : { type: "boolean", text: expectedValue, attributes: {} },
      ],
      external_attr: 0,
    });
    await expect(editor.locator("button.primary:visible")).toHaveCount(1);
    await editor
      .getByRole("button", { name: "Open CAF copy", exact: true })
      .click();
    await expect(
      page.getByLabel("Current CAF archive", { exact: true }),
    ).toHaveText("boolean-multiplexer-boolean-multiplexer-copy.caf");
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
test("unfinished Boolean-output coordinates survive task ABA while saved Open authority retires", async ({
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
for (const kind of ["boolean", "enum-five-b:false"])
  test(`${kind} compact authoring keeps one primary action and bounded controls`, async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const editor = await enter(page, kind);
    await savedCopy(page, family, editor);
    await expect(editor.locator("button.primary:visible")).toHaveCount(1);
    expect(
      (await editor
        .getByRole("button", { name: "Open CAF copy", exact: true })
        .boundingBox())!.height,
    ).toBeGreaterThanOrEqual(36);
    expect((await editor.boundingBox())!.width).toBeLessThan(391);
  });
