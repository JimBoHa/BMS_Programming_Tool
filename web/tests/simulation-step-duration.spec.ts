import {
  test,
  expect,
  simulationServerResponseJSON,
  fetchSimulationResponse,
  type Page,
} from "./simulationFixture";
import { chooseWorkspaceSurface } from "./workspace-navigation";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { projectedSourceFixture } from "./sourceTransportFixtures";
import { sourceStringify } from "../src/programSource";

const root = path.resolve("..");
function source(kind = "timer") {
  return execFileSync(
    path.join(root, ".venv/bin/python"),
    [
      "-c",
      `
from bms_tool.models import Program,Node,Edge
import sys
if sys.argv[1]=='timer':
 nodes=[Node(id='active',kind='Input',value_type='boolean',params={'default':True}),Node(id='timer',kind='TimerOn',params={'seconds':2}),Node(id='out',kind='Output',value_type='boolean')]
else:
 nodes=[Node(id='active',kind='Input',params={'default':10}),Node(id='timer',kind='Slew',params={'rate':2,'initial':0}),Node(id='out',kind='Output')]
p=Program(id='step-duration-'+sys.argv[1],name='Elapsed duration '+sys.argv[1],scan_seconds=1,nodes=nodes,edges=[Edge(id='a',source='active',target='timer'),Edge(id='b',source='timer',target='out')])
print(p.model_dump_json())
`,
      kind,
    ],
    {
      cwd: root,
      env: {
        ...process.env,
        PYTHONPATH: [
          process.env.BMS_TEST_INSTALLED_TARGET || path.join(root, "backend"),
          root,
        ].join(path.delimiter),
      },
    },
  );
}
async function load(page: Page, kind = "timer") {
  await page.goto("/");
  await page
    .getByRole("button", { name: "New application", exact: true })
    .click();
  await page
    .locator(
      'input[type=file][accept=".json,.st,.xml,.graphml,.sedona.zip,.sax,.sab,.bog,.bas"]',
    )
    .setInputFiles({
      name: "elapsed.bms.json",
      mimeType: "application/json",
      buffer: source(kind),
    });
  await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
    "Elapsed duration " + kind,
  );
  await page.getByRole("button", { name: "Simulate", exact: true }).click();
  await expect(
    page.getByLabel("Step simulation", { exact: true }),
  ).toBeEnabled();
}
const mode = (page: Page) =>
  page.getByRole("combobox", {
    name: "Single-step duration mode",
    exact: true,
  });
const duration = (page: Page) =>
  page.getByLabel("Single-step duration (seconds)", { exact: true });
async function step(page: Page) {
  const pending = page.waitForResponse(
    (r) =>
      r.url().endsWith("/api/simulation/step") &&
      r.request().method() === "POST",
  );
  await page.getByLabel("Step simulation", { exact: true }).click();
  const response = await pending;
  expect(response.status()).toBe(200);
  const receipt = simulationServerResponseJSON(response);
  await expect(
    page.getByLabel("Step simulation", { exact: true }),
  ).toBeEnabled();
  return { body: response.request().postDataJSON(), receipt };
}

