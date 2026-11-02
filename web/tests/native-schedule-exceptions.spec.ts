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
for (const caf of [false, true])
  test(`offline ${caf ? "CAF" : "graph"} entry keeps unfinished exception values, exact exports and imported provenance`, async ({
    page,
    request,
  }, info) => {
    const { captures, token, field } = await setup(page, request, caf);
    let p = panel(page);
    const input = () => p.getByLabel("Exception time 1 value", { exact: true });
    await input().fill("1e-");
    await p.getByLabel("Exception time 1 hour", { exact: true }).fill("2e");
    await p
      .getByLabel("Exception time 1 kind", { exact: true })
      .selectOption("Null");
    await expect(input()).toHaveValue("null");
    await expect(input()).toHaveAttribute("readonly", "");
    await p
      .getByLabel("Exception time 1 kind", { exact: true })
      .selectOption("Real");
    await expect(input()).toHaveValue("1e-");
    await chooseWorkspaceTask(page, "Program");
    await chooseWorkspaceTask(page, "Schedules");
    p = panel(page);
    await expect(input()).toHaveValue("1e-");
    await expect(
      p.getByLabel("Exception time 1 hour", { exact: true }),
    ).toHaveValue("2e");
    await chooseWorkspaceSurface(page, "Library");
    await chooseWorkspaceSurface(page, "Workspace");
    await chooseWorkspaceTask(page, "Schedules");
    p = panel(page);
    await expect(input()).toHaveValue("1e-");
    await p.getByLabel("Exception time 1 hour", { exact: true }).fill("09");
    await input().fill("-0");
    await reviewed(page);
    const file = await downloaded(page);
    expect(file.value.request.events[0].transitions[0].value_text).toBe("-0");
    expect(file.value.new.events[0].transitions[0].value_text).toBe("-0.0");
    expect(file.value.new.encoded_hex).toContain("4480000000");
    const exact = await request.post(BASE + "/export", {
      headers: token,
      data: { draft: file.value.request, expected_review_id: file.value.id },
    });
    expect(await exact.body()).toEqual(file.bytes);
    await p
      .getByLabel("Import exception draft file", { exact: true })
      .setInputFiles({
        name: file.name,
        mimeType: "application/json",
        buffer: file.bytes,
      });
    await expect(p).toContainText("Existing work was kept");
    await expect(input()).toHaveValue("-0");
    await p
      .getByRole("button", { name: "Discard exception edits", exact: true })
      .click();
    await p
      .getByLabel("Import exception draft file", { exact: true })
      .setInputFiles({
        name: file.name,
        mimeType: "application/json",
        buffer: file.bytes,
      });
    await expect(p).toContainText("Imported exception draft.");
    const provenance = p.getByLabel("Imported exception provenance", {
      exact: true,
    });
    await provenance.locator("summary").click();
    await expect(provenance).toContainText(file.name);
    await expect(provenance).toContainText(file.value.id);
    await expect(
      p.getByRole("button", {
        name: "Export reviewed exceptions",
        exact: true,
      }),
    ).toBeDisabled();
    await chooseWorkspaceTask(page, "Program");
    await chooseWorkspaceTask(page, "Schedules");
    p = panel(page);
    await expect(p).toContainText(file.value.id);
    await expect(input()).toHaveValue("-0");
    await reviewed(page);
    expect((await downloaded(page)).bytes).toEqual(file.bytes);
    expect(field).toEqual([]);
    expect(
      (await (await request.get("/api/session")).json()).field_network_open,
    ).toBe(false);
    expect(file.value.source.capture_id).toBe(captures[0].id);
    await page.setViewportSize({ width: 390, height: 1100 });
    await p
      .getByLabel("Exception event priority", { exact: true })
      .scrollIntoViewIfNeeded();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: info.outputPath("exception-editor-phone.png"),
      fullPage: true,
    });
  });
