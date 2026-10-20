import { test, expect, type Page, type Locator } from "@playwright/test";
import { spawn, execFileSync } from "node:child_process";
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
async function scanPeer(count = 1) {
  const child = spawn(
    path.join(root, ".venv/bin/python"),
    [
      "-u",
      "-c",
      "import runpy;runpy.run_path('web/tests/device_scan_peer.py',run_name='__main__')",
      String(count),
    ],
    { cwd: root, stdio: ["pipe", "pipe", "pipe"] },
  );
  let output = "",
    error = "",
    ready = false;
  child.stderr.on("data", (data) => {
    error += data.toString();
  });
  const endpoints = await new Promise<{
    first: number;
    second: number;
    router: string;
  }>((resolve, reject) => {
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error("Scan peer startup timed out: " + error));
    }, 8000);
    child.stdout.on("data", (data) => {
      output += data.toString();
      if (!ready && output.includes("\n")) {
        ready = true;
        clearTimeout(timer);
        resolve(JSON.parse(output.split("\n")[0]));
      }
    });
    child.on("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
    child.on("exit", (code) => {
      clearTimeout(timer);
      if (!ready) reject(new Error(`Scan peer exited ${code}: ${error}`));
    });
  });
  return {
    ...endpoints,
    async close() {
      const finished = new Promise<number | null>((resolve) =>
        child.once("exit", resolve),
      );
      child.stdin.end("close\n");
      const timer = setTimeout(() => child.kill(), 3000);
      const code = await finished;
      clearTimeout(timer);
      expect(code, error).toBe(0);
      return JSON.parse(output.trim().split("\n").at(-1)!);
    },
  };
}
async function openScan(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  const panel = page.getByRole("region", {
    name: "BACnet device scan",
    exact: true,
  });
  await expect(
    panel.getByRole("button", { name: "Scan BACnet/IP devices", exact: true }),
  ).toBeDisabled();
  await page
    .getByLabel("Local bind address / UDP port", { exact: true })
    .fill(`127.0.0.1:${await freePort()}`);
  await page.getByLabel("Router IP (optional)", { exact: true }).fill("");
  await page
    .getByLabel("MS/TP destination network (optional)", { exact: true })
    .fill("");
  await page
    .getByLabel("BBMD address / UDP port (optional)", { exact: true })
    .fill("");
  await page
    .getByRole("button", { name: "Open interface", exact: true })
    .click();
  await expect(
    page.getByText("BACnet interface open", { exact: true }),
  ).toBeVisible();
  await panel
    .getByLabel("Discovery response seconds", { exact: true })
    .fill("1");
  return panel;
}
function scanRows(panel: Locator) {
  return panel.locator(".device-scan-table").first().locator("tbody tr");
}
async function singleScan(panel: Locator, port: number) {
  await panel
    .getByLabel("IP scan mode", { exact: true })
    .selectOption("single");
  await panel.getByLabel("Scan IP address", { exact: true }).fill("127.0.0.1");
  await panel.getByLabel("Scan UDP port", { exact: true }).fill(String(port));
  await panel
    .getByRole("button", { name: "Scan BACnet/IP devices", exact: true })
    .click();
}
async function jsonExport(page: Page, panel: Locator) {
  const downloading = page.waitForEvent("download");
  await panel
    .getByRole("button", { name: "Export all received JSON", exact: true })
    .click();
  return JSON.parse(readFileSync((await (await downloading).path())!, "utf8"));
}
function csvRows(file: string) {
  return JSON.parse(
    execFileSync(
      path.join(root, ".venv/bin/python"),
      [
        "-c",
        "import csv,json,sys; print(json.dumps(list(csv.DictReader(open(sys.argv[1],newline='',encoding='utf-8')))))",
        file,
      ],
      { cwd: root, encoding: "utf8" },
    ),
  );
}

