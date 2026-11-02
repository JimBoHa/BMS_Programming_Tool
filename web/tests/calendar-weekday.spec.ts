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

for (const caf of [false, true])
  test(`explicit weekday assistance preserves ${caf ? "CAF" : "graph"} source fields and native export`, async ({
    page,
    request,
  }, info) => {
    const { fieldCalls, captures } = await setup(page, request, caf);
    const action = button(page, "Set matching weekday for Calendar entry 1");
    await expect(action).toBeDisabled();
    await date(page, "Calendar entry 1");
    await expect(control(page, "Calendar entry 1 weekday")).toHaveValue("*");
    await expect(action).toBeEnabled();
    await review(page);
    const oldReview = await document(page);
    expect(oldReview.value.new.entries[0].date).toEqual([126, 11, 2, 255]);
    await action.focus();
    await page.keyboard.press("Enter");
    await expect(control(page, "Calendar entry 1 weekday")).toHaveValue("1");
    await expect(action).toBeDisabled();
    await expect(reviewed(page)).toHaveCount(0);
    await expect(button(page, "Export reviewed Calendar draft")).toBeDisabled();
    await expect(control(page, "Calendar entry 1 year")).toHaveValue("2026");
    await expect(control(page, "Calendar entry 1 month")).toHaveValue("11");
    await expect(control(page, "Calendar entry 1 day")).toHaveValue("2");
    await review(page);
    const next = await document(page);
    expect(next.value.source.capture_id).toBe(captures[0].id);
    expect(next.value.new.entries[0].date).toEqual([126, 11, 2, 1]);
    expect(next.value.new.entries.slice(1)).toEqual(
      oldReview.value.new.entries.slice(1),
    );
    expect(next.value.old.encoded_hex).toBe(oldReview.value.old.encoded_hex);
    expect(next.value.request.entries[0].date).toEqual([126, 11, 2, 1]);
    await chooseWorkspaceTask(page, "Program");
    await chooseWorkspaceTask(page, "Schedules");
    await open(page, captures[0]);
    await expect(control(page, "Calendar entry 1 weekday")).toHaveValue("1");
    await expect(reviewed(page)).toHaveCount(0);
    await page.setViewportSize({ width: 390, height: 1000 });
    await action.scrollIntoViewIfNeeded();
    const box = await action.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(390);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: info.outputPath("calendar-weekday-phone.png"),
      fullPage: true,
    });
    expect(fieldCalls).toEqual([]);
  });

test("wildcard, special, impossible and unfinished date fields stay unchanged until an explicit valid action", async ({
  page,
  request,
}) => {
  const { fieldCalls, captures } = await setup(page, request);
  const action = button(page, "Set matching weekday for Calendar entry 1");
  for (const [year, month, day] of [
    ["*", "11", "2"],
    ["20", "11", "2"],
    ["1900", "2", "29"],
    ["2100", "2", "29"],
    ["2026", "13", "2"],
    ["2026", "11", "32"],
  ]) {
    await control(page, "Calendar entry 1 year").fill(year);
    await control(page, "Calendar entry 1 month").selectOption(month);
    await control(page, "Calendar entry 1 day").selectOption(day);
    await control(page, "Calendar entry 1 weekday").selectOption("*");
    await expect(action).toBeDisabled();
    await expect(control(page, "Calendar entry 1 year")).toHaveValue(year);
    await expect(control(page, "Calendar entry 1 month")).toHaveValue(month);
    await expect(control(page, "Calendar entry 1 day")).toHaveValue(day);
    await expect(control(page, "Calendar entry 1 weekday")).toHaveValue("*");
  }
  await control(page, "Calendar entry 1 year").fill("20");
  await chooseWorkspaceTask(page, "Program");
  await chooseWorkspaceTask(page, "Schedules");
  await open(page, captures[0]);
  await expect(control(page, "Calendar entry 1 year")).toHaveValue("20");
  await expect(action).toBeDisabled();
  await control(page, "Calendar entry 1 year").fill("2000");
  await control(page, "Calendar entry 1 month").selectOption("2");
  await control(page, "Calendar entry 1 day").selectOption("29");
  await action.click();
  await expect(control(page, "Calendar entry 1 weekday")).toHaveValue("2");
  await review(page);
  expect((await document(page)).value.new.entries[0].date).toEqual([
    100, 2, 29, 2,
  ]);
  expect(fieldCalls).toEqual([]);
});

for (const kind of ["calendar", "exception"])
  test(`${kind} date range endpoints receive only their explicitly selected weekdays`, async ({
    page,
    request,
  }) => {
    const { fieldCalls, captures } = await setup(page, request);
    let p = editor(page),
      start = "Calendar entry 2 start",
      end = "Calendar entry 2 end";
    if (kind === "exception") {
      const details = library(page).getByLabel("Captured Schedule exceptions", {
        exact: true,
      });
      await details.locator("summary").click();
      p = page.getByRole("region", {
        name: "Captured Schedule exception editor",
        exact: true,
      });
      await expect(
        p.getByLabel("Captured Schedule for exceptions", { exact: true }),
      ).toHaveValue("schedule,1");
      await p
        .getByLabel("Exception period", { exact: true })
        .selectOption("dateRange");
      start = "Exception range start";
      end = "Exception range end";
    }
    for (const [prefix, day] of [
      [start, "2"],
      [end, "4"],
    ]) {
      await p.getByLabel(prefix + " year", { exact: true }).fill("2026");
      await p.getByLabel(prefix + " month", { exact: true }).selectOption("11");
      await p.getByLabel(prefix + " day", { exact: true }).selectOption(day);
      await p
        .getByLabel(prefix + " weekday", { exact: true })
        .selectOption("*");
    }
    await p
      .getByRole("button", {
        name: "Set matching weekday for " + start,
        exact: true,
      })
      .click();
    await expect(p.getByLabel(start + " weekday", { exact: true })).toHaveValue(
      "1",
    );
    await expect(p.getByLabel(end + " weekday", { exact: true })).toHaveValue(
      "*",
    );
    await p
      .getByRole("button", {
        name: "Set matching weekday for " + end,
        exact: true,
      })
      .click();
    await expect(p.getByLabel(end + " weekday", { exact: true })).toHaveValue(
      "3",
    );
    const reviewName =
      kind === "calendar" ? "Review Calendar dates" : "Review exception draft";
    const exportName =
      kind === "calendar"
        ? "Export reviewed Calendar draft"
        : "Export reviewed exceptions";
    await p.getByRole("button", { name: reviewName, exact: true }).click();
    await expect(
      p.getByRole("button", { name: exportName, exact: true }),
    ).toBeEnabled();
    const downloaded = page.waitForEvent("download");
    await p.getByRole("button", { name: exportName, exact: true }).click();
    const result = JSON.parse(
      readFileSync((await (await downloaded).path())!).toString(),
    );
    const period =
      kind === "calendar" ? result.new.entries[1] : result.new.events[0].period;
    expect(period).toEqual({
      kind: "dateRange",
      start: [126, 11, 2, 1],
      end: [126, 11, 4, 3],
    });
    expect(result.source.capture_id).toBe(captures[0].id);
    expect(fieldCalls).toEqual([]);
  });
