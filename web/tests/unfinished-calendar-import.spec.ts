import {
  test,
  expect,
  type APIRequestContext,
  type Page,
} from "./nativeScheduleWriteFixture";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import {
  chooseWorkspaceSurface,
  chooseWorkspaceTask,
} from "./workspace-navigation";

const root = path.resolve(".."),
  LIB = "/api/bacnet/schedules/library",
  BASE = LIB + "/calendar";
let fixtures: Buffer[] | undefined;
function archives() {
  return (fixtures ||= [false, true].map((routed) =>
    execFileSync(
      path.join(root, ".venv/bin/python"),
      [
        "-c",
        `
import asyncio,sys,tempfile
from pathlib import Path
from tests.test_connections import free_udp
from tests.test_schedule_inventory import make_peer,options
from bms_tool.connections import Bacnet
from bms_tool.schedule_inventory import ScheduleInventory
from bms_tool.storage import Store
from bms_tool.native_schedule_library import NativeScheduleLibrary,encoded
async def acquire(directory,routed):
 peer=await make_peer(routed=routed)
 client=Bacnet(Store(directory))
 await client.connect(f'127.0.0.1:{free_udp()}')
 inventory=ScheduleInventory(client,client.store,timeout=0.2,operation_timeout=5,request_gap=0)
 try:
  report=await inventory.read(**options(peer,object_ids=['calendar,1','calendar,2','schedule,1']))
  assert not peer.errors
  return report
 finally:
  await inventory.close()
  client.close()
  peer.close()
  await asyncio.sleep(0.01)
with tempfile.TemporaryDirectory() as temporary:
 report=asyncio.run(acquire(Path(temporary)/'peer',routed=sys.argv[1]=='1'))
 assert report['complete'] and report['identity_verified']
 library=NativeScheduleLibrary(Path(temporary)/'library')
 capture=library._store(encoded(report),'imported')
 sys.stdout.buffer.write(library.archive(capture['id']))
`,
        routed ? "1" : "0",
      ],
      {
        cwd: root,
        env: { ...process.env, PYTHONPATH: root + "/backend:" + root },
      },
    ),
  ));
}
async function auth(request: APIRequestContext) {
  return {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
}
const library = (page: Page) =>
  page.getByRole("region", {
    name: "Native Schedule capture library",
    exact: true,
  });
const editor = (page: Page) =>
  page.getByRole("region", {
    name: "Captured Calendar date editor",
    exact: true,
  });
const control = (page: Page, label: string) =>
  editor(page).getByLabel(label, { exact: true });
const button = (page: Page, label: string) =>
  editor(page).getByRole("button", { name: label, exact: true });
const reviewed = (page: Page) =>
  editor(page).getByLabel("Calendar date draft review", { exact: true });
async function open(page: Page, capture: any) {
  await library(page)
    .getByRole("button", {
      name: `Open capture ${capture.id.slice(0, 12)}`,
      exact: true,
    })
    .click();
  const details = library(page).getByLabel("Captured Calendar dates", {
    exact: true,
  });
  if (!(await details.evaluate((node) => (node as HTMLDetailsElement).open)))
    await details.getByText("Calendar dates", { exact: true }).click();
  await control(page, "Captured Calendar for date draft").selectOption(
    "calendar,1",
  );
  await expect(control(page, "Captured Calendar for date draft")).toHaveValue(
    "calendar,1",
  );
  await expect(editor(page)).toContainText(capture.id);
}
async function setup(page: Page, request: APIRequestContext, caf = false) {
  const headers = await auth(request);
  expect(
    (await request.post("/api/bacnet/disconnect", { headers, data: {} })).ok(),
  ).toBe(true);
  const captures = [];
  for (const [i, buffer] of archives().entries()) {
    const response = await request.post(LIB + "/import", {
      headers,
      multipart: {
        file: {
          name: `authored-${i}.json`,
          mimeType: "application/json",
          buffer,
        },
      },
    });
    expect(response.ok(), await response.text()).toBe(true);
    captures.push(await response.json());
  }
  const fieldCalls: string[] = [];
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      request.url().includes("/api/bacnet/") &&
      !request.url().includes(LIB + "/")
    )
      fieldCalls.push(request.url());
  });
  await page.goto("/");
  if (caf) {
    const buffer = execFileSync(
      path.join(root, ".venv/bin/python"),
      [
        "-c",
        "from tests.test_caf_graph import make_graph; import sys; sys.stdout.buffer.write(make_graph())",
      ],
      { cwd: root },
    );
    await page
      .getByLabel("Open local CAF application", { exact: true })
      .setInputFiles({
        name: "calendar-work.caf",
        mimeType: "application/octet-stream",
        buffer,
      });
    await expect(page.getByLabel("Working context")).toContainText(
      "calendar-work.caf",
    );
  } else
    await page
      .getByRole("button", { name: "New application", exact: true })
      .click();
  await expect(
    page.getByRole("navigation", { name: "Workspace tasks", exact: true }),
  ).toBeVisible();
  await chooseWorkspaceTask(page, "Schedules");
  await expect(library(page)).toBeVisible();
  await expect(
    page.getByRole("region", {
      name: "Native Calendar and Schedule inventory",
      exact: true,
    }),
  ).toHaveCount(0);
  await open(page, captures[0]);
  return { captures, headers, fieldCalls };
}
async function date(page: Page, prefix: string, day = "2") {
  await control(page, prefix + " year").fill("2026");
  await control(page, prefix + " month").selectOption("11");
  await control(page, prefix + " day").selectOption(day);
  await control(page, prefix + " weekday").selectOption("*");
}
async function review(page: Page) {
  await button(page, "Review Calendar dates").click();
  await expect(reviewed(page)).toBeVisible();
  await expect(button(page, "Export reviewed Calendar draft")).toBeEnabled();
}
async function reviewDocument(page: Page) {
  const download = page.waitForEvent("download");
  await button(page, "Export reviewed Calendar draft").click();
  const file = await download,
    bytes = readFileSync((await file.path())!);
  return {
    bytes,
    value: JSON.parse(bytes.toString()),
    name: file.suggestedFilename(),
  };
}

