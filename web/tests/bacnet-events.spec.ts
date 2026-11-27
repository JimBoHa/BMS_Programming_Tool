import { expect, test } from "@playwright/test";
import { spawn, execFileSync, type ChildProcess } from "node:child_process";
import {
  openEventController,
  showControllerEvents,
  selectEventController,
} from "./event-workspace";
import { chooseWorkspaceTask } from "./workspace-navigation";
import { disconnectTestInterface } from "./workflow-peer";
import { readFileSync } from "node:fs";
import path from "node:path";

const root = path.resolve("..");
test.afterEach(async ({ request }) => {
  await disconnectTestInterface(request);
});
async function peer(
  behavior = "normal",
): Promise<{ process: ChildProcess; port: number; events: () => number }> {
  const child = spawn(
    path.join(root, ".venv/bin/python"),
    [
      "-u",
      "-c",
      `
import asyncio,sys
from tests.test_bacnet_events import events_device
from tests.test_connections import free_udp
from bms_tool.bacnet_read import close_application
async def main():
 port=free_udp();server=events_device(port,behavior=sys.argv[1]);original=server.do_GetEventInformationRequest
 async def tracked(request):
  print('EVENT',flush=True)
  await original(request)
 server.do_GetEventInformationRequest=tracked
 print(port,flush=True)
 try: await asyncio.Event().wait()
 finally: server.release.set();close_application(server)
asyncio.run(main())
`,
      behavior,
    ],
    {
      cwd: root,
      env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  let count = 0;
  const port = await new Promise<number>((resolve, reject) => {
    let text = "",
      error = "",
      resolved = false;
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error("Event peer startup: " + error));
    }, 5000);
    child.stderr!.on("data", (value) => {
      error += String(value);
    });
    child.stdout!.on("data", (value) => {
      text += String(value);
      while (text.includes("\n")) {
        const end = text.indexOf("\n"),
          line = text.slice(0, end);
        text = text.slice(end + 1);
        if (!resolved) {
          resolved = true;
          clearTimeout(timer);
          resolve(Number(line));
        } else if (line === "EVENT") count++;
      }
    });
    child.on("error", (failure) => {
      clearTimeout(timer);
      reject(failure);
    });
    child.on("exit", (code) => {
      clearTimeout(timer);
      if (!resolved) reject(new Error(`Event peer exited ${code}: ${error}`));
    });
  });
  return { process: child, port, events: () => count };
}
test("Selected controller explicitly queries real EventSummary pages and exports raw state/timestamp evidence", async ({
  page,
  request,
}) => {
  const server = await peer();
  let reads = 0;
  page.on("request", (value) => {
    if (value.url().endsWith("/api/bacnet/events/read")) reads++;
  });
  try {
    const panel = await openEventController(page, server.port);
    await page.waitForLoadState("networkidle");
    expect(reads).toBe(0);
    expect(server.events()).toBe(0);
    await panel
      .getByRole("button", { name: "Query device events", exact: true })
      .click();
    await expect(
      panel.getByRole("status", { name: "Event query result", exact: true }),
    ).toContainText("partial · page_boundary · 1 event summaries");
    expect(reads).toBe(1);
    expect(server.events()).toBe(1);
    await panel
      .getByRole("button", {
        name: "Inspect event analog-value,2",
        exact: true,
      })
      .click();
    const details = panel.getByRole("region", {
      name: "Selected native event summary",
      exact: true,
    });
    await expect(details).toContainText('"type": "dateTime"');
    await expect(details).toContainText(
      '"clock_status": "sequence-not-wall-clock"',
    );
    await expect(details).toContainText(
      '"quality": "not-supplied-by-EventSummary"',
    );
    const pending = page.waitForEvent("download");
    await panel
      .getByRole("button", { name: "Export event JSON", exact: true })
      .click();
    const original = JSON.parse(
      readFileSync((await (await pending).path())!, "utf8"),
    );
    expect(original.source_kind).toBe("bacnet-get-event-information");
    expect(original.complete).toBe(false);
    expect(original.next_cursor).not.toBeNull();
    expect(original.events[0].raw.eventState).toBe(2);
    expect(original.events[0].event_timestamps[1].raw.value).toEqual([
      255, 255, 255, 255,
    ]);
    const csvPending = page.waitForEvent("download");
    await panel
      .getByRole("button", { name: "Export event CSV", exact: true })
      .click();
    const csvPath = (await (await csvPending).path())!;
    const csv = JSON.parse(
      execFileSync(
        path.join(root, ".venv/bin/python"),
        [
          "-c",
          "import csv,json,sys; print(json.dumps(list(csv.DictReader(open(sys.argv[1],encoding='utf-8-sig',newline='')))))",
          csvPath,
        ],
        { encoding: "utf8" },
      ),
    );
    expect(csv[0].report_id).toBe(original.id);
    expect(csv[0].report_complete).toBe("false");
    expect(csv[0].identity_verified).toBe("true");
    expect(csv[0].report_page_count).toBe("1");
    expect(csv[0].timestamp_basis).toBe(original.timestamp_basis);
    expect(JSON.parse(csv[0].raw_summary)).toEqual(original.events[0].raw);
    expect(JSON.parse(csv[0].event_timestamps_raw)).toEqual(
      original.events[0].event_timestamps,
    );
    await panel
      .getByLabel("Event pages per request", { exact: true })
      .fill("2");
    await expect(
      panel.getByRole("button", { name: "Continue event query", exact: true }),
    ).toBeEnabled();
    await panel
      .getByRole("button", { name: "Continue event query", exact: true })
      .click();
    await expect(
      panel.getByRole("status", { name: "Event query result", exact: true }),
    ).toContainText("complete · complete · 2 event summaries");
    expect(reads).toBe(2);
    expect(server.events()).toBe(2);
    await expect(
      panel.getByRole("button", { name: "Continue event query", exact: true }),
    ).toBeDisabled();
    await expect(panel.locator("tbody tr")).toHaveCount(2);
    await panel.scrollIntoViewIfNeeded();
    await page.screenshot({
      path: "test-results/bacnet-field-events.png",
      fullPage: true,
    });
    const headers = {
      "X-Studio-Token": (await (await request.get("/api/session")).json())
        .token,
    };
    const refused = await request.post("/api/bacnet/events/read", {
      headers,
      data: {
        address: `127.0.0.1:${server.port}`,
        device: "analog-value,1",
        operation_id: "wrong-device-type",
      },
    });
    expect(refused.status()).toBe(422);
    expect(await refused.text()).toContain("actual Device instance");
    const other = await peer();
    try {
      await page
        .getByLabel("Working context")
        .getByRole("button", { name: "Change controller", exact: true })
        .click();
      const next = await selectEventController(page, other.port);
      await expect(
        next.getByRole("button", { name: "Export event JSON", exact: true }),
      ).toBeDisabled();
      expect(other.events()).toBe(0);
    } finally {
      other.process.kill();
    }
    expect(server.events()).toBe(2);
  } finally {
    server.process.kill();
  }
});