test("String exception text preserves invalid editor input, Unicode controls and explicit Null separately", async ({
  page,
  request,
}) => {
  const { captures, field } = await setup(page, request, true);
  await open(page, captures[2]);
  const p = panel(page),
    input = p.getByLabel("Exception time 1 value", { exact: true });
  await input.fill('"\\u');
  await chooseWorkspaceTask(page, "Program");
  await chooseWorkspaceTask(page, "Schedules");
  await expect(input).toHaveValue('"\\u');
  await p
    .getByLabel("Exception time 1 kind", { exact: true })
    .selectOption("Null");
  await expect(input).toHaveValue("null");
  await p
    .getByLabel("Exception time 1 kind", { exact: true })
    .selectOption("CharacterString");
  await expect(input).toHaveValue('"\\u');
  const text = "\x00é🌡";
  await input.fill(JSON.stringify(text));
  await reviewed(page);
  const file = await downloaded(page);
  expect(file.value.request.events[0].transitions[0].value_text).toBe(text);
  expect(file.value.new.encoded_hex).toBe(
    "0e0cff021dff0f2eb4091e000075080000c3a9f09f8ca12f39081c018000022eb4091e000074006f6c642f3908",
  );
  expect(field).toEqual([]);
});
test("date ranges, newer weekday patterns, references, ordering and empty arrays are local native values", async ({
  page,
  request,
}) => {
  const { field } = await setup(page, request);
  const p = panel(page);
  await p
    .getByLabel("Exception period", { exact: true })
    .selectOption("dateRange");
  for (const [side, day, weekday] of [
    ["start", "2", "1"],
    ["end", "4", "3"],
  ]) {
    await p
      .getByLabel(`Exception range ${side} year`, { exact: true })
      .fill("2026");
    for (const [part, value] of [
      ["month", "11"],
      ["day", day],
      ["weekday", weekday],
    ])
      await p
        .getByLabel(`Exception range ${side} ${part}`, { exact: true })
        .selectOption(value);
  }
  await p
    .getByRole("button", { name: "Add exception event", exact: true })
    .click();
  await p
    .getByLabel("Exception period", { exact: true })
    .selectOption("weekNDay");
  for (const [part, value] of [
    ["month", "*"],
    ["week", "7"],
    ["weekday", "1"],
  ])
    await p
      .getByLabel(`Exception ${part}`, { exact: true })
      .selectOption(value);
  await p.getByLabel("Exception event priority", { exact: true }).fill("16");
  await p
    .getByRole("button", { name: "Add exception event", exact: true })
    .click();
  await p
    .getByLabel("Exception period", { exact: true })
    .selectOption("calendarReference");
  await p
    .getByLabel("Exception Calendar reference", { exact: true })
    .fill("calendar,20");
  await p
    .getByRole("button", { name: "Move exception earlier", exact: true })
    .click();
  await reviewed(page);
  const document = await downloaded(page);
  expect(
    document.value.request.events.map((row: any) => row.period.kind),
  ).toEqual([
    "dateRange",
    "calendarReference",
    "calendarReference",
    "weekNDay",
  ]);
  expect(document.value.new.minimum_known_protocol_revision).toBe(18);
  expect(document.value.controller_queries).toBe(false);
  while (
    await p
      .getByRole("button", { name: "Remove selected exception", exact: true })
      .count()
  )
    await p
      .getByRole("button", { name: "Remove selected exception", exact: true })
      .click();
  await reviewed(page);
  expect((await downloaded(page)).value.new.encoded_hex).toBe("");
  expect(field).toEqual([]);
});
for (const action of ["draft ABA", "source ABA", "task", "visibility"] as const)
  test(`late exception review retires on ${action}`, async ({
    page,
    request,
  }) => {
    const { captures } = await setup(page, request);
    const p = panel(page);
    await p.getByLabel("Exception time 1 value", { exact: true }).fill("-0");
    let release!: () => void, arrived!: () => void;
    const began = new Promise<void>((resolve) => (arrived = resolve)),
      gate = new Promise<void>((resolve) => (release = resolve));
    await page.route("**" + BASE + "/review", async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      arrived();
      await gate;
      await route.fulfill({ response });
    });
    await p
      .getByRole("button", { name: "Review exception draft", exact: true })
      .click();
    await began;
    if (action === "draft ABA") {
      await p.getByLabel("Exception time 1 value", { exact: true }).fill("3");
      await p.getByLabel("Exception time 1 value", { exact: true }).fill("-0");
    } else if (action === "source ABA") {
      await open(page, captures[1]);
      await open(page, captures[0]);
    } else if (action === "task") {
      await chooseWorkspaceTask(page, "Program");
      await chooseWorkspaceTask(page, "Schedules");
    } else
      await page.evaluate(() =>
        document.dispatchEvent(new Event("visibilitychange")),
      );
    const response = page.waitForResponse((r) =>
      r.url().endsWith(BASE + "/review"),
    );
    release();
    await (await response).finished();
    await expect(
      panel(page).getByRole("region", {
        name: "Native exception draft review",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      panel(page).getByRole("button", {
        name: "Export reviewed exceptions",
        exact: true,
      }),
    ).toBeDisabled();
    await expect(
      panel(page).getByLabel("Exception time 1 value", { exact: true }),
    ).toHaveValue("-0");
  });

test("captured modern exception periods remain editable while legacy weekly eligibility stays separate", async ({
  page,
  request,
}) => {
  const { captures, field } = await setup(page, request);
  await open(page, captures[3]);
  const p = panel(page);
  await expect(p.getByLabel("Exception week", { exact: true })).toHaveValue(
    "7",
  );
  await reviewed(page);
  const document = await downloaded(page);
  expect(document.value.diff.changed).toBe(false);
  expect(document.value.new.minimum_known_protocol_revision).toBe(18);
  expect(document.value.old.encoded_hex).toBe(document.value.new.encoded_hex);
  expect(field).toEqual([]);
});

for (const substituted of ["source", "request", "wire"] as const)
  test(`substituted exception ${substituted} proof cannot enable export`, async ({
    page,
    request,
  }) => {
    await setup(page, request);
    const p = panel(page);
    await p.getByLabel("Exception time 1 value", { exact: true }).fill("-0");
    await page.route("**" + BASE + "/review", async (route) => {
      const response = await route.fetch({ maxRetries: 0 }),
        data = await response.json();
      if (substituted === "source") data.source.target.address = "192.0.2.200";
      else if (substituted === "request") data.request.events[0].priority = 1;
      else
        data.new.encoded_hex = data.new.encoded_hex.replace(
          "4480000000",
          "4400000000",
        );
      await route.fulfill({ response, json: data });
    });
    await p
      .getByRole("button", { name: "Review exception draft", exact: true })
      .click();
    await expect(p.getByRole("alert")).toContainText(
      substituted === "wire" ? "native bytes differ" : "review differs",
    );
    await expect(
      p.getByRole("button", {
        name: "Export reviewed exceptions",
        exact: true,
      }),
    ).toBeDisabled();
    await expect(
      p.getByLabel("Exception time 1 value", { exact: true }),
    ).toHaveValue("-0");
  });

for (const kind of ["import", "export"] as const)
  test(`late exception ${kind} cannot replace later work or download obsolete evidence`, async ({
    page,
    request,
  }) => {
    const { captures, token } = await setup(page, request);
    const p = panel(page);
    const source = await (
        await request.post(BASE + "/source", {
          headers: token,
          data: { id: captures[0].id },
        })
      ).json(),
      draft = {
        capture_id: captures[0].id,
        object_id: "schedule,1",
        events: source.schedules[0].events,
      },
      checked = await (
        await request.post(BASE + "/review", { headers: token, data: draft })
      ).json(),
      exported = await request.post(BASE + "/export", {
        headers: token,
        data: { draft, expected_review_id: checked.id },
      }),
      bytes = await exported.body();
    let importText = "";
    if (kind === "import") {
      const proved = await request.post(BASE + "/import", {
        headers: token,
        multipart: {
          file: {
            name: "held-exceptions.json",
            mimeType: "application/json",
            buffer: bytes,
          },
        },
      });
      expect(proved.ok(), await proved.text()).toBe(true);
      importText = await proved.text();
    } else await reviewed(page);
    let release!: () => void, arrived!: () => void;
    const began = new Promise<void>((resolve) => (arrived = resolve)),
      gate = new Promise<void>((resolve) => (release = resolve));
    await page.route("**" + BASE + "/" + kind, async (route) => {
      const response =
        kind === "export" ? await route.fetch({ maxRetries: 0 }) : null;
      arrived();
      await gate;
      if (response) await route.fulfill({ response });
      else
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: importText,
        });
    });
    const downloads: string[] = [];
    page.on("download", (file) => downloads.push(file.suggestedFilename()));
    if (kind === "import")
      await p
        .getByLabel("Import exception draft file", { exact: true })
        .setInputFiles({
          name: "held-exceptions.json",
          mimeType: "application/json",
          buffer: bytes,
        });
    else
      await p
        .getByRole("button", {
          name: "Export reviewed exceptions",
          exact: true,
        })
        .click();
    await began;
    await p.getByLabel("Exception time 1 value", { exact: true }).fill("-0");
    const response = page.waitForResponse((r) =>
      r.url().endsWith(BASE + "/" + kind),
    );
    release();
    await (await response).finished();
    await expect(
      p.getByLabel("Exception time 1 value", { exact: true }),
    ).toHaveValue("-0");
    await expect(
      p.getByRole("region", {
        name: "Native exception draft review",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(p).not.toContainText("Imported exception draft");
    // Observe the completed reply's download outcome; this does not change a field deadline.
    await page.waitForTimeout(100);
    expect(downloads).toEqual([]);
  });

async function known(page: Page, index: number, initial = false) {
  if (initial) {
    await page.goto("/");
    await page
      .getByRole("button", { name: /^Connect to a controller/ })
      .click();
  } else
    await page
      .getByRole("button", { name: "Change controller", exact: true })
      .click();
  await page
    .getByRole("button", { name: "Known controller address", exact: true })
    .click();
  for (const [label, value] of [
    ["Known controller address", "192.0.2." + (index + 1)],
    ["Known Device object", "device," + (7000 + index)],
    ["Known router", ""],
    ["Known network", ""],
  ])
    await page.getByLabel(label, { exact: true }).fill(value);
  await page
    .getByRole("region", { name: "Known controller connection", exact: true })
    .getByRole("button", { name: "Open controller", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Controller overview", exact: true }),
  ).toContainText("Authored context " + index);
  await chooseWorkspaceTask(page, "Schedules");
}
test("selected-controller ABA retains local exception work and retires a held export", async ({
  page,
  request,
}) => {
  const { captures } = await setup(page, request);
  await page.route("**/api/bacnet/status", (route) =>
    route.fulfill({
      json: {
        connected: true,
        config: {
          transport: "ip",
          local_address: "127.0.0.1:59997",
          instance: 4190001,
          router: null,
          dnet: null,
        },
        commands: [],
      },
    }),
  );
  await page.route("**/api/bacnet/device-details", (route) => {
    const body = route.request().postDataJSON(),
      index = Number(body.device.split(",")[1]) - 7000;
    return route.fulfill({
      json: {
        identity_verified: true,
        address: body.address,
        properties: {
          "object-identifier": body.device,
          "object-name": "Authored context " + index,
          "model-name": "Authored HTTP identity",
        },
        finished_at: new Date().toISOString(),
      },
    });
  });
  await known(page, 0, true);
  await open(page, captures[0]);
  const p = panel(page);
  await p.getByLabel("Exception time 1 value", { exact: true }).fill("-0");
  await reviewed(page);
  let release!: () => void, arrived!: () => void;
  const began = new Promise<void>((resolve) => (arrived = resolve)),
    gate = new Promise<void>((resolve) => (release = resolve));
  await page.route("**" + BASE + "/export", async (route) => {
    const response = await route.fetch({ maxRetries: 0 });
    arrived();
    await gate;
    await route.fulfill({ response });
  });
  const downloads: string[] = [];
  page.on("download", (file) => downloads.push(file.suggestedFilename()));
  await p
    .getByRole("button", { name: "Export reviewed exceptions", exact: true })
    .click();
  await began;
  await known(page, 1);
  await known(page, 0);
  await open(page, captures[0]);
  const response = page.waitForResponse((r) =>
    r.url().endsWith(BASE + "/export"),
  );
  release();
  await (await response).finished();
  await expect(
    panel(page).getByLabel("Exception time 1 value", { exact: true }),
  ).toHaveValue("-0");
  await expect(
    panel(page).getByRole("button", {
      name: "Export reviewed exceptions",
      exact: true,
    }),
  ).toBeDisabled();
  await page.waitForTimeout(100);
  expect(downloads).toEqual([]);
  expect(
    (await (await request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
});
