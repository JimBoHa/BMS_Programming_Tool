import {
  expect,
  test,
  type Page,
  type APIRequestContext,
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
  mode = "normal",
): Promise<{ process: ChildProcess; port: number; reads: () => number }> {
  const child = spawn(
    path.join(root, ".venv/bin/python"),
    [
      "-u",
      "-c",
      `
import asyncio,sys
from tests.test_bacnet_event_log import device
from tests.test_connections import free_udp
from bms_tool.bacnet_read import close_application
async def main():
 port=free_udp();server=device(port);server.behavior=sys.argv[1];original=server.do_ReadRangeRequest
 if sys.argv[1]=='unknown':
  from bacpypes3.primitivedata import OpeningTag,ClosingTag
  def unknown(reply):
   for tag in reply.itemData.tagList[1:-1]:
    if isinstance(tag,(OpeningTag,ClosingTag)) and tag.tag_number==5:tag.tag_number=99
  server.mutation=unknown
 async def tracked(request):
  print('RANGE',flush=True);await original(request)
 server.do_ReadRangeRequest=tracked;print(port,flush=True)
 try: await asyncio.Event().wait()
 finally: server.release.set();close_application(server)
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
  let reads = 0;
  const port = await new Promise<number>((resolve, reject) => {
    let text = "",
      errors = "",
      ready = false;
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error(errors || "Multiple peer timeout"));
    }, 5000);
    child.stderr!.on("data", (chunk) => {
      errors += String(chunk);
    });
    child.stdout!.on("data", (chunk) => {
      text += String(chunk);
      while (text.includes("\n")) {
        const index = text.indexOf("\n"),
          line = text.slice(0, index);
        text = text.slice(index + 1);
        if (!ready) {
          ready = true;
          clearTimeout(timer);
          resolve(Number(line));
        } else if (line === "RANGE") reads++;
      }
    });
    child.on("error", reject);
    child.on("exit", (code) => {
      clearTimeout(timer);
      if (!ready) reject(new Error(`Multiple peer ${code}: ${errors}`));
    });
  });
  return { process: child, port, reads: () => reads };
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
  await page
    .getByRole("button", { name: "Device history", exact: true })
    .click();
  const panel = page.getByRole("region", {
    name: "BACnet Event Log history",
    exact: true,
  });
  await expect(
    panel.getByRole("button", {
      name: "Read event-log history",
      exact: true,
    }),
  ).toBeEnabled();
  await panel
    .getByLabel("Event log device address", { exact: true })
    .fill(`127.0.0.1:${port}`);
  await panel
    .getByLabel("Event log Device object", { exact: true })
    .fill("device,4190103");
  await panel
    .getByLabel("Event log range reference", { exact: true })
    .fill("100");
  return { headers, panel };
}

test("native Event Log reads notifications/status/clock entries and exports sealed history", async ({
  page,
  request,
}) => {
  const server = await peer();
  try {
    const { headers, panel } = await open(page, request, server.port);
    expect(server.reads()).toBe(0);
    await panel
      .getByRole("button", { name: "Read event-log history", exact: true })
      .click();
    const evidence = panel.getByRole("region", {
      name: "Event log evidence",
      exact: true,
    });
    await expect(evidence).toContainText(
      "complete · 5 native records · 3 pages",
    );
    await expect(evidence).toContainText("device,42 · analog-input,1 · alarm");
    await expect(evidence).toContainText("ack-notification");
    await expect(evidence).toContainText('"type":"sequenceNumber","value":40');
    await expect(panel).toContainText("does not prove delivery, human receipt");
    expect(server.reads()).toBe(3);
    const download = page.waitForEvent("download");
    await panel
      .getByRole("button", { name: "Export event-log JSON", exact: true })
      .click();
    const report = JSON.parse(
      readFileSync((await (await download).path())!, "utf8"),
    );
    expect(report.profile).toBe("bacnet-event-log-history/1");
    expect(
      report.records[0].notification.event_timestamp.source_clock_utc,
    ).toBeNull();
    expect(report.records[0].source_clock).toBeNull();
    expect(report.records[0].quality).toBe("unknown");
    expect(report.records[4].notification.ack_required).toBeNull();
    const csvEvent = page.waitForEvent("download");
    await panel
      .getByRole("button", { name: "Export event-log CSV", exact: true })
      .click();
    const csv = readFileSync((await (await csvEvent).path())!, "utf8");
    expect(csv).toContain('"embedded_event_timestamp"');
    expect(csv).toContain('"notify_type"');
    expect(csv).toContain('"native_record"');
    await panel
      .getByRole("button", { name: "Save event-log capture", exact: true })
      .click();
    await expect(panel).toContainText("Saved a sealed local Event Log capture");
    await panel
      .getByLabel("Event log range reference", { exact: true })
      .fill("999");
    await panel
      .getByLabel("Saved event-log capture", { exact: true })
      .selectOption(report.id);
    await panel
      .getByRole("button", { name: "Load event-log capture", exact: true })
      .click();
    await expect(evidence).toContainText("5 native records");
    await expect(
      panel.getByLabel("Event log range reference", { exact: true }),
    ).toHaveValue("100");
    expect(server.reads()).toBe(3);
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
  } finally {
    server.process.kill();
  }
});

test("unknown native event parameters remain explicit opaque evidence without invented notifications", async ({
  page,
  request,
}) => {
  const server = await peer("unknown");
  try {
    const { headers, panel } = await open(page, request, server.port);
    await panel
      .getByRole("button", { name: "Read event-log history", exact: true })
      .click();
    await expect(
      panel.getByRole("region", { name: "Event log evidence", exact: true }),
    ).toContainText("unsupported_native_records · 0 native records");
    await expect(
      panel.getByRole("region", {
        name: "Uninterpreted native event page",
        exact: true,
      }),
    ).toContainText("Typed interpretation deferred");
    const downloaded = page.waitForEvent("download");
    await panel
      .getByRole("button", { name: "Export event-log JSON", exact: true })
      .click();
    const report = JSON.parse(
      readFileSync((await (await downloaded).path())!, "utf8"),
    );
    expect(report.undecoded_pages[0].item_data_tags.truncated).toBe(false);
    expect(report.undecoded_pages[0].item_data_tags.sha256).toMatch(
      /^[a-f0-9]{64}$/,
    );
    expect(report.records).toEqual([]);
    const csvEvent = page.waitForEvent("download");
    await panel
      .getByRole("button", { name: "Export event-log CSV", exact: true })
      .click();
    expect(readFileSync((await (await csvEvent).path())!, "utf8")).toContain(
      '"undecoded_native_page"',
    );
    expect(server.reads()).toBe(1);
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
  } finally {
    server.process.kill();
  }
});

test("logger timezone interprets only logger record time and leaves embedded source stamps native", async ({
  page,
  request,
}) => {
  const server = await peer();
  try {
    const { headers, panel } = await open(page, request, server.port);
    await panel
      .getByLabel("Event log logger timezone", { exact: true })
      .fill("America/Los_Angeles");
    await panel
      .getByRole("button", { name: "Read event-log history", exact: true })
      .click();
    await expect(
      panel.getByRole("region", { name: "Event log evidence", exact: true }),
    ).toContainText("2026-10-21T19:00:00.000000+00:00");
    await expect(panel).toContainText("Source UTC unresolved");
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
  } finally {
    server.process.kill();
  }
});

test("explicit Event Log cancellation retains and saves completed native pages", async ({
  page,
  request,
}) => {
  const server = await peer("hold-second");
  try {
    const { headers, panel } = await open(page, request, server.port);
    await panel
      .getByRole("button", { name: "Read event-log history", exact: true })
      .click();
    await expect.poll(server.reads).toBe(2);
    await panel
      .getByRole("button", { name: "Cancel event-log read", exact: true })
      .click();
    await expect(
      panel.getByRole("region", { name: "Event log evidence", exact: true }),
    ).toContainText("cancelled · 2 native records · 1 pages");
    await panel
      .getByRole("button", { name: "Save event-log capture", exact: true })
      .click();
    await expect(panel).toContainText("Saved a sealed local Event Log capture");
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
  } finally {
    server.process.kill();
  }
});

test("leaving Device history cancels the owned Event Log query without restarting it", async ({
  page,
  request,
}) => {
  const server = await peer("hold-second");
  try {
    const { headers, panel } = await open(page, request, server.port);
    await panel
      .getByRole("button", { name: "Read event-log history", exact: true })
      .click();
    await expect.poll(server.reads).toBe(2);
    await page.getByRole("button", { name: "Program", exact: true }).click();
    await expect
      .poll(
        async () =>
          (await (await request.get("/api/bacnet/event-log/status")).json())
            .active_operation,
      )
      .toBeNull();
    expect(server.reads()).toBe(2);
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
  } finally {
    server.process.kill();
  }
});
