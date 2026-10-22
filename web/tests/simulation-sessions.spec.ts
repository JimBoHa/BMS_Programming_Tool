import { simulationServerResponseJSON } from "./simulationFixture";
import { fetchSimulationResponse } from "./simulationFixture";
import {
  test,
  expect,
  type Page,
  type APIRequestContext,
} from "./simulationFixture";
import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import path from "node:path";
const root = path.resolve(".."),
  python = path.join(root, ".venv/bin/python");
const source = () =>
  JSON.parse(
    execFileSync(
      python,
      [
        "-c",
        "import json;from tests.test_simulation_clock_api import timer_program;print(json.dumps(timer_program()))",
      ],
      { cwd: root, encoding: "utf8" },
    ),
  );
const operation = () => randomUUID().replaceAll("-", "");
async function auth(request: APIRequestContext) {
  return {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
}
async function count(request: APIRequestContext) {
  return (await (await request.get("/api/simulation/sessions/status")).json())
    .cached_sessions;
}
async function retire(request: APIRequestContext, receipt: any) {
  if (!receipt?.session || !receipt?.retirement_token) return;
  const response = await request.post("/api/simulation/retire", {
    headers: await auth(request),
    data: {
      session: receipt.session,
      retirement_token: receipt.retirement_token,
      creation_operation_id: receipt.session_creation_operation_id,
    },
  });
  expect(response.ok()).toBe(true);
}
async function seed(request: APIRequestContext) {
  const program = source();
  program.id = "independent-" + operation();
  const response = await request.post("/api/simulation/step", {
    headers: await auth(request),
    data: { program, operation_id: operation() },
  });
  expect(response.ok()).toBe(true);
  return { program, receipt: await response.json() };
}
async function load(page: Page) {
  await page.goto("/");
  await page
    .locator(
      'input[type=file][accept=".json,.st,.xml,.graphml,.sedona.zip,.sax,.sab,.bog,.bas"]',
    )
    .setInputFiles({
      name: "local-session.bms.json",
      mimeType: "application/json",
      buffer: Buffer.from(JSON.stringify(source())),
    });
  await expect(page.locator(".toast")).toContainText(
    "Imported as a new local project",
  );
}
async function step(page: Page) {
  const event = page.waitForResponse(
    (r) =>
      r.url().endsWith("/api/simulation/step") &&
      r.request().method() === "POST",
  );
  await page.getByLabel("Step simulation", { exact: true }).click();
  const response = await event;
  expect(response.ok()).toBe(true);
  const value = simulationServerResponseJSON(response);
  await expect(page.locator(".elapsed")).toHaveText(
    value.last.time.toFixed(1) + " s",
  );
  return value;
}

test("45 reset/source cycles and repeated real reloads release only owned sessions", async ({
  page,
  request,
}) => {
  test.setTimeout(60000);
  const baseline = await count(request),
    other = await seed(request);
  const own: any[] = [];
  try {
    await load(page);
    for (let i = 0; i < 45; i++) {
      own.push(await step(page));
      if (i % 2)
        await page
          .getByLabel("Program name", { exact: true })
          .fill("Source cycle " + i);
      else await page.getByTitle("Reset simulation", { exact: true }).click();
      await expect.poll(() => count(request)).toBe(baseline + 1);
    }
    for (let i = 0; i < 6; i++) {
      own.push(await step(page));
      await page.reload();
      await expect(
        page.getByLabel("Program name", { exact: true }),
      ).toBeVisible();
      await expect.poll(() => count(request)).toBe(baseline + 1);
    }
    const continued = await request.post("/api/simulation/step", {
      headers: await auth(request),
      data: {
        program: other.program,
        session: other.receipt.session,
        steps: 3,
        operation_id: operation(),
      },
    });
    expect(continued.ok()).toBe(true);
    expect((await continued.json()).last.time).toBe(1);
    await page
      .getByRole("button", { name: "Check local session cache", exact: true })
      .click();
    await expect(
      page.getByLabel("Local simulation session cleanup"),
    ).toContainText(`Local cache snapshot: ${baseline + 1}/25`);
  } finally {
    for (const receipt of own) await retire(request, receipt);
    await retire(request, other.receipt);
  }
});

for (const action of ["reset", "source", "pagehide", "unmount"])
  test(`late first receipt after ${action} is verified and retired before new scan admission`, async ({
    page,
    request,
  }) => {
    const baseline = await count(request);
    if (action === "unmount")
      await page.route("**/assets/index-*.js", async (route) => {
        const response = await route.fetch(),
          text = await response.text(),
          pattern =
            /(\w+\.createRoot\(document\.getElementById\("root"\)\))\.render\(/;
        expect(text).toMatch(pattern);
        await route.fulfill({
          response,
          body: text.replace(pattern, "(window.__sessionTestRoot=$1).render("),
        });
      });
    await load(page);
    let seen!: () => void,
      release!: () => void,
      retireSeen!: () => void,
      retireRelease!: () => void,
      receipt: any;
    const requested = new Promise<void>((r) => (seen = r)),
      gate = new Promise<void>((r) => (release = r)),
      retiring = new Promise<void>((r) => (retireSeen = r)),
      retireGate = new Promise<void>((r) => (retireRelease = r));
    await page.route("**/api/simulation/step", async (route) => {
      const response = await fetchSimulationResponse(route);
      receipt = await response.json();
      seen();
      await gate;
      await route.fulfill({ response, body: await response.body() });
    });
    await page.route("**/api/simulation/retire", async (route) => {
      const response = await route.fetch();
      expect(route.request().postDataJSON().session).toBe(receipt.session);
      retireSeen();
      await retireGate;
      await route.fulfill({ response, body: await response.body() });
    });
    try {
      await page.getByLabel("Step simulation", { exact: true }).click();
      await requested;
      expect(await count(request)).toBe(baseline + 1);
      if (action === "reset")
        await page.getByTitle("Reset simulation", { exact: true }).click();
      else if (action === "source")
        await page
          .getByLabel("Program name", { exact: true })
          .fill("Replaced pending source");
      else if (action === "pagehide")
        await page.evaluate(() =>
          window.dispatchEvent(
            new PageTransitionEvent("pagehide", { persisted: false }),
          ),
        );
      else
        await page.evaluate(() => (window as any).__sessionTestRoot.unmount());
      release();
      await retiring;
      if (action !== "unmount") {
        await expect(
          page.getByLabel("Step simulation", { exact: true }),
        ).toBeDisabled();
        await expect(
          page.getByTitle("Run simulation", { exact: true }),
        ).toBeDisabled();
        await expect(
          page.getByLabel("Simulation cleanup status"),
        ).toContainText("Releasing");
        await expect(page.locator(".elapsed")).toHaveText("0.0 s");
      }
      retireRelease();
      if (action !== "unmount")
        await expect(
          page.getByLabel("Step simulation", { exact: true }),
        ).toBeEnabled();
      await expect.poll(() => count(request)).toBe(baseline);
    } finally {
      release();
      retireRelease();
      await retire(request, receipt);
    }
  });

for (const mode of ["other-session", "wrong-creation"])
  test(`untrusted ${mode} receipt never retires another known session`, async ({
    page,
    request,
  }) => {
    const other = await seed(request);
    await load(page);
    let actual: any;
    const nominations: string[] = [];
    page.on("request", (r) => {
      if (r.url().endsWith("/api/simulation/retire"))
        nominations.push(r.postDataJSON().session);
    });
    await page.route("**/api/simulation/step", async (route) => {
      const response = await fetchSimulationResponse(route),
        value = await response.json();
      actual = structuredClone(value);
      if (mode === "other-session") {
        value.session = other.receipt.session;
        value.retirement_token = other.receipt.retirement_token;
      }
      value.session_creation_operation_id =
        other.receipt.session_creation_operation_id;
      await route.fulfill({ response, json: value });
    });
    try {
      await page.getByLabel("Step simulation", { exact: true }).click();
      await expect(page.locator(".simulation")).toContainText(
        "session ownership",
      );
      await expect(
        page.getByLabel("Step simulation", { exact: true }),
      ).toBeDisabled();
      await page.getByTitle("Reset simulation", { exact: true }).click();
      expect(nominations).not.toContain(other.receipt.session);
      const continued = await request.post("/api/simulation/step", {
        headers: await auth(request),
        data: {
          program: other.program,
          session: other.receipt.session,
          operation_id: operation(),
        },
      });
      expect(continued.ok()).toBe(true);
      expect((await continued.json()).last.time).toBe(0.5);
      await expect(
        page.getByLabel("Local simulation session cleanup"),
      ).toContainText("Unknown session IDs cannot be safely removed");
    } finally {
      await retire(request, actual);
      await retire(request, other.receipt);
    }
  });

test("failed cleanup is separate, gates new calculations and retries only on explicit request", async ({
  page,
  request,
}) => {
  const baseline = await count(request);
  await load(page);
  const receipt = await step(page);
  let attempts = 0,
    proof: any;
  await page.route("**/api/simulation/retire", async (route) => {
    attempts++;
    proof = route.request().postDataJSON();
    await route.fetch();
    await route.fulfill({
      status: 503,
      json: { detail: "Cleanup receipt unavailable" },
    });
  });
  try {
    await page.getByTitle("Reset simulation", { exact: true }).click();
    await expect(page.getByLabel("Simulation cleanup status")).toContainText(
      "unconfirmed",
    );
    await expect(
      page.getByLabel("Step simulation", { exact: true }),
    ).toBeDisabled();
    await expect(
      page.getByTitle("Run simulation", { exact: true }),
    ).toBeDisabled();
    await page.waitForTimeout(150);
    expect(attempts).toBe(1);
    await page.unroute("**/api/simulation/retire");
    const event = page.waitForRequest("**/api/simulation/retire");
    await page
      .getByRole("button", { name: "Retry session cleanup", exact: true })
      .click();
    expect((await event).postDataJSON()).toEqual(proof);
    await expect(
      page.getByLabel("Step simulation", { exact: true }),
    ).toBeEnabled();
    await expect.poll(() => count(request)).toBe(baseline);
  } finally {
    await retire(request, receipt);
  }
});

test("reset retires calculation state and preserves durable trends, active alarms and source lifecycle", async ({
  page,
  request,
}) => {
  const buffer = execFileSync(
    python,
    [
      "-c",
      "import json;from tests.test_observation_api import alarm_program;print(json.dumps(alarm_program()))",
    ],
    { cwd: root },
  );
  await page.goto("/");
  await page
    .locator(
      'input[type=file][accept=".json,.st,.xml,.graphml,.sedona.zip,.sax,.sab,.bog,.bas"]',
    )
    .setInputFiles({
      name: "recorded-source.bms.json",
      mimeType: "application/json",
      buffer,
    });
  await page.getByLabel("Persist history", { exact: true }).check();
  await page.getByLabel("Simulate temperature", { exact: true }).fill("90");
  const receipt = await step(page);
  try {
    const trends = await (
        await request.get("/api/observations/trends", {
          params: { source: receipt.recording_source },
        })
      ).json(),
      alarms = await (await request.get("/api/observations/alarms")).json(),
      sources = await (await request.get("/api/observations/sources")).json();
    expect(alarms.some((x: any) => x.active)).toBe(true);
    await page.getByTitle("Reset simulation", { exact: true }).click();
    await expect(
      page.getByLabel("Step simulation", { exact: true }),
    ).toBeEnabled();
    expect(
      await (
        await request.get("/api/observations/trends", {
          params: { source: receipt.recording_source },
        })
      ).json(),
    ).toEqual(trends);
    expect(
      await (await request.get("/api/observations/alarms")).json(),
    ).toEqual(alarms);
    expect(
      await (await request.get("/api/observations/sources")).json(),
    ).toEqual(sources);
  } finally {
    await retire(request, receipt);
  }
});

test("BFcache pagehide preserves known state; actual React unmount retires it", async ({
  page,
  request,
}) => {
  const baseline = await count(request);
  await page.route("**/assets/index-*.js", async (route) => {
    const response = await route.fetch(),
      text = await response.text(),
      pattern =
        /(\w+\.createRoot\(document\.getElementById\("root"\)\))\.render\(/;
    expect(text).toMatch(pattern);
    await route.fulfill({
      response,
      body: text.replace(pattern, "(window.__sessionTestRoot=$1).render("),
    });
  });
  await load(page);
  const first = await step(page);
  try {
    await page.evaluate(() =>
      window.dispatchEvent(
        new PageTransitionEvent("pagehide", { persisted: true }),
      ),
    );
    expect(await count(request)).toBe(baseline + 1);
    const next = await step(page);
    expect(next.session).toBe(first.session);
    expect(next.last.time).toBe(0.5);
    await page.evaluate(() => (window as any).__sessionTestRoot.unmount());
    await expect.poll(() => count(request)).toBe(baseline);
  } finally {
    await retire(request, first);
  }
});
