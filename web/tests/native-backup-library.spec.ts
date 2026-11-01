import {
  test,
  expect,
  type Page,
  type APIRequestContext,
} from "@playwright/test";
import { python } from "./caf-native-fixture";
import { nativeDefaultPeer } from "./native-default-peer";
import { freePort } from "./workflow-peer";
import {
  chooseWorkspaceSurface,
  openNativeCompiler,
} from "./workspace-navigation";

const base = "/api/bacnet/controller/native-application";
const library = (page: Page) =>
  page.getByRole("region", { name: "Native backup library", exact: true });
const selected = (page: Page) =>
  page.getByRole("region", { name: "Selected native backup", exact: true });
function seed(count = 2) {
  return JSON.parse(
    python(
      `
import sys,json,base64
from bms_tool.storage import Store
from bms_tool.application_store import ApplicationStore
from tests.test_native_signal_compiler import retained
from tests.test_caf_native_correlation import caf_source
s=ApplicationStore(Store(sys.argv[1]))
rows=[retained(s,target={'address':f'3001:{i+1}','router':'127.0.0.1:49000','dnet':3001}) for i in range(int(sys.argv[2]))]
print(json.dumps({'rows':rows,'caf':base64.b64encode(caf_source().original).decode()}))
`,
      process.env.BMS_TEST_COMPILER_STATE!,
      String(count),
    ),
  );
}
async function headers(request: APIRequestContext) {
  return {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
}
async function transition(
  request: APIRequestContext,
  row: any,
  action = "archive",
  revision = 0,
) {
  const result = await request.post(base + "/backup-library/change", {
    headers: await headers(request),
    data: {
      capture_id: row.id,
      snapshot_sha256: row.evidence_sha256,
      expected_revision: revision,
      action,
    },
  });
  expect(result.ok()).toBe(true);
  return result.json();
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
  await expect(
    library(page).getByRole("button", { name: "Refresh backups", exact: true }),
  ).toBeEnabled();
}
async function enter(page: Page, data: ReturnType<typeof seed>, caf = false) {
  await page.goto("/");
  if (caf) {
    const chooser = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: /^Open a CAF file/ }).click();
    await (
      await chooser
    ).setFiles({
      name: "archive-reference.caf",
      mimeType: "application/octet-stream",
      buffer: Buffer.from(data.caf, "base64"),
    });
    await expect(
      page.getByLabel("Current CAF archive", { exact: true }),
    ).toHaveText("archive-reference.caf");
  } else
    await page
      .getByRole("button", { name: "New application", exact: true })
      .click();
  await history(page);
}
async function search(page: Page, query: string) {
  await library(page).getByLabel("Search backups", { exact: true }).fill(query);
  await library(page)
    .getByRole("button", { name: "Search backups", exact: true })
    .click();
  await expect(
    library(page).getByRole("button", { name: "Refresh backups", exact: true }),
  ).toBeEnabled();
}
async function pick(page: Page, row: any) {
  await search(page, row.id);
  await library(page)
    .getByRole("button", {
      name: "Select backup " + row.id.slice(0, 8),
      exact: true,
    })
    .click();
  await expect(selected(page)).toContainText(row.device);
}
test.beforeEach(async ({ request }) => {
  expect(
    (
      await request.post("/api/bacnet/disconnect", {
        headers: await headers(request),
        data: {},
      })
    ).ok(),
  ).toBe(true);
});

