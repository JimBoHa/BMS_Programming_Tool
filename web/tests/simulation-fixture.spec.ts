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
  owned = await (await stepped).json();
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
