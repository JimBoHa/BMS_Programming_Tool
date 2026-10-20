import { test, expect } from "@playwright/test";
import { execFileSync, spawn, type ChildProcess } from "node:child_process";
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
async function historyDevice(dropAfter?: number): Promise<{
  process: ChildProcess;
  port: number;
}> {
  const process = spawn(
    path.join(root, ".venv/bin/python"),
    [
      "-u",
      "-c",
      `
import asyncio,sys
from datetime import datetime
from tests.test_bacnet_history import HistoryDevice, log, port
from bacpypes3.local.device import DeviceObject
from bacpypes3.local.networkport import NetworkPortObject
async def main():
    address=port()
    server=HistoryDevice.from_object_list([
        DeviceObject(objectIdentifier=('device',4190070),objectName='Browser history emulator'),
        NetworkPortObject(f'127.0.0.1:{address}',objectIdentifier=('network-port',1),objectName='Loopback')])
    server.setup([log(12.5),log(13.5,flags=(0,1,0,0)),log((),kind='nullValue'),log(14.5,timestamp=datetime(2026,11,1,1,30))])
    server.drop_after=int(sys.argv[1]) if int(sys.argv[1]) >= 0 else None
    print(address,flush=True)
    try: await asyncio.Event().wait()
    finally: server.close()
asyncio.run(main())
`,
      String(dropAfter ?? -1),
    ],
    { cwd: root, stdio: ["ignore", "pipe", "pipe"] },
  );
  const port = await new Promise<number>((resolve, reject) => {
    let output = "",
      error = "";
    const timer = setTimeout(() => {
      process.kill();
      reject(new Error("History emulator startup failed: " + error));
    }, 5000);
    process.stderr!.on("data", (data) => {
      error += data.toString();
    });
    process.stdout!.on("data", (data) => {
      output += data.toString();
      if (output.includes("\n")) {
        clearTimeout(timer);
        resolve(Number(output.split("\n")[0]));
      }
    });
    process.on("error", (e) => {
      clearTimeout(timer);
      reject(e);
    });
    process.on("exit", (code) => {
      clearTimeout(timer);
      if (!output)
        reject(new Error(`History emulator exited ${code}: ${error}`));
    });
  });
  return { process, port };
}

function csvRows(file: string): Record<string, string>[] {
  return JSON.parse(
    execFileSync(
      path.join(root, ".venv/bin/python"),
      [
        "-c",
        "import csv,json,sys; f=open(sys.argv[1],newline='',encoding='utf-8'); print(json.dumps(list(csv.DictReader(f))))",
        file,
      ],
      { cwd: root, encoding: "utf8" },
    ),
  );
}

function checkCsvProvenance(rows: Record<string, string>[], evidence: any) {
  expect(rows).toHaveLength(Math.max(1, evidence.records.length));
  for (const row of rows) {
    expect(row.source_kind).toBe(evidence.source_kind);
    expect(row.address).toBe(evidence.target.address);
    expect(row.object_id).toBe(evidence.target.object_id);
    expect(row.report_id).toBe(evidence.id);
    expect(row.report_record_count).toBe(String(evidence.records.length));
    expect(row.report_read_at_utc).toBe(evidence.read_at);
    expect(row.report_received_at_utc).toBe(evidence.received_at);
    expect(row.device_timezone).toBe(evidence.request.device_timezone);
    expect(row.clock_fold).toBe(String(evidence.request.fold ?? ""));
    expect(JSON.parse(row.timezone_provenance)).toEqual(evidence.timezone);
    expect(JSON.parse(row.range_request)).toEqual(evidence.request);
    expect(row.report_complete).toBe(String(evidence.complete));
    expect(row.report_truncated).toBe(String(evidence.truncated));
    expect(JSON.parse(row.report_errors)).toEqual(evidence.errors);
    expect(JSON.parse(row.report_warnings)).toEqual(evidence.warnings);
    expect(row.next_cursor ? JSON.parse(row.next_cursor) : null).toEqual(
      evidence.next_cursor,
    );
    expect(row.report_consistency).toBe(evidence.consistency);
    expect(row.report_scope).toBe(evidence.scope);
  }
  evidence.records.forEach((record: any, index: number) => {
    const row = rows[index];
    expect(row.export_row_kind).toBe("record");
    expect(row.sequence).toBe(String(record.sequence ?? ""));
    expect(row.source_clock_utc).toBe(record.source_clock ?? "");
    expect(row.recorded_at_utc).toBe(record.recorded_at);
    expect(JSON.parse(row.local_timestamp)).toEqual(record.local_timestamp);
    expect(row.datum_type).toBe(record.datum_type);
    expect(row.sample).toBe(String(record.sample));
    expect(row.quality).toBe(record.quality);
    expect(row.timestamp_error).toBe(record.timestamp_error ?? "");
  });
}

