import { test, expect, type Page } from "./nativeScheduleWriteFixture";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import path from "node:path";
import {
  chooseWorkspaceTask,
  chooseWorkspaceTool,
  chooseWorkspaceSurface,
} from "./workspace-navigation";
import { nativeDefaultPeer } from "./native-default-peer";
import { freePort } from "./workflow-peer";

const root = path.resolve("..");
function python(code: string, ...args: string[]) {
  return execFileSync(
    path.join(root, ".venv/bin/python"),
    ["-c", code, ...args],
    {
      cwd: root,
      env: {
        ...process.env,
        PYTHONPATH: [
          process.env.BMS_TEST_INSTALLED_TARGET || path.join(root, "backend"),
          root,
        ].join(path.delimiter),
      },
    },
  );
}
function authored(cid = "528", set = true) {
  return python(
    "from tests.test_caf_enum_defaults import enum_caf;import sys;sys.stdout.buffer.write(enum_caf(cid=sys.argv[1],attributes=\" set='state&amp;set'\" if sys.argv[2]=='set' else '')[0])",
    cid,
    set ? "set" : "none",
  );
}
async function objects(page: Page) {
  await chooseWorkspaceTask(page, "Program");
  const tools = page.getByRole("navigation", {
    name: "Current task tools",
    exact: true,
  });
  const local =
    (await tools
      .getByRole("button", { name: "Local CAF file", exact: true })
      .count()) ||
    (await tools
      .getByRole("option", { name: "Local CAF file", exact: true })
      .count());
  await chooseWorkspaceTool(page, local ? "Local CAF file" : "CAF file");
  const navigation = page.getByRole("navigation", {
    name: "CAF application tasks",
    exact: true,
  });
  const choice = navigation.getByRole("combobox");
  if (await choice.isVisible())
    await choice.selectOption({ label: "Objects & parameters" });
  else
    await navigation
      .getByRole("button", { name: "Objects & parameters", exact: true })
      .click();
}
async function select(page: Page, name = "ENUM_CMD") {
  await objects(page);
  await page
    .locator(".caf-layout tbody tr")
    .filter({ has: page.getByText(name, { exact: true }) })
    .click();
}
async function closeProperties(page: Page) {
  const close = page.getByRole("button", {
    name: "Close CAF properties",
    exact: true,
  });
  if (await close.isVisible()) await close.click();
}
async function changes(page: Page) {
  await closeProperties(page);
  await chooseWorkspaceTask(page, "Changes");
  await chooseWorkspaceTool(page, "CAF changes");
  await expect(
    page.getByRole("region", { name: "Local CAF change review", exact: true }),
  ).toBeVisible();
  return page.locator(".export-strip:visible");
}
async function open(page: Page, cid = "528", set = true) {
  await page.goto("/");
  const choosing = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: /^Open a CAF file/ }).click();
  await (
    await choosing
  ).setFiles({
    name: "enum.caf",
    mimeType: "application/octet-stream",
    buffer: authored(cid, set),
  });
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("enum.caf");
  await select(page);
}
const field = (page: Page) =>
  page.getByLabel("CAF property 3113", { exact: true });
const digest = (body: Buffer) =>
  createHash("sha256").update(body).digest("hex");

