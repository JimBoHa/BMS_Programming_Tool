import { test, expect } from "./nativeScheduleWriteFixture";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import {
  seed,
  enter,
  prepare,
  openRecord,
} from "./native-effective-connection-fixture";
import { python, a, d } from "./native-connection-fixture";
import {
  chooseWorkspaceSurface,
  openNativeCompiler,
} from "./workspace-navigation";
import { nativeDefaultPeer } from "./native-default-peer";
import { freePort } from "./workflow-peer";

const calls = new WeakMap<object, string[]>();
test.beforeEach(async ({ page }) => {
  const rows: string[] = [];
  calls.set(page, rows);
  page.on("request", (r) => {
    if (
      r.method() === "POST" &&
      /\/api\/bacnet\//.test(r.url()) &&
      !/\/inspection\//.test(r.url()) &&
      !/\/signal-default\/(source|sources)/.test(r.url())
    )
      rows.push(r.url());
  });
});

test("saved-effective connection exports exact review and saved values with one new literal edge", async ({
  page,
  nativeScheduleWriteServer,
  request,
}, info) => {
  const f = seed(nativeScheduleWriteServer.directory);
  await page.setViewportSize({ width: 820, height: 1100 });
  const { editor } = await enter(page, f.id);
  await expect(editor).toContainText(
    "3 saved application parameters merged before the connection addition",
  );
  await expect(editor).toContainText("not current controller readings");
  let exact = Buffer.alloc(0);
  await page.route("**/effective-connection-copy/preview", async (route) => {
    const response = await route.fetch({ maxRetries: 0 });
    exact = await response.body();
    await route.fulfill({ response });
  });
  const reviewed = await prepare(editor),
    data = JSON.parse(exact.toString());
  const evidence = page.waitForEvent("download");
  await reviewed
    .getByRole("button", {
      name: "Save exact effective connection review",
      exact: true,
    })
    .click();
  expect(readFileSync((await (await evidence).path())!)).toEqual(exact);
  const downloading = page.waitForEvent("download");
  await reviewed
    .getByRole("button", {
      name: "Save effective connection compilation",
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
from bms_tool.moi_identity import MoiIdentity,sha
from bms_tool.application_store import ApplicationStore
from bms_tool.storage import Store
from tests.test_moi_wire_sources import REF,A,B
from tests.test_native_wire_compiler import BOOLEAN
s=ApplicationStore(Store(sys.argv[2]));_,files=s.load(sys.argv[3]);assert sha(files[3])==sys.argv[4]
r=MoiIdentity(Path(sys.argv[1]).read_bytes()).reader
assert r.scalar(r.records[A],3113)==42 and r.scalar(r.records[B],3113)==17
assert r.scalar(r.records[BOOLEAN],3113) is True
assert len(r.diagram(REF)['connections'])==2
assert r.diagram(REF)['connections'][-1]['target_ref']==REF+'.2_13'
assert not s.receipts()
print('saved values, one new connection, original source, no field receipt')
`,
      file,
      nativeScheduleWriteServer.directory,
      f.id,
      f.archive.sha256,
    ).trim(),
  ).toBe("saved values, one new connection, original source, no field receipt");
  expect(calls.get(page)).toEqual([]);
  expect(
    (await (await request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
  await editor.scrollIntoViewIfNeeded();
  await page.screenshot({
    path: info.outputPath("native-effective-connection-820.png"),
  });
});

test("archive and effective bases retain independent drafts through task navigation and retire every old review", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seed(nativeScheduleWriteServer.directory),
    { compiler, editor } = await enter(page, f.id);
  await prepare(editor);
  const basis = editor.getByLabel("Native connection basis", { exact: true });
  await basis.selectOption("archive");
  await editor
    .getByRole("button", {
      name: "Open native connection candidates",
      exact: true,
    })
    .click();
  await expect(
    editor.getByLabel("Unused native destination", { exact: true }),
  ).toHaveValue("");
  await expect(
    editor.getByRole("region", {
      name: "Reviewed saved connection compilation",
      exact: true,
    }),
  ).toHaveCount(0);
  await editor
    .getByLabel("Unused native destination", { exact: true })
    .selectOption(d);
  await editor
    .getByRole("button", { name: "Review native connection copy", exact: true })
    .click();
  await expect(
    editor.getByRole("region", {
      name: "Reviewed native connection copy",
      exact: true,
    }),
  ).toBeVisible();
  await basis.selectOption("effective");
  await editor
    .getByRole("button", {
      name: "Open saved connection candidates",
      exact: true,
    })
    .click();
  await expect(
    editor.getByLabel("Unused native destination", { exact: true }),
  ).toHaveValue(d);
  await expect(
    editor.getByRole("region", {
      name: "Reviewed saved connection compilation",
      exact: true,
    }),
  ).toHaveCount(0);
  await chooseWorkspaceSurface(page, "Library");
  await chooseWorkspaceSurface(page, "Workspace");
  await openNativeCompiler(page);
  const again = await openRecord(page, compiler);
  await expect(
    again.editor.getByLabel("Native connection basis", { exact: true }),
  ).toHaveValue("effective");
  await expect(
    again.editor.getByLabel("Unused native destination", { exact: true }),
  ).toHaveValue(d);
  await again.editor
    .getByRole("button", {
      name: "Discard native connection draft",
      exact: true,
    })
    .click();
  await expect(
    again.editor.getByLabel("Unused native destination", { exact: true }),
  ).toHaveValue("");
  await again.editor
    .getByLabel("Native connection basis", { exact: true })
    .selectOption("archive");
  await again.editor
    .getByRole("button", {
      name: "Open native connection candidates",
      exact: true,
    })
    .click();
  await expect(
    again.editor.getByLabel("Unused native destination", { exact: true }),
  ).toHaveValue(d);
  expect(calls.get(page)).toEqual([]);
});

test("unknown saved schema refuses effective compilation and keeps original archive addition available", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seed(nativeScheduleWriteServer.directory),
    { editor } = await enter(page, f.unknown);
  await expect(editor.getByRole("alert")).toContainText(
    "Static parameter directory",
  );
  await expect(
    editor.getByLabel("Unused native destination", { exact: true }),
  ).toHaveCount(0);
  await editor
    .getByLabel("Native connection basis", { exact: true })
    .selectOption("archive");
  await editor
    .getByRole("button", {
      name: "Open native connection candidates",
      exact: true,
    })
    .click();
  await editor
    .getByLabel("Unused native destination", { exact: true })
    .selectOption(d);
  await editor
    .getByRole("button", { name: "Review native connection copy", exact: true })
    .click();
  await expect(
    editor.getByRole("region", {
      name: "Reviewed native connection copy",
      exact: true,
    }),
  ).toContainText("New connection: 0, 85, 3, 7000");
  expect(calls.get(page)).toEqual([]);
});

for (const boundary of ["basis", "pagehide", "hidden"] as const)
  test(`${boundary} ABA retires a delayed saved-effective connection review`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const f = seed(nativeScheduleWriteServer.directory),
      { editor } = await enter(page, f.id);
    await editor
      .getByLabel("Unused native destination", { exact: true })
      .selectOption(d);
    let release = () => {},
      started = () => {};
    const gate = new Promise<void>((r) => (release = r)),
      received = new Promise<void>((r) => (started = r));
    await page.route(
      "**/effective-connection-copy/preview",
      async (route) => {
        const response = await route.fetch({ maxRetries: 0 });
        started();
        await gate;
        await route.fulfill({ response });
      },
      { times: 1 },
    );
    try {
      await editor
        .getByRole("button", {
          name: "Review saved connection compilation",
          exact: true,
        })
        .click();
      await received;
      if (boundary === "basis") {
        await editor
          .getByLabel("Native connection basis", { exact: true })
          .selectOption("archive");
        await editor
          .getByLabel("Native connection basis", { exact: true })
          .selectOption("effective");
      } else
        await page.evaluate((which) => {
          if (which === "pagehide") window.dispatchEvent(new Event("pagehide"));
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
          name: "Open saved connection candidates",
          exact: true,
        })
        .click();
      const delivered = page.waitForResponse((r) =>
        r.url().endsWith("/effective-connection-copy/preview"),
      );
      release();
      await (await delivered).finished();
      await page.evaluate(
        () =>
          new Promise<void>((resolve) =>
            requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
          ),
      );
      await expect(
        editor.getByRole("region", {
          name: "Reviewed saved connection compilation",
          exact: true,
        }),
      ).toHaveCount(0);
      await expect(
        editor.getByLabel("Unused native destination", { exact: true }),
      ).toHaveValue(d);
      expect(calls.get(page)).toEqual([]);
    } finally {
      release();
    }
  });

test("basis ABA retires a delayed effective artifact without losing its destination draft", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seed(nativeScheduleWriteServer.directory),
    { editor } = await enter(page, f.id),
    reviewed = await prepare(editor);
  const downloads: string[] = [];
  page.on("download", (r) => downloads.push(r.suggestedFilename()));
  let release = () => {},
    started = () => {};
  const gate = new Promise<void>((r) => (release = r)),
    received = new Promise<void>((r) => (started = r));
  await page.route(
    "**/effective-connection-copy/export",
    async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      started();
      await gate;
      await route.fulfill({ response });
    },
    { times: 1 },
  );
  try {
    await reviewed
      .getByRole("button", {
        name: "Save effective connection compilation",
        exact: true,
      })
      .click();
    await received;
    await editor
      .getByLabel("Native connection basis", { exact: true })
      .selectOption("archive");
    await editor
      .getByLabel("Native connection basis", { exact: true })
      .selectOption("effective");
    await editor
      .getByRole("button", {
        name: "Open saved connection candidates",
        exact: true,
      })
      .click();
    const delivered = page.waitForResponse((r) =>
      r.url().endsWith("/effective-connection-copy/export"),
    );
    release();
    await (await delivered).finished();
    await page.evaluate(
      () =>
        new Promise<void>((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
        ),
    );
    await expect(
      editor.getByLabel("Unused native destination", { exact: true }),
    ).toHaveValue(d);
    await expect(
      editor.getByRole("region", {
        name: "Reviewed saved connection compilation",
        exact: true,
      }),
    ).toHaveCount(0);
    expect(downloads).toEqual([]);
    expect(calls.get(page)).toEqual([]);
  } finally {
    release();
  }
});

test("saved-file source changes retire reviews and preserve each archive's own proposal", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seed(nativeScheduleWriteServer.directory),
    { compiler, editor } = await enter(page, f.id);
  await prepare(editor);
  await compiler
    .getByLabel("Retained native backup", { exact: true })
    .selectOption(f.changed);
  const changed = await openRecord(page, compiler);
  await expect(
    changed.editor.getByLabel("Unused native destination", { exact: true }),
  ).toHaveValue("");
  await compiler
    .getByLabel("Retained native backup", { exact: true })
    .selectOption(f.id);
  const original = await openRecord(page, compiler);
  await expect(
    original.editor.getByLabel("Unused native destination", { exact: true }),
  ).toHaveValue(d);
  await expect(
    original.editor.getByRole("region", {
      name: "Reviewed saved connection compilation",
      exact: true,
    }),
  ).toHaveCount(0);
  expect(calls.get(page)).toEqual([]);
});

test("wrong effective proof and corrupted file cannot download a compilation", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seed(nativeScheduleWriteServer.directory),
    { editor } = await enter(page, f.id);
  const downloads: string[] = [];
  page.on("download", (r) => downloads.push(r.suggestedFilename()));
  await page.route(
    "**/effective-connection-copy/preview",
    async (route) => {
      const response = await route.fetch({ maxRetries: 0 }),
        data = JSON.parse((await response.body()).toString());
      data.compilation.connection_edit.source_sha256 = f.archive.sha256;
      await route.fulfill({ response, body: JSON.stringify(data) });
    },
    { times: 1 },
  );
  await editor
    .getByLabel("Unused native destination", { exact: true })
    .selectOption(d);
  await editor
    .getByRole("button", {
      name: "Review saved connection compilation",
      exact: true,
    })
    .click();
  await expect(editor.getByRole("alert")).toContainText("exact proposal");
  const reviewed = await prepare(editor);
  await page.route(
    "**/effective-connection-copy/export",
    async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      await route.fulfill({
        response,
        body: Buffer.from("wrong native compilation"),
      });
    },
    { times: 1 },
  );
  await reviewed
    .getByRole("button", {
      name: "Save effective connection compilation",
      exact: true,
    })
    .click();
  await expect(editor.getByRole("alert")).toContainText(
    "output bytes or export proof differ",
  );
  expect(downloads).toEqual([]);
  expect(calls.get(page)).toEqual([]);
});

test("phone keyboard review keeps one primary save action for the selected effective input", async ({
  page,
  nativeScheduleWriteServer,
  browserName,
}, info) => {
  const f = seed(nativeScheduleWriteServer.directory);
  await page.setViewportSize({ width: 390, height: 844 });
  const { editor } = await enter(page, f.id),
    destination = editor.getByLabel("Unused native destination", {
      exact: true,
    });
  await destination.selectOption(d);
  await destination.focus();
  await page.keyboard.press(browserName === "webkit" ? "Alt+Tab" : "Tab");
  await expect(
    editor.getByRole("button", {
      name: "Review saved connection compilation",
      exact: true,
    }),
  ).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(
    editor.getByRole("region", {
      name: "Reviewed saved connection compilation",
      exact: true,
    }),
  ).toContainText("New connection: 0, 85, 3, 7000");
  await expect(editor.locator("button.primary")).toHaveCount(1);
  await editor.scrollIntoViewIfNeeded();
  await page.screenshot({
    path: info.outputPath("native-effective-connection-phone.png"),
  });
  expect(calls.get(page)).toEqual([]);
});

test("routed selected controller adds no BACnet request during effective local compilation", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seed(nativeScheduleWriteServer.directory),
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
    await openNativeCompiler(page);
    const compiler = page.getByRole("region", {
      name: "Native backup default compiler",
      exact: true,
    });
    await compiler
      .getByLabel("Retained native backup", { exact: true })
      .selectOption(f.id);
    const { editor } = await openRecord(page, compiler),
      before = await peer.command("stats"),
      reviewed = await prepare(editor);
    const downloading = page.waitForEvent("download");
    await reviewed
      .getByRole("button", {
        name: "Save effective connection compilation",
        exact: true,
      })
      .click();
    await downloading;
    const after = await peer.command("stats");
    expect(after.request_types).toEqual(before.request_types);
    expect(after.events).toEqual(before.events);
  } finally {
    peer.close();
  }
});
