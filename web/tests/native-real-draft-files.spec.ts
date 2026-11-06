import { test, expect } from "./nativeScheduleWriteFixture";
import type { Page, Locator } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { first, second, seedRealDrafts } from "./native-real-draft-fixture";
import {
  nativeRealDraftDocument,
  nativeRealDraftBytes,
} from "../src/nativeRealDraftFile";
import {
  openNativeCompiler,
  chooseWorkspaceTask,
} from "./workspace-navigation";

async function enter(page: Page, data: any, id = data.a.id, caf = false) {
  await page.goto("/");
  if (caf) {
    const chooser = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: /^Open a CAF file/ }).click();
    await (
      await chooser
    ).setFiles({
      name: "unfinished-real.caf",
      mimeType: "application/octet-stream",
      buffer: Buffer.from(data.caf, "base64"),
    });
    await expect(
      page.getByLabel("Current CAF archive", { exact: true }),
    ).toHaveText("unfinished-real.caf");
  } else
    await page
      .getByRole("button", { name: "New application", exact: true })
      .click();
  await openNativeCompiler(page);
  const panel = page.getByRole("region", {
    name: "Native backup default compiler",
    exact: true,
  });
  await panel
    .getByLabel("Retained native backup", { exact: true })
    .selectOption(id);
  await panel
    .getByRole("button", { name: "Open retained backup", exact: true })
    .click();
  await panel
    .getByLabel("Native Real default", { exact: true })
    .selectOption(first);
  return panel;
}
const valueInput = (panel: Locator) =>
  panel.getByLabel("Proposed native Real default", { exact: true });
