import {
  test,
  expect,
  type Page,
  type APIRequestContext,
} from "./nativeScheduleWriteFixture";
import { nativeDefaultPeer } from "./native-default-peer";
import { freePort } from "./workflow-peer";
import { chooseWorkspaceTask } from "./workspace-navigation";
import { execFileSync } from "node:child_process";
import path from "node:path";
const base = "/api/bacnet/controller/native-application";
async function open(page: Page, request: APIRequestContext, endpoint: string) {
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  expect(
    (
      await request.post(base + "/credentials", {
        headers,
        data: { backup: "authored-backup", restore: "authored-restore" },
      })
    ).ok(),
  ).toBe(true);
  // Ordinary inventory presentation is independent of the native transfer peer.
  await page.route("**/api/bacnet/controller/inventory", (route) =>
    route.fulfill({
      json: {
        identity_verified: true,
        complete: true,
        target: route.request().postDataJSON(),
        offset: 0,
        total: 0,
        next_offset: null,
        objects: [],
        errors: [],
      },
    }),
  );
  await page.goto("/");
  await page.getByRole("button", { name: /^Connect to a controller/ }).click();
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
    .fill(endpoint);
  await page
    .getByLabel("Known Device object", { exact: true })
    .fill("device,5136");
  await page.getByLabel("Known router", { exact: true }).fill("");
  await page.getByLabel("Known network", { exact: true }).fill("");
  await page
    .getByRole("region", { name: "Known controller connection" })
    .getByRole("button", { name: "Open controller", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Controller overview" }),
  ).toContainText("Authored controller");
  await chooseWorkspaceTask(page, "Points & I/O");
  return inputs(page);
}
async function inputs(page: Page) {
  const button = page.getByRole("button", {
    name: "Configure native inputs",
    exact: true,
  });
  if (await button.isVisible()) await button.click();
  return page.getByRole("region", {
    name: "Native input configuration",
    exact: true,
  });
}
async function capture(p: ReturnType<Page["getByRole"]>) {
  await p
    .getByRole("button", { name: "Capture native inputs", exact: true })
    .click();
  await expect(
    p.getByLabel("Native input object instance", { exact: true }),
  ).toHaveValue("3000002");
}
async function apply(p: ReturnType<Page["getByRole"]>) {
  await p
    .getByRole("button", {
      name: "Review controller input change",
      exact: true,
    })
    .click();
  const r = p.getByRole("region", { name: "Input change review", exact: true });
  await expect(r).toBeVisible();
  await r
    .getByLabel(
      "Wiring, sensor mode, common and any required jumpers match this terminal.",
      { exact: true },
    )
    .check();
  await r
    .getByLabel("I confirm this input allocation/mode and scaling change.", {
      exact: true,
    })
    .check();
  await r
    .getByLabel(
      "I confirm the application transfer and possible control restart.",
      { exact: true },
    )
    .check();
  const response = p
    .page()
    .waitForResponse(
      (r) =>
        r.url().endsWith("/native-application/input/apply") &&
        r.request().method() === "POST",
    );
  await r
    .getByRole("button", {
      name: "Apply input change to controller",
      exact: true,
    })
    .click();
  const receipt = await (await response).json();
  expect(receipt.result.status).toBe("verified");
  await expect(
    p.getByRole("region", { name: "Input transfer result", exact: true }),
  ).toContainText("Input transfer: verified", { timeout: 30000 });
  await expect(
    p.getByRole("button", { name: "Capture native inputs", exact: true }),
  ).toBeEnabled({ timeout: 30000 });
}
test("native input allocation, mode round trip, offline copy and guarded removal use actual UDP", async ({
  page,
  request,
}, info) => {
  test.setTimeout(90000);
  const peer = await nativeDefaultPeer("consume", "input");
  try {
    let p = await open(page, request, peer.direct);
    await capture(p);
    await p
      .getByLabel("Native input name", { exact: true })
      .fill("Reviewed spare input");
    await p
      .getByRole("button", { name: "Review local input copy", exact: true })
      .click();
    await expect(p).toContainText("Local copy reviewed.");
    const download = page.waitForEvent("download");
    await p
      .getByRole("button", { name: "Save native copy", exact: true })
      .click();
    expect((await download).suggestedFilename()).toBe("native-input-copy.moi");
    expect(
      (await peer.command("stats")).events.filter(
        (e: any[]) => e[0] === "write",
      ),
    ).toHaveLength(0);
    await p
      .getByRole("button", {
        name: "Review controller input change",
        exact: true,
      })
      .click();
    await expect(
      p.getByRole("region", { name: "Input change review" }),
    ).toBeVisible();
    await chooseWorkspaceTask(page, "Overview");
    await chooseWorkspaceTask(page, "Points & I/O");
    p = await inputs(page);
    await expect(
      p.getByLabel("Native input name", { exact: true }),
    ).toHaveValue("Reviewed spare input");
    await expect(
      p.getByRole("button", {
        name: "Apply input change to controller",
        exact: true,
      }),
    ).toHaveCount(0);
    await apply(p);
    for (const mode of ["resistance", "voltage"]) {
      await p
        .getByRole("button", { name: "Capture native inputs", exact: true })
        .click();
      await expect(
        p.getByRole("button", { name: "Capture native inputs", exact: true }),
      ).toBeEnabled();
      await p
        .getByLabel("Input operation", { exact: true })
        .selectOption("mode");
      await p
        .getByLabel("Configured native input", { exact: true })
        .selectOption("analog-input,3000002");
      await p
        .getByLabel("Native input electrical mode", { exact: true })
        .selectOption(mode);
      if (mode === "resistance")
        await p
          .getByLabel("Electrical range high", { exact: true })
          .fill("1000");
      await apply(p);
    }
    await p
      .getByRole("button", { name: "Capture native inputs", exact: true })
      .click();
    await expect(
      p.getByRole("button", { name: "Capture native inputs", exact: true }),
    ).toBeEnabled();
    await p
      .getByLabel("Input operation", { exact: true })
      .selectOption("remove-allocated");
    await p
      .getByLabel("Configured native input", { exact: true })
      .selectOption("analog-input,3000002");
    await p
      .getByLabel("Input allocation origin", { exact: true })
      .selectOption({
        label: await p
          .getByLabel("Input allocation origin", { exact: true })
          .locator("option")
          .nth(1)
          .innerText(),
      });
    await apply(p);
    await p
      .getByRole("button", { name: "Read back input transfer", exact: true })
      .click();
    await expect(
      p.getByRole("button", { name: "Read back input transfer", exact: true }),
    ).toBeEnabled();
    expect(
      (await peer.command("stats")).events.filter(
        (e: any[]) => e[0] === "state" && e[1] === "start-restore",
      ),
    ).toHaveLength(4);
    await page.screenshot({
      path: info.outputPath("native-inputs-desktop.png"),
      fullPage: true,
    });
    await page.setViewportSize({ width: 390, height: 1100 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: info.outputPath("native-inputs-phone.png"),
      fullPage: true,
    });
  } finally {
    peer.close();
  }
});

test("substituted input review cannot authorize apply", async ({
  page,
  request,
}) => {
  const peer = await nativeDefaultPeer("consume", "input");
  try {
    const p = await open(page, request, peer.direct);
    await capture(p);
    await p
      .getByLabel("Native input name", { exact: true })
      .fill("Proposed input");
    await page.route("**/native-application/input/preview", async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      const r = await response.json();
      r.input_edit.slot = 2;
      await route.fulfill({ response, json: r });
    });
    await p
      .getByRole("button", {
        name: "Review controller input change",
        exact: true,
      })
      .click();
    await expect(p.getByRole("alert")).toContainText("differs from this draft");
    await expect(
      p.getByRole("button", {
        name: "Apply input change to controller",
        exact: true,
      }),
    ).toHaveCount(0);
    expect(
      (await peer.command("stats")).events.filter(
        (e: any[]) => e[0] === "write",
      ),
    ).toHaveLength(0);
  } finally {
    peer.close();
  }
});

