import { test, expect, type Page } from "./nativeScheduleWriteFixture";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import {
  openSimulation,
  simulation,
  python,
  synthetic,
  value,
} from "./caf-simulation-fixture";
import { chooseWorkspaceSurface } from "./workspace-navigation";
const sha = (body: Buffer) => createHash("sha256").update(body).digest("hex");
const panel = (page: Page) => page.locator(".caf-simulation");
async function profile(page: Page) {
  const wait = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Export profile JSON", exact: true })
    .click();
  return JSON.parse(readFileSync((await (await wait).path())!, "utf8"));
}
async function importDraft(page: Page, document: unknown) {
  await page
    .getByLabel("Simulation profile JSON", { exact: true })
    .setInputFiles({
      name: "draft.json",
      mimeType: "application/json",
      buffer: Buffer.from(JSON.stringify(document)),
    });
}
async function copy(page: Page) {
  const wait = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Export simulation CAF", exact: true })
    .click();
  return await wait;
}

test("CAF entry exports mixed Enum Float Boolean changes and exact digest-qualified source copy", async ({
  page,
  request,
}) => {
  await openSimulation(page, { cafEntry: true, cdata: true });
  let fields = 0;
  await page.route("**/api/bacnet/**", (r) => {
    fields++;
    return r.abort();
  });
  await value(page).fill("4294967295");
  await page
    .getByLabel("Simulation value 8-1/526_1", { exact: true })
    .fill("73.25");
  await page
    .getByLabel("Simulation value 8-1/530_3", { exact: true })
    .fill("true");
  const p = await profile(page);
  expect(p.version).toBe(2);
  expect(p.entries[3]).toMatchObject({
    value: "4294967295",
    enum_semantics_verified: false,
    maximum_code: 4294967295,
    attributes: { set: "113" },
  });
  const response = page.waitForResponse(
    (r) => r.request().method() === "POST" && /\/simulation$/.test(r.url()),
  );
  const download = await copy(page),
    file = (await download.path())!,
    r = await response;
  expect(download.suggestedFilename()).toBe("authored-simulation.caf");
  expect(r.headers()["x-studio-source-sha256"]).toBe(
    sha(synthetic("528", true)),
  );
  expect(r.headers()["x-studio-artifact-sha256"]).toBe(sha(readFileSync(file)));
  expect(r.headers()["x-studio-simulation-version"]).toBe("2");
  expect(
    JSON.parse(
      python(
        `from pathlib import Path
import sys,json
from tests.test_caf_enum_simulation import source
from bms_tool.caf import CafArchive
from bms_tool.caf_simulation import CafSimulationProfile
before=CafArchive(source(cdata=True));after=CafArchive(Path(sys.argv[1]).read_bytes())
expected=before.xml.replace(b'<![CDATA[1]]>',b'<![CDATA[4294967295]]>').replace(b'<float>70.000</float>',b'<float>73.25</float>').replace(b'<boolean>0</boolean>',b'<boolean>true</boolean>')
assert after.xml==expected
print(json.dumps({'exact_xml':True,'ordinary_count':after.xml.count(b'<float>111.000</float>'),'value':CafSimulationProfile(after,profile_version=2).summary()['records'][3]['old']}))`,
        file,
      ).toString(),
    ),
  ).toEqual({ exact_xml: true, ordinary_count: 5, value: "4294967295" });
  expect(
    (await (await request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
  expect(fields).toBe(0);
  await expect(panel(page).getByRole("status")).toContainText(
    "JCI execution remains unverified",
  );
});
test("phone Output Enum preserves focus, readable text, raw drafts and navigation without granting scenario support", async ({
  page,
}, info) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openSimulation(page, { cid: "529" });
  await value(page, "529").fill("1e-");
  await value(page, "529").focus();
  await expect(value(page, "529")).toBeFocused();
  expect(
    await value(page, "529").evaluate((e) =>
      parseFloat(getComputedStyle(e).fontSize),
    ),
  ).toBeGreaterThanOrEqual(14);
  await page
    .getByRole("button", { name: "Export simulation CAF", exact: true })
    .click();
  await expect(panel(page).getByRole("alert")).toContainText("Simulation Enum");
  await chooseWorkspaceSurface(page, "Library");
  await chooseWorkspaceSurface(page, "Workspace");
  await simulation(page);
  await expect(value(page, "529")).toHaveValue("1e-");
  await expect(
    page.getByRole("region", { name: "Local CAF input scenarios" }),
  ).toContainText("2 supported inputs");
  const p = await profile(page);
  expect(p.entries[3].value).toBe("1e-");
  await page.screenshot({
    path: info.outputPath("caf-enum-simulation-phone.png"),
    fullPage: true,
  });
});
test("legacy v1 imports carry Float Boolean drafts, protect readonly Enum and adapt to v2 explicitly", async ({
  page,
  request,
}) => {
  await openSimulation(page);
  const p = await profile(page),
    base = `/api/caf/${p.source_sha256}/simulation`;
  const legacy = await (await request.get(base + "/profile")).json();
  expect(legacy.version).toBe(1);
  legacy.entries[0].value = "NaN";
  legacy.entries[2].value = "true";
  await importDraft(page, legacy);
  await expect(panel(page).getByRole("status")).toContainText(
    "Legacy profile values adapted",
  );
  await expect(value(page)).toHaveValue("1");
  await expect(
    page.getByLabel("Simulation value 8-1/526_1", { exact: true }),
  ).toHaveValue("NaN");
  const adapted = await profile(page);
  expect(adapted.version).toBe(2);
  expect(adapted.entries[3].editable).toBe(true);
  legacy.entries[3].value = "2";
  await importDraft(page, legacy);
  await expect(panel(page).getByRole("alert")).toContainText(
    "read-only native record",
  );
  await expect(value(page)).toHaveValue("1");
});
test("v2 imports preserve invalid Enum raw text, reject changed guard metadata and explicit replacement refusal", async ({
  page,
}) => {
  await openSimulation(page);
  const p = await profile(page);
  p.entries[3].value = "01";
  await importDraft(page, p);
  await expect(value(page)).toHaveValue("01");
  await page
    .getByRole("button", { name: "Export simulation CAF", exact: true })
    .click();
  await expect(panel(page).getByRole("alert")).toContainText("Simulation Enum");
  const bad = structuredClone(p);
  bad.entries[3].enum_semantics_verified = true;
  page.once("dialog", (d) => d.accept());
  await importDraft(page, bad);
  await expect(panel(page).getByRole("alert")).toContainText("old-value guard");
  await expect(value(page)).toHaveValue("01");
  page.once("dialog", (d) => d.dismiss());
  await page.getByLabel("Simulation CAF file", { exact: true }).setInputFiles({
    name: "other.caf",
    mimeType: "application/octet-stream",
    buffer: synthetic("529"),
  });
  await expect(value(page)).toHaveValue("01");
});
for (const fault of ["source", "version", "digest", "body"])
  test(`altered exported ${fault} proof suppresses download and preserves the draft`, async ({
    page,
  }) => {
    await openSimulation(page);
    await value(page).fill("2");
    let downloads = 0;
    page.on("download", () => downloads++);
    await page.route("**/api/caf/*/simulation", async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      const r = await route.fetch({ maxRetries: 0 }),
        headers = { ...r.headers() };
      let body = await r.body();
      if (fault === "source")
        headers["x-studio-source-sha256"] = "0".repeat(64);
      if (fault === "version") headers["x-studio-simulation-version"] = "1";
      if (fault === "digest")
        headers["x-studio-artifact-sha256"] = "0".repeat(64);
      if (fault === "body") body = Buffer.from("altered");
      await route.fulfill({ response: r, headers, body });
    });
    await page
      .getByRole("button", { name: "Export simulation CAF", exact: true })
      .click();
    await expect(panel(page).getByRole("alert")).toContainText(
      "artifact digest",
    );
    await expect(value(page)).toHaveValue("2");
    expect(downloads).toBe(0);
  });
for (const lifecycle of ["navigation", "pagehide", "visibility"])
  test(`${lifecycle} retires a late CAF copy even after returning`, async ({
    page,
  }) => {
    await openSimulation(page);
    await value(page).fill("2");
    let release!: () => void, seen!: () => void;
    const hold = new Promise<void>((r) => (release = r)),
      started = new Promise<void>((r) => (seen = r));
    let downloads = 0;
    page.on("download", () => downloads++);
    await page.route("**/api/caf/*/simulation", async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      const r = await route.fetch({ maxRetries: 0 }),
        body = await r.body();
      seen();
      await hold;
      await route.fulfill({ response: r, body });
    });
    await page
      .getByRole("button", { name: "Export simulation CAF", exact: true })
      .click();
    await started;
    if (lifecycle === "navigation") {
      await chooseWorkspaceSurface(page, "Library");
      await chooseWorkspaceSurface(page, "Workspace");
      await simulation(page);
    } else
      await page.evaluate((kind) => {
        if (kind === "pagehide") window.dispatchEvent(new Event("pagehide"));
        else {
          Object.defineProperty(document, "hidden", {
            configurable: true,
            value: true,
          });
          document.dispatchEvent(new Event("visibilitychange"));
          Object.defineProperty(document, "hidden", {
            configurable: true,
            value: false,
          });
          document.dispatchEvent(new Event("visibilitychange"));
        }
      }, lifecycle);
    release();
    await expect(
      page.getByRole("button", { name: "Export simulation CAF", exact: true }),
    ).toBeEnabled();
    await expect(value(page)).toHaveValue("2");
    await expect(
      page.getByRole("region", { name: "Simulation file summary" }),
    ).toContainText("unexported");
    await page.unrouteAll({ behavior: "wait" });
    expect(downloads).toBe(0);
  });
