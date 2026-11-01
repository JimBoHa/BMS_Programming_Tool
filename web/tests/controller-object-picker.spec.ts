import { test, expect, type Page } from "@playwright/test";
import { freePort, peer } from "./workflow-peer";

async function fieldRecording(page: Page, endpoint: string) {
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
    .fill("3001:7");
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
  ).toContainText("Authored 3001 MAC 7");
  await page
    .getByRole("navigation", { name: "Workspace tasks" })
    .getByRole("button", { name: "Trends & Alarms", exact: true })
    .click();
  await page
    .getByRole("navigation", { name: "Current task tools" })
    .getByRole("button", { name: "Field recording", exact: true })
    .click();
}

test("discovered choices reject a different target and page bounded source-qualified object names", async ({
  page,
  request,
}, info) => {
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  await request.post("/api/bacnet/disconnect", { headers, data: {} });
  const router = await peer();
  const inventories: any[] = [],
    names: any[] = [];
  let wrongTarget = true,
    wrongConfiguration = false,
    wrongNameConfiguration = true;
  let failed = false;
  try {
    await page.route("**/api/bacnet/controller/inventory", async (route) => {
      const { offset, limit, ...target } = route.request().postDataJSON();
      const configuration = (
        await (await request.get("/api/bacnet/status")).json()
      ).config;
      inventories.push({ offset, limit, ...target });
      await route.fulfill({
        json: {
          identity_verified: true,
          connector_config: wrongConfiguration
            ? { ...configuration, local_address: "127.0.0.1:49999" }
            : configuration,
          target: wrongTarget ? { ...target, address: "3001:8" } : target,
          objects:
            offset === 0
              ? [
                  {
                    object: "file,1",
                    object_type: 10,
                    has_present_value: false,
                  },
                ]
              : [
                  {
                    object: "analog-input,73",
                    object_type: 0,
                    has_present_value: true,
                  },
                ],
          total: 17,
          next_offset: offset === 0 ? 16 : null,
          complete: true,
          errors: [],
        },
      });
    });
    await page.route("**/api/bacnet/controller/properties", async (route) => {
      const { object_ids, properties, ...target } = route
        .request()
        .postDataJSON();
      names.push({ object_ids, properties, ...target });
      const configuration = (
        await (await request.get("/api/bacnet/status")).json()
      ).config;
      await route.fulfill({
        json: {
          identity_verified: true,
          connector_config: wrongNameConfiguration
            ? { ...configuration, local_address: "127.0.0.1:49999" }
            : configuration,
          target,
          objects: object_ids.map((object: string) => ({
            object,
            identity_verified: true,
            properties: {
              "object-name": {
                status: "ok",
                value: wrongNameConfiguration
                  ? "Other interface name"
                  : "Authored late-page sensor",
              },
            },
          })),
          complete: true,
          errors: [],
        },
      });
    });
    await fieldRecording(page, router.endpoint);
    const picker = page.getByRole("group", {
      name: "Field discovered object",
      exact: true,
    });
    await expect(picker.getByRole("alert")).toContainText(
      "inventory identity or interface context was not verified",
    );
    expect(names).toEqual([]);
    await expect(
      picker.getByLabel("Field discovered object object", { exact: true }),
    ).toBeDisabled();
    wrongTarget = false;
    wrongConfiguration = true;
    await picker
      .getByRole("button", { name: "Reload object choices", exact: true })
      .click();
    await expect(picker.getByRole("alert")).toContainText(
      "interface context was not verified",
    );
    expect(names).toEqual([]);
    wrongConfiguration = false;
    await picker
      .getByRole("button", { name: "Reload object choices", exact: true })
      .click();
    await expect(picker).toContainText(
      "No eligible objects were returned on this page",
    );
    await expect(
      picker.getByRole("button", { name: "Next objects", exact: true }),
    ).toBeEnabled();
    await picker
      .getByRole("button", { name: "Next objects", exact: true })
      .click();
    await expect(picker).toContainText("Names unavailable");
    await expect(
      picker.getByRole("option", { name: /Other interface name/ }),
    ).toHaveCount(0);
    wrongNameConfiguration = false;
    await picker
      .getByRole("button", { name: "Reload object choices", exact: true })
      .click();
    await expect(
      picker.getByRole("option", {
        name: "Authored late-page sensor · analog-input,73",
        exact: true,
      }),
    ).toHaveCount(1);
    await picker
      .getByLabel("Field discovered object search", { exact: true })
      .fill("late-page");
    await picker
      .getByLabel("Field discovered object object", { exact: true })
      .selectOption("analog-input,73");
    await expect(
      page.getByLabel("Field object identifier 1", { exact: true }),
    ).toHaveValue("analog-input,73");
    expect(inventories.map((row) => [row.offset, row.limit])).toEqual([
      [0, 16],
      [0, 16],
      [0, 16],
      [16, 16],
      [16, 16],
    ]);
    expect(
      inventories.every(
        (row) =>
          row.address === "3001:7" &&
          row.device === "device,5136" &&
          row.router === router.endpoint &&
          row.dnet === 3001,
      ),
    ).toBe(true);
    expect(names).toHaveLength(2);
    expect(names[0].object_ids).toEqual(["analog-input,73"]);
    await info.attach("bounded-object-requests", {
      body: JSON.stringify({ inventories, names }),
      contentType: "application/json",
    });
    await info.attach("selected-controller-recording-layout", {
      body: await page.screenshot({ fullPage: true }),
      contentType: "image/png",
    });
  } catch (error) {
    failed = true;
    throw error;
  } finally {
    // Retire the owned child even if the request fixture has already closed.
    router.close();
    try {
      await request.post("/api/bacnet/disconnect", { headers, data: {} });
      expect(router.errors).toEqual([]);
      expect(router.writes).toEqual([]);
    } catch (error) {
      if (!failed) throw error;
      await info.attach("picker-cleanup-error-after-original-failure", {
        body: String(error),
        contentType: "text/plain",
      });
    }
  }
});
