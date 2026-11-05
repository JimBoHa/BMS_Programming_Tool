import { test, expect } from "./nativeScheduleWriteFixture";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import {
  seed,
  enter,
  openRecord,
  prepare,
  python,
} from "./native-connection-removal-fixture";
import {
  chooseWorkspaceSurface,
  openNativeCompiler,
} from "./workspace-navigation";

const calls = new WeakMap<object, string[]>();
test.beforeEach(async ({ page }) => {
  const requests: string[] = [];
  calls.set(page, requests);
  page.on("request", (r) => {
    if (
      r.method() === "POST" &&
      /\/api\/bacnet\//.test(r.url()) &&
      !/\/inspection\//.test(r.url()) &&
      !/\/signal-default\/(source|sources)/.test(r.url())
    )
      requests.push(r.url());
  });
});
for (const effective of [false, true])
  test(`${effective ? "saved-effective" : "archive"} offline removal exports exact reviewed bytes on a compact workspace`, async ({
    page,
    nativeScheduleWriteServer,
    request,
  }, info) => {
    const f = seed(nativeScheduleWriteServer.directory);
    await page.setViewportSize({ width: 820, height: 1100 });
    const { editor } = await enter(page, f.id, effective);
    await expect(
      editor.getByLabel("Existing connection to remove", { exact: true }),
    ).toHaveValue("0");
    await editor
      .getByLabel("Existing connection to remove", { exact: true })
      .selectOption("1");
    let exact = Buffer.alloc(0);
    await page.route(
      "**/" +
        (effective ? "effective-" : "") +
        "connection-removal-copy/preview",
      async (route) => {
        const response = await route.fetch({ maxRetries: 0 });
        exact = await response.body();
        await route.fulfill({ response });
      },
    );
    const review = await prepare(editor),
      data = JSON.parse(exact.toString());
    await expect(review).toContainText("Connections: 3 → 2");
    await expect(editor).toContainText(
      "fallback or retained-value behavior is unverified",
    );
    await expect(editor.locator("button.primary")).toHaveCount(1);
    const evidence = page.waitForEvent("download");
    await review
      .getByRole("button", {
        name: "Save exact connection removal review",
        exact: true,
      })
      .click();
    expect(readFileSync((await (await evidence).path())!)).toEqual(exact);
    const downloading = page.waitForEvent("download");
    await review
      .getByRole("button", {
        name: "Save native connection removal copy",
        exact: true,
      })
      .click();
    const file = (await (await downloading).path())!;
    expect(createHash("sha256").update(readFileSync(file)).digest("hex")).toBe(
      data.output_sha256,
    );
    expect(
      python(
        `
from pathlib import Path
import sys
from bms_tool.application_store import ApplicationStore
from bms_tool.storage import Store
from bms_tool.moi_identity import MoiIdentity,sha
from tests.test_moi_wire_sources import REF,A,B
from tests.test_native_wire_compiler import BOOLEAN
s=ApplicationStore(Store(sys.argv[2]));_,files=s.load(sys.argv[3]);assert sha(files[3])==sys.argv[4]
old,new=MoiIdentity(files[3]),MoiIdentity(Path(sys.argv[1]).read_bytes());expected=old.reader.diagram(REF)['connections'];del expected[1]
for i,w in enumerate(expected):w['index']=i
assert new.reader.diagram(REF)['connections']==expected
assert len(new.reader.diagram(REF)['blocks'])==4
saved=sys.argv[5]=='true'
assert new.reader.scalar(new.reader.records[A],3113)==(42 if saved else 1)
assert new.reader.scalar(new.reader.records[B],3113)==(17 if saved else 2)
assert new.reader.scalar(new.reader.records[BOOLEAN],3113) is saved
assert len(s.receipts())==0
print('exact selected connection removed, source immutable, saved basis retained, no field intent')
`,
        file,
        nativeScheduleWriteServer.directory,
        f.id,
        f.archive.archive.sha256,
        String(effective),
      ),
    ).toContain("source immutable");
    const session = await (
      await request.get(nativeScheduleWriteServer.url + "/api/session")
    ).json();
    expect(session.field_network_open).toBe(false);
    expect(calls.get(page)).toEqual([]);
    await editor.scrollIntoViewIfNeeded();
    await page.screenshot({
      path: info.outputPath("native-removal-compact.png"),
    });
  });