async function files(panel: Locator) {
  const details = panel.getByLabel("Unfinished native Real draft files", {
    exact: true,
  });
  if (!(await details.evaluate((e) => (e as HTMLDetailsElement).open)))
    await details.locator("summary").click();
  return details;
}
async function bytes(data: any, value = "12.", which = "a") {
  const source = data[which].source,
    field = source.fields.find((f: any) => f.ref === first);
  return Buffer.from(
    await nativeRealDraftDocument(source, field, value).arrayBuffer(),
  );
}
async function upload(
  details: Locator,
  buffer: Buffer,
  name = "unfinished-native-real.json",
) {
  await details
    .getByLabel("Import unfinished Real draft", { exact: true })
    .setInputFiles({ name, mimeType: "application/json", buffer });
}
for (const caf of [false, true])
  test(`${caf ? "CAF phone" : "desktop"} unfinished Real text transfers to a clean browser context without review authority`, async ({
    page,
    browser,
    request,
    nativeScheduleWriteServer,
  }, info) => {
    if (caf) await page.setViewportSize({ width: 390, height: 844 });
    const data = seedRealDrafts(nativeScheduleWriteServer.directory),
      panel = await enter(page, data, data.a.id, caf);
    const raw = caf ? "-0" : "12.";
    await valueInput(panel).fill(raw);
    const details = await files(panel),
      download = page.waitForEvent("download");
    await details
      .getByRole("button", { name: "Save unfinished Real draft", exact: true })
      .click();
    const artifact = await download,
      original = await readFile((await artifact.path())!);
    expect(JSON.parse(original.toString()).buffer.value_text).toBe(raw);
    await expect(valueInput(panel)).toHaveValue(raw);
    const clean = await browser.newContext({
      baseURL: nativeScheduleWriteServer.url,
      viewport: caf
        ? { width: 390, height: 844 }
        : { width: 1440, height: 1000 },
    });
    try {
      const other = await clean.newPage(),
        current = await enter(other, data, data.a.id, caf),
        imported = await files(current);
      let posts = 0;
      other.on("request", (r) => {
        if (r.method() === "POST") posts++;
      });
      await upload(imported, original);
      await expect(valueInput(current)).toHaveValue(raw);
      await expect(imported.getByRole("status")).toContainText(
        "Imported unfinished text",
      );
      await expect(
        current.getByRole("region", {
          name: "Reviewed native compilation",
          exact: true,
        }),
      ).toHaveCount(0);
      expect(posts).toBe(0);
      await imported.locator("summary").scrollIntoViewIfNeeded();
      await imported
        .getByRole("button", {
          name: "Save unfinished Real draft",
          exact: true,
        })
        .focus();
      await expect(
        imported.getByRole("button", {
          name: "Save unfinished Real draft",
          exact: true,
        }),
      ).toBeFocused();
      await other.screenshot({
        path: info.outputPath(
          caf ? "native-real-draft-phone.png" : "native-real-draft-desktop.png",
        ),
      });
      await other.reload();
      const resumed = await enter(other, data, data.a.id, caf);
      await expect(valueInput(resumed)).toHaveValue(raw);
      await expect(
        resumed.getByRole("region", {
          name: "Reviewed native compilation",
          exact: true,
        }),
      ).toHaveCount(0);
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

test("import refuses to replace an existing ordinary draft and keeps its local review", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const data = seedRealDrafts(nativeScheduleWriteServer.directory),
    panel = await enter(page, data);
  await valueInput(panel).fill("0.1");
  await panel
    .getByRole("button", { name: "Review native compilation", exact: true })
    .click();
  const review = panel.getByRole("region", {
    name: "Reviewed native compilation",
    exact: true,
  });
  await expect(review).toBeVisible();
  const details = await files(panel);
  await upload(details, await bytes(data));
  await expect(details.getByRole("alert")).toContainText(
    "Discard the selected field draft",
  );
  await expect(valueInput(panel)).toHaveValue("0.1");
  await expect(review).toBeVisible();
});

for (const fault of ["source", "authority", "duplicate", "utf8", "size"])
  test(`${fault} unfinished Real file leaves the selected value and all review authority untouched`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const data = seedRealDrafts(nativeScheduleWriteServer.directory),
      panel = await enter(page, data),
      details = await files(panel);
    let file = await bytes(data, "12.", fault === "source" ? "b" : "a");
    if (fault === "authority") {
      const value = JSON.parse(file.toString());
      value.token = "forbidden-old-plan";
      file = Buffer.from(JSON.stringify(value));
    }
    if (fault === "duplicate")
      file = Buffer.from(
        file
          .toString()
          .replace(
            '"field_authority": false',
            '"field_authority": false, "field_authority": false',
          ),
      );
    if (fault === "utf8") file = Buffer.concat([file, Buffer.from([0xff])]);
    if (fault === "size")
      file = Buffer.concat([Buffer.alloc(nativeRealDraftBytes, " "), file]);
    await upload(details, file);
    await expect(details.getByRole("alert")).toBeVisible();
    await expect(valueInput(panel)).toHaveValue("42");
    await expect(
      panel.getByRole("region", {
        name: "Reviewed native compilation",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      details.getByRole("button", {
        name: "Save unfinished Real draft",
        exact: true,
      }),
    ).toBeDisabled();
  });

async function holdRead(page: Page) {
  await page.evaluate(() => {
    const w = window as any,
      read = File.prototype.arrayBuffer,
      digest = crypto.subtle.digest.bind(crypto.subtle);
    w.__draftDigests = [];
    crypto.subtle.digest = ((...args: Parameters<SubtleCrypto["digest"]>) => {
      const p = digest(...args);
      w.__draftDigests.push(p);
      return p;
    }) as SubtleCrypto["digest"];
    File.prototype.arrayBuffer = function () {
      const result = read.call(this);
      if (this.name !== "held-native-raw.json") return result;
      return (w.__heldRead = result.then(
        (bytes) =>
          new Promise<ArrayBuffer>((resolve) => {
            w.__releaseDraft = () => resolve(bytes);
          }),
      ));
    };
  });
}
async function releaseRead(page: Page) {
  await page.evaluate(async () => {
    const w = window as any;
    w.__releaseDraft();
    await w.__heldRead;
    // Drain the actual digest requests made by the import, if any. The test
    // does not replace hash results, add retries or change a product deadline.
    await Promise.all(w.__draftDigests);
    await Promise.resolve();
  });
}
for (const mode of [
  "field ABA",
  "task change",
  "page hide",
  "document hide",
  "disclosure ABA",
])
  test(`a held raw file cannot restore text after ${mode}`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const data = seedRealDrafts(nativeScheduleWriteServer.directory),
      panel = await enter(page, data),
      details = await files(panel);
    await holdRead(page);
    await upload(details, await bytes(data), "held-native-raw.json");
    await expect
      .poll(() => page.evaluate(() => typeof (window as any).__releaseDraft))
      .toBe("function");
    if (mode === "field ABA") {
      await panel.getByLabel("Native Real default", { exact: true }).evaluate(
        (e, refs) => {
          const select = e as HTMLSelectElement;
          for (const ref of refs) {
            select.value = ref;
            select.dispatchEvent(new Event("change", { bubbles: true }));
          }
        },
        [second, first],
      );
    } else if (mode === "disclosure ABA") {
      await details.locator("summary").evaluate((element) => {
        (element as HTMLElement).click();
        (element as HTMLElement).click();
      });
      await expect(details).toHaveAttribute("open", "");
    } else if (mode === "page hide") {
      await page.evaluate(() => window.dispatchEvent(new Event("pagehide")));
    } else if (mode === "document hide") {
      await page.evaluate(() => {
        Object.defineProperty(document, "visibilityState", {
          configurable: true,
          value: "hidden",
        });
        document.dispatchEvent(new Event("visibilitychange"));
        Object.defineProperty(document, "visibilityState", {
          configurable: true,
          value: "visible",
        });
        document.dispatchEvent(new Event("visibilitychange"));
      });
    } else {
      await chooseWorkspaceTask(page, "Overview");
      await openNativeCompiler(page);
    }
    await releaseRead(page);
    await expect(valueInput(panel)).toHaveValue("42");
    expect(
      await page.evaluate(() =>
        Object.keys(sessionStorage)
          .filter((k) => k.startsWith("bms-effective-native-default/1/"))
          .map((k) => sessionStorage.getItem(k)),
      ),
    ).not.toContain("12.");
    await expect(
      panel.getByRole("region", {
        name: "Reviewed native compilation",
        exact: true,
      }),
    ).toHaveCount(0);
  });

test("a full 64-field draft cache refuses import without evicting earlier text", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const data = seedRealDrafts(nativeScheduleWriteServer.directory),
    source = data.full.source;
  expect(source.fields).toHaveLength(65);
  await page.goto("/");
  await page.evaluate((source) => {
    for (const field of source.fields.filter(
      (f: any) => f.ref !== "controller/signal-10",
    ))
      sessionStorage.setItem(
        "bms-effective-native-default/1/" +
          JSON.stringify([
            source.snapshot_sha256,
            field.ref,
            field.encoded_sha256,
          ]),
        "retained " + field.ref,
      );
  }, source);
  const panel = await enter(page, data, data.full.id),
    details = await files(panel),
    field = source.fields.find((f: any) => f.ref === first);
  await upload(
    details,
    Buffer.from(
      await nativeRealDraftDocument(source, field, "12.").arrayBuffer(),
    ),
  );
  await expect(details.getByRole("alert")).toContainText(
    "can no longer be installed",
  );
  await expect(valueInput(panel)).toHaveValue("42");
  expect(
    await page.evaluate(
      () =>
        Object.keys(sessionStorage).filter((k) =>
          k.startsWith("bms-effective-native-default/1/"),
        ).length,
    ),
  ).toBe(64);
  await panel
    .getByLabel("Native Real default", { exact: true })
    .selectOption(second);
  await expect(valueInput(panel)).toHaveValue("retained " + second);
});

test("restoring the same raw text after discard cannot revive a previous native review", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const data = seedRealDrafts(nativeScheduleWriteServer.directory),
    panel = await enter(page, data);
  await valueInput(panel).fill("0.1");
  await panel
    .getByRole("button", { name: "Review native compilation", exact: true })
    .click();
  const review = panel.getByRole("region", {
    name: "Reviewed native compilation",
    exact: true,
  });
  await expect(review).toBeVisible();
  await panel
    .getByRole("button", { name: "Discard selected field draft", exact: true })
    .click();
  await expect(review).toHaveCount(0);
  const details = await files(panel);
  await upload(details, await bytes(data, "0.1"));
  await expect(valueInput(panel)).toHaveValue("0.1");
  await expect(details.getByRole("status")).toContainText(
    "Imported unfinished text",
  );
  await expect(review).toHaveCount(0);
});

