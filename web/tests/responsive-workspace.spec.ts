import {
  test,
  expect,
  type Page,
  type APIRequestContext,
} from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { freePort, peer } from "./workflow-peer";

test.use({ viewport: { width: 600, height: 1000 }, hasTouch: true });
const root = path.resolve("..");
const menu = (page: Page) =>
  page.getByRole("dialog", { name: "Navigation", exact: true });
const properties = (page: Page) =>
  page.getByRole("dialog", { name: "Block properties", exact: true });
const cafProperties = (page: Page) =>
  page.getByRole("dialog", { name: "CAF properties", exact: true });
async function reset(request: APIRequestContext) {
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  expect(
    (await request.post("/api/bacnet/disconnect", { headers, data: {} })).ok(),
  ).toBe(true);
}
async function editor(page: Page) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "New application", exact: true })
    .click();
  await expect(page.locator(".react-flow__node")).toHaveCount(0);
}
async function addConstant(page: Page) {
  await page
    .getByRole("button", { name: "Open block library", exact: true })
    .click();
  const library = page.getByRole("dialog", {
    name: "Block library",
    exact: true,
  });
  await library.getByLabel("Search blocks", { exact: true }).fill("Constant");
  await library
    .locator(".palette-block")
    .filter({ hasText: "Constant" })
    .click();
  await expect(properties(page)).toBeVisible();
  await expect(page.locator("dialog:modal")).toHaveCount(1);
  await expect(
    properties(page).getByLabel("Label", { exact: true }),
  ).toHaveValue("Constant");
}
function valueInput(page: Page) {
  return properties(page)
    .locator(".inspector label")
    .filter({ hasText: /^\s*value/ })
    .locator("input");
}
function caf(title = "Authored example") {
  return execFileSync(
    path.join(root, ".venv/bin/python"),
    [
      "-c",
      "from tests.test_caf_graph import make_graph,pack; from bms_tool.caf import CafArchive; import sys; sys.stdout.buffer.write(pack(CafArchive(make_graph()).xml.replace(b'Authored example',sys.argv[1].encode())))",
      title,
    ],
    { cwd: root },
  );
}
async function openCaf(
  page: Page,
  name = "drawer.caf",
  title = "Authored example",
) {
  await page
    .getByLabel("Open local CAF application", { exact: true })
    .setInputFiles({
      name,
      mimeType: "application/octet-stream",
      buffer: caf(title),
    });
  await expect(page.getByLabel("Working context")).toContainText(name);
}
const fieldRequests = (page: Page) => {
  const calls: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().includes("/api/bacnet/"))
      calls.push(request.url());
  });
  return calls;
};

test("navigation drawer supports touch, native focus containment, Escape and opener restoration without field requests", async ({
  page,
}) => {
  const calls = fieldRequests(page);
  await page.goto("/");
  const opener = page.getByRole("button", {
    name: "Open navigation",
    exact: true,
  });
  await opener.tap();
  await expect(menu(page)).toBeVisible();
  await expect(opener).toHaveAttribute("aria-expanded", "true");
  await expect(
    menu(page).getByRole("navigation", {
      name: "Main navigation",
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    menu(page).getByRole("button", { name: "Close navigation", exact: true }),
  ).toBeFocused();
  for (let n = 0; n < 10; n++) {
    await page.keyboard.press("Tab");
    expect(
      await menu(page).evaluate((element) =>
        element.contains(document.activeElement),
      ),
    ).toBe(true);
  }
  await page.keyboard.press("Shift+Tab");
  expect(
    await menu(page).evaluate((element) =>
      element.contains(document.activeElement),
    ),
  ).toBe(true);
  await page.keyboard.press("Escape");
  await expect(menu(page)).toHaveCount(0);
  await expect(opener).toHaveAttribute("aria-expanded", "false");
  await expect(opener).toBeFocused();
  expect(calls).toEqual([]);
});

test("navigation closes on an explicit destination and backdrop dismissal; labels stay visible", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Open navigation", exact: true })
    .click();
  await menu(page).getByRole("button", { name: "Help", exact: true }).click();
  await expect(menu(page)).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "Reference desk", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Open navigation", exact: true })
    .click();
  await expect(
    menu(page).getByRole("button", { name: "Workspace", exact: true }),
  ).toContainText("Workspace");
  await page.mouse.click(590, 500);
  await expect(menu(page)).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Open navigation", exact: true }),
  ).toBeFocused();
});

