import { expect, test, type Page } from "@playwright/test";

const firstPort = "/dev/cu.BMS-MOCK-A";
const secondPort = "/dev/cu.BMS-MOCK-B";
const listedPorts = [
  { device: firstPort, description: "Mock automatic-direction RS-485 A" },
  { device: secondPort, description: "Mock automatic-direction RS-485 B" },
];

function openedStatus(config: Record<string, unknown>) {
  return {
    connected: true,
    config: { transport: "mstp", ...config },
    commands: [],
    serial_link: {
      connected: true,
      worker_alive: true,
      state: "idle",
      mac: config.mac,
      port: config.port,
      baudrate: config.baudrate,
      max_master: config.max_master,
      max_info_frames: config.max_info_frames,
      scope: "legacy-ms-tp-npdu",
      btcvt: false,
      physical_bus_verified: false,
      fault: null as string | null,
      error: null as string | null,
      statistics: { transmitted_frames: 4, received_npdus: 1 },
    },
  };
}

async function mockMstp(
  page: Page,
  restored?: ReturnType<typeof openedStatus>,
) {
  const mock = {
    ports: [...listedPorts],
    status: restored || { connected: false, config: null, commands: [] },
    connects: [] as Record<string, unknown>[],
    reads: [] as Record<string, unknown>[],
    discoveries: [] as Record<string, unknown>[],
    applied: [] as Record<string, unknown>[],
    statusCalls: 0,
    unexpected: [] as string[],
  };
  await page.route("**/api/ports", (route) =>
    route.fulfill({ json: mock.ports }),
  );
  // Field BACnet requests are intercepted. These tests must never activate an
  // actual serial worker or a BACnet/IP interface on the isolated test server.
  await page.route("**/api/bacnet/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const body =
      route.request().method() === "POST"
        ? route.request().postDataJSON()
        : null;
    if (
      path === "/api/bacnet/ip-scan-profile" &&
      route.request().method() === "GET"
    ) {
      // Reading Scan's local capability profile cannot open an interface or
      // transmit BACnet traffic. POSTs and every scan action remain blocked.
      await route.continue();
      return;
    }
    switch (path) {
      case "/api/bacnet/files/status":
      case "/api/bacnet/files/captures":
        // These GETs inspect local service/capture metadata and cannot open an
        // interface or issue BACnet requests to a device.
        await route.continue();
        break;
      case "/api/bacnet/status":
        mock.statusCalls++;
        await route.fulfill({ json: mock.status });
        break;
      case "/api/bacnet/connect-mstp":
        mock.connects.push(body);
        mock.status = openedStatus(body);
        await route.fulfill({ json: mock.status.config });
        break;
      case "/api/bacnet/read":
        mock.reads.push(body);
        await route.fulfill({ json: { ...body, value: 12.5 } });
        break;
      case "/api/bacnet/discover":
        mock.discoveries.push(body);
        await route.fulfill({
          json: [
            {
              address: body.address,
              device: "device,4190012",
              vendor: 999,
              max_apdu: 480,
            },
          ],
        });
        break;
      case "/api/bacnet/write-plan":
        await route.fulfill({ json: { ...body, token: "mock-preview-only" } });
        break;
      case "/api/bacnet/write-apply":
        mock.applied.push(body);
        await route.fulfill({ json: { command: "mock-preview-only" } });
        break;
      default:
        mock.unexpected.push(path);
        await route.fulfill({
          status: 503,
          json: { detail: "Unexpected BACnet request blocked by UI test." },
        });
    }
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Connections", exact: true }),
  ).toBeVisible();
  await expect.poll(() => mock.statusCalls).toBeGreaterThan(0);
  return mock;
}

