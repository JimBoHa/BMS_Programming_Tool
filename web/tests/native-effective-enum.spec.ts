import { test, expect } from "./nativeScheduleWriteFixture";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import {
  seed,
  enter,
  load,
  prepare,
  inspect,
  effective,
  python,
} from "./native-effective-enum-fixture";
import {
  chooseWorkspaceSurface,
  openNativeCompiler,
} from "./workspace-navigation";

for (const caf of [false, true]) {
  test(`${caf ? "CAF phone" : "new application"} compiles an actual merged Enum with exact review and artifact bytes`, async ({
    page,
    request,
    nativeScheduleWriteServer,
  }, info) => {
    if (caf) await page.setViewportSize({ width: 390, height: 844 });
    const ids = seed(nativeScheduleWriteServer.directory),
      { panel } = await enter(page, ids, caf ? "b" : "a", caf);
    await load(panel, caf ? "7" : "513");
    await expect(panel).toContainText("numeric maximum 65535");
    await expect(panel).toContainText("allowed states are unverified");
    let original = Buffer.alloc(0);
    await page.route("**/enum-default-compiler/preview", async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      original = await response.body();
      await route.fulfill({ response });
    });
    const reviewed = await prepare(panel);
    await expect(panel.locator("button.primary")).toHaveCount(1);
    const evidencePending = page.waitForEvent("download");
    await reviewed
      .getByRole("button", {
        name: "Save effective Enum review JSON",
        exact: true,
      })
      .click();
    expect(readFileSync((await (await evidencePending).path())!)).toEqual(
      original,
    );
    const pending = page.waitForEvent("download");
    await reviewed
      .getByRole("button", { name: "Save effective Enum copy", exact: true })
      .click();
    const filename = (await (await pending).path())!,
      proof = JSON.parse(original.toString());
    expect(
      createHash("sha256").update(readFileSync(filename)).digest("hex"),
    ).toBe(proof.output_sha256);
    const actual = JSON.parse(
      python(
        `
import json,sys
from pathlib import Path
from bms_tool.moi_identity import MoiIdentity
from bms_tool.application_store import ApplicationStore
from bms_tool.storage import Store
s=ApplicationStore(Store(sys.argv[1]));a=MoiIdentity(Path(sys.argv[2]).read_bytes());r=a.reader.records['controller/enum-1'];p=r['properties'][3113]
assert a.data[p['value_start_offset']:p['value_end_offset']]==b'\\x92\\xff\\xff\\x2f'
print(json.dumps({'code':a.reader.scalar(r,3113),'root_real':a.reader.scalar(a.root,900),'other_unsigned':a.reader.scalar(a.root,901),'states':a.reader.scalar(r,931),'receipts':len(s.receipts())}))
`,
        nativeScheduleWriteServer.directory,
        filename,
      ),
    );
    expect(actual).toEqual({
      code: 65535,
      root_real: 3.5,
      other_unsigned: 70000,
      states: 291,
      receipts: 0,
    });
    expect(proof.saved_settings_merged).toBe(true);
    expect(proof.field_transfer_enabled).toBe(false);
    expect(proof.enum_semantics_verified).toBe(false);
    await panel
      .getByLabel("Proposed effective Enum code", { exact: true })
      .focus();
    await expect(
      panel.getByLabel("Proposed effective Enum code", { exact: true }),
    ).toBeFocused();
    expect(
      await panel
        .getByLabel("Proposed effective Enum code", { exact: true })
        .evaluate((e) => Number.parseFloat(getComputedStyle(e).fontSize)),
    ).toBeGreaterThanOrEqual(14);
    await panel.scrollIntoViewIfNeeded();
    await page.screenshot({
      path: info.outputPath(
        caf ? "effective-enum-phone.png" : "effective-enum-desktop.png",
      ),
    });
    expect(
      (await (await request.get("/api/session")).json()).field_network_open,
    ).toBe(false);
  });
}

test("archive and effective raw drafts stay separate through modes, record and task navigation", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const ids = seed(nativeScheduleWriteServer.directory),
    { compiler, panel } = await enter(page, ids);
  await load(panel);
  await panel
    .getByLabel("Proposed effective Enum code", { exact: true })
    .fill("1e-");
  const modes = compiler.getByLabel("Enum default source", { exact: true });
  await modes.selectOption("archive");
  await compiler.getByLabel("Proposed Enum code", { exact: true }).fill(" 2e");
  await modes.selectOption("effective");
  await load(panel, "1e-");
  await panel
    .getByRole("button", { name: "Review effective Enum copy", exact: true })
    .click();
  await expect(panel.getByRole("alert")).toContainText("decimal Enum code");
  await panel
    .getByLabel("Proposed effective Enum code", { exact: true })
    .fill("65536");
  await panel
    .getByRole("button", { name: "Review effective Enum copy", exact: true })
    .click();
  await expect(panel.getByRole("alert")).toContainText("0 through 65535");
  await chooseWorkspaceSurface(page, "Library");
  await chooseWorkspaceSurface(page, "Workspace");
  await openNativeCompiler(page);
  await inspect(compiler);
  await effective(compiler);
  await load(panel, "65536");
  await panel
    .getByRole("button", { name: "Discard effective Enum draft", exact: true })
    .click();
  await expect(
    panel.getByLabel("Proposed effective Enum code", { exact: true }),
  ).toHaveValue("513");
  await modes.selectOption("archive");
  await expect(
    compiler.getByLabel("Proposed Enum code", { exact: true }),
  ).toHaveValue(" 2e");
});

