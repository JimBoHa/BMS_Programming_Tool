import { test, expect } from "./nativeScheduleWriteFixture";
import type { Page, Locator } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { seedDefaultBatch } from "./native-default-batch-fixture";
import { seedBatchDraftSources } from "./native-batch-draft-fixture";
import {
  nativeBatchDraftDocument,
  nativeBatchDraftBytes,
} from "../src/nativeBatchDraftFile";
import {
  openNativeCompiler,
  chooseWorkspaceTask,
} from "./workspace-navigation";

const rawValues: Record<string, string> = {
  "controller/575_1.2_12": "",
  "controller/575_1.2_13": "-0",
  "controller/retained-boolean": "false",
  "controller/enum-1": "1e-",
  "controller/saved-enum": "  invalid Ω  ",
};
async function enter(page: Page, data: any, caf = false) {
  await page.goto("/");
  if (caf) {
    const choosing = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: /^Open a CAF file/ }).click();
    await (
      await choosing
    ).setFiles({
      name: "unfinished-batch.caf",
      mimeType: "application/octet-stream",
      buffer: Buffer.from(data.caf, "base64"),
    });
    await expect(
      page.getByLabel("Current CAF archive", { exact: true }),
    ).toHaveText("unfinished-batch.caf");
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
  const batch = compiler.getByLabel("Native typed default batch", {
    exact: true,
  });
  await batch.locator(":scope > summary").click();
  await expect(batch.getByRole("table").getByRole("row")).toHaveCount(
    data.source.fields.length + 1,
  );
  return { compiler, batch };
}
async function files(batch: Locator) {
  const panel = batch.getByLabel("Unfinished native batch draft files", {
    exact: true,
  });
  if (!(await panel.evaluate((e) => (e as HTMLDetailsElement).open)))
    await panel.locator("summary").click();
  return panel;
}
const input = (batch: Locator, kind = "real", ref = "controller/575_1.2_12") =>
  batch.getByLabel(`Proposed ${kind} value for ${ref}`, { exact: true });
async function propose(batch: Locator, values = rawValues) {
  for (const [ref, value] of Object.entries(values)) {
    await batch.getByLabel(`Include ${ref} in batch`, { exact: true }).check();
    if (ref === "controller/retained-boolean")
      await batch
        .getByLabel(`Proposed Boolean for ${ref}`, { exact: true })
        .setChecked(value === "true");
    else
      await input(batch, ref.includes("enum") ? "enum" : "real", ref).fill(
        value,
      );
  }
}
async function bytes(data: any, values = rawValues) {
  return Buffer.from(
    await nativeBatchDraftDocument(
      data.signal,
      data.source,
      values,
    ).arrayBuffer(),
  );
}
async function upload(
  panel: Locator,
  buffer: Buffer,
  name = "unfinished-native-batch.json",
) {
  await panel
    .getByLabel("Import unfinished batch draft", { exact: true })
    .setInputFiles({ name, mimeType: "application/json", buffer });
}
for (const caf of [false, true])
  test(`${caf ? "CAF phone" : "desktop"} raw typed batch transfers to a clean context without native review`, async ({
    page,
    browser,
    request,
    nativeScheduleWriteServer,
  }, info) => {
    if (caf) await page.setViewportSize({ width: 390, height: 844 });
    const data = seedDefaultBatch(nativeScheduleWriteServer.directory),
      { batch } = await enter(page, data, caf);
    await propose(batch);
    const panel = await files(batch),
      downloading = page.waitForEvent("download");
    await panel
      .getByRole("button", { name: "Save unfinished batch draft", exact: true })
      .click();
    const original = await readFile((await (await downloading).path())!);
    expect(original.equals(await bytes(data))).toBe(true);
    const clean = await browser.newContext({
      baseURL: nativeScheduleWriteServer.url,
      viewport: caf
        ? { width: 390, height: 844 }
        : { width: 1440, height: 1000 },
    });
    try {
      const other = await clean.newPage(),
        { batch: current } = await enter(other, data, caf),
        imported = await files(current);
      let posts = 0;
      other.on("request", (r) => {
        if (r.method() === "POST") posts++;
      });
      await upload(imported, original);
      await expect(current).toContainText("5 of 16 defaults selected");
      await expect(input(current)).toHaveValue("");
      await expect(input(current, "real", "controller/575_1.2_13")).toHaveValue(
        "-0",
      );
      await expect(input(current, "enum", "controller/enum-1")).toHaveValue(
        "1e-",
      );
      await expect(input(current, "enum", "controller/saved-enum")).toHaveValue(
        "  invalid Ω  ",
      );
      await expect(imported.getByRole("status")).toContainText(
        "Imported 5 unfinished batch fields",
      );
      await expect(
        current.getByRole("region", {
          name: "Reviewed native default batch",
          exact: true,
        }),
      ).toHaveCount(0);
      expect(posts).toBe(0);
      const again = other.waitForEvent("download");
      await imported
        .getByRole("button", {
          name: "Save unfinished batch draft",
          exact: true,
        })
        .click();
      expect(
        (await readFile((await (await again).path())!)).equals(original),
      ).toBe(true);
      await imported.locator("summary").scrollIntoViewIfNeeded();
      await imported
        .getByRole("button", {
          name: "Save unfinished batch draft",
          exact: true,
        })
        .focus();
      await other.screenshot({
        path: info.outputPath(
          caf ? "batch-draft-phone.png" : "batch-draft-desktop.png",
        ),
      });
      await chooseWorkspaceTask(other, "Overview");
      await openNativeCompiler(other);
      await expect(input(current)).toHaveValue("");
    } finally {
      await clean.close();
    }
    expect(
      (
        await (
          await request.get(nativeScheduleWriteServer.url + "/api/session")
        ).json()
      ).field_network_open,
    ).toBe(false);
  });