test("select serial policy, use a decimal target and disable point actions after a polled worker fault", async ({
  page,
  request,
}) => {
  const mock = await mockMstp(page);
  const open = page.getByRole("button", {
    name: "Open MS/TP interface",
    exact: true,
  });
  await expect(open).toBeDisabled();
  await page
    .getByRole("combobox", { name: "MS/TP serial port", exact: true })
    .selectOption(secondPort);
  await page
    .getByRole("combobox", { name: "MS/TP baud rate", exact: true })
    .selectOption("76800");
  await page.getByLabel("MS/TP master MAC", { exact: true }).fill("5");
  await page
    .getByLabel("MS/TP client device instance", { exact: true })
    .fill("4190067");
  await page.getByLabel("Maximum master MAC", { exact: true }).fill("9");
  await page.getByLabel("Maximum frames per token", { exact: true }).fill("3");
  await open.click();
  await expect(
    page.getByText("BACnet interface open", { exact: true }),
  ).toBeVisible();
  expect(mock.connects).toEqual([
    {
      port: secondPort,
      mac: 5,
      instance: 4190067,
      baudrate: 76800,
      max_master: 9,
      max_info_frames: 3,
    },
  ]);
  const target = page.getByLabel("Unicast target", { exact: true });
  await expect(target).toHaveValue("6");
  await target.fill("37");
  await page
    .getByLabel("Object identifier", { exact: true })
    .fill("analog-input,4");
  await page
    .getByRole("button", { name: "Read property", exact: true })
    .click();
  expect(mock.reads).toEqual([
    {
      address: "37",
      object_id: "analog-input,4",
      property_id: "present-value",
    },
  ]);
  await expect(
    page.locator("pre.result").filter({ hasText: '"value": 12.5' }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Who-Is target", exact: true })
    .click();
  expect(mock.discoveries).toEqual([{ address: "37" }]);
  await expect(
    page.getByRole("cell", { name: "device,4190012", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Preview command", exact: true })
    .click();
  const apply = page.getByRole("button", {
    name: "Apply previewed command",
    exact: true,
  });
  await expect(apply).toBeEnabled();

  const card = page.locator("section.card").filter({
    has: page.getByRole("heading", {
      name: "Direct BACnet MS/TP",
      exact: true,
    }),
  });
  await card.screenshot({ path: "test-results/studio-mstp-connected.png" });
  const healthy = mock.status as ReturnType<typeof openedStatus>;
  const fault = "Duplicate address or local echo; transmission is suspended.";
  mock.status = {
    ...healthy,
    connected: false,
    serial_link: {
      ...healthy.serial_link,
      connected: false,
      worker_alive: false,
      state: "fault",
      fault,
      error: fault,
    },
  };
  await expect(
    page.getByText("No BACnet interface open", { exact: true }),
  ).toBeVisible({ timeout: 5000 });
  await expect(
    page.getByRole("button", { name: "Who-Is target", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Read property", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Preview command", exact: true }),
  ).toBeDisabled();
  if (await apply.count()) await expect(apply).toBeDisabled();
  await expect(
    page.getByLabel("MS/TP link status", { exact: true }),
  ).toContainText(fault);
  await card.screenshot({ path: "test-results/studio-mstp-fault.png" });
  expect(mock.applied).toEqual([]);
  expect(mock.unexpected).toEqual([]);
  expect(
    (await (await request.get("/api/bacnet/status")).json()).connected,
  ).toBe(false);
});

test("no detected port or a removed selected port disables opening the serial master", async ({
  page,
  request,
}) => {
  const mock = await mockMstp(page);
  const select = page.getByRole("combobox", {
    name: "MS/TP serial port",
    exact: true,
  });
  const open = page.getByRole("button", {
    name: "Open MS/TP interface",
    exact: true,
  });
  const refresh = page.getByRole("button", {
    name: "Refresh serial interfaces",
    exact: true,
  });
  mock.ports = [];
  await refresh.click();
  await expect(select.locator("option")).toHaveCount(1);
  await expect(open).toBeDisabled();
  mock.ports = [...listedPorts];
  await refresh.click();
  await expect(select.locator("option")).toHaveCount(3);
  await select.selectOption(firstPort);
  await expect(open).toBeEnabled();
  mock.ports = [];
  await refresh.click();
  await expect(select.locator("option")).toHaveCount(1);
  await expect(open).toBeDisabled();
  expect(mock.connects).toEqual([]);
  expect(mock.unexpected).toEqual([]);
  expect(
    (await (await request.get("/api/bacnet/status")).json()).connected,
  ).toBe(false);
});

test("a restored running MS/TP interface starts point services with a remote decimal MAC", async ({
  page,
  request,
}) => {
  const restored = openedStatus({
    port: secondPort,
    mac: 5,
    instance: 4190067,
    baudrate: 76800,
    max_master: 9,
    max_info_frames: 3,
  });
  const mock = await mockMstp(page, restored);
  await expect(
    page.getByText("BACnet interface open", { exact: true }),
  ).toBeVisible();
  const target = page.getByLabel("Unicast target", { exact: true });
  await expect(target).toHaveValue(/^\d+$/);
  await expect(target).not.toHaveValue("5");
  await page
    .getByRole("button", { name: "Read property", exact: true })
    .click();
  expect(mock.reads).toHaveLength(1);
  expect(mock.reads[0].address).toMatch(/^\d+$/);
  expect(mock.connects).toEqual([]);
  expect(mock.unexpected).toEqual([]);
  expect(
    (await (await request.get("/api/bacnet/status")).json()).connected,
  ).toBe(false);
});
