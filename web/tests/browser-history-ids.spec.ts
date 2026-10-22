import {
  test,
  expect,
  type Page,
  type APIRequestContext,
} from "./historyIdentityFixture";
import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import path from "node:path";

const HIGH = "9007199254740993";
async function headers(request: APIRequestContext) {
  return {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
}
async function deliveries(
  page: Page,
  request: APIRequestContext,
  project: string,
) {
  const routes = await (await request.get("/api/notifications/routes")).json();
  const route = routes.find((row: any) => row.name === "Identity " + project);
  await page.goto("/");
  await page
    .getByRole("button", { name: "Alarm delivery", exact: true })
    .click();
  await expect(
    page
      .getByLabel("Delivery route filter", { exact: true })
      .locator("option")
      .filter({ hasText: "Identity " + project }),
  ).toHaveCount(1);
  await page
    .getByLabel("Delivery route filter", { exact: true })
    .selectOption(route.id);
  return route.id as string;
}
async function observations(page: Page, project: string) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Trends & alarms", exact: true })
    .click();
  const chooser = page.getByLabel("Observation source", { exact: true });
  await expect(
    chooser
      .locator("option")
      .filter({ hasText: "simulation/identity-normal-" + project }),
  ).toHaveCount(1);
  await chooser.selectOption("simulation/identity-normal-" + project);
  return chooser;
}

test("unsafe and malformed prune IDs refuse without a mutation request", async ({
  page,
  request,
  browserName,
}) => {
  await deliveries(page, request, browserName);
  const requests: string[] = [];
  page.on("request", (r) => {
    if (r.url().endsWith("/api/notifications/prune"))
      requests.push(r.postData()!);
  });
  await page
    .getByText("Release completed history capacity", { exact: true })
    .click();
  for (const value of [
    HIGH,
    "9007199254740992",
    "9223372036854775807",
    "+13",
    "13.0",
    "1e1",
    "-1",
    "0",
    "01",
  ]) {
    await page
      .getByLabel("Completed delivery history through ID", { exact: true })
      .fill(value);
    await page
      .getByRole("button", {
        name: "Delete completed delivery history",
        exact: true,
      })
      .click();
    await expect(
      page
        .getByRole("alert")
        .filter({ hasText: "Completed delivery history through ID" }),
    ).toBeVisible();
  }
  expect(requests).toEqual([]);
});

test("actual SQLite high delivery identities refuse every row action and unsafe cursors cannot query", async ({
  page,
  request,
  browserName,
}) => {
  const routes = await (await request.get("/api/notifications/routes")).json(),
    high = routes.find((r: any) => r.name === "Identity high");
  const original = await request.get(
    "/api/notifications/deliveries?route_id=" + high.id,
  );
  expect(await original.text()).toContain('"id":' + HIGH);
  const targeted: string[] = [];
  page.on("request", (r) => {
    if (/\/api\/notifications\/(?:retry|discard|deliveries\/)/.test(r.url()))
      targeted.push(r.url());
  });
  await deliveries(page, request, "high");
  await expect(page.getByRole("alert")).toContainText("Delivery ID");
  await expect(
    page.getByRole("button", { name: /^Download delivery/ }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: /^Retry .*delivery|^Discard delivery/ }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Next delivery page", exact: true }),
  ).toBeDisabled();
  expect(targeted).toEqual([]);
  // The page can recover through a safe route filter. A corrupted continuation
  // must not survive merely because the shown rows themselves have small IDs.
  await page.route("**/api/notifications/deliveries?**", async (route) => {
    const response = await route.fetch(),
      body = (await response.text()).replace(
        /"next_after":(?:null|\d+)/,
        '"next_after":' + HIGH,
      );
    await route.fulfill({ response, body });
  });
  const safe = routes.find((r: any) => r.name === "Identity " + browserName);
  await page
    .getByLabel("Delivery route filter", { exact: true })
    .selectOption(safe.id);
  await expect(page.getByRole("alert")).toContainText(
    "Next delivery page cursor",
  );
  await expect(
    page.getByRole("button", { name: "Next delivery page", exact: true }),
  ).toBeDisabled();
  expect(targeted).toEqual([]);
});