test("device history uses real ReadRange, preserves unresolved clocks and saves immutable local evidence", async ({
  page,
  request,
}) => {
  const server = await historyDevice();
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  let reads = 0;
  page.on("request", (value) => {
    if (value.url().endsWith("/api/bacnet/history/read")) reads++;
  });
  try {
    await page.goto("/");
    await page
      .getByRole("button", { name: "Device history", exact: true })
      .click();
    await expect(
      page.getByRole("button", { name: "Read device history", exact: true }),
    ).toBeDisabled();
    const connected = await request.post("/api/bacnet/connect", {
      headers,
      data: { local_address: `127.0.0.1:${await freePort()}` },
    });
    expect(connected.ok()).toBeTruthy();
    await page
      .getByRole("button", { name: "Refresh history status", exact: true })
      .click();
    await page
      .getByLabel("History device address", { exact: true })
      .fill(`127.0.0.1:${server.port}`);
    await page
      .getByLabel("History device clock timezone", { exact: true })
      .fill("America/Los_Angeles");
    await page
      .getByLabel("History range reference", { exact: true })
      .fill("100");
    await page.getByLabel("History record limit", { exact: true }).fill("10");
    await page.getByLabel("History page size", { exact: true }).fill("2");
    await page
      .getByRole("button", { name: "Read device history", exact: true })
      .click();
    const report = page.getByRole("region", {
      name: "Device history records",
      exact: true,
    });
    await expect(report).toContainText("4 device-history records");
    await expect(report.getByRole("status")).toHaveText(
      "Reached the end of the device log.",
    );
    const rows = report.locator("tbody tr");
    await expect(rows).toHaveCount(4);
    await expect(rows.nth(0)).toContainText("12.5");
    await expect(rows.nth(0)).toContainText("2026-01-05T20:00:00.000000+00:00");
    await expect(rows.nth(1)).toContainText("unreliable");
    await expect(rows.nth(2)).toContainText("nullValue");
    await expect(rows.nth(3)).toContainText("Unresolved UTC time");
    await expect(rows.nth(3)).toContainText("Ambiguous local time");
    let downloading = page.waitForEvent("download");
    await page
      .getByRole("button", {
        name: "Download device history JSON",
        exact: true,
      })
      .click();
    let file = await downloading;
    const evidence = JSON.parse(readFileSync((await file.path())!, "utf8"));
    expect(evidence.source_kind).toBe("device-history");
    expect(evidence.records[3].source_clock).toBeNull();
    expect(evidence.records[3].sample).toBe(false);
    downloading = page.waitForEvent("download");
    await page
      .getByRole("button", { name: "Download device history CSV", exact: true })
      .click();
    file = await downloading;
    const csv = readFileSync((await file.path())!, "utf8");
    expect(csv).toContain('"source_clock_utc"');
    expect(csv).toContain('"device-history"');
    expect(csv).toContain('"13.5","unreliable"');
    checkCsvProvenance(csvRows((await file.path())!), evidence);
    await page
      .getByRole("button", {
        name: "Save immutable history capture",
        exact: true,
      })
      .click();
    await expect(
      page.getByText("Saved an immutable local device-history capture.", {
        exact: false,
      }),
    ).toBeVisible();
    const saved = await (
      await request.get(`/api/bacnet/history/captures/${evidence.id}`)
    ).json();
    expect(saved).toEqual(evidence);
    await page.reload();
    await page
      .getByRole("button", { name: "Device history", exact: true })
      .click();
    await page
      .getByLabel("Saved device history capture", { exact: true })
      .selectOption(evidence.id);
    await page
      .getByRole("button", { name: "Open history capture", exact: true })
      .click();
    await expect(report).toContainText("4 device-history records");
    expect(reads).toBe(1);
    await page.screenshot({
      path: "test-results/studio-device-history.png",
      fullPage: true,
    });
  } finally {
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    server.process.kill();
  }
});

