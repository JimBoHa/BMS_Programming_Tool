import { test, expect } from "./nativeScheduleWriteFixture";
import {
  families,
  enterFamily,
  inspectFamily,
  savedCopy,
  logic,
} from "./caf-open-copy-fixture";
import { chooseWorkspaceTask } from "./workspace-navigation";
const family = families[0];
for (const outcome of ["reject", "wrong-identity"])
  test(`failed ${outcome} handoff keeps the original source and allows a proven retry`, async ({
    page,
  }) => {
    const editor = await enterFamily(page),
      proof = await savedCopy(page);
    await page.route("**/api/caf", async (route) => {
      if (route.request().method() !== "POST") {
        await route.continue();
        return;
      }
      await route.fulfill({
        status: outcome === "reject" ? 503 : 200,
        contentType: "application/json",
        body: JSON.stringify(
          outcome === "reject"
            ? { detail: "Authored upload unavailable" }
            : { sha256: "0".repeat(64) },
        ),
      });
    });
    await editor
      .getByRole("button", { name: "Open CAF copy", exact: true })
      .click();
    await expect(editor.getByRole("alert")).toContainText(
      outcome === "reject"
        ? "Authored upload unavailable"
        : "identity does not match",
    );
    await expect(
      page.getByLabel("Current CAF archive", { exact: true }),
    ).toHaveText("authored.caf");
    await expect(
      editor.getByRole("button", { name: "Open CAF copy", exact: true }),
    ).toBeEnabled();
    await page.unroute("**/api/caf");
    await editor
      .getByRole("button", { name: "Open CAF copy", exact: true })
      .click();
    await expect(
      page.getByLabel("Current CAF archive", { exact: true }),
    ).toHaveText("authored-constant-copy.caf");
    const next = await inspectFamily(page, family);
    await expect(
      next.getByLabel("Constant prototype", { exact: true }),
    ).toHaveValue(proof.creation.selection.new_ref);
  });
for (const retirement of ["task ABA", "pagehide", "visibility"])
  test(`${retirement} retires a held native upload before the parent can replace its source`, async ({
    page,
  }) => {
    let editor = await enterFamily(page);
    await editor.getByLabel("New constant X", { exact: true }).fill("150");
    await savedCopy(page);
    let release!: () => void, started!: () => void;
    const held = new Promise<void>((r) => (release = r)),
      entered = new Promise<void>((r) => (started = r));
    await page.route("**/api/caf", async (route) => {
      if (route.request().method() !== "POST") {
        await route.continue();
        return;
      }
      started();
      await held;
      await route.continue();
    });
    const returned = page.waitForResponse(
      (r) =>
        new URL(r.url()).pathname === "/api/caf" &&
        r.request().method() === "POST",
    );
    await editor
      .getByRole("button", { name: "Open CAF copy", exact: true })
      .click();
    await entered;
    if (retirement === "task ABA") {
      await chooseWorkspaceTask(page, "Overview");
      await logic(page);
    } else if (retirement === "pagehide")
      await page.evaluate(() => window.dispatchEvent(new Event("pagehide")));
    else
      await page.evaluate(() => {
        Object.defineProperty(document, "visibilityState", {
          configurable: true,
          value: "hidden",
        });
        document.dispatchEvent(new Event("visibilitychange"));
        Object.defineProperty(document, "visibilityState", {
          configurable: true,
          value: "visible",
        });
        document.dispatchEvent(new Event("visibilitychange"));
      });
    release();
    const response = await returned;
    expect(response.status()).toBe(200);
    expect(await response.finished()).toBeNull();
    await page.unroute("**/api/caf");
    await expect(
      page.getByLabel("Current CAF archive", { exact: true }),
    ).toHaveText("authored.caf");
    editor = await inspectFamily(page, family);
    await expect(
      editor.getByLabel("New constant X", { exact: true }),
    ).toHaveValue("150");
    await expect(
      editor.getByRole("button", { name: "Open CAF copy", exact: true }),
    ).toHaveCount(0);
    await savedCopy(page);
    await editor
      .getByRole("button", { name: "Open CAF copy", exact: true })
      .click();
    await expect(
      page.getByLabel("Current CAF archive", { exact: true }),
    ).toHaveText("authored-constant-copy.caf");
  });
test("changed export proof never offers an Open action", async ({ page }) => {
  const editor = await enterFamily(page);
  await page.route("**/constant-copy/export", async (route) => {
    const response = await route.fetch({ maxRetries: 0 });
    await route.fulfill({
      response,
      headers: {
        ...response.headers(),
        "X-Studio-Artifact-Sha256": "0".repeat(64),
      },
    });
  });
  await editor
    .getByRole("button", { name: "Review constant CAF copy", exact: true })
    .click();
  await editor
    .getByRole("button", { name: "Save constant CAF copy", exact: true })
    .click();
  await expect(editor.getByRole("alert")).toContainText(
    "bytes or proof do not match",
  );
  await expect(
    editor.getByRole("button", { name: "Open CAF copy", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("authored.caf");
});
test("double click opens one proven archive and compact controls keep one primary action", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const editor = await enterFamily(page);
  await savedCopy(page);
  const open = editor.getByRole("button", {
    name: "Open CAF copy",
    exact: true,
  });
  await expect(editor.locator("button.primary:visible")).toHaveCount(1);
  expect((await open.boundingBox())!.height).toBeGreaterThanOrEqual(36);
  let uploads = 0;
  page.on("request", (r) => {
    if (new URL(r.url()).pathname === "/api/caf" && r.method() === "POST")
      uploads++;
  });
  await open.evaluate((button) => {
    (button as HTMLButtonElement).click();
    (button as HTMLButtonElement).click();
  });
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("authored-constant-copy.caf");
  expect(uploads).toBe(1);
});
