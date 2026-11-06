import { test, expect } from "./nativeScheduleWriteFixture";
import type { Page, Response } from "@playwright/test";
import { readFileSync } from "node:fs";
import {
  enter,
  inspect,
  logic,
  prepare,
  python,
  source,
} from "./caf-constant-fixture";
import { enter as enterTimer } from "./caf-timer-fixture";
import { chooseWorkspaceSurface } from "./workspace-navigation";
import { nativeDefaultPeer } from "./native-default-peer";
import { freePort } from "./workflow-peer";

async function capture(page: Page) {
  const receipts = new WeakMap<object, Buffer>();
  await page.route("**/creation-draft**", async (route) => {
    const response = await route.fetch({ maxRedirects: 0, maxRetries: 0 }),
      bytes = await response.body();
    receipts.set(route.request(), Buffer.from(bytes));
    await route.fulfill({ response, body: bytes });
  });
  return (response: Response) => {
    const bytes = receipts.get(response.request());
    expect(bytes).toBeTruthy();
    return { bytes: bytes!, data: JSON.parse(bytes!.toString()) };
  };
}
const panel = (page: Page) =>
  page.getByRole("region", { name: "Saved CAF copy draft", exact: true });
async function openCheckpoint(page: Page) {
  const p = panel(page);
  if (!(await p.isVisible()))
    await page
      .getByText("Saved copy draft", { exact: true })
      .filter({ visible: true })
      .click();
  await expect(
    p.getByRole("button", { name: "Refresh saved copy draft", exact: true }),
  ).toBeEnabled();
  await expect(p).not.toContainText("Checking local copy checkpoint");
  return p;
}
async function save(page: Page, proof: Awaited<ReturnType<typeof capture>>) {
  const pending = page.waitForResponse(
    (r) =>
      r.url().endsWith("/creation-draft") && r.request().method() === "POST",
  );
  await panel(page)
    .getByRole("button", { name: "Save unfinished copy draft", exact: true })
    .click();
  const response = await pending;
  expect(response.status()).toBe(200);
  const receipt = proof(response);
  await expect(panel(page)).toContainText("Unfinished copy draft saved.");
  return receipt;
}

