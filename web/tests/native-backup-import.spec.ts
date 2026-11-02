import {
  test,
  expect,
  type Page,
  type APIRequestContext,
} from "./nativeScheduleWriteFixture";
import { python } from "./caf-native-fixture";
import { chooseWorkspaceSurface } from "./workspace-navigation";
import { nativeDefaultPeer } from "./native-default-peer";
import { freePort } from "./workflow-peer";

const base = "/api/bacnet/controller/native-application";
const region = (page: Page) =>
  page.getByRole("region", { name: "Native backup library", exact: true });
const selected = (page: Page) =>
  page.getByRole("region", { name: "Selected native backup", exact: true });
function original() {
  return JSON.parse(
    python(`
import tempfile,json,base64
from bms_tool.storage import Store
from bms_tool.application_store import ApplicationStore
from tests.test_native_signal_compiler import retained
from tests.test_caf_native_correlation import caf_source
s=ApplicationStore(Store(tempfile.mkdtemp(prefix='bms-original-export-')))
m=retained(s,target={'address':'3001:7','router':'127.0.0.1:49000','dnet':3001})
print(json.dumps({'manifest':m,'zip':base64.b64encode(s.export(m['id'])).decode(),'caf':base64.b64encode(caf_source().original).decode()}))
`),
  );
}
const upload = (data: any, name = "portable-original.zip") => ({
  name,
  mimeType: "application/zip",
  buffer: Buffer.from(data.zip, "base64"),
});
async function headers(request: APIRequestContext) {
  return {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
}
async function openLibrary(page: Page) {
  await chooseWorkspaceSurface(page, "History");
  const navigation = page.getByRole("navigation", {
      name: "history tools",
      exact: true,
    }),
    picker = navigation.getByRole("combobox");
  if (await picker.isVisible())
    await picker.selectOption({ label: "Native backups" });
  else
    await navigation
      .getByRole("button", { name: "Native backups", exact: true })
      .click();
  await expect(
    region(page).getByRole("button", { name: "Refresh backups", exact: true }),
  ).toBeEnabled();
}
async function enter(page: Page, data: any, caf = false) {
  await page.goto("/");
  if (caf) {
    const chooser = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: /^Open a CAF file/ }).click();
    await (
      await chooser
    ).setFiles({
      name: "preserved-application.caf",
      mimeType: "application/octet-stream",
      buffer: Buffer.from(data.caf, "base64"),
    });
    await expect(
      page.getByLabel("Current CAF archive", { exact: true }),
    ).toHaveText("preserved-application.caf");
  } else
    await page
      .getByRole("button", { name: "New application", exact: true })
      .click();
  await openLibrary(page);
}
async function importFile(page: Page, data: any) {
  await region(page)
    .getByLabel("Import native backup ZIP", { exact: true })
    .setInputFiles(upload(data));
  await expect(region(page)).toContainText("Original backup imported locally.");
  await expect(
    region(page).getByRole("button", { name: "Refresh backups", exact: true }),
  ).toBeEnabled();
}
async function pick(page: Page, data: any) {
  await region(page)
    .getByRole("button", {
      name: "Select backup " + data.manifest.id.slice(0, 8),
      exact: true,
    })
    .click();
  await expect(selected(page)).toContainText(
    "Imported historical copy from portable-original.zip",
  );
}

