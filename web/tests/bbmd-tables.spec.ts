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
async function bbmd(drop = false) {
  const child = spawn(
    path.join(root, ".venv/bin/python"),
    [
      "-u",
      "-c",
      `
import asyncio
from tests.test_bbmd_tables import RawTables, endpoint
async def main():
    transport,peer=await asyncio.get_running_loop().create_datagram_endpoint(RawTables,local_addr=("127.0.0.1",0))
    if ${drop ? "True" : "False"}: peer.responses[2]=None
    print(endpoint(peer.address),flush=True)
    try: await asyncio.Event().wait()
    finally:
        for handle in peer.handles: handle.cancel()
        transport.close()
asyncio.run(main())
`,
    ],
    {
      cwd: root,
      stdio: ["ignore", "pipe", "pipe"],
      env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
    },
  );
  const endpoint = await new Promise<string>((resolve, reject) => {
    let output = "";
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error("Raw BBMD peer did not start"));
    }, 5000);
    child.once("error", reject);
    child.stdout!.on("data", (data) => {
      output += data.toString();
      if (output.includes("\n")) {
        clearTimeout(timer);
        resolve(output.split("\n")[0]);
      }
    });
  });
  return { child, endpoint };
}

test("BBMD tables UI explicitly reads native tables and exports immutable endpoint/raw evidence", async ({
  page,
  request,
}) => {
  const peer = await bbmd();
  const token = (await (await request.get("/api/session")).json()).token;
  const headers = { "X-Studio-Token": token };
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  try {
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    await page.goto("/");
    await page.getByRole("button", { name: "Connect", exact: true }).click();
    const panel = page.getByRole("region", {
      name: "BBMD table inspection",
      exact: true,
    });
    await expect(
      panel.getByRole("button", { name: "Inspect BBMD tables", exact: true }),
    ).toBeDisabled();
    expect(
      (await (await request.get("/api/bacnet/bbmd-tables/status")).json()).jobs,
    ).toEqual([]);
    await request.post("/api/bacnet/connect", {
      headers,
      data: { local_address: `127.0.0.1:${await freePort()}` },
    });
    await page.reload();
    await page.getByRole("button", { name: "Connect", exact: true }).click();
    await panel
      .getByLabel("BBMD inspection endpoint", { exact: true })
      .fill(peer.endpoint);
    await panel
      .getByRole("button", { name: "Inspect BBMD tables", exact: true })
      .click();
    const current = panel
      .getByRole("region", { name: /^BBMD inspection bbmd-/ })
      .first();
    await expect(current).toContainText("BDT · ok · 3 entries");
    await expect(current).toContainText("FDT · ok · 1 entries");
    await expect(current).toContainText("255.0.255.0");
    await expect(current).toContainText("89");
    await panel
      .getByLabel("BBMD inspection endpoint", { exact: true })
      .fill("192.0.2.5");
    const downloadPromise = page.waitForEvent("download");
    await current
      .getByRole("button", { name: "Export BBMD snapshot", exact: true })
      .click();
    const downloaded = await downloadPromise;
    const evidence = JSON.parse(
      readFileSync((await downloaded.path())!, "utf8"),
    );
    expect(evidence.endpoint).toBe(peer.endpoint);
    expect(evidence.tables.bdt.response.peer).toBe(peer.endpoint);
    expect(evidence.tables.bdt.rows[2].mask_contiguous).toBe(false);
    expect(evidence.tables.fdt.rows[0]).toMatchObject({
      ttl_seconds: 60,
      remaining_seconds: 89,
    });
    expect(evidence.tables.bdt.request_hex).toBe("81020004");
    expect(evidence.tables.fdt.request_hex).toBe("81060004");
    expect(evidence.tables.bdt.response.raw_hex).toMatch(/^8103/);
    expect(evidence.scope).toContain("late replies");
    await page.reload();
    await page.getByRole("button", { name: "Connect", exact: true }).click();
    await panel
      .getByRole("button", { name: "Load table inspections", exact: true })
      .click();
    await expect(panel).toContainText(peer.endpoint);
    expect(errors).toEqual([]);
  } finally {
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    peer.child.kill();
  }
});

test("BBMD UI cancels an actual waiting read and retains its unknown outcome", async ({
  page,
  request,
}) => {
  const peer = await bbmd(true);
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
      name: "BBMD table inspection",
      exact: true,
    });
    await panel
      .getByLabel("BBMD inspection endpoint", { exact: true })
      .fill(peer.endpoint);
    await panel.getByLabel("BBMD response deadline", { exact: true }).fill("5");
    await panel
      .getByRole("button", { name: "Inspect BBMD tables", exact: true })
      .click();
    const current = panel
      .getByRole("region", { name: /^BBMD inspection bbmd-/ })
      .first();
    await expect(current).toContainText("BDT · waiting");
    await current
      .getByRole("button", { name: "Cancel BBMD inspection", exact: true })
      .click();
    await expect(current).toContainText("cancelled");
    await expect(current).toContainText(
      "transmitted reads are not rolled back",
    );
  } finally {
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    peer.child.kill();
  }
});
