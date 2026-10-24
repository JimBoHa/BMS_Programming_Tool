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
from tests.test_bacnet_history_multiple import device
from tests.test_connections import free_udp
from bms_tool.bacnet_read import close_application
async def main():
 port=free_udp();server=device(port);server.behavior=sys.argv[1];original=server.do_ReadRangeRequest
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
    name: "BACnet Trend Log Multiple history",
    exact: true,
  });
  await expect(
    panel.getByRole("button", {
      name: "Read multiple-channel history",
      exact: true,
    }),
  ).toBeEnabled();
  await panel
    .getByLabel("Multiple history device address", { exact: true })
    .fill(`127.0.0.1:${port}`);
  await panel
    .getByLabel("Multiple history Device object", { exact: true })
    .fill("device,4190102");
  await panel
    .getByLabel("Multiple history range reference", { exact: true })
    .fill("100");
  return { headers, panel };
}
test("explicit native multiple-channel read preserves unknown clocks and exports sealed channel evidence", async ({
  page,
  request,
}) => {
  const server = await peer();
  try {
    const { headers, panel } = await open(page, request, server.port);
    expect(server.reads()).toBe(0);
    await panel
      .getByRole("button", {
        name: "Read multiple-channel history",
        exact: true,
      })
      .click();
    const evidence = panel.getByRole("region", {
      name: "Multiple history evidence",
      exact: true,
    });
    await expect(evidence).toContainText(
      "complete · 5 native records · 3 pages · identity verified · complete",
    );
    await expect(evidence).toContainText(
      "Channel 1: realValue 1.25 · quality unknown",
    );
    await expect(evidence).toContainText("Clock: unresolved native time");
    expect(server.reads()).toBe(3);
    const jsonEvent = page.waitForEvent("download");
    await panel
      .getByRole("button", {
        name: "Export multiple-history JSON",
        exact: true,
      })
      .click();
    const report = JSON.parse(
      readFileSync((await (await jsonEvent).path())!, "utf8"),
    );
    expect(report.records[0].raw.logData.type).toBe("logData");
    expect(report.records[0].source_clock).toBeNull();
    expect(
      report.records[0].channels[0].reference.raw.objectIdentifier,
    ).toEqual([0, 1]);
    const csvEvent = page.waitForEvent("download");
    await panel
      .getByRole("button", { name: "Export multiple-history CSV", exact: true })
      .click();
    const csv = readFileSync((await (await csvEvent).path())!, "utf8");
    expect(csv).toContain("current_channel_reference");
    expect(csv).toContain("Historical channel assignments");
    expect(csv).toContain("realValue");
    await panel
      .getByRole("button", {
        name: "Save multiple-history capture",
        exact: true,
      })
      .click();
    await expect(panel).toContainText(
      "Saved a sealed local Trend Log Multiple capture",
    );
    await panel
      .getByLabel("Multiple history range reference", { exact: true })
      .fill("999");
    await expect(
      panel.getByRole("button", {
        name: "Export multiple-history JSON",
        exact: true,
      }),
    ).toBeDisabled();
    await panel
      .getByLabel("Saved multiple-history capture", { exact: true })
      .selectOption(report.id);
    await panel
      .getByRole("button", {
        name: "Load multiple-history capture",
        exact: true,
      })
      .click();
    await expect(evidence).toContainText("5 native records");
    await expect(
      panel.getByLabel("Multiple history range reference", { exact: true }),
    ).toHaveValue("100");
    expect(server.reads()).toBe(3);
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
  } finally {
    server.process.kill();
  }
});

