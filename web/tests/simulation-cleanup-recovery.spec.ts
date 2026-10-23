import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import path from "node:path";
import { test, expect, simulationServerResponseJSON } from "./simulationFixture";

const root = path.resolve(".."),
  python = path.join(root, ".venv/bin/python");
function program() {
  return JSON.parse(
    execFileSync(
      python,
      ["-c", "import json;from tests.test_simulation_clock_api import timer_program;print(json.dumps(timer_program()))"],
      { cwd: root, encoding: "utf8" },
    ),
  );
}
for (const action of ["reset", "pagehide"] as const)
  test(`a failed ${action} retirement survives reload and releases only its owned session`, async ({ page, request }) => {
    const headers = { "X-Studio-Token": (await (await request.get("/api/session")).json()).token };
    const count = async () => (await (await request.get("/api/simulation/sessions/status")).json()).cached_sessions;
    const baseline = await count();
    const otherProgram = { ...program(), id: "other-" + randomUUID() };
    const otherResponse = await request.post("/api/simulation/step", { headers, data: { program: otherProgram, operation_id: randomUUID().replaceAll("-", "") } });
    expect(otherResponse.ok()).toBe(true);
    const other = await otherResponse.json();
    let own: any;
    try {
      await page.goto("/");
      await page.locator('input[type=file][accept=".json,.st,.xml,.graphml,.sedona.zip,.sax,.sab,.bog,.bas"]').setInputFiles({ name: "recovery.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(program())) });
      await expect(page.locator(".toast")).toContainText("Imported as a new local project");
      const response = page.waitForResponse(r => r.url().endsWith("/api/simulation/step") && r.request().method() === "POST");
      await page.getByLabel("Step simulation", { exact: true }).click();
      own = simulationServerResponseJSON(await response);
      await expect(page.locator(".elapsed")).toHaveText(own.last.time.toFixed(1) + " s");
      let aborted = false;
      await page.route("**/api/simulation/retire", async route => {
        if (!aborted && route.request().postDataJSON().session === own.session) {
          aborted = true;
          await route.abort("failed");
        } else await route.fallback();
      });
      if (action === "reset") await page.getByTitle("Reset simulation", { exact: true }).click();
      else await page.evaluate(() => window.dispatchEvent(new PageTransitionEvent("pagehide", { persisted: false })));
      await expect(page.getByRole("button", { name: "Retry session cleanup", exact: true })).toBeVisible();
      expect(aborted).toBe(true);
      expect(await count()).toBe(baseline + 2);
      await page.reload();
      await expect(page.getByLabel("Program name", { exact: true })).toBeVisible();
      await expect.poll(count).toBe(baseline + 1);
      const continued = await request.post("/api/simulation/step", { headers, data: { program: otherProgram, session: other.session, operation_id: randomUUID().replaceAll("-", "") } });
      expect(continued.ok()).toBe(true);
      expect((await continued.json()).session).toBe(other.session);
    } finally {
      for (const receipt of [own, other]) {
        if (!receipt?.session) continue;
        const result = await request.post("/api/simulation/retire", { headers, data: { session: receipt.session, retirement_token: receipt.retirement_token, creation_operation_id: receipt.session_creation_operation_id } });
        expect(result.ok()).toBe(true);
      }
    }
  });