test("imported complete text still needs explicit review and exports the original compiled bytes", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const data = seedDefaultBatch(nativeScheduleWriteServer.directory),
    { batch } = await enter(page, data),
    panel = await files(batch);
  const values = Object.fromEntries(
    data.body.changes.map((c: any) => [
      c.record_ref,
      c.kind === "real" ? c.value_text : String(c.value),
    ]),
  );
  await upload(panel, await bytes(data, values));
  await expect(batch).toContainText("5 of 16 defaults selected");
  await expect(
    batch.getByRole("region", {
      name: "Reviewed native default batch",
      exact: true,
    }),
  ).toHaveCount(0);
  await batch
    .getByRole("button", { name: "Review local default batch", exact: true })
    .click();
  await expect(
    batch.getByRole("region", {
      name: "Reviewed native default batch",
      exact: true,
    }),
  ).toBeVisible();
  const download = page.waitForEvent("download");
  await batch
    .getByRole("button", { name: "Save compiled default batch", exact: true })
    .click();
  expect(
    (await readFile((await (await download).path())!)).equals(
      Buffer.from(data.output, "base64"),
    ),
  ).toBe(true);
});
test("an existing empty selected value refuses replacement until explicit discard", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const data = seedDefaultBatch(nativeScheduleWriteServer.directory),
    { batch } = await enter(page, data);
  await propose(batch, { "controller/575_1.2_12": "" });
  const panel = await files(batch),
    original = await bytes(data);
  await upload(panel, original);
  await expect(panel.getByRole("alert")).toContainText(
    "Discard the batch draft",
  );
  await expect(batch).toContainText("1 of 16 defaults selected");
  await expect(input(batch)).toHaveValue("");
  await batch
    .getByRole("button", { name: "Discard this batch draft", exact: true })
    .click();
  await upload(panel, original);
  await expect(batch).toContainText("5 of 16 defaults selected");
});
for (const fault of [
  "source",
  "unknown",
  "duplicate",
  "utf8",
  "size",
  "late field",
])
  test(`invalid batch file ${fault} installs no partial selections`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const data = seedDefaultBatch(nativeScheduleWriteServer.directory),
      { batch } = await enter(page, data),
      panel = await files(batch);
    let file = await bytes(data),
      value = JSON.parse(file.toString());
    if (fault === "source") value.source.capture_id = "0".repeat(32);
    if (fault === "unknown") value.token = "forbidden";
    if (fault === "late field")
      value.buffers.at(-1).value_text = "x".repeat(129);
    file = Buffer.from(JSON.stringify(value));
    if (fault === "duplicate")
      file = Buffer.from(
        file
          .toString()
          .replace(
            '"field_authority":false',
            '"field_authority":false,"field_authority":false',
          ),
      );
    if (fault === "utf8") file = Buffer.concat([file, Buffer.from([0xff])]);
    if (fault === "size")
      file = Buffer.concat([Buffer.alloc(nativeBatchDraftBytes, " "), file]);
    await upload(panel, file);
    await expect(panel.getByRole("alert")).toBeVisible();
    await expect(batch).toContainText("0 of 16 defaults selected");
    await expect(input(batch)).toHaveCount(0);
    await expect(
      panel.getByRole("button", {
        name: "Save unfinished batch draft",
        exact: true,
      }),
    ).toBeDisabled();
  });

