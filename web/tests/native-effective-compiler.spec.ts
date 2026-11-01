import { test, expect, type Page, type Locator } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { freePort, peer } from "./workflow-peer";
const root = fileURLToPath(new URL("../..", import.meta.url));
const first = "controller/signal-10",
  second = "controller/signal-11";
const state = process.env.BMS_TEST_COMPILER_STATE;
if (!state)
  throw new Error(
    "The Playwright runner must provide its isolated BMS_TEST_COMPILER_STATE.",
  );
function python(code: string, ...args: string[]) {
  return execFileSync(
    path.join(root, ".venv/bin/python"),
    ["-c", code, ...args],
    {
      cwd: root,
      env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
      encoding: "utf8",
    },
  );
}
function seed() {
  return JSON.parse(
    python(
      `
import json,sys
from bms_tool.storage import Store
from bms_tool.application_store import ApplicationStore
from tests.test_native_signal_compiler import retained
s=ApplicationStore(Store(sys.argv[1]))
a=retained(s);b=retained(s,target={'address':'127.0.0.1:47829','router':None,'dnet':None})
print(json.dumps({'a':a['id'],'b':b['id']}))
`,
      state,
    ),
  );
}
async function open(page: Page, id: string) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "New application", exact: true })
    .click();
  await page
    .getByRole("navigation", { name: "Current task tools" })
    .getByRole("button", { name: "Native backup defaults", exact: true })
    .click();
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
  await expect(
    panel.getByLabel("Native compiler snapshot source", { exact: true }),
  ).toContainText("9 saved application parameters");
  await panel
    .getByLabel("Native Real default", { exact: true })
    .selectOption(first);
  return panel;
}
async function compile(panel: Locator, value = "0.1") {
  await panel
    .getByLabel("Proposed native Real default", { exact: true })
    .fill(value);
  await panel
    .getByRole("button", { name: "Review native compilation", exact: true })
    .click();
  return panel.getByRole("region", {
    name: "Reviewed native compilation",
    exact: true,
  });
}
async function download(page: Page, button: Locator) {
  const pending = page.waitForEvent("download");
  await button.click();
  return (await (await pending).path())!;
}

test("native compiler controls remain readable at narrow widths and support keyboard review", async ({
  page,
}, info) => {
  const ids = seed();
  await page.setViewportSize({ width: 820, height: 1100 });
  const panel = await open(page, ids.a);
  for (const name of ["Retained native backup", "Native Real default"]) {
    const select = panel.getByLabel(name, { exact: true });
    const box = await select.boundingBox();
    expect(box?.height).toBeGreaterThanOrEqual(36);
    expect(
      await select.evaluate((element) => getComputedStyle(element).fontSize),
    ).toBe("14px");
  }
  const text = panel.getByLabel("Proposed native Real default", {
    exact: true,
  });
  await text.fill("-0");
  await text.press("Enter");
  const review = panel.getByRole("region", {
    name: "Reviewed native compilation",
    exact: true,
  });
  await expect(review).toContainText("80000000");
  await expect(text).toHaveValue("-0");
  expect(
    await panel.evaluate(
      (element) => element.scrollWidth <= element.clientWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: info.outputPath("native-compiler-narrow.png"),
  });
});