for (const width of [1440, 412]) {
  test(`unfinished recorded-copy coordinates survive real reload at ${width}px`, async ({
    page,
    request,
  }) => {
    await page.setViewportSize({ width, height: 1100 });
    page.on("dialog", (d) => d.accept());
    const proof = await capture(page),
      editor = await enter(page);
    const compileCalls: string[] = [];
    page.on("request", (r) => {
      if (/\/constant-copy\/(preview|export)$/.test(r.url()))
        compileCalls.push(r.url());
    });
    await editor.getByLabel("New constant X", { exact: true }).fill("1e-");
    await editor.getByLabel("New constant Y", { exact: true }).fill("  +42. ");
    await openCheckpoint(page);
    const saved = await save(page, proof);
    expect(saved.data.checkpoint.selection.x).toBe("1e-");
    expect(saved.data.checkpoint.selection.y).toBe("  +42. ");
    expect(saved.data.coordinates_validated).toBe(false);
    const downloading = page.waitForEvent("download"),
      receipt = page.waitForResponse((r) =>
        r.url().endsWith("/creation-draft/report"),
      );
    await panel(page)
      .getByRole("button", { name: "Download copy checkpoint", exact: true })
      .click();
    const actual = proof(await receipt).bytes,
      bytes = readFileSync((await (await downloading).path())!);
    expect(bytes).toEqual(actual);
    expect(JSON.parse(bytes.toString())).toEqual(saved.data.checkpoint);
    await page.reload();
    await enter(page);
    await openCheckpoint(page);
    await panel(page)
      .getByRole("button", { name: "Restore saved copy draft", exact: true })
      .click();
    await expect(
      page.getByLabel("New constant X", { exact: true }),
    ).toHaveValue("1e-");
    await expect(
      page.getByLabel("New constant Y", { exact: true }),
    ).toHaveValue("  +42. ");
    await expect(
      page.getByRole("button", {
        name: "Review constant CAF copy",
        exact: true,
      }),
    ).toBeDisabled();
    await expect(
      page.getByRole("region", {
        name: "Reviewed CAF constant copy",
        exact: true,
      }),
    ).toHaveCount(0);
    await panel(page).scrollIntoViewIfNeeded();
    await page.screenshot({
      path: test.info().outputPath(`copy-draft-${width}.png`),
      fullPage: true,
    });
    await panel(page)
      .getByRole("button", { name: "Remove saved copy draft", exact: true })
      .click();
    await expect(panel(page)).toContainText("No copy checkpoint is saved");
    await expect(
      page.getByLabel("New constant X", { exact: true }),
    ).toHaveValue("1e-");
    expect(compileCalls).toEqual([]);
    expect(
      (await (await request.get("/api/session")).json()).field_network_open,
    ).toBe(false);
  });

  test(`restoration needs explicit replacement and removes old copy approval at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1100 });
    const proof = await capture(page),
      editor = await enter(page);
    await editor.getByLabel("New constant X", { exact: true }).fill("81");
    await editor.getByLabel("New constant Y", { exact: true }).fill("42");
    await openCheckpoint(page);
    await save(page, proof);
    const reviewed = await prepare(page),
      download = page.waitForEvent("download");
    await reviewed
      .getByRole("button", { name: "Save constant CAF copy", exact: true })
      .click();
    await download;
    await expect(
      editor.getByRole("button", {
        name: "Open CAF copy",
        exact: true,
      }),
    ).toBeEnabled();
    await panel(page)
      .getByRole("button", { name: "Restore saved copy draft", exact: true })
      .click();
    await expect(
      page.getByRole("region", {
        name: "Reviewed CAF constant copy",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      editor.getByRole("button", {
        name: "Open CAF copy",
        exact: true,
      }),
    ).toHaveCount(0);
    await editor.getByLabel("New constant X", { exact: true }).fill("99");
    await panel(page)
      .getByRole("button", { name: "Restore saved copy draft", exact: true })
      .click();
    const replacement = page.getByRole("region", {
      name: "Replace current copy coordinates",
      exact: true,
    });
    await expect(replacement).toBeVisible();
    await expect(
      replacement.getByRole("row", { name: 'X "99" "81"', exact: true }),
    ).toBeVisible();
    await replacement
      .getByRole("button", { name: "Keep current copy draft", exact: true })
      .click();
    await expect(
      editor.getByLabel("New constant X", { exact: true }),
    ).toHaveValue("99");
    await panel(page)
      .getByRole("button", { name: "Restore saved copy draft", exact: true })
      .click();
    await replacement
      .getByRole("button", { name: "Replace current copy draft", exact: true })
      .click();
    await expect(
      editor.getByLabel("New constant X", { exact: true }),
    ).toHaveValue("81");
  });
}

test("recorded Timer draft restoration retains its actual source family and no runtime authority", async ({
  page,
}) => {
  const proof = await capture(page),
    editor = await enterTimer(page, "matching");
  await editor.getByLabel("New block X", { exact: true }).fill("-");
  await openCheckpoint(page);
  const saved = await save(page, proof);
  expect(saved.data.checkpoint.selection.kind).toBe("timer");
  expect(saved.data.checkpoint.source_evidence.source_profile).toBe(
    "caf-recorded-timer-copy/1",
  );
  await editor.getByLabel("New block X", { exact: true }).fill("99");
  await panel(page)
    .getByRole("button", { name: "Restore saved copy draft", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Replace current copy draft", exact: true })
    .click();
  await expect(editor.getByLabel("New block X", { exact: true })).toHaveValue(
    "-",
  );
  await expect(
    editor.getByRole("button", { name: "Review block CAF copy", exact: true }),
  ).toBeDisabled();
});

for (const action of ["text", "type", "prototype"]) {
  test(`held copy restore cannot revive through coalesced ${action} ABA`, async ({
    page,
  }) => {
    const proof = await capture(page);
    let editor;
    if (action === "text") editor = await enter(page);
    else {
      const buffer = python(
        action === "type"
          ? "from tests.test_caf_boolean_copy import mixed_example;import sys;sys.stdout.buffer.write(mixed_example())"
          : "from tests.test_caf_constant_copy import example,options;from bms_tool.caf_constant_copy import CafConstantCopies;import sys;c=CafConstantCopies(example(zero=True));sys.stdout.buffer.write(c.compile(**options(c))[0])",
      );
      await page.goto("/");
      await page
        .getByLabel("Open local CAF application", { exact: true })
        .setInputFiles({
          name: "multiple.caf",
          mimeType: "application/octet-stream",
          buffer,
        });
      await expect(
        page.getByLabel("Current CAF archive", { exact: true }),
      ).toHaveText("multiple.caf");
      await logic(page);
      editor = await inspect(page);
    }
    await editor.getByLabel("New constant X", { exact: true }).fill("81");
    await openCheckpoint(page);
    await save(page, proof);
    await editor.getByLabel("New constant X", { exact: true }).fill("99");
    let release!: () => void, entered!: () => void;
    const gate = new Promise<void>((r) => (release = r)),
      received = new Promise<void>((r) => (entered = r));
    await page.route("**/creation-draft/restore", async (route) => {
      const response = await route.fetch({ maxRedirects: 0, maxRetries: 0 });
      entered();
      await gate;
      await route.fulfill({ response, body: await response.body() });
    });
    try {
      await panel(page)
        .getByRole("button", { name: "Restore saved copy draft", exact: true })
        .click();
      await received;
      await page.evaluate((action) => {
        if (action === "text") {
          const input = document.querySelector<HTMLInputElement>(
            'input[aria-label="New constant X"]',
          )!;
          for (const value of ["100", "99"]) {
            Object.getOwnPropertyDescriptor(
              HTMLInputElement.prototype,
              "value",
            )!.set!.call(input, value);
            input.dispatchEvent(new Event("input", { bubbles: true }));
          }
        } else {
          const select = document.querySelector<HTMLSelectElement>(
            action === "type"
              ? 'select[aria-label="Constant type"]'
              : 'select[aria-label="Constant prototype"]',
          )!;
          const original = select.value,
            other = [...select.options].find(
              (o) => o.value !== original,
            )!.value;
          for (const value of [other, original]) {
            select.value = value;
            select.dispatchEvent(new Event("change", { bubbles: true }));
          }
        }
      }, action);
      const delivered = page.waitForResponse((r) =>
        r.url().endsWith("/creation-draft/restore"),
      );
      release();
      await (await delivered).finished();
      await expect(
        page.getByLabel("New constant X", { exact: true }),
      ).toHaveValue("99");
      await expect(
        page.getByRole("region", {
          name: "Replace current copy coordinates",
          exact: true,
        }),
      ).toHaveCount(0);
      await expect(panel(page)).not.toContainText("coordinates restored");
    } finally {
      release();
      await page.unroute("**/creation-draft/restore");
    }
  });
}

test("replacement rechecks a concurrent checkpoint revision and retains the current draft", async ({
  page,
  request,
}) => {
  const proof = await capture(page),
    editor = await enter(page);
  await editor.getByLabel("New constant X", { exact: true }).fill("81");
  await openCheckpoint(page);
  const record = (await save(page, proof)).data.checkpoint;
  await editor.getByLabel("New constant X", { exact: true }).fill("99");
  await panel(page)
    .getByRole("button", { name: "Restore saved copy draft", exact: true })
    .click();
  await expect(
    page.getByRole("region", {
      name: "Replace current copy coordinates",
      exact: true,
    }),
  ).toBeVisible();
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  const changed = await request.post(
    `/api/caf/${record.caf_sha256}/creation-draft`,
    {
      headers,
      data: {
        selection: { ...record.selection, x: "123" },
        expected: { id: record.id, revision: record.revision },
      },
    },
  );
  expect(changed.status()).toBe(200);
  await page
    .getByRole("button", { name: "Replace current copy draft", exact: true })
    .click();
  await expect(panel(page).getByRole("alert")).toContainText(
    "checkpoint changed",
  );
  await expect(
    editor.getByLabel("New constant X", { exact: true }),
  ).toHaveValue("99");
  await panel(page)
    .getByRole("button", { name: "Refresh saved copy draft", exact: true })
    .click();
  await expect(panel(page)).toContainText(
    `Saved checkpoint revision ${record.revision + 1}.`,
  );
});

test("an untrusted saved receipt cannot overwrite raw text or retry a committed checkpoint", async ({
  page,
}) => {
  await capture(page);
  const editor = await enter(page);
  await editor.getByLabel("New constant X", { exact: true }).fill("1e-");
  await openCheckpoint(page);
  let calls = 0;
  await page.route("**/creation-draft", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    calls++;
    const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 });
    const value = await response.json();
    value.controller_queries = true;
    await route.fulfill({ response, json: value });
  });
  await panel(page)
    .getByRole("button", { name: "Save unfinished copy draft", exact: true })
    .click();
  await expect(panel(page).getByRole("alert")).toContainText("proof differs");
  await expect(
    editor.getByLabel("New constant X", { exact: true }),
  ).toHaveValue("1e-");
  await page.waitForTimeout(100);
  expect(calls).toBe(1);
  await panel(page)
    .getByRole("button", { name: "Refresh saved copy draft", exact: true })
    .click();
  await expect(
    panel(page).getByRole("button", {
      name: "Restore saved copy draft",
      exact: true,
    }),
  ).toBeEnabled();
});

for (const action of ["source", "task", "pagehide"]) {
  test(`late copy restoration after ${action} retains current coordinates`, async ({
    page,
  }) => {
    page.on("dialog", (d) => d.accept());
    const proof = await capture(page),
      editor = await enter(page);
    await editor.getByLabel("New constant X", { exact: true }).fill("81");
    await openCheckpoint(page);
    await save(page, proof);
    await editor.getByLabel("New constant X", { exact: true }).fill("99");
    let release!: () => void, entered!: () => void;
    const gate = new Promise<void>((r) => (release = r)),
      received = new Promise<void>((r) => (entered = r));
    await page.route("**/creation-draft/restore", async (route) => {
      const response = await route.fetch({ maxRedirects: 0, maxRetries: 0 });
      entered();
      await gate;
      await route.fulfill({ response, body: await response.body() });
    });
    try {
      await panel(page)
        .getByRole("button", { name: "Restore saved copy draft", exact: true })
        .click();
      await received;
      if (action === "source") {
        await page
          .getByLabel("Open local CAF application", { exact: true })
          .setInputFiles({
            name: "replacement.caf",
            mimeType: "application/octet-stream",
            buffer: source(796),
          });
        await expect(
          page.getByLabel("Current CAF archive", { exact: true }),
        ).toHaveText("replacement.caf");
        await logic(page);
      } else if (action === "task") {
        await chooseWorkspaceSurface(page, "Library");
        await chooseWorkspaceSurface(page, "Workspace");
        await logic(page);
      } else
        await page.evaluate(() => window.dispatchEvent(new Event("pagehide")));
      const delivered = page.waitForResponse((r) =>
        r.url().endsWith("/creation-draft/restore"),
      );
      release();
      await (await delivered).finished();
      const current = await inspect(page);
      await expect(
        current.getByLabel("New constant X", { exact: true }),
      ).toHaveValue(action === "source" ? "81.000" : "99");
      await expect(
        page.getByRole("region", {
          name: "Replace current copy coordinates",
          exact: true,
        }),
      ).toHaveCount(0);
      await expect(
        page.getByRole("region", {
          name: "Reviewed CAF constant copy",
          exact: true,
        }),
      ).toHaveCount(0);
    } finally {
      release();
      await page.unroute("**/creation-draft/restore");
    }
  });
}

test("routed controller selection is retained and copy checkpoint operations add no field traffic", async ({
  page,
}) => {
  const peer = await nativeDefaultPeer(),
    active = new Set<object>();
  page.on("request", (r) => {
    if (r.url().includes("/api/bacnet/")) active.add(r);
  });
  page.on("requestfinished", (r) => active.delete(r));
  page.on("requestfailed", (r) => active.delete(r));
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
    const choosing = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: "Open CAF", exact: true }).click();
    await (
      await choosing
    ).setFiles({
      name: "local.caf",
      mimeType: "application/octet-stream",
      buffer: source(),
    });
    await expect(
      page.getByLabel("Current CAF archive", { exact: true }),
    ).toHaveText("local.caf");
    await page.getByRole("button", { name: "Edit", exact: true }).click();
    await logic(page);
    const proof = await capture(page),
      editor = await inspect(page);
    await expect.poll(() => active.size).toBe(0);
    const before = await peer.command("stats");
    await editor.getByLabel("New constant X", { exact: true }).fill("1e-");
    await openCheckpoint(page);
    await save(page, proof);
    await editor.getByLabel("New constant X", { exact: true }).fill("99");
    await panel(page)
      .getByRole("button", { name: "Restore saved copy draft", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Replace current copy draft", exact: true })
      .click();
    await expect(
      editor.getByLabel("New constant X", { exact: true }),
    ).toHaveValue("1e-");
    const after = await peer.command("stats");
    expect(after.request_types).toEqual(before.request_types);
    expect(after.events).toEqual(before.events);
    await expect(
      page.getByLabel("Selected controller path", { exact: true }),
    ).toContainText("3001:7");
  } finally {
    peer.close();
  }
});
