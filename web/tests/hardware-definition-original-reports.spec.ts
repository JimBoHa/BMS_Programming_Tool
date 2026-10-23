import { expect, test, type Page, type Locator } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { createHash } from "node:crypto";
const root = fileURLToPath(new URL("../..", import.meta.url));
function fixture(replacement = false) {
  return execFileSync(
    path.join(root, ".venv/bin/python"),
    [
      "-c",
      `from tests.test_jci_hardware import definition;import sys;sys.stdout.buffer.write(definition(default=${replacement ? "1.0,revision=1,instance=4" : "-0.0"},alias=False))`,
    ],
    {
      cwd: root,
      env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
    },
  );
}
async function open(page: Page, replacement = false) {
  await page.goto("/");
  await page.getByRole("button", { name: "JCI hardware", exact: true }).click();
  const panel = page.getByRole("region", {
    name: "JCI hardware definitions",
    exact: true,
  });
  const original = fixture();
  await panel
    .getByLabel("Current hardware XML", { exact: true })
    .setInputFiles({
      name: "current-native.xml",
      mimeType: "application/xml",
      buffer: original,
    });
  await expect(
    panel.getByRole("region", {
      name: "Current hardware definition",
      exact: true,
    }),
  ).toContainText("ExampleSensor · revision 0");
  if (replacement) {
    await panel
      .getByLabel("Replacement hardware XML", { exact: true })
      .setInputFiles({
        name: "replacement-native.xml",
        mimeType: "application/xml",
        buffer: fixture(true),
      });
    await expect(
      panel.getByRole("region", {
        name: "Replacement hardware definition",
        exact: true,
      }),
    ).toContainText("ExampleSensor · revision 1");
  }
  await panel
    .getByLabel("Select hardware point temperature", { exact: true })
    .check();
  return { panel, original };
}
async function download(page: Page, panel: Locator, name: string) {
  const waiting = page.waitForEvent("download");
  await panel.getByRole("button", { name, exact: true }).click();
  return readFileSync((await (await waiting).path())!);
}
for (const kind of ["selection", "migration"] as const)
  test(`retains exact original ${kind} report bytes and native Float spellings`, async ({
    page,
  }, info) => {
    const { panel, original } = await open(page, kind === "migration");
    const sha = createHash("sha256").update(original).digest("hex");
    const url =
      kind === "selection"
        ? `**/api/jci/hardware/${sha}/selection`
        : "**/api/jci/hardware/migration";
    let upstream: Buffer | null = null;
    let calls = 0;
    await page.route(url, async (route) => {
      calls++;
      const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 });
      expect(response.status()).toBe(200);
      upstream = await response.body();
      expect(upstream.length).toBeGreaterThan(0);
      writeFileSync(info.outputPath("original-upstream.json"), upstream);
      await route.fulfill({ response, body: upstream });
    });
    await panel
      .getByRole("button", {
        name:
          kind === "selection"
            ? "Review point selection"
            : "Compare selected point migration",
        exact: true,
      })
      .click();
    await expect(
      panel.getByRole("region", {
        name:
          kind === "selection"
            ? "Hardware engineering selection"
            : "Native hardware migration report",
        exact: true,
      }),
    ).toBeVisible();
    expect(upstream!.toString()).toContain("-0.0");
    if (kind === "migration") expect(upstream!.toString()).toContain("1.0");
    const bytes = await download(
      page,
      panel,
      kind === "selection"
        ? "Export engineering plan JSON"
        : "Export migration report JSON",
    );
    writeFileSync(info.outputPath("downloaded-report.json"), bytes);
    expect(bytes.equals(upstream!)).toBe(true);
    expect(calls).toBe(1);
  });
test("held XML export cannot download after workspace unmount", async ({
  page,
}, info) => {
  const { panel, original } = await open(page);
  let enter!: () => void, release!: () => void;
  const entered = new Promise<void>((r) => (enter = r)),
    gate = new Promise<void>((r) => (release = r));
  await page.route("**/api/jci/hardware/*/export", async (route) => {
    const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 });
    const bytes = await response.body();
    expect(bytes.equals(original)).toBe(true);
    writeFileSync(info.outputPath("original-upstream.xml"), bytes);
    enter();
    await gate;
    await route.fulfill({ response, body: bytes });
  });
  await panel
    .getByRole("button", { name: "Export current XML original", exact: true })
    .click();
  await entered;
  await page.getByRole("button", { name: "Program", exact: true }).click();
  await expect(panel).toHaveCount(0);
  const late = page.waitForEvent("download", { timeout: 1000 }).then(
    () => true,
    () => false,
  );
  release();
  expect(await late).toBe(false);
});

