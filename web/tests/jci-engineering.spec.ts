import { test, expect } from "./nativeScheduleWriteFixture";
import { readFile } from "node:fs/promises";
import {
  engineeringSource,
  reportFor,
  openEngineering,
  digest,
} from "./jci-engineering-fixture";
import {
  snapshotFixture,
  openSnapshot,
} from "./native-snapshot-restore-browser-fixture";
import {
  chooseWorkspaceSurface,
  chooseWorkspaceTask,
  chooseWorkspaceTool,
} from "./workspace-navigation";

for (const width of [1440, 390])
  test(
    "source inspection and exact evidence download remain readable at " +
      width +
      "px",
    async ({ page }, info) => {
      await page.setViewportSize({ width, height: 1000 });
      const panel = await openEngineering(page),
        source = engineeringSource();
      await panel
        .getByLabel("Engineering source file", { exact: true })
        .setInputFiles({
          name: "authored.caf",
          mimeType: "application/octet-stream",
          buffer: source,
        });
      await panel
        .getByRole("button", { name: "Inspect source", exact: true })
        .focus();
      await page.keyboard.press("Enter");
      await expect(
        panel.getByRole("heading", {
          name: "Readable projection",
          exact: true,
        }),
      ).toBeVisible();
      await expect(panel).toContainText("2 represented objects");
      await expect(panel).toContainText("native-sct-import-export");
      const saved = page.waitForEvent("download");
      await panel
        .getByRole("button", {
          name: "Save exact inspection report",
          exact: true,
        })
        .click();
      const download = await saved,
        raw = await readFile((await download.path())!);
      expect(raw).toEqual(reportFor());
      expect(JSON.parse(raw.toString()).source.sha256).toBe(digest(source));
      expect(JSON.parse(raw.toString()).apply_authority).toBe(false);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await panel
        .getByRole("heading", { name: "Readable projection", exact: true })
        .scrollIntoViewIfNeeded();
      await page.screenshot({
        path: info.outputPath("engineering-source-" + width + ".png"),
      });
    },
  );

test("searchable inventory keeps parent packages and native gaps explicit", async ({
  page,
}) => {
  const panel = await openEngineering(page);
  await panel
    .getByRole("button", { name: "Parity inventory", exact: true })
    .click();
  await expect(panel).toContainText("48 of 48");
  await panel
    .getByLabel("Engineering product", { exact: true })
    .selectOption("JCT");
  await expect(panel).toContainText("18 of 48");
  await panel
    .getByLabel("SCT/JCT feature search", { exact: true })
    .fill("vector");
  await expect(
    panel.getByRole("table", { name: "SCT/JCT parity packages", exact: true }),
  ).toContainText("JCT-05");
  await panel
    .getByLabel("SCT/JCT feature search", { exact: true })
    .fill("no-such-authored-feature");
  await expect(panel).toContainText("0 of 48");
  await panel
    .getByText("Artifact families and actual reader coverage", { exact: true })
    .click();
  await expect(panel).toContainText("Protected SCT archive/backup");
  await expect(panel).toContainText("native codec planned");
});

for (const kind of ["moi", "moz", "partial", "program", "unknown"])
  test(
    "selected " + kind + " content retains its distinct scope",
    async ({ page }) => {
      const panel = await openEngineering(page);
      const source =
        kind === "unknown"
          ? Buffer.from("<unknown archive/>")
          : engineeringSource(kind);
      await panel
        .getByLabel("Engineering source file", { exact: true })
        .setInputFiles({
          name: kind === "unknown" ? "unqualified.sDbExport" : "source.bin",
          mimeType: "application/octet-stream",
          buffer: source,
        });
      await panel
        .getByRole("button", { name: "Inspect source", exact: true })
        .click();
      await expect(
        panel.getByRole("heading", {
          name:
            kind === "unknown"
              ? "Unrecognized content"
              : kind === "partial"
                ? "Partial projection"
                : "Readable projection",
          exact: true,
        }),
      ).toBeVisible();
      await expect(panel).toContainText("not-granted");
      if (kind === "unknown")
        await expect(panel).toContainText("separately qualified native codec");
      if (kind === "partial")
        await expect(panel).toContainText("Partial native record coverage");
    },
  );