test("input review keeps Apply as its one primary action", async ({
  page,
  request,
}) => {
  const peer = await nativeDefaultPeer("consume", "input");
  try {
    const p = await open(page, request, peer.direct);
    await capture(p);
    await p
      .getByLabel("Native input name", { exact: true })
      .fill("Primary action review");
    await p
      .getByRole("button", {
        name: "Review controller input change",
        exact: true,
      })
      .click();
    await expect(
      p.getByRole("region", { name: "Input change review", exact: true }),
    ).toBeVisible();
    await expect(p.locator("button.primary")).toHaveCount(1);
    await expect(
      p.getByRole("button", {
        name: "Apply input change to controller",
        exact: true,
      }),
    ).toHaveClass(/primary/);
    expect(
      (await peer.command("stats")).events.filter(
        (e: any[]) => e[0] === "write",
      ),
    ).toHaveLength(0);
  } finally {
    peer.close();
  }
});

test("capturing the selected controller cannot carry an edited foreign source into it", async ({
  page,
  request,
  nativeScheduleWriteServer,
}) => {
  const root = path.resolve(".."),
    foreign = JSON.parse(
      execFileSync(
        path.join(root, ".venv/bin/python"),
        [
          "-c",
          `
import json,sys
from pathlib import Path
from bms_tool.storage import Store
from bms_tool.application_store import ApplicationStore
from tests.test_native_inputs import source
s=ApplicationStore(Store(Path(sys.argv[1])))
c=s.save({'target':{'address':'127.0.0.1:47998','router':None,'dnet':None},'device':'device,5136','identity':{'device':'device,5136','object-name':'Authored controller'},'source_identity_matches':True,'connector_config':{}},source())
print(json.dumps(c))
`,
          nativeScheduleWriteServer.directory,
        ],
        {
          cwd: root,
          env: { ...process.env, PYTHONPATH: root + "/backend:" + root },
          encoding: "utf8",
        },
      ),
    );
  const peer = await nativeDefaultPeer("consume", "input");
  try {
    const p = await open(page, request, peer.direct);
    await p
      .getByLabel("Retained native input source", { exact: true })
      .selectOption(foreign.id);
    await p
      .getByLabel("Native input name", { exact: true })
      .fill("Foreign unfinished input");
    const before = await peer.command("stats");
    await p
      .getByRole("button", { name: "Capture native inputs", exact: true })
      .click();
    await expect(p.getByRole("alert")).toContainText(
      "Discard the local input draft",
    );
    await expect(
      p.getByLabel("Retained native input source", { exact: true }),
    ).toHaveValue(foreign.id);
    await expect(
      p.getByLabel("Native input name", { exact: true }),
    ).toHaveValue("Foreign unfinished input");
    expect((await peer.command("stats")).events).toEqual(before.events);
  } finally {
    peer.close();
  }
});