async function rawExport(page: Page) {
  const details = editor(page)
    .getByText("Unfinished Calendar drafts", { exact: true })
    .locator("..");
  if (!(await details.evaluate((node) => (node as HTMLDetailsElement).open)))
    await details.locator("summary").click();
  const pending = page.waitForEvent("download");
  await button(page, "Export unfinished Calendar text").click();
  const file = await pending,
    bytes = readFileSync((await file.path())!);
  return {
    bytes,
    name: file.suggestedFilename(),
    value: JSON.parse(bytes.toString()),
  };
}
async function restore(page: Page, file: { bytes: Buffer; name: string }) {
  await control(page, "Import unfinished Calendar text file").setInputFiles({
    name: file.name,
    mimeType: "application/json",
    buffer: file.bytes,
  });
}
async function discard(page: Page) {
  await button(page, "Discard Calendar edits").click();
}
async function unfinished(page: Page) {
  await control(page, "Calendar entry 1 year").fill("20");
  return rawExport(page);
}

for (const caf of [false, true])
  test(`unfinished Calendar ${caf ? "CAF" : "graph"} text recovers after reload with separate provenance`, async ({
    page,
    request,
  }, info) => {
    const { captures, fieldCalls } = await setup(page, request, caf),
      file = await unfinished(page);
    await page.reload();
    if (caf) {
      const buffer = execFileSync(
        path.join(root, ".venv/bin/python"),
        [
          "-c",
          "from tests.test_caf_graph import make_graph; import sys; sys.stdout.buffer.write(make_graph())",
        ],
        {
          cwd: root,
          env: { ...process.env, PYTHONPATH: root + "/backend:" + root },
        },
      );
      await page
        .getByLabel("Open local CAF application", { exact: true })
        .setInputFiles({
          name: "calendar-work.caf",
          mimeType: "application/octet-stream",
          buffer,
        });
      await expect(
        page.getByLabel("Working context", { exact: true }),
      ).toContainText("calendar-work.caf");
    } else {
      const create = page.getByRole("button", {
        name: "New application",
        exact: true,
      });
      if (await create.isVisible()) await create.click();
    }
    await chooseWorkspaceSurface(page, "Workspace");
    await chooseWorkspaceTask(page, "Schedules");
    await open(page, captures[0]);
    await restore(page, file);
    await expect(control(page, "Calendar entry 1 year")).toHaveValue("20");
    await expect(reviewed(page)).toHaveCount(0);
    await expect(button(page, "Export reviewed Calendar draft")).toBeDisabled();
    const again = await rawExport(page);
    expect(again.value.buffer.rows).toEqual(file.value.buffer.rows);
    expect(again.value.buffer.rawImported.filename).toBe(file.name);
    await chooseWorkspaceTask(page, "Program");
    await chooseWorkspaceTask(page, "Schedules");
    await expect(control(page, "Calendar entry 1 year")).toHaveValue("20");
    const details = editor(page)
      .getByText("Unfinished Calendar drafts", { exact: true })
      .locator("..");
    if (!(await details.evaluate((n) => (n as HTMLDetailsElement).open)))
      await details.locator("summary").click();
    await page.setViewportSize({ width: 390, height: 1100 });
    const provenance = editor(page).getByLabel(
      "Unfinished Calendar import provenance",
      { exact: true },
    );
    await provenance.scrollIntoViewIfNeeded();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: info.outputPath("unfinished-calendar-phone.png"),
      fullPage: true,
    });
    await page.setViewportSize({ width: 1440, height: 1000 });
    await date(page, "Calendar entry 1");
    await review(page);
    expect(fieldCalls).toEqual([]);
  });

