import { test, expect, type Page } from "@playwright/test";
import { freePort, peer } from "./workflow-peer";
async function openController(page: Page, endpoint: string) {
  await page.goto("/");
  await page.getByRole("button", { name: /^Connect to a controller/ }).click();
  await page
    .getByLabel("Local bind address / UDP port", { exact: true })
    .fill(`127.0.0.1:${await freePort()}`);
  await page
    .getByRole("button", { name: "Open interface", exact: true })
    .click();
  await selectKnown(page, endpoint, 8);
}
async function selectKnown(page: Page, endpoint: string, mac: number) {
  await page
    .getByRole("button", { name: "Known controller address", exact: true })
    .click();
  await page
    .getByLabel("Known controller address", { exact: true })
    .fill(`3001:${mac}`);
  await page
    .getByLabel("Known Device object", { exact: true })
    .fill("device,5136");
  await page.getByLabel("Known router", { exact: true }).fill(endpoint);
  await page.getByLabel("Known network", { exact: true }).fill("3001");
  await page
    .getByRole("region", { name: "Known controller connection" })
    .getByRole("button", { name: "Open controller", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Controller overview" }),
  ).toContainText(`Authored 3001 MAC ${mac}`);
}
const tasks = (page: Page) =>
  page.getByRole("navigation", { name: "Workspace tasks" });
const tools = (page: Page) =>
  page.getByRole("navigation", { name: "Controller task tools" });
test("unsaved state mapping survives subtool navigation", async ({ page }) => {
  const router = await peer();
  try {
    await openController(page, router.endpoint);
    await tasks(page)
      .getByRole("button", { name: "Points & I/O", exact: true })
      .click();
    await tools(page)
      .getByRole("button", { name: "State mapping", exact: true })
      .click();
    await page
      .getByLabel("Source enum domain ID", { exact: true })
      .fill("unsaved-domain-review");
    await tools(page)
      .getByRole("button", { name: "Read properties", exact: true })
      .click();
    await tools(page)
      .getByRole("button", { name: "State mapping", exact: true })
      .click();
    await page.screenshot({
      path: test.info().outputPath("state-mapping-after-navigation.png"),
      fullPage: true,
    });
    expect(router.writes).toEqual([]);
    await expect(
      page.getByLabel("Source enum domain ID", { exact: true }),
    ).toHaveValue("unsaved-domain-review");
  } finally {
    router.close();
  }
});
test("unsaved identity number survives task navigation without restoring a review", async ({
  page,
}) => {
  const router = await peer();
  try {
    await openController(page, router.endpoint);
    await page
      .getByRole("button", { name: "Edit instance number", exact: true })
      .click();
    await page
      .getByLabel("New controller instance (0–4194302)", { exact: true })
      .fill("15136");
    await page
      .getByRole("button", { name: "Review instance change", exact: true })
      .click();
    await expect(
      page.getByLabel("Reviewed instance change", { exact: true }),
    ).toBeVisible();
    await page
      .getByLabel(
        "I reserved this new number across the BACnet internetwork, including offline devices.",
      )
      .check();
    await tasks(page)
      .getByRole("button", { name: "Points & I/O", exact: true })
      .click();
    await tasks(page)
      .getByRole("button", { name: "Overview", exact: true })
      .click();
    await tools(page)
      .getByRole("button", { name: "Identity settings", exact: true })
      .click();
    expect(router.writes).toEqual([]);
    await expect(
      page.getByLabel("New controller instance (0–4194302)", { exact: true }),
    ).toHaveValue("15136");
    await expect(
      page.getByLabel("Reviewed instance change", { exact: true }),
    ).toHaveCount(0);
    await expect(
      page.getByRole("button", {
        name: "Apply controller instance change",
        exact: true,
      }),
    ).toHaveCount(0);
  } finally {
    router.close();
  }
});

test("instance draft stays with the exact station when duplicate Device IDs share a router", async ({
  page,
}) => {
  const router = await peer();
  try {
    await openController(page, router.endpoint);
    await page
      .getByRole("button", { name: "Edit instance number", exact: true })
      .click();
    await page
      .getByLabel("New controller instance (0–4194302)", { exact: true })
      .fill("15136");
    await page
      .getByRole("button", { name: "Change controller", exact: true })
      .click();
    await selectKnown(page, router.endpoint, 7);
    await page
      .getByRole("button", { name: "Edit instance number", exact: true })
      .click();
    await expect(
      page.getByLabel("New controller instance (0–4194302)", { exact: true }),
    ).toHaveValue("");
    await page
      .getByLabel("New controller instance (0–4194302)", { exact: true })
      .fill("15137");
    await page
      .getByRole("button", { name: "Change controller", exact: true })
      .click();
    await selectKnown(page, router.endpoint, 8);
    await page
      .getByRole("button", { name: "Edit instance number", exact: true })
      .click();
    await expect(
      page.getByLabel("New controller instance (0–4194302)", { exact: true }),
    ).toHaveValue("15136");
    await expect(
      page.getByLabel("Reviewed instance change", { exact: true }),
    ).toHaveCount(0);
    expect(router.writes).toEqual([]);
  } finally {
    router.close();
  }
});