test("block library hands focus to one properties drawer and retains valid and unfinished numeric edits", async ({
  page,
}) => {
  const calls = fieldRequests(page);
  await editor(page);
  await addConstant(page);
  await properties(page)
    .getByLabel("Label", { exact: true })
    .fill("Retained constant");
  await valueInput(page).fill("42.5");
  await properties(page)
    .getByRole("button", { name: "Close block properties", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Open block properties", exact: true }),
  ).toBeFocused();
  await page
    .getByRole("button", { name: "Open block properties", exact: true })
    .click();
  await expect(
    properties(page).getByLabel("Label", { exact: true }),
  ).toHaveValue("Retained constant");
  await expect(valueInput(page)).toHaveValue("42.5");
  await valueInput(page).fill("-");
  await expect(properties(page)).toContainText("Edit not applied");
  await page.keyboard.press("Escape");
  await page.locator(".react-flow__node").click();
  await expect(valueInput(page)).toHaveValue("-");
  await expect(properties(page)).toContainText("Edit not applied");
  expect(calls).toEqual([]);
});

test("native drawer blocks hidden graph shortcuts and still permits editing its input", async ({
  page,
}) => {
  await editor(page);
  await addConstant(page);
  await properties(page)
    .getByLabel("Label", { exact: true })
    .fill("Keep this block");
  await page.keyboard.press("Escape");
  await page
    .getByRole("button", { name: "Open navigation", exact: true })
    .click();
  await menu(page)
    .getByRole("button", { name: "Close navigation", exact: true })
    .focus();
  await page.keyboard.press("Delete");
  await page.keyboard.press("Control+z");
  await page.keyboard.press("Control+d");
  await expect(page.locator(".react-flow__node")).toHaveCount(1);
  await page.keyboard.press("Escape");
  await page
    .getByRole("button", { name: "Open block properties", exact: true })
    .click();
  await expect(
    properties(page).getByLabel("Label", { exact: true }),
  ).toHaveValue("Keep this block");
});

test("resizing keeps the same mounted inspector, unfinished draft and a valid focus destination", async ({
  page,
}) => {
  await editor(page);
  await addConstant(page);
  await valueInput(page).fill("-");
  await valueInput(page).evaluate((element) =>
    element.setAttribute("data-preserved-test-input", "same-node"),
  );
  await valueInput(page).focus();
  await page.setViewportSize({ width: 1440, height: 1000 });
  await expect(page.locator("dialog:modal")).toHaveCount(0);
  const inline = page.locator('input[data-preserved-test-input="same-node"]');
  await expect(inline).toBeVisible();
  await expect(inline).toHaveValue("-");
  await expect(inline).toBeFocused();
  await page.setViewportSize({ width: 600, height: 1000 });
  await expect(page.locator("dialog:modal")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Open block properties", exact: true }),
  ).toBeFocused();
  await page
    .getByRole("button", { name: "Open block properties", exact: true })
    .click();
  await expect(valueInput(page)).toHaveValue("-");
  await expect(
    properties(page).locator('input[data-preserved-test-input="same-node"]'),
  ).toHaveCount(1);
});

test("CAF object selection opens its properties by keyboard and retains the local draft after drawer close", async ({
  page,
}) => {
  const calls = fieldRequests(page);
  await page.goto("/");
  await openCaf(page);
  const object = page.getByRole("button", {
    name: "Inspect CAF object Block 10",
    exact: true,
  });
  await object.focus();
  await object.press("Enter");
  await expect(cafProperties(page)).toBeVisible();
  await cafProperties(page)
    .getByLabel("CAF property 3113", { exact: true })
    .fill("42.5");
  await page.keyboard.press("Escape");
  await expect(cafProperties(page)).toHaveCount(0);
  await expect(page.getByLabel("Working context")).toContainText(
    "Local changes",
  );
  await object.click();
  await expect(
    cafProperties(page).getByLabel("CAF property 3113", { exact: true }),
  ).toHaveValue("42.5");
  await page.keyboard.press("Escape");
  await page
    .getByRole("navigation", { name: "Workspace tasks" })
    .getByRole("combobox", { name: "Workspace task", exact: true })
    .selectOption("changes");
  await page
    .getByRole("combobox", { name: "Current task tools", exact: true })
    .selectOption("caf");
  await expect(
    page.getByRole("region", { name: "Local CAF change review", exact: true }),
  ).toContainText("42.5");
  expect(calls).toEqual([]);
});

test("a replacement CAF retires the old modal and delayed property response", async ({
  page,
}) => {
  page.on("dialog", (dialog) => dialog.accept());
  let release!: () => void, arrived!: () => void;
  const held = new Promise<void>((resolve) => (release = resolve));
  const ready = new Promise<void>((resolve) => (arrived = resolve));
  let first = true;
  await page.route("**/api/caf/*/properties?*", async (route) => {
    const response = await route.fetch();
    if (first) {
      first = false;
      arrived();
      await held;
    }
    await route.fulfill({ response });
  });
  try {
    await page.goto("/");
    await openCaf(page);
    await page
      .getByRole("button", { name: "Inspect CAF object Block 10", exact: true })
      .click();
    await ready;
    await expect(cafProperties(page)).toBeVisible();
    await openCaf(page, "replacement.caf", "Distinct replacement archive");
    await expect(cafProperties(page)).toHaveCount(0);
    release();
    await page.waitForLoadState("networkidle");
    await expect(cafProperties(page)).toHaveCount(0);
    await expect(page.getByLabel("Working context")).toContainText(
      "replacement.caf",
    );
    await page
      .getByRole("button", { name: "Open CAF properties", exact: true })
      .click();
    await expect(cafProperties(page)).toContainText("Select an object");
    await expect(
      cafProperties(page).getByLabel("CAF property 3113", { exact: true }),
    ).toHaveCount(0);
  } finally {
    release?.();
  }
});

test("opening and closing the controller explorer preserves an exact routed selection without scanning", async ({
  page,
  request,
}) => {
  await reset(request);
  const router = await peer(3001);
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
      .fill("3001:8");
    await page
      .getByLabel("Known Device object", { exact: true })
      .fill("device,5136");
    await page
      .getByLabel("Known router", { exact: true })
      .fill(router.endpoint);
    await page.getByLabel("Known network", { exact: true }).fill("3001");
    await page
      .getByRole("region", { name: "Known controller connection" })
      .getByRole("button", { name: "Open controller", exact: true })
      .click();
    await expect(
      page.getByRole("region", { name: "Controller overview" }),
    ).toContainText("Authored 3001 MAC 8");
    const calls = fieldRequests(page);
    await page
      .getByRole("button", { name: "Open controller explorer", exact: true })
      .click();
    const explorer = page.getByRole("dialog", {
      name: "Controller explorer",
      exact: true,
    });
    await expect(explorer).toContainText("3001:8");
    await expect(explorer).toContainText("device,5136");
    await page.keyboard.press("Escape");
    await expect(page.getByLabel("Working context")).toContainText("3001:8");
    await expect(page.getByLabel("Working context")).toContainText(
      router.endpoint,
    );
    expect(calls).toEqual([]);
    expect(router.writes).toEqual([]);
  } finally {
    await reset(request);
    router.close();
  }
});