for (const variant of ["unknown", "unverified"]) {
  test(`${variant} source leaves archive work intact without qualifying effective compilation`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const ids = seed(nativeScheduleWriteServer.directory),
      { compiler, panel } = await enter(page, ids, variant);
    await compiler
      .getByLabel("Enum default source", { exact: true })
      .selectOption("archive");
    await compiler.getByLabel("Proposed Enum code", { exact: true }).fill("1e");
    await effective(compiler);
    await panel
      .getByRole("button", { name: "Open saved Enum defaults", exact: true })
      .click();
    await expect(panel.getByRole("alert")).toBeVisible();
    await expect(
      panel.getByLabel("Proposed effective Enum code", { exact: true }),
    ).toHaveCount(0);
    await compiler
      .getByLabel("Enum default source", { exact: true })
      .selectOption("archive");
    await expect(
      compiler.getByLabel("Proposed Enum code", { exact: true }),
    ).toHaveValue("1e");
  });
}

for (const fault of [
  "merge",
  "vendor",
  "capacity",
  "duplicate",
  "authority",
  "archive",
]) {
  test(`altered effective source ${fault} cannot open an Enum editor`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const ids = seed(nativeScheduleWriteServer.directory),
      { panel } = await enter(page, ids);
    await page.route("**/enum-default-compiler/source", async (route) => {
      const response = await route.fetch({ maxRetries: 0 }),
        data = await response.json();
      if (fault === "merge") data.effective_sha256 = "0".repeat(64);
      if (fault === "vendor") data.identity["vendor-identifier"] = 99;
      if (fault === "capacity") data.fields[0].maximum_code = 4294967295;
      if (fault === "duplicate") data.fields.push(data.fields[0]);
      if (fault === "authority") data.field_transfer_enabled = true;
      if (fault === "archive") data.fields[0].archive_value = 2;
      await route.fulfill({ response, json: data });
    });
    await panel
      .getByRole("button", { name: "Open saved Enum defaults", exact: true })
      .click();
    await expect(panel.getByRole("alert")).toContainText(
      "differs from the selected original field",
    );
    await expect(
      panel.getByLabel("Proposed effective Enum code", { exact: true }),
    ).toHaveCount(0);
  });
}

for (const fault of ["before", "merge", "storage", "current-identity"]) {
  test(`altered effective review ${fault} cannot enable a download`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const ids = seed(nativeScheduleWriteServer.directory),
      { panel } = await enter(page, ids);
    await load(panel);
    await page.route("**/enum-default-compiler/preview", async (route) => {
      const response = await route.fetch({ maxRetries: 0 }),
        data = await response.json();
      if (fault === "before") data.edit.before_value = 2;
      if (fault === "merge") data.compilation.saved_settings_merged = false;
      if (fault === "storage") data.compilation.saved_storage.bytes = 4;
      if (fault === "current-identity") data.current_identity_verified = true;
      await route.fulfill({ response, json: data });
    });
    await panel
      .getByLabel("Proposed effective Enum code", { exact: true })
      .fill("65535");
    await panel
      .getByRole("button", { name: "Review effective Enum copy", exact: true })
      .click();
    await expect(panel.getByRole("alert")).toContainText(
      "differs from this exact merged source",
    );
    await expect(
      panel.getByRole("region", {
        name: "Reviewed effective Enum copy",
        exact: true,
      }),
    ).toHaveCount(0);
  });
}