test("native bounded cursor starts a separate explicit range without mixing pages", async ({
  page,
  request,
}) => {
  const server = await peer();
  try {
    const { headers, panel } = await open(page, request, server.port);
    await panel
      .getByLabel("Multiple history record limit", { exact: true })
      .fill("3");
    await panel
      .getByRole("button", {
        name: "Read multiple-channel history",
        exact: true,
      })
      .click();
    const evidence = panel.getByRole("region", {
      name: "Multiple history evidence",
      exact: true,
    });
    await expect(evidence).toContainText(
      "bounded · 3 native records · 2 pages",
    );
    await panel
      .getByRole("button", {
        name: "Read next multiple-history range",
        exact: true,
      })
      .click();
    await expect(evidence).toContainText(
      "complete · 2 native records · 1 pages",
    );
    await expect(evidence.locator("tbody tr")).toHaveCount(2);
    expect(server.reads()).toBe(3);
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
  } finally {
    server.process.kill();
  }
});

test("explicit cancellation retains and can save completed native pages", async ({
  page,
  request,
}) => {
  const server = await peer("hold-second");
  try {
    const { headers, panel } = await open(page, request, server.port);
    await panel
      .getByRole("button", {
        name: "Read multiple-channel history",
        exact: true,
      })
      .click();
    await expect.poll(server.reads).toBe(2);
    await panel
      .getByRole("button", {
        name: "Cancel multiple-history read",
        exact: true,
      })
      .click();
    await expect(
      panel.getByRole("region", {
        name: "Multiple history evidence",
        exact: true,
      }),
    ).toContainText("cancelled · 2 native records · 1 pages");
    await panel
      .getByRole("button", {
        name: "Save multiple-history capture",
        exact: true,
      })
      .click();
    await expect(panel).toContainText("Saved a sealed local");
    const status = await (
      await request.get("/api/bacnet/history-multiple/status")
    ).json();
    expect(status.active_operation).toBeNull();
    expect(
      status.captures.some(
        (value: any) => value.records === 2 && value.truncated,
      ),
    ).toBe(true);
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
  } finally {
    server.process.kill();
  }
});

test("leaving Device history cancels the owned native request without delayed traffic", async ({
  page,
  request,
}) => {
  const server = await peer("hold-second");
  try {
    const { headers, panel } = await open(page, request, server.port);
    await panel
      .getByRole("button", {
        name: "Read multiple-channel history",
        exact: true,
      })
      .click();
    await expect.poll(server.reads).toBe(2);
    await page.getByRole("button", { name: "Program", exact: true }).click();
    await expect
      .poll(
        async () =>
          (
            await (
              await request.get("/api/bacnet/history-multiple/status")
            ).json()
          ).active_operation,
      )
      .toBeNull();
    expect(server.reads()).toBe(2);
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
  } finally {
    server.process.kill();
  }
});

test("late initial metadata cannot replace refreshed connector state", async ({
  page,
  request,
}) => {
  const stale = await (
    await request.get("/api/bacnet/history-multiple/status")
  ).json();
  stale.connected = false;
  let release!: () => void,
    finished!: () => void,
    reads = 0;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const responded = new Promise<void>((resolve) => {
    finished = resolve;
  });
  await page.route("**/api/bacnet/history-multiple/status", async (route) => {
    reads++;
    if (reads === 1) {
      await gate;
      await route.fulfill({ json: stale });
      finished();
    } else await route.continue();
  });
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  await request.post("/api/bacnet/connect", {
    headers,
    data: { local_address: `127.0.0.1:${await freePort()}` },
  });
  try {
    await page.goto("/");
    await page
      .getByRole("button", { name: "Device history", exact: true })
      .click();
    const panel = page.getByRole("region", {
      name: "BACnet Trend Log Multiple history",
      exact: true,
    });
    await expect.poll(() => reads).toBe(1);
    await panel
      .getByRole("button", {
        name: "Refresh multiple-history status",
        exact: true,
      })
      .click();
    await expect(
      panel.getByRole("button", {
        name: "Read multiple-channel history",
        exact: true,
      }),
    ).toBeEnabled();
    release();
    await responded;
    await expect(
      panel.getByRole("button", {
        name: "Read multiple-channel history",
        exact: true,
      }),
    ).toBeEnabled();
  } finally {
    release();
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
  }
});
