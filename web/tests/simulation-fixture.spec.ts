import { simulationServerResponseJSON } from "./simulationFixture";
import { test, expect } from "./simulationFixture";
import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import path from "node:path";

test.describe.configure({ mode: "serial" });
let retained: any, owned: any, program: any;

test.afterAll(async ({ request }) => {
  const token = (await (await request.get("/api/session")).json()).token;
  for (const receipt of [retained, owned]) {
    if (!receipt?.session) continue;
    const response = await request.post("/api/simulation/retire", {
      headers: { "X-Studio-Token": token },
      data: {
        session: receipt.session,
        retirement_token: receipt.retirement_token,
        creation_operation_id: receipt.session_creation_operation_id,
      },
    });
    expect(response.ok()).toBe(true);
  }
});

test("create page-owned and independent engines before fixture teardown", async ({
  page,
  request,
}) => {
  const root = path.resolve("..");
  const buffer = execFileSync(
    path.join(root, ".venv/bin/python"),
    [
      "-c",
      "import json;from tests.test_simulation_clock_api import timer_program;print(json.dumps(timer_program()))",
    ],
    { cwd: root },
  );
  program = JSON.parse(buffer.toString());
  const token = (await (await request.get("/api/session")).json()).token;
  const response = await request.post("/api/simulation/step", {
    headers: { "X-Studio-Token": token },
    data: {
      program,
      operation_id: randomUUID().replaceAll("-", ""),
    },
  });
  expect(response.ok()).toBe(true);
  retained = await response.json();
  await page.goto("/");
  await page
    .locator(
      'input[type=file][accept=".json,.st,.xml,.graphml,.sedona.zip,.sax,.sab,.bog,.bas"]',
    )
    .setInputFiles({
      name: "fixture.bms.json",
      mimeType: "application/json",
      buffer,
    });
  await expect(page.locator(".toast")).toContainText(
    "Imported as a new local project",
  );
  const stepped = page.waitForResponse((r) =>
    r.url().endsWith("/api/simulation/step"),
  );
  await page.getByLabel("Step simulation", { exact: true }).click();
  owned = simulationServerResponseJSON(await stepped);
  expect(owned.session).not.toBe(retained.session);
  await expect(page.locator(".elapsed")).toHaveText("0.3 s");
});

test("fixture retired only its own engine while independent calculation remains usable", async ({
  request,
}) => {
  const token = (await (await request.get("/api/session")).json()).token;
  const missing = await request.post("/api/simulation/step", {
    headers: { "X-Studio-Token": token },
    data: { program, session: owned.session },
  });
  expect(missing.status()).toBe(422);
  expect((await missing.json()).detail).toContain("expired");
  const kept = await request.post("/api/simulation/step", {
    headers: { "X-Studio-Token": token },
    data: { program, session: retained.session },
  });
  expect(kept.ok()).toBe(true);
  expect((await kept.json()).last.time).toBe(0.5);
});

let held: any;
test("capture owns a real HTTP first receipt even when browser delivery is withheld until page close", async ({
  page,
}) => {
  const { fetchSimulationResponse } = await import("./simulationFixture");
  let seen!: () => void, release!: () => void;
  const entered = new Promise<void>((r) => (seen = r)),
    gate = new Promise<void>((r) => (release = r));
  await page.goto("/");
  await page.locator('input[type=file][accept*=".st"]').setInputFiles({
    name: "held-fixture.bms.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(program)),
  });
  await expect(page.locator(".toast")).toContainText(
    "Imported as a new local project",
  );
  await page.route("**/api/simulation/step", async (route) => {
    const response = await fetchSimulationResponse(route);
    held = await response.json();
    seen();
    await gate;
    if (!page.isClosed())
      await route.fulfill({ response, body: await response.body() });
  });
  await page.getByLabel("Step simulation", { exact: true }).click();
  await entered;
  expect(held.session).not.toBe(retained.session);
  await page.close();
  release();
});
test("withheld-reply teardown retires exactly its original server-owned engine and keeps independent state", async ({
  request,
}) => {
  const token = (await (await request.get("/api/session")).json()).token;
  const missing = await request.post("/api/simulation/step", {
    headers: { "X-Studio-Token": token },
    data: { program, session: held.session },
  });
  expect(missing.status()).toBe(422);
  expect((await missing.json()).detail).toContain("expired");
  const kept = await request.post("/api/simulation/step", {
    headers: { "X-Studio-Token": token },
    data: { program, session: retained.session },
  });
  expect(kept.ok()).toBe(true);
  expect((await kept.json()).last.time).toBe(0.75);
});

let failedKnown: any,
  failedObserved = false;
test("a failed acquisition cannot skip fixture cleanup of an earlier proved receipt", async ({
  page,
}) => {
  const { fetchSimulationResponse } = await import("./simulationFixture");
  await page.goto("/");
  await page.locator('input[type=file][accept*=".st"]').setInputFiles({
    name: "failed-capture.bms.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(program)),
  });
  await expect(page.locator(".toast")).toContainText(
    "Imported as a new local project",
  );
  const first = page.waitForResponse((r) =>
    r.url().endsWith("/api/simulation/step"),
  );
  await page.getByLabel("Step simulation", { exact: true }).click();
  failedKnown = simulationServerResponseJSON(await first);
  await expect(page.locator(".elapsed")).toHaveText("0.3 s");
  let entered!: () => void, release!: () => void;
  const requested = new Promise<void>((r) => (entered = r)),
    gate = new Promise<void>((r) => (release = r));
  // Keep acquisition pending when the body returns. Fixture page-close triggers
  // actual request-context disposal and rejection while teardown awaits it.
  page.once("close", () => {
    void page.context().request.dispose().finally(release);
  });
  await page.route("**/api/simulation/step", async (route) => {
    const delayed = {
      request: () => route.request(),
      fetch: async (options: Parameters<typeof route.fetch>[0]) => {
        entered();
        await gate;
        return route.fetch(options);
      },
    } as Parameters<typeof fetchSimulationResponse>[0];
    try {
      await fetchSimulationResponse(delayed);
      throw new Error("Disposed acquisition unexpectedly succeeded");
    } catch (error) {
      expect(String(error)).toMatch(/route\.fetch:.*(?:disposed|closed)/);
      failedObserved = true;
      if (!page.isClosed()) await route.abort();
    }
  });
  // The following case must prove fixture cleanup, independent of pagehide.
  await page.route("**/api/simulation/retire", (route) => route.abort());
  await page.getByLabel("Step simulation", { exact: true }).click();
  await requested;
});
test("failed acquisition teardown retired only its earlier proved engine", async ({
  request,
}) => {
  expect(failedObserved).toBe(true);
  const token = (await (await request.get("/api/session")).json()).token;
  const missing = await request.post("/api/simulation/step", {
    headers: { "X-Studio-Token": token },
    data: { program, session: failedKnown.session },
  });
  expect(missing.status()).toBe(422);
  expect((await missing.json()).detail).toContain("expired");
  const kept = await request.post("/api/simulation/step", {
    headers: { "X-Studio-Token": token },
    data: { program, session: retained.session },
  });
  expect(kept.ok()).toBe(true);
  expect((await kept.json()).last.time).toBe(1);
});
