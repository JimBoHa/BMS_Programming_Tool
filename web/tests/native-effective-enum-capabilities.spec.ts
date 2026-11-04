import { test, expect } from "./nativeScheduleWriteFixture";
import type { Locator } from "@playwright/test";
import { seed, enter, load, python } from "./native-effective-enum-fixture";

const supportFor = (compiler: Locator) =>
  compiler.getByLabel("Native backup operation support", { exact: true });
const effectiveRow = (support: Locator) =>
  support.locator('[data-operation="effective-enum-compile"]');
async function analyze(support: Locator) {
  await support.locator(":scope > summary").click();
  return support.getByRole("table", {
    name: "Native backup operations",
    exact: true,
  });
}

for (const caf of [false, true]) {
  test(`${caf ? "CAF phone" : "new application"} displays actual effective Enum capability without losing unfinished text`, async ({
    page,
    request,
    nativeScheduleWriteServer,
  }, info) => {
    if (caf) await page.setViewportSize({ width: 390, height: 844 });
    const ids = seed(nativeScheduleWriteServer.directory),
      { compiler, panel } = await enter(page, ids, caf ? "b" : "a", caf),
      support = supportFor(compiler);
    await load(panel, caf ? "7" : "513");
    const input = panel.getByLabel("Proposed effective Enum code", {
      exact: true,
    });
    await input.fill("1e");
    const table = await analyze(support);
    await expect(table.getByRole("row")).toHaveCount(25);
    await expect(effectiveRow(support).locator("td").first()).toHaveText(
      "source qualified",
    );
    await expect(effectiveRow(support)).toContainText(
      "1 have captured fixed numeric storage",
    );
    await expect(effectiveRow(support)).toContainText(
      "membership and state meanings remain unverified",
    );
    await expect(effectiveRow(support)).toContainText(
      "No Enum field transfer is prepared",
    );
    await expect(input).toHaveValue("1e");
    await expect(
      panel.getByRole("region", {
        name: "Reviewed effective Enum copy",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      support.getByRole("button", { name: "Apply to controller", exact: true }),
    ).toHaveCount(0);
    await support
      .getByText("Operation qualification evidence", { exact: true })
      .click();
    for (const text of [
      '"effective_enum_default_count": 1',
      '"effective_enum_fixed_storage_count": 1',
      '"effective_enum_unknown_storage_count": 0',
      '"effective_enum_default_error": null',
      '"enum_semantics_verified": false',
    ])
      await expect(support.locator("pre")).toContainText(text);
    await support.locator(":scope > summary").focus();
    await expect(support.locator(":scope > summary")).toBeFocused();
    await effectiveRow(support).scrollIntoViewIfNeeded();
    await page.screenshot({
      path: info.outputPath(
        caf
          ? "effective-enum-capability-phone.png"
          : "effective-enum-capability-desktop.png",
      ),
    });
    expect(
      (await (await request.get("/api/session")).json()).field_network_open,
    ).toBe(false);
    const receipts = python(
      `
import json,sys
from bms_tool.storage import Store
from bms_tool.application_store import ApplicationStore
print(json.dumps(ApplicationStore(Store(sys.argv[1])).receipts()))
`,
      nativeScheduleWriteServer.directory,
    );
    expect(JSON.parse(receipts)).toEqual([]);
  });
}

for (const variant of ["unknown", "unverified"]) {
  test(`${variant} saved source retains archive Enum copy while effective compilation stays unsupported`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const ids = seed(nativeScheduleWriteServer.directory),
      { compiler } = await enter(page, ids, variant),
      support = supportFor(compiler);
    await analyze(support);
    await expect(effectiveRow(support).locator("td").first()).toHaveText(
      "unsupported source",
    );
    await expect(
      support.locator('[data-operation="enum-default-copy"] td').first(),
    ).toHaveText("source qualified");
    await expect(
      support.locator('[data-operation="saved-settings"] td').first(),
    ).toHaveText(
      variant === "unknown" ? "unsupported source" : "source qualified",
    );
    await support
      .getByText("Operation qualification evidence", { exact: true })
      .click();
    await expect(support.locator("pre")).toContainText(
      '"effective_enum_default_count": 0',
    );
    await expect(support.locator("pre")).not.toContainText(
      '"effective_enum_default_error": null',
    );
    await expect(
      compiler.getByLabel("Native archive inspection source", { exact: true }),
    ).toBeVisible();
  });
}

test("a missing selected fixed slot retains only local UInt32 representation qualification", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const ids = seed(nativeScheduleWriteServer.directory);
  ids.noFixed = JSON.parse(
    python(
      `
import json,sys
from bms_tool.storage import Store
from bms_tool.application_store import ApplicationStore
from tests.test_moi_effective_enum import enum_files
from tests.test_native_signal_compiler import retained
print(json.dumps(retained(ApplicationStore(Store(sys.argv[1])),enum_files(slot=False))['id']))
`,
      nativeScheduleWriteServer.directory,
    ),
  );
  const { compiler } = await enter(page, ids, "noFixed"),
    support = supportFor(compiler);
  await analyze(support);
  await expect(effectiveRow(support).locator("td").first()).toHaveText(
    "source qualified",
  );
  await expect(effectiveRow(support)).toContainText(
    "0 have captured fixed numeric storage",
  );
  await expect(effectiveRow(support)).toContainText(
    "only UInt32 representation is checked",
  );
  await support
    .getByText("Operation qualification evidence", { exact: true })
    .click();
  await expect(support.locator("pre")).toContainText(
    '"effective_enum_unknown_storage_count": 1',
  );
});

