import { test, expect } from "./nativeScheduleWriteFixture";
import {
  enter,
  inspect,
  prepare,
} from "./caf-enum-selector-multiplexer-fixture";

test("open proven CAF copy retains the graph task, new prototype and one primary action", async ({
  page,
}) => {
  let editor = await enter(page);
  let proof: any;
  await page.route("**/float-multiplexer-copy/preview", async (route) => {
    const response = await route.fetch({ maxRetries: 0 });
    const bytes = await response.body();
    proof = JSON.parse(bytes.toString());
    await route.fulfill({ response });
  });
  let reviewed = await prepare(page);
  const downloading = page.waitForEvent("download");
  await reviewed
    .getByRole("button", { name: "Save block CAF copy", exact: true })
    .click();
  await downloading;
  const open = editor.getByRole("button", {
    name: "Open CAF copy",
    exact: true,
  });
  await expect(open).toBeVisible();
  await expect(editor.locator("button.primary:visible")).toHaveCount(1);
  await expect(open).toHaveClass(/primary/);
  const uploaded = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/caf" &&
      response.request().method() === "POST",
  );
  const dialogs: string[] = [];
  page.on("dialog", (dialog) => {
    dialogs.push(dialog.message());
    void dialog.dismiss();
  });
  await open.click();
  expect(dialogs).toEqual([]);
  expect((await uploaded).status()).toBe(200);
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("enum-selector-float-multiplexer-copy.caf");
  await expect(
    page
      .getByRole("region", { name: "Native CAF graph", exact: true })
      .locator(".react-flow__node"),
  ).toHaveCount(4);
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
  reviewed = await prepare(page);
  await expect(reviewed).toContainText(
    "One graph member and seven objects added",
  );
});
