import { test, expect, type Page, type Locator } from "@playwright/test";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";

async function open(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await page
    .getByText("Network-number engineering plan", { exact: true })
    .click();
  const panel = page.getByRole("region", {
    name: "BACnet network-number planning",
    exact: true,
  });
  await expect(
    panel.getByLabel("Network plan name", { exact: true }),
  ).toBeVisible();
  return panel;
}
async function add(
  panel: Locator,
  label: string,
  network = "bus-a",
  number = "3001",
  endpoint = "router-" + label.replace(/\s+/g, "-"),
) {
  await panel.getByLabel("Attachment label", { exact: true }).fill(label);
  await panel
    .getByLabel("Internetwork/domain key", { exact: true })
    .fill("authored-domain");
  await panel
    .getByLabel("Physical-network key (blank = unknown)", { exact: true })
    .fill(network);
  await panel
    .getByLabel("Network number (blank = unknown)", { exact: true })
    .fill(number);
  await panel
    .getByLabel("Endpoint identity key (optional)", { exact: true })
    .fill(endpoint);
  await panel
    .getByLabel("Endpoint port key (optional)", { exact: true })
    .fill("mstp-1");
  await panel
    .getByRole("combobox", { name: "Declared network medium", exact: true })
    .selectOption("mstp");
  await panel
    .getByRole("button", { name: "Add attachment to plan", exact: true })
    .click();
}
async function calculate(panel: Locator, status: string) {
  await panel
    .getByRole("button", { name: "Review network numbers", exact: true })
    .click();
  const results = panel.getByRole("region", {
    name: "Network-number review results",
    exact: true,
  });
  await expect(
    results.getByRole("heading", {
      name: "Review status: " + status,
      exact: true,
    }),
  ).toBeVisible();
  return results;
}
async function imported(page: Page) {
  const data = await (
    await page.request.get("/api/network-number-plan/catalog")
  ).json();
  return {
    ...data.template,
    name: "Authored portable topology",
    declarations_complete: true,
    assignments: [
      {
        id: "authored-import",
        label: "Imported controller integration",
        domain_key: "separate-domain",
        physical_network_key: "network-a",
        endpoint_key: "engine-a",
        port_key: "remote-integration-3",
        network_number: 4101,
        medium: "mstp",
        role: "engine-remote-field-integration",
        policy: "generic",
        assignment_state: "existing",
        notes: "Authored browser fixture; no field data",
      },
    ],
  };
}
function sorted(value: any): any {
  return Array.isArray(value)
    ? value.map(sorted)
    : value !== null && typeof value === "object"
      ? Object.fromEntries(
          Object.keys(value)
            .sort()
            .map((key) => [key, sorted(value[key])]),
        )
      : value;
}
function sealed(value: any) {
  return createHash("sha256")
    .update(JSON.stringify(sorted(value)))
    .digest("hex");
}

test.beforeEach(async ({ page }) => {
  // Actual planner API responses; prohibit all field operations in this cohort.
  await page.route("**/api/bacnet/**", async (route) => {
    if (route.request().method() === "GET") await route.continue();
    else
      throw new Error(
        "Unexpected BACnet field operation: " + route.request().url(),
      );
  });
});