for (const altered of [
  "count-type",
  "negative",
  "overflow",
  "partition",
  "error",
  "identity",
  "raw-count",
  "merge-source",
  "merge-static",
  "merge-dynamic",
  "file-static",
  "file-dynamic",
  "file-size",
  "status",
  "missing-row",
  "duplicate-row",
  "profile",
]) {
  test(`substituted effective Enum capability ${altered} cannot promote an accepted table`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const ids = seed(nativeScheduleWriteServer.directory),
      { compiler, panel } = await enter(page, ids),
      support = supportFor(compiler);
    await load(panel);
    const input = panel.getByLabel("Proposed effective Enum code", {
      exact: true,
    });
    await input.fill("65536");
    await page.route(
      "**/native-application/inspection/capabilities",
      async (route) => {
        const response = await route.fetch({ maxRetries: 0 }),
          data = await response.json(),
          q = data.qualification;
        if (altered === "count-type") q.effective_enum_default_count = "1";
        if (altered === "negative") q.effective_enum_fixed_storage_count = -1;
        if (altered === "overflow") q.effective_enum_default_count = 4097;
        if (altered === "partition") q.effective_enum_unknown_storage_count = 1;
        if (altered === "error")
          q.effective_enum_default_error = "Authored contradiction";
        if (altered === "identity") q.recorded_identity_verified = false;
        if (altered === "raw-count") q.archive_enum_default_count = 2;
        if (altered === "merge-source")
          q.parameter_merge.source_sha256 = "0".repeat(64);
        if (altered === "merge-static")
          q.parameter_merge.static_sha256 = "0".repeat(64);
        if (altered === "merge-dynamic")
          q.parameter_merge.dynamic_sha256 = "0".repeat(64);
        if (altered === "file-static") data.files["11"].sha256 = "0".repeat(64);
        if (altered === "file-dynamic")
          data.files["12"].sha256 = "0".repeat(64);
        if (altered === "file-size") data.files["11"].bytes += 1;
        if (altered === "status")
          data.operations.find(
            (row: any) => row.id === "effective-enum-compile",
          ).status = "preflight-required";
        if (altered === "missing-row")
          data.operations = data.operations.filter(
            (row: any) => row.id !== "effective-enum-compile",
          );
        if (altered === "duplicate-row")
          data.operations[12] = data.operations[11];
        if (altered === "profile")
          data.capability_profile = "native-backup-operation-capabilities/9";
        await route.fulfill({ response, json: data });
      },
    );
    await support.locator(":scope > summary").click();
    await expect(support.getByRole("alert")).toContainText(
      "differs from the selected source",
    );
    await expect(support.getByRole("table")).toHaveCount(0);
    await expect(input).toHaveValue("65536");
    await expect(
      panel.getByRole("region", {
        name: "Reviewed effective Enum copy",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      compiler.getByLabel("Native archive inspection source", { exact: true }),
    ).toBeVisible();
  });
}
