import { test, expect, type Page, type Locator } from "@playwright/test";
import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import path from "node:path";
const root = path.resolve("..");
async function open(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await page
    .getByText("JCI bus address and topology plan", { exact: true })
    .click();
  const panel = page.getByRole("region", {
    name: "JCI bus preflight",
    exact: true,
  });
  await expect(
    panel.getByLabel("Bus plan name", { exact: true }),
  ).toBeVisible();
  return panel;
}
async function bus(panel: Locator) {
  await panel
    .getByLabel("Physical bus name", { exact: true })
    .fill("Authored SA");
  await panel
    .getByLabel("Physical bus key", { exact: true })
    .fill("authored-sa");
  await panel
    .getByLabel("Bus manual profile", { exact: true })
    .selectOption("fx-2024");
  await panel
    .getByLabel("Physical bus type", { exact: true })
    .selectOption("sa");
  await panel
    .getByLabel("Segment keys (comma separated)", { exact: true })
    .fill("s1");
  await panel
    .getByLabel("All intended devices and cables for this bus are declared")
    .check();
  await panel
    .getByRole("button", { name: "Add physical bus to plan", exact: true })
    .click();
  await expect(panel.getByRole("status")).toContainText(
    "Applied local declaration",
  );
}
async function device(
  panel: Locator,
  label: string,
  role: string,
  mac: string,
  model: string,
  eol: string,
) {
  await panel
    .getByLabel("Device connection label", { exact: true })
    .fill(label);
  await panel.getByLabel("Exact device model", { exact: true }).fill(model);
  await panel
    .getByLabel("Declared device generation", { exact: true })
    .selectOption("legacy-dip128");
  await panel
    .getByLabel("Device connection role", { exact: true })
    .selectOption(role);
  await panel
    .getByLabel("Device MAC (blank = unknown)", { exact: true })
    .fill(mac);
  await panel
    .getByLabel("Switch128 interpretation", { exact: true })
    .selectOption("off");
  await panel
    .getByLabel("Planned device EOL", { exact: true })
    .selectOption(eol);
  await panel
    .getByRole("button", { name: "Add device connection to plan", exact: true })
    .click();
  await expect(panel.getByRole("status")).toContainText(
    "Applied local declaration",
  );
}
async function fixture(page: Page) {
  const data = await (
    await page.request.get("/api/bus-preflight/catalog")
  ).json();
  const d = (
    id: string,
    role: string,
    mac: number,
    model: string,
    generation: string | null,
    switch128: string,
    eol = "off",
  ) => ({
    id,
    label: id,
    bus_id: "authored-sa",
    role,
    mac,
    model,
    generation,
    switch128,
    eol,
    segment: "s1",
    mode: "wired",
    notes: "Authored browser fixture",
  });
  const l = (
    a: string,
    b: string,
    kind = "terminal",
    straight_through: boolean | null = null,
  ) => ({
    id: a + "-" + b,
    a,
    b,
    kind,
    length_m: 2.0,
    straight_through,
    notes: "Authored planned cable",
  });
  return {
    ...data.template,
    name: "Authored service-port plan",
    buses: [
      {
        id: "authored-sa",
        name: "Authored SA",
        profile: "fx-2024",
        kind: "sa",
        segments: ["s1"],
        inventory_complete: true,
        nce_integral: "absent",
        zfr1810_coordinators: "absent",
        notes: "Authored bus",
      },
    ],
    devices: [
      d(
        "Host",
        "sa-host",
        0,
        "FX-PCV1630-0",
        "legacy-dip128",
        "not-applicable",
        "fixed-on",
      ),
      d(
        "Sensor",
        "network-sensor",
        199,
        "NSB8BTN240-0",
        "refreshed-2025-12-08",
        "not-applicable",
      ),
      d("IOM", "iom", 4, "FX-PCX3721-0", "legacy-dip128", "off"),
      d("Tool", "converter", 2, "TL-CWCVT-0", null, "not-applicable"),
    ],
    links: [
      l("Host", "Sensor"),
      l("Sensor", "IOM"),
      l("Sensor", "Tool", "sensor-service", true),
    ],
  };
}
async function importPlan(panel: Locator, value: any) {
  await panel.getByLabel("Bus plan JSON", { exact: true }).setInputFiles({
    name: "authored-bus-plan.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(value)),
  });
  await expect(panel.getByRole("status")).toContainText(
    "Imported exact source-checked",
  );
}
async function review(panel: Locator, status = "incomplete") {
  await panel
    .getByRole("button", { name: "Review bus plan", exact: true })
    .click();
  const report = panel.getByRole("region", {
    name: "JCI bus review results",
    exact: true,
  });
  await expect(
    report.getByRole("heading", {
      name: "Bus review status: " + status,
      exact: true,
    }),
  ).toBeVisible();
  return report;
}
test.beforeEach(async ({ page }) => {
  await page.route("**/api/bacnet/**", async (route) => {
    if (route.request().method() === "GET") await route.continue();
    else throw new Error("Unexpected field operation " + route.request().url());
  });
});