test("operation, source and workspace navigation retain separate basis/index drafts and retire every review", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seed(nativeScheduleWriteServer.directory),
    { compiler, editor, operations } = await enter(page, f.id);
  await editor
    .getByLabel("Existing connection to remove", { exact: true })
    .selectOption("2");
  await prepare(editor);
  await operations
    .getByLabel("Native diagram operation", { exact: true })
    .selectOption("add");
  await operations
    .getByLabel("Native diagram operation", { exact: true })
    .selectOption("remove");
  await expect(
    editor.getByLabel("Existing connection to remove", { exact: true }),
  ).toHaveValue("2");
  await expect(
    editor.getByRole("region", {
      name: "Reviewed connection removal",
      exact: true,
    }),
  ).toHaveCount(0);
  await editor
    .getByLabel("Connection removal basis", { exact: true })
    .selectOption("effective");
  await editor
    .getByRole("button", { name: "Open connections for removal", exact: true })
    .click();
  await editor
    .getByLabel("Existing connection to remove", { exact: true })
    .selectOption("1");
  await prepare(editor);
  await compiler
    .getByLabel("Retained native backup", { exact: true })
    .selectOption(f.other);
  const other = await openRecord(page, compiler);
  await expect(
    other.editor.getByLabel("Connection removal basis", { exact: true }),
  ).toHaveValue("archive");
  await expect(
    other.editor.getByLabel("Existing connection to remove", { exact: true }),
  ).toHaveValue("0");
  await compiler
    .getByLabel("Retained native backup", { exact: true })
    .selectOption(f.id);
  const restored = await openRecord(page, compiler, true);
  await expect(
    restored.editor.getByLabel("Existing connection to remove", {
      exact: true,
    }),
  ).toHaveValue("1");
  await expect(
    restored.editor.getByRole("region", {
      name: "Reviewed connection removal",
      exact: true,
    }),
  ).toHaveCount(0);
  await chooseWorkspaceSurface(page, "Library");
  await chooseWorkspaceSurface(page, "Workspace");
  await openNativeCompiler(page);
  const again = await openRecord(page, compiler, true);
  await expect(
    again.editor.getByLabel("Existing connection to remove", { exact: true }),
  ).toHaveValue("1");
  await again.editor
    .getByLabel("Connection removal basis", { exact: true })
    .selectOption("archive");
  await again.editor
    .getByRole("button", { name: "Open connections for removal", exact: true })
    .click();
  await expect(
    again.editor.getByLabel("Existing connection to remove", { exact: true }),
  ).toHaveValue("2");
  await again.editor
    .getByRole("button", {
      name: "Discard connection removal selection",
      exact: true,
    })
    .click();
  await expect(
    again.editor.getByLabel("Existing connection to remove", { exact: true }),
  ).toHaveValue("0");
  expect(calls.get(page)).toEqual([]);
});

for (const effective of [false, true])
  test(`${effective ? "saved" : "archive"} empty and final connection have explicit local outcomes`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const f = seed(nativeScheduleWriteServer.directory),
      { compiler, editor } = await enter(page, f.empty, effective);
    await expect(editor).toContainText("No existing connection is recorded");
    await expect(
      editor.getByRole("button", {
        name: "Review connection removal",
        exact: true,
      }),
    ).toHaveCount(0);
    await compiler
      .getByLabel("Retained native backup", { exact: true })
      .selectOption(f.last);
    const last = await openRecord(page, compiler, effective);
    const review = await prepare(last.editor);
    await expect(review).toContainText("Connections: 1 → 0");
    await expect(last.editor).toContainText(
      "No continuation metadata is recorded",
    );
    const downloading = page.waitForEvent("download");
    await review
      .getByRole("button", {
        name: "Save native connection removal copy",
        exact: true,
      })
      .click();
    const file = (await (await downloading).path())!;
    expect(
      python(
        `
import sys
from pathlib import Path
from bms_tool.moi_identity import MoiIdentity
from tests.test_moi_wire_sources import REF
m=MoiIdentity(Path(sys.argv[1]).read_bytes());g=m.reader.diagram(REF)
assert g['connections']==[] and len(g['blocks'])==4
assert 3118 in m.reader.records[REF]['properties'] and 3384 not in m.reader.records[REF]['properties']
print('explicit empty array and all original blocks preserved')
`,
        file,
      ),
    ).toContain("all original blocks preserved");
    expect(calls.get(page)).toEqual([]);
  });

