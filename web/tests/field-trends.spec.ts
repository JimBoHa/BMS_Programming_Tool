import { test, expect } from "@playwright/test";
import { spawn, type ChildProcess } from "node:child_process";
import path from "node:path";
import { readFileSync } from "node:fs";
import { createSocket } from "node:dgram";

const root = path.resolve("..");
async function freePort(): Promise<number> {
  const socket = createSocket("udp4");
  return new Promise((resolve, reject) => {
    socket.once("error", reject);
    socket.bind(0, "127.0.0.1", () => {
      const address = socket.address();
      const port = typeof address === "string" ? 0 : address.port;
      socket.close(() => resolve(port));
    });
  });
}
async function controller(): Promise<{ process: ChildProcess; port: number }> {
  const process = spawn(
    path.join(root, ".venv/bin/python"),
    [
      "-u",
      "-c",
      `
import asyncio
from tests.test_connections import application,free_udp,point
async def main():
    port=free_udp()
    server=application(port,4190026)
    value=point(); value.reliability='no-fault-detected'
    server.add_object(value)
    print(port,flush=True)
    try: await asyncio.Event().wait()
    finally: server.close()
asyncio.run(main())
`,
    ],
    { cwd: root, stdio: ["ignore", "pipe", "pipe"] },
  );
  const port = await new Promise<number>((resolve, reject) => {
    let output = "";
    const timeout = setTimeout(() => {
      process.kill();
      reject(new Error("Loopback controller did not start"));
    }, 5000);
    process.on("error", (error) => {
      clearTimeout(timeout);
      reject(error);
    });
    process.stdout!.on("data", (data) => {
      output += data.toString();
      if (output.includes("\n")) {
        clearTimeout(timeout);
        resolve(Number(output.split("\n")[0]));
      }
    });
    process.on("exit", (code) => {
      clearTimeout(timeout);
      if (!output) reject(new Error(`Loopback controller exited ${code}`));
    });
  });
  return { process, port };
}

test("field sampling persists actual loopback BACnet values and CSV with verified quality", async ({
  page,
  request,
}) => {
  const server = await controller();
  const token = (await (await request.get("/api/session")).json()).token;
  const headers = { "X-Studio-Token": token };
  let jobId = "";
  try {
    await page.goto("/");
    await page
      .getByRole("button", { name: "Field trends", exact: true })
      .click();
    await expect(
      page.getByRole("button", { name: "Start field sampling", exact: true }),
    ).toBeDisabled();
    await page.getByRole("button", { name: "Connect", exact: true }).click();
    const opened = await request.post("/api/bacnet/connect", {
      headers,
      data: { local_address: `127.0.0.1:${await freePort()}` },
    });
    expect(opened.ok()).toBeTruthy();
    await page
      .getByRole("button", { name: "Field trends", exact: true })
      .click();
    await page
      .getByLabel("Trend job name", { exact: true })
      .fill("Browser loopback temperature");
    await page
      .getByLabel("Field signal 1", { exact: true })
      .fill("zone_temperature");
    await page
      .getByLabel("Field address 1", { exact: true })
      .fill(`127.0.0.1:${server.port}`);
    await page
      .getByLabel("Field object identifier 1", { exact: true })
      .fill("analog-value,1");
    await page.getByLabel("Field unit 1", { exact: true }).fill("degF");
    await page.getByLabel("Field sampling interval", { exact: true }).fill("5");
    const started = page.waitForResponse(
      (response) =>
        response.url().endsWith("/api/field-trends/start") &&
        response.request().method() === "POST",
    );
    await page
      .getByRole("button", { name: "Start field sampling", exact: true })
      .click();
    const response = await started;
    expect(response.ok()).toBeTruthy();
    const job = await response.json();
    jobId = job.id;
    await page
      .getByLabel("Field trend source", { exact: true })
      .selectOption(job.source);
    const samples = page.getByRole("region", {
      name: "Saved field trend samples",
    });
    // Older COV receipts may have the same value; wait for this poll source.
    await expect(samples).toContainText("zone_temperature", { timeout: 15000 });
    await expect(samples).toContainText("12.5");
    await expect(samples).toContainText("good");
    await expect(samples).toContainText("degF");
    const event = page.waitForEvent("download");
    await page
      .getByRole("button", { name: "Export field page CSV", exact: true })
      .click();
    const file = await event;
    const csv = readFileSync((await file.path())!, "utf8");
    expect(csv).toContain('"field"');
    expect(csv).toContain('"12.5"');
    expect(csv).toContain('"good"');
    await page
      .getByRole("button", { name: "Stop sampling", exact: true })
      .click();
    await expect(
      page.getByRole("region", { name: "Field sampling jobs" }),
    ).toContainText("stopped");
    await page.reload();
    await page
      .getByRole("button", { name: "Field trends", exact: true })
      .click();
    // Reentry starts with the bounded All-sources page, which can contain only
    // older COV receipts. Select this job's persisted polling source explicitly.
    await page
      .getByLabel("Field trend source", { exact: true })
      .selectOption(job.source);
    await expect(
      page.getByLabel("Field trend source", { exact: true }),
    ).toHaveValue(job.source);
    await expect(samples).toContainText("zone_temperature");
    await expect(samples).toContainText("12.5");
    await samples
      .locator("table")
      .screenshot({ path: "test-results/studio-field-samples.png" });
    await page.screenshot({
      path: "test-results/studio-field-trends.png",
      fullPage: true,
    });
    await page
      .getByLabel("Field trend source", { exact: true })
      .selectOption(job.source);
    await page
      .getByRole("button", { name: "Delete ended field history", exact: true })
      .click();
    await expect(
      samples.locator("tbody tr").filter({ hasText: job.source }),
    ).toHaveCount(0);
    expect(
      (await (await request.get("/api/field-trends/sources")).json()).some(
        (s: any) => s.source === job.source,
      ),
    ).toBe(false);
  } finally {
    if (jobId)
      await request.post("/api/field-trends/stop", {
        headers,
        data: { id: jobId },
      });
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    server.process.kill();
  }
});

test("invalid field target fails visibly and does not start acquisition", async ({
  page,
  request,
}) => {
  const token = (await (await request.get("/api/session")).json()).token;
  const headers = { "X-Studio-Token": token };
  try {
    const opened = await request.post("/api/bacnet/connect", {
      headers,
      data: { local_address: `127.0.0.1:${await freePort()}` },
    });
    expect(opened.ok()).toBeTruthy();
    await page.goto("/");
    await page
      .getByRole("button", { name: "Field trends", exact: true })
      .click();
    await page.getByLabel("Field address 1", { exact: true }).fill("*");
    await page
      .getByRole("button", { name: "Start field sampling", exact: true })
      .click();
    await expect(page.getByRole("alert")).toContainText("unicast");
    expect(
      (await (await request.get("/api/field-trends/status")).json())
        .running_jobs,
    ).toBe(0);
  } finally {
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
  }
});
