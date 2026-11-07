import { test, expect } from "./nativeScheduleWriteFixture";
import type { Page } from "@playwright/test";
import {
  existsSync,
  mkdtempSync,
  readFileSync,
  writeFileSync,
  unlinkSync,
} from "node:fs";
import { readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { seedBundleInspection } from "./native-batch-bundle-inspection-fixture";
import {
  chooseWorkspaceTask,
  chooseWorkspaceTool,
} from "./workspace-navigation";
import { connectionSeal } from "../src/nativeConnectionContract";
import { nativeDefaultPeer } from "./native-default-peer";
import { freePort } from "./workflow-peer";

test.use({ observeBundleInspection: true });
const panel = (page: Page) =>
  page.getByLabel("Portable comparison evidence inspection", { exact: true });
const result = (page: Page) =>
  page.getByRole("region", {
    name: "Inspected comparison evidence",
    exact: true,
  });
const sample = (kind = "valid") =>
  seedBundleInspection(
    mkdtempSync(join(tmpdir(), "bms-external-bundle-")),
    kind,
  );
async function enter(page: Page, f: any, caf = false, openDisclosure = true) {
  await page.goto("/");
  if (caf) {
    const chooser = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: /^Open a CAF file/ }).click();
    await (
      await chooser
    ).setFiles({
      name: "preserved-source.caf",
      mimeType: "application/octet-stream",
      buffer: Buffer.from(f.caf, "base64"),
    });
    await expect(
      page.getByLabel("Working context", { exact: true }),
    ).toContainText("preserved-source.caf");
  } else {
    await page
      .getByRole("button", { name: "New application", exact: true })
      .click();
    await page
      .getByLabel("Program name", { exact: true })
      .fill("Preserved unfinished graph");
  }
  await chooseWorkspaceTask(page, "Changes");
  if (!openDisclosure) return;
  await panel(page).locator(":scope > summary").click();
  await expect(
    panel(page).getByRole("button", {
      name: "Open comparison evidence bundle",
      exact: true,
    }),
  ).toBeVisible();
}
async function choose(page: Page, f: any, name = "comparison-evidence.zip") {
  const chooser = page.waitForEvent("filechooser");
  await panel(page)
    .getByRole("button", {
      name: "Open comparison evidence bundle",
      exact: true,
    })
    .click();
  await (
    await chooser
  ).setFiles({
    name,
    mimeType: "application/zip",
    buffer: Buffer.from(f.bundle, "base64"),
  });
}
async function saved(page: Page, name: string) {
  const download = page.waitForEvent("download");
  await panel(page).getByRole("button", { name, exact: true }).click();
  return readFile((await (await download).path())!);
}

for (const caf of [false, true])
  for (const phone of [false, true])
    test(`${caf ? "CAF" : "graph"} ${phone ? "compact" : "desktop"} opens external evidence offline and exports exact original bytes`, async ({
      page,
      nativeScheduleWriteServer,
    }, testInfo) => {
      if (phone) await page.setViewportSize({ width: 390, height: 844 });
      const f = sample(),
        calls: string[] = [];
      page.on("request", (request) => {
        if (
          request.method() === "POST" &&
          new URL(request.url()).pathname.startsWith("/api/bacnet/")
        )
          calls.push(new URL(request.url()).pathname);
      });
      await enter(page, f, caf);
      const before = await page
        .getByLabel("Working context", { exact: true })
        .textContent();
      await choose(page, f);
      await expect(result(page)).toContainText("Bundle internally consistent");
      await expect(result(page)).toContainText("match the recorded result");
      await expect(
        result(page).getByRole("table", {
          name: "Bundled typed value comparison",
          exact: true,
        }),
      ).toContainText("-0");
      await expect(
        page.getByLabel("Working context", { exact: true }),
      ).toHaveText(before!);
      const bytes = readFileSync(
        join(
          nativeScheduleWriteServer.directory,
          "bundle-inspection-response.json",
        ),
      );
      expect(await saved(page, "Save inspection report")).toEqual(bytes);
      expect(await saved(page, "Save original evidence bundle")).toEqual(
        Buffer.from(f.bundle, "base64"),
      );
      await result(page)
        .getByText("Comparison details and original evidence", { exact: true })
        .click();
      const originalManifest = await saved(page, "Save original manifest.json");
      expect(JSON.parse(originalManifest.toString())).toEqual(
        f.inspection.manifest,
      );
      expect(calls).toEqual([
        "/api/bacnet/controller/native-application/default-batch/result/inspect-evidence",
      ]);
      await testInfo.attach("bundle-inspection-layout", {
        body: await result(page).screenshot(),
        contentType: "image/png",
      });
      await chooseWorkspaceTask(page, "Program");
      if (caf)
        await expect(
          page.getByLabel("Working context", { exact: true }),
        ).toContainText("preserved-source.caf");
      else {
        await chooseWorkspaceTool(page, "Graph editor");
        await expect(
          page.getByLabel("Program name", { exact: true }),
        ).toHaveValue("Preserved unfinished graph");
      }
    });