test("unsupported saved schema refuses effective removal while original archive remains usable", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seed(nativeScheduleWriteServer.directory),
    { editor } = await enter(page, f.unknown, true);
  await expect(editor.getByRole("alert")).toBeVisible();
  await expect(
    editor.getByRole("region", {
      name: "Reviewed connection removal",
      exact: true,
    }),
  ).toHaveCount(0);
  await editor
    .getByLabel("Connection removal basis", { exact: true })
    .selectOption("archive");
  await editor
    .getByRole("button", { name: "Open connections for removal", exact: true })
    .click();
  await prepare(editor);
  expect(calls.get(page)).toEqual([]);
});

for (const phase of ["preview", "export"] as const)
  for (const boundary of [
    "proposal",
    "basis",
    "operation",
    "source",
    "workspace",
    "pagehide",
    "hidden",
    "collapse",
  ] as const)
    test(`${phase} delayed response cannot survive ${boundary} A B A lifecycle`, async ({
      page,
      nativeScheduleWriteServer,
    }) => {
      const f = seed(nativeScheduleWriteServer.directory),
        opened = await enter(page, f.id);
      let { editor, operations } = opened;
      if (phase === "export") await prepare(editor);
      let release = () => {},
        started = () => {};
      const gate = new Promise<void>((r) => (release = r)),
        received = new Promise<void>((r) => (started = r));
      await page.route(
        "**/connection-removal-copy/" + phase,
        async (route) => {
          const response = await route.fetch({ maxRetries: 0 });
          started();
          await gate;
          await route.fulfill({ response });
        },
        { times: 1 },
      );
      const downloads: string[] = [];
      page.on("download", (d) => downloads.push(d.suggestedFilename()));
      try {
        await editor
          .getByRole("button", {
            name:
              phase === "preview"
                ? "Review connection removal"
                : "Save native connection removal copy",
            exact: true,
          })
          .click();
        await received;
        if (boundary === "proposal") {
          await editor
            .getByLabel("Existing connection to remove", { exact: true })
            .selectOption("1");
          await editor
            .getByLabel("Existing connection to remove", { exact: true })
            .selectOption("0");
        } else if (boundary === "basis") {
          await editor
            .getByLabel("Connection removal basis", { exact: true })
            .selectOption("effective");
          await editor
            .getByLabel("Connection removal basis", { exact: true })
            .selectOption("archive");
          await editor
            .getByRole("button", {
              name: "Open connections for removal",
              exact: true,
            })
            .click();
        } else if (boundary === "operation") {
          await operations
            .getByLabel("Native diagram operation", { exact: true })
            .selectOption("source");
          await operations
            .getByLabel("Native diagram operation", { exact: true })
            .selectOption("remove");
        } else if (boundary === "source") {
          await opened.compiler
            .getByLabel("Retained native backup", { exact: true })
            .selectOption(f.other);
          await opened.compiler
            .getByLabel("Retained native backup", { exact: true })
            .selectOption(f.id);
          ({ editor, operations } = await openRecord(page, opened.compiler));
        } else if (boundary === "workspace") {
          await chooseWorkspaceSurface(page, "Library");
          await chooseWorkspaceSurface(page, "Workspace");
          await openNativeCompiler(page);
          ({ editor, operations } = await openRecord(page, opened.compiler));
        } else if (boundary === "collapse") {
          await editor.locator(":scope > summary").click();
          await editor.locator(":scope > summary").click();
        } else {
          await page.evaluate((which) => {
            if (which === "pagehide")
              window.dispatchEvent(new Event("pagehide"));
            else {
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
            }
          }, boundary);
          await editor
            .getByRole("button", {
              name: "Open connections for removal",
              exact: true,
            })
            .click();
        }
        const finished = page.waitForResponse((r) =>
          r.url().endsWith("/connection-removal-copy/" + phase),
        );
        release();
        await (await finished).finished();
        await expect(
          editor.getByRole("region", {
            name: "Reviewed connection removal",
            exact: true,
          }),
        ).toHaveCount(0);
        await expect(
          editor.getByLabel("Existing connection to remove", { exact: true }),
        ).toHaveValue("0");
        expect(downloads).toEqual([]);
        expect(calls.get(page)).toEqual([]);
      } finally {
        release();
      }
    });