for (const mode of ["unavailable", "failure"])
  test(`raw draft hashing handles ${mode} native browser crypto without partial text`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const data = seedRealDrafts(nativeScheduleWriteServer.directory),
      panel = await enter(page, data),
      details = await files(panel);
    await page.evaluate((mode) => {
      if (mode === "unavailable")
        Object.defineProperty(crypto, "subtle", { value: undefined });
      else
        crypto.subtle.digest = () =>
          Promise.reject(new Error("Authored digest refusal"));
    }, mode);
    await upload(details, await bytes(data));
    if (mode === "unavailable") {
      await expect(valueInput(panel)).toHaveValue("12.");
      await expect(details.getByRole("status")).toContainText(
        "Imported unfinished text",
      );
    } else {
      await expect(details.getByRole("alert")).toContainText(
        "Authored digest refusal",
      );
      await expect(valueInput(panel)).toHaveValue("42");
    }
    await expect(
      panel.getByRole("region", {
        name: "Reviewed native compilation",
        exact: true,
      }),
    ).toHaveCount(0);
  });

test("typing while the actual file digest is held retires the pending import", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const data = seedRealDrafts(nativeScheduleWriteServer.directory),
    panel = await enter(page, data),
    details = await files(panel);
  await page.evaluate(() => {
    const w = window as any,
      digest = crypto.subtle.digest.bind(crypto.subtle);
    crypto.subtle.digest = ((...args: Parameters<SubtleCrypto["digest"]>) => {
      const actual = digest(...args);
      return (w.__heldDigest = new Promise<ArrayBuffer>((resolve, reject) => {
        w.__releaseDigest = () => actual.then(resolve, reject);
      }));
    }) as SubtleCrypto["digest"];
  });
  await upload(details, await bytes(data));
  await expect
    .poll(() => page.evaluate(() => typeof (window as any).__releaseDigest))
    .toBe("function");
  await valueInput(panel).fill("14.");
  await page.evaluate(async () => {
    const w = window as any;
    w.__releaseDigest();
    await w.__heldDigest;
    await Promise.resolve();
  });
  await expect(valueInput(panel)).toHaveValue("14.");
  await expect(details.getByRole("status")).toHaveCount(0);
  await expect(
    panel.getByRole("region", {
      name: "Reviewed native compilation",
      exact: true,
    }),
  ).toHaveCount(0);
});

test("an imported empty string remains an existing draft and refuses replacement", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const data = seedRealDrafts(nativeScheduleWriteServer.directory),
    panel = await enter(page, data),
    details = await files(panel);
  await upload(details, await bytes(data, ""));
  await expect(valueInput(panel)).toHaveValue("");
  await expect(details.getByRole("status")).toContainText(
    "Imported unfinished text",
  );
  await upload(details, await bytes(data, "12."));
  await expect(details.getByRole("alert")).toContainText(
    "Discard the selected field draft",
  );
  await expect(valueInput(panel)).toHaveValue("");
});