test("authors a real local bus plan, reopens portable JSON and exports independently checked review seals", async ({
  page,
}) => {
  let panel = await open(page);
  await bus(panel);
  await device(panel, "Host", "sa-host", "0", "FX-PCV1630-0", "fixed-on");
  await device(panel, "IOM", "iom", "4", "FX-PCX3721-0", "off");
  await panel
    .getByLabel("Cable endpoint A", { exact: true })
    .selectOption({ label: "Host" });
  await panel
    .getByLabel("Cable endpoint B", { exact: true })
    .selectOption({ label: "IOM" });
  await panel
    .getByLabel("Cable or bridge kind", { exact: true })
    .selectOption("terminal");
  await panel
    .getByLabel("Planned cable length metres", { exact: true })
    .fill("2");
  await panel
    .getByRole("button", { name: "Add planned cable to plan", exact: true })
    .click();
  await expect(panel.getByRole("status")).toContainText(
    "Applied local declaration",
  );
  let report = await review(panel);
  await expect(report).toContainText(
    "Address checks: no-conflicts-in-declarations",
  );
  await expect(report).toContainText(
    "Graph checks: no-conflicts-in-declarations",
  );
  await expect(report).toContainText("capacity-cable-power-unverified");
  const download = page.waitForEvent("download");
  await panel
    .getByRole("button", { name: "Export bus plan JSON", exact: true })
    .click();
  const portable = JSON.parse(
    readFileSync((await (await download).path())!, "utf8"),
  );
  expect(portable.devices).toHaveLength(2);
  expect(portable.links).toHaveLength(1);
  await page.reload();
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await page
    .getByText("JCI bus address and topology plan", { exact: true })
    .click();
  panel = page.getByRole("region", { name: "JCI bus preflight", exact: true });
  await expect(
    panel.getByRole("heading", { name: "Physical buses (0/32)", exact: true }),
  ).toBeVisible();
  await importPlan(panel, portable);
  report = await review(panel);
  const capture = page.waitForEvent("download");
  await panel
    .getByRole("button", { name: "Export bus review JSON", exact: true })
    .click();
  const file = (await (await capture).path())!;
  const checks = JSON.parse(
    execFileSync(
      path.join(root, ".venv/bin/python"),
      [
        "-c",
        "import json,sys,hashlib; d=json.load(open(sys.argv[1])); h=lambda x:hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest(); print(json.dumps({'plan':h(d['plan'])==d['plan_sha256'],'review':h({k:v for k,v in d.items() if k!='content_sha256'})==d['content_sha256']}))",
        file,
      ],
      { encoding: "utf8" },
    ),
  );
  expect(checks).toEqual({ plan: true, review: true });
  const saved = JSON.parse(readFileSync(file, "utf8"));
  expect(saved.field_operations).toBe(false);
  expect(saved.physical_wiring_verified).toBe(false);
  expect(
    (await (await page.request.get("/api/bacnet/status")).json()).connected,
  ).toBe(false);
});

