import { expect, test, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";

const root = path.resolve("..");
const python = path.join(root, ".venv/bin/python");
function fixture() {
  return execFileSync(
    python,
    [
      "-c",
      "from tests.test_caf_hardware import fixture; import sys; sys.stdout.buffer.write(fixture(model='Other-Controller-Family').original)",
    ],
    { cwd: root },
  );
}

async function openCaf(page: Page, name: string) {
  const choosing = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: /^Open a CAF file/ }).click();
  await (
    await choosing
  ).setFiles({
    name,
    mimeType: "application/octet-stream",
    buffer: fixture(),
  });
}

test("CAF instance review saves both native identity fields and preserves the application", async ({
  page,
}) => {
  await page.goto("/");
  await openCaf(page, "authored.caf");
  const panel = page.getByLabel("CAF device instance", { exact: true });
  await expect(panel).toContainText("current instance 99");
  const input = panel.getByLabel("New CAF device instance (0–4194302)", {
    exact: true,
  });
  await input.fill("5336");
  await panel
    .getByRole("button", { name: "Review CAF instance change", exact: true })
    .click();
  await expect(panel.getByLabel("Reviewed CAF instance change")).toContainText(
    "99 → 5336",
  );
  const pending = page.waitForEvent("download");
  await panel
    .getByRole("button", { name: "Save CAF instance copy", exact: true })
    .click();
  const downloaded = await pending;
  expect(downloaded.suggestedFilename()).toBe("authored-instance-5336.caf");
  const readback = JSON.parse(
    execFileSync(
      python,
      [
        "-c",
        "from pathlib import Path; import sys,json; from bms_tool.caf import CafArchive; from bms_tool.caf_instance import CafInstanceEditor; from tests.test_caf_hardware import fixture; a=CafArchive(Path(sys.argv[1]).read_bytes()); original=fixture(model='Other-Controller-Family'); expected=original.xml.replace(b'objectid=\"99\"',b'objectid=\"5336\"').replace(b'<BACoid id=\"8\">99</BACoid>',b'<BACoid id=\"8\">5336</BACoid>'); print(json.dumps({'exact_xml':a.xml==expected,'instance':CafInstanceEditor(a).current,'same_refs':list(a.objects)==list(original.objects)}))",
        (await downloaded.path())!,
      ],
      { cwd: root },
    ).toString(),
  );
  expect(readback).toEqual({
    exact_xml: true,
    instance: 5336,
    same_refs: true,
  });
  await expect(panel).toContainText("Saved a separate CAF copy");
  await expect(
    (await page.request.get("/api/session")).json(),
  ).resolves.toHaveProperty("field_network_open", false);
  await input.fill("5337");
  await expect(panel.getByLabel("Reviewed CAF instance change")).toHaveCount(0);
  page.once("dialog", (dialog) => dialog.dismiss());
  await page.locator('input[type=file][accept=".caf"]').first().setInputFiles({
    name: "replacement.caf",
    mimeType: "application/octet-stream",
    buffer: fixture(),
  });
  await expect(page.getByLabel("Current CAF archive")).toHaveText(
    "authored.caf",
  );
  await expect(input).toHaveValue("5337");
});

test("a delayed instance review cannot follow a replacement CAF", async ({
  page,
}) => {
  let release!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  let started!: () => void;
  const ready = new Promise<void>((resolve) => {
    started = resolve;
  });
  await page.route("**/api/caf/*/device-instance/preview", async (route) => {
    const response = await route.fetch();
    started();
    await held;
    await route.fulfill({ response });
  });
  await page.goto("/");
  await openCaf(page, "first.caf");
  const picker = page.locator('input[type=file][accept=".caf"]').first();
  const panel = page.getByLabel("CAF device instance", { exact: true });
  await panel.getByLabel("New CAF device instance (0–4194302)").fill("5336");
  await panel
    .getByRole("button", { name: "Review CAF instance change", exact: true })
    .click();
  await ready;
  page.once("dialog", (dialog) => dialog.accept());
  await picker.setInputFiles({
    name: "second.caf",
    mimeType: "application/octet-stream",
    buffer: fixture(),
  });
  await expect(page.getByLabel("Current CAF archive")).toHaveText("second.caf");
  release();
  await expect(
    panel.getByLabel("New CAF device instance (0–4194302)"),
  ).toHaveValue("");
  await expect(panel.getByLabel("Reviewed CAF instance change")).toHaveCount(0);
});
