import { test, expect } from "./nativeScheduleWriteFixture";
import {
  seedTerminals,
  draftTerminal,
  reviewTerminal,
  enterTerminals,
} from "./native-terminal-fixture";
import { chooseWorkspaceTask } from "./workspace-navigation";
import { nativeDefaultPeer } from "./native-default-peer";
import { freePort } from "./workflow-peer";

for (const effective of [false, true]) {
  test(`${effective ? "effective" : "archive"} local terminal copy retains exact selected route and sends no field operation`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const f = seedTerminals(nativeScheduleWriteServer.directory),
      peer = await nativeDefaultPeer();
    async function select(routed: boolean) {
      await page
        .getByRole("button", { name: "Known controller address", exact: true })
        .click();
      await page
        .getByLabel("Known controller address", { exact: true })
        .fill(routed ? "3001:7" : peer.direct);
      await page
        .getByLabel("Known Device object", { exact: true })
        .fill("device,5136");
      await page
        .getByLabel("Known router", { exact: true })
        .fill(routed ? peer.router : "");
      await page
        .getByLabel("Known network", { exact: true })
        .fill(routed ? "3001" : "");
      await page
        .getByRole("region", {
          name: "Known controller connection",
          exact: true,
        })
        .getByRole("button", { name: "Open controller", exact: true })
        .click();
      await expect(
        page.getByRole("region", { name: "Controller overview", exact: true }),
      ).toContainText("Authored controller");
      await chooseWorkspaceTask(page, "Points & I/O");
      await page
        .getByRole("button", { name: "Configure native inputs", exact: true })
        .click();
      const editor = page.getByLabel("Local native terminal reassignment", {
        exact: true,
      });
      await editor.locator(":scope > summary").click();
      return editor;
    }
    try {
      await page.route("**/api/bacnet/controller/inventory", (route) =>
        route.fulfill({
          json: {
            identity_verified: true,
            complete: true,
            target: route.request().postDataJSON(),
            offset: 0,
            total: 0,
            next_offset: null,
            objects: [],
            errors: [],
          },
        }),
      );
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
      const editor = await select(true);
      await expect(editor).toContainText("network 3001 / station 3001:7");
      await editor.getByLabel("Captured terminal source").selectOption(f.id);
      if (effective)
        await editor
          .getByLabel("Terminal copy basis")
          .selectOption("effective");
      await draftTerminal(editor);
      const review = await reviewTerminal(editor),
        before = await peer.command("stats"),
        download = page.waitForEvent("download");
      await review
        .getByRole("button", { name: "Save native terminal copy", exact: true })
        .click();
      await download;
      const after = await peer.command("stats");
      expect(after.request_types).toEqual(before.request_types);
      expect(after.events).toEqual(before.events);
      await page
        .getByRole("button", { name: "Change controller", exact: true })
        .click();
      const changed = await select(false);
      await expect(changed).toContainText(peer.direct);
      await expect(changed.getByLabel("Captured terminal source")).toHaveValue(
        "",
      );
      await expect(
        changed.getByRole("region", {
          name: "Reviewed local terminal copy",
          exact: true,
        }),
      ).toHaveCount(0);
    } finally {
      peer.close();
    }
  });
}

for (const screen of [
  { width: 390, height: 844 },
  { width: 1024, height: 768 },
]) {
  test(`${screen.width}px terminal review stays in existing workspace layout`, async ({
    page,
    nativeScheduleWriteServer,
  }, testInfo) => {
    await page.setViewportSize(screen);
    const f = seedTerminals(nativeScheduleWriteServer.directory),
      editor = await enterTerminals(page, f.id, true);
    await draftTerminal(editor);
    await reviewTerminal(editor);
    await editor
      .getByRole("button", { name: "Save native terminal copy", exact: true })
      .scrollIntoViewIfNeeded();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: testInfo.outputPath(`terminal-${screen.width}.png`),
      fullPage: true,
    });
  });
}

for (const change of ["source", "collapse", "navigation"] as const) {
  test(`late export cannot download after ${change}`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const f = seedTerminals(nativeScheduleWriteServer.directory),
      editor = await enterTerminals(page, f.id);
    await draftTerminal(editor);
    const review = await reviewTerminal(editor);
    let release!: () => void,
      seen!: () => void,
      downloads = 0;
    const gate = new Promise<void>((r) => (release = r)),
      arrived = new Promise<void>((r) => (seen = r));
    page.on("download", () => downloads++);
    await page.route("**/inputs/terminal-copy/export", async (route) => {
      const response = await route.fetch();
      seen();
      await gate;
      await route.fulfill({ response });
    });
    await review
      .getByRole("button", { name: "Save native terminal copy", exact: true })
      .click();
    await arrived;
    if (change === "source")
      await editor
        .getByLabel("Captured terminal source")
        .selectOption(f.binary);
    else if (change === "collapse")
      await editor.locator(":scope > summary").click();
    else await chooseWorkspaceTask(page, "Overview");
    const settled = page.waitForResponse(
      (r) =>
        r.request().method() === "POST" &&
        r.url().endsWith("terminal-copy/export"),
    );
    release();
    await settled;
    if (change === "collapse") await editor.locator(":scope > summary").click();
    if (change === "navigation") {
      await chooseWorkspaceTask(page, "Points & I/O");
      await editor.locator(":scope > summary").click();
    }
    await expect(
      editor.getByRole("region", {
        name: "Reviewed local terminal copy",
        exact: true,
      }),
    ).toHaveCount(0);
    expect(downloads).toBe(0);
  });
}

test("an active existing input task retires a local terminal review", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seedTerminals(nativeScheduleWriteServer.directory),
    editor = await enterTerminals(page, f.id);
  await draftTerminal(editor);
  await reviewTerminal(editor);
  let release!: () => void, seen!: () => void;
  const gate = new Promise<void>((r) => (release = r)),
    arrived = new Promise<void>((r) => (seen = r));
  await page.route("**/native-application/input/source", async (route) => {
    const response = await route.fetch();
    seen();
    await gate;
    await route.fulfill({ response });
  });
  await page
    .getByLabel("Retained native input source", { exact: true })
    .selectOption(f.id);
  await arrived;
  await expect(editor).toContainText("Finish the active input operation");
  await expect(
    editor.getByRole("region", {
      name: "Reviewed local terminal copy",
      exact: true,
    }),
  ).toHaveCount(0);
  release();
  await expect(editor.getByLabel("Input to reassign")).toBeVisible();
});
