import { test, expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import {
  seedDraft,
  recovery,
  review,
  openDraftCaf,
  editScalar,
  cafChanges,
  cafObjects,
  chooseFile,
  discardScalars,
  corruptDraft,
  pythonDraft,
} from "./caf-scalar-draft-recovery-fixture";
import {
  chooseWorkspaceTask,
  chooseWorkspaceTool,
} from "./workspace-navigation";
import { nativeDefaultPeer } from "./native-default-peer";
import { freePort } from "./workflow-peer";
const action = (page: Page, name: string) =>
  recovery(page).getByRole("button", { name, exact: true });
const strip = (page: Page) => page.locator(".export-strip:visible");
const calls = new WeakMap<Page, string[]>();
test.beforeEach(async ({ page, request }) => {
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  expect(
    (await request.post("/api/bacnet/disconnect", { headers, data: {} })).ok(),
  ).toBe(true);
  calls.set(page, []);
  page.on("request", (r) => {
    if (r.method() === "POST" && /\/api\/bacnet\//.test(r.url()))
      calls.get(page)!.push(r.url());
  });
});
async function save(page: Page, revision = 1) {
  await action(page, "Save scalar draft checkpoint").click();
  await expect(recovery(page)).toContainText(
    `Saved scalar checkpoint revision ${revision}`,
  );
}
async function restore(page: Page) {
  await action(page, "Restore saved scalar draft").click();
}
async function scalarCopy(page: Page) {
  const pending = page.waitForEvent("download");
  await strip(page)
    .getByRole("button", { name: "Save CAF copy", exact: true })
    .click();
  return readFileSync((await (await pending).path())!);
}
for (const width of [1440, 390])
  test(`unfinished scalar and Enum text reopens under a renamed CAF at ${width}px`, async ({
    page,
    context,
    request,
  }, info) => {
    const f = seedDraft();
    await page.setViewportSize({ width, height: 1000 });
    await openDraftCaf(page, f.caf);
    await editScalar(page, "FLOAT_CMD", "3113", "-");
    await editScalar(page, "ENUM_CMD", "3113", "1e");
    await editScalar(page, "FLOAT_CMD", "28", "  🙂  ");
    await cafChanges(page);
    await save(page);
    await recovery(page)
      .getByText("Inspect saved raw proposals", { exact: true })
      .click();
    const pending = page.waitForEvent("download");
    await action(page, "Download saved scalar draft JSON").click();
    const downloaded = JSON.parse(
      readFileSync((await (await pending).path())!, "utf8"),
    );
    expect(downloaded.changes.map((r: any) => r.value)).toEqual([
      "-",
      "1e",
      "  🙂  ",
    ]);
    const reopened = await context.newPage();
    await reopened.setViewportSize({ width, height: 1000 });
    await openDraftCaf(reopened, f.caf, "renamed-original.caf");
    await cafChanges(reopened);
    await expect(review(reopened)).toContainText("No scalar edits to review");
    await expect(recovery(reopened)).toContainText("Saved revision 1");
    await restore(reopened);
    await expect(review(reopened)).toContainText(
      "Enum edits copy numeric codes",
    );
    await expect(strip(reopened)).toContainText("3 proposed scalar changes");
    if (width === 390) {
      const scroll = review(reopened).getByRole("region", {
        name: "Current scalar proposals",
        exact: true,
      });
      await scroll.scrollIntoViewIfNeeded();
      await scroll.focus();
      await expect(scroll).toBeFocused();
      await scroll.press("ArrowRight");
      await expect
        .poll(() => scroll.evaluate((e) => e.scrollLeft))
        .toBeGreaterThan(0);
      await scroll.press("ArrowLeft");
      await expect.poll(() => scroll.evaluate((e) => e.scrollLeft)).toBe(0);
      await scroll.press("End");
      await expect
        .poll(() =>
          scroll.evaluate((e) => e.scrollWidth - e.clientWidth - e.scrollLeft),
        )
        .toBeLessThanOrEqual(1);
      const viewport = (await scroll.boundingBox())!,
        last = (await scroll.locator("thead th").last().boundingBox())!;
      expect(last.x).toBeGreaterThanOrEqual(viewport.x);
      expect(last.x + last.width).toBeLessThanOrEqual(
        viewport.x + viewport.width + 1,
      );
      await scroll.press("Home");
      await expect.poll(() => scroll.evaluate((e) => e.scrollLeft)).toBe(0);
      await scroll.press("End");
    }
    await expect(
      reopened.getByLabel("Scalar CAF export result", { exact: true }),
    ).toHaveCount(0);
    await strip(reopened)
      .getByRole("button", { name: "Save CAF copy", exact: true })
      .click();
    await expect(reopened.getByRole("alert").last()).toContainText(
      "Scalar CAF export failed",
    );
    const stored = await (
      await request.get(`/api/caf/${f.hash}/scalar-draft`)
    ).json();
    expect(stored.checkpoint.changes).toEqual(downloaded.changes);
    await recovery(reopened).scrollIntoViewIfNeeded();
    await reopened.screenshot({
      path: info.outputPath(`scalar-checkpoint-${width}.png`),
    });
    expect(calls.get(page)).toEqual([]);
    expect(
      (await (await request.get("/api/session")).json()).field_network_open,
    ).toBe(false);
    await reopened.close();
  });
test("previously exported scalar edits require explicit replacement and restore retires export success", async ({
  page,
  request,
}) => {
  const f = seedDraft();
  await openDraftCaf(page, f.caf);
  await editScalar(page, "ENUM_CMD", "3113", "256");
  await cafChanges(page);
  await save(page);
  await editScalar(page, "ENUM_CMD", "3113", "2");
  await cafChanges(page);
  const fresh = await scalarCopy(page);
  await expect(
    page.getByLabel("Scalar CAF export result", { exact: true }),
  ).toContainText("Browser download requested");
  await restore(page);
  const replace = page.getByRole("region", {
    name: "Replace current scalar edits",
    exact: true,
  });
  await expect(replace).toBeVisible();
  await replace
    .getByRole("button", { name: "Keep current scalar edits", exact: true })
    .click();
  await expect(
    review(page)
      .getByRole("region", { name: "Current scalar proposals", exact: true })
      .locator("tbody"),
  ).toContainText("2");
  await expect(
    page.getByLabel("Scalar CAF export result", { exact: true }),
  ).toBeVisible();
  await restore(page);
  await replace
    .getByRole("button", { name: "Replace current scalar edits", exact: true })
    .click();
  await expect(
    page.getByLabel("Scalar CAF export result", { exact: true }),
  ).toHaveCount(0);
  await expect(strip(page)).toContainText(
    "Current scalar edits have not been exported",
  );
  const restored = await scalarCopy(page);
  expect(restored).not.toEqual(fresh);
  const expected = Buffer.from(
    pythonDraft(
      "import base64;from tests.test_caf_enum_defaults import enum_caf,change;from bms_tool.caf import CafArchive;print(base64.b64encode(CafArchive(enum_caf()[0]).patch([change('256')])[0]).decode())",
    ).trim(),
    "base64",
  );
  expect(restored).toEqual(expected);
  expect(
    (await (await request.get(`/api/caf/${f.hash}/scalar-draft`)).json())
      .checkpoint.revision,
  ).toBe(1);
});
test("unchanged CAF export preserves exact original bytes without removing a saved checkpoint", async ({
  page,
  request,
}) => {
  const f = seedDraft(undefined, true);
  await openDraftCaf(page, f.caf);
  await cafChanges(page);
  expect(await scalarCopy(page)).toEqual(Buffer.from(f.caf, "base64"));
  expect(
    (await (await request.get(`/api/caf/${f.hash}/scalar-draft`)).json())
      .checkpoint,
  ).toEqual(f.checkpoint);
  await expect(review(page)).toContainText("No scalar edits to review");
});
test("restoring unfinished work retires a pending original CAF export response", async ({
  page,
}) => {
  const f = seedDraft(undefined, true);
  await openDraftCaf(page, f.caf);
  await cafChanges(page);
  let release!: () => void, started!: () => void;
  const gate = new Promise<void>((resolve) => (release = resolve)),
    ready = new Promise<void>((resolve) => (started = resolve)),
    downloads: string[] = [];
  page.on("download", (download) =>
    downloads.push(download.suggestedFilename()),
  );
  await page.route(
    `**/api/caf/${f.hash}/export`,
    async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      started();
      await gate;
      await route.fulfill({ response });
    },
    { times: 1 },
  );
  try {
    await strip(page)
      .getByRole("button", { name: "Save CAF copy", exact: true })
      .click();
    await ready;
    await restore(page);
    await expect(strip(page)).toContainText("3 proposed scalar changes");
    release();
    await page.unrouteAll({ behavior: "wait" });
    expect(downloads).toEqual([]);
    await expect(
      page.getByLabel("Scalar CAF export result", { exact: true }),
    ).toHaveCount(0);
    await expect(strip(page)).toContainText(
      "Current scalar edits have not been exported",
    );
  } finally {
    release();
  }
});
test("two browsers retain current work on revision conflicts and delete/recreate ABA", async ({
  page,
  context,
  request,
}) => {
  const f = seedDraft();
  await openDraftCaf(page, f.caf);
  await editScalar(page, "FLOAT_CMD", "3113", "-");
  await cafChanges(page);
  await save(page);
  const second = await context.newPage();
  await openDraftCaf(second, f.caf);
  await editScalar(second, "FLOAT_CMD", "3113", "1e");
  await cafChanges(second);
  await save(second, 2);
  await action(page, "Save scalar draft checkpoint").click();
  await expect(recovery(page).getByRole("alert")).toContainText(
    "checkpoint changed or was removed",
  );
  await expect(
    review(page)
      .getByRole("region", { name: "Current scalar proposals", exact: true })
      .locator("tbody"),
  ).toContainText("-");
  await action(page, "Remove saved scalar draft").click();
  await expect(recovery(page).getByRole("alert")).toContainText(
    "checkpoint changed or was removed",
  );
  const before = (
    await (await request.get(`/api/caf/${f.hash}/scalar-draft`)).json()
  ).checkpoint;
  await action(second, "Remove saved scalar draft").click();
  await expect(recovery(second)).toContainText("No saved scalar checkpoint");
  await save(second);
  const after = (
    await (await request.get(`/api/caf/${f.hash}/scalar-draft`)).json()
  ).checkpoint;
  expect(after.id).not.toBe(before.id);
  expect(after.revision).toBe(1);
  await restore(page);
  await expect(recovery(page).getByRole("alert")).toContainText(
    "checkpoint changed or was removed",
  );
  expect(
    (await (await request.get(`/api/caf/${f.hash}/scalar-draft`)).json())
      .checkpoint,
  ).toEqual(after);
  await second.close();
});
test("changed CAF hash never inherits the original checkpoint", async ({
  page,
}) => {
  const f = seedDraft(undefined, true);
  await openDraftCaf(page, f.caf);
  await cafChanges(page);
  await expect(recovery(page)).toContainText("Saved revision 1");
  await chooseFile(page, f.other, "other.caf");
  await cafChanges(page);
  await expect(recovery(page)).toContainText("No saved scalar checkpoint");
  await expect(action(page, "Restore saved scalar draft")).toBeDisabled();
});
test("corrupt checkpoint allows guarded removal while current text stays unchanged", async ({
  page,
}) => {
  const f = seedDraft(undefined, true);
  corruptDraft(f.hash);
  await openDraftCaf(page, f.caf);
  await editScalar(page, "FLOAT_CMD", "3113", "99");
  await cafChanges(page);
  await expect(recovery(page).getByRole("alert")).toContainText(
    "evidence is unavailable or inconsistent",
  );
  await expect(action(page, "Restore saved scalar draft")).toBeDisabled();
  await action(page, "Remove saved scalar draft").click();
  await expect(recovery(page)).toContainText("No saved scalar checkpoint");
  await expect(
    review(page)
      .getByRole("region", { name: "Current scalar proposals", exact: true })
      .locator("tbody"),
  ).toContainText("99");
});
test("ordinary editable fields with no class identifier restore without invented class constraints", async ({
  page,
}) => {
  const f = seedDraft(undefined, true, true);
  await openDraftCaf(page, f.caf);
  await cafChanges(page);
  await restore(page);
  await expect(strip(page)).toContainText("3 proposed scalar changes");
  await expect(review(page)).toContainText("Enum edits copy numeric codes");
});
for (const change of [
  "typing-after-navigation",
  "same-CAF-reopen",
  "failed-file-replacement",
] as const)
  test(`late restore cannot apply after ${change}`, async ({ page }) => {
    const f = seedDraft(undefined, true);
    await openDraftCaf(page, f.caf);
    await cafChanges(page);
    let release!: () => void, started!: () => void;
    const gate = new Promise<void>((resolve) => (release = resolve)),
      ready = new Promise<void>((resolve) => (started = resolve));
    await page.route(
      "**/scalar-draft/restore",
      async (route) => {
        const response = await route.fetch({ maxRetries: 0 });
        started();
        await gate;
        await route.fulfill({ response });
      },
      { times: 1 },
    );
    try {
      await restore(page);
      await ready;
      if (change === "typing-after-navigation") {
        await editScalar(page, "FLOAT_CMD", "3113", "99");
        await cafChanges(page);
      }
      if (change === "same-CAF-reopen") {
        await chooseFile(page, f.caf, "same-original.caf");
        await cafChanges(page);
      }
      if (change === "failed-file-replacement") {
        await page
          .getByLabel("Open local CAF application", { exact: true })
          .setInputFiles({
            name: "broken.caf",
            mimeType: "application/octet-stream",
            buffer: Buffer.from("not a CAF"),
          });
        await expect(page.getByRole("alert").last()).toBeVisible();
        await expect(
          page.getByLabel("Current CAF archive", { exact: true }),
        ).toHaveText("unfinished.caf");
        await cafChanges(page);
      }
      release();
      await page.unrouteAll({ behavior: "wait" });
      await expect(strip(page)).toContainText(
        change === "typing-after-navigation"
          ? "1 proposed scalar change"
          : "0 proposed scalar changes",
      );
      await expect(recovery(page)).not.toContainText("Restored saved text");
    } finally {
      release();
    }
  });
test("late save response preserves newer local text and leaves the saved snapshot explicit", async ({
  page,
  request,
}) => {
  const f = seedDraft();
  await openDraftCaf(page, f.caf);
  await editScalar(page, "FLOAT_CMD", "3113", "-");
  await cafChanges(page);
  let release!: () => void, started!: () => void;
  const gate = new Promise<void>((resolve) => (release = resolve)),
    ready = new Promise<void>((resolve) => (started = resolve));
  await page.route(`**/api/caf/${f.hash}/scalar-draft`, async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    const response = await route.fetch({ maxRetries: 0 });
    started();
    await gate;
    await route.fulfill({ response });
  });
  try {
    await action(page, "Save scalar draft checkpoint").click();
    await ready;
    await editScalar(page, "FLOAT_CMD", "3113", "1e");
    await cafChanges(page);
    release();
    await page.unrouteAll({ behavior: "wait" });
    await expect(
      review(page)
        .getByRole("region", { name: "Current scalar proposals", exact: true })
        .locator("tbody"),
    ).toContainText("1e");
    expect(
      (await (await request.get(`/api/caf/${f.hash}/scalar-draft`)).json())
        .checkpoint.changes[0].value,
    ).toBe("-");
    await expect(recovery(page)).not.toContainText(
      "Saved scalar checkpoint revision",
    );
  } finally {
    release();
  }
});
for (const fault of [
  "enum-eligibility",
  "source-old-text",
  "write-authority",
  "seal",
] as const)
  test(`altered restore ${fault} never replaces current text`, async ({
    page,
  }) => {
    const f = seedDraft(undefined, true);
    await openDraftCaf(page, f.caf);
    await cafChanges(page);
    await page.route("**/scalar-draft/restore", async (route) => {
      const response = await route.fetch({ maxRetries: 0 }),
        data = await response.json();
      if (fault === "enum-eligibility")
        data.fields[1].property.enum_code_copy.enum_semantics_verified = true;
      if (fault === "source-old-text")
        data.fields[0].property.scalar.text = "23.50";
      if (fault === "write-authority") data.can_apply = true;
      if (fault === "seal") data.checkpoint.checkpoint_sha256 = "0".repeat(64);
      await route.fulfill({ response, json: data });
    });
    await restore(page);
    await expect(recovery(page).getByRole("alert")).toBeVisible();
    await expect(strip(page)).toContainText("0 proposed scalar changes");
    await expect(
      page.getByRole("region", {
        name: "Replace current scalar edits",
        exact: true,
      }),
    ).toHaveCount(0);
    expect(calls.get(page)).toEqual([]);
  });
