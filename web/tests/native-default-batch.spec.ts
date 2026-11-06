import { test, expect } from "./nativeScheduleWriteFixture";
import type { Page, Locator } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { seedDefaultBatch } from "./native-default-batch-fixture";
import { openNativeCompiler } from "./workspace-navigation";

async function enter(page: Page, data: any, caf = false) {
  await page.goto("/");
  if (caf) {
    const chooser = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: /^Open a CAF file/ }).click();
    await (
      await chooser
    ).setFiles({
      name: "typed-default-batch.caf",
      mimeType: "application/octet-stream",
      buffer: Buffer.from(data.caf, "base64"),
    });
  } else
    await page
      .getByRole("button", { name: "New application", exact: true })
      .click();
  await openNativeCompiler(page);
  const compiler = page.getByRole("region", {
    name: "Native backup default compiler",
    exact: true,
  });
  await compiler
    .getByLabel("Retained native backup", { exact: true })
    .selectOption(data.id);
  await compiler
    .getByRole("button", { name: "Open retained backup", exact: true })
    .click();
  await compiler
    .getByLabel("Native Real default", { exact: true })
    .selectOption("controller/575_1.2_12");
  return compiler;
}
async function expand(compiler: Locator) {
  const batch = compiler.getByLabel("Native typed default batch", {
    exact: true,
  });
  await batch.locator(":scope > summary").click();
  await expect(
    batch
      .getByRole("table", { name: "Native batch default fields", exact: true })
      .getByRole("row"),
  ).toHaveCount(6);
  return batch;
}
async function propose(batch: Locator, data: any) {
  for (const change of data.body.changes) {
    await batch
      .getByLabel(`Include ${change.record_ref} in batch`, { exact: true })
      .check();
    if (change.kind === "boolean")
      await batch
        .getByLabel(`Proposed Boolean for ${change.record_ref}`, {
          exact: true,
        })
        .setChecked(change.value);
    else
      await batch
        .getByLabel(`Proposed ${change.kind} value for ${change.record_ref}`, {
          exact: true,
        })
        .fill(
          change.kind === "real" ? change.value_text : String(change.value),
        );
  }
}
const reviewed = (batch: Locator) =>
  batch.getByRole("region", {
    name: "Reviewed native default batch",
    exact: true,
  });
async function review(batch: Locator) {
  await batch
    .getByRole("button", { name: "Review local default batch", exact: true })
    .click();
  await expect(reviewed(batch)).toBeVisible();
}
for (const caf of [false, true])
  test(`${caf ? "CAF phone" : "desktop"} compiles all three types and exports exact local bytes while retaining the ordinary draft`, async ({
    page,
    request,
    nativeScheduleWriteServer,
  }, info) => {
    if (caf) await page.setViewportSize({ width: 390, height: 844 });
    const data = seedDefaultBatch(nativeScheduleWriteServer.directory),
      compiler = await enter(page, data, caf);
    await compiler
      .getByLabel("Proposed native Real default", { exact: true })
      .fill("12.");
    const batch = await expand(compiler);
    await propose(batch, data);
    await batch
      .getByLabel("Find a batch default", { exact: true })
      .fill("enum");
    await expect(
      batch
        .getByRole("table", {
          name: "Native batch default fields",
          exact: true,
        })
        .getByRole("row"),
    ).toHaveCount(3);
    await expect(
      compiler.getByLabel("Proposed native Real default", { exact: true }),
    ).toBeHidden();
    let exact: Buffer = Buffer.alloc(0);
    await page.route("**/default-batch/preview", async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      exact = await response.body();
      await route.fulfill({ response, body: exact });
    });
    await review(batch);
    expect(exact.byteLength).toBeGreaterThan(0);
    expect(JSON.parse(exact.toString()).request).toEqual(data.body);
    await expect(reviewed(batch)).toContainText("5 of");
    await expect(batch.getByRole("button", { name: /Apply/ })).toHaveCount(0);
    let download = page.waitForEvent("download");
    await batch
      .getByRole("button", { name: "Save compiled default batch", exact: true })
      .click();
    expect(
      (await readFile((await (await download).path())!)).equals(
        Buffer.from(data.output, "base64"),
      ),
    ).toBe(true);
    download = page.waitForEvent("download");
    await batch
      .getByRole("button", { name: "Export exact batch review", exact: true })
      .click();
    expect(
      (await readFile((await (await download).path())!)).equals(exact),
    ).toBe(true);
    await batch.getByLabel("Find a batch default", { exact: true }).fill("");
    const viewport = batch.getByRole("region", {
      name: "Native batch defaults table viewport",
      exact: true,
    });
    await viewport.focus();
    await expect(viewport).toBeFocused();
    if (caf) {
      await viewport.evaluate((e) => (e.scrollLeft = 0));
      await page.keyboard.press("ArrowRight");
      await expect
        .poll(() => viewport.evaluate((e) => e.scrollLeft))
        .toBeGreaterThan(0);
    }
    await page.screenshot({
      path: info.outputPath(
        caf
          ? "native-default-batch-phone.png"
          : "native-default-batch-desktop.png",
      ),
    });
    await batch.locator(":scope > summary").click();
    await expect(
      compiler.getByLabel("Proposed native Real default", { exact: true }),
    ).toHaveValue("12.");
    await batch.locator(":scope > summary").click();
    await expect(
      batch.getByLabel("Proposed real value for controller/575_1.2_12", {
        exact: true,
      }),
    ).toHaveValue("0.1");
    await expect(reviewed(batch)).toHaveCount(0);
    expect(
      (
        await (
          await request.get(nativeScheduleWriteServer.url + "/api/session")
        ).json()
      ).field_network_open,
    ).toBe(false);
  });