test("CAF entry exports Enum and ordinary Unicode edits together with exact source/request/artifact hashes", async ({
  page,
  request,
}) => {
  const source = authored();
  await open(page);
  await field(page).fill("256");
  await select(page, "FLOAT_CMD");
  await page.getByLabel("CAF property 28", { exact: true }).fill("é🙂");
  const strip = await changes(page);
  await expect(
    page.getByRole("region", { name: "Local CAF change review", exact: true }),
  ).toContainText("Enum edits copy numeric codes");
  await expect(strip.locator("button.primary")).toHaveCount(1);
  const responsePending = page.waitForResponse((r) =>
    /\/api\/caf\/[^/]+\/export$/.test(r.url()),
  );
  const pending = page.waitForEvent("download");
  await strip
    .getByRole("button", { name: "Save CAF copy", exact: true })
    .click();
  const download = await pending,
    response = await responsePending,
    file = (await download.path())!;
  expect(response.headers()["x-caf-source-sha256"]).toBe(digest(source));
  expect(response.headers()["x-caf-output-sha256"]).toBe(
    digest(readFileSync(file)),
  );
  expect(response.headers()["x-caf-request-sha256"]).toBe(
    "76ecb3156e26dae9a3151103abf8f691c093c110bf7cc199ce9e1792d438a014",
  );
  const proof = JSON.parse(
    python(
      `
import sys,json
from pathlib import Path
from tests.test_caf_enum_defaults import enum_caf
from bms_tool.caf import CafArchive
source,before,after=enum_caf();actual=CafArchive(Path(sys.argv[1]).read_bytes())
assert actual.xml==before+b'256'+after.replace(b'>blue<','>é🙂<'.encode())
print(json.dumps({'exact_other_xml':True,'original_code':CafArchive(source).properties('controller/enum')[1]['scalar']['text']}))
`,
      file,
    ).toString(),
  );
  expect(proof).toEqual({ exact_other_xml: true, original_code: "1" });
  await select(page);
  await expect(field(page)).toHaveValue("256");
  expect(
    (await (await request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
});

test("phone Output Enum without a recorded set has readable code controls and the existing CAF review flow", async ({
  page,
}, info) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page, "529", false);
  await expect(page.getByText(/Set reference:.*not recorded/)).toBeVisible();
  await field(page).fill("0");
  await field(page).focus();
  await expect(field(page)).toBeFocused();
  expect(
    await field(page).evaluate((e) =>
      Number.parseFloat(getComputedStyle(e).fontSize),
    ),
  ).toBeGreaterThanOrEqual(14);
  await page.screenshot({
    path: info.outputPath("caf-enum-phone-properties.png"),
  });
  const strip = await changes(page);
  const pending = page.waitForEvent("download");
  await strip
    .getByRole("button", { name: "Save CAF copy", exact: true })
    .click();
  const file = (await (await pending).path())!;
  expect(
    python(
      "from pathlib import Path;from bms_tool.caf import CafArchive;import sys;print(next(p for p in CafArchive(Path(sys.argv[1]).read_bytes()).properties('controller/enum') if p['id']=='3113')['scalar']['text'])",
      file,
    )
      .toString()
      .trim(),
  ).toBe("0");
});

test("invalid raw Enum text survives failed export, object selection and workspace navigation", async ({
  page,
}) => {
  await open(page);
  await field(page).fill("1e-");
  const strip = await changes(page);
  await strip
    .getByRole("button", { name: "Save CAF copy", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText(
    "Enum codes require a decimal integer",
  );
  await select(page, "FLOAT_CMD");
  await select(page);
  await expect(field(page)).toHaveValue("1e-");
  await chooseWorkspaceSurface(page, "Library");
  await chooseWorkspaceSurface(page, "Workspace");
  await select(page);
  await expect(field(page)).toHaveValue("1e-");
  await changes(page);
  await expect(
    page.getByText("Current scalar edits have not been exported.", {
      exact: true,
    }),
  ).toBeVisible();
});

for (const altered of ["source", "class", "set", "authority"]) {
  test(`altered Enum property ${altered} evidence remains readable without enabling editing`, async ({
    page,
  }) => {
    await page.route("**/api/caf/*/properties?*", async (route) => {
      const response = await route.fetch({ maxRetries: 0 }),
        data = await response.json();
      for (const p of data)
        if (p.enum_code_copy) {
          if (altered === "source")
            p.enum_code_copy.source_sha256 = "0".repeat(64);
          if (altered === "class") p.enum_code_copy.class_id = "530";
          if (altered === "set") p.enum_code_copy.set_reference = "another set";
          if (altered === "authority") p.enum_code_copy.controller_write = true;
        }
      await route.fulfill({ response, json: data });
    });
    await open(page);
    await expect(page.getByRole("alert")).toContainText(
      "Enum edit evidence differs from this file or block",
    );
    await expect(field(page)).toHaveCount(0);
    await expect(
      page.locator(".property-value").filter({ hasText: /^1$/ }),
    ).toBeVisible();
  });
}

for (const altered of ["body", "source", "request", "output"]) {
  test(`altered CAF copy ${altered} is refused and the latest draft stays unsaved`, async ({
    page,
  }) => {
    await open(page);
    await field(page).fill("256");
    let downloads = 0;
    page.on("download", () => downloads++);
    await page.route("**/api/caf/*/export", async (route) => {
      const response = await route.fetch({ maxRetries: 0 }),
        headers = response.headers();
      if (altered !== "body")
        headers[`x-caf-${altered}-sha256`] = "0".repeat(64);
      await route.fulfill({
        response,
        headers,
        body:
          altered === "body"
            ? Buffer.from("authored substituted bytes")
            : await response.body(),
      });
    });
    const strip = await changes(page);
    await strip
      .getByRole("button", { name: "Save CAF copy", exact: true })
      .click();
    await expect(page.getByRole("alert")).toContainText(
      "differs from the exact source, proposal or artifact digest",
    );
    expect(downloads).toBe(0);
    await expect(
      page.getByText("Current scalar edits have not been exported.", {
        exact: true,
      }),
    ).toBeVisible();
    await select(page);
    await expect(field(page)).toHaveValue("256");
  });
}

test("pending Enum export retains its clicked snapshot while newer edits stay dirty", async ({
  page,
}) => {
  await open(page);
  await field(page).fill("256");
  let release!: () => void, started!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const received = new Promise<void>((resolve) => {
    started = resolve;
  });
  await page.route("**/api/caf/*/export", async (route) => {
    const response = await route.fetch({ maxRetries: 0 });
    started();
    await gate;
    await route.fulfill({ response });
  });
  try {
    const pending = page.waitForEvent("download");
    await page
      .getByRole("button", { name: "Save CAF copy", exact: true })
      .click();
    await received;
    await select(page);
    await field(page).fill("257");
    release();
    const file = (await (await pending).path())!;
    expect(
      python(
        "from bms_tool.caf import CafArchive;from pathlib import Path;import sys;print(next(p for p in CafArchive(Path(sys.argv[1]).read_bytes()).properties('controller/enum') if p['id']=='3113')['scalar']['text'])",
        file,
      )
        .toString()
        .trim(),
    ).toBe("256");
    await expect(field(page)).toHaveValue("257");
    await changes(page);
    await expect(
      page.getByText("Current scalar edits have not been exported.", {
        exact: true,
      }),
    ).toBeVisible();
  } finally {
    release();
  }
});

test("accepted file replacement A B A retires a pending Enum export even when the original hash returns", async ({
  page,
}) => {
  await open(page);
  await field(page).fill("256");
  let release!: () => void,
    started!: () => void,
    downloads = 0;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const received = new Promise<void>((resolve) => {
    started = resolve;
  });
  page.on("download", () => downloads++);
  await page.route("**/api/caf/*/export", async (route) => {
    const response = await route.fetch({ maxRetries: 0 });
    started();
    await gate;
    await route.fulfill({ response });
  });
  try {
    await page
      .getByRole("button", { name: "Save CAF copy", exact: true })
      .click();
    await received;
    await objects(page);
    page.once("dialog", async (dialog) => {
      expect(dialog.message()).toContain("Discard unexported CAF edits");
      await dialog.accept();
    });
    await page
      .getByLabel("Open local CAF application", { exact: true })
      .setInputFiles({
        name: "other.caf",
        mimeType: "application/octet-stream",
        buffer: authored("529"),
      });
    await expect(
      page.getByLabel("Current CAF archive", { exact: true }),
    ).toHaveText("other.caf");
    await page
      .getByLabel("Open local CAF application", { exact: true })
      .setInputFiles({
        name: "enum.caf",
        mimeType: "application/octet-stream",
        buffer: authored(),
      });
    await expect(
      page.getByLabel("Current CAF archive", { exact: true }),
    ).toHaveText("enum.caf");
    const settled = page.waitForResponse((r) =>
      /\/api\/caf\/[^/]+\/export$/.test(r.url()),
    );
    release();
    await settled;
    await page.waitForLoadState("networkidle");
    expect(downloads).toBe(0);
    await select(page);
    await expect(field(page)).toHaveValue("1");
  } finally {
    release();
  }
});

test("connected routed entry keeps CAF export local after navigation queries finish", async ({
  page,
}, info) => {
  const peer = await nativeDefaultPeer();
  const profiles: Promise<{
    status: number | undefined;
    finished: Error | null | undefined;
  }>[] = [];
  page.on("request", (request) => {
    if (request.url().endsWith("/api/bacnet/controller/profile"))
      profiles.push(
        request
          .response()
          .then(async (response) => ({
            status: response?.status(),
            finished: await response?.finished(),
          })),
      );
  });
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
      name: "enum.caf",
      mimeType: "application/octet-stream",
      buffer: authored(),
    });
    await expect(
      page.getByLabel("Current CAF archive", { exact: true }),
    ).toHaveText("enum.caf");
    await page.getByRole("button", { name: "Edit", exact: true }).click();
    await select(page);
    await field(page).fill("256");
    const strip = await changes(page);
    // Entering the connected controller's default Program task can launch its
    // existing controller-profile read. It is navigation, not a CAF export.
    // Await the specific later SPA request: the page may already have reached
    // its load state before controller-profile navigation starts.
    expect(profiles.length).toBeGreaterThan(0);
    for (const response of await Promise.all(profiles)) {
      expect(response.status).toBe(200);
      expect(response.finished).toBeNull();
    }
    const before = await peer.command("stats"),
      pending = page.waitForEvent("download");
    await strip
      .getByRole("button", { name: "Save CAF copy", exact: true })
      .click();
    await pending;
    const after = await peer.command("stats");
    await info.attach("CAF export peer requests", {
      body: Buffer.from(JSON.stringify({ before, after })),
      contentType: "application/json",
    });
    expect(after.request_types).toEqual(before.request_types);
    expect(after.events).toEqual(before.events);
  } finally {
    peer.close();
  }
});
