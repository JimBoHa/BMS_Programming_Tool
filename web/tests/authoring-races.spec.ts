import { test, expect, type Page, type Route } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import {
  projectedSourceFixture,
  requestProgram,
} from "./sourceTransportFixtures";

const root = path.resolve("..");
function program(name: string, id: string) {
  return JSON.parse(
    execFileSync(
      path.join(root, ".venv/bin/python"),
      [
        "-c",
        "from tests.test_native_format_api import primitive; import sys; p=primitive(); p.name=sys.argv[1]; p.id=sys.argv[2]; print(p.model_dump_json())",
        name,
        id,
      ],
      { cwd: root, encoding: "utf8" },
    ),
  );
}

async function importProgram(page: Page, source: any) {
  await page.locator('input[type=file][accept*=".st"]').setInputFiles({
    name: source.id + ".bms.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(source)),
  });
  await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
    source.name,
  );
}

async function holdActual(
  page: Page,
  pattern: string,
  match: (route: Route) => boolean = () => true,
) {
  let release!: () => void, received!: (data: any) => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const captured = new Promise<any>((resolve) => {
    received = resolve;
  });
  let first = true,
    heldURL = "";
  const handler = async (route: Route) => {
    if (!first || !match(route)) return route.continue();
    first = false;
    heldURL = route.request().url();
    const response = await route.fetch();
    // The production endpoint has completed. Hold only actual HTTP delivery.
    received({
      status: response.status(),
      data: projectedSourceFixture(await response.json()),
    });
    await gate;
    await route.fulfill({ response });
  };
  await page.route(pattern, handler);
  return {
    captured,
    async deliver() {
      const delivering = page.waitForResponse(
        (response) => response.url() === heldURL,
      );
      release();
      await (await delivering).finished();
      await page.evaluate(
        () =>
          new Promise<void>((resolve) =>
            requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
          ),
      );
    },
    async close() {
      release();
      await page.unroute(pattern, handler);
    },
  };
}

async function exportedDraft(page: Page) {
  await page.getByLabel("Export format", { exact: true }).selectOption("json");
  const downloading = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export", exact: true }).click();
  return JSON.parse(readFileSync((await (await downloading).path())!, "utf8"));
}

test("saving a snapshot retains newer content and advances only its saved base revision", async ({
  page,
  request,
}) => {
  await page.goto("/");
  await importProgram(page, program("Snapshot before save", "save-race"));
  const hold = await holdActual(
    page,
    "**/api/projects",
    (route) => route.request().method() === "POST",
  );
  try {
    const save = page.getByRole("button", {
      name: "Save revision",
      exact: true,
    });
    await save.click();
    const persisted = await hold.captured;
    expect(persisted.status).toBe(200);
    expect(persisted.data.revision).toBe(1);
    await expect(save).toBeDisabled();
    await page
      .getByLabel("Program name", { exact: true })
      .fill("Newer unsaved content");
    await hold.deliver();
    await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
      "Newer unsaved content",
    );
    await expect(
      page.getByLabel("Last saved revision", { exact: true }),
    ).toContainText("Snapshot before save · r1");
    const current = await exportedDraft(page);
    expect(current.name).toBe("Newer unsaved content");
    expect(current.revision).toBe(1);
    const stored = await (
      await request.get(`/api/projects/${persisted.data.id}`)
    ).json();
    expect(stored.name).toBe("Snapshot before save");
    await expect(save).toBeEnabled();
    await save.click();
    await expect(
      page.getByLabel("Last saved revision", { exact: true }),
    ).toContainText("Newer unsaved content · r2");
    const latest = await (
      await request.get(`/api/projects/${persisted.data.id}`)
    ).json();
    expect(latest.name).toBe("Newer unsaved content");
    expect(latest.revision).toBe(2);
  } finally {
    await hold.close();
  }
});

test("a completed save cannot replace a different new draft", async ({
  page,
}) => {
  await page.goto("/");
  await importProgram(page, program("Saved separate project", "save-new-race"));
  const hold = await holdActual(
    page,
    "**/api/projects",
    (route) => route.request().method() === "POST",
  );
  try {
    await page
      .getByRole("button", { name: "Save revision", exact: true })
      .click();
    const saved = (await hold.captured).data;
    await page
      .getByRole("button", { name: "New program", exact: true })
      .click();
    await page
      .getByLabel("Program name", { exact: true })
      .fill("Unrelated draft");
    await hold.deliver();
    await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
      "Unrelated draft",
    );
    await expect(page.locator(".react-flow__node")).toHaveCount(0);
    const draft = await exportedDraft(page);
    expect(draft.id).not.toBe(saved.id);
    expect(draft.revision).toBe(0);
    await expect(
      page.getByLabel("Last saved revision", { exact: true }),
    ).toContainText("Saved separate project · r1");
  } finally {
    await hold.close();
  }
});

test("a save completing during a requested load cannot invalidate that newer navigation", async ({
  page,
  request,
}) => {
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  const first = program("Save and load source", "save-load-source");
  const second = program("Requested load destination", "save-load-destination");
  for (const source of [first, second]) {
    expect(
      (
        await request.post("/api/projects", {
          headers,
          data: { program: source, expected_revision: 0 },
        })
      ).ok(),
    ).toBe(true);
  }
  await page.goto("/");
  await page
    .getByLabel("Open saved project", { exact: true })
    .selectOption(first.id);
  await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
    first.name,
  );
  await page
    .getByLabel("Program name", { exact: true })
    .fill("Saved updated source");
  const saving = await holdActual(
    page,
    "**/api/projects",
    (route) => route.request().method() === "POST",
  );
  const loading = await holdActual(
    page,
    "**/api/projects/save-load-destination",
  );
  try {
    await page
      .getByRole("button", { name: "Save revision", exact: true })
      .click();
    expect((await saving.captured).data.revision).toBe(2);
    await page
      .getByLabel("Open saved project", { exact: true })
      .selectOption(second.id);
    await loading.captured;
    await saving.deliver();
    await loading.deliver();
    await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
      second.name,
    );
    const draft = await exportedDraft(page);
    expect(draft.id).toBe(second.id);
    expect(draft.revision).toBe(1);
    await expect(
      page.getByLabel("Last saved revision", { exact: true }),
    ).toContainText("Saved updated source · r2");
  } finally {
    await saving.close();
    await loading.close();
  }
});

