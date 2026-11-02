import { test, expect, type Page, type Route } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../..", import.meta.url));
const python = path.join(root, ".venv/bin/python");
const pythonOptions = {
  cwd: root,
  env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
};
const reference = "8-1/575_1";
const fieldCalls = new WeakMap<Page, string[]>();
test.beforeEach(async ({ page, request }) => {
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  expect(
    (await request.post("/api/bacnet/disconnect", { headers, data: {} })).ok(),
  ).toBe(true);
  const calls: string[] = [];
  fieldCalls.set(page, calls);
  page.on("request", (request) => {
    if (request.method() === "POST" && /\/api\/bacnet\//.test(request.url()))
      calls.push(request.url());
  });
});
test.afterEach(async ({ page, request }) => {
  expect(fieldCalls.get(page)).toEqual([]);
  expect(
    (await (await request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
});

async function cafTask(page: Page, name: "Objects & parameters" | "Logic") {
  await page
    .getByRole("navigation", { name: "Workspace tasks" })
    .getByRole("button", { name: "Program", exact: true })
    .click();
  await page
    .getByRole("navigation", { name: "CAF application tasks" })
    .getByRole("button", { name, exact: true })
    .click();
  if (name === "Logic") {
    const advanced = page.locator(".caf-logic-export-tools");
    if ((await advanced.getAttribute("open")) === null)
      await advanced.locator("summary").first().click();
  }
}

async function compareAndReturn(
  page: Page,
  task: "Objects & parameters" | "Logic",
) {
  await page
    .getByRole("navigation", { name: "Workspace tasks" })
    .getByRole("button", { name: "Changes", exact: true })
    .click();
  await page
    .getByRole("navigation", { name: "Current task tools" })
    .getByRole("button", { name: "Compare applications", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Compare CAF files", exact: true }),
  ).toBeVisible();
  await cafTask(page, task);
}

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
    pythonOptions,
  );
}

async function choose(page: Page, name: string, title = "Authored example") {
  await page
    .getByLabel("Open local CAF application", { exact: true })
    .setInputFiles({
      name,
      mimeType: "application/octet-stream",
      buffer: authored(title),
    });
}

async function open(page: Page) {
  await page.goto("/");
  const choosing = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: /^Open a CAF file/ }).click();
  await (
    await choosing
  ).setFiles({
    name: "first.caf",
    mimeType: "application/octet-stream",
    buffer: authored(),
  });
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("first.caf");
  await cafTask(page, "Logic");
  await expect(
    page
      .getByRole("region", { name: "Native CAF graph", exact: true })
      .locator(".caf-graph-summary"),
  ).toContainText("4 blocks · 2 connections");
  await cafTask(page, "Objects & parameters");
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
      { ...pythonOptions, encoding: "utf8" },
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
    const response = await route.fetch({ maxRetries: 0 });
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
      .getByRole("button", { name: "Save CAF copy", exact: true })
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
  await expect(
    page.getByRole("button", { name: /^Open a CAF file/ }),
  ).toBeVisible();
  const held = await hold(page, "**/api/caf");
  try {
    await choose(page, "slow-first.caf");
    await held.reached;
    await choose(page, "fast-second.caf", "Second authored archive");
    await expect(
      page.getByLabel("Current CAF archive", { exact: true }),
    ).toHaveText("fast-second.caf");
    await cafTask(page, "Logic");
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
  await compareAndReturn(page, "Objects & parameters");
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
    .getByRole("button", { name: "Save CAF copy", exact: true })
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
      .getByRole("button", { name: "Save CAF copy", exact: true })
      .click();
    await held.reached;
    // Saving enters Changes; return to the editable task while delivery is held.
    await cafTask(page, "Objects & parameters");
    await page.getByLabel("CAF property 3113", { exact: true }).fill("43");
    held.release();
    const file = await pending;
    expect(inspect((await file.path())!).values[`${reference}.2_10`]).toBe(
      "42",
    );
    await expect(
      page.getByLabel("CAF property 3113", { exact: true }),
    ).toHaveValue("43");
    await page
      .getByRole("navigation", { name: "Workspace tasks" })
      .getByRole("button", { name: "Changes", exact: true })
      .click();
    await page
      .getByRole("navigation", { name: "Current task tools" })
      .getByRole("button", { name: "CAF changes", exact: true })
      .click();
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
  await cafTask(page, "Logic");
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
  await cafTask(page, "Logic");
  await expect(
    panel.getByLabel("Native replacement source", { exact: true }),
  ).toHaveValue("");
  await cafTask(page, "Objects & parameters");
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
  await cafTask(page, "Logic");
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
  await compareAndReturn(page, "Logic");
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
    else {
      await cafTask(page, "Logic");
      await panel
        .getByLabel("Native replacement source", { exact: true })
        .selectOption(`${reference}.2_11`);
    }
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
              ? "Save CAF copy"
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
      // This deliberately minimal graph has no root Device identity. Its
      // independent instance editor reports that limitation; no export error
      // may replace or accompany it after the old response arrives.
      await expect(page.getByRole("alert")).toHaveText([
        "Error: CAF instance editing requires one unambiguous root Device BACoid.",
      ]);
    } finally {
      held.release();
    }
  });
}