for (const caf of [false, true])
  test(`offline ${caf ? "CAF" : "new application"} entry archives, exports exact originals and restores selection`, async ({
    page,
    request,
  }) => {
    const data = seed(),
      row = data.rows[0],
      forbidden: string[] = [];
    page.on("request", (request) => {
      if (
        /\/api\/bacnet\/(connect|controller\/native-application\/(capture|apply|preview|readback))$/.test(
          request.url(),
        )
      )
        forbidden.push(request.url());
    });
    await enter(page, data, caf);
    await pick(page, row);
    await expect(selected(page)).toContainText(
      "via 127.0.0.1:49000 / DNET 3001",
    );
    await selected(page)
      .getByRole("button", { name: "Archive local backup", exact: true })
      .click();
    await expect(library(page)).toContainText("Backup archived locally.");
    await expect(
      library(page).getByRole("button", {
        name: "Select backup " + row.id.slice(0, 8),
        exact: true,
      }),
    ).toHaveCount(0);
    await library(page)
      .getByLabel("Backup list", { exact: true })
      .selectOption("archived");
    await expect(
      library(page).getByRole("button", {
        name: "Refresh backups",
        exact: true,
      }),
    ).toBeEnabled();
    await library(page)
      .getByRole("button", {
        name: "Select backup " + row.id.slice(0, 8),
        exact: true,
      })
      .click();
    const downloading = page.waitForEvent("download");
    await selected(page)
      .getByRole("button", {
        name: "Download original backup ZIP",
        exact: true,
      })
      .click();
    const download = await downloading,
      filename = await download.path();
    expect(download.suggestedFilename()).toBe(
      "native-backup-" + row.id + ".zip",
    );
    const zip = JSON.parse(
      python(
        "import sys,zipfile,json,hashlib\nwith zipfile.ZipFile(sys.argv[1]) as z: print(json.dumps({'manifest':json.loads(z.read('manifest.json')),'files':{k:hashlib.sha256(z.read(f'file-{k}.bin')).hexdigest() for k in ('3','11','12')}}))",
        filename!,
      ),
    );
    expect(zip.manifest).toEqual(row);
    for (const id of ["3", "11", "12"])
      expect(zip.files[id]).toBe(row.files[id].sha256);
    await selected(page)
      .getByRole("button", { name: "Restore to active backups", exact: true })
      .click();
    await expect(library(page)).toContainText(
      "Backup restored to the active list.",
    );
    await chooseWorkspaceSurface(page, "Workspace");
    await openNativeCompiler(page);
    await expect(
      page
        .getByLabel("Retained native backup", { exact: true })
        .locator(`option[value="${row.id}"]`),
    ).toHaveCount(1);
    if (caf)
      await expect(
        page.getByLabel("Current CAF archive", { exact: true }),
      ).toHaveText("archive-reference.caf");
    expect(forbidden).toEqual([]);
    expect(
      (await (await request.get("/api/session")).json()).field_network_open,
    ).toBe(false);
  });

test("search and real bounded pages retain exact route identity", async ({
  page,
}) => {
  const data = seed(35);
  await enter(page, data);
  await expect(
    library(page).getByRole("button", { name: /^Select backup / }),
  ).toHaveCount(32);
  await library(page)
    .getByRole("button", { name: "Next backups", exact: true })
    .click();
  await expect(
    library(page).getByRole("button", {
      name: "Previous backups",
      exact: true,
    }),
  ).toBeEnabled();
  await expect(
    library(page).getByRole("button", { name: "Refresh backups", exact: true }),
  ).toBeEnabled();
  const row = data.rows[0];
  await pick(page, row);
  await expect(
    library(page).getByRole("button", { name: /^Select backup / }),
  ).toHaveCount(1);
  await expect(selected(page)).toContainText(row.target.address);
  await search(page, "missing authored source");
  await expect(library(page)).toContainText("No matching backups.");
  await expect(selected(page)).toHaveCount(0);
});

test("archive and restore ABA in another session rejects the stale selection", async ({
  page,
  request,
}) => {
  const data = seed(),
    row = data.rows[0];
  await enter(page, data);
  await pick(page, row);
  await transition(request, row);
  await transition(request, row, "restore", 1);
  await selected(page)
    .getByRole("button", { name: "Archive local backup", exact: true })
    .click();
  await expect(library(page).getByRole("alert")).toContainText(
    "catalog changed",
  );
  await expect(selected(page)).toHaveCount(0);
  await library(page)
    .getByRole("button", { name: "Refresh backups", exact: true })
    .click();
  await expect(
    library(page).getByRole("button", {
      name: "Select backup " + row.id.slice(0, 8),
      exact: true,
    }),
  ).toBeVisible();
  await library(page)
    .getByRole("button", {
      name: "Select backup " + row.id.slice(0, 8),
      exact: true,
    })
    .click();
  await selected(page).locator("summary").click();
  await expect(selected(page).locator("pre")).toContainText('"revision": 2');
});

