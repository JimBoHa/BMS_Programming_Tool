import {
  test,
  expect,
  type Page,
  type APIRequestContext,
} from "./nativeScheduleWriteFixture";
import { readFileSync } from "node:fs";
import { seedPointRecovery } from "./nativePointNameRecoveryFixture";
import { nativeDefaultPeer } from "./native-default-peer";
import { freePort } from "./workflow-peer";
import { chooseWorkspaceTask } from "./workspace-navigation";
const base = "/api/bacnet/controller/native-application";
const panel = (p: Page) =>
  p.getByRole("region", {
    name: "Native point name configuration",
    exact: true,
  });
const proposal = (p: Page) =>
  p.getByRole("region", { name: "Previous point name proposal", exact: true });
async function headers(request: APIRequestContext) {
  return {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
}
async function configure(page: Page) {
  await chooseWorkspaceTask(page, "Points & I/O");
  const row = page
    .getByRole("region", { name: "Connected controller points" })
    .getByRole("row")
    .filter({ hasText: "analog-input,101" });
  await row.getByRole("button", { name: "Configuration", exact: true }).click();
  await page.getByText("Edit point name", { exact: true }).click();
  await expect(panel(page)).toBeVisible();
}
async function pointNavigation(page: Page) {
  // These HTTP fixtures supply navigation/point-list context only; native transfer calls use the real backend/UDP peer.
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
    const body = route.request().postDataJSON(),
      values: any = {
        "object-name": "Authored navigation point",
        "present-value": 72,
        units: "degrees-fahrenheit",
        reliability: 0,
        "out-of-service": false,
        "status-flags": [0, 0, 0, 0],
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
              { status: "ok", value: values[p] ?? "Authored metadata" },
            ]),
          ),
        })),
        errors: [],
        finished_at: new Date().toISOString(),
      },
    });
  });
}
async function connect(page: Page, target: any, caf?: string) {
  await page.goto("/");
  if (caf) {
    const choosing = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: /^Open a CAF file/ }).click();
    await (
      await choosing
    ).setFiles({
      name: "point-recovery.caf",
      mimeType: "application/octet-stream",
      buffer: Buffer.from(caf, "base64"),
    });
    await expect(
      page.getByLabel("Current CAF archive", { exact: true }),
    ).toHaveText("point-recovery.caf");
    await page.getByRole("button", { name: "Connect", exact: true }).click();
  } else
    await page
      .getByRole("button", { name: /^Connect to a controller/ })
      .click();
  await page
    .getByLabel("Local bind address / UDP port", { exact: true })
    .fill(`127.0.0.1:${await freePort()}`);
  await page
    .getByRole("button", { name: "Open interface", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Known controller address", exact: true })
    .click();
  for (const [name, value] of [
    ["Known controller address", target.address],
    ["Known Device object", "device,5136"],
    ["Known router", target.router ?? ""],
    ["Known network", target.dnet == null ? "" : String(target.dnet)],
  ])
    await page.getByLabel(name, { exact: true }).fill(value);
  await page
    .getByRole("region", { name: "Known controller connection", exact: true })
    .getByRole("button", { name: "Open controller", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Controller overview", exact: true }),
  ).toContainText("Authored controller");
  await configure(page);
}
async function retained(page: Page, id: string) {
  await panel(page)
    .getByLabel("Retained point name transfer", { exact: true })
    .selectOption(id);
  await expect(
    panel(page).getByRole("button", {
      name: "Save point name receipt",
      exact: true,
    }),
  ).toBeVisible();
}
async function capture(page: Page) {
  await panel(page)
    .getByRole("button", { name: "Read point name backup", exact: true })
    .click();
  await expect(
    panel(page).getByLabel("New point name", { exact: true }),
  ).toBeVisible();
  await expect(
    panel(page).getByRole("button", {
      name: "Read point name backup",
      exact: true,
    }),
  ).toBeEnabled();
}
async function prepare(page: Page) {
  const disclosure = panel(page).getByText("Previous point name", {
    exact: true,
  });
  if (await disclosure.isVisible()) {
    const details = disclosure.locator("..");
    if ((await details.getAttribute("open")) === null) await disclosure.click();
  }
  await panel(page)
    .getByRole("button", { name: "Prepare previous point name", exact: true })
    .click();
}
async function localContext(
  page: Page,
  request: APIRequestContext,
  data: any,
  caf = false,
) {
  let config: any = {};
  // Explicitly authored selected-controller context; the actual backend interface remains closed.
  await page.route("**/api/bacnet/connect", (route) => {
    config = route.request().postDataJSON();
    return route.fulfill({ json: { connected: true, config, commands: [] } });
  });
  await page.route("**/api/bacnet/status", (route) =>
    route.fulfill({ json: { connected: true, config, commands: [] } }),
  );
  await page.route("**/api/bacnet/device-details", (route) =>
    route.fulfill({
      json: {
        identity_verified: true,
        address: data.capture.target.address,
        properties: {
          "object-identifier": "device,5136",
          "object-name": "Authored controller",
          "model-name": "UNLISTED-MODEL",
        },
        finished_at: new Date().toISOString(),
      },
    }),
  );
  await page.route("**" + base + "/capture", (route) =>
    route.fulfill({ json: data.capture }),
  );
  await page.route("**" + base + "/point-name/source", (route) =>
    route.fulfill({
      json: {
        profile: "native-point-name-transfer/1",
        capture_id: data.capture.id,
        snapshot_sha256: data.capture.snapshot_evidence_sha256,
        target: data.capture.target,
        device: data.capture.device,
        points: [data.field],
        controller_queries: false,
        controller_writes: false,
      },
    }),
  );
  await request.post(base + "/credentials", {
    headers: await headers(request),
    data: { backup: "authored-backup", restore: "authored-restore" },
  });
  await pointNavigation(page);
  await connect(page, data.capture.target, caf ? data.caf : undefined);
  await capture(page);
  await retained(page, data.receipt.intent.id);
}

for (const caf of [false, true])
  test(`local ${caf ? "CAF" : "controller"} entry stages exact evidence and preserves ordinary text without field access`, async ({
    page,
    request,
    nativeScheduleWriteServer,
  }, info) => {
    const data = seedPointRecovery(nativeScheduleWriteServer.directory);
    await localContext(page, request, data, caf);
    await panel(page)
      .getByLabel("New point name", { exact: true })
      .fill("Keep my ordinary draft");
    let originalResponse = "";
    await page.route(
      "**" + base + "/point-name/recovery/prepare",
      async (route) => {
        const response = await route.fetch();
        originalResponse =
          "\n" + JSON.stringify(await response.json(), null, 2) + "\n";
        await route.fulfill({ response, body: originalResponse });
      },
    );
    await prepare(page);
    await expect(proposal(page)).toContainText("Previous name: Authored input");
    await expect(
      panel(page).getByLabel("New point name", { exact: true }),
    ).toHaveValue("Keep my ordinary draft");
    const downloading = page.waitForEvent("download");
    await proposal(page)
      .getByRole("button", {
        name: "Save previous point name proposal",
        exact: true,
      })
      .click();
    const saved = readFileSync((await (await downloading).path())!, "utf8");
    expect(saved).toBe(originalResponse);
    expect(JSON.parse(saved)).toEqual(data.report);
    await proposal(page)
      .getByRole("button", { name: "Use previous point name", exact: true })
      .click();
    await expect(
      panel(page).getByLabel("New point name", { exact: true }),
    ).toHaveValue("Authored input");
    if (caf) {
      await page.setViewportSize({ width: 390, height: 844 });
      await proposal(page)
        .getByText("Previous point name evidence", { exact: true })
        .click();
      await proposal(page).scrollIntoViewIfNeeded();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      expect(
        await proposal(page)
          .locator("pre")
          .evaluate((el) => getComputedStyle(el).fontSize),
      ).toBe("14px");
      await page.screenshot({
        path: info.outputPath("previous-point-proposal-phone.png"),
        fullPage: true,
      });
    }
    await chooseWorkspaceTask(page, "Overview");
    await configure(page);
    await expect(
      panel(page).getByLabel("New point name", { exact: true }),
    ).toHaveValue("Authored input");
    await proposal(page)
      .getByRole("button", {
        name: "Return to saved point name draft",
        exact: true,
      })
      .click();
    await expect(
      panel(page).getByLabel("New point name", { exact: true }),
    ).toHaveValue("Keep my ordinary draft");
    expect(
      (await (await request.get("/api/session")).json()).field_network_open,
    ).toBe(false);
    if (caf)
      await expect(
        page.getByLabel("Current CAF archive", { exact: true }),
      ).toHaveText("point-recovery.caf");
  });

for (const boundary of ["navigation", "visibility", "pagehide"])
  test(`late previous point-name proposal retires across ${boundary}`, async ({
    page,
    request,
    nativeScheduleWriteServer,
  }) => {
    const data = seedPointRecovery(nativeScheduleWriteServer.directory);
    await localContext(page, request, data);
    let release!: () => void, seen!: () => void;
    const gate = new Promise<void>((r) => (release = r)),
      entered = new Promise<void>((r) => (seen = r));
    await page.route(
      "**" + base + "/point-name/recovery/prepare",
      async (route) => {
        const response = await route.fetch();
        seen();
        await gate;
        await route.fulfill({ response });
      },
    );
    await prepare(page);
    await entered;
    if (boundary === "navigation") await chooseWorkspaceTask(page, "Overview");
    else if (boundary === "visibility")
      await page.evaluate(() =>
        document.dispatchEvent(new Event("visibilitychange")),
      );
    else await page.evaluate(() => window.dispatchEvent(new Event("pagehide")));
    const settling = page.waitForResponse((r) =>
      r.url().endsWith("/point-name/recovery/prepare"),
    );
    release();
    await (await settling).finished();
    if (boundary === "navigation") await configure(page);
    await expect(proposal(page)).toHaveCount(0);
    expect(
      (await (await request.get("/api/session")).json()).field_network_open,
    ).toBe(false);
  });

test("substituted point/source proposal never replaces ordinary text", async ({
  page,
  request,
  nativeScheduleWriteServer,
}) => {
  const data = seedPointRecovery(nativeScheduleWriteServer.directory);
  await localContext(page, request, data);
  await panel(page)
    .getByLabel("New point name", { exact: true })
    .fill("Keep me");
  await page.route(
    "**" + base + "/point-name/recovery/prepare",
    async (route) => {
      const response = await route.fetch(),
        body = await response.json();
      body.origin.object_id = "analog-input,102";
      await route.fulfill({ response, json: body });
    },
  );
  await prepare(page);
  await expect(panel(page).getByRole("alert")).toContainText(
    "differs from this receipt",
  );
  await expect(proposal(page)).toHaveCount(0);
  await expect(
    panel(page).getByLabel("New point name", { exact: true }),
  ).toHaveValue("Keep me");
});

for (const routed of [false, true])
  test(`genuine ${routed ? "routed" : "direct"} new reviewed recovery verifies point name and preserves parent receipt`, async ({
    page,
    request,
  }, info) => {
    test.setTimeout(60000); // Two deliberate five-second restore preparation phases plus capture/readback and UI navigation.
    const peer = await nativeDefaultPeer("consume", "point-name"),
      target = {
        address: routed ? "3001:7" : peer.direct,
        device: "device,5136",
        router: routed ? peer.router : null,
        dnet: routed ? 3001 : null,
      };
    const token = await headers(request);
    try {
      await request.post(base + "/credentials", {
        headers: token,
        data: { backup: "authored-backup", restore: "authored-restore" },
      });
      await pointNavigation(page);
      await connect(page, target);
      const read = await request.post(base + "/capture", {
        headers: token,
        data: { ...target, operation_id: "parent-point-capture" },
      });
      expect(read.ok()).toBe(true);
      const first = await read.json();
      const source = await request.post(base + "/point-name/source", {
        headers: token,
        data: {
          ...target,
          capture_id: first.id,
          snapshot_sha256: first.snapshot_evidence_sha256,
        },
      });
      const field = (await source.json()).points.find(
        (p: any) => p.object_id === "analog-input,101",
      );
      const preview = await request.post(base + "/point-name/preview", {
        headers: token,
        data: {
          ...target,
          capture_id: first.id,
          snapshot_sha256: first.snapshot_evidence_sha256,
          object_id: field.object_id,
          record_ref: field.record_ref,
          encoded_sha256: field.encoded_sha256,
          new_name: "Changed input",
          operation_id: "parent-point-preview",
        },
      });
      expect(preview.ok()).toBe(true);
      const plan = await preview.json();
      const applied = await request.post(base + "/point-name/apply", {
        headers: token,
        data: {
          operation_id: "parent-point-apply",
          token: plan.token,
          review_sha256: plan.review_sha256,
          point_name_confirmed: true,
          application_transfer_confirmed: true,
        },
      });
      const parent = await applied.json();
      expect(parent.result.status).toBe("verified");
      const parentOriginal = await (
        await request.get(base + "/receipts/" + parent.intent.id)
      ).text();
      await capture(page);
      await retained(page, parent.intent.id);
      await panel(page)
        .getByLabel("New point name", { exact: true })
        .fill("Keep ordinary text");
      const before = await peer.command("stats");
      await prepare(page);
      await expect(proposal(page)).toContainText(
        "Previous name: Authored input",
      );
      const after = await peer.command("stats");
      expect(after.events).toEqual(before.events);
      await proposal(page)
        .getByRole("button", { name: "Use previous point name", exact: true })
        .click();
      await panel(page)
        .getByRole("button", { name: "Review point name change", exact: true })
        .click();
      const reviewed = panel(page).getByRole("region", {
        name: "Reviewed point name change",
        exact: true,
      });
      await expect(reviewed).toContainText("Changed input → Authored input");
      await expect(panel(page).locator("button.primary:visible")).toHaveCount(
        1,
      );
      await reviewed
        .getByLabel("I confirm this point name change.", { exact: true })
        .check();
      await reviewed
        .getByLabel(
          "I reviewed the application transfer and brief interruption.",
          { exact: true },
        )
        .check();
      const completed = page.waitForResponse((response) =>
        response.url().endsWith(base + "/point-name/apply"),
      );
      await reviewed
        .getByRole("button", { name: "Apply point name", exact: true })
        .click();
      await (await completed).finished();
      await expect(
        panel(page).getByRole("region", {
          name: "Point name transfer receipt",
          exact: true,
        }),
      ).toContainText("Published name: Authored input");
      expect(
        await (
          await request.get(base + "/receipts/" + parent.intent.id)
        ).text(),
      ).toBe(parentOriginal);
      const stats = await peer.command("stats");
      expect(
        stats.events.filter(
          (e: any) => e[0] === "state" && e[1] === "start-restore",
        ),
      ).toHaveLength(2);
      expect(stats.router_errors).toEqual([]);
      if (routed) {
        await page.setViewportSize({ width: 390, height: 844 });
        expect(
          await page.evaluate(
            () => document.documentElement.scrollWidth <= innerWidth,
          ),
        ).toBe(true);
        await page.screenshot({
          path: info.outputPath("point-recovery-phone.png"),
          fullPage: true,
        });
      }
      await capture(page);
      await expect(
        panel(page).getByLabel("New point name", { exact: true }),
      ).toHaveValue("Keep ordinary text");
    } finally {
      await request.post("/api/bacnet/disconnect", {
        headers: token,
        data: {},
      });
      await peer.close();
    }
  });
