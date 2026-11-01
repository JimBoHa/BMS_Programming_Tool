import { test, expect, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import { chooseWorkspaceTask } from "./workspace-navigation";

const root = path.resolve("..");
function seed(invalid = false) {
  const state = process.env.BMS_TEST_COMPILER_STATE;
  if (!state) throw new Error("An isolated state directory is required.");
  return JSON.parse(
    execFileSync(
      path.join(root, ".venv/bin/python"),
      [
        "-c",
        `
import sys,json,secrets
from bms_tool.app import create_app
from tests.test_native_ledger_details import recovery_record,malformed_recovery
from tests.test_change_ledger import native
a=create_app(sys.argv[1]);child,parent=recovery_record(a,(lambda b:malformed_recovery(b,'compilation')) if sys.argv[2]=='invalid' else None,parent_outcome='unknown')
other=native(a,id=secrets.token_hex(16),change_kind='boolean-default',new_instance=123,default_edit={'record_ref':'controller/actual-Boolean'})
wire=native(a,2,id=secrets.token_hex(16),change_kind='wire-source',new_instance=123,wire_edit={'diagram_ref':'controller/actual-diagram','wire_index':0})
s=a.state.native_applications.storage
s.resolve(child['id'],{'status':'verified','fixture':'Authored later observation; no controller traffic'})
for row in (other,wire):s.finish(row['id'],{'intent_sha256':row['evidence_sha256'],'status':'not_sent','may_have_applied':False})
print(json.dumps({'child':child['id'],'parent':parent,'boolean':other['id'],'wire':wire['id']}))
`,
        state,
        invalid ? "invalid" : "valid",
      ],
      {
        cwd: root,
        env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
        encoding: "utf8",
      },
    ),
  );
}
const records = (page: Page) =>
  page.getByRole("region", { name: "Recorded changes", exact: true });
const evidence = (page: Page) =>
  page.getByRole("region", { name: "Change evidence", exact: true });
const lineage = (page: Page) =>
  page.getByRole("region", {
    name: "Recorded native recovery lineage",
    exact: true,
  });
const details = (page: Page, id: string) =>
  records(page).getByRole("button", {
    name: "Details for native " + id,
    exact: true,
  });
async function open(page: Page) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "New application", exact: true })
    .click();
  await chooseWorkspaceTask(page, "Changes");
  await expect(records(page)).toBeVisible();
}

