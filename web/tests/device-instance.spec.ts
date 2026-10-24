import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";
import { spawn, type ChildProcess } from "node:child_process";
import { createSocket } from "node:dgram";
import { readFileSync } from "node:fs";
import path from "node:path";

const root = path.resolve("..");
async function freePort(): Promise<number> {
  const socket = createSocket("udp4");
  return new Promise((resolve, reject) => {
    socket.once("error", reject);
    socket.bind(0, "127.0.0.1", () => {
      const port = (socket.address() as { port: number }).port;
      socket.close(() => resolve(port));
    });
  });
}
async function peer(
  mode = "accept",
): Promise<{ process: ChildProcess; port: number; packets: () => number }> {
  const child = spawn(
    path.join(root, ".venv/bin/python"),
    [
      "-u",
      "-c",
      `
import asyncio,sys
from tests.test_device_instance import instance_peer, InstanceRouter
from tests.test_connections import free_udp
from bms_tool.bacnet_read import close_application
from bacpypes3.apdu import APDU,ConfirmedRequestPDU
from bacpypes3.pdu import PDU
async def main():
 mode=sys.argv[1]
 if mode=='routed':
  _,server=await asyncio.get_running_loop().create_datagram_endpoint(InstanceRouter,local_addr=('127.0.0.1',0))
  original=server.respond
  async def tracked(data,source):
   before=len(server.writes)
   await original(data,source)
   if len(server.writes)>before: print('WRITE',flush=True)
  server.respond=tracked
  port=server.transport.get_extra_info('sockname')[1]
 else:
  port=free_udp();server=instance_peer(port,mode)
  original=server.asap.confirmation
  async def tracked(pdu):
   packet=APDU.decode(PDU(bytes(pdu.pduData)))
   if isinstance(packet,ConfirmedRequestPDU) and packet.apduService==15: print('WRITE',flush=True)
   await original(pdu)
  server.asap.confirmation=tracked
 print(port,flush=True)
 try: await asyncio.Event().wait()
 finally:
  if mode=='routed': await server.close()
  else: server.release.set();close_application(server)
asyncio.run(main())
`,
      mode,
    ],
    {
      cwd: root,
      env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  let packets = 0;
  const port = await new Promise<number>((resolve, reject) => {
    let buffer = "",
      errors = "",
      ready = false;
    const timer = setTimeout(
      () => reject(new Error("Peer startup: " + errors)),
      10000,
    );
    child.stderr!.on("data", (value) => (errors += value.toString()));
    child.stdout!.on("data", (value) => {
      buffer += value.toString();
      while (buffer.includes("\n")) {
        const end = buffer.indexOf("\n"),
          line = buffer.slice(0, end).trim();
        buffer = buffer.slice(end + 1);
        if (!ready) {
          ready = true;
          clearTimeout(timer);
          resolve(Number(line));
        } else if (line === "WRITE") packets++;
      }
    });
    child.once("error", reject);
    child.once("exit", (code) => {
      clearTimeout(timer);
      if (!ready) reject(new Error(`Peer ${code}: ${errors}`));
    });
  });
  return { process: child, port, packets: () => packets };
}
async function open(
  page: Page,
  request: APIRequestContext,
  server: { port: number },
  routed = false,
) {
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  expect(
    (
      await request.post("/api/bacnet/connect", {
        headers,
        data: { local_address: `127.0.0.1:${await freePort()}` },
      })
    ).ok(),
  ).toBe(true);
  await page.goto("/");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  const panel = page.getByRole("region", {
    name: "Device instance commissioning",
    exact: true,
  });
  await panel
    .getByLabel("Controller address (IPv4 or DNET:MAC)", { exact: true })
    .fill(routed ? "3001:7" : `127.0.0.1:${server.port}`);
  await panel
    .getByLabel("Current Device object (device,instance)", { exact: true })
    .fill("device,5136");
  if (routed) {
    await panel
      .getByLabel("Instance-change router (routed targets only)", {
        exact: true,
      })
      .fill(`127.0.0.1:${server.port}`);
    await panel
      .getByLabel("Instance-change network (1–65534)", { exact: true })
      .fill("3001");
  }
  await panel
    .getByLabel("New controller instance (0–4194302)", { exact: true })
    .fill("15136");
  return panel;
}
async function review(panel: ReturnType<Page["getByRole"]>) {
  await panel
    .getByRole("button", { name: "Review instance change", exact: true })
    .click();
  await expect(
    panel.getByLabel("Reviewed instance change", { exact: true }),
  ).toContainText("5136 → 15136");
  await expect(
    panel.getByRole("button", {
      name: "Apply controller instance change",
      exact: true,
    }),
  ).toBeDisabled();
  await panel
    .getByRole("checkbox", { name: "I reserved this new number", exact: false })
    .check();
}
test("direct controller review, stale edit, single write, verified readback and exact receipt download", async ({
  page,
  request,
}) => {
  const server = await peer();
  try {
    const panel = await open(page, request, server);
    await review(panel);
    expect(server.packets()).toBe(0);
    await panel
      .getByLabel("New controller instance (0–4194302)", { exact: true })
      .fill("15137");
    await expect(
      panel.getByRole("button", {
        name: "Apply controller instance change",
        exact: true,
      }),
    ).toHaveCount(0);
    await panel
      .getByLabel("New controller instance (0–4194302)", { exact: true })
      .fill("15136");
    await review(panel);
    const response = page.waitForResponse((value) =>
      value.url().endsWith("/device-instance/apply"),
    );
    await panel
      .getByRole("button", {
        name: "Apply controller instance change",
        exact: true,
      })
      .click();
    const result = await (await response).json();
    expect(result.status).toBe("verified");
    const receipt = panel.getByLabel("Instance change receipt", {
      exact: true,
    });
    await expect(receipt).toContainText("verified_new");
    await panel.screenshot({
      path: test.info().outputPath("instance-verified.png"),
    });
    await expect.poll(server.packets).toBe(1);
    await expect(
      panel.getByLabel("Current Device object (device,instance)", {
        exact: true,
      }),
    ).toHaveValue("device,15136");
    const downloadEvent = page.waitForEvent("download");
    await receipt
      .getByRole("button", { name: "Download instance receipt", exact: true })
      .click();
    const download = await downloadEvent;
    const exported = JSON.parse(readFileSync((await download.path())!, "utf8"));
    expect(exported.attempt).toEqual(result);
    expect(exported.intent.may_have_applied).toBe(true);
    const readbackResponse = page.waitForResponse((value) =>
      value.url().endsWith("/device-instance/readback"),
    );
    await receipt
      .getByRole("button", {
        name: "Read back instance (no write)",
        exact: true,
      })
      .click();
    expect((await (await readbackResponse).json()).readback.status).toBe(
      "verified_new",
    );
    await expect(receipt).toContainText("verified_new");
    expect(server.packets()).toBe(1);
  } finally {
    server.process.kill("SIGTERM");
    await request.post("/api/bacnet/disconnect", {
      headers: {
        "X-Studio-Token": (await (await request.get("/api/session")).json())
          .token,
      },
      data: {},
    });
  }
});

test("routed commissioning pins the chosen duplicate-ID station", async ({
  page,
  request,
}) => {
  const server = await peer("routed");
  try {
    const panel = await open(page, request, server, true);
    await review(panel);
    expect(server.packets()).toBe(0);
    await panel
      .getByRole("button", {
        name: "Apply controller instance change",
        exact: true,
      })
      .click();
    await expect(
      panel.getByLabel("Instance change receipt", { exact: true }),
    ).toContainText("Result: verified");
    await expect.poll(server.packets).toBe(1);
  } finally {
    server.process.kill("SIGTERM");
  }
});

test("controller rejection stays explicit and does not report success", async ({
  page,
  request,
}) => {
  const server = await peer("reject");
  try {
    const panel = await open(page, request, server);
    await review(panel);
    await panel
      .getByRole("button", {
        name: "Apply controller instance change",
        exact: true,
      })
      .click();
    const receipt = panel.getByLabel("Instance change receipt", {
      exact: true,
    });
    await expect(receipt).toContainText("Result: rejected");
    await expect(receipt).toContainText("manufacturer’s commissioning tool");
    expect(server.packets()).toBe(1);
  } finally {
    server.process.kill("SIGTERM");
  }
});

test("cancel after dispatch retains an uncertain receipt across reload and never repeats the write", async ({
  page,
  request,
}) => {
  const server = await peer("hold");
  try {
    const panel = await open(page, request, server);
    await review(panel);
    await panel
      .getByRole("button", {
        name: "Apply controller instance change",
        exact: true,
      })
      .click();
    await expect.poll(server.packets).toBe(1);
    await panel
      .getByRole("button", { name: "Cancel instance operation", exact: true })
      .click();
    await expect(
      panel.getByLabel("Instance change receipt", { exact: true }),
    ).toContainText("Result: unknown");
    await page.reload();
    await page.getByRole("button", { name: "Connect", exact: true }).click();
    const restored = page.getByRole("region", {
      name: "Device instance commissioning",
      exact: true,
    });
    const list = restored.getByLabel("Retained instance receipts", {
      exact: true,
    });
    await expect(list).toContainText(`127.0.0.1:${server.port}`);
    const values = await list.locator("option").allTextContents();
    const selected = values.findIndex((value) =>
      value.includes(`127.0.0.1:${server.port}`),
    );
    expect(selected).toBeGreaterThan(0);
    await list.selectOption({ index: selected });
    await expect(
      restored.getByLabel("Instance change receipt", { exact: true }),
    ).toContainText("do not retry the write");
    await restored
      .getByRole("button", {
        name: "Read back instance (no write)",
        exact: true,
      })
      .click();
    await expect(
      restored.getByLabel("Instance change receipt", { exact: true }),
    ).toContainText("verified_old");
    expect(server.packets()).toBe(1);
  } finally {
    server.process.kill("SIGTERM");
  }
});

test("a late preview cannot restore Apply after leaving the connection workspace", async ({
  page,
  request,
}) => {
  const server = await peer();
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let captured!: () => void;
  const ready = new Promise<void>((resolve) => {
    captured = resolve;
  });
  try {
    const panel = await open(page, request, server);
    await page.route("**/api/bacnet/device-instance/preview", async (route) => {
      const response = await route.fetch();
      captured();
      await gate;
      await route.fulfill({ response });
    });
    await panel
      .getByRole("button", { name: "Review instance change", exact: true })
      .click();
    await ready;
    await page.getByRole("button", { name: "Program", exact: true }).click();
    release();
    await page.getByRole("button", { name: "Connect", exact: true }).click();
    await expect(
      page.getByRole("region", {
        name: "Device instance commissioning",
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", {
        name: "Apply controller instance change",
        exact: true,
      }),
    ).toHaveCount(0);
    expect(server.packets()).toBe(0);
  } finally {
    release();
    server.process.kill("SIGTERM");
  }
});
