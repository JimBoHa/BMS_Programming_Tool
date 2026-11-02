import {
  test,
  expect,
  type Page,
  type APIRequestContext,
} from "./nativeScheduleWriteFixture";
import {
  chooseWorkspaceTask,
  chooseWorkspaceSurface,
} from "./workspace-navigation";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
const root = path.resolve(".."),
  LIB = "/api/bacnet/schedules/library",
  BASE = LIB + "/weekly/unfinished";
const panel = (page: Page) =>
  page.getByRole("region", {
    name: "Native Schedule capture library",
    exact: true,
  });
let sources: Buffer[] | undefined;
function archives() {
  return (sources ||= ["numeric", "string"].map((kind) =>
    execFileSync(
      path.join(root, ".venv/bin/python"),
      [
        "-c",
        `
import asyncio,sys,tempfile
from pathlib import Path
from tests.test_native_schedule_library import acquire
from tests.test_native_schedule_strings import string_overrides,stringtag
from bms_tool.native_schedule_library import NativeScheduleLibrary,encoded
with tempfile.TemporaryDirectory() as directory:
 overrides=string_overrides(stringtag('old')) if sys.argv[1]=='string' else None
 if sys.argv[1]=='modern':overrides={('schedule,1','exception-schedule',1):bytes.fromhex('0e2bff07010f2eb4091e000044400000002f3908')}
 report,_,_=asyncio.run(acquire(Path(directory)/'peer',routed=sys.argv[1]=='string',overrides=overrides))
 assert report['complete'] and report['identity_verified']
 library=NativeScheduleLibrary(Path(directory)/'library');capture=library._store(encoded(report),'imported')
 sys.stdout.buffer.write(library.archive(capture['id']))
`,
        kind,
      ],
      {
        cwd: root,
        env: {
          ...process.env,
          PYTHONPATH: [path.join(root, "backend"), root].join(path.delimiter),
        },
      },
    ),
  ));
}
async function headers(request: APIRequestContext) {
  return {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
}
async function open(page: Page, capture: any) {
  const library = page.getByRole("region", {
    name: "Native Schedule capture library",
    exact: true,
  });

  await library
    .getByRole("button", {
      name: "Open capture " + capture.id.slice(0, 12),
      exact: true,
    })
    .click();
  await expect(
    library.getByLabel("Opened native schedule capture", { exact: true }),
  ).toContainText(capture.id);
}
async function setup(page: Page, request: APIRequestContext, caf = false) {
  const token = await headers(request),
    captures = [];
  expect(
    (
      await request.post("/api/bacnet/disconnect", { headers: token, data: {} })
    ).ok(),
  ).toBe(true);
  for (const [part, buffer] of archives().entries()) {
    const response = await request.post(LIB + "/import", {
      headers: token,
      multipart: {
        file: {
          name: `weekly-source-${part}.json`,
          mimeType: "application/json",
          buffer,
        },
      },
    });
    expect(response.ok(), await response.text()).toBe(true);
    captures.push(await response.json());
  }
  const field: string[] = [];
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      request.url().includes("/api/bacnet/") &&
      !request.url().includes(LIB + "/")
    )
      field.push(request.url());
  });
  await page.goto("/");
  if (caf) {
    const buffer = execFileSync(
      path.join(root, ".venv/bin/python"),
      [
        "-c",
        "from tests.test_caf_graph import make_graph; import sys; sys.stdout.buffer.write(make_graph())",
      ],
      {
        cwd: root,
        env: {
          ...process.env,
          PYTHONPATH: [path.join(root, "backend"), root].join(path.delimiter),
        },
      },
    );
    await page
      .getByLabel("Open local CAF application", { exact: true })
      .setInputFiles({
        name: "weekly-work.caf",
        mimeType: "application/octet-stream",
        buffer,
      });
  } else
    await page
      .getByRole("button", { name: "New application", exact: true })
      .click();
  await chooseWorkspaceTask(page, "Schedules");
  await open(page, captures[0]);
  return { captures, token, field };
}
const button = (page: Page, name: string) =>
  panel(page).getByRole("button", { name, exact: true });
const value = (page: Page) =>
  panel(page).getByLabel("Transition 1 exact value text", { exact: true });
const string = (page: Page) =>
  panel(page).getByLabel("Transition 1 CharacterString JSON literal", {
    exact: true,
  });
const proof = (page: Page) =>
  panel(page).getByLabel("Native weekly draft review", { exact: true });
