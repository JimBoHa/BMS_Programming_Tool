import { test, expect, type Page, type Route } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";

const root = path.resolve("..");
const python = path.join(root, ".venv/bin/python");
const reference = "8-1/575_1";

function authored(title = "Authored example") {
  return execFileSync(
    python,
    [
      "-c",
      `
from tests.test_caf_graph import make_graph,pack
from bms_tool.caf import CafArchive
import sys
xml=CafArchive(make_graph()).xml.replace(b'Authored example',sys.argv[1].encode())
sys.stdout.buffer.write(pack(xml))
`,
      title,
    ],
    { cwd: root },
  );
}

async function choose(page: Page, name: string, title = "Authored example") {
  await page.locator('input[type=file][accept=".caf"]').setInputFiles({
    name,
    mimeType: "application/octet-stream",
    buffer: authored(title),
  });
}

async function open(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "CAF files", exact: true }).click();
  await choose(page, "first.caf");
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("first.caf");
  await expect(
    page
      .getByRole("region", { name: "Native CAF graph", exact: true })
      .locator(".caf-graph-summary"),
  ).toContainText("4 blocks · 2 connections");
}

function object(page: Page, number: number) {
  return page
    .locator(".caf-layout tbody tr")
    .filter({ has: page.getByText(`Block ${number}`, { exact: true }) });
}

async function editScalar(page: Page, value: string) {
  await object(page, 10).click();
  await page.getByLabel("CAF property 3113", { exact: true }).fill(value);
}

function inspect(file: string) {
  return JSON.parse(
    execFileSync(
      python,
      [
        "-c",
        `
from bms_tool.caf import CafArchive
from bms_tool.caf_graph import CafGraph
from pathlib import Path
import json,sys
data=Path(sys.argv[1]).read_bytes();caf=CafArchive(data)
print(json.dumps({'values':{row['ref']:row['stored_value'] for row in caf.inventory()},
 'wires':[w['raw'] for w in CafGraph(data).diagram('${reference}')['connections']]}))
`,
        file,
      ],
      { cwd: root, encoding: "utf8" },
    ),
  );
}

async function hold(
  page: Page,
  pattern: string,
  matches: (route: Route) => boolean = () => true,
) {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let ready!: () => void;
  const reached = new Promise<void>((resolve) => {
    ready = resolve;
  });
  let held = false;
  await page.route(pattern, async (route) => {
    if (held || !matches(route)) return route.continue();
    held = true;
    // Delay delivery of the actual API response; no backend semantic mocks.
    const response = await route.fetch();
    ready();
    await gate;
    await route.fulfill({ response });
  });
  return { reached, release };
}

test("late properties cannot overwrite another selected object's values or edit target", async ({
  page,
}) => {
  await open(page);
  const held = await hold(
    page,
    "**/api/caf/*/properties?*",
    (route) =>
      new URL(route.request().url()).searchParams.get("ref") ===
      `${reference}.2_10`,
  );
  try {
    await object(page, 10).click();
    await held.reached;
    await object(page, 11).click();
    await expect(
      page.getByLabel("CAF property 3113", { exact: true }),
    ).toHaveValue("11.000");
    held.release();
    await page.waitForLoadState("networkidle");
    await expect(
      page.getByLabel("CAF property 3113", { exact: true }),
    ).toHaveValue("11.000");
    await page.getByLabel("CAF property 3113", { exact: true }).fill("42.5");
    const pending = page.waitForEvent("download");
    await page
      .getByRole("button", { name: "Export CAF copy", exact: true })
      .click();
    const file = await pending;
    const result = inspect((await file.path())!);
    expect(result.values[`${reference}.2_10`]).toBe("10.000");
    expect(result.values[`${reference}.2_11`]).toBe("42.5");
  } finally {
    held.release();
  }
});

test("latest selected archive wins even when an earlier upload completes later", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "CAF files", exact: true }).click();
  const held = await hold(page, "**/api/caf");
  try {
    await choose(page, "slow-first.caf");
    await held.reached;
    await choose(page, "fast-second.caf", "Second authored archive");
    await expect(
      page.getByLabel("Current CAF archive", { exact: true }),
    ).toHaveText("fast-second.caf");
    held.release();
    await page.waitForLoadState("networkidle");
    await expect(
      page.getByLabel("Current CAF archive", { exact: true }),
    ).toHaveText("fast-second.caf");
    await expect(
      page.getByLabel("Native CAF diagram", { exact: true }),
    ).toContainText("Second authored archive");
  } finally {
    held.release();
  }
});

test("unexported scalars survive refused file replacement and tab navigation; exported drafts need no discard", async ({
  page,
}) => {
  await open(page);
  await editScalar(page, "42");
  await page.getByRole("button", { name: "CAF compare", exact: true }).click();
  await page.getByRole("button", { name: "CAF files", exact: true }).click();
  await expect(
    page.getByLabel("CAF property 3113", { exact: true }),
  ).toHaveValue("42");
  page.once("dialog", async (dialog) => {
    expect(dialog.message()).toContain("unexported CAF edits");
    await dialog.dismiss();
  });
  await choose(page, "second.caf", "Second authored archive");
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("first.caf");
  await expect(
    page.getByLabel("CAF property 3113", { exact: true }),
  ).toHaveValue("42");
  const pending = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Export CAF copy", exact: true })
    .click();
  const file = await pending;
  expect(inspect((await file.path())!).values[`${reference}.2_10`]).toBe("42");
  await expect(
    page.getByLabel("Scalar CAF export result", { exact: true }),
  ).toContainText("first-scalars.caf with 1 scalar change");
  let prompts = 0;
  page.on("dialog", async (dialog) => {
    prompts++;
    await dialog.dismiss();
  });
  await choose(page, "second.caf", "Second authored archive");
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("second.caf");
  expect(prompts).toBe(0);
});