for (const width of [1440, 412]) {
  test(`variable elapsed scans preserve the timer session and nominal project at ${width}px`, async ({
    page,
    request,
  }) => {
    await page.setViewportSize({ width, height: 1000 });
    await load(page);
    await expect(mode(page)).toHaveValue("nominal");
    await mode(page).selectOption("custom");
    await expect(
      page.getByRole("button", { name: "Run", exact: true }),
    ).toBeDisabled();
    const receipts = [];
    for (const seconds of [0.25, 0.25, 1.5]) {
      await duration(page).fill(String(seconds));
      const { body, receipt } = await step(page);
      expect(body.dt).toBe(seconds);
      expect(projectedSourceFixture(body.program).scan_seconds).toBe(1);
      expect(receipt.applied_dt).toBe(seconds);
      receipts.push(receipt);
    }
    expect(receipts.map((r) => r.last.time)).toEqual([0.25, 0.5, 2]);
    expect(receipts.map((r) => r.last.outputs.out)).toEqual([
      false,
      false,
      true,
    ]);
    expect(new Set(receipts.map((r) => r.session)).size).toBe(1);
    await expect(page.locator(".elapsed")).toHaveText("2 s");
    await duration(page).scrollIntoViewIfNeeded();
    await page.screenshot({
      path: test.info().outputPath(`step-duration-${width}.png`),
      fullPage: true,
    });
    await mode(page).selectOption("nominal");
    const nominal = await step(page);
    expect(nominal.body).not.toHaveProperty("dt");
    expect(nominal.receipt.applied_dt).toBe(1);
    expect(nominal.receipt.last.time).toBe(3);
    expect(nominal.receipt.session).toBe(receipts[0].session);
    await expect(
      page.getByRole("button", { name: "Run", exact: true }),
    ).toBeEnabled();
    expect(
      (await (await request.get("/api/session")).json()).field_network_open,
    ).toBe(false);
  });

  test(`unfinished duration is retained and cannot dispatch before repaint at ${width}px`, async ({
    page,
    request,
  }) => {
    await page.setViewportSize({ width, height: 1000 });
    await load(page);
    const baseline = (
      await (await request.get("/api/simulation/sessions/status")).json()
    ).cached_sessions;
    await mode(page).selectOption("custom");
    const calls: string[] = [];
    page.on("request", (r) => {
      if (r.method() === "POST" && r.url().endsWith("/api/simulation/step"))
        calls.push(r.url());
    });
    for (const raw of ["", "0", "-0", "60.01", "Infinity", "true", "1e-"]) {
      await duration(page).fill(raw);
      await expect(
        page.getByLabel("Step simulation", { exact: true }),
      ).toBeDisabled();
      await expect(
        page
          .getByRole("group", { name: "Simulation step duration", exact: true })
          .getByRole("alert"),
      ).toContainText("greater than 0");
    }
    await chooseWorkspaceSurface(page, "Library");
    await chooseWorkspaceSurface(page, "Workspace");
    await page.getByRole("button", { name: "Simulate", exact: true }).click();
    await expect(duration(page)).toHaveValue("1e-");
    await duration(page).fill("0.25");
    await page.evaluate(() => {
      const input = document.querySelector<HTMLInputElement>(
        'input[aria-label="Single-step duration (seconds)"]',
      )!;
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )!.set!.call(input, "1e-");
      input.dispatchEvent(new Event("input", { bubbles: true }));
      document
        .querySelector<HTMLButtonElement>(
          'button[aria-label="Step simulation"]',
        )!
        .click();
    });
    await expect(duration(page)).toHaveValue("1e-");
    await expect(
      page.getByLabel("Step simulation", { exact: true }),
    ).toBeDisabled();
    expect(calls).toHaveLength(0);
    expect(
      (await (await request.get("/api/simulation/sessions/status")).json())
        .cached_sessions,
    ).toBe(baseline);
  });

  test(`elapsed duration drives Slew without changing its rate at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 });
    await load(page, "slew");
    await mode(page).selectOption("custom");
    await duration(page).fill("0.25");
    const first = await step(page);
    expect(first.receipt.last.outputs.out).toBe(0.5);
    await duration(page).fill("0.75");
    const second = await step(page);
    expect(second.receipt.last.outputs.out).toBe(2);
    expect(second.receipt.last.time).toBe(1);
    expect(
      sourceStringify(
        projectedSourceFixture(second.body.program).nodes.find(
          (n: any) => n.id === "timer",
        ).params.rate,
      ),
    ).toBe("2");
  });

  test(`bad quality cannot consume elapsed timer state at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 });
    await load(page);
    await mode(page).selectOption("custom");
    await duration(page).fill("0.25");
    const first = await step(page);
    await page
      .getByLabel("Quality active", { exact: true })
      .selectOption("open-circuit");
    const fault = await step(page);
    expect(fault.receipt.completed_steps).toBe(0);
    expect(fault.receipt.scan_error).toContain("quality");
    await expect(page.locator(".elapsed")).toHaveText("0.25 s");
    await page
      .getByLabel("Quality active", { exact: true })
      .selectOption("good");
    await duration(page).fill("1.5");
    const recovered = await step(page);
    expect(recovered.receipt.session).toBe(first.receipt.session);
    expect(recovered.receipt.last.time).toBe(1.75);
    expect(recovered.receipt.last.outputs.out).toBe(false);
  });

  for (const action of ["reset", "source"])
    test(`late custom first receipt after ${action} retires its exact owned session at ${width}px`, async ({
      page,
      request,
    }) => {
      await page.setViewportSize({ width, height: 1000 });
      await load(page);
      const baseline = (
        await (await request.get("/api/simulation/sessions/status")).json()
      ).cached_sessions;
      await mode(page).selectOption("custom");
      await duration(page).fill("0.25");
      let release!: () => void, entered!: () => void;
      const gate = new Promise<void>((r) => (release = r)),
        received = new Promise<void>((r) => (entered = r));
      await page.route("**/api/simulation/step", async (route) => {
        const response = await fetchSimulationResponse(route);
        entered();
        await gate;
        await route.fulfill({ response });
      });
      try {
        await page.getByLabel("Step simulation", { exact: true }).click();
        await received;
        await expect(mode(page)).toBeDisabled();
        await expect(duration(page)).toBeDisabled();
        if (action === "reset")
          await page.getByTitle("Reset simulation", { exact: true }).click();
        else
          await page
            .getByLabel("Program name", { exact: true })
            .fill("Replacement source");
        const delivery = page.waitForResponse((r) =>
          r.url().endsWith("/api/simulation/step"),
        );
        release();
        await (await delivery).finished();
        await expect
          .poll(
            async () =>
              (
                await (
                  await request.get("/api/simulation/sessions/status")
                ).json()
              ).cached_sessions,
          )
          .toBe(baseline);
        await expect(
          page.getByLabel("Step simulation", { exact: true }),
        ).toBeEnabled();
        await expect(page.locator(".elapsed")).toHaveText(
          action === "reset" ? "0 s" : "0.0 s",
        );
        await expect(mode(page)).toHaveValue(
          action === "reset" ? "custom" : "nominal",
        );
      } finally {
        release();
        await page.unroute("**/api/simulation/step");
      }
    });

  test(`explicit UTC and elapsed duration remain separate at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 });
    await load(page);
    await mode(page).selectOption("custom");
    await duration(page).fill("0.25");
    await page
      .getByLabel("Next scan UTC clock", { exact: true })
      .fill("2026-01-05T12:00");
    const first = await step(page);
    expect(first.body.clock).toBe("2026-01-05T12:00:00.000Z");
    expect(first.receipt.last.clock).toBe("2026-01-05T12:00:00+00:00");
    const second = await step(page);
    expect(second.receipt.last.clock).toBe("2026-01-05T12:00:00.250000+00:00");
    expect(second.receipt.last.time).toBe(0.5);
  });

  test(`a different applied duration is uncertain and never retried at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 });
    await load(page);
    await mode(page).selectOption("custom");
    await duration(page).fill("0.25");
    let calls = 0;
    await page.route("**/api/simulation/step", async (route) => {
      calls++;
      const response = await fetchSimulationResponse(route);
      const value = await response.json();
      expect(value.applied_dt).toBe(0.25);
      value.applied_dt = 1;
      await route.fulfill({ response, json: value });
    });
    await page.getByLabel("Step simulation", { exact: true }).click();
    await expect(
      page.getByText("An admitted request may have committed scans.", {
        exact: false,
      }),
    ).toBeVisible();
    await expect(page.locator(".elapsed")).toHaveText("0 s");
    await expect(
      page.getByLabel("Step simulation", { exact: true }),
    ).toBeDisabled();
    await expect(mode(page)).toBeDisabled();
    await expect(duration(page)).toBeDisabled();
    await page.waitForTimeout(150);
    expect(calls).toBe(1);
  });

  test(`changing timing does not clear a paced scan fault at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 });
    await load(page);
    await page
      .getByLabel("Quality active", { exact: true })
      .selectOption("open-circuit");
    await page.getByLabel("Requested simulation speed").selectOption("100");
    await page.getByLabel("Maximum scans per run").fill("4");
    await page.getByRole("button", { name: "Run", exact: true }).click();
    const status = page.getByLabel("Simulation pacing status");
    await expect(status).toContainText("fault:");
    await mode(page).selectOption("custom");
    await duration(page).fill("0.25");
    await mode(page).selectOption("nominal");
    await expect(status).toContainText("fault:");
    await expect(
      page.getByRole("button", { name: "Run", exact: true }),
    ).toBeDisabled();
    await mode(page).selectOption("custom");
    await page
      .getByLabel("Quality active", { exact: true })
      .selectOption("good");
    const recovered = await step(page);
    expect(recovered.receipt.last.time).toBe(0.25);
    await mode(page).selectOption("nominal");
    await expect(
      page.getByRole("button", { name: "Run", exact: true }),
    ).toBeEnabled();
  });

  test(`custom Step timing does not change independent scenario cadence at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 });
    await load(page);
    await mode(page).selectOption("custom");
    await duration(page).fill("0.25");
    await page.getByRole("button", { name: "Scenarios", exact: true }).click();
    await page
      .getByLabel("Timed simulation events")
      .fill('[{"time":0,"inputs":{"active":true}}]');
    await page.getByLabel("Scenario duration seconds").fill("2");
    const pending = page.waitForResponse((r) =>
      r.url().endsWith("/api/simulation/scenario"),
    );
    await page
      .getByRole("button", { name: "Run scenario", exact: true })
      .click();
    const response = await pending;
    expect(response.status()).toBe(200);
    expect(response.request().postDataJSON()).not.toHaveProperty("dt");
    const receipt = simulationServerResponseJSON(response);
    expect(receipt.history.map((row: any) => row.time)).toEqual([1, 2]);
    expect(receipt.history.map((row: any) => row.outputs.out)).toEqual([
      false,
      true,
    ]);
    await expect(page.locator(".elapsed")).toHaveText("2 s");
    await expect(duration(page)).toHaveValue("0.25");
    const fresh = await step(page);
    expect(fresh.receipt.last.time).toBe(0.25);
    expect(fresh.body.dt).toBe(0.25);
  });
}
