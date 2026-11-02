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
  BASE = LIB + "/exceptions";
const panel = (page: Page) =>
  page.getByRole("region", {
    name: "Captured Schedule exception editor",
    exact: true,
  });
let sources: Buffer[] | undefined;
function archives() {
  return (sources ||= ["numeric", "routed", "string", "modern"].map((kind) =>
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
 report,_,_=asyncio.run(acquire(Path(directory)/'peer',routed=sys.argv[1]=='routed',overrides=overrides))
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
  const details = library.getByLabel("Captured Schedule exceptions", {
    exact: true,
  });
  if (!(await details.evaluate((node) => (node as HTMLDetailsElement).open)))
    await details.locator("summary").click();
  await expect(
    panel(page).getByLabel("Captured Schedule for exceptions", { exact: true }),
  ).toHaveValue("schedule,1");
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
          name: `exception-source-${part}.json`,
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
        name: "exception-work.caf",
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
async function reviewed(page: Page) {
  await panel(page)
    .getByRole("button", { name: "Review exception draft", exact: true })
    .click();
  await expect(
    panel(page).getByRole("region", {
      name: "Native exception draft review",
      exact: true,
    }),
  ).toBeVisible();
}
async function downloaded(page: Page) {
  const pending = page.waitForEvent("download");
  await panel(page)
    .getByRole("button", { name: "Export reviewed exceptions", exact: true })
    .click();
  const file = await pending;
  const bytes = readFileSync((await file.path())!);
  return {
    bytes,
    name: file.suggestedFilename(),
    value: JSON.parse(bytes.toString()),
  };
}

async function rawExport(page: Page) {
  const p = panel(page),
    details = p.getByText("Retained exception drafts", { exact: true });
  if (
    !(await details
      .locator("..")
      .evaluate((node) => (node as HTMLDetailsElement).open))
  )
    await details.click();
  await p
    .getByLabel("Retained exception source", { exact: true })
    .selectOption({ index: 1 });
  const pending = page.waitForEvent("download");
  await p
    .getByRole("button", {
      name: "Save unfinished exception text",
      exact: true,
    })
    .click();
  const file = await pending,
    bytes = readFileSync((await file.path())!);
  return {
    bytes,
    name: file.suggestedFilename(),
    value: JSON.parse(bytes.toString()),
  };
}
async function restore(page: Page, file: { bytes: Buffer; name: string }) {
  await panel(page)
    .getByLabel("Import unfinished exception text file", { exact: true })
    .setInputFiles({
      name: file.name,
      mimeType: "application/json",
      buffer: file.bytes,
    });
}
async function discard(page: Page) {
  await panel(page)
    .getByRole("button", { name: "Discard exception edits", exact: true })
    .click();
}
async function unfinished(page: Page) {
  const p = panel(page);
  await p.getByLabel("Exception time 1 value", { exact: true }).fill("1e-");
  await p.getByLabel("Exception time 1 hour", { exact: true }).fill("2e");
  await p.getByLabel("Exception event priority", { exact: true }).fill("-");
  await p.getByLabel("Exception date year", { exact: true }).fill("20");
  return rawExport(page);
}
for (const caf of [false, true])
  test(`unfinished ${caf ? "CAF" : "graph"} fields restore after reload without a native review`, async ({
    page,
    request,
  }, info) => {
    const { captures, field } = await setup(page, request, caf);
    const file = await unfinished(page);
    expect(file.value.profile).toBe("native-schedule-unfinished-exceptions/1");
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
          env: {
            ...process.env,
            PYTHONPATH: [path.join(root, "backend"), root].join(path.delimiter),
          },
        },
      );
      await page
        .getByLabel("Open local CAF application", { exact: true })
        .setInputFiles({
          name: "exception-work.caf",
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
    const p = panel(page);
    await expect(p).toContainText("Unfinished exception text imported.");
    await expect(
      p.getByLabel("Exception time 1 value", { exact: true }),
    ).toHaveValue("1e-");
    await expect(
      p.getByLabel("Exception time 1 hour", { exact: true }),
    ).toHaveValue("2e");
    await expect(
      p.getByLabel("Exception event priority", { exact: true }),
    ).toHaveValue("-");
    await expect(
      p.getByLabel("Exception date year", { exact: true }),
    ).toHaveValue("20");
    await expect(
      p.getByRole("button", {
        name: "Export reviewed exceptions",
        exact: true,
      }),
    ).toBeDisabled();
    await expect(
      p.getByLabel("Native exception draft review", { exact: true }),
    ).toHaveCount(0);
    await expect(
      p.getByRole("button", { name: "Apply Schedule exceptions", exact: true }),
    ).toHaveCount(0);
    const again = await rawExport(page);
    expect(again.value.buffer.rows).toEqual(file.value.buffer.rows);
    expect(again.value.buffer.rawImported.filename).toBe(file.name);
    expect(again.value.buffer.rawImported.file_sha256).toMatch(
      /^[a-f0-9]{64}$/,
    );
    await chooseWorkspaceTask(page, "Program");
    await chooseWorkspaceTask(page, "Schedules");
    await expect(
      p.getByLabel("Exception time 1 value", { exact: true }),
    ).toHaveValue("1e-");
    const provenance = panel(page).getByLabel(
      "Unfinished exception import provenance",
      { exact: true },
    );
    await provenance.locator("summary").click();
    await page.setViewportSize({ width: 390, height: 1000 });
    await p
      .getByText("Retained exception drafts", { exact: true })
      .scrollIntoViewIfNeeded();
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
    await page.screenshot({
      path: info.outputPath("unfinished-import-phone.png"),
      fullPage: true,
    });
    expect(field).toEqual([]);
    expect(
      (await (await request.get("/api/session")).json()).field_network_open,
    ).toBe(false);
  });

test("unfinished String and Null preserve invalid JSON until a separate valid native review", async ({
  page,
  request,
}) => {
  const { captures, field } = await setup(page, request);
  await open(page, captures[2]);
  const p = panel(page),
    input = p.getByLabel("Exception time 1 value", { exact: true });
  await input.fill('"\\u');
  await p
    .getByLabel("Exception time 1 kind", { exact: true })
    .selectOption("Null");
  const file = await rawExport(page);
  await discard(page);
  await restore(page, file);
  await expect(p).toContainText("Unfinished exception text imported.");
  await expect(input).toHaveValue("null");
  await p
    .getByLabel("Exception time 1 kind", { exact: true })
    .selectOption("CharacterString");
  await expect(input).toHaveValue('"\\u');
  await p
    .getByRole("button", { name: "Review exception draft", exact: true })
    .click();
  await expect(p.getByRole("alert")).toBeVisible();
  await expect(
    p.getByRole("button", { name: "Export reviewed exceptions", exact: true }),
  ).toBeDisabled();
  const text = "\x00é🌡null";
  await input.fill(JSON.stringify(text));
  await reviewed(page);
  expect(
    (await downloaded(page)).value.new.events[0].transitions[0].value_text,
  ).toBe(text);
  expect(field).toEqual([]);
});

test("unfinished import refuses replacement and foreign sources while preserving current raw fields", async ({
  page,
  request,
}) => {
  const { captures } = await setup(page, request),
    file = await unfinished(page),
    p = panel(page);
  await p.getByLabel("Exception time 1 value", { exact: true }).fill("2e-");
  await restore(page, file);
  await expect(p.getByRole("alert")).toContainText("Existing work was kept");
  await expect(
    p.getByLabel("Exception time 1 value", { exact: true }),
  ).toHaveValue("2e-");
  await discard(page);
  const foreign = structuredClone(file.value);
  foreign.source[0] = captures[1].id;
  await restore(page, {
    bytes: Buffer.from(JSON.stringify(foreign)),
    name: "foreign-raw.json",
  });
  await expect(p.getByRole("alert")).toContainText("differs from this file");
  await expect(p).not.toContainText("Unfinished exception text imported.");
  const unknown = structuredClone(file.value);
  unknown.source[0] = "f".repeat(64);
  await restore(page, {
    bytes: Buffer.from(JSON.stringify(unknown)),
    name: "missing-source.json",
  });
  await expect(p.getByRole("alert")).toBeVisible();
  await expect(
    p.getByLabel("Exception time 1 value", { exact: true }),
  ).toHaveValue("2.0");
});

test("duplicate JSON keys and excessive files are refused before a local import request", async ({
  page,
  request,
}) => {
  await setup(page, request);
  const p = panel(page),
    calls: string[] = [];
  page.on("request", (r) => {
    if (r.url().endsWith("/unfinished/import")) calls.push(r.url());
  });
  await p.getByLabel("Exception time 1 value", { exact: true }).fill("2e-");
  await restore(page, {
    bytes: Buffer.from('{"profile":"x","profile":"y"}'),
    name: "duplicate.json",
  });
  await expect(p.getByRole("alert")).toContainText("Duplicate JSON object key");
  await restore(page, {
    bytes: Buffer.alloc(8 * 1024 * 1024 + 1, 32),
    name: "too-large.json",
  });
  await expect(p.getByRole("alert")).toContainText("8 MiB");
  await expect(
    p.getByLabel("Exception time 1 value", { exact: true }),
  ).toHaveValue("2e-");
  expect(calls).toEqual([]);
});

for (const action of ["edit", "source ABA", "visibility", "task"] as const)
  test(`held unfinished import retires on ${action} without replacing later work`, async ({
    page,
    request,
  }) => {
    const { captures, token } = await setup(page, request),
      file = await unfinished(page);
    await discard(page);
    const response = await request.post(BASE + "/unfinished/import", {
      headers: token,
      multipart: {
        file: {
          name: file.name,
          mimeType: "application/json",
          buffer: file.bytes,
        },
      },
      maxRetries: 0,
      maxRedirects: 0,
    });
    expect(response.ok(), await response.text()).toBe(true);
    const body = await response.body();
    let arrived!: () => void, release!: () => void, finished!: () => void;
    const held = new Promise<void>((r) => (arrived = r)),
      gate = new Promise<void>((r) => (release = r)),
      delivered = new Promise<void>((r) => (finished = r));
    await page.route(
      "**/exceptions/unfinished/import",
      async (route) => {
        arrived();
        await gate;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body,
        });
        finished();
      },
      { times: 1 },
    );
    try {
      await reviewed(page);
      await restore(page, file);
      await held;
      await expect(
        panel(page).getByLabel("Native exception draft review", {
          exact: true,
        }),
      ).toHaveCount(0);
      if (action === "edit")
        await panel(page)
          .getByLabel("Exception time 1 value", { exact: true })
          .fill("9e-");
      else if (action === "source ABA") {
        await open(page, captures[1]);
        await open(page, captures[0]);
      } else if (action === "visibility")
        await page.evaluate(() =>
          document.dispatchEvent(new Event("visibilitychange")),
        );
      else {
        await chooseWorkspaceTask(page, "Program");
        await chooseWorkspaceTask(page, "Schedules");
        await open(page, captures[0]);
      }
      release();
      await delivered;
      await expect(panel(page)).not.toContainText(
        "Unfinished exception text imported.",
      );
      await expect(
        panel(page).getByLabel("Exception time 1 value", { exact: true }),
      ).toHaveValue(action === "edit" ? "9e-" : "2.0");
    } finally {
      release();
    }
  });

for (const substituted of ["file", "source", "buffer", "authority"] as const)
  test(`substituted unfinished ${substituted} response cannot replace the original source`, async ({
    page,
    request,
  }) => {
    const { captures, token } = await setup(page, request),
      file = await unfinished(page);
    await discard(page);
    const response = await request.post(BASE + "/unfinished/import", {
      headers: token,
      multipart: {
        file: {
          name: file.name,
          mimeType: "application/json",
          buffer: file.bytes,
        },
      },
      maxRetries: 0,
      maxRedirects: 0,
    });
    expect(response.ok()).toBe(true);
    const data = await response.json();
    if (substituted === "file") data.file_sha256 = "f".repeat(64);
    if (substituted === "source") data.source[0] = captures[1].id;
    if (substituted === "buffer") data.buffer.rows[0].priority = "1";
    if (substituted === "authority") data.field_authority = true;
    await page.route(
      "**/exceptions/unfinished/import",
      (route) => route.fulfill({ status: 200, json: data }),
      { times: 1 },
    );
    await restore(page, file);
    await expect(panel(page).getByRole("alert")).toContainText(
      "differs from this file",
    );
    await expect(panel(page)).not.toContainText(
      "Unfinished exception text imported.",
    );
    await expect(
      panel(page).getByLabel("Exception time 1 value", { exact: true }),
    ).toHaveValue("2.0");
  });
