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
): Promise<{
  process: ChildProcess;
  port: number;
  packets: () => number;
  reads: () => number;
}> {
  const child = spawn(
    path.join(root, ".venv/bin/python"),
    [
      "-u",
      "-c",
      `
import asyncio,sys
from tests.test_bacnet_events import event,events_device
from tests.test_bacnet_event_ack import configure_ack_peer
from tests.test_connections import free_udp
from bms_tool.bacnet_read import close_application
from bacpypes3.apdu import APDU,ConfirmedRequestPDU
from bacpypes3.pdu import PDU
async def main():
 mode=sys.argv[1];port=free_udp();server=events_device(port,pages={None:([event(state='normal' if mode=='unsafe' else 'offnormal')],False)})
 await configure_ack_peer(server)
 server.ack_mode='hold' if mode=='hold' else 'accept'
 wire=server.asap.confirmation;read=server.do_GetEventInformationRequest;count=0
 async def tracked_wire(pdu):
  packet=APDU.decode(PDU(bytes(pdu.pduData)))
  if isinstance(packet,ConfirmedRequestPDU) and packet.apduService==0: print('ACK',flush=True)
  await wire(pdu)
 async def tracked_read(request):
  nonlocal count
  count+=1;print('READ',flush=True)
  if mode=='stale' and count>=2: server.pages[None][0][0].eventState='highLimit'
  await read(request)
 server.asap.confirmation=tracked_wire;server.do_GetEventInformationRequest=tracked_read
 print(port,flush=True)
 try: await asyncio.Event().wait()
 finally: server.ack_release.set();server.release.set();close_application(server)
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
  let packets = 0,
    reads = 0;
  const port = await new Promise<number>((resolve, reject) => {
    let output = "",
      errors = "",
      ready = false;
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error(errors || "ACK peer timeout"));
    }, 5000);
    child.stderr!.on("data", (chunk) => {
      errors += String(chunk);
    });
    child.stdout!.on("data", (chunk) => {
      output += String(chunk);
      while (output.includes("\n")) {
        const index = output.indexOf("\n"),
          line = output.slice(0, index);
        output = output.slice(index + 1);
        if (!ready) {
          ready = true;
          clearTimeout(timer);
          resolve(Number(line));
        } else if (line === "ACK") packets++;
        else if (line === "READ") reads++;
      }
    });
    child.on("error", reject);
    child.on("exit", (code) => {
      clearTimeout(timer);
      if (!ready) reject(new Error(`Peer ${code}: ${errors}`));
    });
  });
  return { process: child, port, packets: () => packets, reads: () => reads };
}
async function open(page: Page, request: APIRequestContext, port: number) {
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
  const events = page.getByRole("region", {
    name: "BACnet field events",
    exact: true,
  });
  await expect(
    events.getByRole("button", { name: "Query device events", exact: true }),
  ).toBeEnabled();
  await events
    .getByLabel("Event device address", { exact: true })
    .fill(`127.0.0.1:${port}`);
  await events
    .getByLabel("Event Device object", { exact: true })
    .fill("device,4190096");
  return {
    headers,
    events,
    ack: page.getByRole("region", {
      name: "Reviewed event acknowledgement",
      exact: true,
    }),
  };
}
async function prepare(events: any, ack: any) {
  await events
    .getByRole("button", { name: "Query device events", exact: true })
    .click();
  await events
    .getByRole("button", { name: "Inspect event analog-value,1", exact: true })
    .click();
  await ack
    .getByLabel("Declared operator identity", { exact: true })
    .fill("Authored Browser Operator");
  await ack
    .getByLabel("Acknowledgement clock timezone", { exact: true })
    .fill("America/Los_Angeles");
  await ack
    .getByRole("button", { name: "Preview acknowledgement", exact: true })
    .click();
}
test("fresh preview is read only; deliberate Apply exports exact native acceptance evidence", async ({
  page,
  request,
}) => {
  const server = await peer();
  try {
    const { headers, events, ack } = await open(page, request, server.port);
    expect(server.reads()).toBe(0);
    expect(server.packets()).toBe(0);
    await prepare(events, ack);
    const review = ack.getByRole("region", {
      name: "Acknowledgement review",
      exact: true,
    });
    await expect(review).toContainText("review_required");
    await expect(review).toContainText('"type":"dateTime"');
    await expect(review).toContainText(
      "BMS Studio / Authored Browser Operator",
    );
    expect(server.reads()).toBe(2);
    expect(server.packets()).toBe(0);
    await review
      .getByRole("button", {
        name: "Apply reviewed acknowledgement",
        exact: true,
      })
      .click();
    const receipt = ack.getByRole("region", {
      name: "Acknowledgement receipt",
      exact: true,
    });
    await expect(receipt).toContainText(
      "Acknowledgement accepted · protocol accepted: true · may have applied: true",
    );
    expect(server.packets()).toBe(1);
    expect(server.reads()).toBe(3);
    await expect(
      events.getByRole("button", {
        name: "Inspect event analog-value,1",
        exact: true,
      }),
    ).toHaveCount(0);
    const downloaded = page.waitForEvent("download");
    await receipt
      .getByRole("button", {
        name: "Export acknowledgement receipt",
        exact: true,
      })
      .click();
    const evidence = JSON.parse(
      readFileSync((await (await downloaded).path())!, "utf8"),
    );
    expect(evidence.native_request.timeStamp.type).toBe("dateTime");
    expect(evidence.native_request.acknowledgmentSource).toBe(
      "BMS Studio / Authored Browser Operator",
    );
    expect(evidence.request_apdu_sha256).toMatch(/^[a-f0-9]{64}$/);
    expect(evidence.automatic_retries).toBe(false);
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
  } finally {
    server.process.kill();
  }
});
for (const mode of ["stale", "unsafe"])
  test(`${mode} evidence visibly defers without a write`, async ({
    page,
    request,
  }) => {
    const server = await peer(mode);
    try {
      const { headers, events, ack } = await open(page, request, server.port);
      await prepare(events, ack);
      const review = ack.getByRole("region", {
        name: "Acknowledgement review",
        exact: true,
      });
      await expect(review).toContainText("deferred");
      await expect(review).toContainText(
        mode === "stale"
          ? "changed since the displayed query"
          : "exact historical offnormal state",
      );
      await expect(
        ack.getByRole("button", {
          name: "Apply reviewed acknowledgement",
          exact: true,
        }),
      ).toHaveCount(0);
      expect(server.packets()).toBe(0);
      await request.post("/api/bacnet/disconnect", { headers, data: {} });
    } finally {
      server.process.kill();
    }
  });
test("missing response remains unknown, invalidates review and never retries", async ({
  page,
  request,
}) => {
  const server = await peer("hold");
  try {
    const { headers, events, ack } = await open(page, request, server.port);
    await prepare(events, ack);
    await ack
      .getByRole("button", {
        name: "Apply reviewed acknowledgement",
        exact: true,
      })
      .click();
    await expect(
      ack.getByRole("region", { name: "Acknowledgement receipt", exact: true }),
    ).toContainText(
      "Acknowledgement unknown · protocol accepted: false · may have applied: true",
    );
    expect(server.packets()).toBe(1);
    await expect(
      ack.getByRole("button", {
        name: "Apply reviewed acknowledgement",
        exact: true,
      }),
    ).toHaveCount(0);
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
  } finally {
    server.process.kill();
  }
});
test("leaving Connect retires the write and retains its unknown receipt", async ({
  page,
  request,
}) => {
  const server = await peer("hold");
  try {
    const { headers, events, ack } = await open(page, request, server.port);
    await prepare(events, ack);
    await ack
      .getByRole("button", {
        name: "Apply reviewed acknowledgement",
        exact: true,
      })
      .click();
    await expect.poll(server.packets).toBe(1);
    await page.getByRole("button", { name: "Program", exact: true }).click();
    await expect
      .poll(
        async () =>
          (await (await request.get("/api/bacnet/events/ack/profile")).json())
            .active_operation,
      )
      .toBeNull();
    const profile = await (
      await request.get("/api/bacnet/events/ack/profile")
    ).json();
    expect(profile.receipts[0].status).toBe("unknown");
    expect(profile.receipts[0].may_have_applied).toBe(true);
    await page.getByRole("button", { name: "Connect", exact: true }).click();
    await ack
      .getByText("Earlier acknowledgement receipts in this session", {
        exact: true,
      })
      .click();
    await ack
      .getByRole("button", {
        name: `Inspect receipt ${profile.receipts[0].id}`,
        exact: true,
      })
      .click();
    await expect(
      ack.getByRole("region", { name: "Acknowledgement receipt", exact: true }),
    ).toContainText("Acknowledgement unknown");
    expect(server.packets()).toBe(1);
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
  } finally {
    server.process.kill();
  }
});
