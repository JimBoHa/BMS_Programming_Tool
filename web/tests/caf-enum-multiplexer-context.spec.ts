import { test, expect } from "./nativeScheduleWriteFixture";
import {
  enter,
  source,
  inspect,
  prepare,
  logic,
} from "./caf-enum-multiplexer-fixture";
import { savedCopy, type Family } from "./caf-open-copy-fixture";
import { connectionSeal } from "../src/nativeConnectionContract";
const family: Family = {
  name: "Enum Multiplexer",
  kind: "multiplexer",
  primitive: true,
  source: () => source(),
};

test("Float and Enum prototypes keep separate raw drafts through a copied file and return", async ({
  page,
}) => {
  let editor = await enter(page, "mixed");
  await editor.getByLabel("New block X", { exact: true }).fill("240");
  await editor
    .getByLabel("Block prototype", { exact: true })
    .selectOption("8-1/575_1.562_130");
  editor = await inspect(page);
  await expect(editor).toContainText(
    "Float inputs and output; Boolean selector.",
  );
  await editor.getByLabel("New block X", { exact: true }).fill("-");
  await editor
    .getByLabel("Block prototype", { exact: true })
    .selectOption("8-1/575_1.562_150");
  editor = await inspect(page);
  await expect(editor.getByLabel("New block X", { exact: true })).toHaveValue(
    "240",
  );
  const proof = await savedCopy(page, family, editor);
  page.on("dialog", (d) => d.accept());
  await editor
    .getByRole("button", { name: "Open CAF copy", exact: true })
    .click();
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("enum-multiplexer-enum-multiplexer-copy.caf");
  editor = await inspect(page);
  await expect(
    editor.getByLabel("Block prototype", { exact: true }),
  ).toHaveValue(proof.creation.selection.new_ref);
  await expect(editor).toContainText(
    "Enum inputs and output; Boolean selector.",
  );
  await page
    .getByLabel("Open local CAF application", { exact: true })
    .setInputFiles({
      name: "original.caf",
      mimeType: "application/octet-stream",
      buffer: source("mixed"),
    });
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("original.caf");
  await logic(page);
  await page
    .getByLabel("Recorded block type", { exact: true })
    .selectOption("multiplexer");
  editor = await inspect(page);
  await editor
    .getByLabel("Block prototype", { exact: true })
    .selectOption("8-1/575_1.562_150");
  editor = await inspect(page);
  await expect(editor.getByLabel("New block X", { exact: true })).toHaveValue(
    "240",
  );
  await editor
    .getByLabel("Block prototype", { exact: true })
    .selectOption("8-1/575_1.562_130");
  editor = await inspect(page);
  await expect(editor.getByLabel("New block X", { exact: true })).toHaveValue(
    "-",
  );
  await expect(
    editor.getByRole("button", { name: "Open CAF copy", exact: true }),
  ).toHaveCount(0);
});

test("a retired late Enum Multiplexer export cannot download or offer Open after kind ABA", async ({
  page,
}) => {
  let editor = await enter(page, "mixed");
  await prepare(page);
  let release!: () => void, started!: () => void, completed!: () => void;
  const held = new Promise<void>((r) => (release = r)),
    entered = new Promise<void>((r) => (started = r)),
    finished = new Promise<void>((r) => (completed = r));
  await page.route("**/float-multiplexer-copy/export", async (route) => {
    const response = await route.fetch({ maxRetries: 0 });
    started();
    await held;
    await route.fulfill({ response });
    completed();
  });
  const downloads: string[] = [];
  page.on("download", (d) => downloads.push(d.suggestedFilename()));
  await editor
    .getByRole("button", { name: "Save block CAF copy", exact: true })
    .click();
  await entered;
  await page
    .getByLabel("Recorded block type", { exact: true })
    .selectOption("boolean");
  await page
    .getByLabel("Recorded block type", { exact: true })
    .selectOption("multiplexer");
  editor = await inspect(page);
  release();
  await finished;
  await page.unroute("**/float-multiplexer-copy/export");
  await prepare(page);
  expect(downloads).toEqual([]);
  await expect(
    editor.getByRole("button", { name: "Open CAF copy", exact: true }),
  ).toHaveCount(0);
});

test("a resealed unsupported Enum default namespace is refused before authoring", async ({
  page,
}) => {
  await page.route("**/float-multiplexer-copy/source", async (route) => {
    const response = await route.fetch({ maxRetries: 0 }),
      data = await response.json();
    data.children[3].default_encoding_set = 366;
    const { selection_sha256, ...body } = data;
    void selection_sha256;
    data.selection_sha256 = await connectionSeal(body);
    await route.fulfill({ response, json: data });
  });
  await page.goto("/");
  await page
    .getByLabel("Open local CAF application", { exact: true })
    .setInputFiles({
      name: "enum.caf",
      mimeType: "application/octet-stream",
      buffer: source(),
    });
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("enum.caf");
  await logic(page);
  await page
    .locator(".caf-constant-copy:visible")
    .locator("summary")
    .first()
    .click();
  const editor = page.getByRole("region", {
    name: "CAF block creation",
    exact: true,
  });
  await editor
    .getByRole("button", { name: "Inspect block prototype", exact: true })
    .click();
  await expect(editor.getByRole("alert")).toContainText(
    "source proof does not match",
  );
  await expect(editor.getByLabel("New block X", { exact: true })).toHaveCount(
    0,
  );
});

test("page lifecycle retains Enum coordinates and retires saved Open authority", async ({
  page,
}) => {
  let editor = await enter(page, "two-no-text");
  await editor.getByLabel("New block X", { exact: true }).fill("190");
  await savedCopy(page, family, editor);
  await page.evaluate(() => window.dispatchEvent(new Event("pagehide")));
  editor = await inspect(page);
  await expect(editor.getByLabel("New block X", { exact: true })).toHaveValue(
    "190",
  );
  await expect(
    editor.getByRole("button", { name: "Open CAF copy", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("enum-multiplexer.caf");
});