test("Scan receives real IP/routed identities, reads actual names and Program objects, preserves duplicate IDs and exports provenance", async ({
  page,
  request,
}) => {
  test.setTimeout(90000);
  const peer = await scanPeer();
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  let connections = 0;
  page.on("request", (value) => {
    if (value.url().endsWith("/api/bacnet/connect")) connections++;
  });
  try {
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    const panel = await openScan(page);
    await singleScan(panel, peer.first);
    const rows = scanRows(panel);
    await expect(rows).toHaveCount(1);
    await expect(rows.first()).toContainText("=Named Controller 01");
    await expect(rows.first().locator("td").nth(5)).toContainText(
      "Actual Program 1; Actual Program 2",
    );
    await expect(rows.first().locator("td").nth(4)).toHaveText(
      "version-only-1.2",
    );
    await expect(rows.first().locator("td").nth(5)).not.toContainText(
      "version-only-1.2",
    );
    await expect(rows.first().locator("td").nth(5)).not.toContainText(
      "Device description",
    );
    await expect(
      panel.getByRole("button", {
        name: "Export all received JSON",
        exact: true,
      }),
    ).toBeEnabled();
    await singleScan(panel, peer.second);
    await expect(rows).toHaveCount(2);
    await expect(panel).toContainText("Duplicate ID at another address");
    const noProgram = rows.filter({
      hasText: "Duplicate ID at another address",
    });
    await expect(noProgram.locator("td").nth(5)).toContainText("Not exposed");
    await expect(
      panel.getByRole("button", {
        name: "Export all received JSON",
        exact: true,
      }),
    ).toBeEnabled();
    await panel
      .getByLabel("IP scan mode", { exact: true })
      .selectOption("range");
    await panel
      .getByLabel("First scan IP address", { exact: true })
      .fill("127.0.0.1");
    await panel
      .getByLabel("Last scan IP address", { exact: true })
      .fill("127.0.0.3");
    await panel
      .getByLabel("Scan UDP port", { exact: true })
      .fill(String(peer.first));
    await panel
      .getByRole("button", { name: "Scan BACnet/IP devices", exact: true })
      .click();
    await expect(
      panel.getByRole("region", {
        name: "Last IP discovery response",
        exact: true,
      }),
    ).toContainText("3 targets requested this page / 3 selected");
    await expect(rows.filter({ hasText: "=Named Controller 01" })).toHaveCount(
      1,
    );
    await expect(
      panel.getByRole("button", {
        name: "Export all received JSON",
        exact: true,
      }),
    ).toBeEnabled();
    await panel
      .getByLabel("IP scan mode", { exact: true })
      .selectOption("local");
    await panel
      .getByRole("button", { name: "Scan BACnet/IP devices", exact: true })
      .click();
    await expect(
      panel.getByRole("region", {
        name: "Last IP discovery response",
        exact: true,
      }),
    ).toContainText("local-subnet");
    await expect(
      panel.getByRole("button", {
        name: "Export all received JSON",
        exact: true,
      }),
    ).toBeEnabled();
    const routed = page.getByRole("region", {
      name: "Routed BACnet discovery",
      exact: true,
    });
    await routed
      .getByLabel("Discovery router address", { exact: true })
      .fill(peer.router);
    await routed
      .getByLabel("Routed destination network", { exact: true })
      .fill("3001");
    await routed
      .getByLabel("Routed minimum device instance", { exact: true })
      .fill("4190090");
    await routed
      .getByLabel("Routed maximum device instance", { exact: true })
      .fill("4190090");
    await routed
      .getByLabel("Routed response window seconds", { exact: true })
      .fill("1");
    await routed
      .getByRole("button", {
        name: "Scan selected routed network",
        exact: true,
      })
      .click();
    await expect(
      routed.getByRole("link", {
        name: "View named Scan results",
        exact: true,
      }),
    ).toHaveAttribute("href", "#bacnet-device-scan");
    await expect(rows).toHaveCount(4);
    await expect(
      rows.filter({ hasText: "Routed named controller" }),
    ).toHaveCount(2);
    await expect(
      panel.getByRole("button", {
        name: "Export all received JSON",
        exact: true,
      }),
    ).toBeEnabled();
    await panel
      .getByLabel("Discovery source", { exact: true })
      .selectOption("routed");
    await panel
      .getByLabel("Search discovered devices", { exact: true })
      .fill("Routed named");
    await panel
      .getByLabel("Sort discovered devices", { exact: true })
      .selectOption("name");
    await expect(rows).toHaveCount(2);
    const evidence = await jsonExport(page, panel);
    expect(evidence.rows).toHaveLength(4);
    expect(new Set(evidence.rows.map((row: any) => row.target.device))).toEqual(
      new Set(["device,4190090"]),
    );
    expect(new Set(evidence.rows.map((row: any) => row.key)).size).toBe(4);
    const second = evidence.rows.find(
      (row: any) => row.target.address === `127.0.0.1:${peer.second}`,
    );
    expect(second.details.programs_status).toBe("not_exposed");
    expect(second.details.object_list.complete).toBe(true);
    expect(second.details.property_status.description.status).toBe(
      "unsupported",
    );
    expect(second.details.program_names).toEqual([]);
    for (const row of evidence.rows) {
      expect(row.details.identity_verified).toBe(true);
      expect(row.details.properties["application-software-version"]).toBe(
        "version-only-1.2",
      );
      expect(
        Object.values(row.discoveries).every(
          (item: any) =>
            item.window.started_at &&
            item.observation.address === row.target.address,
        ),
      ).toBe(true);
    }
    const downloading = page.waitForEvent("download");
    await panel
      .getByRole("button", { name: "Export all received CSV", exact: true })
      .click();
    const records = csvRows((await (await downloading).path())!);
    const csv = records.filter((row: any) => row.row_type === "device");
    const csvReports = records.filter((row: any) => row.row_type === "report");
    expect(csv).toHaveLength(4);
    expect(csvReports).toHaveLength(
      Object.values(evidence.reports).reduce(
        (count: number, scope: any) => count + scope.pages.length,
        0,
      ),
    );
    for (const row of csvReports) {
      const original =
        evidence.reports[row.scope_key].pages[Number(row.report_page) - 1];
      expect(JSON.parse(row.request_json)).toEqual(original.request);
      expect(JSON.parse(row.report_json)).toEqual(original.report);
    }
    for (const row of csv) {
      const json = evidence.rows.find(
        (item: any) =>
          item.target.address === row.address &&
          item.target.source === row.source,
      );
      expect(JSON.parse(row.metadata_json)).toEqual(json.details);
      expect(JSON.parse(row.discovery_evidence_json)).toEqual(json.discoveries);
      expect(Number(row.device_instance)).toBe(4190090);
    }
    expect(
      csv.find((row: any) => row.name.includes("Named Controller 01")).name,
    ).toBe("'=Named Controller 01");
    await panel
      .getByRole("button", {
        name: `Use controller ${peer.router}/3001:7/device,4190090`,
        exact: true,
      })
      .click();
    await expect(
      page.getByLabel("Unicast target", { exact: true }),
    ).toHaveValue("3001:7");
    await expect(
      page.getByLabel("Router IP (optional)", { exact: true }),
    ).toHaveValue(peer.router);
    await expect(
      page.getByLabel("MS/TP destination network (optional)", { exact: true }),
    ).toHaveValue("3001");
    expect(connections).toBe(1);
    await panel
      .getByLabel("Discovery source", { exact: true })
      .selectOption("all");
    await panel
      .getByLabel("Search discovered devices", { exact: true })
      .fill("");
    await panel
      .getByRole("button", {
        name: `Use controller IP/127.0.0.1:${peer.first}/device,4190090`,
        exact: true,
      })
      .click();
    await expect(
      page.getByLabel("Unicast target", { exact: true }),
    ).toHaveValue(`127.0.0.1:${peer.first}`);
    expect(connections).toBe(1);
  } finally {
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    const result = await peer.close();
    expect(result.first_discovery).toBeGreaterThanOrEqual(2);
    expect(result.second_discovery).toBe(1);
    expect(result.routed_discovery).toBe(1);
    expect(result.routed_metadata).toBeGreaterThan(0);
    expect(result.maximum_pending).toBe(1);
  }
});

