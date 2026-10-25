import { test, expect } from "@playwright/test";
import { spawn } from "node:child_process";
import path from "node:path";
import { freePort } from "./workflow-peer";

const root = path.resolve("..");
test("native application capture, stale review, one transfer and physical-station readback", async ({
  page,
  request,
}) => {
  test.setTimeout(60000);
  const child = spawn(
    path.join(root, ".venv/bin/python"),
    [
      "-u",
      "-c",
      `
import asyncio
from tests.test_native_applications import NativePeer,port
from bacpypes3.local.device import DeviceObject
from bacpypes3.local.networkport import NetworkPortObject
async def main():
 p=port();app=NativePeer.from_object_list([DeviceObject(objectIdentifier=('device',5136),objectName='Authored controller',vendorIdentifier=5),NetworkPortObject(f'127.0.0.1:{p}',objectIdentifier=('network-port',1),objectName='Isolated native peer')]);app.setup()
 print(p,flush=True)
 try:await asyncio.Event().wait()
 finally:app.close()
asyncio.run(main())
`,
    ],
    {
      cwd: root,
      env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  let errors = "";
  child.stderr!.on("data", (data) => (errors += data.toString()));
  try {
    const endpoint = await new Promise<string>((resolve, reject) => {
      let output = "";
      const timeout = setTimeout(
        () => reject(new Error(errors || "Native peer did not start")),
        10000,
      );
      child.stdout!.on("data", (data) => {
        output += data.toString();
        if (output.includes("\n")) {
          clearTimeout(timeout);
          resolve(`127.0.0.1:${Number(output.trim().split("\n")[0])}`);
        }
      });
      child.once("exit", (code) => {
        clearTimeout(timeout);
        reject(new Error(`Native peer ${code}: ${errors}`));
      });
    });
    const headers = {
      "X-Studio-Token": (await (await request.get("/api/session")).json())
        .token,
    };
    expect(
      (
        await request.post("/api/bacnet/disconnect", { headers, data: {} })
      ).ok(),
    ).toBeTruthy();
    await page.goto("/");
    await page
      .getByRole("button", { name: /^Connect to a controller/ })
      .click();
    await page
      .getByLabel("Local bind address / UDP port", { exact: true })
      .fill(`127.0.0.1:${await freePort()}`);
    await page
      .getByRole("button", { name: "Open interface", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Known controller address", exact: true })
      .click();
    await page
      .getByLabel("Known controller address", { exact: true })
      .fill(endpoint);
    await page
      .getByLabel("Known Device object", { exact: true })
      .fill("device,5136");
    await page
      .getByRole("region", { name: "Known controller connection" })
      .getByRole("button", { name: "Open controller", exact: true })
      .click();
    await expect(
      page.getByRole("region", { name: "Controller overview" }),
    ).toContainText("Authored controller");
    await page
      .getByRole("button", { name: "Edit instance number", exact: true })
      .click();
    await page
      .getByLabel("Instance change method", { exact: true })
      .selectOption("native");
    const panel = page.getByRole("region", {
      name: "Native application instance commissioning",
      exact: true,
    });
    await panel.getByText(/^Transfer credentials/).click();
    await panel
      .getByLabel("Backup credential", { exact: true })
      .fill("authored-backup");
    await panel
      .getByLabel("Application transfer credential", { exact: true })
      .fill("authored-restore");
    await panel
      .getByRole("button", {
        name: "Save private transfer credentials",
        exact: true,
      })
      .click();
    await expect(
      panel.getByLabel("Backup credential", { exact: true }),
    ).toHaveValue("");
    await panel
      .getByRole("button", { name: "Read application backup", exact: true })
      .click();
    await expect(
      panel.getByLabel("Captured native application", { exact: true }),
    ).toContainText("7 application records");
    const number = panel.getByLabel(
      "New application Device instance (0–4194302)",
      { exact: true },
    );
    await number.fill("5336");
    let reply = page.waitForResponse((response) =>
      response.url().endsWith("/native-application/preview"),
    );
    await panel
      .getByRole("button", {
        name: "Review application instance change",
        exact: true,
      })
      .click();
    const stalePlan = await (await reply).json();
    const cancelled = page.waitForResponse((response) =>
      response.url().endsWith("/native-application/cancel"),
    );
    await number.fill("5337");
    await cancelled;
    await expect(
      panel.getByLabel("Reviewed native application transfer", { exact: true }),
    ).toHaveCount(0);
    const stale = await request.post(
      "/api/bacnet/controller/native-application/apply",
      {
        headers,
        data: {
          operation_id: "stale-native-apply",
          token: stalePlan.token,
          review_sha256: stalePlan.review_sha256,
          allocation_confirmed: true,
          application_transfer_confirmed: true,
        },
      },
    );
    expect(stale.status()).toBe(422);
    await number.fill("5336");
    await panel
      .getByRole("button", {
        name: "Review application instance change",
        exact: true,
      })
      .click();
    await expect(
      panel.getByLabel("Reviewed native application transfer", { exact: true }),
    ).toContainText("5136 → 5336");
    const apply = panel.getByRole("button", {
      name: "Apply application instance change",
      exact: true,
    });
    await expect(apply).toBeDisabled();
    await panel
      .getByRole("checkbox", { name: /I reserved this instance/ })
      .check();
    await expect(apply).toBeDisabled();
    await panel
      .getByRole("checkbox", { name: /I reviewed this application transfer/ })
      .check();
    reply = page.waitForResponse((response) =>
      response.url().endsWith("/native-application/apply"),
    );
    await apply.click();
    const result = await (await reply).json();
    expect(result.result.status, JSON.stringify(result)).toBe("verified");
    expect(result.pending).toBe(false);
    await expect(
      panel.getByLabel("Native application transfer receipt", { exact: true }),
    ).toContainText("verified_new");
    await expect(
      panel.getByLabel("Native application transfer receipt", { exact: true }),
    ).toContainText("matches transferred application");
    await expect(
      page.getByLabel("Selected controller path", { exact: true }),
    ).toContainText("device,5336");
    await panel.screenshot({
      path: test.info().outputPath("native-application-verified.png"),
    });
    expect(errors).toBe("");
  } finally {
    child.kill("SIGTERM");
  }
});