test("real unsupported event service remains distinct from an empty event list", async ({
  page,
}) => {
  const server = await peer("unsupported");
  try {
    const panel = await openEventController(page, server.port);
    await panel
      .getByRole("button", { name: "Query device events", exact: true })
      .click();
    await expect(
      panel.getByRole("status", { name: "Event query result", exact: true }),
    ).toContainText("unsupported · unsupported · 0 event summaries");
    await expect(panel).toContainText("unrecognized-service");
    await expect(panel).not.toContainText(
      "empty complete GetEventInformation list",
    );
  } finally {
    server.process.kill();
  }
});

test("explicit cancel and leaving Controller events stop the owned event query", async ({
  page,
  request,
}) => {
  const server = await peer("hold");
  try {
    const panel = await openEventController(page, server.port);
    await panel
      .getByRole("button", { name: "Query device events", exact: true })
      .click();
    await expect.poll(server.events).toBe(1);
    await panel
      .getByRole("button", { name: "Cancel event query", exact: true })
      .click();
    await expect(
      panel.getByRole("status", { name: "Event query result", exact: true }),
    ).toContainText("cancelled");
    expect(
      (await (await request.get("/api/bacnet/events/profile")).json())
        .active_operation,
    ).toBeNull();
    await panel
      .getByRole("button", { name: "Query device events", exact: true })
      .click();
    await expect.poll(server.events).toBe(2);
    await chooseWorkspaceTask(page, "Program");
    await expect
      .poll(
        async () =>
          (await (await request.get("/api/bacnet/events/profile")).json())
            .active_operation,
      )
      .toBeNull();
    await showControllerEvents(page);
    await expect(
      page
        .getByRole("region", { name: "BACnet field events", exact: true })
        .getByRole("button", { name: "Export event JSON", exact: true }),
    ).toBeDisabled();
  } finally {
    server.process.kill();
  }
});
