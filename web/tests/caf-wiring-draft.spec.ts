import { test, expect } from "@playwright/test";
import { python } from "./caf-simulation-fixture";
import {
  checkpoint,
  openWiring,
  savedWiring,
} from "./caf-wiring-draft-fixture";
for (const width of [1440, 390])
  test(`${width} unfinished connection survives same-source reopening without restoring export success`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 });
    const f = await openWiring(page, "partial");
    await page
      .getByText("Add native connection between existing blocks", {
        exact: true,
      })
      .click();
    await page
      .getByLabel("Native new connection source", { exact: true })
      .selectOption("8-1/575_1.2_11");
    await checkpoint(page)
      .getByRole("button", {
        name: "Save unfinished wiring draft",
        exact: true,
      })
      .click();
    await expect(checkpoint(page).getByRole("status")).toContainText(
      "No CAF was exported",
    );
    let discardPrompt = "";
    page.once("dialog", (d) => {
      discardPrompt = d.message();
      return d.accept();
    });
    const choosing = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: "Open CAF", exact: true }).click();
    await (
      await choosing
    ).setFiles({
      name: "wiring-reopened.caf",
      mimeType: "application/octet-stream",
      buffer: Buffer.from(f.caf, "base64"),
    });
    await expect(
      page.getByLabel("Current CAF archive", { exact: true }),
    ).toHaveText("wiring-reopened.caf");
    expect(discardPrompt).toContain("Discard unexported CAF edits");
    await savedWiring(page);
    await expect(checkpoint(page)).toContainText("Saved checkpoint revision 1");
    await checkpoint(page)
      .getByRole("button", { name: "Restore saved wiring draft", exact: true })
      .click();
    await expect(
      page.getByLabel("Native new connection source", { exact: true }),
    ).toHaveValue("8-1/575_1.2_11");
    await expect(
      page.getByLabel("Native new connection destination", { exact: true }),
    ).toHaveValue("");
    await expect(
      checkpoint(page).getByRole("status").filter({
        hasText: "Export and compatibility checks remain required",
      }),
    ).toBeVisible();
    await page
      .getByLabel("Native new connection destination", { exact: true })
      .selectOption("8-1/575_1.2_13");
    const download = page.waitForEvent("download");
    await page
      .getByRole("button", {
        name: "Check and export new native CAF connection",
        exact: true,
      })
      .click();
    await download;
    if (width === 390) {
      await checkpoint(page).scrollIntoViewIfNeeded();
      await page.screenshot({
        path: test.info().outputPath("wiring-checkpoint-phone.png"),
      });
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
    }
  });
test("different current selections remain until explicit replacement or cancellation", async ({
  page,
}) => {
  await openWiring(page, "rewire", true);
  await page
    .getByText("Add native connection between existing blocks", { exact: true })
    .click();
  await page
    .getByLabel("Native new connection source", { exact: true })
    .selectOption("8-1/575_1.2_10");
  await checkpoint(page)
    .getByRole("button", { name: "Restore saved wiring draft", exact: true })
    .click();
  await expect(
    checkpoint(page).getByRole("region", {
      name: "Replace current wiring selections",
      exact: true,
    }),
  ).toBeVisible();
  await checkpoint(page)
    .getByRole("button", { name: "Keep current wiring draft", exact: true })
    .click();
  await expect(
    page.getByLabel("Native replacement source", { exact: true }),
  ).toHaveValue("");
  await checkpoint(page)
    .getByRole("button", { name: "Restore saved wiring draft", exact: true })
    .click();
  await checkpoint(page)
    .getByRole("button", { name: "Replace current wiring draft", exact: true })
    .click();
  await expect(
    page.getByLabel("Native replacement source", { exact: true }),
  ).toHaveValue("8-1/575_1.2_11");
});
test("held restore cannot revive after coalesced selection ABA", async ({
  page,
}) => {
  await openWiring(page, "rewire", true);
  let release!: () => void, arrived!: () => void;
  const held = new Promise<void>((r) => (release = r)),
    sent = new Promise<void>((r) => (arrived = r));
  await page.route("**/wiring-draft/restore", async (route) => {
    arrived();
    await held;
    await route.continue();
  });
  await checkpoint(page)
    .getByRole("button", { name: "Restore saved wiring draft", exact: true })
    .click();
  await sent;
  await page
    .getByLabel("Native replacement source", { exact: true })
    .evaluate((select) => {
      const s = select as HTMLSelectElement;
      s.value = "8-1/575_1.2_11";
      s.dispatchEvent(new Event("change", { bubbles: true }));
      s.value = "";
      s.dispatchEvent(new Event("change", { bubbles: true }));
    });
  const returned = page.waitForResponse((r) =>
    r.url().endsWith("/wiring-draft/restore"),
  );
  release();
  await returned;
  await expect(
    page.getByLabel("Native replacement source", { exact: true }),
  ).toHaveValue("");
  await expect(
    checkpoint(page).getByRole("region", {
      name: "Replace current wiring selections",
      exact: true,
    }),
  ).toHaveCount(0);
  await checkpoint(page)
    .getByRole("button", { name: "Restore saved wiring draft", exact: true })
    .click();
  await expect(
    page.getByLabel("Native replacement source", { exact: true }),
  ).toHaveValue("8-1/575_1.2_11");
});

