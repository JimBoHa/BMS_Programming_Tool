import { expect, test, type Page } from "@playwright/test";
import { spawn, type ChildProcess } from "node:child_process";
import { openEventController, showControllerEvents } from "./event-workspace";
import { chooseWorkspaceTask } from "./workspace-navigation";
import { disconnectTestInterface } from "./workflow-peer";
import { readFileSync } from "node:fs";
import path from "node:path";
const root = path.resolve("..");
test.afterEach(async ({ request }) => {
  await disconnectTestInterface(request);
});
async function peer(mode = "accept"): Promise<{
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
async function open(page: Page, port: number) {
  const events = await openEventController(page, port);
  return {
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
}) => {
  const server = await peer();
  try {
    const { events, ack } = await open(page, server.port);
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
  } finally {
    server.process.kill();
  }
});
for (const mode of ["stale", "unsafe"])
  test(`${mode} evidence visibly defers without a write`, async ({ page }) => {
    const server = await peer(mode);
    try {
      const { events, ack } = await open(page, server.port);
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
    } finally {
      server.process.kill();
    }
  });
test("missing response remains unknown, invalidates review and never retries", async ({
  page,
}) => {
  const server = await peer("hold");
  try {
    const { events, ack } = await open(page, server.port);
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
  } finally {
    server.process.kill();
  }
});
test("leaving Controller events retires the write and retains its unknown receipt", async ({
  page,
  request,
}) => {
  const server = await peer("hold");
  try {
    const { events, ack } = await open(page, server.port);
    await prepare(events, ack);
    await ack
      .getByRole("button", {
        name: "Apply reviewed acknowledgement",
        exact: true,
      })
      .click();
    await expect.poll(server.packets).toBe(1);
    await chooseWorkspaceTask(page, "Program");
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
    await showControllerEvents(page);
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
  } finally {
    server.process.kill();
  }
});
