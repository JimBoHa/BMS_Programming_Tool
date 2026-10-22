import {
  test,
  expect,
  fetchSimulationResponse,
  simulationServerResponseJSON,
  simulationServerResponseText,
} from "./simulationFixture";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { writeFileSync } from "node:fs";
test("actual HTTP capture stays private, forwards unchanged, and creates only one owned engine", async ({
  page,
  request,
}, info) => {
  const root = path.resolve(".."),
    python = path.join(root, ".venv/bin/python");
  const buffer = execFileSync(
    python,
    [
      "-c",
      "import json;from tests.test_simulation_clock_api import timer_program;print(json.dumps(timer_program()))",
    ],
    { cwd: root },
  );
  const before = (
    await (await request.get("/api/simulation/sessions/status")).json()
  ).cached_sessions;
  await page.goto("/");
  await page.locator('input[type=file][accept*=".st"]').setInputFiles({
    name: "capture.bms.json",
    mimeType: "application/json",
    buffer,
  });
  await expect(page.locator(".toast")).toContainText(
    "Imported as a new local project",
  );
  let requests = 0,
    raw = Buffer.alloc(0),
    length = 0;
  await page.route("**/api/simulation/step", async (route) => {
    requests++;
    const response = await fetchSimulationResponse(route),
      bytes = await response.body();
    raw = Buffer.from(bytes);
    length = Number(response.headers()["content-length"]);
    bytes.fill(0); // Caller mutation must never affect the fixture's private source copy.
    await route.fulfill({ response, body: raw });
  });
  const pending = page.waitForResponse((r) =>
    r.url().endsWith("/api/simulation/step"),
  );
  await page.getByLabel("Step simulation", { exact: true }).click();
  const response = await pending;
  const receipt = simulationServerResponseJSON(response),
    text = simulationServerResponseText(response);
  expect(response.ok()).toBe(true);
  expect(Buffer.from(text)).toEqual(raw);
  expect(raw.length).toBe(length);
  expect(receipt.completed_steps).toBe(1);
  expect(receipt.last.time).toBe(0.25);
  await expect(page.locator(".elapsed")).toHaveText("0.3 s");
  expect(requests).toBe(1);
  expect(
    (await (await request.get("/api/simulation/sessions/status")).json())
      .cached_sessions,
  ).toBe(before + 1);
  writeFileSync(info.outputPath("original-server-response.json"), raw);
  execFileSync(
    python,
    [
      "-c",
      "import json,sys;v=json.load(sys.stdin);assert v['completed_steps']==1 and v['last']['time']==.25",
    ],
    { input: raw },
  );
});