test("authors multi-router declarations, diagnoses a distinct bus, and reopens exact portable plan/review JSON", async ({
  page,
}) => {
  let panel = await open(page);
  await panel
    .getByLabel("Network plan name", { exact: true })
    .fill("Authored numbering review");
  await panel
    .getByLabel("I have included the intended inventory in these declarations")
    .check();
  await add(panel, "Router A");
  await add(panel, "Router B");
  await calculate(panel, "no-conflicts-in-declarations");
  await panel
    .getByRole("button", { name: "Edit attachment Router B", exact: true })
    .click();
  await panel
    .getByLabel("Physical-network key (blank = unknown)", { exact: true })
    .fill("different-bus");
  await expect(
    panel.getByRole("region", { name: "Network-number review results" }),
  ).toHaveCount(0);
  await expect(
    panel.getByRole("button", { name: "Review network numbers", exact: true }),
  ).toBeDisabled();
  await panel
    .getByRole("button", { name: "Apply attachment edits", exact: true })
    .click();
  const results = await calculate(panel, "conflicts");
  await expect(results).toContainText("number-on-distinct-networks");
  await expect(results).toContainText("Router A");
  await expect(results).toContainText("Router B");
  const planDownload = page.waitForEvent("download");
  await panel
    .getByRole("button", { name: "Export network plan JSON", exact: true })
    .click();
  const portable = JSON.parse(
    readFileSync((await (await planDownload).path())!, "utf8"),
  );
  expect(portable.assignments).toHaveLength(2);
  expect(portable.assignments[0].domain_key).toBe("authored-domain");
  expect(portable.profile_sha256).toMatch(/^[a-f0-9]{64}$/);
  await page.reload();
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await page
    .getByText("Network-number engineering plan", { exact: true })
    .click();
  panel = page.getByRole("region", {
    name: "BACnet network-number planning",
    exact: true,
  });
  await expect(
    panel.getByText("No attachments declared.", { exact: true }),
  ).toBeVisible();
  await panel.getByLabel("Network plan JSON", { exact: true }).setInputFiles({
    name: "portable-plan.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(portable)),
  });
  await expect(panel.getByRole("status")).toContainText(
    "Imported source-checked plan",
  );
  await calculate(panel, "conflicts");
  const reviewDownload = page.waitForEvent("download");
  await panel
    .getByRole("button", { name: "Export network review JSON", exact: true })
    .click();
  const report = JSON.parse(
    readFileSync((await (await reviewDownload).path())!, "utf8"),
  );
  expect(report.plan).toEqual(portable);
  expect(report.plan_sha256).toBe(sealed(portable));
  const hash = report.content_sha256;
  delete report.content_sha256;
  expect(hash).toBe(sealed(report));
  expect(report.physical_topology_verified).toBe(false);
  expect(report.controller_writes).toBe(false);
  expect(report.field_scans).toBe(false);
  expect(
    (await (await page.request.get("/api/bacnet/status")).json()).connected,
  ).toBe(false);
});

test("keeps unknowns and Release15 reservations distinct from generic BACnet numbering", async ({
  page,
}) => {
  const panel = await open(page);
  await panel
    .getByLabel("I have included the intended inventory in these declarations")
    .check();
  await add(panel, "Unknown attachment", "", "");
  let results = await calculate(panel, "incomplete");
  await expect(results).toContainText("unknown-network-number");
  await expect(results).toContainText("unknown-physical-network");
  await panel
    .getByRole("button", {
      name: "Edit attachment Unknown attachment",
      exact: true,
    })
    .click();
  await panel
    .getByLabel("Physical-network key (blank = unknown)", { exact: true })
    .fill("new-remote-ip");
  await panel
    .getByLabel("Network number (blank = unknown)", { exact: true })
    .fill("2000");
  await panel
    .getByRole("combobox", { name: "Declared network medium", exact: true })
    .selectOption("bacnet-ip");
  await panel
    .getByRole("combobox", { name: "Engineering policy", exact: true })
    .selectOption("jci-r15-remote-field");
  await panel
    .getByRole("combobox", { name: "Assignment context", exact: true })
    .selectOption("new");
  await panel
    .getByRole("button", { name: "Apply attachment edits", exact: true })
    .click();
  results = await calculate(panel, "conflicts");
  await expect(results).toContainText("jci-r15-new-reserved-number");
  await panel
    .getByRole("button", {
      name: "Edit attachment Unknown attachment",
      exact: true,
    })
    .click();
  await panel
    .getByRole("combobox", { name: "Engineering policy", exact: true })
    .selectOption("generic");
  await panel
    .getByRole("button", { name: "Apply attachment edits", exact: true })
    .click();
  await calculate(panel, "no-conflicts-in-declarations");
  await panel
    .getByRole("button", {
      name: "Edit attachment Unknown attachment",
      exact: true,
    })
    .click();
  await panel
    .getByLabel("Network number (blank = unknown)", { exact: true })
    .fill("65535");
  await panel
    .getByRole("button", { name: "Apply attachment edits", exact: true })
    .click();
  results = await calculate(panel, "conflicts");
  await expect(results).toContainText("not-a-physical-network-number");
  await panel
    .getByRole("button", {
      name: "Remove attachment Unknown attachment",
      exact: true,
    })
    .click();
  await calculate(panel, "incomplete");
});

