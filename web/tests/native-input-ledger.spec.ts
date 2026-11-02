import { test, expect, type Page } from "./nativeScheduleWriteFixture";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import {
  chooseWorkspaceTask,
  chooseWorkspaceSurface,
} from "./workspace-navigation";
const root = path.resolve("..");
const records = (p: Page) =>
  p.getByRole("region", { name: "Recorded changes", exact: true });
const details = (p: Page, id: string) =>
  records(p).getByRole("button", {
    name: "Details for native " + id,
    exact: true,
  });
const evidence = (p: Page) =>
  p.getByRole("region", { name: "Change evidence", exact: true });
const input = (p: Page) =>
  p.getByRole("region", {
    name: "Recorded native input configuration",
    exact: true,
  });
function seed(directory: string, invalid = false) {
  return JSON.parse(
    execFileSync(
      path.join(root, ".venv/bin/python"),
      [
        "-c",
        `
import asyncio,json,sys
from pathlib import Path
from tests.test_native_input_ledger import seed_input_records,authored_body
from tests.test_change_ledger import native
from bms_tool.app import create_app
rows=asyncio.run(seed_input_records(Path(sys.argv[1])))
result={'ids':[r['intent']['id'] for r in rows]}
if sys.argv[2]=='invalid':
 a=create_app(sys.argv[1]);body=authored_body();body['operation_profile']='future-input/2';intent=native(a,**body);result['invalid']=intent['id']
print(json.dumps(result))
`,
        directory,
        invalid ? "invalid" : "valid",
      ],
      {
        cwd: root,
        env: { ...process.env, PYTHONPATH: root + "/backend:" + root },
        encoding: "utf8",
      },
    ),
  );
}
async function open(page: Page, caf = false, history = false) {
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
        env: { ...process.env, PYTHONPATH: root + "/backend:" + root },
      },
    );
    await page
      .getByLabel("Open local CAF application", { exact: true })
      .setInputFiles({
        name: "input-ledger.caf",
        mimeType: "application/octet-stream",
        buffer,
      });
    await expect(
      page.getByLabel("Working context", { exact: true }),
    ).toContainText("input-ledger.caf");
  } else
    await page
      .getByRole("button", { name: "New application", exact: true })
      .click();
  if (history) {
    await chooseWorkspaceSurface(page, "History");
    const tools = page.getByRole("navigation", {
        name: "history tools",
        exact: true,
      }),
      select = tools.getByRole("combobox");
    if (await select.isVisible())
      await select.selectOption({ label: "Recorded changes" });
    else
      await tools
        .getByRole("button", { name: "Recorded changes", exact: true })
        .click();
  } else await chooseWorkspaceTask(page, "Changes");
  await page
    .getByLabel("Record family", { exact: true })
    .selectOption("native");
  await expect(records(page)).toContainText(
    "Native input configuration transfer",
  );
}
function traffic(page: Page) {
  const calls: string[] = [];
  page.on("request", (r) => {
    if (
      r.method() === "POST" &&
      new URL(r.url()).pathname.startsWith("/api/bacnet/")
    )
      calls.push(r.url());
  });
  return calls;
}
for (const width of [1440, 390])
  test(`actual input allocation/mode/removal and original JSON remain local at ${width}px`, async ({
    page,
    request,
    nativeScheduleWriteServer,
  }, info) => {
    const data = seed(nativeScheduleWriteServer.directory),
      calls = traffic(page);
    await page.setViewportSize({ width, height: 1100 });
    await open(page);
    for (const [index, label] of [
      "Allocate input",
      "Edit input mode/scaling",
      "Remove allocated input",
    ].entries()) {
      await details(page, data.ids[index]).click();
      await expect(input(page)).toContainText(label);
      await expect(input(page)).toContainText("analog-input,3000010 · UI IN1");
      await expect(input(page)).toContainText("controller/0_3000010");
      await expect(input(page)).toContainText("No backup/parent revalidation");
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await expect(
        evidence(page).getByRole("button", {
          name: "Open input tools",
          exact: true,
        }),
      ).toBeEnabled();
      if (index < 2)
        await expect(
          input(page).getByRole("table", {
            name: "Requested and compiled input configuration",
            exact: true,
          }),
        ).toBeVisible();
      if (index === 2) await expect(input(page)).toContainText(data.ids[0]);
      await evidence(page)
        .getByRole("button", { name: "Close evidence", exact: true })
        .click();
    }
    await details(page, data.ids[2]).click();
    const original = await request.get(
      "/api/bacnet/controller/native-application/receipts/" + data.ids[2],
    );
    expect(original.ok()).toBe(true);
    const download = page.waitForEvent("download");
    await evidence(page)
      .getByRole("button", { name: "Download evidence JSON", exact: true })
      .click();
    expect(readFileSync((await (await download).path())!)).toEqual(
      await original.body(),
    );
    await input(page).scrollIntoViewIfNeeded();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: info.outputPath("native-input-ledger.png"),
      fullPage: true,
    });
    await input(page)
      .getByRole("button", {
        name: "Search recorded allocation receipt",
        exact: true,
      })
      .click();
    await expect(
      page.getByLabel("Search recorded changes", { exact: true }),
    ).toHaveValue(data.ids[0]);
    await expect(details(page, data.ids[0])).toBeVisible();
    expect(calls).toEqual([]);
    expect(
      (await (await request.get("/api/session")).json()).field_network_open,
    ).toBe(false);
  });