async function holdRead(page: Page) {
  await page.evaluate(() => {
    const w = window as any,
      read = File.prototype.arrayBuffer,
      digest = crypto.subtle.digest.bind(crypto.subtle);
    w.__batchDigests = [];
    crypto.subtle.digest = ((...args: Parameters<SubtleCrypto["digest"]>) => {
      const result = digest(...args);
      w.__batchDigests.push(result);
      return result;
    }) as SubtleCrypto["digest"];
    File.prototype.arrayBuffer = function (this: File) {
      const result = read.call(this);
      if (this.name !== "held-native-batch.json") return result;
      return (w.__batchRead = result.then(
        (bytes) =>
          new Promise<ArrayBuffer>(
            (resolve) => (w.__batchRelease = () => resolve(bytes)),
          ),
      ));
    };
  });
}
async function releaseRead(page: Page) {
  await page.evaluate(async () => {
    const w = window as any;
    w.__batchRelease();
    await w.__batchRead;
    await Promise.all(w.__batchDigests);
    await Promise.resolve();
  });
}
for (const mode of [
  "draft ABA",
  "task ABA",
  "disclosure ABA",
  "visibility",
  "pagehide",
  "source",
])
  test(`held batch file read retires across ${mode}`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const data = seedDefaultBatch(nativeScheduleWriteServer.directory),
      { compiler, batch } = await enter(page, data),
      panel = await files(batch);
    await holdRead(page);
    await upload(
      panel,
      await bytes(data, { "controller/575_1.2_12": "11." }),
      "held-native-batch.json",
    );
    await expect
      .poll(() => page.evaluate(() => !!(window as any).__batchRelease))
      .toBe(true);
    if (mode === "draft ABA")
      await batch
        .getByLabel("Include controller/575_1.2_12 in batch", { exact: true })
        .evaluate((element) => {
          (element as HTMLInputElement).click();
          (element as HTMLInputElement).click();
        });
    if (mode === "task ABA") {
      await chooseWorkspaceTask(page, "Overview");
      await openNativeCompiler(page);
    }
    if (mode === "disclosure ABA")
      await panel.locator("summary").evaluate((element) => {
        (element as HTMLElement).click();
        (element as HTMLElement).click();
      });
    if (mode === "visibility")
      await page.evaluate(() => {
        const w = window as any;
        Object.defineProperty(document, "visibilityState", {
          configurable: true,
          get: () => (w.__batchHidden ? "hidden" : "visible"),
        });
        w.__batchHidden = true;
        document.dispatchEvent(new Event("visibilitychange"));
        w.__batchHidden = false;
        document.dispatchEvent(new Event("visibilitychange"));
      });
    if (mode === "pagehide")
      await page.evaluate(() => window.dispatchEvent(new Event("pagehide")));
    if (mode === "source")
      await compiler
        .getByLabel("Retained native backup", { exact: true })
        .selectOption(data.other);
    await releaseRead(page);
    if (mode === "source") {
      await compiler
        .getByLabel("Retained native backup", { exact: true })
        .selectOption(data.id);
      await compiler
        .getByRole("button", { name: "Open retained backup", exact: true })
        .click();
      await expect(batch.getByRole("table").getByRole("row")).toHaveCount(6);
    }
    await expect(batch).toContainText("0 of 16 defaults selected");
    await expect(input(batch)).toHaveCount(0);
    await expect(
      batch.getByRole("region", {
        name: "Reviewed native default batch",
        exact: true,
      }),
    ).toHaveCount(0);
  });

