import { test, expect } from "./nativeScheduleWriteFixture";
import { readFileSync } from "node:fs";
import {
  seed,
  enter,
  analyze,
  inspect,
} from "./native-connection-capability-fixture";

const original = '[data-operation="matching-connection-copy"]';
const effective = '[data-operation="effective-connection-compile"]';
const calls = new WeakMap<object, string[]>();
test.beforeEach(async ({ page }) => {
  const rows: string[] = [];
  calls.set(page, rows);
  page.on("request", (r) => {
    if (
      r.method() === "POST" &&
      /\/api\/bacnet\//.test(r.url()) &&
      !/\/inspection\//.test(r.url()) &&
      !/\/signal-default\/(source|sources)/.test(r.url())
    )
      rows.push(r.url());
  });
});

test("actual matching archive and effective support export the exact source-bound analysis on compact screens", async ({
  page,
  nativeScheduleWriteServer,
  request,
}, info) => {
  const f = seed(nativeScheduleWriteServer.directory);
  await page.setViewportSize({ width: 820, height: 1100 });
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
  await expect(table.locator(original).locator("td").first()).toHaveText(
    "source qualified",
  );
  await expect(table.locator(effective).locator("td").first()).toHaveText(
    "source qualified",
  );
  await expect(table.locator(effective)).toContainText(
    "Captured settings are not current live values",
  );
  await expect(
    table.locator('[data-operation="general-logic"]').locator("td").first(),
  ).toHaveText("unavailable");
  await expect(
    support.getByRole("button", { name: "Apply to controller", exact: true }),
  ).toHaveCount(0);
  const downloading = page.waitForEvent("download");
  await support
    .getByRole("button", { name: "Save exact operation analysis", exact: true })
    .click();
  expect(readFileSync((await (await downloading).path())!)).toEqual(exact);
  const data = JSON.parse(exact.toString());
  expect(data.can_apply).toBe(false);
  expect(data.current_identity_verified).toBe(false);
  expect(calls.get(page)).toEqual([]);
  expect(
    (await (await request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
  await table.locator(original).scrollIntoViewIfNeeded();
  await page.screenshot({
    path: info.outputPath("native-connection-capabilities-820.png"),
  });
});

for (const which of ["unknown", "unverified", "full"] as const)
  test(`${which} source shows actual unavailable connection scope without hiding archive inspection`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const f = seed(nativeScheduleWriteServer.directory),
      { support } = await enter(page, f[which]),
      table = await analyze(support);
    await expect(table.locator(original).locator("td").first()).toHaveText(
      which === "full" ? "unsupported source" : "source qualified",
    );
    await expect(table.locator(effective).locator("td").first()).toHaveText(
      "unsupported source",
    );
    await expect(
      table.locator('[data-operation="archive-read"]').locator("td").first(),
    ).toHaveText("source qualified");
    expect(calls.get(page)).toEqual([]);
  });

test("altered witness authority cannot populate the capability table", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seed(nativeScheduleWriteServer.directory);
  await page.route(
    "**/inspection/capabilities",
    async (route) => {
      const response = await route.fetch({ maxRetries: 0 }),
        data = JSON.parse((await response.body()).toString());
      data.qualification.archive_matching_connection.can_apply = true;
      await route.fulfill({ response, body: JSON.stringify(data) });
    },
    { times: 1 },
  );
  const { support } = await enter(page, f.id);
  await support.locator(":scope > summary").click();
  await expect(support.getByRole("alert")).toContainText(
    "differs from the selected source",
  );
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
    .getByRole("button", { name: "Analyze retained files again", exact: true })
    .click();
  await expect(
    support
      .getByRole("table", { name: "Native backup operations", exact: true })
      .getByRole("row"),
  ).toHaveCount(28);
  expect(calls.get(page)).toEqual([]);
});

test("source A B A cannot restore a delayed capability result or its export", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seed(nativeScheduleWriteServer.directory),
    { compiler, support } = await enter(page, f.id);
  let release = () => {},
    started = () => {};
  const gate = new Promise<void>((r) => (release = r)),
    received = new Promise<void>((r) => (started = r));
  await page.route(
    "**/inspection/capabilities",
    async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      started();
      await gate;
      await route.fulfill({ response });
    },
    { times: 1 },
  );
  try {
    await support.locator(":scope > summary").click();
    await received;
    await compiler
      .getByLabel("Retained native backup", { exact: true })
      .selectOption(f.full);
    await compiler
      .getByLabel("Retained native backup", { exact: true })
      .selectOption(f.id);
    const current = await inspect(compiler);
    const delivered = page.waitForResponse((r) =>
      r.url().endsWith("/inspection/capabilities"),
    );
    release();
    await (await delivered).finished();
    await page.evaluate(
      () =>
        new Promise<void>((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
        ),
    );
    await expect(
      current.getByRole("table", {
        name: "Native backup operations",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      current.getByRole("button", {
        name: "Save exact operation analysis",
        exact: true,
      }),
    ).toHaveCount(0);
    await analyze(current);
    expect(calls.get(page)).toEqual([]);
  } finally {
    release();
  }
});