for (const fault of ["body", "artifact", "review", "snapshot"]) {
  test(`altered effective export ${fault} retains the raw draft and saves no file`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const ids = seed(nativeScheduleWriteServer.directory),
      { panel } = await enter(page, ids);
    await load(panel);
    await prepare(panel, " 0007 ");
    let downloads = 0;
    page.on("download", () => downloads++);
    await page.route("**/enum-default-compiler/export", async (route) => {
      const response = await route.fetch({ maxRetries: 0 }),
        headers = response.headers();
      if (fault !== "body")
        headers[`x-studio-${fault}-sha256`] = "0".repeat(64);
      await route.fulfill({
        response,
        headers,
        body:
          fault === "body"
            ? Buffer.from("authored wrong bytes")
            : await response.body(),
      });
    });
    await panel
      .getByRole("button", { name: "Save effective Enum copy", exact: true })
      .click();
    await expect(panel.getByRole("alert")).toContainText(
      "differs from its source, review or artifact digest",
    );
    expect(downloads).toBe(0);
    await expect(
      panel.getByLabel("Proposed effective Enum code", { exact: true }),
    ).toHaveValue(" 0007 ");
  });
}

for (const phase of ["source", "preview", "export"]) {
  test(`late effective Enum ${phase} cannot survive mode A B A`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const ids = seed(nativeScheduleWriteServer.directory),
      { compiler, panel } = await enter(page, ids);
    if (phase !== "source") await load(panel);
    if (phase === "preview")
      await panel
        .getByLabel("Proposed effective Enum code", { exact: true })
        .fill("7");
    if (phase === "export") await prepare(panel, "7");
    let release!: () => void,
      started!: () => void,
      downloads = 0;
    const gate = new Promise<void>((resolve) => {
        release = resolve;
      }),
      received = new Promise<void>((resolve) => {
        started = resolve;
      });
    page.on("download", () => downloads++);
    await page.route(`**/enum-default-compiler/${phase}`, async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      started();
      await gate;
      await route.fulfill({ response });
    });
    try {
      await panel
        .getByRole("button", {
          name:
            phase === "source"
              ? "Open saved Enum defaults"
              : phase === "preview"
                ? "Review effective Enum copy"
                : "Save effective Enum copy",
          exact: true,
        })
        .click();
      await received;
      await compiler
        .getByLabel("Enum default source", { exact: true })
        .selectOption("archive");
      await effective(compiler);
      const settled = page.waitForResponse((response) =>
        response.url().endsWith(`/enum-default-compiler/${phase}`),
      );
      release();
      await settled;
      await expect(
        panel.getByRole("button", {
          name: "Open saved Enum defaults",
          exact: true,
        }),
      ).toBeVisible();
      await expect(
        panel.getByRole("region", {
          name: "Reviewed effective Enum copy",
          exact: true,
        }),
      ).toHaveCount(0);
      expect(downloads).toBe(0);
    } finally {
      release();
    }
  });
}

for (const phase of ["preview", "export"]) {
  for (const event of ["edit", "visibilitychange", "pagehide"]) {
    test(`late effective Enum ${phase} after ${event} cannot restore a review or save a file`, async ({
      page,
      nativeScheduleWriteServer,
    }) => {
      const ids = seed(nativeScheduleWriteServer.directory),
        { panel } = await enter(page, ids);
      await load(panel);
      if (phase === "export") await prepare(panel, "7");
      else
        await panel
          .getByLabel("Proposed effective Enum code", { exact: true })
          .fill("7");
      let release!: () => void,
        started!: () => void,
        downloads = 0;
      const gate = new Promise<void>((resolve) => {
          release = resolve;
        }),
        received = new Promise<void>((resolve) => {
          started = resolve;
        });
      page.on("download", () => downloads++);
      await page.route(`**/enum-default-compiler/${phase}`, async (route) => {
        const response = await route.fetch({ maxRetries: 0 });
        started();
        await gate;
        await route.fulfill({ response });
      });
      try {
        await panel
          .getByRole("button", {
            name:
              phase === "preview"
                ? "Review effective Enum copy"
                : "Save effective Enum copy",
            exact: true,
          })
          .click();
        await received;
        if (event === "edit")
          await panel
            .getByLabel("Proposed effective Enum code", { exact: true })
            .fill("1e");
        if (event === "visibilitychange")
          await page.evaluate(() =>
            document.dispatchEvent(new Event("visibilitychange")),
          );
        if (event === "pagehide")
          await page.evaluate(() =>
            window.dispatchEvent(new Event("pagehide")),
          );
        const settled = page.waitForResponse((response) =>
          response.url().endsWith(`/enum-default-compiler/${phase}`),
        );
        release();
        await settled;
        await expect(
          panel.getByRole("button", {
            name: "Review effective Enum copy",
            exact: true,
          }),
        ).toBeEnabled();
        await expect(
          panel.getByRole("region", {
            name: "Reviewed effective Enum copy",
            exact: true,
          }),
        ).toHaveCount(0);
        await expect(
          panel.getByLabel("Proposed effective Enum code", { exact: true }),
        ).toHaveValue(event === "edit" ? "1e" : "7");
        expect(downloads).toBe(0);
      } finally {
        release();
      }
    });
  }
}
