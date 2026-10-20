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
      const port = typeof address === "string" ? 0 : address.port;
      socket.close(() => resolve(port));
    });
  });
}
async function objectPeer() {
  const child = spawn(
    path.join(root, ".venv/bin/python"),
    [
      "-u",
      "-c",
      `
import asyncio,json,sys
from tests.test_connections import application,point,free_udp
from bms_tool.bacnet_read import close_application
async def main():
    port=free_udp();app=application(port,4190032)
    for number in range(1,6):
        value=point();value.objectIdentifier=('analog-value',number);value.objectName='Loopback value '+str(number);app.add_object(value)
    original=app.do_ReadPropertyRequest
    delayed=False
    async def read(request):
        nonlocal delayed
        if str(request.propertyIdentifier)=='object-list' and request.propertyArrayIndex==4 and not delayed:
            delayed=True
            await asyncio.sleep(1.25)
            return
        await original(request)
    app.do_ReadPropertyRequest=read
    await asyncio.sleep(.05)
    print(json.dumps({'port':port,'total':len(app.objectIdentifier)}),flush=True)
    try: await asyncio.to_thread(sys.stdin.readline)
    finally: close_application(app);await asyncio.sleep(.05)
asyncio.run(main())
`,
    ],
    { cwd: root, stdio: ["pipe", "pipe", "pipe"] },
  );
  let error = "";
  child.stderr.on("data", (data) => {
    error += data.toString();
  });
  const data = await new Promise<{ port: number; total: number }>(
    (resolve, reject) => {
      let output = "",
        ready = false;
      const timer = setTimeout(() => {
        child.kill();
        reject(new Error("Object peer startup timed out: " + error));
      }, 6000);
      child.stdout.on("data", (data) => {
        output += data.toString();
        if (!ready && output.includes("\n")) {
          ready = true;
          clearTimeout(timer);
          resolve(JSON.parse(output.split("\n")[0]));
        }
      });
      child.on("error", (error) => {
        clearTimeout(timer);
        reject(error);
      });
      child.on("exit", (code) => {
        clearTimeout(timer);
        if (!ready) reject(new Error(`Object peer exited ${code}: ${error}`));
      });
    },
  );
  return {
    ...data,
    async close() {
      const finished = new Promise<number | null>((resolve) =>
        child.once("exit", resolve),
      );
      child.stdin.end("close\n");
      const timer = setTimeout(() => child.kill(), 2000);
      const code = await finished;
      clearTimeout(timer);
      expect(code, error).toBe(0);
    },
  };
}

test("object-list pages preserve actual UDP partial reads, explicit continuation and exact JSON evidence", async ({
  page,
  request,
}) => {
  const peer = await objectPeer();
  const target = `127.0.0.1:${peer.port}`;
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  try {
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    await page.goto("/");
    await page.getByRole("button", { name: "Connect", exact: true }).click();
    await page
      .getByLabel("Local bind address / UDP port", { exact: true })
      .fill(`127.0.0.1:${await freePort()}`);
    await page
      .getByLabel("BBMD address / UDP port (optional)", { exact: true })
      .fill("");
    await page.getByLabel("Router IP (optional)", { exact: true }).fill("");
    await page
      .getByLabel("MS/TP destination network (optional)", { exact: true })
      .fill("");
    await page
      .getByRole("button", { name: "Open interface", exact: true })
      .click();
    await expect(
      page.getByRole("button", { name: "Read object list", exact: true }),
    ).toBeEnabled();
    await page.getByLabel("Unicast target", { exact: true }).fill(target);
    await page
      .getByLabel("Object identifier", { exact: true })
      .fill("device,4190032");
    await page.getByLabel("Object-list page size", { exact: true }).fill("2");
    await page
      .getByLabel("Object-list deadline seconds", { exact: true })
      .fill("1");
    await page
      .getByRole("button", { name: "Read object list", exact: true })
      .click();
    const report = page.getByRole("region", {
      name: "BACnet object-list page",
      exact: true,
    });
    await expect(report.locator("tbody tr")).toHaveCount(2);
    await expect(report).toContainText("Page request completed");
    await expect(report).toContainText(`Device total ${peer.total}`);
    await expect(report).toContainText("Further indices remain");
    await report
      .getByRole("button", { name: "Read next object-list page", exact: true })
      .click();
    await expect(
      page.getByLabel("Unicast target", { exact: true }),
    ).toBeDisabled();
    await expect(report).toContainText("Page request incomplete");
    await expect(report.getByRole("alert")).toContainText("timed out");
    await expect(report.locator("tbody tr")).toHaveCount(1);
    await expect(report.locator("tbody tr")).toContainText("analog-value,1");
    const downloading = page.waitForEvent("download");
    await report
      .getByRole("button", {
        name: "Download shown object-list JSON",
        exact: true,
      })
      .click();
    const archived = JSON.parse(
      readFileSync((await (await downloading).path())!, "utf8"),
    );
    expect(archived).toMatchObject({
      address: target,
      device: "device,4190032",
      offset: 2,
      limit: 2,
      next_offset: 3,
      complete: false,
      truncated: true,
      objects: [{ object: "analog-value,1", index: 3 }],
    });
    expect(archived.error).toContain("timed out");
    await report
      .getByRole("button", { name: "Read next object-list page", exact: true })
      .click();
    await expect(report).toContainText("Offset 3");
    await expect(report.locator("tbody tr")).toHaveCount(2);
    await expect(report).toContainText("Page request completed");
    await expect(report.getByRole("alert")).toHaveCount(0);
    await report
      .getByRole("button", { name: "Read next object-list page", exact: true })
      .click();
    await expect(report).toContainText("Offset 5");
    await expect(
      report.getByRole("button", {
        name: "Read next object-list page",
        exact: true,
      }),
    ).toHaveCount(0);
    await page
      .getByLabel("Object identifier", { exact: true })
      .fill("analog-value,1");
    await expect(report).toHaveCount(0);
    await expect(
      page.getByLabel("Object-list offset", { exact: true }),
    ).toHaveValue("0");
  } finally {
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    await peer.close();
  }
});
