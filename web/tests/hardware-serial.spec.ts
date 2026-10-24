import { test, expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";

const config = {
  transport: "mstp",
  port: "/dev/cu.AUTHORED-PTY",
  mac: 0,
  baudrate: 38400,
  instance: 4190001,
  max_master: 1,
  max_info_frames: 1,
};
const target = {
  transport: "direct-mstp",
  address: "1",
  device: "device,123",
  router: null,
  dnet: null,
};
const report = {
  id: "a".repeat(32),
  profile: "bacnet-hardware-survey/1",
  target,
  connector_config: config,
  identity: {
    name: "Authored serial controller",
    model: "FX-PCG2611-0",
    object: "device,123",
  },
  status: "complete",
  inventory: {
    complete: true,
    read: 3,
    total: 3,
    objects: ["device,123", "analog-input,56", "file,31"],
  },
  inputs_complete: true,
  inputs: [
    {
      object: "analog-input,56",
      name: "Fixture temperature",
      present_value: -12.5,
      units: 64,
      device_type: "UI IN1",
      slot: 1,
      host: { kind: "local-inferred" },
      errors: [],
    },
  ],
  modules: [],
  candidates: [],
  errors: [],
  read_only: true,
  controller_writes: false,
};
const completed = {
  id: "b".repeat(32),
  kind: "survey",
  status: "complete",
  target,
  connector_config: config,
  report,
  report_id: report.id,
};

async function setup(page: Page) {
  const mock = {
    healthy: true,
    connectionConfig: { ...config },
    running: false,
    surveys: [] as any[],
    archives: [] as any[],
    unexpected: [] as string[],
  };
  await page.route("**/api/ports", (route) =>
    route.fulfill({
      json: [
        { device: config.port, description: "Authored interface metadata" },
      ],
    }),
  );
  await page.route("**/api/bacnet/**", async (route) => {
    const request = route.request(),
      path = new URL(request.url()).pathname;
    const respond = (value: unknown) => route.fulfill({ json: value });
    if (path === "/api/bacnet/status")
      return respond({
        connected: mock.healthy,
        config: mock.connectionConfig,
        commands: [],
        serial_link: {
          connected: mock.healthy,
          fault: mock.healthy ? null : "Authored worker stopped",
        },
      });
    if (path === "/api/bacnet/hardware/status")
      return respond({
        reports: [report],
        jobs: [completed],
        archives: [],
        captures: [],
      });
    if (path === "/api/bacnet/hardware/survey") {
      mock.surveys.push(request.postDataJSON());
      return respond(
        mock.running
          ? {
              ...completed,
              status: "running",
              report: undefined,
              report_id: undefined,
            }
          : completed,
      );
    }
    if (path === `/api/bacnet/hardware/jobs/${completed.id}/cancel`)
      return respond({
        ...completed,
        status: "cancelled",
        report: {
          ...report,
          status: "partial",
          cancelled: true,
          inventory: { ...report.inventory, complete: false },
          candidates: [],
        },
      });
    if (path === `/api/bacnet/hardware/jobs/${completed.id}`)
      return respond(
        mock.running
          ? {
              ...completed,
              status: "running",
              report: undefined,
              report_id: undefined,
            }
          : completed,
      );
    if (path === `/api/bacnet/hardware/reports/${report.id}`)
      return respond(report);
    if (path === `/api/bacnet/hardware/reports/${report.id}/export`)
      return route.fulfill({
        body: JSON.stringify(report),
        contentType: "application/json",
      });
    if (path === "/api/bacnet/hardware/read-archive") {
      mock.archives.push(request.postDataJSON());
      return route.fulfill({
        status: 422,
        json: {
          detail:
            "Serial interface differs from the saved survey; reopen that exact interface or run a new survey.",
        },
      });
    }
    if (
      request.method() === "GET" &&
      (path === "/api/bacnet/ip-scan-profile" ||
        path === "/api/bacnet/cov/status" ||
        path === "/api/bacnet/events/profile" ||
        path === "/api/bacnet/schedules/library/profile" ||
        path === "/api/bacnet/events/ack/profile" ||
        path.startsWith("/api/bacnet/files/"))
    )
      return route.continue();
    mock.unexpected.push(path);
    return route.fulfill({
      status: 503,
      json: { detail: "Field action blocked by serial UI fixture." },
    });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  const panel = page.getByRole("region", {
    name: "Controller hardware and input survey",
    exact: true,
  });
  await expect(panel.getByLabel("Hardware transport")).toHaveValue(
    "direct-mstp",
  );
  await panel
    .getByLabel("Hardware controller address", { exact: true })
    .fill("1");
  await panel
    .getByLabel("Hardware Device object", { exact: true })
    .fill("device,123");
  return { panel, mock };
}

test("serial hardware survey selects explicit local transport and preserves bus provenance in saved reopening and exports", async ({
  page,
}) => {
  let { panel, mock } = await setup(page);
  await expect(panel.getByLabel("Hardware serial interface")).toContainText(
    config.port,
  );
  await expect(panel.getByLabel("Hardware router (optional)")).toBeDisabled();
  await expect(
    panel.getByLabel("Hardware destination network (optional)"),
  ).toBeDisabled();
  await panel
    .getByRole("button", { name: "Survey controller inputs", exact: true })
    .click();
  await expect(
    panel.getByRole("region", { name: "Hardware survey results" }),
  ).toContainText("Direct MS/TP MAC 1");
  await expect(
    panel.getByRole("region", { name: "Hardware survey results" }),
  ).toContainText("38400 baud · client MAC 0");
  await expect(
    panel.getByRole("region", { name: "Hardware survey results" }),
  ).toContainText("-12.5");
  expect(mock.surveys).toHaveLength(1);
  expect(mock.surveys[0]).toMatchObject({
    transport: "direct-mstp",
    address: "1",
    device: "device,123",
  });
  expect(mock.surveys[0]).not.toHaveProperty("router");
  expect(mock.surveys[0]).not.toHaveProperty("dnet");
  const pending = page.waitForEvent("download");
  await panel
    .getByRole("button", { name: "Download hardware JSON", exact: true })
    .click();
  const downloaded = JSON.parse(
    readFileSync((await (await pending).path())!, "utf8"),
  );
  expect(downloaded.connector_config).toEqual(config);
  expect(downloaded.target.transport).toBe("direct-mstp");
  await panel
    .getByRole("button", { name: "Read controller archive", exact: true })
    .click();
  await expect(panel.getByRole("alert")).toContainText(
    "Serial interface differs",
  );
  expect(mock.archives).toEqual([{ report_id: report.id }]);
  expect(mock.unexpected).toEqual([]);
  await page.reload();
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  panel = page.getByRole("region", {
    name: "Controller hardware and input survey",
    exact: true,
  });
  await panel
    .getByLabel("Saved hardware report", { exact: true })
    .selectOption(report.id);
  await panel
    .getByRole("button", { name: "Open saved hardware report", exact: true })
    .click();
  await expect(
    panel.getByRole("region", { name: "Hardware survey results" }),
  ).toContainText(config.port);
  expect(mock.surveys).toHaveLength(1);
  mock.connectionConfig.max_info_frames = 2;
  await expect(
    panel.getByRole("button", { name: "Read controller archive", exact: true }),
  ).toBeDisabled();
  await expect(panel.getByLabel("Archive interface mismatch")).toContainText(
    "exact serial port",
  );
});

test("serial hardware UI rejects own/broadcast MACs, cancels jobs and disables fresh reads after link failure", async ({
  page,
}) => {
  const { panel, mock } = await setup(page);
  for (const wrong of ["0", "255", "3101:1"]) {
    await panel
      .getByLabel("Hardware controller address", { exact: true })
      .fill(wrong);
    await panel
      .getByRole("button", { name: "Survey controller inputs", exact: true })
      .click();
    await expect(panel.getByRole("alert")).toContainText(
      "remote decimal MS/TP MAC",
    );
  }
  expect(mock.surveys).toEqual([]);
  await panel
    .getByLabel("Hardware controller address", { exact: true })
    .fill("1");
  mock.running = true;
  await panel
    .getByRole("button", { name: "Survey controller inputs", exact: true })
    .click();
  await expect(
    panel.getByRole("button", { name: "Cancel hardware survey", exact: true }),
  ).toBeEnabled();
  await panel
    .getByRole("button", { name: "Cancel hardware survey", exact: true })
    .click();
  await expect(
    panel.getByRole("region", { name: "Hardware survey results" }),
  ).toContainText("captured survey readings", { ignoreCase: true });
  await expect(panel).toContainText("cancelled");
  mock.healthy = false;
  await expect(
    panel.getByRole("button", {
      name: "Survey controller inputs",
      exact: true,
    }),
  ).toBeDisabled();
  expect(mock.unexpected).toEqual([]);
});