async function review(
  panel: Locator,
  kind: "selection" | "migration" = "selection",
) {
  await panel
    .getByRole("button", {
      name:
        kind === "selection"
          ? "Review point selection"
          : "Compare selected point migration",
      exact: true,
    })
    .click();
  await expect(
    panel.getByRole("region", {
      name:
        kind === "selection"
          ? "Hardware engineering selection"
          : "Native hardware migration report",
      exact: true,
    }),
  ).toBeVisible();
}
const region = (panel: Locator, kind: "selection" | "migration") =>
  panel.getByRole("region", {
    name:
      kind === "selection"
        ? "Hardware engineering selection"
        : "Native hardware migration report",
    exact: true,
  });
for (const change of ["points", "units", "current", "replacement"] as const)
  test(`relevant ${change} change retires downloaded report authority`, async ({
    page,
  }) => {
    const { panel } = await open(page, true);
    await review(panel, "migration");
    if (change === "points")
      await panel
        .getByLabel("Select hardware point display", { exact: true })
        .check();
    else if (change === "units")
      await panel
        .getByLabel("Hardware measurement system", { exact: true })
        .selectOption("metric");
    else
      await panel
        .getByLabel(
          change === "current"
            ? "Current hardware XML"
            : "Replacement hardware XML",
          { exact: true },
        )
        .setInputFiles({
          name: "different-source.xml",
          mimeType: "application/xml",
          buffer: fixture(change === "current"),
        });
    await expect(region(panel, "migration")).toHaveCount(0);
    await expect(
      panel.getByRole("button", {
        name: "Export migration report JSON",
        exact: true,
      }),
    ).toHaveCount(0);
    if (change === "current")
      await panel
        .getByLabel("Select hardware point temperature", { exact: true })
        .check();
    await expect(
      panel.getByRole("button", {
        name: "Review point selection",
        exact: true,
      }),
    ).toBeEnabled();
    if (change === "units") {
      await review(panel);
      await expect(region(panel, "selection")).toContainText('"units": 62');
    }
  });
for (const slot of ["current", "replacement"] as const)
  test(`failed ${slot} source import retires original reports and that source`, async ({
    page,
  }) => {
    const { panel } = await open(page, true);
    await review(panel, "migration");
    await panel
      .getByLabel(
        slot === "current"
          ? "Current hardware XML"
          : "Replacement hardware XML",
        { exact: true },
      )
      .setInputFiles({
        name: "invalid.xml",
        mimeType: "application/xml",
        buffer: Buffer.from("not native XML"),
      });
    await expect(panel.getByRole("alert")).toBeVisible();
    await expect(region(panel, "migration")).toHaveCount(0);
    await expect(
      panel.getByRole("button", {
        name: `Export ${slot} XML original`,
        exact: true,
      }),
    ).toHaveCount(0);
    await panel
      .getByLabel(
        slot === "current"
          ? "Current hardware XML"
          : "Replacement hardware XML",
        { exact: true },
      )
      .setInputFiles({
        name: "reopened.xml",
        mimeType: "application/xml",
        buffer: fixture(slot === "replacement"),
      });
    await expect(
      panel.getByRole("button", {
        name: `Export ${slot} XML original`,
        exact: true,
      }),
    ).toBeEnabled();
  });