test("cancellation retires a held upload and a fresh inspection remains usable", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = sample(),
    directory = nativeScheduleWriteServer.directory,
    gate = join(directory, "hold-bundle-inspection");
  writeFileSync(gate, "hold");
  try {
    await enter(page, f);
    await choose(page, f);
    await expect
      .poll(() =>
        existsSync(join(directory, "bundle-inspection-original-response.json")),
      )
      .toBe(true);
    await panel(page)
      .getByRole("button", { name: "Cancel evidence inspection", exact: true })
      .click();
    unlinkSync(gate);
    await expect
      .poll(() =>
        existsSync(join(directory, "bundle-inspection-response.json")),
      )
      .toBe(true);
    await expect(result(page)).toHaveCount(0);
    await panel(page)
      .getByRole("button", {
        name: "Inspect selected bundle again",
        exact: true,
      })
      .click();
    await expect(result(page)).toContainText("Bundle internally consistent");
  } finally {
    if (existsSync(gate)) unlinkSync(gate);
  }
});

test("a newer file retires a held older response without losing its differences", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const first = sample(),
    second = sample("different"),
    directory = nativeScheduleWriteServer.directory,
    gate = join(directory, "hold-bundle-inspection");
  writeFileSync(gate, "hold");
  try {
    await enter(page, first);
    await choose(page, first, "older.zip");
    await expect
      .poll(() =>
        existsSync(join(directory, "bundle-inspection-original-response.json")),
      )
      .toBe(true);
    await choose(page, second, "newer.zip");
    unlinkSync(gate);
    await expect(result(page)).toContainText("have recorded differences");
    await expect(panel(page)).toContainText("newer.zip");
    expect(await saved(page, "Save original evidence bundle")).toEqual(
      Buffer.from(second.bundle, "base64"),
    );
  } finally {
    if (existsSync(gate)) unlinkSync(gate);
  }
});

test("task navigation retires a held response and preserves the unfinished graph", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = sample(),
    directory = nativeScheduleWriteServer.directory,
    gate = join(directory, "hold-bundle-inspection");
  writeFileSync(gate, "hold");
  try {
    await enter(page, f);
    await choose(page, f);
    await expect
      .poll(() =>
        existsSync(join(directory, "bundle-inspection-original-response.json")),
      )
      .toBe(true);
    await chooseWorkspaceTask(page, "Program");
    await chooseWorkspaceTool(page, "Graph editor");
    await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
      "Preserved unfinished graph",
    );
    unlinkSync(gate);
    await expect
      .poll(() =>
        existsSync(join(directory, "bundle-inspection-response.json")),
      )
      .toBe(true);
    await chooseWorkspaceTask(page, "Changes");
    await panel(page).locator(":scope > summary").click();
    await expect(result(page)).toHaveCount(0);
  } finally {
    if (existsSync(gate)) unlinkSync(gate);
  }
});

for (const lifetime of ["disclosure", "pagehide"])
  test(`${lifetime} retirement rejects the original cached export callback`, async ({
    page,
  }) => {
    const f = sample();
    await enter(page, f);
    await choose(page, f);
    await expect(result(page)).toContainText("Bundle internally consistent");
    const cached = await panel(page)
      .getByRole("button", { name: "Save inspection report", exact: true })
      .evaluateHandle(
        (element: any) =>
          element[
            Object.keys(element).find((k) => k.startsWith("__reactProps"))!
          ].onClick,
      );
    let downloads = 0;
    page.on("download", () => downloads++);
    if (lifetime === "pagehide")
      await page.evaluate(() => {
        window.dispatchEvent(new Event("pagehide"));
        window.dispatchEvent(new Event("pageshow"));
      });
    else
      await panel(page)
        .locator(":scope > summary")
        .evaluate((element: HTMLElement) => {
          element.click();
          element.click();
        });
    await cached.evaluate((callback: any) => callback());
    await expect(result(page)).toHaveCount(0);
    expect(downloads).toBe(0);
    await expect(
      panel(page).getByRole("button", {
        name: "Inspect selected bundle again",
        exact: true,
      }),
    ).toBeEnabled();
  });

test("invalid ZIP refuses locally and another file remains usable", async ({
  page,
}) => {
  const f = sample();
  await enter(page, f);
  await choose(
    page,
    { bundle: Buffer.from("bad archive").toString("base64") },
    "invalid.zip",
  );
  await expect(panel(page).getByRole("alert")).toContainText("ZIP");
  await expect(result(page)).toHaveCount(0);
  await choose(page, f);
  await expect(result(page)).toContainText("Bundle internally consistent");
});

for (const kind of ["historical", "recovery", "different", "routed"])
  test(`external ${kind} bundle preserves its historical proof and comparison meaning`, async ({
    page,
  }) => {
    const f = sample(kind);
    await enter(page, f);
    await choose(page, f);
    await expect(result(page)).toContainText("Bundle internally consistent");
    await expect(result(page)).toContainText(f.report.verified_proof.kind);
    await expect(result(page)).toContainText(
      kind === "different" || kind === "routed"
        ? "have recorded differences"
        : "match the recorded result",
    );
    if (kind === "routed") await expect(result(page)).toContainText("3001:7");
  });

