import { test, expect } from "./nativeScheduleWriteFixture";
import { readFileSync } from "node:fs";
import {
  seedTerminals,
  enterTerminals,
  draftTerminal,
  reviewTerminal,
} from "./native-terminal-fixture";
import { chooseWorkspaceTask } from "./workspace-navigation";
import { connectionSeal } from "../src/nativeConnectionContract";

for (const effective of [false, true]) {
  test(`${effective ? "effective" : "archive"} Points & I/O saves exact local native copy and original review bytes`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const f = seedTerminals(nativeScheduleWriteServer.directory),
      editor = await enterTerminals(page, f.id, effective);
    await draftTerminal(editor);
    let raw = Buffer.alloc(0);
    await page.route("**/inputs/*terminal-copy/preview", async (route) => {
      const response = await route.fetch();
      raw = await response.body();
      await route.fulfill({ response, body: raw });
    });
    const review = await reviewTerminal(editor),
      data = JSON.parse(raw.toString());
    await expect(review).toContainText("analog-input,101: UI IN1 to UI IN3");
    await expect(editor).toContainText(
      effective
        ? "Captured saved values merged; these are not live values."
        : "Original archive; saved values are not merged.",
    );
    const reviewDownload = page.waitForEvent("download");
    await review
      .getByRole("button", { name: "Save terminal review", exact: true })
      .click();
    expect(readFileSync((await (await reviewDownload).path())!)).toEqual(raw);
    const downloaded = page.waitForEvent("download");
    await review
      .getByRole("button", { name: "Save native terminal copy", exact: true })
      .click();
    const file = await downloaded;
    expect(file.suggestedFilename()).toBe(
      effective
        ? "native-effective-terminal-copy.moi"
        : "native-local-terminal-copy.moi",
    );
    expect(readFileSync((await file.path())!)).toEqual(
      Buffer.from(f[effective ? "effective" : "archive"].output, "base64"),
    );
    await expect(editor).toContainText(
      "Saved a local native copy. No controller was changed.",
    );
    expect(data.controller_write).toBe(false);
    expect(data.can_apply).toBe(false);
    expect(
      await page.getByRole("button", { name: /Apply.*terminal/i }).count(),
    ).toBe(0);
  });
}

test("binary inputs use actual configured occupancy and preserve source-specific drafts through navigation", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seedTerminals(nativeScheduleWriteServer.directory),
    editor = await enterTerminals(page, f.binary);
  await expect(editor.getByLabel("Input to reassign")).toContainText(
    "binary-input,101",
  );
  expect(
    await editor
      .getByLabel("Input to reassign")
      .locator("option")
      .allTextContents(),
  ).not.toContain("Integral input");
  await editor.getByLabel("Input to reassign").selectOption("controller/3_101");
  await editor.getByLabel("Destination universal terminal").selectOption("2");
  await reviewTerminal(editor);
  await chooseWorkspaceTask(page, "Overview");
  await chooseWorkspaceTask(page, "Points & I/O");
  await editor.locator(":scope > summary").click();
  await expect(editor.getByLabel("Input to reassign")).toHaveValue(
    "controller/3_101",
  );
  await expect(editor.getByLabel("Destination universal terminal")).toHaveValue(
    "2",
  );
  await expect(
    editor.getByRole("region", {
      name: "Reviewed local terminal copy",
      exact: true,
    }),
  ).toHaveCount(0);
  await editor.getByLabel("Captured terminal source").selectOption(f.id);
  await expect(editor.getByLabel("Input to reassign")).toHaveValue("");
  await expect(editor.getByLabel("Destination universal terminal")).toHaveValue(
    "",
  );
  await expect(editor.getByLabel("Input to reassign")).toContainText(
    "analog-input,101",
  );
});

test("unknown saved schema stays visible and original archive remains independently usable", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seedTerminals(nativeScheduleWriteServer.directory),
    editor = await enterTerminals(page, f.unknown);
  await draftTerminal(editor);
  await reviewTerminal(editor);
  await editor.getByLabel("Terminal copy basis").selectOption("effective");
  await expect(editor.getByRole("alert")).toBeVisible();
  await expect(
    editor.getByRole("button", {
      name: "Save native terminal copy",
      exact: true,
    }),
  ).toHaveCount(0);
  await editor.getByLabel("Terminal copy basis").selectOption("archive");
  await expect(editor.getByLabel("Input to reassign")).toBeVisible();
  await draftTerminal(editor);
  await reviewTerminal(editor);
});

