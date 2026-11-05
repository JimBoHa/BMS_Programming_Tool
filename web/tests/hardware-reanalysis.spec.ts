import { test, expect } from "./nativeScheduleWriteFixture";
import {
  seedReanalysis,
  openSavedArchive,
} from "./hardware-reanalysis-fixture";
import { chooseWorkspaceTask } from "./workspace-navigation";
import { readFileSync } from "node:fs";
for (const caf of [false, true])
  for (const width of [1440, 390])
    test(`${caf ? "CAF" : "graph"} ${width}px saved-byte reanalysis preserves original and makes no field request`, async ({
      page,
      request,
      nativeScheduleWriteServer,
    }, info) => {
      const f = seedReanalysis(nativeScheduleWriteServer.directory),
        calls: string[] = [];
      await page.setViewportSize({ width, height: 1000 });
      page.on("request", (r) => {
        if (
          r.method() === "POST" &&
          new URL(r.url()).pathname.startsWith("/api/bacnet/")
        )
          calls.push(new URL(r.url()).pathname);
      });
      const panel = await openSavedArchive(page, f.parent.id, caf);
      await expect(
        panel.getByRole("button", {
          name: "Survey controller inputs",
          exact: true,
        }),
      ).toBeDisabled();
      const before = await (
        await request.get(
          "/api/bacnet/hardware/archives/" +
            f.parent.id +
            "/export?format=json",
        )
      ).body();
      let captured: any;
      await page.route("**/archives/*/reanalyze", async (route) => {
        captured = route.request().postDataJSON();
        await route.continue();
      });
      await panel
        .getByRole("button", { name: "Reanalyze saved archive", exact: true })
        .click();
      await expect(panel.getByRole("status")).toContainText(
        "Created new local analysis from saved bytes",
      );
      const id = await panel
        .getByLabel("Configured hardware archive", { exact: true })
        .inputValue();
      expect(id).not.toBe(f.parent.id);
      expect(id).not.toBe(f.child.id);
      expect(captured).toEqual({ source_sha256: f.parent.source.sha256 });
      const child = await (
        await request.get("/api/bacnet/hardware/archives/" + id)
      ).json();
      expect(child.origin.parent_archive_id).toBe(f.parent.id);
      expect(
        child.inputs.find((p: any) => p.object === "analog-input,56").host.kind,
      ).toBe("unknown");
      expect(
        await (
          await request.get(
            "/api/bacnet/hardware/archives/" +
              f.parent.id +
              "/export?format=json",
          )
        ).body(),
      ).toEqual(before);
      await expect(
        panel
          .getByRole("combobox", {
            name: "Configured hardware archive",
            exact: true,
          })
          .locator(`option[value="${f.parent.id}"]`),
      ).toHaveCount(1);
      const button = panel.getByRole("button", {
        name: "Download original controller archive",
        exact: true,
      });
      const download = page.waitForEvent("download");
      await button.click();
      const raw = await request.get(
        "/api/bacnet/hardware/archives/" +
          f.parent.id +
          "/export?format=source",
      );
      expect(readFileSync((await (await download).path())!)).toEqual(
        await raw.body(),
      );
      expect(calls).toEqual([
        "/api/bacnet/hardware/archives/" + f.parent.id + "/reanalyze",
      ]);
      expect(
        (await (await request.get("/api/session")).json()).field_network_open,
      ).toBe(false);
      expect(
        await button.evaluate(
          (n) => n.getBoundingClientRect().right <= innerWidth,
        ),
      ).toBe(true);
      await button.scrollIntoViewIfNeeded();
      await page.screenshot({
        path: info.outputPath(`saved-reanalysis-${width}.png`),
        fullPage: true,
      });
      if (caf) {
        await chooseWorkspaceTask(page, "Program");
        await expect(
          page.getByLabel("Working context", { exact: true }),
        ).toContainText("reanalysis.caf");
      }
    });
for (const fault of ["source", "identity", "lineage"] as const)
  test(`refuse inconsistent reanalysis ${fault} without replacing the selected archive`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const f = seedReanalysis(nativeScheduleWriteServer.directory),
      panel = await openSavedArchive(page, f.parent.id);
    await page.route("**/archives/*/reanalyze", async (route) => {
      const response = await route.fetch(),
        value = await response.json();
      if (fault === "source") value.source.sha256 = "0".repeat(64);
      if (fault === "identity")
        value.origin.current_controller_identity_verified = true;
      if (fault === "lineage") value.origin.parent_archive_id = "0".repeat(32);
      await route.fulfill({ response, json: value });
    });
    await panel
      .getByRole("button", { name: "Reanalyze saved archive", exact: true })
      .click();
    await expect(panel.getByRole("alert")).toContainText(
      "differs from the selected saved source",
    );
    await expect(
      panel.getByLabel("Configured hardware archive", { exact: true }),
    ).toHaveValue(f.parent.id);
  });
test("delayed reanalysis cannot restore a retired task or replace the current selection", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seedReanalysis(nativeScheduleWriteServer.directory);
  let release!: () => void, arrived!: () => void;
  const gate = new Promise<void>((r) => (release = r)),
    seen = new Promise<void>((r) => (arrived = r));
  await page.route("**/archives/*/reanalyze", async (route) => {
    const response = await route.fetch();
    arrived();
    await gate;
    await route.fulfill({ response });
  });
  const panel = await openSavedArchive(page, f.parent.id);
  await panel
    .getByRole("button", { name: "Reanalyze saved archive", exact: true })
    .click();
  await seen;
  await chooseWorkspaceTask(page, "Program");
  release();
  await expect(panel).toHaveCount(0);
  await chooseWorkspaceTask(page, "Points & I/O");
  const tools = page.getByRole("navigation", {
    name: "Controller task tools",
    exact: true,
  });
  await expect(tools).toBeVisible();
  await tools
    .getByRole("button", { name: "Hardware survey", exact: true })
    .click();
  await expect(
    page.getByLabel("Configured hardware archive", { exact: true }),
  ).toHaveValue("");
  await expect(
    page.getByRole("status").filter({ hasText: "Created new local analysis" }),
  ).toHaveCount(0);
});

test("new selection exists while the saved-library refresh is deliberately delayed", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seedReanalysis(nativeScheduleWriteServer.directory),
    panel = await openSavedArchive(page, f.parent.id);
  let release!: () => void,
    arrived!: () => void,
    hold = false,
    child: any;
  const gate = new Promise<void>((r) => (release = r)),
    seen = new Promise<void>((r) => (arrived = r));
  await page.route("**/archives/*/reanalyze", async (route) => {
    const response = await route.fetch();
    child = await response.json();
    hold = true;
    await route.fulfill({ response });
  });
  await page.route("**/api/bacnet/hardware/status", async (route) => {
    const response = await route.fetch();
    if (hold) {
      arrived();
      await gate;
    }
    await route.fulfill({ response });
  });
  await panel
    .getByRole("button", { name: "Reanalyze saved archive", exact: true })
    .click();
  await seen;
  await expect(
    panel.getByLabel("Configured hardware archive", { exact: true }),
  ).toHaveValue(child.id);
  await expect(
    panel.getByRole("button", {
      name: "Download original controller archive",
      exact: true,
    }),
  ).toBeVisible();
  release();
  await expect(
    panel.getByRole("button", { name: "Reanalyze saved archive", exact: true }),
  ).toBeEnabled();
  await expect(
    panel.getByLabel("Configured hardware archive", { exact: true }),
  ).toHaveValue(child.id);
});