for (const phase of ["source", "preview"] as const)
  for (const effective of [false, true])
    test(`${effective ? "saved" : "archive"} substituted ${phase} authority is refused`, async ({
      page,
      nativeScheduleWriteServer,
    }) => {
      const f = seed(nativeScheduleWriteServer.directory);
      const endpoint =
        "**/" +
        (effective ? "effective-" : "") +
        "connection-removal-copy/" +
        phase;
      await page.route(
        endpoint,
        async (route) => {
          const response = await route.fetch({ maxRetries: 0 }),
            value = JSON.parse((await response.body()).toString());
          value.controller_write = true;
          await route.fulfill({ response, body: JSON.stringify(value) });
        },
        { times: 1 },
      );
      const { editor } = await enter(page, f.id, effective);
      if (phase === "preview")
        await editor
          .getByRole("button", {
            name: "Review connection removal",
            exact: true,
          })
          .click();
      await expect(editor.getByRole("alert")).toContainText("does not match");
      await expect(
        editor.getByRole("region", {
          name: "Reviewed connection removal",
          exact: true,
        }),
      ).toHaveCount(0);
      expect(calls.get(page)).toEqual([]);
    });

for (const fault of [
  "body",
  "Artifact",
  "Review",
  "Snapshot",
  "Source",
  "Compilation",
])
  test(`export refuses substituted ${fault} without a browser download`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const f = seed(nativeScheduleWriteServer.directory),
      { editor } = await enter(page, f.id);
    await prepare(editor);
    await page.route(
      "**/connection-removal-copy/export",
      async (route) => {
        const response = await route.fetch({ maxRetries: 0 }),
          headers = { ...response.headers() };
        if (fault === "body")
          await route.fulfill({
            response,
            body: Buffer.from("different native output"),
          });
        else {
          headers["x-studio-" + fault.toLowerCase() + "-sha256"] = "0".repeat(
            64,
          );
          await route.fulfill({ response, headers });
        }
      },
      { times: 1 },
    );
    const downloads: string[] = [];
    page.on("download", (d) => downloads.push(d.suggestedFilename()));
    await editor
      .getByRole("button", {
        name: "Save native connection removal copy",
        exact: true,
      })
      .click();
    await expect(editor.getByRole("alert")).toContainText(
      "differ from the reviewed local copy",
    );
    expect(downloads).toEqual([]);
    expect(calls.get(page)).toEqual([]);
  });

test("failed source keeps selected draft discardable and requires fresh review after recovery", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seed(nativeScheduleWriteServer.directory),
    { editor } = await enter(page, f.id);
  await editor
    .getByLabel("Existing connection to remove", { exact: true })
    .selectOption("2");
  await prepare(editor);
  await page.route(
    "**/connection-removal-copy/source",
    async (route) =>
      route.fulfill({
        status: 422,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Authored source unavailable" }),
      }),
    { times: 1 },
  );
  await editor
    .getByRole("button", { name: "Open connections for removal", exact: true })
    .click();
  await expect(editor.getByRole("alert")).toContainText(
    "Authored source unavailable",
  );
  await editor
    .getByRole("button", {
      name: "Discard connection removal selection",
      exact: true,
    })
    .click();
  await expect(
    editor.getByLabel("Existing connection to remove", { exact: true }),
  ).toHaveValue("0");
  await expect(
    editor.getByRole("region", {
      name: "Reviewed connection removal",
      exact: true,
    }),
  ).toHaveCount(0);
  expect(calls.get(page)).toEqual([]);
});

test("phone keyboard review keeps one primary action and labelled native ports", async ({
  page,
  nativeScheduleWriteServer,
  browserName,
}, info) => {
  const f = seed(nativeScheduleWriteServer.directory);
  await page.setViewportSize({ width: 390, height: 844 });
  const { editor } = await enter(page, f.id);
  const selection = editor.getByLabel("Existing connection to remove", {
    exact: true,
  });
  await selection.focus();
  await page.keyboard.press(browserName === "webkit" ? "Alt+Tab" : "Tab");
  await expect(
    editor.getByRole("button", {
      name: "Review connection removal",
      exact: true,
    }),
  ).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(
    editor.getByRole("region", {
      name: "Reviewed connection removal",
      exact: true,
    }),
  ).toContainText("Connections: 3 → 2");
  await expect(editor.locator("button.primary")).toHaveCount(1);
  expect((await selection.boundingBox())!.height).toBeGreaterThanOrEqual(36);
  await editor.scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath("native-removal-phone.png") });
  expect(calls.get(page)).toEqual([]);
});