for (const mode of ["edit", "task"])
  test(`an actual held file digest cannot install after a ${mode} change`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const data = seedDefaultBatch(nativeScheduleWriteServer.directory),
      { batch } = await enter(page, data),
      panel = await files(batch);
    await page.evaluate(() => {
      const w = window as any,
        digest = crypto.subtle.digest.bind(crypto.subtle);
      crypto.subtle.digest = ((...args: Parameters<SubtleCrypto["digest"]>) => {
        const actual = digest(...args);
        return (w.__batchDigest = actual.then(
          (bytes) =>
            new Promise<ArrayBuffer>(
              (resolve) => (w.__batchReleaseDigest = () => resolve(bytes)),
            ),
        ));
      }) as SubtleCrypto["digest"];
    });
    await upload(panel, await bytes(data));
    await expect
      .poll(() => page.evaluate(() => !!(window as any).__batchReleaseDigest))
      .toBe(true);
    if (mode === "edit")
      await propose(batch, { "controller/575_1.2_12": "19." });
    else {
      await chooseWorkspaceTask(page, "Overview");
      await openNativeCompiler(page);
    }
    await page.evaluate(async () => {
      const w = window as any;
      w.__batchReleaseDigest();
      await w.__batchDigest;
      await Promise.resolve();
    });
    await expect(batch).toContainText(
      mode === "edit"
        ? "1 of 16 defaults selected"
        : "0 of 16 defaults selected",
    );
    if (mode === "edit") await expect(input(batch)).toHaveValue("19.");
    else await expect(input(batch)).toHaveCount(0);
  });
for (const mode of ["unavailable", "failure"])
  test(`file digest ${mode} keeps the original crypto behavior`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const data = seedDefaultBatch(nativeScheduleWriteServer.directory),
      { batch } = await enter(page, data),
      panel = await files(batch);
    await page.evaluate((mode) => {
      if (mode === "unavailable")
        Object.defineProperty(crypto, "subtle", {
          configurable: true,
          value: undefined,
        });
      else
        crypto.subtle.digest = () =>
          Promise.reject(new Error("Authored batch digest refusal"));
    }, mode);
    await upload(panel, await bytes(data));
    if (mode === "unavailable") {
      await expect(batch).toContainText("5 of 16 defaults selected");
      await expect(panel.getByRole("status")).toContainText("SHA-256");
    } else {
      await expect(panel.getByRole("alert")).toContainText(
        "Authored batch digest refusal",
      );
      await expect(batch).toContainText("0 of 16 defaults selected");
    }
  });