for (const width of [1440, 390]) {
  test(`actual native receipt fields, recovery search and original bytes at ${width}px`, async ({
    page,
    request,
  }, info) => {
    const data = seed();
    await page.setViewportSize({ width, height: 1100 });
    const fieldCalls: string[] = [];
    page.on("request", (r) => {
      if (
        r.method() === "POST" &&
        new URL(r.url()).pathname.startsWith("/api/bacnet/")
      )
        fieldCalls.push(r.url());
    });
    let original: Buffer | undefined;
    await page.route(
      "**/api/bacnet/controller/native-application/receipts/" + data.child,
      async (route) => {
        const response = await route.fetch({ maxRetries: 0 });
        expect(response.ok()).toBe(true);
        original = await response.body();
        await route.fulfill({ response });
      },
    );
    await open(page);
    await expect(records(page)).toContainText("controller/actual-Boolean");
    await expect(records(page)).toContainText("controller/actual-diagram");
    await expect(records(page)).toContainText("Connection 1 · wire index 0");
    const childRow = records(page)
      .getByRole("row")
      .filter({
        has: page.getByRole("button", {
          name: "Details for native " + data.child,
          exact: true,
        }),
      });
    await expect(childRow).toContainText("controller/signal-10");
    await expect(childRow).toContainText(
      "Previous-value recovery · parent " + data.parent,
    );
    await details(page, data.child).click();
    await expect(lineage(page)).toContainText(
      "controller/signal-10 · -0 to 42",
    );
    await expect(lineage(page)).toContainText("80000000 to 42280000");
    await expect(lineage(page)).toContainText("Later readback event");
    await expect(lineage(page)).toContainText("does not revalidate");
    await expect(evidence(page)).toContainText("127.0.0.1:47819");
    await expect(evidence(page)).toContainText("possible");
    await expect(
      evidence(page).getByRole("button", {
        name: "Download evidence JSON",
        exact: true,
      }),
    ).toBeVisible();
    const download = page.waitForEvent("download");
    await evidence(page)
      .getByRole("button", { name: "Download evidence JSON", exact: true })
      .click();
    expect(readFileSync((await (await download).path())!)).toEqual(original);
    await page.screenshot({
      path: info.outputPath("recorded-native-recovery.png"),
      fullPage: true,
    });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await lineage(page)
      .getByRole("button", {
        name: "Search recorded parent receipt",
        exact: true,
      })
      .click();
    await expect(
      page.getByLabel("Search recorded changes", { exact: true }),
    ).toHaveValue(data.parent);
    await expect(evidence(page)).toHaveCount(0);
    await expect(details(page, data.parent)).toBeVisible();
    await details(page, data.parent).click();
    await expect(evidence(page)).toContainText(data.parent);
    await expect(lineage(page)).toHaveCount(0);
    await expect(
      evidence(page).getByRole("button", {
        name: "Download evidence JSON",
        exact: true,
      }),
    ).toBeVisible();
    expect(fieldCalls).toEqual([]);
    expect(
      (await (await request.get("/api/session")).json()).field_network_open,
    ).toBe(false);
    const headers = {
      "X-Studio-Token": (await (await request.get("/api/session")).json())
        .token,
    };
    const report = await (
      await request.post("/api/changes/query", {
        headers,
        data: { source: "native", text: data.child },
      })
    ).json();
    expect(report.field_requests).toBe(0);
    expect(report.rows[0].dispatch).toBe("possible");
  });
}

test("malformed recovery metadata retains ordinary evidence without a parent action", async ({
  page,
}) => {
  const data = seed(true);
  await open(page);
  const childRow = records(page)
    .getByRole("row")
    .filter({
      has: page.getByRole("button", {
        name: "Details for native " + data.child,
        exact: true,
      }),
    });
  await expect(childRow).toContainText("Recovery metadata unavailable");
  await expect(childRow).toContainText("controller/signal-10");
  await details(page, data.child).click();
  await expect(lineage(page)).toContainText("incomplete or inconsistent");
  await expect(
    lineage(page).getByRole("button", {
      name: "Search recorded parent receipt",
      exact: true,
    }),
  ).toHaveCount(0);
  await expect(
    evidence(page).getByRole("button", {
      name: "Download evidence JSON",
      exact: true,
    }),
  ).toBeVisible();
});

test("parent search retires the original pending child document", async ({
  page,
}) => {
  const data = seed();
  let release!: () => void, entered!: () => void;
  const gate = new Promise<void>((resolve) => {
      release = resolve;
    }),
    seen = new Promise<void>((resolve) => {
      entered = resolve;
    });
  const childPath =
    "/api/bacnet/controller/native-application/receipts/" + data.child;
  await page.route("**" + childPath, async (route) => {
    const response = await route.fetch({ maxRetries: 0 });
    expect(response.ok()).toBe(true);
    entered();
    await gate;
    await route.fulfill({ response });
  });
  try {
    await open(page);
    await details(page, data.child).click();
    await seen;
    await expect(
      evidence(page).getByRole("button", {
        name: "Download evidence JSON",
        exact: true,
      }),
    ).toHaveCount(0);
    await lineage(page)
      .getByRole("button", {
        name: "Search recorded parent receipt",
        exact: true,
      })
      .click();
    await expect(details(page, data.parent)).toBeVisible();
    const completed = page.waitForResponse((r) => r.url().endsWith(childPath));
    release();
    await (await completed).finished();
    await expect(evidence(page)).toHaveCount(0);
    await details(page, data.parent).click();
    await expect(evidence(page)).toContainText(data.parent);
    await expect(lineage(page)).toHaveCount(0);
  } finally {
    release();
  }
});
