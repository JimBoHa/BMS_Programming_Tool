import { test, expect } from "./nativeScheduleWriteFixture";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import {
  seed,
  enter,
  prepare,
  openRecord,
  python,
  ref,
  a,
  b,
  d,
} from "./native-connection-fixture";
import {
  chooseWorkspaceSurface,
  openNativeCompiler,
} from "./workspace-navigation";
import { nativeDefaultPeer } from "./native-default-peer";
import { freePort } from "./workflow-peer";

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

test("offline matching connection exports exact reviewed bytes and keeps original archives untouched on compact screens", async ({
  page,
  nativeScheduleWriteServer,
  request,
}, info) => {
  const f = seed(nativeScheduleWriteServer.directory);
  await page.setViewportSize({ width: 820, height: 1100 });
  const { editor } = await enter(page, f.a);
  await expect(
    editor.getByLabel("Native connection source", { exact: true }),
  ).toHaveValue(a);
  await expect(
    editor.getByLabel("Unused native destination", { exact: true }),
  ).toHaveValue("");
  await expect(
    editor.getByRole("button", {
      name: "Review native connection copy",
      exact: true,
    }),
  ).toBeDisabled();
  for (const label of [
    "Native connection prototype",
    "Native connection source",
    "Unused native destination",
  ])
    expect(
      (await editor.getByLabel(label, { exact: true }).boundingBox())!.height,
    ).toBeGreaterThanOrEqual(36);
  let exact = Buffer.alloc(0);
  await page.route("**/connection-copy/preview", async (route) => {
    const response = await route.fetch({ maxRetries: 0 });
    exact = await response.body();
    await route.fulfill({ response });
  });
  const reviewed = await prepare(editor),
    data = JSON.parse(exact.toString());
  const evidence = page.waitForEvent("download");
  await reviewed
    .getByRole("button", {
      name: "Save exact native connection review",
      exact: true,
    })
    .click();
  expect(readFileSync((await (await evidence).path())!)).toEqual(exact);
  const downloading = page.waitForEvent("download");
  await reviewed
    .getByRole("button", { name: "Save native connection copy", exact: true })
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
from bms_tool.moi_identity import MoiIdentity
from bms_tool.moi_identity import sha
from bms_tool.application_store import ApplicationStore
from bms_tool.storage import Store
from tests.test_moi_wire_sources import REF
s=ApplicationStore(Store(sys.argv[2]));_,files=s.load(sys.argv[3])
assert sha(files[3])==sys.argv[4]
old=MoiIdentity(files[3]);new=MoiIdentity(Path(sys.argv[1]).read_bytes())
assert len(old.reader.diagram(REF)['connections'])==1
assert new.reader.diagram(REF)['connections'][-1]=={'index':1,'source_ref':REF+'.2_10','source_port':85,'target_ref':REF+'.2_13','target_port':7000}
assert len(s.receipts())==0
print('one new connection, original retained, no field receipt')
`,
      file,
      nativeScheduleWriteServer.directory,
      f.a,
      f.source.source_sha256,
    ).trim(),
  ).toBe("one new connection, original retained, no field receipt");
  await expect(editor.getByRole("status")).toContainText(
    "Saved reviewed local native connection copy",
  );
  expect(calls.get(page)).toEqual([]);
  expect(
    (await (await request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
  await editor.scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath("native-connection-820.png") });
});

test("operation and workspace navigation preserve each local draft while retiring reviews", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seed(nativeScheduleWriteServer.directory),
    { compiler, editor, operations } = await enter(page, f.a);
  await prepare(editor);
  await operations
    .getByLabel("Native diagram operation", { exact: true })
    .selectOption("source");
  const old = operations.getByLabel("Native archive wire source copy", {
    exact: true,
  });
  await old.locator(":scope > summary").click();
  await old
    .getByRole("button", { name: "Open native wire sources", exact: true })
    .click();
  await expect(
    old.getByLabel("Replacement native source", { exact: true }),
  ).toHaveValue(a);
  await operations
    .getByLabel("Native diagram operation", { exact: true })
    .selectOption("add");
  await expect(
    editor.getByLabel("Unused native destination", { exact: true }),
  ).toHaveValue(d);
  await expect(
    editor.getByRole("region", {
      name: "Reviewed native connection copy",
      exact: true,
    }),
  ).toHaveCount(0);
  await chooseWorkspaceSurface(page, "Library");
  await chooseWorkspaceSurface(page, "Workspace");
  await openNativeCompiler(page);
  const reopened = await openRecord(page, compiler);
  await expect(
    reopened.operations.getByLabel("Native diagram operation", { exact: true }),
  ).toHaveValue("add");
  await expect(
    reopened.editor.getByLabel("Unused native destination", { exact: true }),
  ).toHaveValue(d);
  await expect(
    reopened.editor.getByRole("region", {
      name: "Reviewed native connection copy",
      exact: true,
    }),
  ).toHaveCount(0);
  await reopened.editor
    .getByRole("button", {
      name: "Discard native connection draft",
      exact: true,
    })
    .click();
  await expect(
    reopened.editor.getByLabel("Unused native destination", { exact: true }),
  ).toHaveValue("");
  expect(calls.get(page)).toEqual([]);
});

test("prototype selection retains separate source and destination drafts", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seed(nativeScheduleWriteServer.directory),
    { editor } = await enter(page, f.multi);
  const prototype = editor.getByLabel("Native connection prototype", {
    exact: true,
  });
  await editor
    .getByLabel("Unused native destination", { exact: true })
    .selectOption(d);
  await prototype.selectOption("1");
  await expect(
    editor.getByLabel("Native connection source", { exact: true }),
  ).toHaveValue(b);
  await editor
    .getByLabel("Native connection source", { exact: true })
    .selectOption(a);
  await editor
    .getByLabel("Unused native destination", { exact: true })
    .selectOption(d);
  await prototype.selectOption("0");
  await expect(
    editor.getByLabel("Unused native destination", { exact: true }),
  ).toHaveValue(d);
  await prototype.selectOption("1");
  await expect(
    editor.getByLabel("Native connection source", { exact: true }),
  ).toHaveValue(a);
  await expect(
    editor.getByLabel("Unused native destination", { exact: true }),
  ).toHaveValue(d);
  expect(calls.get(page)).toEqual([]);
});

for (const which of ["empty", "full"] as const)
  test(`${which} graph stays inspectable without inventing a destination`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const f = seed(nativeScheduleWriteServer.directory),
      { editor } = await enter(page, f[which]);
    await expect(editor).toContainText(
      which === "empty"
        ? "No recorded native connection prototype"
        : "No destination passes",
    );
    await expect(
      editor.getByRole("region", {
        name: "Reviewed native connection copy",
        exact: true,
      }),
    ).toHaveCount(0);
    expect(calls.get(page)).toEqual([]);
  });

test("source read refusal preserves local work and explicit retry restores qualified candidates", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seed(nativeScheduleWriteServer.directory),
    { editor } = await enter(page, f.a);
  await prepare(editor);
  await page.route(
    "**/connection-copy/source",
    (route) =>
      route.fulfill({
        status: 409,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Authored original integrity refusal" }),
      }),
    { times: 1 },
  );
  await editor
    .getByRole("button", {
      name: "Open native connection candidates",
      exact: true,
    })
    .click();
  await expect(editor.getByRole("alert")).toContainText(
    "Authored original integrity refusal",
  );
  await expect(
    editor.getByRole("region", {
      name: "Reviewed native connection copy",
      exact: true,
    }),
  ).toHaveCount(0);
  await editor
    .getByRole("button", {
      name: "Open native connection candidates",
      exact: true,
    })
    .click();
  await expect(
    editor.getByLabel("Unused native destination", { exact: true }),
  ).toHaveValue(d);
  await prepare(editor);
  expect(calls.get(page)).toEqual([]);
});

for (const boundary of ["proposal", "operation", "pagehide", "hidden"] as const)
  test(`${boundary} A B A retires delayed native connection review`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const f = seed(nativeScheduleWriteServer.directory),
      { operations, editor } = await enter(page, f.a);
    await editor
      .getByLabel("Unused native destination", { exact: true })
      .selectOption(d);
    let release = () => {},
      started = () => {};
    const gate = new Promise<void>((r) => (release = r)),
      received = new Promise<void>((r) => (started = r));
    await page.route(
      "**/connection-copy/preview",
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
          name: "Review native connection copy",
          exact: true,
        })
        .click();
      await received;
      if (boundary === "proposal") {
        await editor
          .getByLabel("Unused native destination", { exact: true })
          .selectOption("");
        await editor
          .getByLabel("Unused native destination", { exact: true })
          .selectOption(d);
      } else if (boundary === "operation") {
        await operations
          .getByLabel("Native diagram operation", { exact: true })
          .selectOption("source");
        await operations
          .getByLabel("Native diagram operation", { exact: true })
          .selectOption("add");
      } else {
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
            name: "Open native connection candidates",
            exact: true,
          })
          .click();
      }
      // Wait for the held response itself; no arbitrary delay or retry can conceal a late adoption.
      const delivered = page.waitForResponse((r) =>
        r.url().endsWith("/connection-copy/preview"),
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
          name: "Reviewed native connection copy",
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

test("wrong review request and corrupted output never download a connection copy", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seed(nativeScheduleWriteServer.directory),
    { editor } = await enter(page, f.a);
  const downloads: string[] = [];
  page.on("download", (download) =>
    downloads.push(download.suggestedFilename()),
  );
  await page.route(
    "**/connection-copy/preview",
    async (route) => {
      const response = await route.fetch({ maxRetries: 0 }),
        data = JSON.parse((await response.body()).toString());
      data.request.target_ref = a;
      await route.fulfill({ response, body: JSON.stringify(data) });
    },
    { times: 1 },
  );
  await editor
    .getByLabel("Unused native destination", { exact: true })
    .selectOption(d);
  await editor
    .getByRole("button", { name: "Review native connection copy", exact: true })
    .click();
  await expect(editor.getByRole("alert")).toContainText("exact proposal");
  const reviewed = await prepare(editor);
  await page.route(
    "**/connection-copy/export",
    async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      await route.fulfill({
        response,
        body: Buffer.from("wrong native bytes"),
      });
    },
    { times: 1 },
  );
  await reviewed
    .getByRole("button", { name: "Save native connection copy", exact: true })
    .click();
  await expect(editor.getByRole("alert")).toContainText(
    "output bytes or export proof differ",
  );
  expect(downloads).toEqual([]);
  expect(calls.get(page)).toEqual([]);
});

test("changing retained source keeps separate drafts and never restores the previous review", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seed(nativeScheduleWriteServer.directory),
    { compiler, editor } = await enter(page, f.a);
  await prepare(editor);
  await compiler
    .getByLabel("Retained native backup", { exact: true })
    .selectOption(f.other);
  const other = await openRecord(page, compiler);
  await expect(
    other.editor.getByLabel("Unused native destination", { exact: true }),
  ).toHaveValue("");
  await compiler
    .getByLabel("Retained native backup", { exact: true })
    .selectOption(f.a);
  const original = await openRecord(page, compiler);
  await expect(
    original.editor.getByLabel("Unused native destination", { exact: true }),
  ).toHaveValue(d);
  await expect(
    original.editor.getByRole("region", {
      name: "Reviewed native connection copy",
      exact: true,
    }),
  ).toHaveCount(0);
  expect(calls.get(page)).toEqual([]);
});

test("routed controller entry keeps connection copies local and exact route changes retire review", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seed(nativeScheduleWriteServer.directory),
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
      .selectOption(f.a);
    return openRecord(page, compiler);
  }
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
    const { editor } = await select(true),
      before = await peer.command("stats");
    const reviewed = await prepare(editor),
      downloading = page.waitForEvent("download");
    await reviewed
      .getByRole("button", { name: "Save native connection copy", exact: true })
      .click();
    await downloading;
    const after = await peer.command("stats");
    expect(after.request_types).toEqual(before.request_types);
    expect(after.events).toEqual(before.events);
    await page
      .getByRole("button", { name: "Change controller", exact: true })
      .click();
    const changed = await select(false);
    await expect(
      changed.editor.getByLabel("Unused native destination", { exact: true }),
    ).toHaveValue(d);
    await expect(
      changed.editor.getByRole("region", {
        name: "Reviewed native connection copy",
        exact: true,
      }),
    ).toHaveCount(0);
    expect(
      (await peer.command("stats")).events.filter(
        (r: any[]) => r[0] === "write" || r[0] === "state",
      ),
    ).toEqual([]);
  } finally {
    peer.close();
  }
});

test("retired export response cannot download after operation A B A", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seed(nativeScheduleWriteServer.directory),
    { editor, operations } = await enter(page, f.a);
  const reviewed = await prepare(editor),
    downloads: string[] = [];
  page.on("download", (download) =>
    downloads.push(download.suggestedFilename()),
  );
  let release = () => {},
    started = () => {};
  const gate = new Promise<void>((r) => (release = r)),
    received = new Promise<void>((r) => (started = r));
  await page.route(
    "**/connection-copy/export",
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
      .getByRole("button", { name: "Save native connection copy", exact: true })
      .click();
    await received;
    await operations
      .getByLabel("Native diagram operation", { exact: true })
      .selectOption("source");
    await operations
      .getByLabel("Native diagram operation", { exact: true })
      .selectOption("add");
    const delivered = page.waitForResponse((r) =>
      r.url().endsWith("/connection-copy/export"),
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
        name: "Reviewed native connection copy",
        exact: true,
      }),
    ).toHaveCount(0);
    expect(downloads).toEqual([]);
    expect(calls.get(page)).toEqual([]);
  } finally {
    release();
  }
});

test("substituted source authority is refused and local draft can be discarded before a source retry", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seed(nativeScheduleWriteServer.directory),
    { editor } = await enter(page, f.a);
  await prepare(editor);
  await page.route(
    "**/connection-copy/source",
    async (route) => {
      const response = await route.fetch({ maxRetries: 0 }),
        value = JSON.parse((await response.body()).toString());
      value.can_apply = true;
      await route.fulfill({ response, body: JSON.stringify(value) });
    },
    { times: 1 },
  );
  await editor
    .getByRole("button", {
      name: "Open native connection candidates",
      exact: true,
    })
    .click();
  await expect(editor.getByRole("alert")).toContainText("do not match");
  await expect(
    editor.getByLabel("Unused native destination", { exact: true }),
  ).toHaveCount(0);
  await editor
    .getByRole("button", {
      name: "Discard native connection draft",
      exact: true,
    })
    .click();
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
      name: "Reviewed native connection copy",
      exact: true,
    }),
  ).toHaveCount(0);
  expect(calls.get(page)).toEqual([]);
});

test("phone keyboard review exposes one primary action and preserves exact selected input", async ({
  page,
  nativeScheduleWriteServer,
  browserName,
}, info) => {
  const f = seed(nativeScheduleWriteServer.directory);
  await page.setViewportSize({ width: 390, height: 844 });
  const { editor } = await enter(page, f.a);
  const destination = editor.getByLabel("Unused native destination", {
    exact: true,
  });
  await destination.selectOption(d);
  await destination.focus();
  await page.keyboard.press(browserName === "webkit" ? "Alt+Tab" : "Tab");
  const button = editor.getByRole("button", {
    name: "Review native connection copy",
    exact: true,
  });
  await expect(button).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(
    editor.getByRole("region", {
      name: "Reviewed native connection copy",
      exact: true,
    }),
  ).toContainText("New connection: 0, 85, 3, 7000");
  await expect(editor.locator("button.primary")).toHaveCount(1);
  await expect(destination).toHaveValue(d);
  await editor.scrollIntoViewIfNeeded();
  await page.screenshot({
    path: info.outputPath("native-connection-phone.png"),
  });
  expect(calls.get(page)).toEqual([]);
});
