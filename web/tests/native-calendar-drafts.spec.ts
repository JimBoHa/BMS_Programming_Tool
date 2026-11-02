import {
  test,
  expect,
  type APIRequestContext,
  type Page,
} from "@playwright/test";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import {
  chooseWorkspaceSurface,
  chooseWorkspaceTask,
} from "./workspace-navigation";
import {
  openScheduleController,
  scheduleTracePeer,
} from "./schedule-trace-peer";

const root = path.resolve(".."),
  LIB = "/api/bacnet/schedules/library",
  BASE = LIB + "/calendar";
const OLD = "0cff0d20ff1ea4ff0101ffa4ff0c1fff1f2bff0607";
const NEW = "0c7e0b02ff1ea47e0b02ffa47e0b04ff1f2bff06072bff0701";
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
from tests.test_native_schedule_library import acquire
from bms_tool.native_schedule_library import NativeScheduleLibrary,encoded
with tempfile.TemporaryDirectory() as temporary:
 report,_,_=asyncio.run(acquire(Path(temporary)/'peer',routed=sys.argv[1]=='1'))
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
async function document(page: Page) {
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
test.afterEach(async ({ request }) => {
  expect(
    (await (await request.get("/api/bacnet/status")).json()).connected,
  ).toBe(false);
});

test("offline Calendar source, all three native choices and exact export use real local APIs", async ({
  page,
  request,
}) => {
  const { captures, fieldCalls, headers } = await setup(page, request);
  await expect(control(page, "Calendar entry 1 year")).toHaveValue("*");
  await expect(control(page, "Calendar entry 1 month")).toHaveValue("13");
  await expect(control(page, "Calendar entry 1 day")).toHaveValue("32");
  await expect(control(page, "Calendar entry 2 type")).toHaveValue("dateRange");
  await expect(control(page, "Calendar entry 3 week")).toHaveValue("6");
  await review(page);
  const original = await document(page);
  expect(original.value.old.encoded_hex).toBe(OLD);
  expect(original.value.new.encoded_hex).toBe(OLD);
  expect(original.value.diff.changed).toBe(false);
  await date(page, "Calendar entry 1");
  await date(page, "Calendar entry 2 start");
  await date(page, "Calendar entry 2 end", "4");
  await button(page, "Add Calendar entry").click();
  await control(page, "Calendar entry 4 type").selectOption("weekNDay");
  await control(page, "Calendar entry 4 month").selectOption("*");
  await control(page, "Calendar entry 4 week").selectOption("7");
  await control(page, "Calendar entry 4 weekday").selectOption("1");
  await review(page);
  await expect(reviewed(page)).toContainText("protocol revision 18 or later");
  const exported = await document(page);
  expect(exported.value.new.encoded_hex).toBe(NEW);
  expect(exported.value.source.capture_id).toBe(captures[0].id);
  expect(exported.value.diff.other_properties_changed).toBe(false);
  expect(exported.value.field_writes).toBe(false);
  const response = await request.post(BASE + "/export", {
    headers,
    data: {
      draft: exported.value.request,
      expected_review_id: exported.value.id,
    },
  });
  expect(response.ok()).toBe(true);
  expect(await response.body()).toEqual(exported.bytes);
  expect(exported.name).toBe(`native-calendar-draft-${exported.value.id}.json`);
  expect(fieldCalls).toEqual([]);
});

test("Calendar edits preserve an independent existing weekly-day review and its literal negative zero", async ({
  page,
  request,
}) => {
  const { fieldCalls } = await setup(page, request);
  const weekly = library(page).getByLabel("Native weekly day editor", {
    exact: true,
  });
  await weekly
    .getByLabel("Transition 1 exact value text", { exact: true })
    .fill("-0.0");
  await weekly
    .getByRole("button", { name: "Review native weekly draft", exact: true })
    .click();
  const weeklyReview = weekly.getByLabel("Native weekly draft review", {
    exact: true,
  });
  await expect(weeklyReview).toBeVisible();
  const exportWeekly = async () => {
    const pending = page.waitForEvent("download");
    await weeklyReview
      .getByRole("button", {
        name: "Export exact reviewed weekly draft",
        exact: true,
      })
      .click();
    return readFileSync((await (await pending).path())!);
  };
  const first = await exportWeekly();
  expect(JSON.parse(first.toString()).new.encoded_hex).toBe(
    "0eb40800000044800000000f",
  );
  const original = await weeklyReview.textContent();
  await date(page, "Calendar entry 1");
  await review(page);
  await document(page);
  await expect(weeklyReview).toHaveText(original!);
  expect(await exportWeekly()).toEqual(first);
  expect(fieldCalls).toEqual([]);
});

test("unfinished source-specific drafts survive task, surface and capture ABA without restoring reviews", async ({
  page,
  request,
}) => {
  const { captures, fieldCalls } = await setup(page, request);
  await review(page);
  await control(page, "Calendar entry 1 year").fill("20");
  await expect(button(page, "Export reviewed Calendar draft")).toBeDisabled();
  await chooseWorkspaceTask(page, "Program");
  await chooseWorkspaceTask(page, "Schedules");
  await expect(control(page, "Calendar entry 1 year")).toHaveValue("20");
  await expect(reviewed(page)).toHaveCount(0);
  await chooseWorkspaceSurface(page, "Library");
  await chooseWorkspaceSurface(page, "Workspace");
  await chooseWorkspaceTask(page, "Schedules");
  await expect(control(page, "Calendar entry 1 year")).toHaveValue("20");
  await open(page, captures[1]);
  await control(page, "Calendar entry 1 year").fill("203");
  await open(page, captures[0]);
  await expect(control(page, "Calendar entry 1 year")).toHaveValue("20");
  await open(page, captures[1]);
  await expect(control(page, "Calendar entry 1 year")).toHaveValue("203");
  await button(page, "Discard Calendar edits").click();
  await expect(control(page, "Calendar entry 1 year")).toHaveValue("*");
  await open(page, captures[0]);
  await expect(control(page, "Calendar entry 1 year")).toHaveValue("20");
  expect(fieldCalls).toEqual([]);
});

test("empty Calendar lists and repeated dates retain their exact value and order", async ({
  page,
  request,
}) => {
  const { fieldCalls } = await setup(page, request);
  for (let count = 3; count; count--)
    await button(page, "Remove Calendar entry 1").click();
  await review(page);
  expect((await document(page)).value.new.encoded_hex).toBe("");
  for (let i = 1; i <= 2; i++) {
    await button(page, "Add Calendar entry").click();
    await date(page, `Calendar entry ${i}`);
  }
  await review(page);
  const repeated = await document(page);
  expect(repeated.value.new.encoded_hex).toBe("0c7e0b02ff0c7e0b02ff");
  expect(repeated.value.new.entries[0]).toEqual(repeated.value.new.entries[1]);
  expect(fieldCalls).toEqual([]);
});

test("local validation refuses incomplete and impossible dates while retaining raw work", async ({
  page,
  request,
}) => {
  const { fieldCalls } = await setup(page, request);
  await control(page, "Calendar entry 1 year").fill("20");
  await button(page, "Review Calendar dates").click();
  await expect(editor(page).getByRole("alert")).toContainText("1900–2154");
  await expect(control(page, "Calendar entry 1 year")).toHaveValue("20");
  await date(page, "Calendar entry 1", "30");
  await control(page, "Calendar entry 1 month").selectOption("2");
  await button(page, "Review Calendar dates").click();
  await expect(editor(page).getByRole("alert")).toBeVisible();
  await expect(button(page, "Export reviewed Calendar draft")).toBeDisabled();
  await expect(control(page, "Calendar entry 1 day")).toHaveValue("30");
  await date(page, "Calendar entry 1");
  await review(page);
  expect((await document(page)).value.new.entries[0].date).toEqual([
    126, 11, 2, 255,
  ]);
  expect(fieldCalls).toEqual([]);
});

test("late review cannot return after capture ABA or visibility retirement", async ({
  page,
  request,
}) => {
  const { captures, fieldCalls } = await setup(page, request);
  let release!: () => void, received!: () => void;
  const gate = new Promise<void>((resolve) => (release = resolve)),
    ready = new Promise<void>((resolve) => (received = resolve));
  await page.route(
    "**" + BASE + "/review",
    async (route) => {
      const response = await route.fetch();
      received();
      await gate;
      await route.fulfill({ response });
    },
    { times: 1 },
  );
  try {
    await button(page, "Review Calendar dates").click();
    await ready;
    await open(page, captures[1]);
    await open(page, captures[0]);
    release();
    await expect(button(page, "Review Calendar dates")).toBeEnabled();
    await page.waitForTimeout(150);
    await expect(reviewed(page)).toHaveCount(0);
    await review(page);
    await page.evaluate(() =>
      document.dispatchEvent(new Event("visibilitychange")),
    );
    await expect(reviewed(page)).toHaveCount(0);
    await button(page, "Refresh captured Calendars").click();
    await expect(control(page, "Calendar entry 1 year")).toHaveValue("*");
    await expect(button(page, "Export reviewed Calendar draft")).toBeDisabled();
  } finally {
    release();
  }
  expect(fieldCalls).toEqual([]);
});

for (const retire of ["edit", "task"] as const)
  test(`late exact export is suppressed after ${retire}`, async ({
    page,
    request,
  }) => {
    const { fieldCalls } = await setup(page, request);
    await review(page);
    const downloads: string[] = [];
    page.on("download", (file) => downloads.push(file.suggestedFilename()));
    let release!: () => void,
      received!: () => void,
      finished = false;
    const gate = new Promise<void>((resolve) => (release = resolve)),
      ready = new Promise<void>((resolve) => (received = resolve));
    await page.route(
      "**" + BASE + "/export",
      async (route) => {
        const response = await route.fetch();
        received();
        await gate;
        await route.fulfill({ response });
        finished = true;
      },
      { times: 1 },
    );
    try {
      await button(page, "Export reviewed Calendar draft").click();
      await ready;
      if (retire === "edit")
        await control(page, "Calendar entry 1 year").fill("20");
      else {
        await chooseWorkspaceTask(page, "Program");
        await chooseWorkspaceTask(page, "Schedules");
      }
      release();
      await expect.poll(() => finished).toBe(true);
      await page.waitForTimeout(150);
      expect(downloads).toEqual([]);
      await expect(
        button(page, "Export reviewed Calendar draft"),
      ).toBeDisabled();
    } finally {
      release();
    }
    expect(fieldCalls).toEqual([]);
  });

test("imports restore only the matching captured Calendar and require another review", async ({
  page,
  request,
}) => {
  const { captures, headers, fieldCalls } = await setup(page, request);
  const draft = {
    capture_id: captures[0].id,
    object_id: "calendar,1",
    entries: [{ kind: "date", date: [126, 11, 2, 255] }],
  };
  const response = await request.post(BASE + "/review", {
    headers,
    data: draft,
  });
  expect(response.ok()).toBe(true);
  const buffer = await response.body(),
    value = JSON.parse(buffer.toString());
  const upload = () =>
    control(page, "Import Calendar draft file").setInputFiles({
      name: "calendar.json",
      mimeType: "application/json",
      buffer,
    });
  await upload();
  await expect(editor(page).getByRole("status")).toContainText(value.id);
  await expect(control(page, "Calendar entry 1 year")).toHaveValue("2026");
  await expect(control(page, "Calendar entry 2 type")).toHaveCount(0);
  await expect(button(page, "Export reviewed Calendar draft")).toBeDisabled();
  await review(page);
  expect((await document(page)).value).toEqual(value);
  await open(page, captures[1]);
  await upload();
  await expect(editor(page).getByRole("alert")).toContainText("does not match");
  await expect(control(page, "Calendar entry 1 year")).toHaveValue("*");
  const changed = {
    ...value,
    new: { ...value.new, encoded_hex: "0c7e0b03ff" },
  };
  await control(page, "Import Calendar draft file").setInputFiles({
    name: "altered.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(changed)),
  });
  await expect(editor(page).getByRole("alert")).toBeVisible();
  await open(page, captures[0]);
  await expect(control(page, "Calendar entry 1 year")).toHaveValue("2026");
  expect(fieldCalls).toEqual([]);
});

test("late imports cannot replace raw work after a capture changes", async ({
  page,
  request,
}) => {
  const { captures, headers, fieldCalls } = await setup(page, request);
  const response = await request.post(BASE + "/review", {
    headers,
    data: { capture_id: captures[0].id, object_id: "calendar,1", entries: [] },
  });
  expect(response.ok()).toBe(true);
  const buffer = await response.body();
  await control(page, "Calendar entry 1 year").fill("204");
  let release!: () => void,
    received!: () => void,
    finished = false;
  const gate = new Promise<void>((resolve) => (release = resolve)),
    ready = new Promise<void>((resolve) => (received = resolve));
  await page.route(
    "**" + BASE + "/import",
    async (route) => {
      const response = await route.fetch();
      received();
      await gate;
      await route.fulfill({ response });
      finished = true;
    },
    { times: 1 },
  );
  try {
    await control(page, "Import Calendar draft file").setInputFiles({
      name: "calendar.json",
      mimeType: "application/json",
      buffer,
    });
    await ready;
    await open(page, captures[1]);
    release();
    await expect.poll(() => finished).toBe(true);
    await page.waitForTimeout(150);
    await expect(control(page, "Calendar entry 1 year")).toHaveValue("*");
    await open(page, captures[0]);
    await expect(control(page, "Calendar entry 1 year")).toHaveValue("204");
    await expect(
      editor(page).getByText(/Imported local Calendar review/),
    ).toHaveCount(0);
    await expect(button(page, "Export reviewed Calendar draft")).toBeDisabled();
  } finally {
    release();
  }
  expect(fieldCalls).toEqual([]);
});

for (const mismatch of ["target", "rules"] as const)
  test(`a substituted ${mismatch} cannot authorize a Calendar export`, async ({
    page,
    request,
  }) => {
    const { fieldCalls } = await setup(page, request);
    await page.route(
      "**" + BASE + "/review",
      async (route) => {
        const response = await route.fetch(),
          value = await response.json();
        if (mismatch === "target") value.source.target.address = "192.0.2.99";
        else value.rules_sha256 = "0".repeat(64);
        await route.fulfill({ response, json: value });
      },
      { times: 1 },
    );
    await button(page, "Review Calendar dates").click();
    await expect(editor(page).getByRole("alert")).toContainText(
      "does not match",
    );
    await expect(button(page, "Export reviewed Calendar draft")).toBeDisabled();
    await review(page);
    expect(fieldCalls).toEqual([]);
  });

test("a selected routed controller keeps its identity separate from an offline Calendar source", async ({
  page,
  request,
}) => {
  const peer = await scheduleTracePeer(true);
  const headers = await auth(request);
  try {
    const response = await request.post(LIB + "/import", {
      headers,
      multipart: {
        file: {
          name: "calendar.json",
          mimeType: "application/json",
          buffer: archives()[0],
        },
      },
    });
    expect(response.ok()).toBe(true);
    const capture = await response.json();
    await openScheduleController(page, request, peer, true);
    await open(page, capture);
    await expect(page.locator(".workflow-target-row")).toContainText("3001:7");
    await expect(editor(page)).toContainText(capture.target.address);
    const before = peer.reads();
    await date(page, "Calendar entry 1");
    await review(page);
    await document(page);
    expect(peer.reads()).toBe(before);
    await expect(page.locator(".workflow-target-row")).toContainText("3001:7");
  } finally {
    expect(
      (
        await request.post("/api/bacnet/disconnect", { headers, data: {} })
      ).ok(),
    ).toBe(true);
    await peer.stop();
  }
});

test("compact CAF entry keeps readable Calendar controls and the open file without field access", async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 600, height: 1000 });
  const { fieldCalls } = await setup(page, request, true);
  await date(page, "Calendar entry 1");
  await review(page);
  await expect(page.getByLabel("Working context")).toContainText(
    "calendar-work.caf",
  );
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth <=
        document.documentElement.clientWidth + 1,
    ),
  ).toBe(true);
  const sizes = await editor(page)
    .locator("input:not([type=file]),select")
    .evaluateAll((nodes) =>
      nodes.map((node) => ({
        label: node.getAttribute("aria-label"),
        height: node.getBoundingClientRect().height,
        font: parseFloat(getComputedStyle(node).fontSize),
      })),
    );
  expect(sizes.length).toBeGreaterThan(10);
  await test.info().attach("Calendar control geometry", {
    body: JSON.stringify(sizes, null, 2),
    contentType: "application/json",
  });
  await page.screenshot({
    path: test.info().outputPath("calendar-compact.png"),
    fullPage: true,
  });
  expect(sizes.every((size) => size.height >= 36 && size.font >= 14)).toBe(
    true,
  );
  await chooseWorkspaceTask(page, "Program");
  await chooseWorkspaceTask(page, "Schedules");
  await expect(control(page, "Calendar entry 1 year")).toHaveValue("2026");
  await expect(reviewed(page)).toHaveCount(0);
  expect(fieldCalls).toEqual([]);
});
