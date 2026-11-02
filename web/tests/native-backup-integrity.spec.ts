import { test, expect, type Page } from "./nativeScheduleWriteFixture";
import { readFileSync } from "node:fs";
import { python } from "./caf-native-fixture";
import { chooseWorkspaceSurface } from "./workspace-navigation";

const diagnostics = (page: Page) =>
  page.getByRole("region", {
    name: "Native backup storage inspection",
    exact: true,
  });
const selection = (page: Page) =>
  diagnostics(page).getByRole("region", {
    name: "Selected backup storage entry",
    exact: true,
  });
const result = (page: Page) =>
  diagnostics(page).getByLabel("Original backup integrity result", {
    exact: true,
  });

function seed(directory: string, mismatch = false, count = 3) {
  return JSON.parse(
    python(
      `
import sys,json,secrets,uuid,base64
from unittest.mock import patch
from bms_tool.storage import Store
from bms_tool.application_store import ApplicationStore
from tests.test_native_signal_compiler import retained
from tests.test_caf_native_correlation import caf_source
s=ApplicationStore(Store(sys.argv[1]));prefix=uuid.uuid4().hex[:8];counter=iter(range(64));original=secrets.token_hex
def token(n):return prefix+format(next(counter),'024x') if n==16 else original(n)
with patch('bms_tool.application_store.secrets.token_hex',side_effect=token):
 rows=[retained(s) for _ in range(int(sys.argv[3]))]
bad=s.directory/rows[2]['id'];(bad/'manifest.json').write_bytes(b'{authored incomplete manifest')
partial=prefix+'f'*24;(s.directory/partial).mkdir();(s.directory/partial/'file-3.bin').write_bytes(b'authored unpublished original')
unknown=prefix+'-operator-note';(s.directory/unknown).write_bytes(b'unrecognized entry, never interpreted')
if sys.argv[2]=='1':
 p=s.directory/rows[0]['id']/'file-3.bin';raw=p.read_bytes();p.write_bytes(bytes([raw[0]^1])+raw[1:])
 (s.directory/rows[0]['id']/'file-11.bin').unlink()
print(json.dumps({'prefix':prefix,'first':rows[0]['id'],'second':rows[1]['id'],'bad':rows[2]['id'],'partial':partial,'unknown':unknown,'caf':base64.b64encode(caf_source().original).decode()}))
`,
      directory,
      mismatch ? "1" : "0",
      String(count),
    ),
  );
}
async function history(page: Page) {
  await chooseWorkspaceSurface(page, "History");
  const navigation = page.getByRole("navigation", {
    name: "history tools",
    exact: true,
  });
  await expect(navigation).toBeVisible();
  const picker = navigation.getByRole("combobox");
  if (await picker.isVisible())
    await picker.selectOption({ label: "Native backups" });
  else
    await navigation
      .getByRole("button", { name: "Native backups", exact: true })
      .click();
}
async function enter(page: Page, data: ReturnType<typeof seed>, caf = false) {
  await page.goto("/");
  if (caf) {
    const chooser = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: /^Open a CAF file/ }).click();
    await (
      await chooser
    ).setFiles({
      name: "integrity-reference.caf",
      mimeType: "application/octet-stream",
      buffer: Buffer.from(data.caf, "base64"),
    });
    await expect(
      page.getByLabel("Current CAF archive", { exact: true }),
    ).toHaveText("integrity-reference.caf");
  } else
    await page
      .getByRole("button", { name: "New application", exact: true })
      .click();
  await history(page);
  await page
    .getByLabel("Backup storage diagnostics", { exact: true })
    .locator(":scope > summary")
    .click();
  await expect(diagnostics(page)).toBeVisible();
  await inspect(page, data.prefix);
}
async function inspect(page: Page, query: string) {
  await diagnostics(page)
    .getByLabel("Stored entry search", { exact: true })
    .fill(query);
  await diagnostics(page)
    .getByRole("button", { name: "Inspect backup storage", exact: true })
    .click();
  await expect(
    diagnostics(page).getByRole("table", {
      name: "Observed native backup storage entries",
      exact: true,
    }),
  ).toBeVisible();
}
async function choose(page: Page, id: string) {
  await diagnostics(page)
    .getByRole("button", { name: `Inspect stored entry ${id}`, exact: true })
    .click();
  await expect(
    selection(page).getByRole("heading", {
      name: `Stored entry ${id}`,
      exact: true,
    }),
  ).toBeVisible();
}
async function check(page: Page) {
  const response = page.waitForResponse((response) =>
    response.url().endsWith("/backup-library/check-originals"),
  );
  await selection(page)
    .getByRole("button", { name: "Check original backup files", exact: true })
    .click();
  const data = await (await response).json();
  await expect(result(page)).toBeVisible();
  return data;
}
function fieldCalls(page: Page) {
  const calls: string[] = [];
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      request.url().includes("/api/bacnet/") &&
      !/\/backup-library\/(list|storage-inventory|check-originals)$/.test(
        request.url(),
      )
    )
      calls.push(request.url());
  });
  return calls;
}