test("invalid unfinished batch text stays retained without a preview request", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const data = seedDefaultBatch(nativeScheduleWriteServer.directory),
    compiler = await enter(page, data),
    batch = await expand(compiler);
  await propose(batch, data);
  const input = batch.getByLabel(
    "Proposed real value for controller/575_1.2_12",
    { exact: true },
  );
  await input.fill("1e-999");
  let posts = 0;
  page.on("request", (r) => {
    if (r.url().endsWith("/default-batch/preview")) posts++;
  });
  await batch
    .getByRole("button", { name: "Review local default batch", exact: true })
    .click();
  await expect(batch.getByRole("alert")).toContainText("finite float32");
  await expect(input).toHaveValue("1e-999");
  expect(posts).toBe(0);
});
for (const fault of ["source-authority", "review-order", "review-enum"])
  test(`altered ${fault} evidence cannot enable batch export`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const data = seedDefaultBatch(nativeScheduleWriteServer.directory);
    await page.route(
      fault === "source-authority"
        ? "**/default-batch/source"
        : "**/default-batch/preview",
      async (route) => {
        const response = await route.fetch({ maxRetries: 0 }),
          value = await response.json();
        if (fault === "source-authority") value.can_apply = true;
        else if (fault === "review-order") value.compilation.reverse.reverse();
        else
          value.compilation.independent
            .filter((r: any) => r.kind === "enum")
            .at(-1).compilation.maximum_code = 4294967295;
        await route.fulfill({ response, json: value });
      },
    );
    const compiler = await enter(page, data),
      batch = compiler.getByLabel("Native typed default batch", {
        exact: true,
      });
    await batch.locator(":scope > summary").click();
    if (fault !== "source-authority") {
      await expect(batch.getByRole("table")).toBeVisible();
      await propose(batch, data);
      await batch
        .getByRole("button", {
          name: "Review local default batch",
          exact: true,
        })
        .click();
    }
    await expect(batch.getByRole("alert")).toContainText(
      /does not match|differs/,
    );
    await expect(
      batch.getByRole("button", {
        name: "Save compiled default batch",
        exact: true,
      }),
    ).toHaveCount(0);
  });