for (const { caf, width } of [
  { caf: false, width: 1440 },
  { caf: true, width: 1440 },
  { caf: true, width: 390 },
])
  test(`${caf ? "CAF History" : "graph Changes"} at ${width}px opens local input tools without selecting or connecting to a controller`, async ({
    page,
    request,
    nativeScheduleWriteServer,
  }) => {
    const data = seed(nativeScheduleWriteServer.directory),
      calls = traffic(page);
    await page.setViewportSize({ width, height: 1100 });
    await open(page, caf, caf);
    await details(page, data.ids[0]).click();
    await evidence(page)
      .getByRole("button", { name: "Open input tools", exact: true })
      .click();
    await expect(
      page.getByRole("region", {
        name: "Native input configuration",
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      page.getByRole("region", {
        name: "Native input configuration",
        exact: true,
      }),
    ).toContainText("No controller selected.");
    if (caf)
      await expect(
        page.getByLabel("Working context", { exact: true }),
      ).toContainText("input-ledger.caf");
    expect(calls).toEqual([]);
    expect(
      (await (await request.get("/api/session")).json()).field_network_open,
    ).toBe(false);
  });

test("unknown input profile remains readable without structured metadata or a tool link", async ({
  page,
  request,
  nativeScheduleWriteServer,
}) => {
  const data = seed(nativeScheduleWriteServer.directory, true),
    calls = traffic(page);
  await open(page);
  await details(page, data.invalid).click();
  await expect(input(page)).toContainText("Input metadata unavailable");
  await expect(
    evidence(page).getByRole("button", {
      name: "Open input tools",
      exact: true,
    }),
  ).toHaveCount(0);
  const pending = page.waitForEvent("download");
  await evidence(page)
    .getByRole("button", { name: "Download evidence JSON", exact: true })
    .click();
  const actual = readFileSync((await (await pending).path())!);
  expect(JSON.parse(actual.toString()).intent.operation_profile).toBe(
    "future-input/2",
  );
  expect(calls).toEqual([]);
  expect(
    (await (await request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
});

test("a substituted input metadata shape cannot create a tool link", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const data = seed(nativeScheduleWriteServer.directory),
    calls = traffic(page);
  await page.route("**/api/changes/query", async (route) => {
    const reply = await route.fetch({ maxRetries: 0, maxRedirects: 0 }),
      body = await reply.json();
    for (const row of body.rows)
      if (row.native_input?.state === "recorded") row.native_input.slot = "1";
    await route.fulfill({ response: reply, json: body });
  });
  await open(page);
  await details(page, data.ids[0]).click();
  await expect(input(page)).toContainText("Input metadata unavailable");
  await expect(
    evidence(page).getByRole("button", {
      name: "Open input tools",
      exact: true,
    }),
  ).toHaveCount(0);
  expect(calls).toEqual([]);
});