for (const invalidation of [
  "source",
  "basis",
  "draft",
  "collapse",
  "visibility",
  "navigation",
] as const) {
  test(`late preview cannot return after ${invalidation}`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const f = seedTerminals(nativeScheduleWriteServer.directory),
      editor = await enterTerminals(page, f.id);
    await draftTerminal(editor);
    let release!: () => void, seen!: () => void;
    const gate = new Promise<void>((r) => (release = r)),
      arrived = new Promise<void>((r) => (seen = r));
    await page.route("**/inputs/terminal-copy/preview", async (route) => {
      const response = await route.fetch();
      seen();
      await gate;
      await route.fulfill({ response });
    });
    await editor
      .getByRole("button", { name: "Review local terminal copy", exact: true })
      .click();
    await arrived;
    if (invalidation === "source")
      await editor
        .getByLabel("Captured terminal source")
        .selectOption(f.binary, { force: true });
    else if (invalidation === "basis")
      await editor
        .getByLabel("Terminal copy basis")
        .selectOption("effective", { force: true });
    else if (invalidation === "draft")
      await editor
        .getByLabel("Destination universal terminal")
        .selectOption("2", { force: true });
    else if (invalidation === "collapse")
      await editor.locator(":scope > summary").click();
    else if (invalidation === "visibility")
      await page.evaluate(() => window.dispatchEvent(new Event("pagehide")));
    else await chooseWorkspaceTask(page, "Overview");
    release();
    if (invalidation === "collapse" || invalidation === "visibility")
      await editor.locator(":scope > summary").click();
    if (invalidation === "navigation") {
      await chooseWorkspaceTask(page, "Points & I/O");
      await editor.locator(":scope > summary").click();
    }
    await expect(
      editor.getByRole("region", {
        name: "Reviewed local terminal copy",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      editor.getByRole("button", {
        name: "Save native terminal copy",
        exact: true,
      }),
    ).toHaveCount(0);
  });
}

for (const fault of [
  "bytes",
  "artifact",
  "review",
  "snapshot",
  "source",
  "compilation",
] as const) {
  test(`mismatched ${fault} export cannot download`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const f = seedTerminals(nativeScheduleWriteServer.directory),
      editor = await enterTerminals(page, f.id);
    await draftTerminal(editor);
    const review = await reviewTerminal(editor);
    let downloads = 0;
    page.on("download", () => downloads++);
    await page.route("**/inputs/terminal-copy/export", async (route) => {
      const response = await route.fetch(),
        headers = { ...response.headers() },
        body = await response.body();
      if (fault !== "bytes")
        headers[`x-studio-${fault}-sha256`] = "0".repeat(64);
      await route.fulfill({
        response,
        headers,
        body:
          fault === "bytes" ? Buffer.concat([body, Buffer.from([0])]) : body,
      });
    });
    await review
      .getByRole("button", { name: "Save native terminal copy", exact: true })
      .click();
    await expect(editor.getByRole("alert")).toContainText(
      "differ from the reviewed file",
    );
    expect(downloads).toBe(0);
  });
}

test("a resealed review with another slot is rejected before download is offered", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seedTerminals(nativeScheduleWriteServer.directory),
    editor = await enterTerminals(page, f.id);
  await draftTerminal(editor);
  await page.route("**/inputs/terminal-copy/preview", async (route) => {
    const response = await route.fetch(),
      v = await response.json();
    v.compilation.destination_slot = 2;
    const { compilation_sha256, ...c } = v.compilation;
    v.compilation.compilation_sha256 = await connectionSeal(c);
    const { review_sha256, ...body } = v;
    v.review_sha256 = await connectionSeal(body);
    await route.fulfill({ response, json: v });
  });
  await editor
    .getByRole("button", { name: "Review local terminal copy", exact: true })
    .click();
  await expect(editor.getByRole("alert")).toContainText(
    "does not match this input",
  );
  await expect(
    editor.getByRole("button", {
      name: "Save native terminal copy",
      exact: true,
    }),
  ).toHaveCount(0);
});