test("rejects stale source imports without replacing the draft and invalidates review on plan edits", async ({
  page,
}) => {
  const panel = await open(page);
  const source = await imported(page);
  await panel.getByLabel("Network plan JSON", { exact: true }).setInputFiles({
    name: "authored.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(source)),
  });
  await expect(
    panel.getByLabel("Network plan name", { exact: true }),
  ).toHaveValue(source.name);
  await calculate(panel, "no-conflicts-in-declarations");
  const stale = structuredClone(source);
  stale.profile_sha256 = "0".repeat(64);
  await panel.getByLabel("Network plan JSON", { exact: true }).setInputFiles({
    name: "stale.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(stale)),
  });
  await expect(panel.getByRole("alert")).toContainText(
    "source profile changed",
  );
  await expect(
    panel.getByLabel("Network plan name", { exact: true }),
  ).toHaveValue(source.name);
  await expect(
    panel.getByRole("region", { name: "Network-number review results" }),
  ).toHaveCount(0);
  await calculate(panel, "no-conflicts-in-declarations");
  await panel
    .getByLabel("Network plan notes", { exact: true })
    .fill("New engineering context");
  await expect(
    panel.getByRole("region", { name: "Network-number review results" }),
  ).toHaveCount(0);
  await expect(
    panel.getByRole("button", {
      name: "Export network review JSON",
      exact: true,
    }),
  ).toBeDisabled();
});

async function holdReviews(page: Page) {
  let release!: () => void, entered!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  const seen = new Promise<void>((resolve) => {
    entered = resolve;
  });
  await page.route("**/api/network-number-plan/review", async (route) => {
    entered();
    await held;
    await route.continue();
  });
  return { release, seen };
}

test("late review cannot replace edited/imported declarations or create a stale result", async ({
  page,
}) => {
  const panel = await open(page);
  await add(panel, "Authored row");
  let held = await holdReviews(page);
  await panel
    .getByRole("button", { name: "Review network numbers", exact: true })
    .click();
  await held.seen;
  await panel
    .getByLabel("Network plan name", { exact: true })
    .fill("Edited during review");
  held.release();
  await page.unroute("**/api/network-number-plan/review");
  await expect(
    panel.getByRole("button", { name: "Review network numbers", exact: true }),
  ).toBeEnabled();
  await expect(
    panel.getByRole("region", { name: "Network-number review results" }),
  ).toHaveCount(0);
  held = await holdReviews(page);
  await panel
    .getByRole("button", { name: "Review network numbers", exact: true })
    .click();
  await held.seen;
  const source = await imported(page);
  page.once("dialog", (dialog) => dialog.accept());
  await panel.getByLabel("Network plan JSON", { exact: true }).setInputFiles({
    name: "replacement.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(source)),
  });
  await expect(
    panel.getByLabel("Network plan name", { exact: true }),
  ).toHaveValue(source.name);
  held.release();
  await page.unroute("**/api/network-number-plan/review");
  await expect(
    panel.getByRole("region", { name: "Network-number review results" }),
  ).toHaveCount(0);
  await calculate(panel, "no-conflicts-in-declarations");
});

test("closing or unmounting the planner suppresses delayed review downloads", async ({
  page,
}) => {
  let panel = await open(page);
  await panel
    .getByLabel("I have included the intended inventory in these declarations")
    .check();
  await add(panel, "Authored row");
  await calculate(panel, "no-conflicts-in-declarations");
  const downloads: string[] = [];
  page.on("download", (file) => downloads.push(file.suggestedFilename()));
  let held = await holdReviews(page);
  await panel
    .getByRole("button", { name: "Export network review JSON", exact: true })
    .click();
  await held.seen;
  await page
    .getByText("Network-number engineering plan", { exact: true })
    .click();
  held.release();
  await page.unroute("**/api/network-number-plan/review");
  const hidden = page.getByRole("region", {
    name: "BACnet network-number planning",
    includeHidden: true,
  });
  await expect(
    hidden.getByRole("button", {
      name: "Review network numbers",
      exact: true,
      includeHidden: true,
    }),
  ).toBeEnabled();
  expect(downloads).toEqual([]);
  await page
    .getByText("Network-number engineering plan", { exact: true })
    .click();
  await calculate(panel, "no-conflicts-in-declarations");
  held = await holdReviews(page);
  await panel
    .getByRole("button", { name: "Export network review JSON", exact: true })
    .click();
  await held.seen;
  await page.getByRole("button", { name: "Program", exact: true }).click();
  held.release();
  await page.unroute("**/api/network-number-plan/review");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await page
    .getByText("Network-number engineering plan", { exact: true })
    .click();
  panel = page.getByRole("region", {
    name: "BACnet network-number planning",
    exact: true,
  });
  await expect(
    panel.getByText("No attachments declared.", { exact: true }),
  ).toBeVisible();
  await expect(
    panel.getByRole("region", { name: "Network-number review results" }),
  ).toHaveCount(0);
  expect(downloads).toEqual([]);
});
