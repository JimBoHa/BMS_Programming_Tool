import { expect, test, type Page } from "@playwright/test";
import {
  chooseWorkspaceSurface,
  chooseWorkspaceTask,
  chooseWorkspaceTool,
} from "./workspace-navigation";
import { openCommunicationTool } from "./workflow-navigation";

const firstPort = "/dev/cu.BMS-MOCK-A";
const secondPort = "/dev/cu.BMS-MOCK-B";
const remoteDevice = "device,4190012";
const identity = {
  "object-identifier": remoteDevice,
  "object-name": "Serial fixture",
  "model-name": "Test controller",
  "firmware-revision": "1.0",
};
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
    identities: [] as Record<string, unknown>[],
    discoveries: [] as Record<string, unknown>[],
    replyToDiscovery: true,
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
      (path === "/api/bacnet/ip-scan-profile" ||
        path === "/api/bacnet/device-instance/status") &&
      route.request().method() === "GET"
    ) {
      // Local capability/receipt status cannot open an interface or transmit
      // BACnet traffic. POSTs and every scan/commissioning action remain blocked.
      await route.continue();
      return;
    }
    switch (path) {
      case "/api/bacnet/hardware/status":
      case "/api/bacnet/events/profile":
      case "/api/bacnet/schedules/library/profile":
      case "/api/bacnet/files/status":
      case "/api/bacnet/files/captures":
      case "/api/bacnet/cov/status":
      case "/api/bacnet/events/ack/profile":
        // These GETs inspect local service/capture metadata and cannot open an
        // interface or issue BACnet requests to a device.
        await route.continue();
        break;
      case "/api/bacnet/interfaces":
        await route.fulfill({ json: { interfaces: [] } });
        break;
      case "/api/bacnet/controller/inventory":
        await route.fulfill({
          json: {
            target: {
              address: body.address,
              device: body.device,
              router: null,
              dnet: null,
            },
            identity_verified: true,
            complete: true,
            offset: 0,
            total: 0,
            next_offset: null,
            objects: [],
          },
        });
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
        if (
          body.object_id === remoteDevice &&
          Object.hasOwn(identity, body.property_id)
        ) {
          mock.identities.push(body);
          await route.fulfill({
            json: {
              ...body,
              value: identity[body.property_id as keyof typeof identity],
            },
          });
          break;
        }
        mock.reads.push(body);
        await route.fulfill({ json: { ...body, value: 12.5 } });
        break;
      case "/api/bacnet/discover":
        mock.discoveries.push(body);
        await route.fulfill({
          json: mock.replyToDiscovery
            ? [
                {
                  address: body.address,
                  device: "device,4190012",
                  vendor: 999,
                  max_apdu: 480,
                },
              ]
            : [],
        });
        break;
      case "/api/bacnet/write-plan":
        await route.fulfill({
          json: {
            ...body,
            object: body.object_id,
            requested_value: body.value,
            token: "mock-preview-only",
          },
        });
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
  await page.getByRole("button", { name: /^Connect to a controller/ }).click();
  await chooseWorkspaceTool(page, "Direct MS/TP", "Connection transport");
  await expect(
    page.getByRole("heading", { name: "Direct BACnet MS/TP", exact: true }),
  ).toBeVisible();
  await expect.poll(() => mock.statusCalls).toBeGreaterThan(0);
  return mock;
}

async function openSerialStation(page: Page, address?: string) {
  await page
    .getByRole("button", { name: "Known controller address", exact: true })
    .click();
  const form = page.getByRole("region", {
    name: "Known controller connection",
    exact: true,
  });
  const target = form.getByLabel("Known controller address", { exact: true });
  await expect(target).toHaveValue("6");
  if (address) await target.fill(address);
  await form
    .getByLabel("Known Device object", { exact: true })
    .fill(remoteDevice);
  await form
    .getByRole("button", { name: "Open controller", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Controller overview" }),
  ).toContainText("Serial fixture");
  await chooseWorkspaceTask(page, "Points & I/O");
  await chooseWorkspaceTool(page, "Read properties", "Controller task tools");
}

async function chooseSerialCommands(page: Page) {
  await chooseWorkspaceSurface(page, "Workspace");
  await chooseWorkspaceTask(page, "Points & I/O");
  await chooseWorkspaceTool(
    page,
    "Commands & overrides",
    "Controller task tools",
  );
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
  const card = page.locator("section.card").filter({
    has: page.getByRole("heading", {
      name: "Direct BACnet MS/TP",
      exact: true,
    }),
  });
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
  await openSerialStation(page, "37");
  expect(mock.identities.map((row) => [row.address, row.property_id])).toEqual(
    Object.keys(identity).map((property) => ["37", property]),
  );
  const target = page.getByLabel("Controller address", { exact: true });
  await expect(target).toHaveValue("37");
  await expect(target).not.toBeEditable();
  await page
    .getByLabel("Object identifier", { exact: true })
    .fill("analog-input,4");
  await page.getByLabel("Property", { exact: true }).fill("present-value");
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
  const replies = page.getByRole("region", {
    name: "Discovery replies",
    exact: true,
  });
  const selected = replies.getByRole("button", {
    name: "Open controller device,4190012 at 37",
  });
  await selected.focus();
  await page.keyboard.press("Shift+Tab");
  await page.keyboard.press("Tab");
  await expect(selected).toBeFocused();
  await replies.screenshot({
    path: `test-results/point-discovery-${test.info().project.name}.png`,
  });
  mock.replyToDiscovery = false;
  await page
    .getByRole("button", { name: "Who-Is target", exact: true })
    .click();
  await expect(replies.getByRole("status")).toHaveText(
    "No device replied during this request.",
  );
  await expect(selected).toHaveCount(0);
  expect(mock.discoveries).toEqual([{ address: "37" }, { address: "37" }]);
  await openCommunicationTool(page, "Direct serial");
  await expect(
    page.getByLabel("MS/TP link status", { exact: true }),
  ).toContainText("idle");
  await card.screenshot({ path: "test-results/studio-mstp-connected.png" });
  await chooseSerialCommands(page);
  await page
    .getByRole("button", { name: "Preview command", exact: true })
    .click();
  const apply = page.getByRole("button", {
    name: "Apply previewed command",
    exact: true,
  });
  await expect(apply).toBeEnabled();

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
    page.getByRole("button", { name: "Preview command", exact: true }),
  ).toBeDisabled();
  if (await apply.count()) await expect(apply).toBeDisabled();
  await chooseWorkspaceTool(page, "Read properties", "Controller task tools");
  await expect(replies).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Who-Is target", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Read property", exact: true }),
  ).toBeDisabled();
  await openCommunicationTool(page, "Direct serial");
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
  await openSerialStation(page);
  const target = page.getByLabel("Controller address", { exact: true });
  await expect(target).toHaveValue(/^\d+$/);
  await expect(target).not.toHaveValue("5");
  await page
    .getByLabel("Object identifier", { exact: true })
    .fill("analog-input,4");
  await page.getByLabel("Property", { exact: true }).fill("present-value");
  await page
    .getByRole("button", { name: "Read property", exact: true })
    .click();
  await expect.poll(() => mock.reads.length).toBe(1);
  expect(mock.reads[0].address).toMatch(/^\d+$/);
  expect(mock.connects).toEqual([]);
  expect(mock.unexpected).toEqual([]);
  expect(
    (await (await request.get("/api/bacnet/status")).json()).connected,
  ).toBe(false);
});