for (const kind of ["limited", "empty", "partial", "folded"] as const) {
  test(`device history CSV preserves ${kind} acquisition and clock provenance without inventing records`, async ({
    page,
    request,
  }) => {
    const server = await historyDevice(kind === "partial" ? 1 : undefined);
    const headers = {
      "X-Studio-Token": (await (await request.get("/api/session")).json())
        .token,
    };
    try {
      await request.post("/api/bacnet/connect", {
        headers,
        data: { local_address: `127.0.0.1:${await freePort()}` },
      });
      await page.goto("/");
      await page
        .getByRole("button", { name: "Device history", exact: true })
        .click();
      await page
        .getByLabel("History device address", { exact: true })
        .fill(`127.0.0.1:${server.port}`);
      await page
        .getByLabel("History device clock timezone", { exact: true })
        .fill("America/Los_Angeles");
      await page
        .getByLabel("History range reference", { exact: true })
        .fill(kind === "empty" ? "1000" : kind === "partial" ? "99" : "100");
      await page
        .getByLabel("History record limit", { exact: true })
        .fill(kind === "limited" ? "1" : "10");
      await page
        .getByLabel("History page size", { exact: true })
        .fill(kind === "partial" ? "3" : "2");
      await page
        .getByLabel("History ambiguous local hour", { exact: true })
        .selectOption("1");
      await page
        .getByRole("button", { name: "Read device history", exact: true })
        .click();
      const report = page.getByRole("region", {
        name: "Device history records",
        exact: true,
      });
      await expect(report).toBeVisible({ timeout: 10000 });
      let pending = page.waitForEvent("download");
      await page
        .getByRole("button", {
          name: "Download device history JSON",
          exact: true,
        })
        .click();
      const evidence = JSON.parse(
        readFileSync((await (await pending).path())!, "utf8"),
      );
      pending = page.waitForEvent("download");
      await page
        .getByRole("button", {
          name: "Download device history CSV",
          exact: true,
        })
        .click();
      const rows = csvRows((await (await pending).path())!);
      checkCsvProvenance(rows, evidence);
      if (kind === "limited") {
        expect(evidence.records).toHaveLength(1);
        expect(evidence.complete).toBe(false);
        expect(evidence.truncated).toBe(true);
        expect(JSON.parse(rows[0].next_cursor)).toEqual({
          mode: "sequence",
          reference: 101,
        });
      } else if (kind === "empty") {
        expect(evidence.records).toHaveLength(0);
        expect(evidence.complete).toBe(true);
        expect(rows[0].export_row_kind).toBe("report_metadata");
        for (const field of [
          "sequence",
          "source_clock_utc",
          "recorded_at_utc",
          "local_timestamp",
          "datum_type",
          "sample",
          "value",
          "quality",
          "status_flags",
          "timestamp_error",
        ])
          expect(rows[0][field]).toBe("");
      } else if (kind === "partial") {
        expect(evidence.records).toHaveLength(2);
        expect(evidence.complete).toBe(false);
        expect(evidence.truncated).toBe(true);
        expect(evidence.errors.length).toBeGreaterThan(0);
        expect(evidence.warnings[0]).toContain("outside retained history");
        await expect(report).toContainText(evidence.warnings[0]);
      } else {
        expect(evidence.complete).toBe(true);
        expect(rows[3].clock_fold).toBe("1");
        expect(rows[3].source_clock_utc).toBe(
          "2026-11-01T09:30:00.000000+00:00",
        );
        expect(rows[3].sample).toBe("true");
      }
    } finally {
      await request.post("/api/bacnet/disconnect", { headers, data: {} });
      server.process.kill();
    }
  });
}
