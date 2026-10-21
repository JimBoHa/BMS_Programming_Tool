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
async function peer(drop = false, reject = false) {
  const writes: string[] = [];
  const child = spawn(
    path.join(root, ".venv/bin/python"),
    [
      "-u",
      "-c",
      `
import asyncio,json
from tests.test_bbmd_admin import RawAdmin
from tests.test_bbmd_tables import endpoint
async def main():
    transport,peer=await asyncio.get_running_loop().create_datagram_endpoint(RawAdmin,local_addr=("127.0.0.1",0))
    peer.drop_result=${drop ? "True" : "False"}
    peer.accept_write=${reject ? "False" : "True"}
    peer.code=${reject ? "0x10" : "0"}
    if ${reject ? "True" : "False"}:
        from tests.test_foreign_bacnet import bvlc
        def stale(function,source):
            if function==1:
                for _ in range(12): peer.transport.sendto(bvlc(0,b"\\0\\0"),source)
        peer.before_reply=stale
    peer.before_write=lambda data: print(json.dumps({"write":data.hex()}),flush=True)
    print(json.dumps({"endpoint":endpoint(peer.address)}),flush=True)
    try: await asyncio.Event().wait()
    finally: transport.close()
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
    let buffer = "";
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error("Raw administration peer did not start"));
    }, 5000);
    child.once("error", reject);
    child.stdout!.on("data", (bytes) => {
      buffer += bytes.toString();
      while (buffer.includes("\n")) {
        const end = buffer.indexOf("\n");
        const line = JSON.parse(buffer.slice(0, end));
        buffer = buffer.slice(end + 1);
        if (line.endpoint) {
          clearTimeout(timer);
          resolve(line.endpoint);
        }
        if (line.write) writes.push(line.write);
      }
    });
  });
  return { child, endpoint, writes };
}

test("BBMD receipt keeps late native NACK visible after generic Result retention fills", async ({
  page,
  request,
}) => {
  const server = await peer(false, true);
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
      name: "Reviewed BBMD administration",
      exact: true,
    });
    await panel
      .getByLabel("BBMD change endpoint", { exact: true })
      .fill(server.endpoint);
    await panel
      .getByRole("button", { name: "Prepare BBMD change review", exact: true })
      .click();
    const approval = panel.getByRole("region", {
      name: "BBMD change approval",
      exact: true,
    });
    await approval
      .getByRole("checkbox", {
        name: "Acknowledge exact BBMD change and protocol limits",
        exact: true,
      })
      .check();
    await approval
      .getByRole("button", {
        name: "Apply reviewed BBMD change once",
        exact: true,
      })
      .click();
    const receipt = panel.getByRole("region", {
      name: /^BBMD change receipt bbma-/,
    });
    await expect(receipt).toContainText(
      "Observation: different-state-observed",
    );
    await expect(receipt).toContainText("Write outcome: unknown");
    await expect(receipt).toContainText(
      "Native administration NACK observed: 0x0010",
    );
    await expect(receipt).toContainText("Additional Results omitted: 5");
    const downloadPromise = page.waitForEvent("download");
    await receipt
      .getByRole("button", { name: "Export BBMD change receipt", exact: true })
      .click();
    const data = JSON.parse(
      readFileSync((await (await downloadPromise).path())!, "utf8"),
    );
    expect(data.results_observed).toHaveLength(8);
    expect(data.last_native_admin_nack.result_code).toBe(0x10);
    expect(data.result_counts.success).toBe(12);
    expect(server.writes).toHaveLength(1);
  } finally {
    server.child.kill();
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
  }
});

test("BBMD changes require fresh review, send one exact write, export observations and restore only as a new proposal", async ({
  page,
  request,
}) => {
  const server = await peer();
  const token = (await (await request.get("/api/session")).json()).token;
  const headers = { "X-Studio-Token": token };
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  try {
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    await request.post("/api/bacnet/connect", {
      headers,
      data: { local_address: `127.0.0.1:${await freePort()}` },
    });
    await page.goto("/");
    await page.getByRole("button", { name: "Connect", exact: true }).click();
    const panel = page.getByRole("region", {
      name: "Reviewed BBMD administration",
      exact: true,
    });
    await panel
      .getByLabel("BBMD change endpoint", { exact: true })
      .fill(server.endpoint);
    await panel
      .getByRole("button", { name: "Load current BDT into draft", exact: true })
      .click();
    await expect(panel.getByLabel("BDT ip 1", { exact: true })).toHaveValue(
      "10.2.3.4",
    );
    await expect(panel.getByLabel("BDT mask 2", { exact: true })).toHaveValue(
      "255.0.255.0",
    );
    expect(server.writes).toEqual([]);
    await panel.getByLabel("BDT ip 1", { exact: true }).fill("10.22.33.44");
    await panel
      .getByRole("button", { name: "Prepare BBMD change review", exact: true })
      .click();
    const approval = panel.getByRole("region", {
      name: "BBMD change approval",
      exact: true,
    });
    await expect(approval).toContainText(server.endpoint);
    await expect(
      approval.getByRole("button", {
        name: "Apply reviewed BBMD change once",
        exact: true,
      }),
    ).toBeDisabled();
    await panel.getByLabel("BDT port 1", { exact: true }).fill("47809");
    await expect(approval).toHaveCount(0); // a draft change invalidates browser approval
    await panel
      .getByRole("button", { name: "Prepare BBMD change review", exact: true })
      .click();
    await approval
      .getByRole("checkbox", {
        name: "Acknowledge exact BBMD change and protocol limits",
        exact: true,
      })
      .check();
    expect(server.writes).toEqual([]);
    await approval
      .getByRole("button", {
        name: "Apply reviewed BBMD change once",
        exact: true,
      })
      .click();
    await expect.poll(() => server.writes.length).toBe(1);
    const receipt = panel.getByRole("region", {
      name: /^BBMD change receipt bbma-/,
    });
    await expect(receipt).toContainText("Observation: desired-state-observed");
    await expect(receipt).toContainText("Write outcome: unknown");
    await expect(approval).toHaveCount(0);
    const downloadPromise = page.waitForEvent("download");
    await receipt
      .getByRole("button", { name: "Export BBMD change receipt", exact: true })
      .click();
    const downloaded = await downloadPromise;
    const data = JSON.parse(readFileSync((await downloaded.path())!, "utf8"));
    expect(data.write_wire_hex).toBe(server.writes[0]);
    expect(data.authorship_proven).toBe(false);
    expect(data.atomic_cas).toBe(false);
    expect(data.endpoint).toBe(server.endpoint);
    expect(data.before.rows).toHaveLength(3);
    expect(data.postapply.rows[0]).toMatchObject({
      ip: "10.22.33.44",
      port: 47809,
    });
    await page.reload();
    await page.getByRole("button", { name: "Connect", exact: true }).click();
    await panel
      .getByRole("button", { name: "Load BBMD change history", exact: true })
      .click();
    await panel.getByText(/^Saved BBMD change history/).click();
    await panel.getByRole("button", { name: data.id, exact: true }).click();
    await expect(receipt).toContainText(server.endpoint);
    expect(server.writes).toHaveLength(1);
    await receipt
      .getByRole("button", {
        name: "Review restoring BDT before-state",
        exact: true,
      })
      .click();
    await expect(approval).toContainText(server.endpoint);
    await expect(
      panel.getByLabel("BBMD change endpoint", { exact: true }),
    ).toHaveValue(server.endpoint);
    expect(server.writes).toHaveLength(1); // no automatic rollback
    expect(errors).toEqual([]);
  } finally {
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    server.child.kill();
  }
});

test("FDT UI targets an exact native lease and cancellation after dispatch stays unknown", async ({
  page,
  request,
}) => {
  const server = await peer(true);
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
      name: "Reviewed BBMD administration",
      exact: true,
    });
    await panel
      .getByLabel("BBMD change endpoint", { exact: true })
      .fill(server.endpoint);
    await panel
      .getByLabel("BBMD change operation", { exact: true })
      .selectOption("delete-fdt");
    await panel
      .getByLabel("Exact FDT endpoint to delete", { exact: true })
      .fill("10.4.5.6:47900");
    await panel
      .getByRole("button", { name: "Prepare BBMD change review", exact: true })
      .click();
    const receipt = panel.getByRole("region", {
      name: /^BBMD change receipt bbma-/,
    });
    await expect(receipt).toContainText(
      "Native TTL 60s · Remaining at preview 89s",
    );
    await panel
      .getByRole("checkbox", {
        name: "Acknowledge exact BBMD change and protocol limits",
        exact: true,
      })
      .check();
    await panel
      .getByRole("button", {
        name: "Apply reviewed BBMD change once",
        exact: true,
      })
      .click();
    await expect.poll(() => server.writes.length).toBe(1);
    expect(server.writes[0]).toBe("8108000a0a040506bb1c");
    await receipt
      .getByRole("button", { name: "Cancel BBMD Apply", exact: true })
      .click();
    await expect(receipt).toContainText("State: cancelled");
    await expect(receipt).toContainText("Write outcome: unknown");
    await expect(receipt).toContainText("Observation: unknown");
    expect(server.writes).toHaveLength(1);
  } finally {
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    server.child.kill();
  }
});