test("recognizes exact sensor service leaves and rejects ordinary branches and SA segmentation", async ({
  page,
}) => {
  const panel = await open(page);
  await importPlan(panel, await fixture(page));
  let report = await review(panel);
  await expect(report).toContainText("documented-sensor-service-leaf");
  await expect(report).not.toContainText("trunk-branch");
  await panel
    .getByRole("button", { name: "Edit cable Sensor to Tool", exact: true })
    .click();
  await panel
    .getByLabel("Cable or bridge kind", { exact: true })
    .selectOption("terminal");
  await expect(
    panel.getByRole("region", { name: "JCI bus review results" }),
  ).toHaveCount(0);
  await panel
    .getByRole("button", { name: "Apply cable edits", exact: true })
    .click();
  await expect(panel.getByRole("status")).toContainText(
    "Applied local declaration",
  );
  report = await review(panel, "conflicts");
  await expect(report).toContainText("trunk-branch");
  await panel
    .getByRole("button", { name: "Edit bus Authored SA", exact: true })
    .click();
  await expect(
    panel.getByLabel("Physical bus key", { exact: true }),
  ).toBeDisabled();
  await panel
    .getByLabel("Segment keys (comma separated)", { exact: true })
    .fill("s1,s2");
  await panel
    .getByRole("button", { name: "Apply bus edits", exact: true })
    .click();
  await expect(panel.getByRole("status")).toContainText(
    "Applied local declaration",
  );
  report = await review(panel, "conflicts");
  await expect(report).toContainText("sa-single-segment-no-repeaters");
});

test("edits reserved address and legacy mode facts without adding switch128 to the MAC", async ({
  page,
}) => {
  const panel = await open(page);
  await importPlan(panel, await fixture(page));
  await panel
    .getByRole("button", { name: "Edit device IOM", exact: true })
    .click();
  await panel
    .getByLabel("Device MAC (blank = unknown)", { exact: true })
    .fill("2");
  await panel
    .getByRole("button", { name: "Apply device edits", exact: true })
    .click();
  await expect(panel.getByRole("status")).toContainText(
    "Applied local declaration",
  );
  let report = await review(panel, "conflicts");
  await expect(report).toContainText("duplicate-mac-on-bus");
  await expect(report).toContainText("manager-address-range");
  await panel
    .getByRole("button", { name: "Edit device IOM", exact: true })
    .click();
  await panel
    .getByLabel("Device MAC (blank = unknown)", { exact: true })
    .fill("21");
  await panel
    .getByLabel("Switch128 interpretation", { exact: true })
    .selectOption("on");
  await panel
    .getByRole("button", { name: "Apply device edits", exact: true })
    .click();
  await expect(panel.getByRole("status")).toContainText(
    "Applied local declaration",
  );
  report = await review(panel, "conflicts");
  await expect(report).toContainText("wireless-switch-mode-conflict");
  const pending = page.waitForEvent("download");
  await panel
    .getByRole("button", { name: "Export bus plan JSON", exact: true })
    .click();
  const value = JSON.parse(
    readFileSync((await (await pending).path())!, "utf8"),
  );
  expect(value.devices.find((d: any) => d.id === "IOM").mac).toBe(21);
});

async function hold(page: Page, routeName = "review") {
  let release!: () => void, entered!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  const seen = new Promise<void>((resolve) => {
    entered = resolve;
  });
  await page.route("**/api/bus-preflight/" + routeName, async (route) => {
    entered();
    await held;
    await route.continue();
  });
  return {
    release,
    seen,
    async cleanup() {
      release();
      await page.unroute("**/api/bus-preflight/" + routeName);
    },
  };
}

test("stale source files and late edited review responses cannot replace current declarations", async ({
  page,
}) => {
  const panel = await open(page);
  const source = await fixture(page);
  await importPlan(panel, source);
  await review(panel);
  const stale = structuredClone(source);
  stale.catalog_sha256 = "0".repeat(64);
  await panel.getByLabel("Bus plan JSON", { exact: true }).setInputFiles({
    name: "stale.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(stale)),
  });
  await expect(panel.getByRole("alert")).toContainText(
    "source catalog changed",
  );
  await expect(panel.getByLabel("Bus plan name", { exact: true })).toHaveValue(
    source.name,
  );
  const held = await hold(page);
  await panel
    .getByRole("button", { name: "Review bus plan", exact: true })
    .click();
  await held.seen;
  await panel
    .getByLabel("Bus plan name", { exact: true })
    .fill("Newer engineering draft");
  await held.cleanup();
  await expect(
    panel.getByRole("button", { name: "Review bus plan", exact: true }),
  ).toBeEnabled();
  await expect(
    panel.getByRole("region", { name: "JCI bus review results" }),
  ).toHaveCount(0);
  await expect(
    panel.getByRole("button", { name: "Export bus review JSON", exact: true }),
  ).toBeDisabled();
});