for (const caf of [false, true])
  for (const compact of [false, true])
    test(`storage diagnostics from ${caf ? "CAF" : "new application"} entry on ${compact ? "compact" : "desktop"} layout retain damaged originals and export exact observations`, async ({
      page,
      request,
      nativeScheduleWriteServer,
    }) => {
      const data = seed(nativeScheduleWriteServer.directory),
        calls = fieldCalls(page);
      if (compact) await page.setViewportSize({ width: 600, height: 1000 });
      await enter(page, data, caf);
      await expect(
        page.getByText(/Refresh backups to obtain their current catalog state/),
      ).toBeVisible();
      await expect(diagnostics(page)).toContainText("5 matching names");
      await choose(page, data.first);
      const document = await check(page);
      expect(document.capture_id).toBe(data.first);
      expect(document.integrity).toBe("matches_manifest");
      expect(document.files.map((file: any) => file.status)).toEqual([
        "matches",
        "matches",
        "matches",
      ]);
      await expect(result(page)).toContainText("Original files match manifest");
      await expect(result(page)).toContainText("not an atomic snapshot");
      const downloading = page.waitForEvent("download");
      await result(page)
        .getByRole("button", { name: "Export integrity report", exact: true })
        .click();
      const file = (await (await downloading).path())!;
      expect(JSON.parse(readFileSync(file, "utf8"))).toEqual(document);
      for (const id of [data.bad, data.partial, data.unknown]) {
        await choose(page, id);
        await expect(selection(page)).toContainText(
          "Retain this original entry",
        );
        await expect(
          selection(page).getByRole("button", {
            name: "Check original backup files",
            exact: true,
          }),
        ).toHaveCount(0);
        await expect(result(page)).toHaveCount(0);
        await expect(
          selection(page).getByRole("button", {
            name: /archive|restore|delete|apply/i,
          }),
        ).toHaveCount(0);
      }
      await page.screenshot({
        path: test.info().outputPath("storage-inspection.png"),
        fullPage: true,
      });
      expect(calls).toEqual([]);
      expect(
        (await (await request.get("/api/session")).json()).field_network_open,
      ).toBe(false);
    });

test("changed and missing payloads remain separate failures with no repair or field dispatch", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const data = seed(nativeScheduleWriteServer.directory, true),
    calls = fieldCalls(page);
  await enter(page, data);
  await choose(page, data.first);
  const document = await check(page);
  expect(document.integrity).toBe("incomplete");
  expect(document.files.map((file: any) => file.status)).toEqual([
    "mismatch",
    "unavailable",
    "matches",
  ]);
  await expect(result(page)).toContainText("Original files incomplete");
  const again = await check(page);
  expect(again.files).toEqual(document.files);
  expect(calls).toEqual([]);
});

for (const boundary of ["source", "ABA", "close", "navigation", "visibility"])
  test(`held original-file check cannot survive ${boundary} changes`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const data = seed(nativeScheduleWriteServer.directory),
      calls = fieldCalls(page);
    await enter(page, data);
    await choose(page, data.first);
    let entered!: () => void, release!: () => void;
    const held = new Promise<void>((resolve) => {
      entered = resolve;
    });
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    await page.route(
      "**/api/bacnet/controller/native-application/backup-library/check-originals",
      async (route) => {
        const response = await route.fetch();
        entered();
        await gate;
        await route.fulfill({ response });
      },
    );
    try {
      await selection(page)
        .getByRole("button", {
          name: "Check original backup files",
          exact: true,
        })
        .click();
      await held;
      if (boundary === "source" || boundary === "ABA") {
        await choose(page, data.second);
        if (boundary === "ABA") await choose(page, data.first);
      } else if (boundary === "close") {
        await page
          .getByLabel("Backup storage diagnostics", { exact: true })
          .locator(":scope > summary")
          .click();
        await expect(diagnostics(page)).toHaveCount(0);
      } else if (boundary === "navigation") {
        await chooseWorkspaceSurface(page, "Workspace");
        await expect(diagnostics(page)).toHaveCount(0);
      } else {
        await page.evaluate(() =>
          document.dispatchEvent(new Event("visibilitychange")),
        );
        await expect(diagnostics(page).getByRole("table")).toHaveCount(0);
      }
      const finished = page.waitForResponse((response) =>
        response.url().endsWith("/backup-library/check-originals"),
      );
      release();
      await (await finished).finished();
      if (boundary === "close")
        await page
          .getByLabel("Backup storage diagnostics", { exact: true })
          .locator(":scope > summary")
          .click();
      else if (boundary === "navigation") {
        await history(page);
        await page
          .getByLabel("Backup storage diagnostics", { exact: true })
          .locator(":scope > summary")
          .click();
      }
      await expect(result(page)).toHaveCount(0);
      if (["close", "navigation", "visibility"].includes(boundary)) {
        await inspect(page, data.prefix);
        await choose(page, data.second);
      }
      await page.unroute(
        "**/api/bacnet/controller/native-application/backup-library/check-originals",
      );
      const fresh = await check(page);
      expect(fresh.capture_id).toBe(
        boundary === "ABA" ? data.first : data.second,
      );
      expect(calls).toEqual([]);
    } finally {
      release();
    }
  });

