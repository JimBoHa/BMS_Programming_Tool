import { test, expect } from "@playwright/test";
import { spawn } from "node:child_process";
import path from "node:path";
import { freePort } from "./workflow-peer";

test("schedule discovery prepares the next source-owned page without another field read", async ({
  page,
}) => {
  const root = path.resolve("..");
  const child = spawn(
    path.join(root, ".venv/bin/python"),
    [
      "-u",
      "-c",
      `
import asyncio
from tests.test_schedule_inventory import SchedulePeer,text,unsigned
class Peer(SchedulePeer):
 def value(self,obj,prop,index):
  if prop in ('model-name','firmware-revision','application-software-version','vendor-name','location'):return text('Authored')
  if prop=='protocol-revision':return unsigned(22)
  if prop=='max-apdu-length-accepted':return unsigned(480)
  if prop=='segmentation-supported':return b'\\x91\\x03'
  if prop=='vendor-identifier':return unsigned(5)
  if prop=='system-status':return b'\\x91\\x00'
  return super().value(obj,prop,index)
 async def reply(self,data,source):
  await super().reply(data,source)
  print('READ',flush=True)
async def main():
 p=Peer();t,_=await asyncio.get_running_loop().create_datagram_endpoint(lambda:p,local_addr=('127.0.0.1',0))
 print(p.endpoint,flush=True)
 try:await asyncio.Event().wait()
 finally:t.close()
asyncio.run(main())
`,
    ],
    {
      cwd: root,
      env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  let reads = 0;
  const endpoint = await new Promise<string>((resolve, reject) => {
    let pending = "",
      ready = false;
    child.stdout!.on("data", (data) => {
      pending += data.toString();
      while (pending.includes("\n")) {
        const n = pending.indexOf("\n");
        const line = pending.slice(0, n);
        pending = pending.slice(n + 1);
        if (!ready) {
          ready = true;
          resolve(line);
        } else if (line === "READ") reads++;
      }
    });
    child.once("error", reject);
    child.once("exit", (code) => {
      if (!ready) reject(new Error("Peer exited " + code));
    });
  });
  const calls: any[] = [];
  page.on("request", (r) => {
    if (r.url().endsWith("/api/bacnet/schedules/read"))
      calls.push(r.postDataJSON());
  });
  try {
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
      .fill("device,42");
    await page
      .getByRole("region", { name: "Known controller connection" })
      .getByRole("button", { name: "Open controller", exact: true })
      .click();
    await expect(
      page.getByRole("region", { name: "Controller overview" }),
    ).toBeVisible();
    await page
      .getByRole("navigation", { name: "Workspace tasks" })
      .getByRole("button", { name: "Schedules", exact: true })
      .click();
    const panel = page.getByRole("region", {
      name: "Native Calendar and Schedule inventory",
      exact: true,
    });
    await panel
      .getByLabel("Schedule Object_List page limit", { exact: true })
      .fill("2");
    await panel
      .getByRole("button", { name: "Read native schedules", exact: true })
      .click();
    const prepare = panel.getByRole("button", {
      name: "Prepare next Object_List page",
      exact: true,
    });
    await expect(prepare).toBeEnabled();
    await expect(
      panel.getByLabel("Schedule evidence report", { exact: true }),
    ).toContainText("Next offset: 2");
    const afterRead = reads;
    await prepare.click();
    await expect(
      panel.getByLabel("Schedule Object_List offset", { exact: true }),
    ).toHaveValue("2");
    await expect(
      panel.getByLabel("Schedule evidence report", { exact: true }),
    ).toHaveCount(0);
    expect(calls).toHaveLength(1);
    expect(reads).toBe(afterRead);
    await panel
      .getByRole("button", { name: "Read native schedules", exact: true })
      .click();
    await expect(
      panel.getByLabel("Schedule evidence report", { exact: true }),
    ).toBeVisible();
    expect(calls).toHaveLength(2);
    expect(calls[1].object_list_offset).toBe(2);
    expect(calls[1].address).toBe(endpoint);
    expect(calls[1].device).toBe("device,42");
  } finally {
    child.kill("SIGTERM");
  }
});
