import { test, expect } from "@playwright/test";
import { spawn } from "node:child_process";
import {
  openMonitoringInterface,
  selectKnownMonitoringController,
  showControllerMonitor,
} from "./event-workspace";
import { chooseWorkspaceSurface } from "./workspace-navigation";
import { openMonitoring } from "./monitoring-navigation";
import { readFileSync } from "node:fs";
import path from "node:path";

const root = path.resolve("..");
async function controller() {
  const child = spawn(
    path.join(root, ".venv/bin/python"),
    [
      "-u",
      "-c",
      `
import asyncio
from tests.test_connections import application, free_udp, point
async def main():
    port=free_udp(); server=application(port,4190010)
    value=point(); value.covIncrement=0.1; server.add_object(value)
    await asyncio.sleep(0.05)
    print(port,flush=True)
    try: await asyncio.Event().wait()
    finally: server.close()
asyncio.run(main())
`,
    ],
    {
      cwd: root,
      stdio: ["ignore", "pipe", "pipe"],
      env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
    },
  );
  const port = await new Promise<number>((resolve, reject) => {
    let output = "";
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error("Loopback controller did not start"));
    }, 5000);
    child.once("error", reject);
    child.stdout!.on("data", (data) => {
      output += data.toString();
      if (output.includes("\n")) {
        clearTimeout(timer);
        resolve(Number(output.split("\n")[0]));
      }
    });
  });
  return { process: child, port };
}

test("Explicit real UDP COV recording survives UI reopen with native evidence export and distinct field provenance", async ({
  page,
  request,
}) => {
  const peer = await controller();
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  const token = (await (await request.get("/api/session")).json()).token;
  const headers = { "X-Studio-Token": token };
  try {
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    await openMonitoringInterface(page);
    await selectKnownMonitoringController(
      page,
      `127.0.0.1:${peer.port}`,
      "device,4190010",
    );
    await showControllerMonitor(page, "Live COV monitor");
    const panel = page.getByRole("region", {
      name: "BACnet COV monitoring",
      exact: true,
    });
    const checkbox = panel.getByRole("checkbox", {
      name: "Record COV receipts and eligible trends locally",
    });
    await expect(checkbox).not.toBeChecked();
    await expect(
      panel.getByLabel("COV device IP / port", { exact: true }),
    ).toHaveCount(0);
    await expect(
      panel.getByLabel("Expected COV Device", { exact: true }),
    ).toHaveCount(0);
    await panel
      .getByLabel("COV monitored object", { exact: true })
      .fill("analog-value,1");
    await checkbox.check();
    await panel
      .getByLabel("COV monitored object", { exact: true })
      .fill("analog-value,2");
    await expect(checkbox).not.toBeChecked();
    await panel
      .getByLabel("COV monitored object", { exact: true })
      .fill("analog-value,1");
    await checkbox.check();
    await panel
      .getByRole("button", { name: "Start verified COV monitor" })
      .click();
    await expect(panel).toContainText(/Local recording: active.*Saved: [1-9]/);
    const status = await (await request.get("/api/bacnet/cov/status")).json();
    const job = status.jobs.find((item: any) => item.active && item.recording);
    expect(job.config.address).toBe(`127.0.0.1:${peer.port}`);
    expect(job.config.device).toBe("device,4190010");
    const monitor = panel.getByRole("region", {
      name: `COV monitor ${job.id}`,
      exact: true,
    });
    await monitor
      .getByRole("button", { name: "Stop COV monitor", exact: true })
      .click();
    await expect(monitor).toContainText("Local recording: stopped");
    await showControllerMonitor(page, "Controller events");
    await showControllerMonitor(page, "Live COV monitor");
    await expect(
      panel.getByRole("checkbox", {
        name: "Record COV receipts and eligible trends locally",
      }),
    ).not.toBeChecked();
    expect(
      (
        await request.post("/api/bacnet/disconnect", { headers, data: {} })
      ).ok(),
    ).toBe(true);
    await page.reload();
    const fieldRequests: string[] = [];
    page.on("request", (r) => {
      if (r.method() === "POST" && r.url().includes("/api/bacnet/"))
        fieldRequests.push(r.url());
    });
    await chooseWorkspaceSurface(page, "History");
    await page
      .getByText("Change-of-value (COV) recordings", { exact: true })
      .click();
    const saved = page.getByRole("region", {
      name: "Saved COV observations",
      exact: true,
    });
    await saved
      .getByRole("button", { name: "Load saved COV observations" })
      .click();
    await saved
      .getByLabel("Saved COV recording", { exact: true })
      .selectOption(job.id);
    await expect(saved).toContainText("Controller timestamps are unknown");
    await expect(saved).toContainText("notification");
    const downloadPromise = page.waitForEvent("download");
    await saved
      .getByRole("button", { name: "Download saved COV page" })
      .click();
    const download = await downloadPromise;
    const evidence = JSON.parse(readFileSync((await download.path())!, "utf8"));
    const notification = evidence.events.find(
      (item: any) => item.event === "notification",
    );
    expect(notification.evidence.values[0].native_datatype).toBe("Real");
    expect(notification.evidence.values[0].value).toBe(12.5);
    expect(notification.source_clock).toBeNull();
    expect(evidence.recording.metadata.acquisition_kind).toBe("bacnet-cov");
    await openMonitoring(page, "Field recording");
    await page
      .getByLabel("Field trend source", { exact: true })
      .selectOption(job.recording.source);
    const samples = page.getByRole("region", {
      name: "Saved field trend samples",
      exact: true,
    });
    await expect(samples).toContainText(
      "COV receipt · controller clock unknown",
    );
    await expect(samples).toContainText("unknown");
    const csvPromise = page.waitForEvent("download");
    await samples
      .getByRole("button", { name: "Export field page CSV" })
      .click();
    const csv = readFileSync((await (await csvPromise).path())!, "utf8");
    expect(csv).toContain(
      '"acquisition_kind","clock_basis","source_clock","receipt_at","provenance"',
    );
    expect(csv).toContain('"bacnet-cov","receipt"');
    expect(fieldRequests).toEqual([]);
    expect(
      (await (await request.get("/api/bacnet/status")).json()).connected,
    ).toBe(false);
    expect(errors).toEqual([]);
  } finally {
    peer.process.kill();
    if (!page.isClosed()) {
      expect(
        (
          await request.post("/api/bacnet/disconnect", { headers, data: {} })
        ).ok(),
      ).toBe(true);
    }
  }
});
