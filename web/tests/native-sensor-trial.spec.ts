import {
  test,
  expect,
  type Page,
  type APIRequestContext,
} from "./nativeScheduleWriteFixture";
import { nativeDefaultPeer } from "./native-default-peer";
import { freePort } from "./workflow-peer";
import { chooseWorkspaceTask } from "./workspace-navigation";
import { execFileSync } from "node:child_process";
import path from "node:path";

test.setTimeout(90000);
const base = "/api/bacnet/controller/native-application";
async function open(page: Page, request: APIRequestContext, address: string) {
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  expect(
    (
      await request.post(base + "/credentials", {
        headers,
        data: { backup: "authored-backup", restore: "authored-restore" },
      })
    ).ok(),
  ).toBe(true);
  await page.route("**/api/bacnet/controller/inventory", (route) =>
    route.fulfill({
      json: {
        identity_verified: true,
        complete: true,
        target: route.request().postDataJSON(),
        offset: 0,
        total: 0,
        next_offset: null,
        objects: [],
        errors: [],
      },
    }),
  );
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
    .fill(address);
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
  return panel(page);
}
async function panel(page: Page) {
  const inputs = page.getByRole("button", {
    name: "Configure native inputs",
    exact: true,
  });
  if (await inputs.isVisible()) await inputs.click();
  await page
    .getByRole("button", {
      name: "Test sensor definition compatibility",
      exact: true,
    })
    .click();
  return page.getByRole("region", {
    name: "Sensor definition compatibility",
    exact: true,
  });
}
async function capture(p: ReturnType<Page["getByRole"]>) {
  const button = p.getByRole("button", {
    name: "Capture sensor configuration",
    exact: true,
  });
  await button.focus();
  await expect(button).toBeFocused();
  await button.press("Space");
  await expect(
    p.getByLabel("First trial identifier", { exact: true }),
  ).toHaveValue("3000000");
}
async function review(p: ReturnType<Page["getByRole"]>, restore = false) {
  await p
    .getByRole("button", {
      name: restore
        ? "Review restoring original definition"
        : "Review controller sensor trial",
      exact: true,
    })
    .click();
  const r = p.getByRole("region", { name: "Sensor trial review", exact: true });
  await expect(r).toBeVisible();
  await r
    .getByLabel(
      "I reviewed the exact controller, addresses and reversible sensor trial.",
      { exact: true },
    )
    .check();
  await r
    .getByLabel(
      "I authorize the application transfer and temporary control interruption.",
      { exact: true },
    )
    .check();
  return r;
}

test("sensor trial local copy, review invalidation, live readback and restoration use real UDP", async ({
  page,
  request,
}, info) => {
  const peer = await nativeDefaultPeer("consume", "sensor-trial");
  try {
    const p = await open(page, request, peer.direct);
    await capture(p);
    await p
      .getByRole("button", { name: "Review local trial copy", exact: true })
      .click();
    await expect(p).toContainText("16 new unconnected records");
    const download = page.waitForEvent("download");
    await p
      .getByRole("button", { name: "Save trial application copy", exact: true })
      .click();
    expect((await download).suggestedFilename()).toBe(
      "netsensor-trial-copy.moz",
    );
    await review(p);
    await p.getByLabel("Trial SA addresses", { exact: true }).fill("201,205");
    await expect(
      p.getByRole("region", { name: "Sensor trial review", exact: true }),
    ).toHaveCount(0);
    expect(
      (await peer.command("stats")).events.some((e: any[]) => e[0] === "write"),
    ).toBe(false);
    await p
      .getByLabel("Trial SA addresses", { exact: true })
      .fill("199,200,201,202,203,204,205,206");
    const r = await review(p);
    await r
      .getByRole("button", {
        name: "Apply reviewed sensor change",
        exact: true,
      })
      .click();
    await expect(
      p.getByRole("region", { name: "Sensor trial result" }),
    ).toContainText("Application transfer: verified", { timeout: 25000 });
    await p
      .getByRole("button", { name: "Read trial sensor values", exact: true })
      .click();
    await expect(
      p.getByRole("row").filter({ hasText: "70.5 °F" }),
    ).toContainText("205");
    await expect(
      p.getByRole("row").filter({ hasText: "unreliable" }),
    ).toHaveCount(7);
    await p.scrollIntoViewIfNeeded();
    await page.screenshot({
      path: info.outputPath("sensor-trial-desktop.png"),
      fullPage: true,
    });
    await page.setViewportSize({ width: 390, height: 844 });
    await p.getByRole("table").scrollIntoViewIfNeeded();
    await page.screenshot({
      path: info.outputPath("sensor-trial-narrow.png"),
      fullPage: true,
    });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth + 1,
      ),
    ).toBe(true);
    await page.setViewportSize({ width: 1440, height: 1000 });
    const restore = await review(p, true);
    await restore
      .getByRole("button", {
        name: "Apply reviewed sensor change",
        exact: true,
      })
      .click();
    await expect(
      p.getByRole("region", { name: "Sensor trial result" }),
    ).toContainText("Application transfer: verified", { timeout: 25000 });
    await expect(
      p.getByRole("button", { name: "Read trial sensor values", exact: true }),
    ).toHaveCount(0);
    const events = (await peer.command("stats")).events;
    expect(
      events.filter((e: any[]) => e[0] === "state" && e[1] === "start-restore"),
    ).toHaveLength(2);
  } finally {
    peer.close();
  }
});