test("raw Calendar replacement requires explicit discard and exact capture/object selection", async ({
  page,
  request,
}) => {
  const { captures, fieldCalls } = await setup(page, request),
    file = await unfinished(page);
  await restore(page, file);
  await expect(editor(page).getByRole("alert")).toContainText(
    "Discard this retained Calendar draft",
  );
  await expect(control(page, "Calendar entry 1 year")).toHaveValue("20");
  await discard(page);
  await control(page, "Captured Calendar for date draft").selectOption(
    "calendar,2",
  );
  await restore(page, file);
  await expect(editor(page).getByRole("alert")).toContainText(
    "selected Calendar",
  );
  await open(page, captures[1]);
  await restore(page, file);
  await expect(editor(page).getByRole("alert")).toContainText(
    "original capture",
  );
  await expect(reviewed(page)).toHaveCount(0);
  await open(page, captures[0]);
  await restore(page, file);
  await expect(control(page, "Calendar entry 1 year")).toHaveValue("20");
  expect(fieldCalls).toEqual([]);
});

test("unknown raw pattern choices remain visible and require valid native review", async ({
  page,
  request,
}) => {
  const { fieldCalls } = await setup(page, request),
    file = await unfinished(page);
  file.value.buffer.rows[0].date[1] = "?";
  file.bytes = Buffer.from(JSON.stringify(file.value));
  await discard(page);
  await restore(page, file);
  await expect(control(page, "Calendar entry 1 month")).toHaveValue("?");
  await expect(control(page, "Calendar entry 1 month")).toContainText(
    "Unrecognized value: ?",
  );
  expect((await rawExport(page)).value.buffer.rows).toEqual(
    file.value.buffer.rows,
  );
  await button(page, "Review Calendar dates").click();
  await expect(editor(page).getByRole("alert")).toBeVisible();
  await expect(reviewed(page)).toHaveCount(0);
  await date(page, "Calendar entry 1");
  await review(page);
  expect(fieldCalls).toEqual([]);
});

