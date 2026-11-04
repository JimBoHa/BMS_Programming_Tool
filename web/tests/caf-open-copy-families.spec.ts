import { test, expect } from "./nativeScheduleWriteFixture";
import {
  families,
  enterFamily,
  inspectFamily,
  savedCopy,
  editorFor,
} from "./caf-open-copy-fixture";
for (const family of families)
  test(`${family.name} opens exact reviewed bytes and selects its actual new prototype`, async ({
    page,
    request,
  }, info) => {
    const editor = await enterFamily(page, family),
      proof = await savedCopy(page, family, editor);
    await expect(editor.locator("button.primary:visible")).toHaveCount(1);
    await editor
      .getByRole("button", { name: "Open CAF copy", exact: true })
      .click();
    await expect(
      page.getByLabel("Current CAF archive", { exact: true }),
    ).not.toHaveText("authored.caf");
    const graph = await request.get(
      `/api/caf/${proof.creation.output_sha256}/graph?ref=${encodeURIComponent(proof.request.diagram_ref)}`,
    );
    expect(graph.status()).toBe(200);
    const actual = await graph.json();
    expect(
      actual.blocks.some(
        (b: any) => b.ref === proof.creation.selection.new_ref,
      ),
    ).toBe(true);
    const reopened = await inspectFamily(page, family),
      subject = family.primitive ? "block" : "constant";
    await expect(
      reopened.getByLabel(
        family.primitive ? "Block prototype" : "Constant prototype",
        { exact: true },
      ),
    ).toHaveValue(proof.creation.selection.new_ref);
    await expect(
      reopened.getByRole("region", {
        name: family.primitive
          ? "Reviewed CAF block copy"
          : "Reviewed CAF constant copy",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      reopened.getByRole("button", {
        name: `Review ${subject} CAF copy`,
        exact: true,
      }),
    ).toHaveClass(/primary/);
    await info.attach("native upload artifact identity", {
      body: Buffer.from(
        JSON.stringify({
          expected_archive: proof.creation.output_sha256,
          actual_block: proof.creation.selection.new_ref,
          field_writes: 0,
        }),
      ),
      contentType: "application/json",
    });
  });