test("current-page naming is sequential, Stop finishes only its current RPC, and later pages load explicitly received metadata", async ({
  page,
  request,
}) => {
  test.setTimeout(120000);
  const peer = await scanPeer(25);
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  let metadata = 0,
    release!: () => void,
    arrived!: () => void;
  const held = new Promise<void>((resolve) => {
      release = resolve;
    }),
    waiting = new Promise<void>((resolve) => {
      arrived = resolve;
    });
  await page.route("**/api/bacnet/device-details", async (route) => {
    metadata++;
    const response = await route.fetch();
    if (metadata === 1) {
      arrived();
      await held;
    }
    await route.fulfill({ response });
  });
  try {
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    const panel = await openScan(page);
    expect(metadata).toBe(0);
    await singleScan(panel, peer.first);
    await waiting;
    const rows = scanRows(panel);
    await expect(rows).toHaveCount(20);
    await expect(panel).toContainText("25 matching identities");
    await panel
      .getByRole("button", { name: "Stop device details", exact: true })
      .click();
    release();
    await expect(
      panel.getByRole("button", {
        name: "Export all received JSON",
        exact: true,
      }),
    ).toBeEnabled();
    expect(metadata).toBe(1);
    const stopped = await jsonExport(page, panel);
    expect(
      stopped.rows.filter((row: any) => row.details !== null),
    ).toHaveLength(1);
    expect(
      stopped.rows.filter((row: any) => row.state === "pending"),
    ).toHaveLength(24);
    await panel
      .getByRole("button", { name: "Next scan page", exact: true })
      .click();
    await expect(rows).toHaveCount(5);
    expect(metadata).toBe(1);
    await panel
      .getByRole("button", { name: "Resume shown-page details", exact: true })
      .click();
    await expect(rows.filter({ hasText: "Actual Program 1" })).toHaveCount(5, {
      timeout: 30000,
    });
    await expect(
      panel.getByRole("button", {
        name: "Export all received JSON",
        exact: true,
      }),
    ).toBeEnabled();
    expect(metadata).toBe(6);
    await panel
      .getByRole("button", { name: "Previous scan page", exact: true })
      .click();
    await expect(rows.filter({ hasText: "Actual Program 1" })).toHaveCount(20, {
      timeout: 60000,
    });
    await expect(
      panel.getByRole("button", {
        name: "Export all received JSON",
        exact: true,
      }),
    ).toBeEnabled();
    expect(metadata).toBe(25);
    await panel
      .getByLabel("Search discovered devices", { exact: true })
      .fill("Named Controller 25");
    await expect(rows).toHaveCount(1);
    await expect(rows).toContainText("device,4190114");
    const all = await jsonExport(page, panel);
    expect(all.rows).toHaveLength(25);
    expect(all.rows.every((row: any) => row.details.identity_verified)).toBe(
      true,
    );
  } finally {
    release?.();
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    const result = await peer.close();
    expect(result.maximum_pending).toBe(1);
  }
});