test("a substituted integrity source is rejected without exposing an export", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const data = seed(nativeScheduleWriteServer.directory);
  await enter(page, data);
  await choose(page, data.first);
  await page.route(
    "**/api/bacnet/controller/native-application/backup-library/check-originals",
    async (route) => {
      const response = await route.fetch(),
        body = await response.json();
      await route.fulfill({
        response,
        json: { ...body, capture_id: data.second },
      });
    },
  );
  await selection(page)
    .getByRole("button", { name: "Check original backup files", exact: true })
    .click();
  await expect(diagnostics(page).getByRole("alert")).toContainText(
    "does not match the selected original source",
  );
  await expect(result(page)).toHaveCount(0);
  await expect(
    selection(page).getByRole("button", {
      name: "Export integrity report",
      exact: true,
    }),
  ).toHaveCount(0);
});

test("inventory pages and exact-name searches read actual bounded stored entries", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const data = seed(nativeScheduleWriteServer.directory, false, 33);
  await enter(page, data);
  const table = diagnostics(page).getByRole("table", {
    name: "Observed native backup storage entries",
    exact: true,
  });
  const names = () =>
    table.locator("tbody tr td:first-child button").allTextContents();
  await expect(table.locator("tbody tr")).toHaveCount(16);
  const first = await names();
  for (const offset of [16, 32]) {
    const response = page.waitForResponse((r) =>
      r.url().endsWith("/backup-library/storage-inventory"),
    );
    await diagnostics(page)
      .getByRole("button", { name: "Next storage page", exact: true })
      .click();
    expect((await (await response).json()).offset).toBe(offset);
    await expect(table.locator("tbody tr")).toHaveCount(offset === 16 ? 16 : 3);
    const next = await names();
    expect(next.every((name) => !first.includes(name))).toBe(true);
    first.push(...next);
  }
  expect(new Set(first).size).toBe(35);
  await expect(
    diagnostics(page).getByRole("button", {
      name: "Next storage page",
      exact: true,
    }),
  ).toBeDisabled();
  await diagnostics(page)
    .getByRole("button", { name: "Previous storage page", exact: true })
    .click();
  await expect(table.locator("tbody tr")).toHaveCount(16);
  await inspect(page, data.second);
  await expect(table.locator("tbody tr")).toHaveCount(1);
  await choose(page, data.second);
  expect((await check(page)).capture_id).toBe(data.second);
});

test("storage entry bound is visible and never claims an exhaustive inventory", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  python(
    `
import sys
from bms_tool.storage import Store
from bms_tool.application_store import ApplicationStore
s=ApplicationStore(Store(sys.argv[1]))
for i in range(1153):(s.directory/format(i,'032x')).mkdir(exist_ok=True)
`,
    nativeScheduleWriteServer.directory,
  );
  await page.goto("/");
  await page
    .getByRole("button", { name: "New application", exact: true })
    .click();
  await history(page);
  await page
    .getByLabel("Backup storage diagnostics", { exact: true })
    .locator(":scope > summary")
    .click();
  await inspect(page, "");
  await expect(diagnostics(page).getByRole("alert")).toContainText(
    "Inspection stopped at 1152 entries",
  );
  await expect(diagnostics(page)).toContainText(
    "Additional entries were not inspected",
  );
  await expect(diagnostics(page)).toContainText("1152 observed entries");
});