test("thirty-two retained source batches refuse import without eviction until explicit discard", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  // This test performs 33 real source selections/import attempts, rather than
  // filling a private React Map or relaxing the production source budget.
  test.setTimeout(60000);
  const sources = seedBatchDraftSources(nativeScheduleWriteServer.directory),
    { compiler, batch } = await enter(page, sources[0]);
  async function openSource(data: any) {
    await compiler
      .getByLabel("Retained native backup", { exact: true })
      .selectOption(data.id);
    await compiler
      .getByRole("button", { name: "Open retained backup", exact: true })
      .click();
    await expect(batch.getByRole("table").getByRole("row")).toHaveCount(6);
  }
  for (let i = 0; i < 32; i++) {
    if (i) await openSource(sources[i]);
    await upload(
      await files(batch),
      await bytes(sources[i], { "controller/575_1.2_12": `${i}.` }),
    );
    await expect(input(batch)).toHaveValue(`${i}.`);
  }
  await openSource(sources[32]);
  const panel = await files(batch);
  await upload(
    panel,
    await bytes(sources[32], { "controller/575_1.2_12": "33." }),
  );
  await expect(panel.getByRole("alert")).toContainText(
    "full 32-source batch draft cache",
  );
  await expect(batch).toContainText("0 of 16 defaults selected");
  await openSource(sources[0]);
  await expect(input(batch)).toHaveValue("0.");
  await batch
    .getByRole("button", { name: "Discard this batch draft", exact: true })
    .click();
  await openSource(sources[32]);
  await upload(
    await files(batch),
    await bytes(sources[32], { "controller/575_1.2_12": "33." }),
  );
  await expect(input(batch)).toHaveValue("33.");
  await openSource(sources[1]);
  await expect(input(batch)).toHaveValue("1.");
});

test("coalesced edits save the current raw batch through the refreshed action", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const data = seedDefaultBatch(nativeScheduleWriteServer.directory),
    { batch } = await enter(page, data);
  await propose(batch, {
    "controller/575_1.2_12": "11.",
    "controller/575_1.2_13": "22.",
  });
  const panel = await files(batch),
    button = await panel
      .getByRole("button", { name: "Save unfinished batch draft", exact: true })
      .elementHandle(),
    second = await input(
      batch,
      "real",
      "controller/575_1.2_13",
    ).elementHandle();
  const downloading = page.waitForEvent("download");
  await input(batch).evaluate(
    (first, { second, button }) => {
      const setter = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )!.set!;
      for (const [element, value] of [
        [first, "19."],
        [second, "29."],
      ] as [HTMLInputElement, string][]) {
        setter.call(element, value);
        element.dispatchEvent(new Event("input", { bubbles: true }));
      }
      // Each discrete input event may flush a fresh React handler before paint.
      // A current Save is valid; it must use both latest admitted raw buffers.
      (button as HTMLElement).click();
    },
    { second, button },
  );
  const document = JSON.parse(
    (await readFile((await (await downloading).path())!)).toString(),
  );
  expect(
    Object.fromEntries(
      document.buffers.map((r: any) => [r.field.record_ref, r.value_text]),
    ),
  ).toEqual({ "controller/575_1.2_12": "19.", "controller/575_1.2_13": "29." });
  expect(document.native_review_created).toBe(false);
  expect(document.field_authority).toBe(false);
});

test("sixteen imported selections fit and a distinct seventeenth is refused as a whole", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const data = seedDefaultBatch(nativeScheduleWriteServer.directory, 12),
    { batch } = await enter(page, data),
    panel = await files(batch);
  const values = Object.fromEntries(
    data.source.fields
      .slice(0, 16)
      .map((r: any) => [r.field.ref, r.kind === "boolean" ? "false" : "12."]),
  );
  const original = await bytes(data, values);
  await upload(panel, original);
  await expect(batch).toContainText("16 of 16 defaults selected");
  const last = data.source.fields[16].field.ref;
  await expect(
    batch.getByLabel(`Include ${last} in batch`, { exact: true }),
  ).toBeDisabled();
  const extra = JSON.parse((await bytes(data, { [last]: "12." })).toString())
      .buffers[0],
    oversized = JSON.parse(original.toString());
  oversized.buffers.push(extra);
  await batch
    .getByRole("button", { name: "Discard this batch draft", exact: true })
    .click();
  await upload(panel, Buffer.from(JSON.stringify(oversized)));
  await expect(panel.getByRole("alert")).toBeVisible();
  await expect(batch).toContainText("0 of 16 defaults selected");
});
