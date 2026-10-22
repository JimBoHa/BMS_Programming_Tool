import { test, expect, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";
const root = path.resolve(".."),
  python = path.join(root, ".venv/bin/python");
async function load(page: Page) {
  await page.goto("/");
  const buffer = execFileSync(
    python,
    [
      "-c",
      "import json;from tests.test_simulation_clock_api import timer_program;print(json.dumps(timer_program()))",
    ],
    { cwd: root },
  );
  await page
    .locator(
      'input[type=file][accept=".json,.st,.xml,.graphml,.sedona.zip,.sax,.sab,.bog,.bas"]',
    )
    .setInputFiles({
      name: "paced.bms.json",
      mimeType: "application/json",
      buffer,
    });
  await expect(page.locator(".toast")).toContainText(
    "Imported as a new local project",
  );
  await expect(page.getByLabel("Simulation pacing controls")).toContainText(
    "Fixed scan: 0.25 s",
  );
}
const status = (page: Page) => page.getByLabel("Simulation pacing status");
async function configure(page: Page, speed = "10", limit = "8") {
  await load(page);
  await page.getByLabel("Requested simulation speed").selectOption(speed);
  await page.getByLabel("Maximum scans per run").fill(limit);
}
test("actual paced run executes fixed scans to bounded budget and exports independently checked timer trace", async ({
  page,
  request,
}) => {
  await configure(page);
  const calls: any[] = [];
  page.on("request", (r) => {
    if (r.url().endsWith("/api/simulation/step")) calls.push(r.postDataJSON());
  });
  await page.getByTitle("Run simulation", { exact: true }).click();
  await expect(status(page)).toContainText(
    "complete: 8 confirmed committed scans",
  );
  await expect(page.locator(".elapsed")).toHaveText("2.0 s");
  expect(calls.reduce((n, c) => n + c.steps, 0)).toBe(8);
  expect(calls.every((c) => c.steps <= 100 && !("dt" in c))).toBe(true);
  await expect(status(page)).toContainText("requested 10×, achieved");
  const event = page.waitForEvent("download");
  await page.getByTitle("Export simulation CSV").click();
  const file = (await (await event).path())!;
  execFileSync(
    python,
    [
      "-c",
      "import csv,sys;r=list(csv.DictReader(open(sys.argv[1])));assert len(r)==8;assert [float(x['seconds']) for x in r]==[.25,.5,.75,1,1.25,1.5,1.75,2];assert [x['out'] for x in r]==['false']*3+['true']*5",
      file,
    ],
    { cwd: root },
  );
  expect(
    (await (await request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
});
test("pause freezes confirmed state and explicit resume continues retained timer without paused-time catch-up", async ({
  page,
}) => {
  await configure(page, "5", "100");
  await page.getByTitle("Run simulation", { exact: true }).click();
  await expect
    .poll(async () =>
      Number((await page.locator(".elapsed").innerText()).split(" ")[0]),
    )
    .toBeGreaterThan(0);
  await page.getByTitle("Pause simulation", { exact: true }).click();
  await expect(status(page)).toContainText("paused:");
  const before = await page.locator(".elapsed").innerText();
  await page.waitForTimeout(350);
  await expect(page.locator(".elapsed")).toHaveText(before);
  const resumed: any[] = [];
  page.on("request", (r) => {
    if (r.url().endsWith("/api/simulation/step"))
      resumed.push(r.postDataJSON());
  });
  await page.getByTitle("Run simulation", { exact: true }).click();
  await expect.poll(() => resumed.length).toBeGreaterThan(0);
  expect(resumed[0].session).toBeTruthy();
  expect(resumed[0].steps).toBeLessThan(10);
  await page.getByTitle("Pause simulation", { exact: true }).click();
  await expect(status(page)).toContainText("paused:");
  await expect
    .poll(async () =>
      Number((await page.locator(".elapsed").innerText()).split(" ")[0]),
    )
    .toBeGreaterThan(Number(before.split(" ")[0]));
});
test("workspace navigation pauses explicitly and never silently resumes", async ({
  page,
}) => {
  await configure(page, "10", "100");
  await page.getByTitle("Run simulation", { exact: true }).click();
  await expect
    .poll(async () =>
      Number((await page.locator(".elapsed").innerText()).split(" ")[0]),
    )
    .toBeGreaterThan(0);
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await page.getByRole("button", { name: "Program", exact: true }).click();
  await expect(status(page)).toContainText("paused:");
  const value = await page.locator(".elapsed").innerText();
  await page.waitForTimeout(300);
  await expect(page.locator(".elapsed")).toHaveText(value);
});
for (const action of ["pause", "reset", "source"])
  test(`delayed admitted receipt after ${action} preserves exact lifecycle`, async ({
    page,
  }) => {
    await configure(page, "10", "20");
    let seen!: () => void,
      release!: () => void,
      done!: () => void,
      receipt: any,
      body: any,
      count = 0;
    const requested = new Promise<void>((r) => (seen = r)),
      gate = new Promise<void>((r) => (release = r)),
      completed = new Promise<void>((r) => (done = r));
    await page.route("**/api/simulation/step", async (route) => {
      count++;
      body = route.request().postDataJSON();
      const response = await route.fetch();
      receipt = await response.json();
      seen();
      await gate;
      await route.fulfill({ response });
      done();
    });
    await page.getByTitle("Run simulation", { exact: true }).click();
    await requested;
    if (action === "pause") {
      await page.getByTitle("Pause simulation", { exact: true }).click();
      await expect(status(page)).toContainText("pausing:");
    }
    if (action === "reset")
      await page.getByTitle("Reset simulation", { exact: true }).click();
    if (action === "source")
      await page
        .getByLabel("Program name", { exact: true })
        .fill("Changed while admitted");
    release();
    await completed;
    if (action === "pause") {
      await expect(status(page)).toContainText("paused:");
      await expect(page.locator(".elapsed")).toHaveText(
        receipt.last.time.toFixed(1) + " s",
      );
      expect(receipt.completed_steps).toBe(body.steps);
    } else {
      await expect(page.locator(".elapsed")).toHaveText("0.0 s");
      await expect(status(page)).toContainText("Idle.");
    }
    await page.waitForTimeout(150);
    expect(count).toBe(1);
    await page.unroute("**/api/simulation/step");
    if (action !== "pause") {
      const next = page.waitForRequest("**/api/simulation/step");
      await page.getByLabel("Step simulation", { exact: true }).click();
      expect((await next).postDataJSON().session).toBeNull();
      await expect(page.locator(".elapsed")).toHaveText("0.3 s");
    }
  });
for (const mode of ["wrong-operation", "wrong-count", "http-error"])
  test(`refuse ${mode} response without automatic retry`, async ({ page }) => {
    await configure(page, "10", "20");
    let count = 0;
    await page.route("**/api/simulation/step", async (route) => {
      count++;
      const response = await route.fetch(),
        value = await response.json();
      if (mode === "wrong-operation") value.operation_id = "0".repeat(32);
      if (mode === "wrong-count") value.completed_steps = 1001;
      await route.fulfill({
        response,
        status: mode === "http-error" ? 503 : 200,
        json:
          mode === "http-error"
            ? { detail: "Response unavailable after admission" }
            : value,
      });
    });
    await page.getByTitle("Run simulation", { exact: true }).click();
    await expect(status(page)).toContainText("fault:");
    await expect(
      page.getByTitle("Run simulation", { exact: true }),
    ).toBeDisabled();
    await expect(
      page.getByLabel("Step simulation", { exact: true }),
    ).toBeDisabled();
    await expect(page.getByLabel("Requested simulation speed")).toBeDisabled();
    await page.waitForTimeout(150);
    expect(count).toBe(1);
    await expect(page.locator(".elapsed")).toHaveText("0.0 s");
    await page.getByTitle("Reset simulation", { exact: true }).click();
    await expect(
      page.getByTitle("Run simulation", { exact: true }),
    ).toBeEnabled();
  });
test("explicit simulation UTC uses one step; host pacing never substitutes wall UTC", async ({
  page,
}) => {
  await configure(page, "100", "4");
  await page.getByLabel("Next scan UTC clock").fill("2025-03-01T12:00");
  await expect(
    page.getByTitle("Run simulation", { exact: true }),
  ).toBeDisabled();
  await page.getByLabel("Step simulation", { exact: true }).click();
  await expect(page.getByLabel("Next scan UTC clock")).toHaveValue("");
  await page.getByTitle("Run simulation", { exact: true }).click();
  await expect(status(page)).toContainText(
    "complete: 4 confirmed committed scans",
  );
  const event = page.waitForEvent("download");
  await page.getByTitle("Export simulation CSV").click();
  const file = (await (await event).path())!;
  execFileSync(
    python,
    [
      "-c",
      "import csv,sys,datetime;r=list(csv.DictReader(open(sys.argv[1])));assert len(r)==5;assert r[0]['clock'].startswith('2025-03-01T12:00:00');assert datetime.datetime.fromisoformat(r[-1]['clock'])-datetime.datetime.fromisoformat(r[0]['clock'])==datetime.timedelta(seconds=1)",
      file,
    ],
    { cwd: root },
  );
});

test("known sensor fault pauses and explicit single-step recovery retains committed timer state", async ({
  page,
}) => {
  await configure(page, "10", "100");
  await page.getByLabel("Step simulation", { exact: true }).click();
  await expect(page.locator(".elapsed")).toHaveText("0.3 s");
  await page
    .getByLabel("Quality enable", { exact: true })
    .selectOption("open-circuit");
  await page.getByTitle("Run simulation", { exact: true }).click();
  await expect(status(page)).toContainText(
    "fault: 0 confirmed committed scans",
  );
  await expect(page.locator(".elapsed")).toHaveText("0.3 s");
  await expect(
    page.getByLabel("Step simulation", { exact: true }),
  ).toBeEnabled();
  await page.getByLabel("Quality enable", { exact: true }).selectOption("good");
  await page.getByLabel("Step simulation", { exact: true }).click();
  await expect(page.locator(".elapsed")).toHaveText("0.5 s");
});

test("opening an authoring dialog alone leaves run pacing explicit and unchanged", async ({
  page,
}) => {
  await configure(page, "5", "100");
  let calls = 0;
  page.on("request", (r) => {
    if (r.url().endsWith("/api/simulation/step")) calls++;
  });
  await page.getByTitle("Run simulation", { exact: true }).click();
  await expect.poll(() => calls).toBeGreaterThan(0);
  await page
    .getByRole("button", { name: "Equipment wizard", exact: true })
    .click();
  await expect(
    page.getByRole("dialog", {
      name: "Equipment and sequence wizard",
      exact: true,
    }),
  ).toBeVisible();
  const before = calls;
  await expect.poll(() => calls).toBeGreaterThan(before);
  await page
    .getByRole("button", { name: "Cancel wizard", exact: true })
    .click();
  await expect(status(page)).toContainText("running:");
  await page.getByTitle("Pause simulation", { exact: true }).click();
  await expect(status(page)).toContainText("paused:");
});

test("visibility-change handling pauses without automatic hidden-time catch-up", async ({
  page,
}) => {
  await configure(page, "5", "100");
  await page.getByTitle("Run simulation", { exact: true }).click();
  await expect
    .poll(async () =>
      Number((await page.locator(".elapsed").innerText()).split(" ")[0]),
    )
    .toBeGreaterThan(0);
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", {
      configurable: true,
      value: true,
    });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect(status(page)).toContainText("paused:");
  const before = await page.locator(".elapsed").innerText();
  await page.waitForTimeout(150);
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", {
      configurable: true,
      value: false,
    });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await page.waitForTimeout(150);
  await expect(page.locator(".elapsed")).toHaveText(before);
  await expect(status(page)).toContainText("hidden");
});

