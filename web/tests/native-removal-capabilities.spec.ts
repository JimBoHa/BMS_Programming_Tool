import { test, expect } from "./nativeScheduleWriteFixture";
import { readFileSync } from "node:fs";
import { seed, enter, analyze } from "./native-removal-capability-fixture";

const archive = '[data-operation="connection-removal-copy"]';
const effective = '[data-operation="effective-connection-removal-compile"]';
const calls = new WeakMap<object, string[]>();
test.beforeEach(async ({ page }) => {
  const requests: string[] = [];
  calls.set(page, requests);
  page.on("request", (r) => {
    if (
      r.method() === "POST" &&
      /\/api\/bacnet\//.test(r.url()) &&
      !/\/inspection\//.test(r.url()) &&
      !/\/signal-default\/(source|sources)/.test(r.url())
    )
      requests.push(r.url());
  });
});
for (const width of [820, 390])
  test(`${width}px removal analysis exports exact local evidence with one source and no field requests`, async ({
    page,
    nativeScheduleWriteServer,
    request,
  }, info) => {
    const f = seed(nativeScheduleWriteServer.directory);
    await page.setViewportSize({ width, height: 1100 });
    let exact = Buffer.alloc(0),
      body: any;
    await page.route("**/inspection/capabilities", async (route) => {
      body = route.request().postDataJSON();
      const response = await route.fetch({ maxRetries: 0 });
      exact = await response.body();
      await route.fulfill({ response });
    });
    const { support } = await enter(page, f.id),
      table = await analyze(support);
    expect(body.capability_profile).toBe(
      "native-backup-operation-capabilities/14",
    );
    for (const selector of [archive, effective])
      await expect(table.locator(selector).locator("td").first()).toHaveText(
        "source qualified",
      );
    await expect(table.locator(archive)).toContainText(
      "destination becomes unwired",
    );
    await expect(table.locator(effective)).toContainText("fallback/retention");
    await expect(
      support.getByRole("button", { name: "Apply to controller", exact: true }),
    ).toHaveCount(0);
    const downloading = page.waitForEvent("download");
    await support
      .getByRole("button", {
        name: "Save exact operation analysis",
        exact: true,
      })
      .click();
    expect(readFileSync((await (await downloading).path())!)).toEqual(exact);
    const data = JSON.parse(exact.toString());
    expect(data.can_apply).toBe(false);
    expect(data.field_actions).toBe(false);
    expect(
      (await (await request.get("/api/session")).json()).field_network_open,
    ).toBe(false);
    expect(calls.get(page)).toEqual([]);
    await table.locator(archive).scrollIntoViewIfNeeded();
    await page.screenshot({
      path: info.outputPath("removal-capabilities.png"),
    });
  });
for (const which of ["unknown", "unverified", "full", "empty"] as const)
  test(`${which} source reports actual archive and saved removal support`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const f = seed(nativeScheduleWriteServer.directory),
      { support } = await enter(page, f[which]),
      table = await analyze(support);
    await expect(table.locator(archive).locator("td").first()).toHaveText(
      which === "empty" ? "unsupported source" : "source qualified",
    );
    await expect(table.locator(effective).locator("td").first()).toHaveText(
      which === "full" ? "source qualified" : "unsupported source",
    );
    if (which === "full")
      await expect(
        table
          .locator('[data-operation="matching-connection-copy"]')
          .locator("td")
          .first(),
      ).toHaveText("unsupported source");
    expect(calls.get(page)).toEqual([]);
  });
for (const fault of ["source", "count", "semantics", "status"])
  test(`substituted removal ${fault} withholds the table and exact export until explicit reanalysis`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const f = seed(nativeScheduleWriteServer.directory);
    await page.route(
      "**/inspection/capabilities",
      async (route) => {
        const response = await route.fetch({ maxRetries: 0 }),
          value = JSON.parse((await response.body()).toString()),
          w = value.qualification.archive_connection_removal;
        if (fault === "source") w.source_sha256 = "0".repeat(64);
        else if (fault === "count") w.connection_count = 0;
        else if (fault === "semantics")
          w.native_fallback_or_retention_verified = true;
        else
          value.operations.find(
            (r: any) => r.id === "connection-removal-copy",
          ).status = "preflight-required";
        await route.fulfill({ response, body: JSON.stringify(value) });
      },
      { times: 1 },
    );
    const { support } = await enter(page, f.id);
    if ((await support.getAttribute("open")) === null)
      await support.locator(":scope > summary").click();
    await expect(support.getByRole("alert")).toBeVisible();
    await expect(
      support.getByRole("table", {
        name: "Native backup operations",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      support.getByRole("button", {
        name: "Save exact operation analysis",
        exact: true,
      }),
    ).toHaveCount(0);
    await support
      .getByRole("button", {
        name: "Analyze retained files again",
        exact: true,
      })
      .click();
    await expect(
      support
        .getByRole("table", { name: "Native backup operations", exact: true })
        .getByRole("row"),
    ).toHaveCount(28);
    expect(calls.get(page)).toEqual([]);
  });