for (const caf of [false, true])
  test(`${caf ? "CAF" : "new application"} imports genuine multipart ZIP, preserves originals, repeats and archives`, async ({
    page,
    request,
  }) => {
    const data = original(),
      forbidden: string[] = [];
    page.on("request", (r) => {
      if (
        /\/api\/bacnet\/(connect|controller\/native-application\/(capture|preview|apply|readback))$/.test(
          r.url(),
        )
      )
        forbidden.push(r.url());
    });
    await enter(page, data, caf);
    await importFile(page, data);
    await pick(page, data);
    await expect(selected(page)).toContainText(
      "3001:7 via 127.0.0.1:49000 / DNET 3001",
    );
    await expect(selected(page)).toContainText(
      "No current controller identity, compatibility or transfer authority is established.",
    );
    const downloading = page.waitForEvent("download");
    await selected(page)
      .getByRole("button", {
        name: "Download original backup ZIP",
        exact: true,
      })
      .click();
    const filename = await (await downloading).path();
    const exported = JSON.parse(
      python(
        `import sys,json,zipfile,hashlib
with zipfile.ZipFile(sys.argv[1]) as z: print(json.dumps({'members':sorted(z.namelist()),'manifest':json.loads(z.read('manifest.json')),'files':{k:hashlib.sha256(z.read(f'file-{k}.bin')).hexdigest() for k in ('3','11','12')}}))`,
        filename!,
      ),
    );
    expect(exported.members).toEqual([
      "file-11.bin",
      "file-12.bin",
      "file-3.bin",
      "manifest.json",
    ]);
    expect(exported.manifest).toEqual(data.manifest);
    for (const key of ["3", "11", "12"])
      expect(exported.files[key]).toBe(data.manifest.files[key].sha256);
    await region(page)
      .getByLabel("Import native backup ZIP", { exact: true })
      .setInputFiles(upload(data));
    await expect(region(page)).toContainText(
      "Original backup already present.",
    );
    await expect(
      region(page).getByRole("button", { name: /^Select backup / }),
    ).toHaveCount(1);
    await pick(page, data);
    await selected(page)
      .getByRole("button", { name: "Archive local backup", exact: true })
      .click();
    await expect(region(page)).toContainText("Backup archived locally.");
    await region(page)
      .getByLabel("Backup list", { exact: true })
      .selectOption("archived");
    await expect(
      region(page).getByRole("button", {
        name: "Refresh backups",
        exact: true,
      }),
    ).toBeEnabled();
    await region(page)
      .getByLabel("Import native backup ZIP", { exact: true })
      .setInputFiles(upload(data));
    await expect(region(page)).toContainText(
      "Original backup already present.",
    );
    await pick(page, data);
    expect(forbidden).toEqual([]);
    expect(
      (await (await request.get("/api/session")).json()).field_network_open,
    ).toBe(false);
    if (caf) {
      await chooseWorkspaceSurface(page, "Workspace");
      await expect(
        page.getByLabel("Current CAF archive", { exact: true }),
      ).toHaveText("preserved-application.caf");
    }
  });

test("invalid ZIP and local byte cap preserve selected originals and send no oversized request", async ({
  page,
}) => {
  const data = original();
  await enter(page, data);
  await importFile(page, data);
  await pick(page, data);
  await region(page)
    .getByLabel("Import native backup ZIP", { exact: true })
    .setInputFiles({
      name: "truncated.zip",
      mimeType: "application/zip",
      buffer: upload(data).buffer.subarray(0, -20),
    });
  await expect(region(page).getByRole("alert")).toContainText(
    "cannot be safely interpreted",
  );
  await expect(selected(page)).toContainText(data.manifest.device);
  const calls: string[] = [];
  page.on("request", (r) => {
    if (r.url().endsWith(base + "/backup-library/import")) calls.push(r.url());
  });
  await region(page)
    .getByLabel("Import native backup ZIP", { exact: true })
    .setInputFiles({
      name: "large.zip",
      mimeType: "application/zip",
      buffer: Buffer.alloc(8 * 1024 * 1024 + 1),
    });
  await expect(region(page).getByRole("alert")).toContainText("8 MiB");
  await expect(selected(page)).toContainText(data.manifest.device);
  expect(calls).toEqual([]);
});