test("desktop retains inline navigation, palette and properties with usable canvas width", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await editor(page);
  await expect(
    page.getByRole("navigation", { name: "Main navigation", exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("Search blocks", { exact: true })).toBeVisible();
  await expect(page.locator(".inspector")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Open navigation", exact: true }),
  ).toBeHidden();
  await expect(page.locator("dialog:modal")).toHaveCount(0);
  expect(
    await page
      .locator(".canvas")
      .evaluate((element) => element.getBoundingClientRect().width),
  ).toBeGreaterThan(500);
  await page.screenshot({
    path: test.info().outputPath("responsive-desktop.png"),
    fullPage: true,
  });
});

test("phone workspace exposes named drawers and keeps table scrolling inside its own container", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 900 });
  await page.goto("/");
  await openCaf(page);
  await expect(
    page.getByRole("button", { name: "Open navigation", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Open CAF properties", exact: true }),
  ).toBeVisible();
  await expect(
    page.locator('dialog[data-responsive-panel="caf-properties"]'),
  ).toBeHidden();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: test.info().outputPath("responsive-phone-caf.png"),
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Inspect CAF object Block 10", exact: true })
    .tap();
  await expect(cafProperties(page)).toBeVisible();
  const input = cafProperties(page).getByLabel("CAF property 3113", {
    exact: true,
  });
  await expect(input).toBeVisible();
  expect(
    await input.evaluate((element) =>
      parseFloat(getComputedStyle(element).fontSize),
    ),
  ).toBeGreaterThanOrEqual(14);
  await page.screenshot({
    path: test.info().outputPath("responsive-phone-properties.png"),
    fullPage: true,
  });
  const scroller = cafProperties(page).locator(".responsive-panel-content");
  await scroller.evaluate((element) => {
    element.scrollTop = element.scrollHeight;
  });
  await expect(
    cafProperties(page)
      .getByText("Inspect preserved XML", { exact: true })
      .last(),
  ).toBeInViewport();
});