test("a changed scan view suppresses a delayed real metadata result and no hidden page continues reading", async ({
  page,
  request,
}) => {
  const peer = await scanPeer(2);
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  let metadata = 0,
    release!: () => void,
    arrived!: () => void;
  const held = new Promise<void>((resolve) => {
      release = resolve;
    }),
    waiting = new Promise<void>((resolve) => {
      arrived = resolve;
    });
  await page.route("**/api/bacnet/device-details", async (route) => {
    metadata++;
    const response = await route.fetch();
    arrived();
    await held;
    await route.fulfill({ response });
  });
  try {
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    const panel = await openScan(page);
    await singleScan(panel, peer.first);
    await waiting;
    await expect(
      panel.getByRole("button", {
        name: `Use controller IP/127.0.0.1:${peer.first}/device,4190090`,
        exact: true,
      }),
    ).toBeDisabled();
    await panel
      .getByLabel("Search discovered devices", { exact: true })
      .fill("No device has this text");
    release();
    await expect(
      panel.getByRole("button", {
        name: "Export all received JSON",
        exact: true,
      }),
    ).toBeEnabled();
    await expect(scanRows(panel)).toHaveCount(0);
    const evidence = await jsonExport(page, panel);
    expect(evidence.rows).toHaveLength(2);
    expect(
      evidence.rows.every(
        (row: any) => row.details === null && row.state === "pending",
      ),
    ).toBe(true);
    expect(metadata).toBe(1);
    await page.getByRole("button", { name: "Program", exact: true }).click();
    expect(metadata).toBe(1);
  } finally {
    release?.();
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    await peer.close();
  }
});

test("an IP range over one page retains original bounds and continues only after an explicit cursor action", async ({
  page,
  request,
}) => {
  test.setTimeout(60000);
  const peer = await scanPeer();
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  const scans: any[] = [];
  page.on("request", (value) => {
    if (value.url().endsWith("/api/bacnet/scan-ip"))
      scans.push(value.postDataJSON());
  });
  try {
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    const panel = await openScan(page);
    await panel
      .getByLabel("IP scan mode", { exact: true })
      .selectOption("range");
    await panel
      .getByLabel("First scan IP address", { exact: true })
      .fill("127.0.0.0");
    await panel
      .getByLabel("Last scan IP address", { exact: true })
      .fill("127.1.0.0");
    await panel
      .getByLabel("Scan UDP port", { exact: true })
      .fill(String(peer.first));
    await panel
      .getByRole("button", { name: "Scan BACnet/IP devices", exact: true })
      .click();
    await expect(panel.getByRole("alert")).toContainText("65,536 hosts");
    expect(scans).toHaveLength(0);
    await panel
      .getByLabel("Last scan IP address", { exact: true })
      .fill("127.0.1.1");
    await panel
      .getByRole("button", { name: "Scan BACnet/IP devices", exact: true })
      .click();
    const response = panel.getByRole("region", {
      name: "Last IP discovery response",
      exact: true,
    });
    await expect(response).toContainText(
      "256 targets requested this page / 258 selected",
      { timeout: 30000 },
    );
    await expect(scanRows(panel).first()).toContainText("Actual Program 1");
    const next = panel.getByRole("button", {
      name: "Continue IP range from 127.0.1.0",
      exact: true,
    });
    await expect(next).toBeEnabled();
    expect(scans).toHaveLength(1);
    await next.click();
    await expect(response).toContainText(
      "2 targets requested this page / 258 selected",
    );
    await expect(scanRows(panel)).toHaveCount(1);
    expect(scans).toHaveLength(2);
    expect(scans[0]).toMatchObject({
      mode: "range",
      start_ip: "127.0.0.0",
      end_ip: "127.0.1.1",
    });
    expect(scans[1]).toEqual({ ...scans[0], cursor_ip: "127.0.1.0" });
    const evidence = await jsonExport(page, panel),
      scopes = Object.values(evidence.reports) as any[];
    expect(scopes).toHaveLength(1);
    expect(scopes[0].pages).toHaveLength(2);
    expect(scopes[0].pages[0].report.next_ip).toBe("127.0.1.0");
    expect(scopes[0].pages[1].report.next_ip).toBeNull();
    expect(evidence.rows).toHaveLength(1);
    const downloading = page.waitForEvent("download");
    await panel
      .getByRole("button", { name: "Export all received CSV", exact: true })
      .click();
    const records = csvRows((await (await downloading).path())!);
    const reports = records.filter((row: any) => row.row_type === "report");
    expect(reports).toHaveLength(2);
    expect(JSON.parse(reports[1].report_json)).toEqual(
      scopes[0].pages[1].report,
    );
    expect(JSON.parse(reports[1].report_json).devices).toEqual([]);
  } finally {
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    await peer.close();
  }
});