test("late apply validation preserves newer editor input and unapplied parallel forms", async ({
  page,
}) => {
  const panel = await open(page);
  await bus(panel);
  await panel
    .getByLabel("Physical bus name", { exact: true })
    .fill("Second authored bus");
  await panel
    .getByLabel("Physical bus key", { exact: true })
    .fill("second-bus");
  await panel
    .getByLabel("Device connection label", { exact: true })
    .fill("Preserved device draft");
  await panel
    .getByRole("button", { name: "Add physical bus to plan", exact: true })
    .click();
  await expect(panel.getByRole("status")).toContainText(
    "Applied local declaration",
  );
  await expect(
    panel.getByLabel("Device connection label", { exact: true }),
  ).toHaveValue("Preserved device draft");
  await expect(
    panel.getByRole("button", { name: "Review bus plan", exact: true }),
  ).toBeDisabled();
  await panel
    .getByRole("button", { name: "Clear all editors", exact: true })
    .click();
  const source = await fixture(page);
  page.once("dialog", (dialog) => dialog.accept());
  await importPlan(panel, source);
  await panel
    .getByRole("button", { name: "Edit device IOM", exact: true })
    .click();
  await panel
    .getByLabel("Device MAC (blank = unknown)", { exact: true })
    .fill("5");
  const held = await hold(page, "validate");
  await panel
    .getByRole("button", { name: "Apply device edits", exact: true })
    .click();
  await held.seen;
  await panel
    .getByLabel("Device MAC (blank = unknown)", { exact: true })
    .fill("6");
  await held.cleanup();
  await expect(
    panel.getByRole("button", { name: "Apply device edits", exact: true }),
  ).toBeEnabled();
  await expect(
    panel.getByLabel("Device MAC (blank = unknown)", { exact: true }),
  ).toHaveValue("6");
  await expect(
    panel.getByRole("button", { name: "Review bus plan", exact: true }),
  ).toBeDisabled();
  await panel
    .getByRole("button", { name: "Apply device edits", exact: true })
    .click();
  await expect(panel.getByRole("status")).toContainText(
    "Applied local declaration",
  );
  await review(panel);
});

test("closed or unmounted panels suppress delayed review exports", async ({
  page,
}) => {
  let panel = await open(page);
  await importPlan(panel, await fixture(page));
  await review(panel);
  const downloads: string[] = [];
  page.on("download", (file) => downloads.push(file.suggestedFilename()));
  let held = await hold(page, "export-review");
  await panel
    .getByRole("button", { name: "Export bus review JSON", exact: true })
    .click();
  await held.seen;
  await page
    .getByText("JCI bus address and topology plan", { exact: true })
    .click();
  await held.cleanup();
  const hidden = page.getByRole("region", {
    name: "JCI bus preflight",
    includeHidden: true,
  });
  await expect(
    hidden.getByRole("button", {
      name: "Review bus plan",
      exact: true,
      includeHidden: true,
    }),
  ).toBeEnabled();
  expect(downloads).toEqual([]);
  await page
    .getByText("JCI bus address and topology plan", { exact: true })
    .click();
  await review(panel);
  held = await hold(page, "export-review");
  await panel
    .getByRole("button", { name: "Export bus review JSON", exact: true })
    .click();
  await held.seen;
  await page.getByRole("button", { name: "Program", exact: true }).click();
  await held.cleanup();
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await page
    .getByText("JCI bus address and topology plan", { exact: true })
    .click();
  panel = page.getByRole("region", { name: "JCI bus preflight", exact: true });
  await expect(
    panel.getByRole("heading", { name: "Physical buses (0/32)", exact: true }),
  ).toBeVisible();
  expect(downloads).toEqual([]);
});