for (const action of ["none", "reset", "source", "failure"])
  test(`scenario admission shares scan gate and retires delayed ${action} response`, async ({
    page,
  }) => {
    await configure(page, "10", "20");
    await page.getByLabel("Step simulation", { exact: true }).click();
    await expect(page.locator(".elapsed")).toHaveText("0.3 s");
    await page.getByRole("button", { name: "Scenarios", exact: true }).click();
    await page
      .getByLabel("Timed simulation events")
      .fill('[{"time":0,"inputs":{"enable":true}}]');
    await page.getByLabel("Scenario duration seconds").fill("1");
    let seen!: () => void, release!: () => void, done!: () => void;
    const requested = new Promise<void>((r) => (seen = r)),
      gate = new Promise<void>((r) => (release = r)),
      completed = new Promise<void>((r) => (done = r));
    await page.route("**/api/simulation/scenario", async (route) => {
      const response = await route.fetch();
      seen();
      await gate;
      await route.fulfill(
        action === "failure"
          ? { status: 503, json: { detail: "Scenario result unavailable" } }
          : { response },
      );
      done();
    });
    await page
      .getByRole("button", { name: "Run scenario", exact: true })
      .click();
    await requested;
    await expect(
      page.getByTitle("Run simulation", { exact: true }),
    ).toBeDisabled();
    await expect(
      page.getByLabel("Step simulation", { exact: true }),
    ).toBeDisabled();
    await expect(
      page.getByRole("button", { name: "Run scenario", exact: true }),
    ).toBeDisabled();
    if (action === "reset")
      await page.getByTitle("Reset simulation", { exact: true }).click();
    if (action === "source")
      await page
        .getByLabel("Program name", { exact: true })
        .fill("Retired scenario source");
    await expect(
      page.getByLabel("Step simulation", { exact: true }),
    ).toBeDisabled();
    release();
    await completed;
    await expect(
      page.getByLabel("Step simulation", { exact: true }),
    ).toBeEnabled();
    if (action === "none")
      await expect(page.locator(".elapsed")).toHaveText("1.0 s");
    else if (action === "failure") {
      await expect(page.locator(".elapsed")).toHaveText("0.3 s");
      await expect(page.locator(".simulation")).toContainText(
        "Scenario result unavailable",
      );
      await page.getByLabel("Step simulation", { exact: true }).click();
      await expect(page.locator(".elapsed")).toHaveText("0.5 s");
    } else await expect(page.locator(".elapsed")).toHaveText("0.0 s");
  });

