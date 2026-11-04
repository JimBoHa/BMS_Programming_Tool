import { test, expect } from "./nativeScheduleWriteFixture";
import {
  enter as enterMixed,
  source,
} from "./caf-enum-selector-multiplexer-fixture";
import {
  families,
  inspectFamily,
  savedCopy,
  logic,
} from "./caf-open-copy-fixture";

for (const change of ["source ABA", "kind ABA"])
  test(`${change} prevents a late native upload from replacing current work`, async ({
    page,
  }) => {
    const family = families[11];
    let editor = await enterMixed(page, "mixed");
    await editor.getByLabel("New block X", { exact: true }).fill("170");
    await savedCopy(page, family, editor);
    let release!: () => void, started!: () => void;
    const held = new Promise<void>((r) => (release = r)),
      entered = new Promise<void>((r) => (started = r));
    let first = true;
    await page.route("**/api/caf", async (route) => {
      if (route.request().method() === "POST" && first) {
        first = false;
        started();
        await held;
      }
      await route.continue();
    });
    const uploading = page.waitForRequest(
      (r) => new URL(r.url()).pathname === "/api/caf" && r.method() === "POST",
    );
    await editor
      .getByRole("button", { name: "Open CAF copy", exact: true })
      .click();
    const originalRequest = await uploading;
    const returned = page.waitForResponse(
      (r) => r.request() === originalRequest,
    );
    await entered;
    if (change === "source ABA") {
      for (const [name, buffer] of [
        ["other.caf", families[0].source()],
        ["original.caf", source("mixed")],
      ] as const) {
        await page
          .getByLabel("Open local CAF application", { exact: true })
          .setInputFiles({
            name,
            mimeType: "application/octet-stream",
            buffer,
          });
        await expect(
          page.getByLabel("Current CAF archive", { exact: true }),
        ).toHaveText(name);
      }
    } else if (change === "kind ABA") {
      await page
        .getByLabel("Recorded block type", { exact: true })
        .selectOption("boolean");
      await page
        .getByLabel("Recorded block type", { exact: true })
        .selectOption("multiplexer");
    }
    release();
    // Each replacement uses the original native browser request; no multipart replay.
    const response = await returned;
    expect(response.status()).toBe(200);
    expect(await response.finished()).toBeNull();
    await page.unroute("**/api/caf");
    await expect(
      page.getByLabel("Current CAF archive", { exact: true }),
    ).toHaveText(
      change === "source ABA" ? "original.caf" : "enum-selector.caf",
    );
    await logic(page);
    editor = await inspectFamily(page, family);
    await expect(editor.getByLabel("New block X", { exact: true })).toHaveValue(
      "170",
    );
    await expect(
      editor.getByRole("button", { name: "Open CAF copy", exact: true }),
    ).toHaveCount(0);
    await savedCopy(page, family, editor);
  });

test("prototype ABA retires a saved artifact before Open and retains its raw draft", async ({
  page,
}) => {
  const family = families[11];
  let editor = await enterMixed(page, "mixed");
  await editor.getByLabel("New block X", { exact: true }).fill("170");
  await savedCopy(page, family, editor);
  let uploads = 0;
  page.on("request", (r) => {
    if (new URL(r.url()).pathname === "/api/caf" && r.method() === "POST")
      uploads++;
  });
  await editor
    .getByLabel("Block prototype", { exact: true })
    .selectOption("8-1/575_1.562_130");
  await inspectFamily(page, family);
  await editor
    .getByLabel("Block prototype", { exact: true })
    .selectOption("8-1/575_1.562_140");
  editor = await inspectFamily(page, family);
  await expect(
    editor.getByRole("button", { name: "Open CAF copy", exact: true }),
  ).toHaveCount(0);
  await expect(editor.getByLabel("New block X", { exact: true })).toHaveValue(
    "170",
  );
  expect(uploads).toBe(0);
  await savedCopy(page, family, editor);
  page.once("dialog", async (dialog) => {
    expect(dialog.message()).toContain(
      "Other unexported CAF edits will be cleared",
    );
    await dialog.accept();
  });
  await editor
    .getByRole("button", { name: "Open CAF copy", exact: true })
    .click();
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("enum-selector-float-multiplexer-copy.caf");
  expect(uploads).toBe(1);
});