test("oversized raw text explains checkpoint limits without losing editing or export", async ({
  page,
}) => {
  const f = seedDraft();
  await openDraftCaf(page, f.caf);
  await editScalar(page, "FLOAT_CMD", "28", "x".repeat(8193));
  await cafChanges(page);
  await expect(action(page, "Save scalar draft checkpoint")).toBeDisabled();
  await expect(recovery(page).getByRole("alert")).toContainText(
    "8192 Unicode characters",
  );
  await expect(
    strip(page).getByRole("button", { name: "Save CAF copy", exact: true }),
  ).toBeEnabled();
  await expect(
    review(page)
      .getByRole("region", { name: "Current scalar proposals", exact: true })
      .locator("tbody"),
  ).toContainText("x".repeat(8193));
});
test("graph entry and instance draft remain separate from scalar checkpoint restore", async ({
  page,
}) => {
  const f = seedDraft();
  await page.goto("/");
  await page
    .getByRole("button", { name: "New application", exact: true })
    .click();
  await page
    .getByLabel("Program name", { exact: true })
    .fill("Keep local graph name");
  await chooseFile(page, f.caf);
  await page
    .getByLabel("New CAF device instance (0–4194302)", { exact: true })
    .fill("15136");
  await editScalar(page, "FLOAT_CMD", "3113", "-");
  await cafChanges(page);
  await save(page);
  await discardScalars(page);
  await restore(page);
  await expect(strip(page)).toContainText("1 proposed scalar change");
  await cafObjects(page);
  await expect(
    page.getByLabel("New CAF device instance (0–4194302)", { exact: true }),
  ).toHaveValue("15136");
  await chooseWorkspaceTool(page, "Graph editor");
  await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
    "Keep local graph name",
  );
  expect(calls.get(page)).toEqual([]);
});
test("selected routed controller stays unchanged and scalar recovery sends no field requests", async ({
  page,
}) => {
  const f = seedDraft(undefined, true),
    peer = await nativeDefaultPeer();
  try {
    await page.goto("/");
    await page
      .getByRole("button", { name: /^Connect to a controller/ })
      .click();
    await page
      .getByLabel("Local bind address / UDP port", { exact: true })
      .fill(`127.0.0.1:${await freePort()}`);
    await page
      .getByRole("button", { name: "Open interface", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Known controller address", exact: true })
      .click();
    await page
      .getByLabel("Known controller address", { exact: true })
      .fill("3001:7");
    await page
      .getByLabel("Known Device object", { exact: true })
      .fill("device,5136");
    await page.getByLabel("Known router", { exact: true }).fill(peer.router);
    await page.getByLabel("Known network", { exact: true }).fill("3001");
    await page
      .getByRole("region", { name: "Known controller connection", exact: true })
      .getByRole("button", { name: "Open controller", exact: true })
      .click();
    await expect(
      page.getByRole("region", { name: "Controller overview", exact: true }),
    ).toContainText("Authored controller");
    await chooseFile(page, f.caf);
    await cafChanges(page);
    const before = await peer.command("stats");
    await restore(page);
    await expect(strip(page)).toContainText("3 proposed scalar changes");
    await save(page, 2);
    const after = await peer.command("stats");
    expect(after.events).toEqual(before.events);
    expect(after.request_types).toEqual(before.request_types);
    await expect(
      page.getByLabel("Working context", { exact: true }),
    ).toContainText(peer.router);
    await expect(
      page.getByLabel("Working context", { exact: true }),
    ).toContainText("3001:7");
  } finally {
    peer.close();
  }
});