test("corrupt checkpoint can be removed while current selections remain intact", async ({
  page,
}) => {
  await openWiring(page, "rewire", true);
  python(
    "from bms_tool.storage import Store;import sys;s=Store(sys.argv[1]);c=s.connect();c.execute('UPDATE caf_wiring_drafts SET sha256=?',('0'*64,));c.commit();c.close()",
    process.env.BMS_TEST_COMPILER_STATE!,
  );
  await checkpoint(page)
    .getByRole("button", { name: "Refresh saved wiring draft", exact: true })
    .click();
  await expect(checkpoint(page).getByRole("alert")).toContainText(
    "unavailable",
  );
  await page
    .getByLabel("Native replacement source", { exact: true })
    .selectOption("8-1/575_1.2_11");
  await checkpoint(page)
    .getByRole("button", { name: "Remove saved wiring draft", exact: true })
    .click();
  await expect(checkpoint(page).getByRole("status")).toContainText(
    "Current wiring selections are retained",
  );
  await expect(
    page.getByLabel("Native replacement source", { exact: true }),
  ).toHaveValue("8-1/575_1.2_11");
  await checkpoint(page)
    .getByRole("button", { name: "Save unfinished wiring draft", exact: true })
    .click();
  await expect(checkpoint(page)).toContainText("Saved checkpoint revision 1");
});

test("failed ordinary source replacement permanently retires held checkpoint restoration", async ({
  page,
}) => {
  await openWiring(page, "rewire", true);
  let release!: () => void, arrived!: () => void;
  const held = new Promise<void>((r) => (release = r)),
    sent = new Promise<void>((r) => (arrived = r));
  await page.route("**/wiring-draft/restore", async (route) => {
    arrived();
    await held;
    await route.continue();
  });
  await checkpoint(page)
    .getByRole("button", { name: "Restore saved wiring draft", exact: true })
    .click();
  await sent;
  const choosing = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Open CAF", exact: true }).click();
  const failed = page.waitForResponse(
    (r) =>
      new URL(r.url()).pathname === "/api/caf" &&
      r.request().method() === "POST",
  );
  await (
    await choosing
  ).setFiles({
    name: "invalid.caf",
    mimeType: "application/octet-stream",
    buffer: Buffer.from("not an archive"),
  });
  expect((await failed).status()).toBe(422);
  const returned = page.waitForResponse((r) =>
    r.url().endsWith("/wiring-draft/restore"),
  );
  release();
  await returned;
  await savedWiring(page);
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("wiring-original.caf");
  await expect(
    page.getByLabel("Native replacement source", { exact: true }),
  ).toHaveValue("");
  await expect(
    checkpoint(page).getByRole("region", {
      name: "Replace current wiring selections",
      exact: true,
    }),
  ).toHaveCount(0);
  await expect(
    checkpoint(page).getByRole("button", {
      name: "Restore saved wiring draft",
      exact: true,
    }),
  ).toBeEnabled();
  await checkpoint(page)
    .getByRole("button", { name: "Restore saved wiring draft", exact: true })
    .click();
  await expect(
    page.getByLabel("Native replacement source", { exact: true }),
  ).toHaveValue("8-1/575_1.2_11");
});

test("restoring an earlier exported selection requires a fresh export", async ({
  page,
}) => {
  const f = await openWiring(page, "rewire", true);
  await page
    .getByLabel("Native replacement source", { exact: true })
    .selectOption("8-1/575_1.2_11");
  const downloading = page.waitForEvent("download");
  await page
    .getByRole("button", {
      name: "Check and export native CAF rewire",
      exact: true,
    })
    .click();
  await downloading;
  await checkpoint(page)
    .getByRole("button", { name: "Restore saved wiring draft", exact: true })
    .click();
  await expect(
    checkpoint(page).getByRole("status").filter({
      hasText: "Export and compatibility checks remain required",
    }),
  ).toBeVisible();
  let message = "";
  page.once("dialog", (d) => {
    message = d.message();
    return d.dismiss();
  });
  const choosing = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Open CAF", exact: true }).click();
  await (
    await choosing
  ).setFiles({
    name: "cancelled.caf",
    mimeType: "application/octet-stream",
    buffer: Buffer.from(f.caf, "base64"),
  });
  await expect.poll(() => message).toContain("Discard unexported CAF edits");
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("wiring-original.caf");
});