for (const fault of ["authority", "source", "member"])
  test(`altered ${fault} response cannot display or export inspection evidence`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const f = sample(),
      value = structuredClone(f.inspection);
    if (fault === "authority") value.receipt_restored = true;
    else if (fault === "source")
      value.comparison.source.capture_id = "f".repeat(32);
    else value.members[0].sha256 = "f".repeat(64);
    const { inspection_sha256: _, ...body } = value;
    value.inspection_sha256 = await connectionSeal(body);
    writeFileSync(
      join(
        nativeScheduleWriteServer.directory,
        "bundle-inspection-response-override.json",
      ),
      JSON.stringify(value),
    );
    await enter(page, f);
    await choose(page, f);
    await expect(panel(page).getByRole("alert")).toContainText(
      "does not match this exact bundle",
    );
    await expect(result(page)).toHaveCount(0);
    await expect(
      panel(page).getByRole("button", {
        name: "Save inspection report",
        exact: true,
      }),
    ).toHaveCount(0);
  });

for (const routed of [false, true])
  test(`${routed ? "routed" : "direct"} selected controller stays independent of external evidence`, async ({
    page,
  }) => {
    const peer = await nativeDefaultPeer("consume", "execution-order"),
      f = sample();
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
      ).toContainText("Authored native wire controller");
      const before = await peer.command("stats");
      await chooseWorkspaceTask(page, "Changes");
      await panel(page).locator(":scope > summary").click();
      await choose(page, f);
      await expect(result(page)).toContainText("Bundle internally consistent");
      await expect(
        page.getByLabel("Selected controller path", { exact: true }),
      ).toContainText(routed ? "3001:7" : peer.direct);
      const after = await peer.command("stats");
      expect(after.events).toEqual(before.events);
      expect(after.request_types).toEqual(before.request_types);
      expect(after.router_errors).toEqual([]);
      const cached = await panel(page)
        .getByRole("button", { name: "Save inspection report", exact: true })
        .evaluateHandle(
          (element: any) =>
            element[
              Object.keys(element).find((k) => k.startsWith("__reactProps"))!
            ].onClick,
        );
      let downloads = 0;
      page.on("download", () => downloads++);
      await page
        .getByRole("button", { name: "Change controller", exact: true })
        .click();
      await cached.evaluate((callback: any) => callback());
      expect(downloads).toBe(0);
    } finally {
      peer.close();
    }
  });

test("keyboard file choice and report save remain accessible", async ({
  page,
}) => {
  await page.addInitScript(() => {
    const events: unknown[] = [];
    (window as any).__bundleKeyboardEvents = events;
    for (const type of [
      "pagehide",
      "pageshow",
      "visibilitychange",
      "click",
      "toggle",
      "keydown",
      "keyup",
    ])
      window.addEventListener(
        type,
        (event) => {
          const target = event.target as HTMLElement;
          events.push({
            type,
            visibility: document.visibilityState,
            tag: target?.tagName,
            text:
              target?.tagName === "BUTTON" || target?.tagName === "SUMMARY"
                ? target.textContent
                : "",
            open: document
              .querySelector(
                'details[aria-label="Portable comparison evidence inspection"]',
              )
              ?.hasAttribute("open"),
          });
        },
        true,
      );
  });
  const f = sample();
  await enter(page, f);
  const open = panel(page).getByRole("button", {
    name: "Open comparison evidence bundle",
    exact: true,
  });
  await open.focus();
  await expect(open).toBeFocused();
  const picker = page.waitForEvent("filechooser");
  await page.keyboard.press("Enter");
  await (
    await picker
  ).setFiles({
    name: "keyboard.zip",
    mimeType: "application/zip",
    buffer: Buffer.from(f.bundle, "base64"),
  });
  try {
    await expect(result(page)).toContainText("Bundle internally consistent");
  } catch (error) {
    console.log(
      JSON.stringify(
        await page.evaluate(() => (window as any).__bundleKeyboardEvents),
      ),
    );
    throw error;
  }
  const save = panel(page).getByRole("button", {
    name: "Save inspection report",
    exact: true,
  });
  await save.focus();
  await expect(save).toBeFocused();
  const download = page.waitForEvent("download");
  await page.keyboard.press("Enter");
  expect(
    JSON.parse((await readFile((await (await download).path())!)).toString())
      .bundle_sha256,
  ).toBe(f.inspection.bundle_sha256);
});

test("opening the disclosure and selecting a file in one turn keeps the new inspection", async ({
  page,
}) => {
  const f = sample();
  await enter(page, f, false, false);
  await panel(page).evaluate((element, encoded) => {
    (element.querySelector(":scope > summary") as HTMLElement).click();
    const bytes = Uint8Array.from(atob(encoded), (char) => char.charCodeAt(0));
    const transfer = new DataTransfer();
    transfer.items.add(
      new File([bytes], "same-turn.zip", { type: "application/zip" }),
    );
    const input = element.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    input.files = transfer.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }, f.bundle);
  await expect(result(page)).toContainText("Bundle internally consistent");
});