test("malformed and oversized raw Calendar files retire reviews without changing rows or posting", async ({
  page,
  request,
}) => {
  const { fieldCalls } = await setup(page, request);
  await date(page, "Calendar entry 1");
  await review(page);
  const posts: string[] = [];
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().endsWith(BASE + "/unfinished/import"))
      posts.push(r.url());
  });
  await restore(page, {
    name: "duplicate.json",
    bytes: Buffer.from('{"source":1,"source":1}'),
  });
  await expect(editor(page).getByRole("alert")).toBeVisible();
  await expect(reviewed(page)).toHaveCount(0);
  await expect(control(page, "Calendar entry 1 year")).toHaveValue("2026");
  await restore(page, {
    name: "large.json",
    bytes: Buffer.alloc(128 * 1024 + 1, 32),
  });
  await expect(editor(page).getByRole("alert")).toContainText("128 KiB");
  expect(posts).toEqual([]);
  expect(fieldCalls).toEqual([]);
});

for (const boundary of ["edit", "source ABA", "visibility", "pagehide", "task"])
  test(`held raw Calendar reply cannot replace work after ${boundary}`, async ({
    page,
    request,
  }) => {
    const { captures, headers, fieldCalls } = await setup(page, request),
      file = await unfinished(page);
    await discard(page);
    const response = await request.post(BASE + "/unfinished/import", {
      headers,
      multipart: {
        file: {
          name: file.name,
          mimeType: "application/json",
          buffer: file.bytes,
        },
      },
    });
    expect(response.ok(), await response.text()).toBe(true);
    const body = await response.body();
    let release!: () => void, arrived!: () => void;
    const held = new Promise<void>((r) => (release = r)),
      seen = new Promise<void>((r) => (arrived = r));
    await page.route("**" + BASE + "/unfinished/import", async (route) => {
      arrived();
      await held;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body,
      });
    });
    await review(page);
    await restore(page, file);
    await seen;
    await expect(reviewed(page)).toHaveCount(0);
    if (boundary === "edit")
      await control(page, "Calendar entry 1 year").fill("202");
    else if (boundary === "source ABA") {
      await control(page, "Captured Calendar for date draft").selectOption(
        "calendar,2",
      );
      await control(page, "Captured Calendar for date draft").selectOption(
        "calendar,1",
      );
    } else if (boundary === "task") {
      await chooseWorkspaceTask(page, "Program");
      await chooseWorkspaceTask(page, "Schedules");
      await open(page, captures[0]);
    } else
      await page.evaluate((type) => {
        if (type === "visibility")
          document.dispatchEvent(new Event("visibilitychange"));
        else window.dispatchEvent(new Event("pagehide"));
      }, boundary);
    const reply = page.waitForResponse((r) =>
      r.url().endsWith(BASE + "/unfinished/import"),
    );
    release();
    await reply;
    if (["visibility", "pagehide"].includes(boundary))
      await button(page, "Refresh captured Calendars").click();
    await expect(control(page, "Calendar entry 1 year")).toHaveValue(
      boundary === "edit" ? "202" : "*",
    );
    await expect(reviewed(page)).toHaveCount(0);
    expect(fieldCalls).toEqual([]);
  });

for (const altered of ["hash", "source", "buffer", "authority"])
  test(`substituted raw Calendar ${altered} response is refused`, async ({
    page,
    request,
  }) => {
    const { headers, fieldCalls } = await setup(page, request),
      file = await unfinished(page);
    await discard(page);
    const reply = await request.post(BASE + "/unfinished/import", {
      headers,
      multipart: {
        file: {
          name: file.name,
          mimeType: "application/json",
          buffer: file.bytes,
        },
      },
    });
    expect(reply.ok(), await reply.text()).toBe(true);
    const body = await reply.json();
    if (altered === "hash") body.file_sha256 = "f".repeat(64);
    else if (altered === "source") body.source[1] = "calendar,2";
    else if (altered === "buffer") body.buffer.rows[0].date[0] = "2030";
    else body.field_authority = true;
    await page.route("**" + BASE + "/unfinished/import", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(body),
      }),
    );
    await restore(page, file);
    await expect(editor(page).getByRole("alert")).toContainText(
      "differs from this file",
    );
    await expect(control(page, "Calendar entry 1 year")).toHaveValue("*");
    await expect(reviewed(page)).toHaveCount(0);
    expect(fieldCalls).toEqual([]);
  });