async function rawExport(page: Page) {
  const details = panel(page)
    .getByText("Weekly workspace draft limits", { exact: true })
    .locator("..");
  if (!(await details.evaluate((node) => (node as HTMLDetailsElement).open)))
    await details.locator("summary").click();
  const pending = page.waitForEvent("download");
  await button(page, "Export unfinished weekly text").click();
  const download = await pending,
    bytes = readFileSync((await download.path())!);
  return {
    bytes,
    name: download.suggestedFilename(),
    value: JSON.parse(bytes.toString()),
  };
}
async function restore(page: Page, file: { bytes: Buffer; name: string }) {
  await panel(page)
    .getByLabel("Import unfinished weekly text file", { exact: true })
    .setInputFiles({
      name: file.name,
      mimeType: "application/json",
      buffer: file.bytes,
    });
}
async function discard(page: Page) {
  await button(page, "Discard weekly draft").click();
}
async function unfinished(page: Page) {
  await value(page).fill("2e-");
  await panel(page).getByLabel("Transition 1 hour", { exact: true }).fill("1e");
  return rawExport(page);
}
for (const caf of [false, true])
  test(`unfinished weekly ${caf ? "CAF" : "graph"} raw text survives reload and keeps native authority absent`, async ({
    page,
    request,
  }, info) => {
    const { captures, field } = await setup(page, request, caf);
    const file = await unfinished(page);
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
          name: "weekly-work.caf",
          mimeType: "application/octet-stream",
          buffer,
        });
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
    await expect(panel(page)).toContainText("Restored unfinished weekly text.");
    await expect(value(page)).toHaveValue("2e-");
    await expect(
      panel(page).getByLabel("Transition 1 hour", { exact: true }),
    ).toHaveValue("1e");
    await expect(proof(page)).toHaveCount(0);
    await expect(button(page, "Apply reviewed weekly day")).toHaveCount(0);
    const again = await rawExport(page);
    expect(again.value.buffer.rows).toEqual(file.value.buffer.rows);
    expect(again.value.buffer.rawImported.filename).toBe(file.name);
    await chooseWorkspaceTask(page, "Program");
    await chooseWorkspaceTask(page, "Schedules");
    await expect(value(page)).toHaveValue("2e-");
    const provenance = panel(page).getByLabel(
      "Imported weekly draft provenance",
      { exact: true },
    );
    await provenance.locator("summary").click();
    await page.setViewportSize({ width: 390, height: 1000 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    expect(
      await provenance
        .locator("p")
        .evaluateAll((nodes) =>
          nodes.every((node) => node.scrollWidth <= node.clientWidth),
        ),
    ).toBe(true);
    await provenance.scrollIntoViewIfNeeded();
    await page.screenshot({
      path: info.outputPath("weekly-raw-phone.png"),
      fullPage: true,
    });
    await page.setViewportSize({ width: 1440, height: 1000 });
    await value(page).fill("5.25");
    await panel(page)
      .getByLabel("Transition 1 hour", { exact: true })
      .fill("6");
    await button(page, "Review native weekly draft").click();
    await expect(proof(page)).toBeVisible();
    expect(field).toEqual([]);
  });

test("raw import requires explicit discard even after native export and refuses another day or capture", async ({
  page,
  request,
}) => {
  const { captures, field } = await setup(page, request);
  const file = await unfinished(page);
  await restore(page, file);
  await expect(panel(page).getByRole("alert")).toContainText(
    "Discard this retained weekly draft",
  );
  await expect(value(page)).toHaveValue("2e-");
  await value(page).fill("4.5");
  await panel(page).getByLabel("Transition 1 hour", { exact: true }).fill("6");
  await button(page, "Review native weekly draft").click();
  await expect(proof(page)).toBeVisible();
  const saved = page.waitForEvent("download");
  await button(page, "Export exact reviewed weekly draft").click();
  await saved;
  await restore(page, file);
  await expect(panel(page).getByRole("alert")).toContainText(
    "Discard this retained weekly draft",
  );
  await expect(value(page)).toHaveValue("4.5");
  await expect(proof(page)).toHaveCount(0);
  await discard(page);
  await panel(page)
    .getByLabel("Native weekly day", { exact: true })
    .selectOption("2");
  await restore(page, file);
  await expect(panel(page).getByRole("alert")).toContainText(
    "original capture, Schedule or day",
  );
  await expect(proof(page)).toHaveCount(0);
  await open(page, captures[1]);
  await restore(page, file);
  await expect(panel(page).getByRole("alert")).toContainText(
    "original capture, Schedule or day",
  );
  await expect(string(page)).toHaveValue('"old"');
  await open(page, captures[0]);
  await panel(page)
    .getByLabel("Native weekly day", { exact: true })
    .selectOption("1");
  await restore(page, file);
  await expect(value(page)).toHaveValue("2e-");
  expect(field).toEqual([]);
});