for (const retirement of ["navigation", "visibility", "pagehide"])
  test(`completed local import reply retires after ${retirement}`, async ({
    page,
    request,
  }) => {
    const data = original();
    await enter(page, data);
    let release!: () => void, seen!: () => void;
    const gate = new Promise<void>((r) => (release = r)),
      entered = new Promise<void>((r) => (seen = r));
    await page.route("**" + base + "/backup-library/import", async (route) => {
      // Controlled known-file HTTP import tests response ownership; ordinary cases above test browser multipart.
      const response = await request.post(base + "/backup-library/import", {
        headers: await headers(request),
        multipart: { file: upload(data) },
      });
      expect(response.ok()).toBe(true);
      seen();
      await gate;
      await route.fulfill({ response });
    });
    await region(page)
      .getByLabel("Import native backup ZIP", { exact: true })
      .setInputFiles(upload(data));
    await entered;
    await expect(
      region(page).getByLabel("Import native backup ZIP", { exact: true }),
    ).toBeDisabled();
    if (retirement === "navigation")
      await chooseWorkspaceSurface(page, "Workspace");
    else if (retirement === "visibility")
      await page.evaluate(() =>
        document.dispatchEvent(new Event("visibilitychange")),
      );
    else await page.evaluate(() => window.dispatchEvent(new Event("pagehide")));
    const settled = page.waitForResponse((r) =>
      r.url().endsWith(base + "/backup-library/import"),
    );
    release();
    await (await settled).finished();
    await page.unroute("**" + base + "/backup-library/import");
    if (retirement === "navigation") await openLibrary(page);
    else {
      await expect(region(page)).not.toContainText(
        "Original backup imported locally.",
      );
      await region(page)
        .getByRole("button", { name: "Refresh backups", exact: true })
        .click();
    }
    await expect(
      region(page).getByRole("button", { name: /^Select backup / }),
    ).toHaveCount(1);
    await expect(selected(page)).toHaveCount(0);
    await expect(region(page)).not.toContainText(
      "Original backup imported locally.",
    );
  });

test("substituted import identity is rejected while actual local originals remain", async ({
  page,
  request,
}) => {
  const data = original();
  await enter(page, data);
  await page.route("**" + base + "/backup-library/import", async (route) => {
    const response = await request.post(base + "/backup-library/import", {
      headers: await headers(request),
      multipart: { file: upload(data) },
    });
    const body = await response.json();
    body.capture_id = "f".repeat(32);
    await route.fulfill({ response, json: body });
  });
  await region(page)
    .getByLabel("Import native backup ZIP", { exact: true })
    .setInputFiles(upload(data));
  await expect(region(page).getByRole("alert")).toContainText(
    "does not match this ZIP",
  );
  await expect(selected(page)).toHaveCount(0);
  await expect(region(page)).not.toContainText(
    "Original backup imported locally.",
  );
  await page.unroute("**" + base + "/backup-library/import");
  await region(page)
    .getByRole("button", { name: "Refresh backups", exact: true })
    .click();
  await pick(page, data);
});

test("phone import keeps focus, one primary action and original CAF context", async ({
  page,
}, info) => {
  const data = original();
  await page.setViewportSize({ width: 390, height: 844 });
  await enter(page, data, true);
  await importFile(page, data);
  await pick(page, data);
  const input = region(page).getByLabel("Import native backup ZIP", {
    exact: true,
  });
  await input.focus();
  await expect(input).toBeFocused();
  expect(await region(page).locator("button.primary:visible").count()).toBe(1);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: info.outputPath("native-import-phone.png"),
    fullPage: true,
  });
  await chooseWorkspaceSurface(page, "Workspace");
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("preserved-application.caf");
});

for (const routed of [false, true])
  test(`${routed ? "routed" : "direct"} connected import keeps exact selection and makes zero controller queries`, async ({
    page,
    request,
  }) => {
    const data = original(),
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
      await openLibrary(page);
      const before = await peer.command("stats");
      await importFile(page, data);
      await pick(page, data);
      const after = await peer.command("stats");
      expect(after.events).toEqual(before.events);
      expect(after.router_errors).toEqual([]);
      expect(
        (await (await request.get("/api/session")).json()).field_network_open,
      ).toBe(true);
      await chooseWorkspaceSurface(page, "Workspace");
      await expect(
        page.getByRole("region", { name: "Controller overview", exact: true }),
      ).toContainText("Authored controller");
      await expect(
        page.getByRole("region", { name: "Controller overview", exact: true }),
      ).toContainText(routed ? "3001:7" : peer.direct);
    } finally {
      await request.post("/api/bacnet/disconnect", {
        headers: await headers(request),
        data: {},
      });
      await peer.close();
    }
  });
