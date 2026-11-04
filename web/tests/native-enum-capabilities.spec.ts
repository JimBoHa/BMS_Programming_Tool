import { test, expect, type Page } from "./nativeScheduleWriteFixture";
import type { Locator } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { openNativeCompiler } from "./workspace-navigation";

function seed(directory: string) {
  const root = path.resolve("..");
  return JSON.parse(
    execFileSync(
      path.join(root, ".venv/bin/python"),
      [
        "-c",
        `
import base64,json,sys
from bms_tool.storage import Store
from bms_tool.application_store import ApplicationStore
from tests.test_native_signal_compiler import retained
from tests.test_moi_enum_defaults import enum_source
from tests.test_caf_native_correlation import caf_source
s=ApplicationStore(Store(sys.argv[1]))
files={3:enum_source(),11:b'Opaque schema',12:b'Opaque values'}
a=retained(s,files)
files[3]=enum_source(cid=529,compressed=False)
b=retained(s,files,target={'address':'10','router':'127.0.0.1:47919','dnet':200},source_identity_matches=False,source_identity_error='Authored incomplete acquisition identity',connector_config={'transport':'mstp','serial_port':'/dev/authored-only'})
files[3]=enum_source(cid=528,value=b'\\x21\\x01')
c=retained(s,files)
print(json.dumps({'a':a['id'],'b':b['id'],'c':c['id'],'caf':base64.b64encode(caf_source().original).decode()}))
`,
        directory,
      ],
      {
        cwd: root,
        env: {
          ...process.env,
          PYTHONPATH: [
            process.env.BMS_TEST_INSTALLED_TARGET || path.join(root, "backend"),
            root,
          ].join(path.delimiter),
        },
        encoding: "utf8",
      },
    ),
  );
}
async function inspect(compiler: Locator) {
  await compiler
    .getByRole("button", {
      name: "Inspect retained native backup",
      exact: true,
    })
    .click();
  const support = compiler.getByLabel("Native backup operation support", {
    exact: true,
  });
  await expect(support).toBeVisible();
  return support;
}
async function enter(page: Page, ids: any, caf = false) {
  await page.goto("/");
  if (caf) {
    const choosing = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: /^Open a CAF file/ }).click();
    await (
      await choosing
    ).setFiles({
      name: "enum-capability.caf",
      mimeType: "application/octet-stream",
      buffer: Buffer.from(ids.caf, "base64"),
    });
    await expect(
      page.getByLabel("Current CAF archive", { exact: true }),
    ).toHaveText("enum-capability.caf");
  } else
    await page
      .getByRole("button", { name: "New application", exact: true })
      .click();
  await openNativeCompiler(page);
  const compiler = page.getByRole("region", {
    name: "Native backup default compiler",
    exact: true,
  });
  await compiler
    .getByLabel("Retained native backup", { exact: true })
    .selectOption(caf ? ids.b : ids.a);
  return { compiler, support: await inspect(compiler) };
}
const row = (support: Locator) =>
  support.locator('[data-operation="enum-default-copy"]');