test("coalesced raw value A B A retires an old batch Save before paint", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const data = seedDefaultBatch(nativeScheduleWriteServer.directory),
    compiler = await enter(page, data),
    batch = await expand(compiler);
  await propose(batch, data);
  await review(batch);
  const button = await batch
    .getByRole("button", { name: "Save compiled default batch", exact: true })
    .elementHandle();
  let exports = 0,
    downloads = 0;
  page.on("request", (r) => {
    if (r.url().endsWith("/default-batch/export")) exports++;
  });
  page.on("download", () => downloads++);
  await batch
    .getByLabel("Proposed real value for controller/575_1.2_12", {
      exact: true,
    })
    .evaluate((e, button) => {
      const setter = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )!.set!;
      for (const value of ["0.2", "0.1"]) {
        setter.call(e, value);
        e.dispatchEvent(new Event("input", { bubbles: true }));
      }
      (button as HTMLElement).click();
    }, button);
  await expect(reviewed(batch)).toHaveCount(0);
  expect(exports).toBe(0);
  expect(downloads).toBe(0);
  await expect(
    batch.getByLabel("Proposed real value for controller/575_1.2_12", {
      exact: true,
    }),
  ).toHaveValue("0.1");
});

for (const fault of ["header", "payload"])
  test(`a changed batch export ${fault} produces no local download`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const data = seedDefaultBatch(nativeScheduleWriteServer.directory),
      compiler = await enter(page, data),
      batch = await expand(compiler);
    await propose(batch, data);
    await review(batch);
    let downloads = 0;
    page.on("download", () => downloads++);
    await page.route("**/default-batch/export", async (route) => {
      const response = await route.fetch({ maxRetries: 0 }),
        body = await response.body(),
        headers = response.headers();
      if (fault === "header")
        headers["x-studio-artifact-sha256"] = "0".repeat(64);
      else body[body.length - 1] ^= 1;
      await route.fulfill({ response, body, headers });
    });
    await batch
      .getByRole("button", { name: "Save compiled default batch", exact: true })
      .click();
    await expect(batch.getByRole("alert")).toContainText("do not match");
    expect(downloads).toBe(0);
  });

test("a held old preview cannot replace a newer raw batch draft", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const data = seedDefaultBatch(nativeScheduleWriteServer.directory),
    compiler = await enter(page, data),
    batch = await expand(compiler);
  await propose(batch, data);
  let release = () => {},
    held = false;
  const gate = new Promise<void>((resolve) => (release = resolve));
  await page.route("**/default-batch/preview", async (route) => {
    if (held) return route.continue();
    held = true;
    const response = await route.fetch({ maxRetries: 0 });
    await gate;
    await route.fulfill({ response });
  });
  try {
    await batch
      .getByRole("button", { name: "Review local default batch", exact: true })
      .click();
    await expect.poll(() => held).toBe(true);
    const input = batch.getByLabel(
      "Proposed real value for controller/575_1.2_12",
      { exact: true },
    );
    await input.fill("0.2");
    const done = page.waitForResponse((r) =>
      r.url().endsWith("/default-batch/preview"),
    );
    release();
    await (await done).finished();
    await expect(reviewed(batch)).toHaveCount(0);
    await expect(input).toHaveValue("0.2");
    await review(batch);
    await expect(reviewed(batch).locator("pre")).toContainText(
      '"value_text": "0.2"',
    );
  } finally {
    release();
  }
});

test("a held source result cannot replace the later selected native capture", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const data = seedDefaultBatch(nativeScheduleWriteServer.directory),
    compiler = await enter(page, data);
  let release = () => {},
    held = false;
  const gate = new Promise<void>((resolve) => (release = resolve));
  await page.route("**/default-batch/source", async (route) => {
    if (route.request().postDataJSON().capture_id !== data.id || held)
      return route.continue();
    held = true;
    const response = await route.fetch({ maxRetries: 0 });
    await gate;
    await route.fulfill({ response });
  });
  const batch = compiler.getByLabel("Native typed default batch", {
    exact: true,
  });
  try {
    await batch.locator(":scope > summary").click();
    await expect.poll(() => held).toBe(true);
    await compiler
      .getByLabel("Retained native backup", { exact: true })
      .selectOption(data.other);
    await compiler
      .getByRole("button", { name: "Open retained backup", exact: true })
      .click();
    const newer = compiler.getByLabel("Native typed default batch", {
      exact: true,
    });
    await expect(newer.getByRole("table")).toBeVisible();
    const done = page.waitForResponse(
      (r) =>
        r.url().endsWith("/default-batch/source") &&
        r.request().postDataJSON().capture_id === data.id,
    );
    release();
    await (await done).finished();
    await expect(newer).toContainText("127.0.0.1:47929");
    await expect(newer).toContainText("0 of 16");
  } finally {
    release();
  }
});

