import { test, expect } from "./nativeScheduleWriteFixture";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import {
  enter,
  logic,
  inspect,
  prepare,
  source,
  inspectFile,
  ref,
} from "./caf-constant-fixture";
import { chooseWorkspaceTask } from "./workspace-navigation";
import { python } from "./caf-constant-fixture";

test("offline copy includes both identities, preserves exact review and can use the existing web connection editor", async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 820, height: 1100 });
  const editor = await enter(page);
  await expect(editor).toContainText("output 1.000000");
  await editor.getByLabel("New constant X", { exact: true }).fill("+81.000");
  for (const label of [
    "Constant prototype",
    "New constant X",
    "New constant Y",
  ])
    expect(
      (await editor.getByLabel(label, { exact: true }).boundingBox())!.height,
    ).toBeGreaterThanOrEqual(36);
  let exact = Buffer.alloc(0);
  await page.route("**/constant-copy/preview", async (route) => {
    const response = await route.fetch({ maxRetries: 0 });
    exact = await response.body();
    await route.fulfill({ response });
  });
  const review = await prepare(page),
    reviewed = JSON.parse(exact.toString());
  let downloading = page.waitForEvent("download");
  await review
    .getByRole("button", { name: "Save exact constant review", exact: true })
    .click();
  expect(readFileSync((await (await downloading).path())!)).toEqual(exact);
  downloading = page.waitForEvent("download");
  await review
    .getByRole("button", { name: "Save constant CAF copy", exact: true })
    .click();
  const file = (await (await downloading).path())!;
  expect(createHash("sha256").update(readFileSync(file)).digest("hex")).toBe(
    reviewed.creation.output_sha256,
  );
  expect(inspectFile(file)).toMatchObject({
    objects: 7,
    blocks: 4,
    order: [0, 3, 1, 2],
    wires: [[0, 85, 1, 513]],
    external_attr: 0,
    last: {
      ref: ref + ".551_31",
      layout: { x: "+81.000", y: "42.000", opaque_code: 12 },
    },
  });
  await expect(editor.getByRole("status")).toContainText(
    "No controller write was sent",
  );
  await page
    .getByLabel("Open local CAF application", { exact: true })
    .setInputFiles({
      name: "copied.caf",
      mimeType: "application/octet-stream",
      buffer: readFileSync(file),
    });
  await logic(page);
  const panel = page.getByRole("region", {
    name: "Native CAF graph",
    exact: true,
  });
  await panel
    .getByText("Connection table and guarded CAF export", { exact: true })
    .click();
  await panel
    .getByText("Add native connection between existing blocks", { exact: true })
    .click();
  await panel
    .getByLabel("Native new connection source", { exact: true })
    .selectOption(ref + ".551_31");
  await panel
    .getByLabel("Native new connection destination", { exact: true })
    .selectOption(ref + ".2_30");
  downloading = page.waitForEvent("download");
  await panel
    .getByRole("button", {
      name: "Check and export new native CAF connection",
      exact: true,
    })
    .click();
  expect(inspectFile((await (await downloading).path())!).wires).toEqual([
    [0, 85, 1, 513],
    [3, 85, 2, 513],
  ]);
  expect(
    (await (await request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
});

test("unfinished positions survive task and file ABA without restoring a review", async ({
  page,
}) => {
  let editor = await enter(page);
  await editor.getByLabel("New constant X", { exact: true }).fill("-");
  await editor.getByLabel("New constant Y", { exact: true }).fill(" ");
  await chooseWorkspaceTask(page, "Overview");
  await logic(page);
  editor = await inspect(page);
  await expect(
    page
      .getByRole("region", { name: "Native CAF graph", exact: true })
      .locator(".react-flow__node"),
  ).toHaveCount(3);
  await expect(
    editor.getByLabel("New constant X", { exact: true }),
  ).toHaveValue("-");
  await expect(
    editor.getByLabel("New constant Y", { exact: true }),
  ).toHaveValue(" ");
  await expect(
    editor.getByRole("button", {
      name: "Review constant CAF copy",
      exact: true,
    }),
  ).toBeDisabled();
  page.on("dialog", (d) => d.accept());
  for (const standard of [796, 11]) {
    await page
      .getByLabel("Open local CAF application", { exact: true })
      .setInputFiles({
        name: `constant-${standard}.caf`,
        mimeType: "application/octet-stream",
        buffer: source(standard),
      });
    await logic(page);
    editor = await inspect(page);
    await expect(editor).toContainText(`standard-name code ${standard}`);
    await expect(
      editor.getByLabel("New constant X", { exact: true }),
    ).toHaveValue(standard === 11 ? "-" : "81.000");
  }
  await editor.getByLabel("New constant X", { exact: true }).fill("81");
  await editor.getByLabel("New constant Y", { exact: true }).fill("42");
  await prepare(page);
  await chooseWorkspaceTask(page, "Overview");
  await logic(page);
  await inspect(page);
  await expect(
    page.getByRole("region", {
      name: "Reviewed CAF constant copy",
      exact: true,
    }),
  ).toHaveCount(0);
  await expect(
    editor.getByLabel("New constant X", { exact: true }),
  ).toHaveValue("81");
});

for (const event of ["pagehide", "hidden", "close", "navigation"])
  test(`late local download retires on ${event} and keeps its draft`, async ({
    page,
  }) => {
    let editor = await enter(page);
    await prepare(page);
    let release!: () => void, started!: () => void, completed!: () => void;
    const held = new Promise<void>((resolve) => (release = resolve)),
      entered = new Promise<void>((resolve) => (started = resolve)),
      finished = new Promise<void>((resolve) => (completed = resolve));
    await page.route("**/constant-copy/export", async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      started();
      await held;
      await route.fulfill({ response });
      completed();
    });
    const downloads: string[] = [];
    page.on("download", (d) => downloads.push(d.suggestedFilename()));
    await editor
      .getByRole("button", { name: "Save constant CAF copy", exact: true })
      .click();
    await entered;
    if (event === "pagehide")
      await page.evaluate(() => window.dispatchEvent(new Event("pagehide")));
    if (event === "hidden")
      await page.evaluate(() => {
        Object.defineProperty(document, "visibilityState", {
          configurable: true,
          value: "hidden",
        });
        document.dispatchEvent(new Event("visibilitychange"));
        Object.defineProperty(document, "visibilityState", {
          configurable: true,
          value: "visible",
        });
        document.dispatchEvent(new Event("visibilitychange"));
      });
    if (event === "close")
      await page.locator(".caf-constant-copy > summary").click();
    if (event === "navigation") {
      await chooseWorkspaceTask(page, "Overview");
      await logic(page);
    }
    release();
    await finished;
    await expect(
      page.getByRole("region", {
        name: "Reviewed CAF constant copy",
        exact: true,
      }),
    ).toHaveCount(0);
    editor = await inspect(page);
    // A fresh review waits for the retired export handler to finish, without extending timeouts.
    await page.unroute("**/constant-copy/export");
    await prepare(page);
    expect(downloads).toEqual([]);
    await expect(
      editor.getByLabel("New constant X", { exact: true }),
    ).toHaveValue("81.000");
  });