test("failed unit source validation clears both definitions and report exports", async ({
  page,
}) => {
  const { panel, original } = await open(page, true);
  await review(panel, "migration");
  const sha = createHash("sha256").update(original).digest("hex");
  await page.route(
    `**/api/jci/hardware/${sha}?system=metric`,
    async (route) => {
      const response = await route.fetch({
        url: route.request().url().replace("system=metric", "system=imperial"),
        maxRetries: 0,
        maxRedirects: 0,
      });
      await route.fulfill({ response, body: await response.body() });
    },
  );
  await panel
    .getByLabel("Hardware measurement system", { exact: true })
    .selectOption("metric");
  await expect(panel.getByRole("alert")).toContainText(
    "another source or measurement system",
  );
  for (const slot of ["current", "replacement"])
    await expect(
      panel.getByRole("button", {
        name: `Export ${slot} XML original`,
        exact: true,
      }),
    ).toHaveCount(0);
  await expect(region(panel, "migration")).toHaveCount(0);
  await expect(region(panel, "selection")).toHaveCount(0);
});
for (const kind of ["selection", "migration"] as const)
  test(`wrong source ${kind} report cannot authorize an original export`, async ({
    page,
  }) => {
    const { panel, original } = await open(page, kind === "migration");
    const sha = createHash("sha256").update(original).digest("hex");
    await page.route(
      kind === "selection"
        ? `**/api/jci/hardware/${sha}/selection`
        : "**/api/jci/hardware/migration",
      async (route) => {
        const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 });
        const value = await response.json();
        value[kind === "selection" ? "definition_sha256" : "old_sha256"] =
          "0".repeat(64);
        await route.fulfill({ response, json: value });
      },
    );
    await panel
      .getByRole("button", {
        name:
          kind === "selection"
            ? "Review point selection"
            : "Compare selected point migration",
        exact: true,
      })
      .click();
    await expect(panel.getByRole("alert")).toContainText("another source");
    await expect(region(panel, kind)).toHaveCount(0);
  });
for (const phase of [
  "selection",
  "migration",
  "units",
  "current-import",
  "replacement-import",
] as const)
  test(`held ${phase} response cannot restore state after unmount and reopen`, async ({
    page,
  }) => {
    const { panel, original } = await open(page, true);
    const sha = createHash("sha256").update(original).digest("hex");
    let enter!: () => void, release!: () => void, done!: () => void;
    const entered = new Promise<void>((r) => (enter = r)),
      gate = new Promise<void>((r) => (release = r)),
      completed = new Promise<void>((r) => (done = r));
    const url =
      phase === "selection"
        ? `**/api/jci/hardware/${sha}/selection`
        : phase === "migration"
          ? "**/api/jci/hardware/migration"
          : phase === "units"
            ? `**/api/jci/hardware/${sha}?system=metric`
            : "**/api/jci/hardware/open";
    await page.route(url, async (route) => {
      const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 });
      const bytes = await response.body();
      enter();
      await gate;
      await route.fulfill({ response, body: bytes });
      done();
    });
    if (phase === "units")
      await panel
        .getByLabel("Hardware measurement system", { exact: true })
        .selectOption("metric");
    else if (phase.endsWith("import"))
      await panel
        .getByLabel(
          phase === "current-import"
            ? "Current hardware XML"
            : "Replacement hardware XML",
          { exact: true },
        )
        .setInputFiles({
          name: "held-import.xml",
          mimeType: "application/xml",
          buffer: fixture(phase === "current-import"),
        });
    else
      await panel
        .getByRole("button", {
          name:
            phase === "selection"
              ? "Review point selection"
              : "Compare selected point migration",
          exact: true,
        })
        .click();
    await entered;
    await page.getByRole("button", { name: "Program", exact: true }).click();
    await expect(panel).toHaveCount(0);
    release();
    await completed;
    await page
      .getByRole("button", { name: "JCI hardware", exact: true })
      .click();
    await expect(panel).toBeVisible();
    await expect(region(panel, "selection")).toHaveCount(0);
    await expect(region(panel, "migration")).toHaveCount(0);
    await expect(
      panel.getByRole("button", {
        name: "Export current XML original",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      panel.getByRole("button", {
        name: "Export replacement XML original",
        exact: true,
      }),
    ).toHaveCount(0);
  });

test("altered XML response cannot export as the selected original source", async ({
  page,
}, info) => {
  const { panel, original } = await open(page);
  let calls = 0;
  await page.route("**/api/jci/hardware/*/export", async (route) => {
    calls++;
    const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 });
    const bytes = await response.body();
    expect(bytes.equals(original)).toBe(true);
    writeFileSync(info.outputPath("original-upstream.xml"), bytes);
    await route.fulfill({
      response,
      body: Buffer.concat([bytes, Buffer.from("\n")]),
    });
  });
  let downloads = 0;
  page.on("download", () => downloads++);
  await panel
    .getByRole("button", { name: "Export current XML original", exact: true })
    .click();
  await expect(panel.getByRole("alert")).toContainText(
    "does not match the selected source bytes",
  );
  expect(downloads).toBe(0);
  expect(calls).toBe(1);
});
