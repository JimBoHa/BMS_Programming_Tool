import { expect, test, type Locator, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";

const root = path.resolve("..");
const python = path.join(root, ".venv/bin/python");
function fixture(unsupported = false) {
  return execFileSync(
    python,
    [
      "-c",
      `from tests.test_caf_hardware import fixture; import sys; sys.stdout.buffer.write(fixture(model=${unsupported ? "'Unknown-Controller'" : "'MS-VMA1630-0'"}).original)`,
    ],
    { cwd: root },
  );
}

async function pickCaf(button: Locator, name: string, unsupported = false) {
  const chooser = button.page().waitForEvent("filechooser");
  await button.click();
  const picker = await chooser;
  await picker.setFiles({
    name,
    mimeType: "application/octet-stream",
    buffer: fixture(unsupported),
  });
}

async function hardwareMapping(page: Page) {
  const tasks = page.getByRole("navigation", {
    name: "CAF application tasks",
    exact: true,
  });
  await expect(tasks).toBeVisible();
  const compact = tasks.getByRole("combobox", {
    name: "CAF application tasks",
    exact: true,
  });
  if (await compact.isVisible())
    await compact.selectOption({ label: "Hardware mapping" });
  else
    await tasks
      .getByRole("button", { name: "Hardware mapping", exact: true })
      .click();
  return page.getByRole("region", {
    name: "Offline CAF hardware bindings",
    exact: true,
  });
}

async function openHardware(page: Page, name: string, unsupported = false) {
  await page.goto("/");
  await pickCaf(
    page.getByRole("button", { name: /^Open a CAF file/ }),
    name,
    unsupported,
  );
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText(name);
  return hardwareMapping(page);
}

test("native CAF terminal review exports real guarded binding changes without opening field access", async ({
  page,
}) => {
  const panel = await openHardware(page, "authored.caf");
  await expect(panel).toContainText("Internal DPT — fixed");
  await panel
    .getByLabel("CAF input to move", { exact: true })
    .selectOption("8-1/0_10");
  await expect(
    panel
      .getByLabel("CAF destination universal input", { exact: true })
      .locator("option"),
  ).toHaveCount(3);
  await panel
    .getByLabel("CAF destination universal input", { exact: true })
    .selectOption("3");
  await panel
    .getByRole("button", { name: "Review CAF terminal edit", exact: true })
    .click();
  await expect(
    panel.getByRole("region", { name: "CAF terminal edit review" }),
  ).toContainText('"native_download": false');
  const pending = page.waitForEvent("download");
  await panel
    .getByRole("button", { name: "Download terminal-edited CAF", exact: true })
    .click();
  const downloaded = await pending;
  expect(downloaded.suggestedFilename()).toBe("authored-hardware.caf");
  const readback = JSON.parse(
    execFileSync(
      python,
      [
        "-c",
        "from pathlib import Path; import sys,json; from bms_tool.caf import CafArchive; from bms_tool.caf_hardware import CafHardwareBindings; from tests.test_caf_hardware import fixture; a=CafArchive(Path(sys.argv[1]).read_bytes()); original=fixture(); expected=original.xml.replace(b'>UI IN1<',b'>UI IN3<').replace(b'<unsignedByte>1</unsignedByte>',b'<unsignedByte>3</unsignedByte>'); print(json.dumps({'exact_xml':a.xml==expected,'slots':[p['slot'] for p in CafHardwareBindings(a).summary()['inputs']]}))",
        (await downloaded.path())!,
      ],
      { cwd: root },
    ).toString(),
  );
  expect(readback).toEqual({ exact_xml: true, slots: [3, 2, 4] });
  await expect(panel).toContainText("Downloaded a separate CAF");
  await expect(
    (await page.request.get("/api/session")).json(),
  ).resolves.toHaveProperty("field_network_open", false);
});

test("unknown controller hardware remains visibly unsupported", async ({
  page,
}) => {
  const panel = await openHardware(page, "unsupported.caf", true);
  await expect(panel).toContainText("Terminal editing unavailable");
  await expect(
    panel.getByRole("button", {
      name: "Review CAF terminal edit",
      exact: true,
    }),
  ).toHaveCount(0);
});

test("late terminal preview cannot replace another CAF archive", async ({
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
  await page.route("**/api/caf/*/hardware/preview", async (route) => {
    const response = await route.fetch();
    started();
    await held;
    await route.fulfill({ response });
  });
  const panel = await openHardware(page, "first.caf");
  await panel
    .getByLabel("CAF input to move", { exact: true })
    .selectOption("8-1/0_10");
  await panel
    .getByLabel("CAF destination universal input", { exact: true })
    .selectOption("3");
  await panel
    .getByRole("button", { name: "Review CAF terminal edit", exact: true })
    .click();
  await ready;
  page.once("dialog", (dialog) => dialog.accept());
  await pickCaf(
    page.getByRole("button", { name: "Open CAF", exact: true }),
    "second.caf",
    true,
  );
  await expect(page.getByLabel("Current CAF archive")).toHaveText("second.caf");
  await expect(panel).toBeHidden();
  await hardwareMapping(page);
  await expect(panel).toContainText("Terminal editing unavailable");
  release();
  await expect(
    panel.getByRole("region", { name: "CAF terminal edit review" }),
  ).toHaveCount(0);
  await expect(page.getByLabel("Current CAF archive")).toHaveText("second.caf");
});

test("terminal proposals invalidate earlier reviews and can cancel archive replacement", async ({
  page,
}) => {
  const panel = await openHardware(page, "keep-editing.caf");
  await panel
    .getByLabel("CAF input to move", { exact: true })
    .selectOption("8-1/0_10");
  const destination = panel.getByLabel("CAF destination universal input", {
    exact: true,
  });
  await destination.selectOption("3");
  await panel
    .getByRole("button", { name: "Review CAF terminal edit", exact: true })
    .click();
  await expect(
    panel.getByRole("region", { name: "CAF terminal edit review" }),
  ).toBeVisible();
  await destination.selectOption("1");
  await expect(
    panel.getByRole("region", { name: "CAF terminal edit review" }),
  ).toHaveCount(0);
  await destination.selectOption("3");
  page.once("dialog", (dialog) => dialog.dismiss());
  await pickCaf(
    page.getByRole("button", { name: "Open CAF", exact: true }),
    "discarded.caf",
    true,
  );
  await expect(page.getByLabel("Current CAF archive")).toHaveText(
    "keep-editing.caf",
  );
  await expect(destination).toBeVisible();
  await expect(destination).toHaveValue("3");
  await expect(panel).toContainText(
    "Current terminal proposal has not been exported.",
  );
});