test("a response substituted after local archive cannot authorize another action", async ({
  page,
}) => {
  const data = seed(),
    row = data.rows[0];
  let calls = 0;
  await enter(page, data);
  await pick(page, row);
  await page.route("**" + base + "/backup-library/change", async (route) => {
    calls++;
    const response = await route.fetch(),
      body = await response.json();
    body.backup.id = data.rows[1].id;
    await route.fulfill({ response, json: body });
  });
  await selected(page)
    .getByRole("button", { name: "Archive local backup", exact: true })
    .click();
  await expect(library(page).getByRole("alert")).toContainText(
    "does not match",
  );
  await expect(selected(page)).toHaveCount(0);
  expect(calls).toBe(1);
  await page.unroute("**" + base + "/backup-library/change");
  await library(page)
    .getByRole("button", { name: "Refresh backups", exact: true })
    .click();
  await expect(
    library(page).getByRole("button", { name: "Refresh backups", exact: true }),
  ).toBeEnabled();
  await expect(
    library(page).getByRole("button", {
      name: "Select backup " + row.id.slice(0, 8),
      exact: true,
    }),
  ).toHaveCount(0);
});

for (const retirement of ["navigation", "visibility"])
  test(`delayed catalog reply retires across ${retirement}`, async ({
    page,
  }) => {
    const data = seed();
    await enter(page, data);
    await pick(page, data.rows[0]);
    let release!: () => void, seen!: () => void;
    const gate = new Promise<void>((resolve) => (release = resolve)),
      entered = new Promise<void>((resolve) => (seen = resolve));
    await page.route("**" + base + "/backup-library/list", async (route) => {
      const response = await route.fetch();
      seen();
      await gate;
      await route.fulfill({ response });
    });
    await library(page)
      .getByRole("button", { name: "Refresh backups", exact: true })
      .click();
    await entered;
    if (retirement === "navigation")
      await chooseWorkspaceSurface(page, "Workspace");
    else
      await page.evaluate(() =>
        document.dispatchEvent(new Event("visibilitychange")),
      );
    const response = page.waitForResponse((response) =>
      response.url().endsWith(base + "/backup-library/list"),
    );
    release();
    await (await response).finished();
    await page.unroute("**" + base + "/backup-library/list");
    if (retirement === "navigation") await history(page);
    else {
      await expect(library(page).getByRole("table")).toHaveCount(0);
      await library(page)
        .getByRole("button", { name: "Refresh backups", exact: true })
        .click();
    }
    await expect(library(page).getByRole("table")).toBeVisible();
    await expect(selected(page)).toHaveCount(0);
  });

test("phone catalog keeps labels, focus and local file through task navigation", async ({
  page,
}, info) => {
  const data = seed();
  await page.setViewportSize({ width: 390, height: 844 });
  await enter(page, data, true);
  await pick(page, data.rows[0]);
  const action = selected(page).getByRole("button", {
    name: "Archive local backup",
    exact: true,
  });
  await action.focus();
  await expect(action).toBeFocused();
  expect(
    await library(page).evaluate(
      (element) => getComputedStyle(element).fontSize,
    ),
  ).toBe("14px");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: info.outputPath("backup-phone.png"),
    fullPage: true,
  });
  await chooseWorkspaceSurface(page, "Workspace");
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("archive-reference.caf");
});

for (const routed of [false, true])
  test(`connected ${routed ? "routed" : "direct"} catalog action makes zero controller requests`, async ({
    page,
    request,
  }) => {
    const data = seed(),
      peer = await nativeDefaultPeer("consume", "instance");
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
        .getByRole("region", {
          name: "Known controller connection",
          exact: true,
        })
        .getByRole("button", { name: "Open controller", exact: true })
        .click();
      await expect(
        page.getByRole("region", { name: "Controller overview", exact: true }),
      ).toContainText("Authored controller");
      await history(page);
      await pick(page, data.rows[0]);
      const before = await peer.command("stats");
      await selected(page)
        .getByRole("button", { name: "Archive local backup", exact: true })
        .click();
      await expect(library(page)).toContainText("Backup archived locally.");
      const after = await peer.command("stats");
      expect(after.events).toEqual(before.events);
      expect(after.router_errors).toEqual([]);
      expect(
        (await (await request.get("/api/session")).json()).field_network_open,
      ).toBe(true);
    } finally {
      await request.post("/api/bacnet/disconnect", {
        headers: await headers(request),
        data: {},
      });
      await peer.close();
    }
  });