test("pending batch uses admitted inputs/recording snapshot and next step uses current selections", async ({
  page,
  request,
}) => {
  await configure(page, "5", "100");
  let seen!: () => void,
    release!: () => void,
    done!: () => void,
    body: any,
    receipt: any;
  const requested = new Promise<void>((r) => (seen = r)),
    gate = new Promise<void>((r) => (release = r)),
    completed = new Promise<void>((r) => (done = r));
  await page.route("**/api/simulation/step", async (route) => {
    body = route.request().postDataJSON();
    const response = await route.fetch();
    receipt = await response.json();
    seen();
    await gate;
    await route.fulfill({ response });
    done();
  });
  await page.getByTitle("Run simulation", { exact: true }).click();
  await requested;
  await page.getByLabel("Simulate enable", { exact: true }).uncheck();
  await page.getByLabel("Persist history", { exact: true }).check();
  await page.getByTitle("Pause simulation", { exact: true }).click();
  release();
  await completed;
  await expect(status(page)).toContainText("paused:");
  expect(body.record).toBe(false);
  expect(receipt.last.values.enable).toBe(true);
  expect(
    (await (await request.get("/api/observations/status")).json()).samples,
  ).toBe(0);
  await page.unroute("**/api/simulation/step");
  const event = page.waitForRequest("**/api/simulation/step");
  await page.getByLabel("Step simulation", { exact: true }).click();
  const next = (await event).postDataJSON();
  expect(next.inputs.enable).toBe(false);
  expect(next.record).toBe(true);
  await expect
    .poll(
      async () =>
        (await (await request.get("/api/observations/status")).json()).samples,
    )
    .toBe(3);
});

