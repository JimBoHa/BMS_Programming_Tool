import { test, expect } from "@playwright/test";
import { spawn } from "node:child_process";
import { createSocket } from "node:dgram";
import { readFileSync } from "node:fs";
import path from "node:path";

const root = path.resolve("..");
async function freePort(): Promise<number> {
  const socket = createSocket("udp4");
  return new Promise((resolve, reject) => {
    socket.once("error", reject);
    socket.bind(0, "127.0.0.1", () => {
      const address = socket.address();
      socket.close(() =>
        resolve(typeof address === "string" ? 0 : address.port),
      );
    });
  });
}
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
    await request.post("/api/bacnet/connect", {
      headers,
      data: { local_address: `127.0.0.1:${await freePort()}` },
    });
    await page.goto("/");
    await page.getByRole("button", { name: "Connect", exact: true }).click();
    const panel = page.getByRole("region", {
      name: "BACnet COV monitoring",
      exact: true,
    });
    const checkbox = panel.getByRole("checkbox", {
      name: "Record COV receipts and eligible trends locally",
    });
    await expect(checkbox).not.toBeChecked();
    await panel
      .getByLabel("COV device IP / port", { exact: true })
      .fill(`127.0.0.1:${peer.port}`);
    await panel
      .getByLabel("Expected COV Device", { exact: true })
      .fill("device,4190010");
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
    const monitor = panel.getByRole("region", {
      name: `COV monitor ${job.id}`,
      exact: true,
    });
    await monitor
      .getByRole("button", { name: "Stop COV monitor", exact: true })
      .click();
    await expect(monitor).toContainText("Local recording: stopped");
    await page.reload();
    await page.getByRole("button", { name: "Connect", exact: true }).click();
    await expect(
      panel.getByRole("checkbox", {
        name: "Record COV receipts and eligible trends locally",
      }),
    ).not.toBeChecked();
    const saved = panel.getByRole("region", {
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
    await page
      .getByRole("button", { name: "Field trends", exact: true })
      .click();
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
    expect(errors).toEqual([]);
  } finally {
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    peer.process.kill();
  }
});