test("late imports cannot overwrite edits or a more recent import", async ({
  page,
}) => {
  await page.goto("/");
  const first = program("First delayed import", "import-first");
  const second = program("Most recent import", "import-second");
  const hold = await holdActual(page, "**/api/import");
  const file = page.locator('input[type=file][accept*=".st"]');
  try {
    await file.setInputFiles({
      name: "first.json",
      mimeType: "application/json",
      buffer: Buffer.from(JSON.stringify(first)),
    });
    await hold.captured;
    await page
      .getByRole("button", { name: "New program", exact: true })
      .click();
    await page
      .getByLabel("Program name", { exact: true })
      .fill("Kept current edits");
    await hold.deliver();
    await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
      "Kept current edits",
    );
    await expect(page.locator(".react-flow__node")).toHaveCount(0);
  } finally {
    await hold.close();
  }
  const older = await holdActual(page, "**/api/import");
  try {
    await file.setInputFiles({
      name: "older.json",
      mimeType: "application/json",
      buffer: Buffer.from(JSON.stringify(first)),
    });
    await older.captured;
    await importProgram(page, second);
    await older.deliver();
    await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
      second.name,
    );
    await expect(page.locator(".react-flow__node")).toHaveCount(4);
  } finally {
    await older.close();
  }
});

test("saved project loads respect request order and preserve edits made while loading", async ({
  page,
  request,
}) => {
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  const first = program("Saved project A", "load-a");
  const second = program("Saved project B", "load-b");
  for (const source of [first, second]) {
    expect(
      (
        await request.post("/api/projects", {
          headers,
          data: { program: source, expected_revision: 0 },
        })
      ).ok(),
    ).toBe(true);
  }
  await page.goto("/");
  const loading = await holdActual(page, "**/api/projects/load-a");
  try {
    await page
      .getByLabel("Open saved project", { exact: true })
      .selectOption(first.id);
    await loading.captured;
    await page
      .getByLabel("Open saved project", { exact: true })
      .selectOption(second.id);
    await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
      second.name,
    );
    await loading.deliver();
    await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
      second.name,
    );
  } finally {
    await loading.close();
  }
  const edited = await holdActual(page, "**/api/projects/load-a");
  try {
    await page
      .getByLabel("Open saved project", { exact: true })
      .selectOption(first.id);
    await edited.captured;
    await page
      .getByLabel("Program name", { exact: true })
      .fill("Edited while loading");
    await edited.deliver();
    await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
      "Edited while loading",
    );
    const draft = await exportedDraft(page);
    expect(draft.id).toBe(second.id);
    expect(draft.revision).toBe(1);
  } finally {
    await edited.close();
  }
});

test("an old validation response cannot attach graph errors to a newer valid draft", async ({
  page,
}) => {
  await page.goto("/");
  const validation = await holdActual(
    page,
    "**/api/validate",
    (route) =>
      requestProgram(route.request().postDataJSON()).nodes.length === 0,
  );
  try {
    await page
      .getByRole("button", { name: "New program", exact: true })
      .click();
    const old = await validation.captured;
    expect(old.data.issues.some((issue: any) => issue.level === "error")).toBe(
      true,
    );
    await importProgram(page, program("Valid newer draft", "validation-new"));
    await expect(page.locator(".validation-bar button").first()).toContainText(
      "Graph checks passed",
    );
    await validation.deliver();
    await expect(page.locator(".validation-bar button").first()).toContainText(
      "Graph checks passed",
    );
    await expect(page.locator(".validation-error")).toHaveCount(0);
  } finally {
    await validation.close();
  }
});

test("a late sandbox preview is rejected until the exact current proposal is reviewed again", async ({
  page,
  request,
}) => {
  await page.goto("/");
  await importProgram(page, program("Old sandbox proposal", "runtime-race"));
  await page.getByRole("button", { name: "Runtime", exact: true }).click();
  const before = await (await request.get("/api/runtime")).json();
  const preview = await holdActual(page, "**/api/runtime/plan");
  try {
    const create = page.getByRole("button", {
      name: "Validate and preview deployment",
      exact: true,
    });
    await create.click();
    expect((await preview.captured).status).toBe(200);
    await expect(create).toBeDisabled();
    await page
      .getByLabel("Program name", { exact: true })
      .fill("New sandbox proposal");
    await preview.deliver();
    await expect(
      page.getByRole("button", {
        name: "Apply to sandbox runtime",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(page.getByRole("alert")).toContainText(
      "changed while previewing",
    );
    await expect(create).toBeEnabled();
    await create.click();
    await expect(
      page.getByRole("button", {
        name: "Apply to sandbox runtime",
        exact: true,
      }),
    ).toBeEnabled();
    await expect(page.locator("pre.result").first()).toContainText(
      '"result": 42',
    );
    const runtime = await (await request.get("/api/runtime")).json();
    expect(runtime.program).toEqual(before.program);
    expect(runtime.generation).toBe(before.generation);
  } finally {
    await preview.close();
  }
});