test("scenario completion preserves a newer operator force release for the next scan", async ({
  page,
}) => {
  await configure(page, "5", "100");
  await page.locator('.react-flow__node[data-id="out"]').click();
  await page
    .getByLabel("Simulation force value", { exact: true })
    .selectOption("false");
  await page
    .getByRole("button", { name: "Hold simulation value", exact: true })
    .click();
  await page.getByRole("button", { name: "Scenarios", exact: true }).click();
  await page
    .getByLabel("Timed simulation events")
    .fill('[{"time":0,"inputs":{"enable":true},"forces":{"out":true}}]');
  await page.getByLabel("Scenario duration seconds").fill("1");
  let seen!: () => void, release!: () => void, done!: () => void;
  const requested = new Promise<void>((r) => (seen = r)),
    gate = new Promise<void>((r) => (release = r)),
    completed = new Promise<void>((r) => (done = r));
  await page.route("**/api/simulation/scenario", async (route) => {
    const response = await route.fetch();
    seen();
    await gate;
    await route.fulfill({ response });
    done();
  });
  await page.getByRole("button", { name: "Run scenario", exact: true }).click();
  await requested;
  await page
    .getByRole("button", { name: "Release simulation force", exact: true })
    .click();
  release();
  await completed;
  await expect(page.locator(".elapsed")).toHaveText("1.0 s");
  await expect(page.locator(".force-status")).toContainText(
    "Next scan: automatic",
  );
  const event = page.waitForRequest("**/api/simulation/step");
  await page.getByLabel("Step simulation", { exact: true }).click();
  expect((await event).postDataJSON().forces).toEqual({});
});