for (const caf of [false, true]) {
  test(`${caf ? "CAF phone" : "new application"} capability analysis shows an actual Enum copy without promoting semantics or field writes`, async ({
    page,
    request,
    nativeScheduleWriteServer,
  }, info) => {
    if (caf) await page.setViewportSize({ width: 390, height: 844 });
    const ids = seed(nativeScheduleWriteServer.directory),
      { compiler, support } = await enter(page, ids, caf);
    const records = compiler.getByLabel("Captured native record explorer", {
      exact: true,
    });
    await records.locator(":scope > summary").click();
    await records
      .getByRole("table", { name: "Captured native records", exact: true })
      .getByRole("row")
      .filter({ hasText: "controller/enum-1" })
      .getByRole("button", { name: "Inspect record", exact: true })
      .click();
    const draft = records.getByLabel("Proposed Enum code", { exact: true });
    await draft.fill("1e");
    await support.locator(":scope > summary").click();
    await expect(
      support
        .getByRole("table", { name: "Native backup operations", exact: true })
        .getByRole("row"),
    ).toHaveCount(25);
    await expect(row(support).locator("td").first()).toHaveText(
      "source qualified",
    );
    await expect(row(support)).toContainText(
      "membership and state meanings remain unverified",
    );
    await expect(row(support)).toContainText(
      "no executable mapping, Enum field transfer or physical acceptance",
    );
    await expect(
      support.locator('[data-operation="saved-settings"] td').first(),
    ).toHaveText("unsupported source");
    await expect(
      support.locator('[data-operation="general-logic"] td').first(),
    ).toHaveText("unavailable");
    await expect(draft).toHaveValue("1e");
    await expect(
      records.getByRole("region", {
        name: "Reviewed Enum archive copy",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      support.getByRole("button", { name: "Apply to controller", exact: true }),
    ).toHaveCount(0);
    await support
      .getByText("Operation qualification evidence", { exact: true })
      .click();
    await expect(support.locator("pre")).toContainText(
      '"archive_enum_default_count": 1',
    );
    await expect(support.locator("pre")).toContainText(
      '"enum_semantics_verified": false',
    );
    await support.locator(":scope > summary").focus();
    await expect(support.locator(":scope > summary")).toBeFocused();
    await row(support).scrollIntoViewIfNeeded();
    await page.screenshot({
      path: info.outputPath(
        caf ? "enum-capability-phone.png" : "enum-capability-desktop.png",
      ),
    });
    expect(
      (await (await request.get("/api/session")).json()).field_network_open,
    ).toBe(false);
  });
}

test("an Enum class with an actual Unsigned default does not qualify a typed Enum copy", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const ids = seed(nativeScheduleWriteServer.directory),
    { compiler } = await enter(page, ids);
  await compiler
    .getByLabel("Retained native backup", { exact: true })
    .selectOption(ids.c);
  const support = await inspect(compiler);
  await support.locator(":scope > summary").click();
  await expect(row(support).locator("td").first()).toHaveText(
    "unsupported source",
  );
  await expect(row(support)).toContainText(
    "No supported class 528/529 Enumerated Default Value",
  );
});

for (const altered of [
  "count",
  "semantics",
  "status",
  "profile",
  "missing-row",
  "duplicate-row",
]) {
  test(`substituted Enum capability ${altered} is refused while original records stay readable`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const ids = seed(nativeScheduleWriteServer.directory),
      { compiler, support } = await enter(page, ids);
    await page.route(
      "**/native-application/inspection/capabilities",
      async (route) => {
        const response = await route.fetch({ maxRetries: 0 }),
          data = await response.json();
        if (altered === "count")
          data.qualification.archive_enum_default_count = "1";
        if (altered === "semantics")
          data.qualification.enum_semantics_verified = true;
        if (altered === "status")
          data.operations.find(
            (r: any) => r.id === "enum-default-copy",
          ).status = "preflight-required";
        if (altered === "profile")
          data.capability_profile = "native-backup-operation-capabilities/8";
        if (altered === "missing-row")
          data.operations = data.operations.filter(
            (r: any) => r.id !== "enum-default-copy",
          );
        if (altered === "duplicate-row")
          data.operations[8] = data.operations[7];
        await route.fulfill({ response, json: data });
      },
    );
    await support.locator(":scope > summary").click();
    await expect(support.getByRole("alert")).toContainText(
      "differs from the selected source",
    );
    await expect(support.getByRole("table")).toHaveCount(0);
    await expect(
      compiler.getByLabel("Native archive inspection source", { exact: true }),
    ).toBeVisible();
    const records = compiler.getByLabel("Captured native record explorer", {
      exact: true,
    });
    await records.locator(":scope > summary").click();
    await expect(
      records.getByRole("table", {
        name: "Captured native records",
        exact: true,
      }),
    ).toContainText("controller/enum-1");
  });
}