test("normal delivery download retry discard and prune keep exact small IDs", async ({
  page,
  request,
  browserName,
}) => {
  const start = browserName === "chromium" ? 11 : 21;
  const route = await deliveries(page, request, browserName),
    auth = await headers(request);
  const original = await (
    await request.get("/api/notifications/deliveries/" + start)
  ).text();
  const pending = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Download delivery " + start, exact: true })
    .click();
  const file = await pending;
  const downloaded = readFileSync((await file.path())!, "utf8");
  expect(downloaded).toBe(original);
  expect(JSON.parse(downloaded).id).toBe(start);
  execFileSync(
    path.resolve("../.venv/bin/python"),
    [
      "-c",
      "import json,sys;p=json.load(sys.stdin);assert p['payload']['opaque_record_id']==9007199254740993",
    ],
    { input: downloaded },
  );
  await page
    .getByLabel("Delivery action note", { exact: true })
    .fill("Authored local review");
  const retry = page.waitForResponse((r) =>
    r.url().endsWith("/api/notifications/retry"),
  );
  await page
    .getByRole("button", { name: "Retry delivery " + start, exact: true })
    .click();
  const retried = await retry;
  expect(retried.ok()).toBe(true);
  expect(retried.request().postDataJSON().id).toBe(start);
  const discard = page.waitForResponse((r) =>
    r.url().endsWith("/api/notifications/discard"),
  );
  await page
    .getByRole("button", {
      name: "Discard delivery " + (start + 1),
      exact: true,
    })
    .click();
  const discarded = await discard;
  expect(discarded.ok()).toBe(true);
  expect(discarded.request().postDataJSON().id).toBe(start + 1);
  await page
    .getByText("Release completed history capacity", { exact: true })
    .click();
  await page
    .getByLabel("Completed delivery history through ID", { exact: true })
    .fill(String(start + 2));
  const pruned = page.waitForResponse((r) =>
    r.url().endsWith("/api/notifications/prune"),
  );
  await page
    .getByRole("button", {
      name: "Delete completed delivery history",
      exact: true,
    })
    .click();
  expect((await pruned).request().postDataJSON().through_id).toBe(start + 2);
  await expect(page.getByRole("status")).toContainText(
    "Completed delivery history cleanup",
  );
  const rows = await (
    await request.get("/api/notifications/deliveries?route_id=" + route)
  ).json();
  expect(rows.rows.map((r: any) => r.id)).toEqual([start]);
  expect(rows.rows[0].state).toBe("queued");
  expect(
    (await (await request.get("/api/session", { headers: auth })).json())
      .field_network_open,
  ).toBe(false);
});

test("actual high alarm event and sample identities refuse acknowledgment event selection and paging", async ({
  page,
  request,
  browserName,
}) => {
  const chooser = await observations(page, browserName),
    targeted: string[] = [];
  page.on("request", (r) => {
    if (
      r.url().includes("/api/observations/acknowledge") ||
      new URL(r.url()).searchParams.has("alarm_id")
    )
      targeted.push(r.url());
  });
  for (const [source, label] of [
    ["alarm", "Alarm occurrence ID"],
    ["event", "Alarm event sequence"],
    ["trend", "Trend sample sequence"],
  ]) {
    await chooser.selectOption("simulation/identity-high-" + source);
    await expect(page.getByRole("alert")).toContainText(label);
    await expect(
      page.getByRole("button", {
        name: /^Acknowledge alarm|^Events for alarm/,
      }),
    ).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "Next samples", exact: true }),
    ).toBeDisabled();
    await expect(
      page.getByRole("button", {
        name: "Export shown trends CSV",
        exact: true,
      }),
    ).toBeDisabled();
  }
  expect(targeted).toEqual([]);
  expect(
    (await (await request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
});

test("normal alarm acknowledgment and event query keep the selected occurrence ID", async ({
  page,
  request,
  browserName,
}) => {
  const source = "simulation/identity-normal-" + browserName;
  const [alarm] = await (
    await request.get("/api/observations/alarms?source=" + source)
  ).json();
  await observations(page, browserName);
  const events = page.waitForRequest(
    (r) =>
      new URL(r.url()).pathname === "/api/observations/events" &&
      new URL(r.url()).searchParams.has("alarm_id"),
  );
  await page
    .getByRole("button", { name: "Events for alarm " + alarm.id, exact: true })
    .click();
  expect(new URL((await events).url()).searchParams.get("alarm_id")).toBe(
    String(alarm.id),
  );
  await page
    .getByLabel(`Alarm ${alarm.id} acknowledgment note`, { exact: true })
    .fill("Reviewed authored local alarm");
  const ack = page.waitForRequest((r) =>
    r.url().endsWith("/api/observations/acknowledge"),
  );
  await page
    .getByRole("button", { name: "Acknowledge alarm " + alarm.id, exact: true })
    .click();
  expect((await ack).postDataJSON().alarm_id).toBe(alarm.id);
  await expect(
    page.getByRole("button", {
      name: "Acknowledge alarm " + alarm.id,
      exact: true,
    }),
  ).toHaveCount(0);
  expect(
    (
      await (
        await request.get("/api/observations/alarms?source=" + source)
      ).json()
    )[0].acknowledged,
  ).toBe(true);
});

test("wrong unsafe download receipt cannot create an exported delivery file", async ({
  page,
  request,
  browserName,
}) => {
  const start = browserName === "chromium" ? 11 : 21;
  await deliveries(page, request, browserName);
  await page.route(
    "**/api/notifications/deliveries/" + start,
    async (route) => {
      const response = await route.fetch(),
        body = (await response.text()).replace('"id":' + start, '"id":' + HIGH);
      await route.fulfill({ response, body });
    },
  );
  const files: string[] = [];
  page.on("download", (file) => files.push(file.suggestedFilename()));
  await page
    .getByRole("button", { name: "Download delivery " + start, exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("Downloaded delivery ID");
  expect(files).toEqual([]);
});