test("a held export remains retired after changing a raw value away and back", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const data = seedDefaultBatch(nativeScheduleWriteServer.directory),
    compiler = await enter(page, data),
    batch = await expand(compiler);
  await propose(batch, data);
  await review(batch);
  let release = () => {},
    held = false,
    downloads = 0;
  const gate = new Promise<void>((resolve) => (release = resolve));
  page.on("download", () => downloads++);
  await page.evaluate(() => {
    const w = window as any,
      digest = crypto.subtle.digest.bind(crypto.subtle);
    w.__batchDigests = [];
    crypto.subtle.digest = ((...args: Parameters<SubtleCrypto["digest"]>) => {
      const p = digest(...args);
      w.__batchDigests.push(p);
      return p;
    }) as SubtleCrypto["digest"];
  });
  await page.route("**/default-batch/export", async (route) => {
    const response = await route.fetch({ maxRetries: 0 });
    held = true;
    await gate;
    await route.fulfill({ response });
  });
  try {
    await batch
      .getByRole("button", { name: "Save compiled default batch", exact: true })
      .click();
    await expect.poll(() => held).toBe(true);
    const input = batch.getByLabel(
      "Proposed real value for controller/575_1.2_12",
      { exact: true },
    );
    await input.fill("0.2");
    await input.fill("0.1");
    release();
    await expect
      .poll(() => page.evaluate(() => (window as any).__batchDigests.length))
      .toBeGreaterThan(0);
    await page.evaluate(async () => {
      await Promise.all((window as any).__batchDigests);
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(downloads).toBe(0);
    await expect(reviewed(batch)).toHaveCount(0);
    await expect(input).toHaveValue("0.1");
  } finally {
    release();
  }
});

test("sixteen actual selections retain their values and refuse a seventeenth", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const data = seedDefaultBatch(nativeScheduleWriteServer.directory, 12),
    compiler = await enter(page, data);
  const batch = compiler.getByLabel("Native typed default batch", {
    exact: true,
  });
  await batch.locator(":scope > summary").click();
  await expect(batch.getByRole("table").getByRole("row")).toHaveCount(18);
  await propose(batch, data);
  await expect(batch).toContainText("16 of 16");
  const unselected = data.source.fields.find(
    (r: any) =>
      !data.body.changes.some((c: any) => c.record_ref === r.field.ref),
  );
  await expect(
    batch.getByLabel(`Include ${unselected.field.ref} in batch`, {
      exact: true,
    }),
  ).toBeDisabled();
  await review(batch);
  await expect(reviewed(batch)).toContainText("16 of");
});

test("coalesced edits to two different fields preserve both raw values", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const data = seedDefaultBatch(nativeScheduleWriteServer.directory),
    compiler = await enter(page, data),
    batch = await expand(compiler);
  await propose(batch, data);
  const second = await batch
    .getByLabel("Proposed real value for controller/575_1.2_13", {
      exact: true,
    })
    .elementHandle();
  await batch
    .getByLabel("Proposed real value for controller/575_1.2_12", {
      exact: true,
    })
    .evaluate((first, second) => {
      const setter = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )!.set!;
      for (const [element, value] of [
        [first, "11."],
        [second, "19."],
      ] as [HTMLInputElement, string][]) {
        setter.call(element, value);
        element.dispatchEvent(new Event("input", { bubbles: true }));
      }
    }, second);
  await expect(
    batch.getByLabel("Proposed real value for controller/575_1.2_12", {
      exact: true,
    }),
  ).toHaveValue("11.");
  await expect(
    batch.getByLabel("Proposed real value for controller/575_1.2_13", {
      exact: true,
    }),
  ).toHaveValue("19.");
  await review(batch);
  await expect(reviewed(batch).locator("pre")).toContainText(
    '"value_text": "11."',
  );
  await expect(reviewed(batch).locator("pre")).toContainText(
    '"value_text": "19."',
  );
});
