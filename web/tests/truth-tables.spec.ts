import { test, expect, type Page } from "@playwright/test";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

function stable(value: any): string {
  if (Array.isArray(value)) return "[" + value.map(stable).join(",") + "]";
  if (value && typeof value === "object")
    return (
      "{" +
      Object.keys(value)
        .sort()
        .map((key) => JSON.stringify(key) + ":" + stable(value[key]))
        .join(",") +
      "}"
    );
  return JSON.stringify(value);
}
const sha = (value: Buffer | string) =>
  createHash("sha256").update(value).digest("hex");
async function releaseReply(page: Page, suffix: string, release: () => void) {
  const response = page.waitForResponse((value) =>
    value.url().endsWith(suffix),
  );
  release();
  await (await response).finished();
  await page.evaluate(
    () =>
      new Promise<void>((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
      ),
  );
}
async function open(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Truth tables", exact: true }).click();
  await expect(
    page.getByRole("textbox", { name: "Truth-table name", exact: true }),
  ).toHaveValue("Mode and override example");
}
async function review(page: Page) {
  await page
    .getByRole("button", { name: "Review all combinations", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Truth-table review", exact: true }),
  ).toBeVisible();
}
async function exported(page: Page, kind: "table" | "review", path: string) {
  const response = page.waitForResponse((response) =>
    response.url().endsWith("/truth-tables/export/" + kind),
  );
  const pending = page.waitForEvent("download");
  await page
    .getByRole("button", {
      name: kind === "table" ? "Export table" : "Export full review",
      exact: true,
    })
    .click();
  const download = await pending;
  await download.saveAs(path);
  const raw = readFileSync(path),
    document = JSON.parse(raw.toString());
  const { content_sha256, ...content } = document;
  expect(content_sha256).toBe(sha(stable(content)));
  expect((await response).headers()["x-file-sha256"]).toBe(sha(raw));
  expect(document.table_sha256).toBe(sha(stable(document.table)));
  return { raw, document };
}

test("actual finite review downloads sealed source/full coverage and round-trips authoring", async ({
  page,
}, info) => {
  const fieldWrites: string[] = [],
    projectWrites: string[] = [];
  page.on("request", (request) => {
    if (request.url().endsWith("/api/projects") && request.method() === "POST")
      projectWrites.push(request.url());
    if (request.url().includes("/api/bacnet/") && request.method() !== "GET")
      fieldWrites.push(request.url());
  });
  await open(page);
  await expect(
    page.getByRole("button", { name: "Save revision", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("textbox", { name: "Program name", exact: true }),
  ).toBeDisabled();
  await page.keyboard.press("ControlOrMeta+s");
  await expect(
    page.getByText("Use Export table in the truth-table workspace.", {
      exact: true,
    }),
  ).toBeVisible();
  await review(page);
  await expect(
    page.getByRole("heading", { name: "Coverage: incomplete" }),
  ).toBeVisible();
  await page
    .getByLabel("Coverage filter", { exact: true })
    .selectOption("uncovered");
  await expect(
    page
      .getByRole("table", { name: "Coverage combinations" })
      .locator("tbody tr"),
  ).toHaveCount(1);
  await expect(
    page.getByRole("table", { name: "Coverage combinations" }),
  ).toContainText("Output cannot be determined");
  const path = info.outputPath("table.json");
  const source = await exported(page, "table", path);
  const report = await exported(page, "review", info.outputPath("review.json"));
  expect(report.document.coverage).toHaveLength(4);
  expect(report.document.counts.uncovered).toBe(1);
  expect(source.document.source_profile.sources[0].sha256).toBe(
    "68935362c85cb1879dc033cc701115e8ea7c4ecb26748f21a9ceaf0454f82903",
  );
  await page
    .getByLabel("Truth-table name", { exact: true })
    .fill("Changed source");
  await expect(
    page.getByRole("region", { name: "Truth-table review", exact: true }),
  ).toHaveCount(0);
  await page
    .getByLabel("Import truth table", { exact: true })
    .setInputFiles(path);
  await expect(
    page.getByLabel("Truth-table name", { exact: true }),
  ).toHaveValue("Mode and override example");
  await expect(
    page.getByLabel("Imported truth-table file identity"),
  ).toContainText(sha(source.raw));
  await review(page);
  await page.getByLabel("Selected mode", { exact: true }).selectOption("on");
  await page
    .getByRole("button", { name: "Evaluate selected combination", exact: true })
    .click();
  await expect(page.getByLabel("Selected combination result")).toContainText(
    "True (True)",
  );
  await page.getByLabel("Selected mode", { exact: true }).selectOption("off");
  await page
    .getByLabel("Selected override", { exact: true })
    .selectOption("true");
  await page
    .getByRole("button", { name: "Evaluate selected combination", exact: true })
    .click();
  await expect(page.getByLabel("Selected combination result")).toContainText(
    "Output cannot be determined",
  );
  await page.getByLabel("Enable constant fallback", { exact: true }).check();
  await page
    .getByLabel("Fallback rationale", { exact: true })
    .fill("Explicit off choice for the unlisted combination.");
  await review(page);
  await expect(
    page.getByRole("heading", { name: "Coverage: complete" }),
  ).toBeVisible();
  await page
    .getByLabel("Selected override", { exact: true })
    .selectOption("true");
  await page
    .getByRole("button", { name: "Evaluate selected combination", exact: true })
    .click();
  await expect(page.getByLabel("Selected combination result")).toContainText(
    "Explicit off choice",
  );
  expect(fieldWrites).toEqual([]);
  expect(projectWrites).toEqual([]);
});

test("same-output copies are ambiguous and explicit row priority retains shadowed identities", async ({
  page,
}) => {
  await open(page);
  await page
    .getByRole("button", { name: "Copy row enabled", exact: true })
    .click();
  await review(page);
  await expect(
    page.getByRole("heading", { name: "Coverage: ambiguous" }),
  ).toBeVisible();
  const copied = (await page
    .getByRole("textbox", { name: /^Row name row-/ })
    .getAttribute("aria-label"))!.slice("Row name ".length);
  await page
    .getByLabel(`Result ${copied}`, { exact: true })
    .selectOption("false");
  await page
    .getByLabel("Overlap policy", { exact: true })
    .selectOption("first-match");
  await page
    .getByRole("button", { name: `Move row ${copied} up`, exact: true })
    .click();
  await page
    .getByRole("button", { name: `Move row ${copied} up`, exact: true })
    .click();
  await review(page);
  await page.getByLabel("Selected mode", { exact: true }).selectOption("on");
  await page
    .getByRole("button", { name: "Evaluate selected combination", exact: true })
    .click();
  await expect(page.getByLabel("Selected combination result")).toContainText(
    "False (False)",
  );
  await expect(page.getByLabel("Selected combination result")).toContainText(
    "Shadowed rows: Mode enabled [enabled]",
  );
  await page
    .getByText("Row usage and unreachable-row diagnostics", { exact: true })
    .click();
  await expect(
    page.getByRole("table", { name: "Truth-table row usage" }),
  ).toContainText("fully-shadowed");
});

test("authors explicit Enum values and paginates the whole declared product", async ({
  page,
}) => {
  await open(page);
  await page.getByLabel("State value mode on", { exact: true }).fill("0");
  await page
    .getByRole("button", { name: "Review all combinations", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText(
    "Domain values must be unique",
  );
  await page.getByLabel("State value mode on", { exact: true }).fill("2");
  for (let i = 0; i < 6; i++)
    await page.getByRole("button", { name: "Add input", exact: true }).click();
  await review(page);
  await expect(
    page.getByText("1–64 of 256 filtered combinations", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Next cases", exact: true }).click();
  await expect(
    page.getByText("65–128 of 256 filtered combinations", { exact: true }),
  ).toBeVisible();
  await page
    .getByLabel("Coverage filter", { exact: true })
    .selectOption("uncovered");
  await expect(
    page.getByText("1–64 of 64 filtered combinations", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Next cases", exact: true }),
  ).toBeDisabled();
});

test("late review never replaces edited source", async ({ page }) => {
  await open(page);
  let release!: () => void;
  const waiting = new Promise<void>((resolve) => (release = resolve));
  let arrived!: () => void;
  const requested = new Promise<void>((resolve) => (arrived = resolve));
  await page.route("**/api/truth-tables/review", async (route) => {
    const response = await route.fetch();
    arrived();
    await waiting;
    await route.fulfill({ response });
  });
  await page
    .getByRole("button", { name: "Review all combinations", exact: true })
    .click();
  await requested;
  await page
    .getByLabel("Truth-table name", { exact: true })
    .fill("Edited during review");
  await releaseReply(page, "/truth-tables/review", release);
  await expect(
    page.getByLabel("Truth-table name", { exact: true }),
  ).toHaveValue("Edited during review");
  await expect(
    page.getByRole("region", { name: "Truth-table review", exact: true }),
  ).toHaveCount(0);
});

test("late selected evaluation cannot replace a changed selection", async ({
  page,
}) => {
  await open(page);
  await review(page);
  let release!: () => void, arrived!: () => void;
  const waiting = new Promise<void>((resolve) => (release = resolve)),
    requested = new Promise<void>((resolve) => (arrived = resolve));
  await page.route(
    "**/api/truth-tables/evaluate",
    async (route) => {
      const response = await route.fetch();
      arrived();
      await waiting;
      await route.fulfill({ response });
    },
    { times: 1 },
  );
  await page
    .getByRole("button", { name: "Evaluate selected combination", exact: true })
    .click();
  await requested;
  await page.getByLabel("Selected mode", { exact: true }).selectOption("on");
  await releaseReply(page, "/truth-tables/evaluate", release);
  await expect(page.getByLabel("Selected combination result")).toHaveCount(0);
  await page
    .getByRole("button", { name: "Evaluate selected combination", exact: true })
    .click();
  await expect(page.getByLabel("Selected combination result")).toContainText(
    "True (True)",
  );
});

test("late import cannot replace edits and actual tampered seals are refused", async ({
  page,
}, info) => {
  await open(page);
  await review(page);
  const path = info.outputPath("source.json");
  const source = await exported(page, "table", path);
  let release!: () => void, arrived!: () => void;
  const waiting = new Promise<void>((resolve) => (release = resolve)),
    requested = new Promise<void>((resolve) => (arrived = resolve));
  await page.route(
    "**/api/truth-tables/import",
    async (route) => {
      const response = await route.fetch();
      arrived();
      await waiting;
      await route.fulfill({ response });
    },
    { times: 1 },
  );
  await page
    .getByLabel("Import truth table", { exact: true })
    .setInputFiles(path);
  await requested;
  await page
    .getByLabel("Truth-table name", { exact: true })
    .fill("Keep this edit");
  await releaseReply(page, "/truth-tables/import", release);
  await expect(
    page.getByLabel("Truth-table name", { exact: true }),
  ).toHaveValue("Keep this edit");
  await page.getByLabel("Import truth table", { exact: true }).setInputFiles({
    name: "tampered.json",
    mimeType: "application/json",
    buffer: Buffer.from(
      source.raw
        .toString()
        .replace("Mode and override example", "Different source name"),
    ),
  });
  await expect(page.getByRole("alert")).toContainText("content seal failed");
  await expect(
    page.getByLabel("Truth-table name", { exact: true }),
  ).toHaveValue("Keep this edit");
});

test("leaving the workspace suppresses an in-flight authoritative download", async ({
  page,
}) => {
  await open(page);
  await review(page);
  let release!: () => void, arrived!: () => void;
  const waiting = new Promise<void>((resolve) => (release = resolve)),
    requested = new Promise<void>((resolve) => (arrived = resolve));
  await page.route("**/api/truth-tables/export/review", async (route) => {
    const response = await route.fetch();
    arrived();
    await waiting;
    await route.fulfill({ response });
  });
  let downloads = 0;
  page.on("download", () => downloads++);
  await page
    .getByRole("button", { name: "Export full review", exact: true })
    .click();
  await requested;
  await page.getByRole("button", { name: "Program", exact: true }).click();
  await releaseReply(page, "/truth-tables/export/review", release);
  await expect(
    page.getByRole("heading", { name: "Truth tables", exact: true }),
  ).toHaveCount(0);
  expect(downloads).toBe(0);
});

test("editing source suppresses an in-flight authoritative source download", async ({
  page,
}) => {
  await open(page);
  await review(page);
  let release!: () => void, arrived!: () => void;
  const waiting = new Promise<void>((resolve) => (release = resolve)),
    requested = new Promise<void>((resolve) => (arrived = resolve));
  await page.route("**/api/truth-tables/export/table", async (route) => {
    const response = await route.fetch();
    arrived();
    await waiting;
    await route.fulfill({ response });
  });
  let downloads = 0;
  page.on("download", () => downloads++);
  await page.getByRole("button", { name: "Export table", exact: true }).click();
  await requested;
  await page
    .getByLabel("Truth-table name", { exact: true })
    .fill("New table source");
  await releaseReply(page, "/truth-tables/export/table", release);
  expect(downloads).toBe(0);
  await expect(
    page.getByRole("region", { name: "Truth-table review", exact: true }),
  ).toHaveCount(0);
});

test("late coverage page cannot replace a new source review", async ({
  page,
}) => {
  await open(page);
  for (let i = 0; i < 6; i++)
    await page.getByRole("button", { name: "Add input", exact: true }).click();
  await review(page);
  let release!: () => void, arrived!: () => void;
  const waiting = new Promise<void>((resolve) => (release = resolve)),
    requested = new Promise<void>((resolve) => (arrived = resolve));
  await page.route(
    "**/api/truth-tables/cases",
    async (route) => {
      const response = await route.fetch();
      arrived();
      await waiting;
      await route.fulfill({ response });
    },
    { times: 1 },
  );
  await page.getByRole("button", { name: "Next cases", exact: true }).click();
  await requested;
  await page
    .getByLabel("Truth-table name", { exact: true })
    .fill("New source for coverage");
  await review(page);
  await releaseReply(page, "/truth-tables/cases", release);
  await expect(
    page.getByText("1–64 of 256 filtered combinations", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("65–128 of 256 filtered combinations", { exact: true }),
  ).toHaveCount(0);
});

test("a stale displayed rule profile cannot silently change the interpretation", async ({
  page,
}) => {
  await page.route("**/api/truth-tables/profile", async (route) => {
    const response = await route.fetch();
    const catalog = await response.json();
    catalog.profile.sha256 = "0".repeat(64);
    await route.fulfill({ json: catalog });
  });
  await open(page);
  await page
    .getByRole("button", { name: "Review all combinations", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("profile changed");
  await expect(
    page.getByRole("region", { name: "Truth-table review", exact: true }),
  ).toHaveCount(0);
});
