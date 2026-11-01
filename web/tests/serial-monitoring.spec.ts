import {
  test,
  expect,
  type Page,
  type APIRequestContext,
} from "@playwright/test";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { openMonitoring } from "./monitoring-navigation";

type Port = { device: string; description: string; audit: string };
const fixture = () =>
  JSON.parse(readFileSync(process.env.BMS_SERIAL_MONITOR_FIXTURE!, "utf8")) as {
    ports: Port[];
  };
const wire = (port: Port) =>
  readFileSync(port.audit, "utf8")
    .trim()
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line));
const digest = (bytes: Buffer) =>
  createHash("sha256").update(bytes).digest("hex");
async function reset(request: APIRequestContext) {
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  const status = await (await request.get("/api/field-trends/status")).json();
  for (const job of status.jobs)
    if (job.running)
      expect(
        (
          await request.post("/api/field-trends/stop", {
            headers,
            data: { id: job.id },
          })
        ).ok(),
      ).toBeTruthy();
  expect(
    (await request.post("/api/bacnet/disconnect", { headers, data: {} })).ok(),
  ).toBeTruthy();
  return headers;
}
async function connectSerial(page: Page, port: Port, first = false) {
  if (first) {
    await page.goto("/");
    await page
      .getByRole("button", { name: /^Connect to a controller/ })
      .click();
  } else {
    await page
      .getByRole("button", { name: "Change controller", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Close BACnet interface", exact: true })
      .click();
    await page
      .getByRole("button", { name: "1 · Connection", exact: true })
      .click();
  }
  await page
    .getByRole("navigation", { name: "Connection transport" })
    .getByRole("button", { name: "Direct MS/TP", exact: true })
    .click();
  await page
    .getByRole("combobox", { name: "MS/TP serial port", exact: true })
    .selectOption(port.device);
  await page
    .getByRole("combobox", { name: "MS/TP baud rate", exact: true })
    .selectOption("38400");
  await page.getByLabel("MS/TP master MAC", { exact: true }).fill("0");
  await page.getByLabel("Maximum master MAC", { exact: true }).fill("1");
  await page.getByLabel("Maximum frames per token", { exact: true }).fill("1");
  await page
    .getByRole("button", { name: "Open MS/TP interface", exact: true })
    .click();
  await page.getByLabel("Known controller address", { exact: true }).fill("1");
  await page
    .getByLabel("Known Device object", { exact: true })
    .fill("device,123");
  await expect(page.getByLabel("Known router", { exact: true })).toHaveCount(0);
  await page
    .getByRole("region", { name: "Known controller connection" })
    .getByRole("button", { name: "Open controller", exact: true })
    .click();
  await expect(page.getByLabel("Working context")).toContainText(
    `Authored serial controller ${port.description.endsWith("A") ? "A" : "B"}`,
  );
}
const fieldPicker = (page: Page) =>
  page.getByLabel("Field discovered object object", { exact: true });

test("serial controller keeps IP-only native backup unavailable with credentials configured", async ({
  page,
  request,
}) => {
  const headers = await reset(request),
    port = fixture().ports[0];
  const configured = await request.post(
    "/api/bacnet/controller/native-application/credentials",
    {
      headers,
      data: { backup: "authored-backup", restore: "authored-restore" },
    },
  );
  expect(configured.status(), await configured.text()).toBe(200);
  await connectSerial(page, port, true);
  await page
    .getByRole("navigation", { name: "Workspace tasks", exact: true })
    .getByRole("button", { name: "Program", exact: true })
    .click();
  await page
    .getByRole("navigation", { name: "Current task tools", exact: true })
    .getByRole("button", { name: "Native backup defaults", exact: true })
    .click();
  const panel = page.getByRole("region", {
    name: "Native default controller transfer",
    exact: true,
  });
  await panel
    .getByText("Native backup and restore credentials", { exact: true })
    .click();
  await expect(
    panel.getByText("Native credentials configured on this machine.", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    panel.getByRole("button", {
      name: "Read current native backup",
      exact: true,
    }),
  ).toBeDisabled();
  await expect(panel).toContainText(
    "Native backup and application transfer require a BACnet/IPv4 interface.",
  );
  await expect(
    panel.getByRole("button", {
      name: "Save native transfer credentials",
      exact: true,
    }),
  ).toBeDisabled();
  await reset(request);
});

test("serial controller sampling discovers actual objects and records verified source-bound values", async ({
  page,
  request,
}) => {
  test.setTimeout(60000);
  await reset(request);
  const port = fixture().ports[0],
    before = wire(port).length;
  await connectSerial(page, port, true);
  await openMonitoring(page, "Field recording");
  await expect(page.getByLabel("Field sampling target")).toContainText(
    port.device,
  );
  await expect(fieldPicker(page)).toContainText(
    "Serial temperature · analog-input,1",
  );
  await expect(page.getByLabel("Field address 1", { exact: true })).toHaveValue(
    "1",
  );
  await expect(
    page.getByLabel("Field address 1", { exact: true }),
  ).toHaveAttribute("readonly", "");
  await fieldPicker(page).selectOption("analog-input,1");
  const response = page.waitForResponse("**/api/field-trends/start");
  await page
    .getByRole("button", { name: "Start field sampling", exact: true })
    .click();
  const started = await response,
    job = await started.json(),
    body = started.request().postDataJSON();
  expect(started.ok()).toBeTruthy();
  expect(body.controller_target).toEqual({
    transport: "direct-mstp",
    address: "1",
    device: "device,123",
    router: null,
    dnet: null,
  });
  expect(body.expected_connector_config.port).toBe(port.device);
  await expect(
    page.getByLabel("Field trend source", { exact: true }),
  ).toHaveValue(job.source);
  await expect(
    page.getByRole("cell", { name: "good", exact: true }).first(),
  ).toBeVisible({ timeout: 10000 });
  await page
    .getByRole("row")
    .filter({ has: page.getByRole("button", { name: job.id, exact: true }) })
    .getByRole("button", { name: "Stop sampling", exact: true })
    .click();
  const rows = await (
    await request.get("/api/field-trends/samples", {
      params: { source: job.source },
    })
  ).json();
  expect(rows.length).toBeGreaterThan(0);
  expect(
    rows.every(
      (row: any) =>
        row.quality === "good" &&
        row.provenance.connector_config.port === port.device &&
        row.provenance.controller_target.transport === "direct-mstp",
    ),
  ).toBeTruthy();
  expect(rows[0].provenance.connector_config.port).toBe(port.device);
  expect(rows[0].provenance.controller_target.transport).toBe("direct-mstp");
  expect(Object.is(rows[0].value, -0)).toBeTruthy();
  expect(
    wire(port)
      .slice(before)
      .every((row) => row.service === 12),
  ).toBeTruthy();
  await page.screenshot({
    path: test.info().outputPath("serial-field-monitoring.png"),
    fullPage: true,
  });
});

test("serial Trend Log history downloads exact response bytes and remains available after closing its interface", async ({
  page,
  request,
}) => {
  test.setTimeout(60000);
  await reset(request);
  const port = fixture().ports[0];
  await connectSerial(page, port, true);
  await openMonitoring(page, "Controller history");
  await expect(
    page.getByLabel("History selected controller", { exact: true }),
  ).toContainText(port.device);
  const picker = page.getByLabel("History Trend Log object object", {
    exact: true,
  });
  await expect(picker).toContainText(
    "Serial temperature history · trend-log,1",
  );
  await picker.selectOption("trend-log,1");
  await page
    .getByLabel("History device clock timezone", { exact: true })
    .fill("UTC");
  await page.getByLabel("History range reference", { exact: true }).fill("100");
  await page.getByLabel("History record limit", { exact: true }).fill("3");
  await page.getByLabel("History page size", { exact: true }).fill("2");
  let bytes = Buffer.alloc(0);
  // Preserve the actual backend response before browser/DevTools body capture.
  // Pass it through unchanged; all production HTTP and serial services still run.
  await page.route("**/api/bacnet/history/read", async (route) => {
    const response = await route.fetch({ maxRetries: 0 });
    bytes = await response.body();
    await route.fulfill({ response, body: bytes });
  });
  const response = page.waitForResponse("**/api/bacnet/history/read");
  await page
    .getByRole("button", { name: "Read device history", exact: true })
    .click();
  const original = await response;
  expect(bytes.length).toBeGreaterThan(0);
  const report = JSON.parse(bytes.toString());
  expect(original.ok()).toBeTruthy();
  expect(report.identity_verified).toBeTruthy();
  expect(report.controller_target.transport).toBe("direct-mstp");
  expect(report.connector_config.port).toBe(port.device);
  expect(report.records.map((row: any) => row.value)).toEqual([-0, 1.25, 2.25]);
  const download = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Download device history JSON", exact: true })
    .click();
  expect(digest(readFileSync((await (await download).path())!))).toBe(
    digest(bytes),
  );
  await page
    .getByRole("button", {
      name: "Save immutable history capture",
      exact: true,
    })
    .click();
  await expect(
    page.getByRole("status").filter({ hasText: "Saved an immutable" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Change controller", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Close BACnet interface", exact: true })
    .click();
  await expect(
    page.getByText("No BACnet interface open", { exact: true }),
  ).toBeVisible();
  const reads = wire(port).length;
  await openMonitoring(page, "Controller history");
  await page
    .getByLabel("Saved device history capture", { exact: true })
    .selectOption(report.id);
  await page
    .getByRole("button", { name: "Open history capture", exact: true })
    .click();
  await expect(
    page.getByText(
      "Saved local capture: historical evidence, usable without a field connection.",
      { exact: true },
    ),
  ).toBeVisible();
  expect(wire(port)).toHaveLength(reads);
});

test("a held sampling response cannot move to another serial port with the same controller MAC and Device ID", async ({
  page,
  request,
}) => {
  test.setTimeout(90000);
  await reset(request);
  const [first, second] = fixture().ports;
  await connectSerial(page, first, true);
  await openMonitoring(page, "Field recording");
  await fieldPicker(page).selectOption("analog-input,1");
  await page
    .getByLabel("Field signal 1", { exact: true })
    .fill("original_bus_draft");
  let release: (() => void) | undefined, job: any;
  await page.route("**/api/field-trends/start", async (route) => {
    const response = await route.fetch();
    job = await response.json();
    await new Promise<void>((resolve) => {
      release = resolve;
    });
    await route.fulfill({ response });
  });
  try {
    const late = page.waitForResponse("**/api/field-trends/start");
    await page
      .getByRole("button", { name: "Start field sampling", exact: true })
      .click();
    await expect.poll(() => Boolean(release)).toBeTruthy();
    await connectSerial(page, second);
    const oldReads = wire(first).length;
    await openMonitoring(page, "Field recording");
    await expect(page.getByLabel("Field sampling target")).toContainText(
      second.device,
    );
    await expect(
      page.getByLabel("Field signal 1", { exact: true }),
    ).not.toHaveValue("original_bus_draft");
    release!();
    await late;
    await expect(
      page.getByLabel("Field trend source", { exact: true }),
    ).toHaveValue("");
    await expect(
      page.getByRole("cell").filter({ hasText: first.device }).first(),
    ).toBeVisible();
    const status = await (await request.get("/api/field-trends/status")).json();
    expect(
      status.jobs.find((row: any) => row.id === job.id).connector_config.port,
    ).toBe(first.device);
    expect(wire(first)).toHaveLength(oldReads);
    await expect(
      page.getByLabel("Field object identifier 1", { exact: true }),
    ).toHaveValue("");
  } finally {
    release?.();
  }
});
