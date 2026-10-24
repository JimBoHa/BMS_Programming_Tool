import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import path from "node:path";
import {
  test,
  expect,
  simulationServerResponseJSON,
} from "./simulationFixture";

const root = path.resolve(".."),
  python = path.join(root, ".venv/bin/python");
function program() {
  return JSON.parse(
    execFileSync(
      python,
      [
        "-c",
        "import json;from tests.test_simulation_clock_api import timer_program;print(json.dumps(timer_program()))",
      ],
      { cwd: root, encoding: "utf8" },
    ),
  );
}
for (const { action, delayedAuth } of [
  { action: "reset", delayedAuth: false },
  { action: "pagehide", delayedAuth: false },
  { action: "reset", delayedAuth: true },
] as const)
  test(`a failed ${action} retirement survives reload${delayedAuth ? " after delayed authentication" : ""} and releases only its owned session`, async ({
    page,
    request,
  }) => {
    const headers = {
      "X-Studio-Token": (await (await request.get("/api/session")).json())
        .token,
    };
    const count = async () =>
      (await (await request.get("/api/simulation/sessions/status")).json())
        .cached_sessions;
    const baseline = await count();
    const otherProgram = { ...program(), id: "other-" + randomUUID() };
    const otherResponse = await request.post("/api/simulation/step", {
      headers,
      data: {
        program: otherProgram,
        operation_id: randomUUID().replaceAll("-", ""),
      },
    });
    expect(otherResponse.ok()).toBe(true);
    const other = await otherResponse.json();
    let own: any;
    try {
      await page.goto("/");
      await page
        .locator(
          'input[type=file][accept=".json,.st,.xml,.graphml,.sedona.zip,.sax,.sab,.bog,.bas"]',
        )
        .setInputFiles({
          name: "recovery.json",
          mimeType: "application/json",
          buffer: Buffer.from(JSON.stringify(program())),
        });
      await expect(page.locator(".toast")).toContainText(
        "Imported as a new local project",
      );
      const response = page.waitForResponse(
        (r) =>
          r.url().endsWith("/api/simulation/step") &&
          r.request().method() === "POST",
      );
      await page.getByLabel("Step simulation", { exact: true }).click();
      own = simulationServerResponseJSON(await response);
      await expect(page.locator(".elapsed")).toHaveText(
        own.last.time.toFixed(1) + " s",
      );
      let aborted = false,
        retirements = 0;
      await page.route("**/api/simulation/retire", async (route) => {
        if (route.request().postDataJSON().session === own.session)
          retirements++;
        if (
          !aborted &&
          route.request().postDataJSON().session === own.session
        ) {
          aborted = true;
          await route.abort("failed");
        } else await route.fallback();
      });
      if (action === "reset")
        await page.getByTitle("Reset simulation", { exact: true }).click();
      else
        await page.evaluate(() =>
          window.dispatchEvent(
            new PageTransitionEvent("pagehide", { persisted: false }),
          ),
        );
      await expect(
        page.getByRole("button", {
          name: "Retry session cleanup",
          exact: true,
        }),
      ).toBeVisible();
      expect(aborted).toBe(true);
      expect(await count()).toBe(baseline + 2);
      let releaseAuth: (() => void) | null = null;
      let authSeen: (() => void) | null = null;
      const authRequested = new Promise<void>((resolve) => {
        authSeen = resolve;
      });
      const authGate = new Promise<void>((resolve) => {
        releaseAuth = resolve;
      });
      if (delayedAuth)
        await page.route("**/api/session", async (route) => {
          const response = await route.fetch({
            maxRedirects: 0,
            maxRetries: 0,
          });
          const body = await response.body();
          authSeen!();
          await authGate;
          await route.fulfill({ response, body });
        });
      await page.reload();
      if (delayedAuth) {
        await authRequested;
        expect(retirements).toBe(1);
        expect(await count()).toBe(baseline + 2);
        releaseAuth!();
      }
      await expect(
        page.getByLabel("Program name", { exact: true }),
      ).toBeVisible();
      await expect.poll(count).toBe(baseline + 1);
      await expect.poll(() => retirements).toBe(2);
      const continued = await request.post("/api/simulation/step", {
        headers,
        data: {
          program: otherProgram,
          session: other.session,
          operation_id: randomUUID().replaceAll("-", ""),
        },
      });
      expect(continued.ok()).toBe(true);
      expect((await continued.json()).session).toBe(other.session);
    } finally {
      for (const receipt of [own, other]) {
        if (!receipt?.session) continue;
        const result = await request.post("/api/simulation/retire", {
          headers,
          data: {
            session: receipt.session,
            retirement_token: receipt.retirement_token,
            creation_operation_id: receipt.session_creation_operation_id,
          },
        });
        expect(result.ok()).toBe(true);
      }
    }
  });