test("raw String and Null text survive recovery and still require fresh valid native review", async ({
  page,
  request,
}) => {
  const { captures, field } = await setup(page, request);
  await open(page, captures[1]);
  await string(page).fill('"\\u');
  const file = await rawExport(page);
  await discard(page);
  await restore(page, file);
  await expect(string(page)).toHaveValue('"\\u');
  await button(page, "Review native weekly draft").click();
  await expect(panel(page).getByRole("alert")).toBeVisible();
  await expect(proof(page)).toHaveCount(0);
  await string(page).fill('"null\\u0000é🌡"');
  await button(page, "Review native weekly draft").click();
  await expect(proof(page)).toBeVisible();
  await panel(page)
    .getByLabel("Transition 1 native type", { exact: true })
    .selectOption("Null");
  const nullFile = await rawExport(page);
  expect(nullFile.value.buffer.rows[0].native_type).toBe("Null");
  expect(nullFile.value.buffer.rows[0].value_text).toBe("null");
  await discard(page);
  await restore(page, nullFile);
  await expect(
    panel(page).getByLabel("Transition 1 native type", { exact: true }),
  ).toHaveValue("Null");
  await expect(proof(page)).toHaveCount(0);
  expect(field).toEqual([]);
});

test("duplicate keys and oversized raw files refuse before POST and keep existing work", async ({
  page,
  request,
}) => {
  const { field } = await setup(page, request);
  await value(page).fill("9.5");
  const calls: string[] = [];
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().endsWith(BASE + "/import"))
      calls.push(r.url());
  });
  await restore(page, {
    name: "duplicate.json",
    bytes: Buffer.from('{"source":1,"source":1}'),
  });
  await expect(panel(page).getByRole("alert")).toBeVisible();
  await expect(value(page)).toHaveValue("9.5");
  await restore(page, {
    name: "large.json",
    bytes: Buffer.alloc(512 * 1024 + 1, 32),
  });
  await expect(panel(page).getByRole("alert")).toContainText("512 KiB");
  await expect(value(page)).toHaveValue("9.5");
  expect(calls).toEqual([]);
  expect(field).toEqual([]);
});

for (const boundary of ["edit", "day ABA", "visibility", "task"])
  test(`held raw weekly reply cannot replace work after ${boundary}`, async ({
    page,
    request,
  }) => {
    const { captures, token, field } = await setup(page, request);
    const file = await unfinished(page);
    await discard(page);
    // Verify a real local HTTP response using known original bytes. Do not replay browser multipart bodies.
    const result = await request.post(BASE + "/import", {
      headers: token,
      multipart: {
        file: {
          name: file.name,
          mimeType: "application/json",
          buffer: file.bytes,
        },
      },
    });
    expect(result.ok(), await result.text()).toBe(true);
    const payload = await result.body();
    let release!: () => void, arrived!: () => void;
    const held = new Promise<void>((r) => (release = r)),
      seen = new Promise<void>((r) => (arrived = r));
    await page.route("**" + BASE + "/import", async (route) => {
      arrived();
      await held;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: payload,
      });
    });
    await button(page, "Review native weekly draft").click();
    await expect(proof(page)).toBeVisible();
    await restore(page, file);
    await seen;
    await expect(proof(page)).toHaveCount(0);
    if (boundary === "edit") await value(page).fill("8.5");
    else if (boundary === "day ABA") {
      await panel(page)
        .getByLabel("Native weekly day", { exact: true })
        .selectOption("2");
      await panel(page)
        .getByLabel("Native weekly day", { exact: true })
        .selectOption("1");
    } else if (boundary === "visibility")
      await page.evaluate(() =>
        document.dispatchEvent(new Event("visibilitychange")),
      );
    else {
      await chooseWorkspaceTask(page, "Program");
      await chooseWorkspaceTask(page, "Schedules");
      await open(page, captures[0]);
    }
    const reply = page.waitForResponse((r) =>
      r.url().endsWith(BASE + "/import"),
    );
    release();
    await reply;
    await expect(button(page, "Refresh local schedule library")).toBeEnabled();
    await expect(panel(page)).not.toContainText(
      "Restored unfinished weekly text.",
    );
    if (boundary === "edit") await expect(value(page)).toHaveValue("8.5");
    else await expect(value(page)).toHaveValue("-0.0");
    await expect(proof(page)).toHaveCount(0);
    expect(field).toEqual([]);
  });

for (const altered of ["hash", "source", "buffer", "authority"])
  test(`substituted raw weekly ${altered} response is rejected`, async ({
    page,
    request,
  }) => {
    const { token, field } = await setup(page, request);
    const file = await unfinished(page);
    await discard(page);
    const response = await request.post(BASE + "/import", {
      headers: token,
      multipart: {
        file: {
          name: file.name,
          mimeType: "application/json",
          buffer: file.bytes,
        },
      },
    });
    expect(response.ok(), await response.text()).toBe(true);
    const payload = await response.json();
    if (altered === "hash") payload.file_sha256 = "f".repeat(64);
    else if (altered === "source") payload.source[2] = "2";
    else if (altered === "buffer") payload.buffer.rows[0].value_text = "999";
    else payload.field_authority = true;
    await page.route("**" + BASE + "/import", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(payload),
      }),
    );
    await restore(page, file);
    await expect(panel(page).getByRole("alert")).toContainText(
      "differs from this file",
    );
    await expect(value(page)).toHaveValue("-0.0");
    await expect(proof(page)).toHaveCount(0);
    expect(field).toEqual([]);
  });