test("late legacy import cannot replace a newer visible draft after workspace retirement", async ({
  page,
  request,
}) => {
  await openSimulation(page);
  const p = await profile(page),
    legacy = await (
      await request.get(`/api/caf/${p.source_sha256}/simulation/profile`)
    ).json();
  legacy.entries[0].value = "88";
  let release!: () => void, seen!: () => void;
  const hold = new Promise<void>((r) => (release = r)),
    started = new Promise<void>((r) => (seen = r));
  await page.route("**/api/caf/*/simulation/profile", async (route) => {
    const r = await route.fetch({ maxRetries: 0 }),
      body = await r.body();
    seen();
    await hold;
    await route.fulfill({ response: r, body });
  });
  await importDraft(page, legacy);
  await started;
  await chooseWorkspaceSurface(page, "Library");
  await chooseWorkspaceSurface(page, "Workspace");
  await simulation(page);
  await value(page).fill("3");
  release();
  await page.unrouteAll({ behavior: "wait" });
  await expect(value(page)).toHaveValue("3");
  await expect(
    page.getByLabel("Simulation value 8-1/526_1", { exact: true }),
  ).toHaveValue("70.000");
});
for (const fault of ["source", "semantics"])
  test(`altered ${fault} inventory cannot enable a simulation draft`, async ({
    page,
  }) => {
    await page.route(
      "**/api/caf/*/simulation/profile?profile_version=2",
      async (route) => {
        const r = await route.fetch({ maxRetries: 0 }),
          p = await r.json();
        if (fault === "source") p.source_sha256 = "0".repeat(64);
        else p.entries[3].enum_semantics_verified = true;
        await route.fulfill({ response: r, json: p });
      },
    );
    await page.goto("/");
    await page
      .getByRole("button", { name: "New application", exact: true })
      .click();
    await simulation(page);
    await page
      .getByLabel("Simulation CAF file", { exact: true })
      .setInputFiles({
        name: "authored.caf",
        mimeType: "application/octet-stream",
        buffer: synthetic(),
      });
    await expect(panel(page).getByRole("alert")).toContainText(
      "does not match",
    );
    await expect(value(page)).toHaveCount(0);
  });