test("scalar export keeps its snapshot outcome when the editable draft changes during preparation", async ({
  page,
}) => {
  await open(page);
  await editScalar(page, "42");
  const held = await hold(page, "**/api/caf/*/export");
  try {
    const pending = page.waitForEvent("download");
    await page
      .getByRole("button", { name: "Export CAF copy", exact: true })
      .click();
    await held.reached;
    await page.getByLabel("CAF property 3113", { exact: true }).fill("43");
    held.release();
    const file = await pending;
    expect(inspect((await file.path())!).values[`${reference}.2_10`]).toBe(
      "42",
    );
    await expect(
      page.getByLabel("CAF property 3113", { exact: true }),
    ).toHaveValue("43");
    await expect(
      page.getByText("Current scalar edits have not been exported.", {
        exact: true,
      }),
    ).toBeVisible();
    page.once("dialog", async (dialog) => {
      expect(dialog.message()).toContain("unexported CAF edits");
      await dialog.dismiss();
    });
    await choose(page, "second.caf", "Second authored archive");
    await expect(
      page.getByLabel("CAF property 3113", { exact: true }),
    ).toHaveValue("43");
  } finally {
    held.release();
  }
});

test("explicitly reopening the same CAF resets discarded native proposals and scalar drafts", async ({
  page,
}) => {
  await open(page);
  const panel = page.getByRole("region", {
    name: "Native CAF graph",
    exact: true,
  });
  await panel
    .getByLabel("Native replacement source", { exact: true })
    .selectOption(`${reference}.2_11`);
  page.once("dialog", async (dialog) => {
    await dialog.accept();
  });
  await choose(page, "first.caf");
  await expect(
    panel.getByLabel("Native replacement source", { exact: true }),
  ).toHaveValue("");
  await editScalar(page, "42");
  page.once("dialog", async (dialog) => {
    await dialog.accept();
  });
  await choose(page, "first.caf");
  await expect(
    page.getByLabel("CAF property 3113", { exact: true }),
  ).toHaveCount(0);
  await object(page, 10).click();
  await expect(
    page.getByLabel("CAF property 3113", { exact: true }),
  ).toHaveValue("10.000");
});

test("native proposal switching requires discard until exported, and outcome keeps its original tuple", async ({
  page,
}) => {
  await open(page);
  const panel = page.getByRole("region", {
    name: "Native CAF graph",
    exact: true,
  });
  await panel
    .getByLabel("Native replacement source", { exact: true })
    .selectOption(`${reference}.2_11`);
  page.once("dialog", async (dialog) => {
    expect(dialog.message()).toContain("unexported native CAF");
    await dialog.dismiss();
  });
  await panel
    .getByRole("button", { name: "Select native connection 1", exact: true })
    .click();
  await expect(
    panel.getByRole("button", {
      name: "Select native connection 0",
      exact: true,
    }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(
    panel.getByLabel("Native replacement source", { exact: true }),
  ).toHaveValue(`${reference}.2_11`);
  await page.getByRole("button", { name: "CAF compare", exact: true }).click();
  await page.getByRole("button", { name: "CAF files", exact: true }).click();
  await expect(
    panel.getByLabel("Native replacement source", { exact: true }),
  ).toHaveValue(`${reference}.2_11`);
  const pending = page.waitForEvent("download");
  await panel
    .getByRole("button", {
      name: "Check and export native CAF rewire",
      exact: true,
    })
    .click();
  const file = await pending;
  expect(inspect((await file.path())!).wires[0]).toEqual([1, 663, 2, 513]);
  await panel
    .getByRole("button", { name: "Select native connection 1", exact: true })
    .click();
  await expect(panel.getByRole("status")).toContainText(
    "connection #0, [0,663,2,513] to [1,663,2,513]",
  );
  await expect(
    panel.getByLabel("Native replacement source", { exact: true }),
  ).toHaveValue("");
});

for (const kind of ["scalar", "native"] as const) {
  test(`${kind} export response cannot download or report success for a subsequently opened archive`, async ({
    page,
  }) => {
    await open(page);
    const panel = page.getByRole("region", {
      name: "Native CAF graph",
      exact: true,
    });
    if (kind === "scalar") await editScalar(page, "42");
    else
      await panel
        .getByLabel("Native replacement source", { exact: true })
        .selectOption(`${reference}.2_11`);
    const held = await hold(
      page,
      kind === "scalar" ? "**/api/caf/*/export" : "**/api/caf/*/rewire",
    );
    let downloads = 0;
    page.on("download", () => downloads++);
    try {
      await page
        .getByRole("button", {
          name:
            kind === "scalar"
              ? "Export CAF copy"
              : "Check and export native CAF rewire",
          exact: true,
        })
        .click();
      await held.reached;
      page.once("dialog", async (dialog) => {
        await dialog.accept();
      });
      await choose(page, "second.caf", "Second authored archive");
      await expect(
        page.getByLabel("Current CAF archive", { exact: true }),
      ).toHaveText("second.caf");
      held.release();
      await page.waitForLoadState("networkidle");
      expect(downloads).toBe(0);
      await expect(
        page.getByLabel("Scalar CAF export result", { exact: true }),
      ).toHaveCount(0);
      await expect(panel.locator(".caf-graph-exported")).toHaveCount(0);
      await expect(page.getByRole("alert")).toHaveCount(0);
    } finally {
      held.release();
    }
  });
}