for (const kind of ["source", "review", "header", "bytes"])
  test(`substituted ${kind} proof never downloads a CAF`, async ({ page }) => {
    const downloads: string[] = [];
    page.on("download", (d) => downloads.push(d.suggestedFilename()));
    if (kind === "source")
      await page.route("**/constant-copy/source", async (route) => {
        const response = await route.fetch({ maxRetries: 0 }),
          body = await response.json();
        body.new_output_instance++;
        await route.fulfill({ response, json: body });
      });
    if (kind === "source") {
      await page.goto("/");
      await page
        .getByLabel("Open local CAF application", { exact: true })
        .setInputFiles({
          name: "constant.caf",
          mimeType: "application/octet-stream",
          buffer: source(),
        });
      await logic(page);
      await page.locator(".caf-constant-copy > summary").click();
      await page
        .getByRole("button", {
          name: "Inspect constant prototype",
          exact: true,
        })
        .click();
      await expect(
        page
          .getByRole("region", { name: "CAF constant creation", exact: true })
          .getByRole("alert"),
      ).toContainText("source proof");
    } else {
      const editor = await enter(page);
      if (kind === "review")
        await page.route("**/constant-copy/preview", async (route) => {
          const response = await route.fetch({ maxRetries: 0 }),
            body = await response.json();
          body.creation.new_output_sha256 = "0".repeat(64);
          await route.fulfill({ response, json: body });
        });
      if (kind === "review") {
        await editor
          .getByRole("button", {
            name: "Review constant CAF copy",
            exact: true,
          })
          .click();
        await expect(editor.getByRole("alert")).toContainText("review proof");
      } else {
        await prepare(page);
        await page.route("**/constant-copy/export", async (route) => {
          const response = await route.fetch({ maxRetries: 0 });
          if (kind === "header") {
            const headers = {
              ...response.headers(),
              "x-studio-creation-sha256": "0".repeat(64),
            };
            await route.fulfill({ response, headers });
          } else
            await route.fulfill({
              response,
              body: Buffer.from("substituted bytes"),
            });
        });
        await editor
          .getByRole("button", { name: "Save constant CAF copy", exact: true })
          .click();
        await expect(editor.getByRole("alert")).toContainText(
          "download bytes or proof",
        );
      }
    }
    expect(downloads).toEqual([]);
  });

