import { test, expect, type Page, type Route } from "@playwright/test";
import { readFileSync } from "node:fs";

// Public, authored evidence only. Every hardware request is intercepted; these
// tests never open a BACnet interface or send packets to a site network.
const target = {
  address: "3101:9",
  device: "device,319009",
  router: "198.51.100.20",
  dnet: 3101,
};
const report = {
  profile: "bacnet-hardware-survey/1",
  id: "survey-fixture",
  target,
  identity: { name: "Authored controller fixture", model: "FX-PCG2611-0" },
  inventory: {
    total: 4,
    read: 4,
    complete: true,
    objects: [
      "device,319009",
      "analog-input,1",
      "binary-input,2",
      "binary-input,3",
    ],
  },
  inputs: [
    {
      object: "analog-input,1",
      name: "Fixture temperature",
      description: "Authored temperature evidence",
      device_type: "UI IN1",
      slot: 1,
      sa_mac: 4,
      host: { kind: "sa", sa_mac: 4 },
      terminal_type: "UI",
      setup_raw: 3,
      present_value: 68.5,
      units: 64,
      reliability: 0,
      status_flags: "0000",
      out_of_service: false,
      errors: [],
    },
    {
      object: "binary-input,2",
      name: "Fixture compressor alarm",
      description: "Dry-contact compatibility unverified",
      device_type: "UI IN4",
      slot: 4,
      sa_mac: 4,
      host: { kind: "sa", sa_mac: 4 },
      terminal_type: "UI",
      setup_raw: 1,
      present_value: "inactive",
      reliability: 0,
      status_flags: "0000",
      out_of_service: false,
      errors: [{ property: 3645, error: "Authored property error retained" }],
    },
    {
      object: "binary-input,3",
      name: "Fixture pump status",
      device_type: "BI IN1",
      slot: 1,
      sa_mac: 7,
      host: { kind: "sa", sa_mac: 7 },
      terminal_type: "BI",
      present_value: "active",
      reliability: 0,
      out_of_service: false,
      errors: [],
    },
  ],
  modules: [
    {
      host: "sa",
      sa_mac: 4,
      configured_model: "FX-PCX3711-0",
      name: "Authored UI module",
      capacity: { universal_inputs: [1, 2, 3, 4], binary_inputs: [] },
      occupied_slots: [1, 4],
    },
    {
      host: "sa",
      sa_mac: 7,
      configured_model: "FX-PCX3721-0",
      name: "Authored BI module",
      capacity: {
        universal_inputs: [],
        binary_inputs: Array.from({ length: 16 }, (_, index) => index + 1),
      },
      occupied_slots: [1],
    },
  ],
  candidates: [
    {
      host: "sa",
      sa_mac: 4,
      slot: 2,
      terminal: "IN2",
      terminal_type: "UI",
      voltage_capable: true,
      status: "candidate",
      reason: "No assignment observed; wiring unverified",
    },
    {
      host: "sa",
      sa_mac: 7,
      slot: 16,
      terminal: "IN16",
      terminal_type: "BI",
      voltage_capable: false,
      status: "candidate",
      reason: "No assignment observed; wiring unverified",
    },
  ],
  warnings: [
    "Physical labels and native assignment completeness are unverified.",
  ],
};
const archive = {
  id: "archive-fixture",
  profile: "jci-moi-hardware-evidence/1",
  source: {
    filename: "authored-fixture.moi",
    sha256: "a".repeat(64),
    bytes: 42,
  },
  modules: report.modules,
};
const completed = {
  id: "job-fixture",
  status: "completed",
  report_id: report.id,
  report,
  target,
};
type RequestRecord = { path: string; method: string; body: any };
async function setup(
  page: Page,
  handle?: (route: Route, record: RequestRecord) => Promise<boolean>,
) {
  const requests: RequestRecord[] = [];
  await page.route("**/api/**", async (route) => {
    const request = route.request(),
      path = new URL(request.url()).pathname;
    let body: any = null;
    try {
      body = request.postDataJSON();
    } catch {
      body = request.postData();
    }
    const record = { path, method: request.method(), body };
    requests.push(record);
    if (handle && (await handle(route, record))) return;
    const respond = (value: unknown) => route.fulfill({ json: value });
    if (path === "/api/bacnet/status")
      return respond({
        connected: true,
        config: {
          transport: "ip",
          local_address: "127.0.0.1:47899",
          instance: 4190001,
          router: "",
          dnet: null,
        },
        commands: [],
      });
    if (path === "/api/bacnet/hardware/status")
      return respond({
        jobs: [],
        reports: [
          {
            id: report.id,
            target,
            identity: report.identity,
            saved_at: "2026-01-02T03:04:10Z",
          },
        ],
        archives: [archive],
        captures: [{ id: "capture-fixture", bytes: 42, target }],
      });
    if (path === `/api/bacnet/hardware/reports/${report.id}`)
      return respond(report);
    if (path === `/api/bacnet/hardware/archives/${archive.id}`)
      return respond(archive);
    if (path === "/api/bacnet/hardware/survey")
      return respond({
        id: "job-fixture",
        status: "running",
        target,
        progress: { inputs: 1 },
      });
    if (path === "/api/bacnet/hardware/jobs/job-fixture")
      return respond(completed);
    if (path.startsWith("/api/bacnet/hardware/"))
      return route.fulfill({
        status: 500,
        json: { detail: "Unmocked hardware request: " + path },
      });
    if (["/api/macros/catalog", "/api/validate"].includes(path))
      return route.continue();
    if (request.method() !== "GET")
      return route.fulfill({
        status: 500,
        json: {
          detail: "Unexpected mutation outside offline hardware workflow",
        },
      });
    return route.continue();
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  const panel = page.getByRole("region", {
    name: "Controller hardware and input survey",
    exact: true,
  });
  await expect(panel).toBeVisible();
  return { panel, requests };
}
async function selectTarget(panel: ReturnType<Page["getByRole"]>) {
  await panel
    .getByLabel("Hardware controller address", { exact: true })
    .fill(target.address);
  await panel
    .getByLabel("Hardware Device object", { exact: true })
    .fill(target.device);
  await panel
    .getByLabel("Hardware router (optional)", { exact: true })
    .fill(target.router);
  await panel
    .getByLabel("Hardware destination network (optional)", { exact: true })
    .fill(String(target.dnet));
}
async function openSaved(panel: ReturnType<Page["getByRole"]>) {
  await panel
    .getByLabel("Saved hardware report", { exact: true })
    .selectOption(report.id);
  await panel
    .getByRole("button", { name: "Open saved hardware report", exact: true })
    .click();
  await expect(
    panel.getByRole("region", { name: "Hardware survey results", exact: true }),
  ).toBeVisible();
}

test("hardware survey keeps explicit routed source, binary-on-UI occupancy, errors, filters and CSV/JSON exports", async ({
  page,
}) => {
  const { panel, requests } = await setup(page, async (route, record) => {
    if (!record.path.endsWith("/export")) return false;
    const format = new URL(route.request().url()).searchParams.get("format");
    await route.fulfill({
      contentType: format === "csv" ? "text/csv" : "application/json",
      body:
        format === "csv"
          ? "object,name,sa_mac,slot\nbinary-input-2,Fixture compressor alarm,4,4\n"
          : JSON.stringify(report),
    });
    return true;
  });
  await selectTarget(panel);
  await panel
    .getByRole("button", { name: "Survey controller inputs", exact: true })
    .click();
  const results = panel.getByRole("region", {
    name: "Hardware survey results",
    exact: true,
  });
  await expect(results).toContainText("Authored controller fixture");
  expect(
    requests.find((request) => request.path.endsWith("/survey"))?.body,
  ).toEqual({
    ...target,
    transport: "bacnet-ip",
    max_objects: 512,
    max_inputs: 256,
    timeout_seconds: 120,
    property_timeout: 1.5,
  });
  await expect(results).toContainText("198.51.100.20 · DNET 3101");
  await expect(results).toContainText(
    "Binary object occupying a universal input",
  );
  await expect(results).toContainText("Authored property error retained");
  await expect(
    results.getByRole("region", { name: "Candidate spare input terminals" }),
  ).not.toContainText("IN4");
  await panel
    .getByLabel("Hardware input object type", { exact: true })
    .selectOption("binary-input,");
  await expect(
    results.getByRole("region", { name: "SA 4 input assignments" }),
  ).not.toContainText("Fixture temperature");
  await panel
    .getByLabel("Search hardware inputs", { exact: true })
    .fill("compressor");
  await expect(
    results.getByRole("region", { name: "SA 4 input assignments" }),
  ).toContainText("Fixture compressor alarm");
  await expect(
    results.getByRole("region", { name: "SA 7 input assignments" }),
  ).toHaveCount(0);
  for (const format of ["CSV", "JSON"]) {
    const downloading = page.waitForEvent("download");
    await panel
      .getByRole("button", { name: `Download hardware ${format}`, exact: true })
      .click();
    const download = await downloading;
    const contents = readFileSync((await download.path())!, "utf8");
    expect(download.suggestedFilename()).toBe(
      `hardware-inputs-${report.id}.${format.toLowerCase()}`,
    );
    expect(contents).toContain("Fixture compressor alarm");
  }
  expect(
    requests
      .filter(
        (request) =>
          request.method !== "GET" && request.path.startsWith("/api/bacnet/"),
      )
      .map((request) => request.path),
  ).toEqual(["/api/bacnet/hardware/survey"]);
});

test("hardware survey cancellation preserves partial evidence", async ({
  page,
}) => {
  const partial = {
    ...report,
    inventory: { ...report.inventory, complete: false, read: 2 },
    status: "cancelled",
  };
  const { panel, requests } = await setup(page, async (route, record) => {
    if (record.path === "/api/bacnet/hardware/jobs/job-fixture") {
      await route.fulfill({
        json: { id: "job-fixture", status: "running", progress: { read: 2 } },
      });
      return true;
    }
    if (record.path.endsWith("/cancel")) {
      await route.fulfill({
        json: { id: "job-fixture", status: "cancelled", report: partial },
      });
      return true;
    }
    return false;
  });
  await selectTarget(panel);
  await panel
    .getByRole("button", { name: "Survey controller inputs", exact: true })
    .click();
  await expect(
    panel.getByRole("button", { name: "Cancel hardware survey", exact: true }),
  ).toBeEnabled();
  await panel
    .getByRole("button", { name: "Cancel hardware survey", exact: true })
    .click();
  await expect(panel).toContainText("Survey cancelled");
  await expect(panel).toContainText(
    "Incomplete or unverified exposed object inventory",
  );
  expect(requests.some((request) => request.path.endsWith("/cancel"))).toBe(
    true,
  );
});

test("changing controller ignores late survey results and cancels its old source", async ({
  page,
}) => {
  let release: (() => void) | undefined;
  const arrived = new Promise<void>((resolve) => {
    release = resolve;
  });
  const { panel, requests } = await setup(page, async (route, record) => {
    if (record.path.endsWith("/survey")) {
      await arrived;
      await route.fulfill({ json: { ...completed, status: "running" } });
      return true;
    }
    if (record.path.endsWith("/cancel")) {
      await route.fulfill({ json: { id: "job-fixture", status: "cancelled" } });
      return true;
    }
    return false;
  });
  await selectTarget(panel);
  await panel
    .getByRole("button", { name: "Survey controller inputs", exact: true })
    .click();
  await expect
    .poll(() => requests.some((request) => request.path.endsWith("/survey")))
    .toBe(true);
  await panel
    .getByLabel("Hardware controller address", { exact: true })
    .fill("3101:10");
  release!();
  await expect
    .poll(() => requests.some((request) => request.path.endsWith("/cancel")))
    .toBe(true);
  await expect(
    panel.getByRole("region", { name: "Hardware survey results", exact: true }),
  ).toHaveCount(0);
  await expect(
    panel.getByLabel("Hardware controller address", { exact: true }),
  ).toHaveValue("3101:10");
});

test("a temporary progress failure can be retried without another controller survey", async ({
  page,
}) => {
  let failed = false;
  const { panel, requests } = await setup(page, async (route, record) => {
    if (record.path === "/api/bacnet/hardware/jobs/job-fixture" && !failed) {
      failed = true;
      await route.fulfill({
        status: 503,
        json: { detail: "Authored temporary progress outage" },
      });
      return true;
    }
    return false;
  });
  await selectTarget(panel);
  await panel
    .getByRole("button", { name: "Survey controller inputs", exact: true })
    .click();
  await expect(panel.getByRole("alert")).toContainText(
    "Authored temporary progress outage",
  );
  await panel
    .getByRole("button", { name: "Refresh hardware job progress", exact: true })
    .click();
  await expect(
    panel.getByRole("region", { name: "Hardware survey results", exact: true }),
  ).toContainText("Authored controller fixture");
  expect(
    requests.filter((request) => request.path.endsWith("/survey")),
  ).toHaveLength(1);
});

test("saved reports, local native imports, saved captures, correlation and explicit archive reads work without controller writes", async ({
  page,
}) => {
  const importedReport = {
    ...report,
    imported: true,
    started_at: "2026-01-02T03:04:05Z",
    finished_at: "2026-01-02T03:04:08Z",
  };
  const { panel, requests } = await setup(page, async (route, record) => {
    if (record.path.endsWith("/import-report")) {
      await route.fulfill({ json: importedReport });
      return true;
    }
    if (
      record.path.endsWith("/archive") ||
      record.path.endsWith("/archive/capture")
    ) {
      await route.fulfill({ json: archive });
      return true;
    }
    if (record.path.endsWith("/enrich")) {
      await route.fulfill({ json: report });
      return true;
    }
    if (record.path.endsWith("/read-archive")) {
      await route.fulfill({
        json: {
          ...completed,
          kind: "read-archive",
          archive_id: archive.id,
          archive,
        },
      });
      return true;
    }
    return false;
  });
  await openSaved(panel);
  await expect(
    panel
      .getByLabel("Saved hardware report", { exact: true })
      .locator(`option[value="${report.id}"]`),
  ).toContainText(
    "Authored controller fixture · 3101:9 / device,319009 via 198.51.100.20 · DNET 3101 · 2026-01-02T03:04:10Z",
  );
  await expect(panel).toContainText("Configured modules and capacity");
  await panel
    .getByLabel("Import hardware survey JSON", { exact: true })
    .setInputFiles({
      name: "authored-survey.json",
      mimeType: "application/json",
      buffer: Buffer.from(JSON.stringify(importedReport)),
    });
  await expect(panel).toContainText("No network reads were started");
  await expect(
    panel.getByLabel("Hardware report provenance", { exact: true }),
  ).toContainText("Imported report — user-supplied historical evidence");
  await expect(
    panel.getByLabel("Hardware survey capture time", { exact: true }),
  ).toContainText("2026-01-02T03:04:08Z");
  await panel
    .getByLabel("Import native hardware archive", { exact: true })
    .setInputFiles({
      name: "authored-fixture.moi",
      mimeType: "application/octet-stream",
      buffer: Buffer.from("authored placeholder; parser tested separately"),
    });
  await expect(panel).toContainText("Physical module labels remain unverified");
  await panel
    .getByLabel("Saved BACnet file capture", { exact: true })
    .selectOption("capture-fixture");
  await panel
    .getByRole("button", {
      name: "Identify modules from saved capture",
      exact: true,
    })
    .click();
  await expect(panel).toContainText(
    "An opaque capture is not assumed to be a native application",
  );
  await panel
    .getByRole("button", {
      name: "Correlate archive with input survey",
      exact: true,
    })
    .click();
  await expect(panel).toContainText("Correlated archive hardware");
  await panel
    .getByRole("button", { name: "Read controller archive", exact: true })
    .click();
  await expect(panel).toContainText("Controller archive read completed");
  expect(
    requests.find((request) => request.path.endsWith("/read-archive"))?.body,
  ).toEqual({ report_id: report.id });
  expect(
    requests
      .filter(
        (request) =>
          request.method !== "GET" && request.path.startsWith("/api/bacnet/"),
      )
      .every((request) => request.path.startsWith("/api/bacnet/hardware/")),
  ).toBe(true);
});

test("relocation stays a review, blocks occupied destinations, and conditionally plans voltage scaling", async ({
  page,
}) => {
  const { panel, requests } = await setup(page, async (route, record) => {
    if (record.path.endsWith("/relocation")) {
      await route.fulfill({
        json:
          record.body.destination_slot === 1
            ? {
                status: "blocked",
                can_apply: false,
                reasons: ["Destination is occupied"],
              }
            : {
                status: "review-required",
                can_apply: false,
                source: report.inputs[1],
                destination: { sa_mac: 7, slot: 16 },
                freed_input: { sa_mac: 4, slot: 4 },
                required_checks: [
                  "Physical dry-contact compatibility and rewiring",
                  "Native alarm references and polarity",
                ],
              },
      });
      return true;
    }
    if (record.path.endsWith("/sensor-plan")) {
      await route.fulfill({
        json: {
          status: "review-required",
          can_apply: false,
          channels: record.body.channels,
          relocation: record.body.relocation,
          examples: [0, 50, 100],
        },
      });
      return true;
    }
    return false;
  });
  await openSaved(panel);
  await panel
    .getByText("Review moving a binary signal off a universal input", {
      exact: true,
    })
    .click();
  await panel
    .getByLabel("Binary signal to relocate", { exact: true })
    .selectOption("binary-input,2");
  await expect(
    panel
      .getByLabel("Binary signal to relocate", { exact: true })
      .locator("option"),
  ).toHaveCount(2);
  await panel
    .getByLabel("Destination SA address (empty for base)", { exact: true })
    .fill("7");
  await panel
    .getByLabel("Destination binary input slot", { exact: true })
    .fill("1");
  await panel
    .getByRole("button", { name: "Review input relocation", exact: true })
    .click();
  const review = panel.getByRole("region", {
    name: "Input relocation review",
    exact: true,
  });
  await expect(review).toContainText("Destination is occupied");
  await expect(review).toContainText("no controller changes applied");
  await expect(panel.getByRole("button", { name: /^Apply/ })).toHaveCount(0);
  await panel
    .getByLabel("Destination binary input slot", { exact: true })
    .fill("16");
  await panel
    .getByRole("button", { name: "Review input relocation", exact: true })
    .click();
  await expect(review).toContainText("review-required");
  await panel
    .getByText("Plan voltage sensor input assignments and scaling", {
      exact: true,
    })
    .click();
  await panel
    .getByLabel("Outdoor-air temperature — SA address (empty for base)", {
      exact: true,
    })
    .fill("4");
  await panel
    .getByLabel("Outdoor-air temperature — Universal input slot", {
      exact: true,
    })
    .fill("2");
  await panel
    .getByLabel("Outdoor-air humidity — SA address (empty for base)", {
      exact: true,
    })
    .fill("4");
  await panel
    .getByLabel("Outdoor-air humidity — Universal input slot", { exact: true })
    .fill("4");
  await panel
    .getByLabel(
      "Include the reviewed binary relocation as a condition for freeing its universal input",
      { exact: true },
    )
    .check();
  await panel
    .getByRole("button", {
      name: "Review voltage sensor assignments",
      exact: true,
    })
    .click();
  await expect(
    panel.getByRole("region", {
      name: "Voltage sensor assignment review",
      exact: true,
    }),
  ).toContainText("native apply unavailable");
  const payload = requests.find((request) =>
    request.path.endsWith("/sensor-plan"),
  )?.body;
  expect(payload.relocation).toEqual({
    source_object: "binary-input,2",
    destination_sa_mac: 7,
    destination_slot: 16,
  });
  expect(payload.channels[1]).toEqual({
    name: "Outdoor-air humidity",
    sa_mac: 4,
    slot: 4,
    signal_low: 0,
    signal_high: 5,
    engineering_low: 0,
    engineering_high: 100,
    units: "%RH",
  });
  await expect(panel).toContainText(
    "Native JCI application compilation and download are unsupported here",
  );
});

test("saved jobs can resume after navigation, partial jobs stop polling, and local evidence can be exported or removed", async ({
  page,
}) => {
  let partial = false,
    removedJob = false,
    removedArchive = false,
    removedReport = false;
  const retainedJob = { id: "retained-job", status: "running", target };
  const { panel, requests } = await setup(page, async (route, record) => {
    if (record.path === "/api/bacnet/hardware/status") {
      await route.fulfill({
        json: {
          jobs: removedJob
            ? []
            : [{ ...retainedJob, status: partial ? "partial" : "running" }],
          reports: removedReport ? [] : [{ id: report.id, target }],
          archives: removedArchive
            ? []
            : [{ id: archive.id, source: archive.source }],
          captures: [],
        },
      });
      return true;
    }
    if (
      record.path === "/api/bacnet/hardware/jobs/retained-job" &&
      record.method === "GET"
    ) {
      partial = true;
      await route.fulfill({
        json: {
          ...retainedJob,
          status: "partial",
          report: {
            ...report,
            inventory: { ...report.inventory, complete: false, read: 2 },
          },
        },
      });
      return true;
    }
    if (record.path.endsWith("/export")) {
      const original =
        new URL(route.request().url()).searchParams.get("format") === "source";
      await route.fulfill({
        contentType: original ? "application/octet-stream" : "application/json",
        body: original
          ? "Exact authored source archive bytes"
          : JSON.stringify(
              record.path.includes("/jobs/")
                ? { ...retainedJob, status: "partial" }
                : archive,
            ),
      });
      return true;
    }
    if (record.method === "DELETE") {
      if (record.path.includes("/jobs/")) removedJob = true;
      if (record.path.includes("/archives/")) removedArchive = true;
      if (record.path.includes("/reports/")) removedReport = true;
      await route.fulfill({ json: { removed: true } });
      return true;
    }
    return false;
  });
  await panel
    .getByLabel("Configured hardware archive", { exact: true })
    .selectOption(archive.id);
  await panel
    .getByText("Archive provenance and configured hardware", { exact: true })
    .click();
  await expect(
    panel.getByRole("columnheader", {
      name: "Configured module model",
      exact: true,
    }),
  ).toBeVisible();
  await expect(panel).toContainText("FX-PCX3711-0");
  const downloading = page.waitForEvent("download");
  await panel
    .getByRole("button", {
      name: "Download original controller archive",
      exact: true,
    })
    .click();
  const source = await downloading;
  expect(source.suggestedFilename()).toBe("authored-fixture.moi");
  expect(readFileSync((await source.path())!, "utf8")).toBe(
    "Exact authored source archive bytes",
  );
  await panel
    .getByLabel("Saved hardware job", { exact: true })
    .selectOption(retainedJob.id);
  await panel
    .getByRole("button", { name: "View or resume hardware job", exact: true })
    .click();
  await expect(panel).toContainText("Survey partial");
  await expect(
    panel.getByRole("button", { name: "Cancel hardware survey", exact: true }),
  ).toBeDisabled();
  const jobDownload = page.waitForEvent("download");
  await panel
    .getByRole("button", { name: "Download hardware job JSON", exact: true })
    .click();
  expect(
    JSON.parse(readFileSync((await (await jobDownload).path())!, "utf8"))
      .status,
  ).toBe("partial");
  await panel
    .getByRole("button", { name: "Remove finished hardware job", exact: true })
    .click();
  await expect(
    panel.getByLabel("Saved hardware job", { exact: true }).locator("option"),
  ).toHaveCount(1);
  await panel
    .getByRole("button", { name: "Remove saved hardware report", exact: true })
    .click();
  await expect(
    panel.getByRole("region", { name: "Hardware survey results", exact: true }),
  ).toHaveCount(0);
  await panel
    .getByRole("button", { name: "Remove saved hardware archive", exact: true })
    .click();
  await expect(
    panel
      .getByLabel("Configured hardware archive", { exact: true })
      .locator("option"),
  ).toHaveCount(1);
  expect(
    requests
      .filter((request) => request.method === "DELETE")
      .map((request) => request.path),
  ).toEqual([
    "/api/bacnet/hardware/jobs/retained-job",
    `/api/bacnet/hardware/reports/${report.id}`,
    `/api/bacnet/hardware/archives/${archive.id}`,
  ]);
});