test("CAF entry can edit and save a retained native input copy with no field interface", async ({
  page,
  request,
  nativeScheduleWriteServer,
}) => {
  const root = path.resolve(".."),
    env = {
      ...process.env,
      PYTHONPATH: [path.join(root, "backend"), root].join(path.delimiter),
    };
  const capture = JSON.parse(
    execFileSync(
      path.join(root, ".venv/bin/python"),
      [
        "-c",
        `
import json,sys
from pathlib import Path
from bms_tool.storage import Store
from bms_tool.application_store import ApplicationStore
from tests.test_native_inputs import source
s=ApplicationStore(Store(Path(sys.argv[1])))
c=s.save({'target':{'address':'127.0.0.1:47999','router':None,'dnet':None},'device':'device,5136','identity':{'device':'device,5136','object-name':'Authored controller'},'source_identity_matches':True,'connector_config':{}},source())
c['alternate_id']=s.save({'target':{'address':'127.0.0.1:47998','router':None,'dnet':None},'device':'device,5136','identity':{'device':'device,5136','object-name':'Authored controller'},'source_identity_matches':True,'connector_config':{}},source())['id']
print(json.dumps(c))
`,
        nativeScheduleWriteServer.directory,
      ],
      { cwd: root, env, encoding: "utf8" },
    ),
  );
  const caf = execFileSync(
    path.join(root, ".venv/bin/python"),
    [
      "-c",
      "from tests.test_caf_graph import make_graph; import sys; sys.stdout.buffer.write(make_graph())",
    ],
    { cwd: root, env },
  );
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  expect(
    (await request.post("/api/bacnet/disconnect", { headers, data: {} })).ok(),
  ).toBe(true);
  const calls: string[] = [];
  page.on("request", (r) => {
    if (
      r.method() === "POST" &&
      /\/(connect|capture|input\/support|input\/preview|input\/apply|readback)$/.test(
        r.url(),
      )
    )
      calls.push(r.url());
  });
  await page.goto("/");
  await page
    .getByLabel("Open local CAF application", { exact: true })
    .setInputFiles({
      name: "native-input-offline.caf",
      mimeType: "application/octet-stream",
      buffer: caf,
    });
  await chooseWorkspaceTask(page, "Points & I/O");
  let p = page.getByRole("region", {
    name: "Native input configuration",
    exact: true,
  });
  await p
    .getByLabel("Retained native input source", { exact: true })
    .selectOption(capture.id);
  await p
    .getByLabel("Native input object instance", { exact: true })
    .fill("3000010");
  await p
    .getByLabel("Native input name", { exact: true })
    .fill("Offline spare input");
  await chooseWorkspaceTask(page, "Schedules");
  await chooseWorkspaceTask(page, "Points & I/O");
  p = page.getByRole("region", {
    name: "Native input configuration",
    exact: true,
  });
  await expect(p.getByLabel("Native input name", { exact: true })).toHaveValue(
    "Offline spare input",
  );
  await expect(
    p.getByRole("button", {
      name: "Review controller input change",
      exact: true,
    }),
  ).toBeDisabled();
  await expect(
    p.getByRole("button", { name: "Review local input copy", exact: true }),
  ).toHaveClass(/primary/);
  await p
    .getByRole("button", { name: "Review local input copy", exact: true })
    .click();
  await expect(p).toContainText("Local copy reviewed.");
  await expect(
    p.getByRole("button", { name: "Save native copy", exact: true }),
  ).toHaveClass(/primary/);
  await expect(p.locator("button.primary")).toHaveCount(1);
  const download = page.waitForEvent("download");
  await p
    .getByRole("button", { name: "Save native copy", exact: true })
    .click();
  await download;
  await p
    .getByLabel("Retained native input source", { exact: true })
    .selectOption(capture.alternate_id);
  await expect(p.getByRole("alert")).toContainText(
    "Discard the local input draft",
  );
  await expect(p.getByLabel("Native input name", { exact: true })).toHaveValue(
    "Offline spare input",
  );
  await expect(
    p.getByLabel("Retained native input source", { exact: true }),
  ).toHaveValue(capture.id);
  await p
    .getByRole("button", { name: "Discard local input draft", exact: true })
    .click();
  await p
    .getByLabel("Retained native input source", { exact: true })
    .selectOption(capture.alternate_id);
  await expect(
    p.getByLabel("Retained native input source", { exact: true }),
  ).toHaveValue(capture.alternate_id);
  await expect(p.getByLabel("Native input name", { exact: true })).toHaveValue(
    "",
  );
  expect(
    (await (await request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
  expect(calls).toEqual([]);
});
