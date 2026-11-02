import {
  test,
  expect,
  type Page,
  type APIRequestContext,
} from "@playwright/test";
import { nativeDefaultPeer } from "./native-default-peer";
import { freePort } from "./workflow-peer";
import { chooseWorkspaceTask } from "./workspace-navigation";
const base = "/api/bacnet/controller/native-application";
async function reset(request: APIRequestContext) {
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  expect(
    (await request.post("/api/bacnet/disconnect", { headers, data: {} })).ok(),
  ).toBe(true);
  expect(
    (
      await request.post(base + "/credentials", {
        headers,
        data: { backup: "authored-backup", restore: "authored-restore" },
      })
    ).ok(),
  ).toBe(true);
}
async function open(page: Page, endpoint: string) {
  let published = "Authored input";
  await page.route("**/api/bacnet/controller/inventory", (route) =>
    route.fulfill({
      json: {
        identity_verified: true,
        complete: true,
        target: route.request().postDataJSON(),
        offset: 0,
        total: 1,
        next_offset: null,
        objects: [
          {
            object: "analog-input,101",
            object_type: 0,
            has_present_value: true,
          },
        ],
        errors: [],
        finished_at: new Date().toISOString(),
      },
    }),
  );
  await page.route("**/api/bacnet/controller/properties", (route) => {
    const body = route.request().postDataJSON();
    const fields: Record<string, unknown> = {
      "object-name": published,
      "present-value": 72,
      units: "degrees-fahrenheit",
      reliability: 0,
      "out-of-service": false,
      "status-flags": [0, 0, 0, 0],
      description: "Authored local point",
    };
    return route.fulfill({
      json: {
        identity_verified: true,
        complete: true,
        target: body,
        objects: body.object_ids.map((object: string) => ({
          object,
          identity_verified: true,
          properties: Object.fromEntries(
            body.properties.map((p: string) => [
              p,
              { status: "ok", value: fields[p] ?? "Authored configuration" },
            ]),
          ),
        })),
        errors: [],
        finished_at: new Date().toISOString(),
      },
    });
  });
  await page.route("**/native-application/point-name/apply", async (route) => {
    const response = await route.fetch({ maxRetries: 0 });
    const data = await response.json();
    if (data.result?.status === "verified")
      published = data.result.published_point_name;
    await route.fulfill({ response, json: data });
  });
  await page.goto("/");
  await page.getByRole("button", { name: /^Connect to a controller/ }).click();
  await page
    .getByLabel("Local bind address / UDP port", { exact: true })
    .fill(`127.0.0.1:${await freePort()}`);
  await page
    .getByRole("button", { name: "Open interface", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Known controller address", exact: true })
    .click();
  await page
    .getByLabel("Known controller address", { exact: true })
    .fill(endpoint);
  await page
    .getByLabel("Known Device object", { exact: true })
    .fill("device,5136");
  await page.getByLabel("Known router", { exact: true }).fill("");
  await page.getByLabel("Known network", { exact: true }).fill("");
  await page
    .getByRole("region", { name: "Known controller connection" })
    .getByRole("button", { name: "Open controller", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Controller overview" }),
  ).toContainText("Authored controller");
  await chooseWorkspaceTask(page, "Points & I/O");
  return configure(page);
}
async function configure(page: Page) {
  const row = page
    .getByRole("region", { name: "Connected controller points" })
    .getByRole("row")
    .filter({ hasText: "analog-input,101" });
  await row.getByRole("button", { name: "Configuration", exact: true }).click();
  await page.getByText("Edit point name", { exact: true }).click();
  return page.getByRole("region", {
    name: "Native point name configuration",
    exact: true,
  });
}
test("point configuration keeps drafts across tasks, retires reviews, and verifies one owned native transfer", async ({
  page,
  request,
}, info) => {
  test.setTimeout(60000);
  await reset(request);
  const peer = await nativeDefaultPeer("consume", "point-name");
  const writes: string[] = [];
  page.on("request", (r) => {
    if (r.url().endsWith("/point-name/apply")) writes.push(r.url());
  });
  try {
    let p = await open(page, peer.direct);
    await p
      .getByRole("button", { name: "Read point name backup", exact: true })
      .click();
    await expect(p).toContainText("Captured name: Authored input");
    await p
      .getByLabel("New point name", { exact: true })
      .fill("Reviewed input");
    await p
      .getByRole("button", { name: "Review point name change", exact: true })
      .click();
    await expect(
      p.getByRole("button", { name: "Apply point name", exact: true }),
    ).toBeDisabled();
    await chooseWorkspaceTask(page, "Overview");
    await chooseWorkspaceTask(page, "Points & I/O");
    p = await configure(page);
    await expect(p.getByLabel("New point name", { exact: true })).toHaveValue(
      "Reviewed input",
    );
    await expect(
      p.getByRole("button", { name: "Apply point name", exact: true }),
    ).toHaveCount(0);
    expect(writes).toEqual([]);
    await p
      .getByRole("button", { name: "Review point name change", exact: true })
      .click();
    await p
      .getByLabel("I confirm this point name change.", { exact: true })
      .check();
    await p
      .getByLabel(
        "I reviewed the application transfer and brief interruption.",
        { exact: true },
      )
      .check();
    await p
      .getByRole("button", { name: "Apply point name", exact: true })
      .click();
    await expect(
      p.getByRole("region", { name: "Point name transfer receipt" }),
    ).toContainText("Published name: Reviewed input.", { timeout: 30000 });
    expect(writes).toHaveLength(1);
    const calibration = p.getByRole("region", {
      name: "Live flow calibration readback",
    });
    await expect(calibration).toContainText("calibration differs");
    await calibration
      .getByText("Live airflow calibration values", { exact: true })
      .click();
    await expect(calibration).toContainText("3.5");
    await expect(calibration).toContainText("0.25");
    const stats = await peer.command("stats");
    expect(
      stats.events.filter(
        (e: any[]) => e[0] === "state" && e[1] === "start-restore",
      ),
    ).toHaveLength(1);
    await p
      .getByRole("button", { name: "Read back point name", exact: true })
      .click();
    await expect(
      p.getByRole("button", { name: "Read back point name", exact: true }),
    ).toBeEnabled();
    expect(
      (await peer.command("stats")).events.filter(
        (e: any[]) => e[0] === "state" && e[1] === "start-restore",
      ),
    ).toHaveLength(1);
    await page.screenshot({
      path: info.outputPath("point-name-desktop.png"),
      fullPage: true,
    });
    await page.setViewportSize({ width: 390, height: 1100 });
    await p.scrollIntoViewIfNeeded();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: info.outputPath("point-name-phone.png"),
      fullPage: true,
    });
  } finally {
    peer.close();
  }
});