test("an internally consistent response for another cached CAF cannot replace selected file bytes", async ({
  page,
  request,
}) => {
  const other = await (
    await request.post("/api/caf", {
      headers: {
        "X-Studio-Token": (await (await request.get("/api/session")).json())
          .token,
      },
      multipart: {
        file: {
          name: "other.caf",
          mimeType: "application/octet-stream",
          buffer: synthetic("529"),
        },
      },
    })
  ).json();
  await page.route("**/api/caf", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      json: other,
    });
  });
  await page.goto("/");
  await page
    .getByRole("button", { name: "New application", exact: true })
    .click();
  await simulation(page);
  await page.getByLabel("Simulation CAF file", { exact: true }).setInputFiles({
    name: "selected.caf",
    mimeType: "application/octet-stream",
    buffer: synthetic(),
  });
  await expect(panel(page).getByRole("alert")).toContainText(
    "selected file bytes",
  );
  await expect(value(page)).toHaveCount(0);
});
for (const replacement of ["new-source", "hidden"])
  test(`late source open retires after ${replacement}`, async ({ page }) => {
    await openSimulation(page);
    let release!: () => void, seen!: () => void;
    const held = new Promise<void>((r) => (release = r)),
      started = new Promise<void>((r) => (seen = r));
    let intercept = true;
    await page.route(
      "**/api/caf/*/simulation/profile?profile_version=2",
      async (route) => {
        const response = await route.fetch({ maxRetries: 0 }),
          body = await response.body();
        if (intercept) {
          intercept = false;
          seen();
          await held;
        }
        await route.fulfill({ response, body });
      },
    );
    await page
      .getByLabel("Simulation CAF file", { exact: true })
      .setInputFiles({
        name: "late.caf",
        mimeType: "application/octet-stream",
        buffer: synthetic("529"),
      });
    await started;
    if (replacement === "new-source")
      await page
        .getByLabel("Simulation CAF file", { exact: true })
        .setInputFiles({
          name: "current.caf",
          mimeType: "application/octet-stream",
          buffer: synthetic(),
        });
    else {
      await chooseWorkspaceSurface(page, "Library");
      await chooseWorkspaceSurface(page, "Workspace");
      await simulation(page);
    }
    release();
    await page.unrouteAll({ behavior: "wait" });
    await expect(
      page.getByRole("region", { name: "Simulation file summary" }),
    ).toContainText(
      replacement === "new-source" ? "current.caf" : "authored.caf",
    );
    await expect(
      page.getByRole("button", { name: "Export profile JSON", exact: true }),
    ).toBeEnabled();
    const p = await profile(page);
    expect(p.source_sha256).toBe(sha(synthetic()));
    expect(p.entries[3].class_id).toBe("528");
  });