test("offline native compiler preserves saved settings, exact bytes and source-specific drafts through navigation", async ({
  page,
  request,
}, info) => {
  const ids = seed(),
    panel = await open(page, ids.a);
  await expect(
    panel.getByRole("table", { name: "Native default source values" }),
  ).toContainText("23.5");
  await expect(
    panel.getByRole("table", { name: "Native default source values" }),
  ).toContainText("42");
  const input = panel.getByLabel("Proposed native Real default", {
    exact: true,
  });
  await input.fill("1e-");
  await panel
    .getByLabel("Native Real default", { exact: true })
    .selectOption(second);
  await expect(input).toHaveValue("7");
  await input.fill("-0");
  await panel
    .getByLabel("Native Real default", { exact: true })
    .selectOption(first);
  await expect(input).toHaveValue("1e-");
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("button", { name: "Library", exact: true })
    .click();
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("button", { name: "Workspace", exact: true })
    .click();
  await page
    .getByRole("navigation", { name: "Current task tools" })
    .getByRole("button", { name: "Native backup defaults", exact: true })
    .click();
  await expect(input).toHaveValue("1e-");
  const review = await compile(panel);
  await expect(review).toContainText("3dcccccd");
  const file = await download(
    page,
    review.getByRole("button", {
      name: "Save compiled native copy",
      exact: true,
    }),
  );
  expect(
    python(
      `
import sys
from bms_tool.moi_identity import MoiIdentity
a=MoiIdentity(open(sys.argv[1],'rb').read())
assert a.reader.scalar(a.root,900)==3.5
assert a.reader.scalar(a.root,904)=='saved'
assert a.reader.scalar(a.reader.records['controller/signal-11'],3113)==7
p=a.reader.records['controller/signal-10']['properties'][3113]
assert a.data[p['value_start_offset']+1:p['value_start_offset']+5].hex()=='3dcccccd'
print('preserved')
`,
      file,
    ).trim(),
  ).toBe("preserved");
  const exactReview = JSON.parse(
    readFileSync(
      await download(
        page,
        review.getByRole("button", {
          name: "Export exact compilation review",
          exact: true,
        }),
      ),
      "utf8",
    ),
  );
  expect(exactReview.compilation.controller_write).toBe(false);
  expect(exactReview.request.capture_id).toBe(ids.a);
  await panel
    .getByLabel("Find native default", { exact: true })
    .fill("signal-11");
  await expect(
    panel.getByLabel("Native Real default", { exact: true }),
  ).toHaveValue(first);
  await expect(input).toHaveValue("0.1");
  await page.screenshot({
    path: info.outputPath("effective-native-compiler.png"),
  });
  expect(
    (await (await request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
});

test("same-source reopening restores drafts and another snapshot does not inherit them", async ({
  page,
}) => {
  const ids = seed(),
    panel = await open(page, ids.a);
  const input = panel.getByLabel("Proposed native Real default", {
    exact: true,
  });
  await input.fill("29.25");
  await panel
    .getByRole("button", { name: "Open retained backup", exact: true })
    .click();
  await panel
    .getByLabel("Native Real default", { exact: true })
    .selectOption(first);
  await expect(input).toHaveValue("29.25");
  await panel
    .getByLabel("Retained native backup", { exact: true })
    .selectOption(ids.b);
  await expect(
    panel.getByLabel("Native compiler snapshot source", { exact: true }),
  ).toHaveCount(0);
  await panel
    .getByRole("button", { name: "Open retained backup", exact: true })
    .click();
  await panel
    .getByLabel("Native Real default", { exact: true })
    .selectOption(first);
  await expect(input).toHaveValue("42");
  await panel
    .getByLabel("Retained native backup", { exact: true })
    .selectOption(ids.a);
  await panel
    .getByRole("button", { name: "Open retained backup", exact: true })
    .click();
  await panel
    .getByLabel("Native Real default", { exact: true })
    .selectOption(first);
  await expect(input).toHaveValue("29.25");
  await panel
    .getByRole("button", { name: "Discard selected field draft", exact: true })
    .click();
  await expect(input).toHaveValue("42");
});

test("late compilation and export cannot return after proposal or navigation changes", async ({
  page,
}) => {
  const panel = await open(page, seed().a);
  let release!: () => void, enter!: () => void;
  let gate = new Promise<void>((resolve) => {
      release = resolve;
    }),
    entered = new Promise<void>((resolve) => {
      enter = resolve;
    });
  await page.route(
    "**/native-application/signal-default/preview",
    async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      enter();
      await gate;
      await route.fulfill({ response });
    },
  );
  try {
    await panel
      .getByLabel("Proposed native Real default", { exact: true })
      .fill("31");
    await panel
      .getByRole("button", { name: "Review native compilation", exact: true })
      .click();
    await entered;
    await panel
      .getByLabel("Proposed native Real default", { exact: true })
      .fill("32");
    release();
    await expect(
      panel.getByRole("button", {
        name: "Review native compilation",
        exact: true,
      }),
    ).toBeEnabled();
    await expect(
      panel.getByRole("region", {
        name: "Reviewed native compilation",
        exact: true,
      }),
    ).toHaveCount(0);
    await page.unroute("**/native-application/signal-default/preview");
    const review = await compile(panel);
    await expect(review).toBeVisible();
    gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    entered = new Promise<void>((resolve) => {
      enter = resolve;
    });
    await page.route(
      "**/native-application/signal-default/export",
      async (route) => {
        const response = await route.fetch({ maxRetries: 0 });
        enter();
        await gate;
        await route.fulfill({ response });
      },
    );
    let downloads = 0;
    page.on("download", () => downloads++);
    await review
      .getByRole("button", { name: "Save compiled native copy", exact: true })
      .click();
    await entered;
    await page
      .getByRole("navigation", { name: "Main navigation" })
      .getByRole("button", { name: "Library", exact: true })
      .click();
    release();
    await page
      .getByRole("navigation", { name: "Main navigation" })
      .getByRole("button", { name: "Workspace", exact: true })
      .click();
    await page
      .getByRole("navigation", { name: "Current task tools" })
      .getByRole("button", { name: "Native backup defaults", exact: true })
      .click();
    await expect(
      panel.getByRole("region", {
        name: "Reviewed native compilation",
        exact: true,
      }),
    ).toHaveCount(0);
    expect(downloads).toBe(0);
    await expect(
      panel.getByLabel("Proposed native Real default", { exact: true }),
    ).toHaveValue("0.1");
  } finally {
    release();
  }
});

for (const corrupted of ["review", "artifact"])
  test(`altered ${corrupted} cannot authorize a native compiled download`, async ({
    page,
  }) => {
    const panel = await open(page, seed().a);
    if (corrupted === "review")
      await page.route(
        "**/native-application/signal-default/preview",
        async (route) => {
          const response = await route.fetch({ maxRetries: 0 }),
            body = await response.json();
          body.compilation.selected_edit.before_bits = "00000000";
          await route.fulfill({ response, json: body });
        },
      );
    const review = await compile(panel);
    if (corrupted === "review") {
      await expect(panel.getByRole("alert")).toContainText("does not match");
      await expect(review).toHaveCount(0);
    } else {
      await expect(review).toBeVisible();
      await page.route(
        "**/native-application/signal-default/export",
        async (route) => {
          const response = await route.fetch({ maxRetries: 0 });
          await route.fulfill({
            response,
            headers: {
              ...response.headers(),
              "x-studio-artifact-sha256": "0".repeat(64),
            },
          });
        },
      );
      let downloads = 0;
      page.on("download", () => downloads++);
      await review
        .getByRole("button", { name: "Save compiled native copy", exact: true })
        .click();
      await expect(panel.getByRole("alert")).toContainText("do not match");
      expect(downloads).toBe(0);
    }
  });

test("CAF draft and explicit file provenance survive the independent native compiler", async ({
  page,
}) => {
  const ids = seed();
  await page.goto("/");
  await page
    .locator("input[type=file][accept='.caf']")
    .first()
    .setInputFiles({
      name: "native-companion.caf",
      mimeType: "application/octet-stream",
      buffer: Buffer.from(
        python(
          "from tests.test_caf_graph import make_graph; import base64; print(base64.b64encode(make_graph()).decode())",
        ).trim(),
        "base64",
      ),
    });
  await page
    .locator(".caf-layout tbody tr")
    .filter({ has: page.getByText("Block 10", { exact: true }) })
    .click();
  await page.getByLabel("CAF property 3113", { exact: true }).fill("27.25");
  await page
    .getByRole("navigation", { name: "Current task tools" })
    .getByRole("button", { name: "Native backup defaults", exact: true })
    .click();
  const panel = page.getByRole("region", {
    name: "Native backup default compiler",
    exact: true,
  });
  await panel
    .getByLabel("Retained native backup", { exact: true })
    .selectOption(ids.a);
  await panel
    .getByRole("button", { name: "Open retained backup", exact: true })
    .click();
  await panel
    .getByLabel("Native Real default", { exact: true })
    .selectOption(first);
  const review = await compile(panel);
  await expect(review).toBeVisible();
  await expect(page.getByLabel("Working context")).toContainText(
    "native-companion.caf",
  );
  await page
    .getByRole("navigation", { name: "Current task tools" })
    .getByRole("button", { name: "CAF file", exact: true })
    .click();
  await expect(
    page.getByLabel("CAF property 3113", { exact: true }),
  ).toHaveValue("27.25");
  await expect(page.getByLabel("Working context")).toContainText(
    "native-companion.caf",
  );
});

test("connected-controller entry retains native drafts and retires review when the routed station changes", async ({
  page,
  request,
}) => {
  const router = await peer();
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  const ids = seed();
  await request.post("/api/bacnet/disconnect", { headers, data: {} });
  async function selectStation(mac: number) {
    await page
      .getByRole("button", { name: "Known controller address", exact: true })
      .click();
    await page
      .getByLabel("Known controller address", { exact: true })
      .fill(`3001:${mac}`);
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
    ).toContainText(`Authored 3001 MAC ${mac}`);
    await page
      .getByRole("navigation", { name: "Workspace tasks" })
      .getByRole("button", { name: "Program", exact: true })
      .click();
    await page
      .getByRole("navigation", { name: "Current task tools" })
      .getByRole("button", { name: "Native backup defaults", exact: true })
      .click();
  }
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
    await selectStation(7);
    const panel = page.getByRole("region", {
      name: "Native backup default compiler",
      exact: true,
    });
    await panel
      .getByLabel("Retained native backup", { exact: true })
      .selectOption(ids.a);
    await panel
      .getByRole("button", { name: "Open retained backup", exact: true })
      .click();
    await panel
      .getByLabel("Native Real default", { exact: true })
      .selectOption(first);
    await expect(await compile(panel, "29.5")).toBeVisible();
    await expect(
      panel.getByLabel("Native compiler snapshot source", { exact: true }),
    ).toContainText("127.0.0.1:47819");
    await page
      .getByLabel("Working context")
      .getByRole("button", { name: "Change controller", exact: true })
      .click();
    await selectStation(8);
    await expect(
      panel.getByRole("region", {
        name: "Reviewed native compilation",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      panel.getByLabel("Proposed native Real default", { exact: true }),
    ).toHaveValue("29.5");
    await expect(page.getByLabel("Working context")).toContainText(
      "Authored 3001 MAC 8",
    );
    expect(router.writes).toEqual([]);
    expect(router.errors).toEqual([]);
  } finally {
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    router.close();
  }
});