test("prototype drafts retain exact text through ABA while reviews stay retired", async ({
  page,
}) => {
  const two = python(
    "from tests.test_caf_constant_copy import example,options;from bms_tool.caf_constant_copy import CafConstantCopies;import sys;c=CafConstantCopies(example());sys.stdout.buffer.write(c.compile(**options(c))[0])",
  );
  await page.goto("/");
  await page
    .getByLabel("Open local CAF application", { exact: true })
    .setInputFiles({
      name: "two.caf",
      mimeType: "application/octet-stream",
      buffer: two,
    });
  await logic(page);
  let editor = await inspect(page);
  await editor.getByLabel("New constant X", { exact: true }).fill(".5");
  await prepare(page);
  await editor
    .getByLabel("Constant prototype", { exact: true })
    .selectOption(ref + ".551_31");
  await expect(
    editor.getByLabel("New constant X", { exact: true }),
  ).toHaveValue("161.000");
  await editor.getByLabel("New constant X", { exact: true }).fill("-");
  await editor
    .getByLabel("Constant prototype", { exact: true })
    .selectOption(ref + ".551_10");
  await expect(
    editor.getByLabel("New constant X", { exact: true }),
  ).toHaveValue(".5");
  await expect(
    editor.getByRole("region", {
      name: "Reviewed CAF constant copy",
      exact: true,
    }),
  ).toHaveCount(0);
  await chooseWorkspaceTask(page, "Overview");
  await logic(page);
  editor = await inspect(page);
  await expect(
    editor.getByLabel("New constant X", { exact: true }),
  ).toHaveValue(".5");
  await editor
    .getByLabel("Constant prototype", { exact: true })
    .selectOption(ref + ".551_31");
  await expect(
    editor.getByLabel("New constant X", { exact: true }),
  ).toHaveValue("-");
});

test("late review after navigation ABA cannot return authority or clear newer text", async ({
  page,
}) => {
  let editor = await enter(page);
  let release!: () => void, started!: () => void, completed!: () => void;
  const held = new Promise<void>((r) => (release = r)),
    entered = new Promise<void>((r) => (started = r)),
    finished = new Promise<void>((r) => (completed = r));
  await page.route("**/constant-copy/preview", async (route) => {
    const response = await route.fetch({ maxRetries: 0 });
    started();
    await held;
    await route.fulfill({ response });
    completed();
  });
  await editor
    .getByRole("button", { name: "Review constant CAF copy", exact: true })
    .click();
  await entered;
  await chooseWorkspaceTask(page, "Overview");
  await logic(page);
  editor = await inspect(page);
  await editor.getByLabel("New constant X", { exact: true }).fill("-");
  release();
  await finished;
  await page.unroute("**/constant-copy/preview");
  await expect(
    editor.getByRole("region", {
      name: "Reviewed CAF constant copy",
      exact: true,
    }),
  ).toHaveCount(0);
  await expect(
    editor.getByLabel("New constant X", { exact: true }),
  ).toHaveValue("-");
  await expect(
    editor.getByRole("button", {
      name: "Review constant CAF copy",
      exact: true,
    }),
  ).toBeDisabled();
});

test("phone controls remain readable and keyboard review uses the local workflow", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const editor = await enter(page);
  const x = editor.getByLabel("New constant X", { exact: true });
  await x.focus();
  await page.keyboard.press("ControlOrMeta+A");
  await page.keyboard.type("12.5");
  await page.keyboard.press("Tab");
  await expect(
    editor.getByLabel("New constant Y", { exact: true }),
  ).toBeFocused();
  expect((await x.boundingBox())!.width).toBeGreaterThan(150);
  expect((await editor.boundingBox())!.width).toBeLessThan(391);
  await prepare(page);
  await expect(
    editor.getByRole("button", { name: "Save constant CAF copy", exact: true }),
  ).toBeEnabled();
  await editor
    .getByRole("button", { name: "Discard constant draft", exact: true })
    .click();
  await expect(
    editor.getByRole("region", {
      name: "Reviewed CAF constant copy",
      exact: true,
    }),
  ).toHaveCount(0);
  await expect(x).toHaveValue("81.000");
});