test("a lost Apply response reopens durable evidence and readback sends no second download", async ({
  page,
  request,
}) => {
  const peer = await nativeDefaultPeer("consume", "sensor-trial");
  try {
    const p = await open(page, request, peer.direct);
    await capture(p);
    const r = await review(p);
    await page.route(
      "**/sensor-trial/apply",
      async (route) => {
        await route.fetch();
        await route.abort("failed");
      },
      { times: 1 },
    );
    await r
      .getByRole("button", {
        name: "Apply reviewed sensor change",
        exact: true,
      })
      .click();
    await p
      .getByText("Retained sensor trials and recovery", { exact: true })
      .click();
    const retained = p.getByRole("button", { name: /^Open sensor receipt/ });
    await expect(retained).toHaveCount(1, { timeout: 25000 });
    await retained.click();
    await expect(
      p.getByRole("region", { name: "Sensor trial result" }),
    ).toContainText("verified");
    await p
      .getByRole("button", { name: "Read back sensor transfer", exact: true })
      .click();
    await expect(p.getByRole("status")).toContainText("Local copies");
    const events = (await peer.command("stats")).events;
    expect(
      events.filter((e: any[]) => e[0] === "state" && e[1] === "start-restore"),
    ).toHaveLength(1);
  } finally {
    peer.close();
  }
});

test("CAF entry retains offline sensor drafts and exports a copy without a field connection", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const root = path.resolve(".."),
    env = {
      ...process.env,
      PYTHONPATH: [path.join(root, "backend"), root].join(path.delimiter),
    };
  const capture = JSON.parse(
    execFileSync(
      path.join(root, ".venv/bin/python"),
      [
        "-c",
        `
import json,sys
from bms_tool.storage import Store
from bms_tool.application_store import ApplicationStore
from tests.test_native_sensor_trial import sensor_source
s=ApplicationStore(Store(sys.argv[1]))
print(json.dumps(s.save({'target':{'address':'192.0.2.44','router':None,'dnet':None},'device':'device,5136','identity':{'device':'device,5136','object-name':'Authored controller','model-name':'UNLISTED-MODEL'},'source_identity_matches':True,'connector_config':{}},sensor_source())))
`,
        nativeScheduleWriteServer.directory,
      ],
      { cwd: root, env, encoding: "utf8" },
    ),
  );
  const caf = execFileSync(
    path.join(root, ".venv/bin/python"),
    [
      "-c",
      "from tests.test_caf_graph import make_graph; import sys; sys.stdout.buffer.write(make_graph())",
    ],
    { cwd: root, env },
  );
  const field: string[] = [];
  page.on("request", (r) => {
    if (
      r.method() === "POST" &&
      /\/(connect|capture|support|preview|apply|readback|observe)$/.test(
        r.url(),
      )
    )
      field.push(r.url());
  });
  await page.goto("/");
  await page
    .getByLabel("Open local CAF application", { exact: true })
    .setInputFiles({
      name: "authored-offline.caf",
      mimeType: "application/octet-stream",
      buffer: caf,
    });
  await chooseWorkspaceTask(page, "Points & I/O");
  let p = await panel(page);
  await p
    .getByLabel("Retained sensor capture", { exact: true })
    .selectOption(capture.id);
  await p
    .getByRole("button", { name: "Open sensor capture", exact: true })
    .click();
  await expect(p).toContainText("Local inspection");
  await p.getByLabel("First trial identifier", { exact: true }).fill("3000010");
  await p.getByLabel("Trial SA addresses", { exact: true }).fill("201,205");
  await chooseWorkspaceTask(page, "Schedules");
  await chooseWorkspaceTask(page, "Points & I/O");
  p = await panel(page);
  await expect(p.getByLabel("Trial SA addresses", { exact: true })).toHaveValue(
    "201,205",
  );
  await expect(
    p.getByRole("button", {
      name: "Review controller sensor trial",
      exact: true,
    }),
  ).toBeDisabled();
  await p
    .getByRole("button", { name: "Review local trial copy", exact: true })
    .click();
  await expect(p).toContainText("4 new unconnected records");
  const download = page.waitForEvent("download");
  await p
    .getByRole("button", { name: "Save trial application copy", exact: true })
    .click();
  expect((await download).suggestedFilename()).toBe("netsensor-trial-copy.moz");
  expect(field).toEqual([]);
});