test("CAF property read failures stay visible inside the active drawer", async ({
  page,
}) => {
  await page.route("**/api/caf/*/properties?*", (route) =>
    route.fulfill({
      status: 422,
      json: { detail: "Authored property read failure" },
    }),
  );
  await page.goto("/");
  await openCaf(page);
  await page
    .getByRole("button", { name: "Inspect CAF object Block 10", exact: true })
    .click();
  await expect(cafProperties(page).getByRole("alert")).toContainText(
    "Authored property read failure",
  );
  await expect(
    cafProperties(page).getByLabel("CAF property 3113", { exact: true }),
  ).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("button", { name: "Open CAF properties", exact: true }),
  ).toBeFocused();
});

test("desktop graph still supports drag, wiring, parameter edits and undo", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await editor(page);
  const constant = page
    .locator(".palette-block")
    .filter({ hasText: "Constant" });
  await constant.dragTo(page.locator(".canvas"), {
    targetPosition: { x: 220, y: 180 },
  });
  await expect(page.locator(".react-flow__node")).toHaveCount(1);
  await page.locator(".palette-block").filter({ hasText: "Output" }).click();
  await expect(page.locator(".react-flow__node")).toHaveCount(2);
  await page.getByTitle("Fit view", { exact: true }).click();
  const source = page
    .locator(".react-flow__node")
    .filter({ hasText: "Constant" });
  const target = page
    .locator(".react-flow__node")
    .filter({ hasText: "Output" });
  await source.click();
  await page
    .locator(".inspector label")
    .filter({ hasText: /^value$/ })
    .locator("input")
    .fill("37.5");
  const from = await source.locator(".react-flow__handle-right").boundingBox();
  const to = await target.locator(".react-flow__handle-left").boundingBox();
  await page.mouse.move(from!.x + from!.width / 2, from!.y + from!.height / 2);
  await page.mouse.down();
  await page.mouse.move(to!.x + to!.width / 2, to!.y + to!.height / 2, {
    steps: 20,
  });
  await page.mouse.up();
  await expect(page.locator(".react-flow__edge")).toHaveCount(1);
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(page.locator(".react-flow__edge")).toHaveCount(0);
  await expect(
    page
      .locator(".inspector label")
      .filter({ hasText: /^value$/ })
      .locator("input"),
  ).toHaveValue("37.5");
});

test("dragging a block in the compact wiresheet does not open an inspector during the gesture", async ({
  page,
}) => {
  await editor(page);
  await addConstant(page);
  await page.keyboard.press("Escape");
  const node = page.locator(".react-flow__node");
  await node.locator(".node-header").scrollIntoViewIfNeeded();
  const before = await node.getAttribute("style");
  const box = await node.locator(".node-header").boundingBox();
  await page.mouse.move(box!.x + 24, box!.y + 12);
  await page.mouse.down();
  try {
    await page.mouse.move(box!.x + 72, box!.y + 60, { steps: 10 });
    await expect(page.locator("dialog:modal")).toHaveCount(0);
  } finally {
    await page.mouse.up();
  }
  await expect(page.locator("dialog:modal")).toHaveCount(0);
  await expect.poll(() => node.getAttribute("style")).not.toBe(before);
  await node.click();
  await expect(properties(page)).toBeVisible();
});