test("an empty real discovery response can be exported with full report evidence and cleared", async ({
  page,
  request,
}) => {
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  try {
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    const panel = await openScan(page);
    await singleScan(panel, await freePort());
    const response = panel.getByRole("region", {
      name: "Last IP discovery response",
      exact: true,
    });
    await expect(response).toContainText(
      "1 targets requested this page / 1 selected",
    );
    const exported = await jsonExport(page, panel);
    expect(exported.rows).toEqual([]);
    const scope = Object.values(exported.reports)[0] as any;
    expect(scope.pages).toHaveLength(1);
    expect(scope.pages[0].report.devices).toEqual([]);
    const downloading = page.waitForEvent("download");
    await panel
      .getByRole("button", { name: "Export all received CSV", exact: true })
      .click();
    const csv = csvRows((await (await downloading).path())!);
    expect(csv).toHaveLength(1);
    expect(csv[0].row_type).toBe("report");
    expect(JSON.parse(csv[0].report_json)).toEqual(scope.pages[0].report);
    expect(JSON.parse(csv[0].request_json)).toEqual(scope.pages[0].request);
    await panel
      .getByRole("button", { name: "Clear scan results", exact: true })
      .click();
    await expect(panel).toContainText("0 retained");
    await expect(panel).toContainText("0 latest discovery reports");
    await expect(
      panel.getByRole("button", {
        name: "Export all received JSON",
        exact: true,
      }),
    ).toBeDisabled();
  } finally {
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
  }
});

test("sorting by unread names keeps exactly one twenty-device page until explicit Next", async ({
  page,
  request,
}) => {
  test.setTimeout(120000);
  const peer = await scanPeer(25);
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  const metadata: string[] = [];
  page.on("request", (value) => {
    if (value.url().endsWith("/api/bacnet/device-details"))
      metadata.push(value.postDataJSON().device);
  });
  try {
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    const panel = await openScan(page);
    await panel
      .getByLabel("Sort discovered devices", { exact: true })
      .selectOption("name");
    await singleScan(panel, peer.first);
    const rows = scanRows(panel);
    await expect(rows.filter({ hasText: "Actual Program 1" })).toHaveCount(20, {
      timeout: 60000,
    });
    await expect(
      panel.getByRole("button", {
        name: "Export all received JSON",
        exact: true,
      }),
    ).toBeEnabled();
    expect(metadata).toHaveLength(20);
    expect(new Set(metadata).size).toBe(20);
    const first = await jsonExport(page, panel);
    expect(first.rows.filter((row: any) => row.details !== null)).toHaveLength(
      20,
    );
    expect(
      first.rows.filter((row: any) => row.state === "pending"),
    ).toHaveLength(5);
    await panel
      .getByRole("button", { name: "Next scan page", exact: true })
      .click();
    await expect(rows.filter({ hasText: "Actual Program 1" })).toHaveCount(5, {
      timeout: 20000,
    });
    await expect(
      panel.getByRole("button", {
        name: "Export all received JSON",
        exact: true,
      }),
    ).toBeEnabled();
    expect(metadata).toHaveLength(25);
    expect(new Set(metadata).size).toBe(25);
  } finally {
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    const result = await peer.close();
    expect(result.maximum_pending).toBe(1);
  }
});
