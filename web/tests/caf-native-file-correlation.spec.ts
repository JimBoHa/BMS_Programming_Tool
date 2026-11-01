import { test, expect, type Page, type Locator } from "@playwright/test";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import {
  python,
  enterCafComparison,
  compatibility,
  chooseFile,
} from "./caf-native-fixture";
import { nativeDefaultPeer } from "./native-default-peer";
import { freePort } from "./workflow-peer";

function seed(direct = "127.0.0.1:47918", router = "127.0.0.1:47919") {
  return JSON.parse(
    python(
      `
import json,sys,base64
from bms_tool.storage import Store
from bms_tool.bacnet_files import BacnetFiles
from bms_tool.application_store import ApplicationStore
from tests.test_native_signal_compiler import retained
from tests.test_caf_native_correlation import caf_source
from tests.test_caf_native_file_correlation import retained_file
store=Store(sys.argv[1]);files=BacnetFiles(None,store)
a=retained_file(files,target={'address':sys.argv[2]},reuse=True)
b=retained_file(files,format_hint='.MoZ',target={'address':'3001:7'},config={'router':sys.argv[3],'dnet':3001},reuse=True)
serial=retained_file(files,format_hint='.bin',target={'address':'7'},config={'transport':'mstp','serial_port':'/dev/authored-only'},reuse=True)
opaque=retained_file(files,b'Authored opaque .moz bytes',format_hint='.moz',reuse=True)
native=retained(ApplicationStore(store))
print(json.dumps({'a':a['id'],'b':b['id'],'serial':serial['id'],'opaque':opaque['id'],'native':native['id'],
'caf':base64.b64encode(caf_source().original).decode(),
'other':base64.b64encode(caf_source(model='Another model').original).decode()}))
`,
      process.env.BMS_TEST_COMPILER_STATE!,
      direct,
      router,
    ),
  );
}
async function fileMode(p: Locator, id: string) {
  await p
    .getByLabel("Comparison source type", { exact: true })
    .selectOption("file");
  await p
    .getByLabel("Captured File for CAF comparison", { exact: true })
    .selectOption(id);
}
async function open(page: Page, ids: any) {
  const p = await enterCafComparison(page, ids.caf);
  await fileMode(p, ids.a);
  return p;
}
async function compare(p: Locator) {
  await p
    .getByRole("button", {
      name: "Compare original CAF and native archive",
      exact: true,
    })
    .click();
  const result = p.getByRole("region", {
    name: "CAF/native comparison result",
    exact: true,
  });
  await expect(result).toContainText(
    "Recorded identities equal within the checked scope",
  );
  return result;
}
const calls = new WeakMap<Page, string[]>();
test.beforeEach(async ({ page, request }) => {
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  expect(
    (await request.post("/api/bacnet/disconnect", { headers, data: {} })).ok(),
  ).toBe(true);
  const seen: string[] = [];
  calls.set(page, seen);
  page.on("request", (r) => {
    if (r.method() === "POST" && /\/api\/bacnet\//.test(r.url()))
      seen.push(r.url());
  });
});

test("offline File comparison verifies source bytes, independent provenance and exact report download", async ({
  page,
  request,
}, info) => {
  const ids = seed();
  await page.setViewportSize({ width: 820, height: 1100 });
  const p = await open(page, ids);
  let original = Buffer.alloc(0);
  await page.route("**/native-file-correlation", async (route) => {
    const response = await route.fetch({ maxRetries: 0 });
    original = await response.body();
    await route.fulfill({ response });
  });
  await p.getByLabel("Find comparison records", { exact: true }).press("Enter");
  const result = p.getByRole("region", {
    name: "CAF/native comparison result",
    exact: true,
  });
  await expect(result).toContainText(
    "Recorded File device identity agrees with archive: yes",
  );
  await expect(p).toContainText(
    "Paired saved-setting files and atomic-backup evidence are unavailable.",
  );
  const download = page.waitForEvent("download");
  await result
    .getByRole("button", { name: "Save exact source comparison", exact: true })
    .click();
  expect(readFileSync((await (await download).path())!)).toEqual(original);
  const data = JSON.parse(original.toString());
  expect(data.native_backup).toBeUndefined();
  expect(data.native_file.full_native_backup).toBe(false);
  expect(data.native_file.saved_settings_available).toBe(false);
  expect(data.request.capture_id).toBe(ids.a);
  expect(data.application_association_granted).toBe(false);
  expect(
    (await p
      .getByLabel("Comparison source type", { exact: true })
      .boundingBox())!.height,
  ).toBeGreaterThanOrEqual(36);
  await p.scrollIntoViewIfNeeded();
  await page.screenshot({
    path: info.outputPath("caf-native-file-comparison-820.png"),
  });
  expect(calls.get(page)).toEqual([]);
  expect(
    (await (await request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
});

test("actual native bytes compare through MoZ and serial-recorded source types without opening an interface", async ({
  page,
}) => {
  const ids = seed(),
    p = await open(page, ids);
  await p
    .getByLabel("Captured File for CAF comparison", { exact: true })
    .selectOption(ids.b);
  await compare(p);
  await expect(
    p.getByLabel("Comparison source station", { exact: true }),
  ).toContainText("network 3001");
  await p
    .getByLabel("Captured File for CAF comparison", { exact: true })
    .selectOption(ids.serial);
  await compare(p);
  await expect(
    p.getByLabel("Comparison source station", { exact: true }),
  ).toContainText("7 · device,5136");
  expect(calls.get(page)).toEqual([]);
});

test("opaque MoZ label never supplies a fabricated native program", async ({
  page,
}) => {
  const ids = seed(),
    p = await open(page, ids);
  await p
    .getByLabel("Captured File for CAF comparison", { exact: true })
    .selectOption(ids.opaque);
  await p
    .getByRole("button", {
      name: "Compare original CAF and native archive",
      exact: true,
    })
    .click();
  await expect(p.getByRole("alert")).toContainText("recognized tagged MOI");
  await expect(
    p.getByRole("region", {
      name: "CAF/native comparison result",
      exact: true,
    }),
  ).toHaveCount(0);
  expect(calls.get(page)).toEqual([]);
});

test("source type A B A retires a delayed File result and keeps each type's explicit selection", async ({
  page,
}) => {
  const ids = seed(),
    p = await open(page, ids);
  await p
    .getByLabel("Comparison source type", { exact: true })
    .selectOption("backup");
  await p
    .getByLabel("Native backup for CAF comparison", { exact: true })
    .selectOption(ids.native);
  await fileMode(p, ids.a);
  let release = () => {},
    started!: () => void;
  const gate = new Promise<void>((resolve) => {
      release = resolve;
    }),
    received = new Promise<void>((resolve) => {
      started = resolve;
    });
  await page.route(
    "**/native-file-correlation",
    async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      started();
      await gate;
      await route.fulfill({ response });
    },
    { times: 1 },
  );
  try {
    await p
      .getByRole("button", {
        name: "Compare original CAF and native archive",
        exact: true,
      })
      .click();
    await received;
    await p
      .getByLabel("Comparison source type", { exact: true })
      .selectOption("backup");
    await expect(
      p.getByLabel("Native backup for CAF comparison", { exact: true }),
    ).toHaveValue(ids.native);
    await p
      .getByLabel("Comparison source type", { exact: true })
      .selectOption("file");
    await expect(
      p.getByLabel("Captured File for CAF comparison", { exact: true }),
    ).toHaveValue(ids.a);
    release();
    await expect(
      p.getByRole("region", {
        name: "CAF/native comparison result",
        exact: true,
      }),
    ).toHaveCount(0);
    await compare(p);
    expect(calls.get(page)).toEqual([]);
  } finally {
    release();
  }
});

test("File comparison and CAF proposals retain separate provenance through navigation and source changes", async ({
  page,
}) => {
  const ids = seed(),
    p = await open(page, ids);
  await page
    .getByRole("navigation", { name: "CAF application tasks" })
    .getByRole("button", { name: "Objects & parameters", exact: true })
    .click();
  await page
    .locator(".caf-layout tbody tr")
    .filter({ hasText: "Authored controller" })
    .click();
  await page
    .getByLabel("CAF property 2390", { exact: true })
    .fill("Unexported File context name");
  await compatibility(page);
  await expect(p).toContainText("Local CAF proposals are excluded");
  await p.getByLabel("Find comparison records", { exact: true }).fill("signal");
  await compare(p);
  await page
    .getByRole("navigation", { name: "Workspace tasks" })
    .getByRole("button", { name: "Changes", exact: true })
    .click();
  await page
    .getByRole("navigation", { name: "Workspace tasks" })
    .getByRole("button", { name: "Program", exact: true })
    .click();
  await compatibility(page);
  await expect(
    p.getByRole("region", {
      name: "CAF/native comparison result",
      exact: true,
    }),
  ).toHaveCount(0);
  await expect(
    p.getByLabel("Comparison source type", { exact: true }),
  ).toHaveValue("file");
  await expect(
    p.getByLabel("Captured File for CAF comparison", { exact: true }),
  ).toHaveValue(ids.a);
  await expect(
    p.getByLabel("Find comparison records", { exact: true }),
  ).toHaveValue("signal");
  await page
    .getByRole("navigation", { name: "CAF application tasks" })
    .getByRole("button", { name: "Objects & parameters", exact: true })
    .click();
  await expect(
    page.getByLabel("CAF property 2390", { exact: true }),
  ).toHaveValue("Unexported File context name");
  expect(calls.get(page)).toEqual([]);
});

test("a replacement CAF cannot inherit the File selection or completed comparison", async ({
  page,
}) => {
  const ids = seed(),
    p = await open(page, ids);
  await compare(p);
  await chooseFile(page, ids.other, "other.caf");
  await compatibility(page);
  await expect(
    p.getByRole("region", {
      name: "CAF/native comparison result",
      exact: true,
    }),
  ).toHaveCount(0);
  await expect(
    p.getByLabel("Comparison source type", { exact: true }),
  ).toHaveValue("backup");
  await fileMode(p, ids.a);
  await p
    .getByRole("button", {
      name: "Compare original CAF and native archive",
      exact: true,
    })
    .click();
  await expect(
    p.getByRole("region", {
      name: "CAF/native comparison result",
      exact: true,
    }),
  ).toContainText("Recorded identity differences found");
  expect(calls.get(page)).toEqual([]);
});

for (const fault of [
  "receipt",
  "payload",
  "station",
  "backup",
  "settings",
  "digest",
]) {
  test(`altered File ${fault} evidence is refused`, async ({ page }) => {
    const ids = seed(),
      p = await open(page, ids);
    await page.route("**/native-file-correlation", async (route) => {
      const response = await route.fetch({ maxRetries: 0 }),
        data = await response.json();
      if (fault === "receipt") data.native_file.receipt_sha256 = "0".repeat(64);
      if (fault === "payload") data.native_file.sha256 = "0".repeat(64);
      if (fault === "station")
        data.native_file.target.address = "127.0.0.1:47999";
      if (fault === "backup") {
        data.native_file.full_native_backup = true;
        data.native_backup = data.native_file;
      }
      if (fault === "settings")
        data.native_file.saved_settings_available = true;
      const body = JSON.stringify(data),
        headers = { ...response.headers() };
      headers["x-studio-artifact-sha256"] =
        fault === "digest"
          ? "0".repeat(64)
          : createHash("sha256").update(body).digest("hex");
      await route.fulfill({ response, body, headers });
    });
    await p
      .getByRole("button", {
        name: "Compare original CAF and native archive",
        exact: true,
      })
      .click();
    await expect(p.getByRole("alert")).toContainText(
      "Comparison evidence does not match",
    );
    await expect(
      p.getByRole("region", {
        name: "CAF/native comparison result",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      p.getByRole("button", {
        name: "Save exact source comparison",
        exact: true,
      }),
    ).toHaveCount(0);
    expect(calls.get(page)).toEqual([]);
  });
}

test("routed controller context is reused while File comparison sends zero further BACnet requests", async ({
  page,
}) => {
  const peer = await nativeDefaultPeer();
  try {
    const ids = seed(peer.direct, peer.router);
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
      .fill("3001:7");
    await page
      .getByLabel("Known Device object", { exact: true })
      .fill("device,5136");
    await page.getByLabel("Known router", { exact: true }).fill(peer.router);
    await page.getByLabel("Known network", { exact: true }).fill("3001");
    await page
      .getByRole("region", { name: "Known controller connection", exact: true })
      .getByRole("button", { name: "Open controller", exact: true })
      .click();
    await expect(
      page.getByRole("region", { name: "Controller overview", exact: true }),
    ).toContainText("Authored controller");
    await chooseFile(page, ids.caf);
    const p = await compatibility(page);
    await fileMode(p, ids.b);
    await expect(
      p.getByLabel("Comparison workspace relation", { exact: true }),
    ).toContainText("matching recorded addresses");
    const before = await peer.command("stats");
    await compare(p);
    const after = await peer.command("stats");
    expect(after.request_types).toEqual(before.request_types);
    expect(after.events).toEqual(before.events);
    expect(
      after.events.filter(
        (row: any[]) =>
          row[0] === "write" ||
          (row[0] === "state" && row[1].includes("restore")),
      ),
    ).toEqual([]);
    await p
      .getByLabel("Captured File for CAF comparison", { exact: true })
      .selectOption(ids.serial);
    await expect(
      p.getByLabel("Comparison workspace relation", { exact: true }),
    ).toContainText("different station");
    await compare(p);
  } finally {
    peer.close();
  }
});