for (const change of ["source", "clear", "pane", "close", "surface"])
  test(
    "late inspection after " + change + " cannot return to the retired view",
    async ({ page }) => {
      const panel = await openEngineering(page);
      let release!: () => void, seen!: () => void;
      const wait = new Promise<void>((r) => (release = r)),
        reached = new Promise<void>((r) => (seen = r));
      await page.route("**/api/jci/engineering/inspect", async (route) => {
        const response = await route.fetch();
        seen();
        await wait;
        await route.fulfill({ response });
      });
      const select = panel.getByLabel("Engineering source file", {
        exact: true,
      });
      await select.setInputFiles({
        name: "authored.caf",
        mimeType: "application/octet-stream",
        buffer: engineeringSource(),
      });
      await panel
        .getByRole("button", { name: "Inspect source", exact: true })
        .click();
      await reached;
      if (change === "source")
        await select.setInputFiles({
          name: "replacement.dbexport",
          mimeType: "application/octet-stream",
          buffer: Buffer.from("opaque replacement"),
        });
      if (change === "clear")
        await panel
          .getByRole("button", { name: "Clear source", exact: true })
          .click();
      if (change === "pane")
        await panel
          .getByRole("button", { name: "Parity inventory", exact: true })
          .click();
      if (change === "close")
        await page
          .getByText("SCT/JCT engineering sources and parity inventory", {
            exact: true,
          })
          .click();
      if (change === "surface") await chooseWorkspaceSurface(page, "Settings");
      release();
      await page.unrouteAll({ behavior: "wait" });
      await page.evaluate(async () => {
        await new Promise<void>((resolve) =>
          requestAnimationFrame(() => resolve()),
        );
        await new Promise<void>((resolve) =>
          requestAnimationFrame(() => resolve()),
        );
      });
      if (change === "surface") await openEngineering(page, false);
      if (change === "close")
        await page
          .getByText("SCT/JCT engineering sources and parity inventory", {
            exact: true,
          })
          .click();
      if (change === "pane")
        await panel
          .getByRole("button", { name: "Source inspection", exact: true })
          .click();
      await expect(
        page.getByRole("heading", { name: "Readable projection", exact: true }),
      ).toHaveCount(0);
      await expect(
        page.getByRole("button", {
          name: "Save exact inspection report",
          exact: true,
        }),
      ).toHaveCount(0);
    },
  );

test("malformed report authority is rejected before showing a result", async ({
  page,
}) => {
  const panel = await openEngineering(page);
  await page.route("**/api/jci/engineering/inspect", async (route) => {
    const response = await route.fetch(),
      value = await response.json();
    value.apply_authority = true;
    await route.fulfill({
      status: 200,
      body: JSON.stringify(value),
      contentType: "application/json",
    });
  });
  await panel
    .getByLabel("Engineering source file", { exact: true })
    .setInputFiles({
      name: "authored.caf",
      mimeType: "application/octet-stream",
      buffer: engineeringSource(),
    });
  await panel
    .getByRole("button", { name: "Inspect source", exact: true })
    .click();
  await expect(panel.getByRole("alert")).toContainText(
    "does not match this file",
  );
  await expect(
    panel.getByRole("button", {
      name: "Save exact inspection report",
      exact: true,
    }),
  ).toHaveCount(0);
});

for (const caf of [false, true])
  snapshotFixture()(
    (caf ? "offline CAF" : "connected controller") +
      " inspection preserves existing graph, file and route",
    async ({ page, snapshot }) => {
      const { peer, seeded } = snapshot;
      await openSnapshot(page, seeded, caf, !caf);
      const before = await peer.command("stats");
      const panel = await openEngineering(page, false);
      await panel
        .getByLabel("Engineering source file", { exact: true })
        .setInputFiles({
          name: "unqualified.dbexport",
          mimeType: "application/octet-stream",
          buffer: Buffer.from("<unknown/>"),
        });
      await panel
        .getByRole("button", { name: "Inspect source", exact: true })
        .click();
      await expect(
        panel.getByRole("heading", {
          name: "Unrecognized content",
          exact: true,
        }),
      ).toBeVisible();
      await chooseWorkspaceSurface(page, "Workspace");
      await chooseWorkspaceTask(page, "Program");
      await chooseWorkspaceTool(page, "Graph editor");
      await expect(
        page.getByLabel("Program name", { exact: true }),
      ).toHaveValue("Preserved retained-restore local graph");
      if (caf) {
        await chooseWorkspaceTool(page, "CAF file");
        await expect(
          page.getByLabel("Current CAF archive", { exact: true }),
        ).toHaveText("retained-restore-local.caf");
      } else {
        await expect(page.getByLabel("Working context")).toContainText(
          seeded.target.address,
        );
      }
      expect((await peer.command("stats")).events).toEqual(before.events);
    },
  );
