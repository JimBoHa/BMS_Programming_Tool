import {
  test,
  expect,
  type Page,
  type APIRequestContext,
} from "./nativeScheduleWriteFixture";
import { chooseWorkspaceTask } from "./workspace-navigation";
import { execFileSync } from "node:child_process";
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
const root = path.resolve(".."),
  base = "/api/bacnet/controller/native-application";
async function auth(request: APIRequestContext) {
  return {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
}
function seed(directory: string, kind: "name" | "instance") {
  return JSON.parse(
    execFileSync(
      path.join(root, ".venv/bin/python"),
      [
        "-c",
        `
import sys,json
from pathlib import Path
if sys.argv[2]=='name':
 from tests.test_native_name_recovery import setup
else:
 from tests.test_native_instance_recovery import setup
storage,service,request,*_=setup(Path(sys.argv[1]))
print(json.dumps({'request':request,'receipt':storage.receipt(request['receipt_id']),'folder':str(storage.directory/request['capture_id'])}))
`,
        directory,
        kind,
      ],
      {
        cwd: root,
        env: {
          ...process.env,
          PYTHONPATH: [path.join(root, "backend"), root].join(path.delimiter),
        },
        encoding: "utf8",
      },
    ),
  );
}
function archiveContents(buffer: Buffer) {
  return JSON.parse(
    execFileSync(
      path.join(root, ".venv/bin/python"),
      [
        "-c",
        `
import sys,io,json,zipfile,hashlib
with zipfile.ZipFile(io.BytesIO(sys.stdin.buffer.read())) as archive:
 print(json.dumps([{'name':entry.filename,'bytes':entry.file_size,'sha256':hashlib.sha256(archive.read(entry)).hexdigest()} for entry in archive.infolist()]))
`,
      ],
      { input: buffer, encoding: "utf8" },
    ),
  );
}
function storedContents(folder: string) {
  return readdirSync(folder)
    .sort()
    .map((name) => ({ name, bytes: readFileSync(path.join(folder, name)) }));
}
const panel = (page: Page, kind: string) =>
  page.getByRole("region", {
    name: `Native application ${kind} commissioning`,
    exact: true,
  });
async function identity(page: Page, kind: "name" | "instance") {
  await chooseWorkspaceTask(page, "Overview");
  const tools = page.getByRole("navigation", {
    name: "Controller task tools",
    exact: true,
  });
  const select = tools.getByRole("combobox", {
    name: "Controller task tools",
    exact: true,
  });
  if (await select.isVisible())
    await select.selectOption({ label: "Identity settings" });
  else
    await tools
      .getByRole("button", { name: "Identity settings", exact: true })
      .click();
  await page.getByLabel("Identity setting", { exact: true }).selectOption(kind);
  if (kind === "instance")
    await page
      .getByLabel("Instance change method", { exact: true })
      .selectOption("native");
  await expect(panel(page, kind)).toBeVisible();
  return panel(page, kind);
}
async function openLocal(page: Page, kind: "name" | "instance") {
  await page.goto("/");
  const buffer = execFileSync(
    path.join(root, ".venv/bin/python"),
    [
      "-c",
      "from tests.test_caf_graph import make_graph; import sys; sys.stdout.buffer.write(make_graph())",
    ],
    {
      cwd: root,
      env: {
        ...process.env,
        PYTHONPATH: [path.join(root, "backend"), root].join(path.delimiter),
      },
    },
  );
  await page
    .getByLabel("Open local CAF application", { exact: true })
    .setInputFiles({
      name: "identity-work.caf",
      mimeType: "application/octet-stream",
      buffer,
    });
  return identity(page, kind);
}
async function load(page: Page, kind: "name" | "instance", id: string) {
  const p = panel(page, kind),
    summary = p
      .locator("summary")
      .filter({ hasText: new RegExp("^Previous controller " + kind + "$") });
  if ((await summary.locator("..").getAttribute("open")) === null)
    await summary.click();
  await p
    .getByRole("button", { name: `Load retained ${kind} backups`, exact: true })
    .click();
  await p
    .getByLabel((kind === "name" ? "Name" : "Instance") + " recovery backup", {
      exact: true,
    })
    .selectOption(id);
  await expect(
    p.getByLabel("Captured native application", { exact: true }),
  ).toBeVisible();
  return p;
}
async function manager(page: Page, kind: string) {
  const p = panel(page, kind),
    summary = p
      .locator("summary")
      .filter({ hasText: /^Retained identity drafts$/ });
  if ((await summary.locator("..").getAttribute("open")) === null)
    await summary.click();
  return p;
}
for (const kind of ["name", "instance"] as const)
  test(`offline ${kind} draft can be saved and explicitly discarded without changing original evidence`, async ({
    page,
    request,
    nativeScheduleWriteServer,
  }) => {
    const data = seed(nativeScheduleWriteServer.directory, kind),
      headers = await auth(request);
    expect(
      (
        await request.post("/api/bacnet/disconnect", { headers, data: {} })
      ).ok(),
    ).toBe(true);
    const storedBefore = storedContents(data.folder);
    const before = archiveContents(
      await (
        await request.get(base + "/backups/" + data.request.capture_id)
      ).body(),
    );
    const calls: string[] = [];
    page.on("request", (r) => {
      if (
        r.method() === "POST" &&
        /\/native-application\/(capture|preview|apply|readback)$/.test(r.url())
      )
        calls.push(r.url());
    });
    let p = await openLocal(page, kind);
    await manager(page, kind);
    await expect(p).toContainText("0 of 32 slots used");
    await p
      .getByLabel("Retained native transfer receipts", { exact: true })
      .selectOption(data.request.receipt_id);
    await expect(
      p.getByLabel("Native application transfer receipt", { exact: true }),
    ).toBeVisible();
    await expect(p).toContainText("0 of 32 slots used");
    p = await load(page, kind, data.request.capture_id);
    const label =
        kind === "name"
          ? "New controller name"
          : "New application Device instance (0–4194302)",
      text = kind === "name" ? "  unfinished identity  " : "6000";
    await p.getByLabel(label, { exact: true }).fill(text);
    await chooseWorkspaceTask(page, "Program");
    p = await identity(page, kind);
    await expect(p.getByLabel(label, { exact: true })).toHaveValue(text);
    await manager(page, kind);
    await expect(p).toContainText("1 of 32 slots used");
    const chooser = p.getByLabel("Retained local identity draft", {
      exact: true,
    });
    const key = await chooser
      .locator("option:not([disabled])")
      .first()
      .getAttribute("value");
    await chooser.selectOption(key!);
    const downloading = page.waitForEvent("download");
    await p
      .getByRole("button", { name: "Save local identity draft", exact: true })
      .click();
    const doc = JSON.parse(
      readFileSync((await (await downloading).path())!).toString(),
    );
    expect(doc.profile).toBe("native-identity-local-draft/1");
    expect(doc.field_authority).toBe(false);
    expect(doc[kind === "name" ? "new_name" : "new_instance_text"]).toBe(text);
    expect(doc.capture_id).toBe(data.request.capture_id);
    await p
      .getByRole("button", {
        name: "Discard local identity draft",
        exact: true,
      })
      .click();
    await expect(
      p.getByLabel("Captured native application", { exact: true }),
    ).toHaveCount(0);
    await expect(p).toContainText("0 of 32 slots used");
    expect(
      archiveContents(
        await (
          await request.get(base + "/backups/" + data.request.capture_id)
        ).body(),
      ),
    ).toEqual(before);
    expect(storedContents(data.folder)).toEqual(storedBefore);
    expect(
      await (
        await request.get(base + "/receipts/" + data.request.receipt_id)
      ).json(),
    ).toEqual(data.receipt);
    expect(calls).toEqual([]);
  });
async function context(page: Page, i: number, initial = false) {
  if (initial) {
    await page.goto("/");
    await page
      .getByRole("button", { name: /^Connect to a controller/ })
      .click();
  } else
    await page
      .getByRole("button", { name: "Change controller", exact: true })
      .click();
  await page
    .getByRole("button", { name: "Known controller address", exact: true })
    .click();
  for (const [name, value] of [
    ["Known controller address", "192.0.2." + (i + 1)],
    ["Known Device object", "device," + (6000 + i)],
    ["Known router", ""],
    ["Known network", ""],
  ])
    await page.getByLabel(name, { exact: true }).fill(value);
  await page
    .getByRole("region", { name: "Known controller connection", exact: true })
    .getByRole("button", { name: "Open controller", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Controller overview", exact: true }),
  ).toContainText("Authored context " + i);
  await page
    .getByRole("button", { name: "Edit controller name", exact: true })
    .click();
  return panel(page, "name");
}
test("identity UI refuses a 33rd context, keeps earlier proposals, and frees only explicitly discarded work", async ({
  page,
  request,
  nativeScheduleWriteServer,
}, info) => {
  test.setTimeout(180000);
  const data = seed(nativeScheduleWriteServer.directory, "name"),
    headers = await auth(request);
  expect(
    (await request.post("/api/bacnet/disconnect", { headers, data: {} })).ok(),
  ).toBe(true);
  await page.route("**/api/bacnet/status", (route) =>
    route.fulfill({
      json: {
        connected: true,
        config: {
          local_address: "127.0.0.1:59997",
          instance: 4190001,
          router: null,
          dnet: null,
        },
        commands: [],
      },
    }),
  );
  await page.route("**/api/bacnet/device-details", (route) => {
    const body = route.request().postDataJSON(),
      i = Number(body.device.split(",")[1]) - 6000;
    return route.fulfill({
      json: {
        identity_verified: true,
        address: body.address,
        properties: {
          "object-identifier": body.device,
          "object-name": "Authored context " + i,
          "model-name": "Authored HTTP context",
        },
        finished_at: new Date().toISOString(),
      },
    });
  });
  const field: string[] = [];
  page.on("request", (r) => {
    if (
      r.method() === "POST" &&
      /\/native-application\/(capture|preview|apply|readback)$/.test(r.url())
    )
      field.push(r.url());
  });
  for (let i = 0; i < 32; i++) {
    const p = await context(page, i, i === 0);
    await load(page, "name", data.request.capture_id);
    await p
      .getByLabel("New controller name", { exact: true })
      .fill("Draft " + i);
  }
  let p = await context(page, 32);
  await manager(page, "name");
  await expect(p).toContainText("32 of 32 slots used");
  await expect(p).toContainText(
    "All 32 native identity draft slots are in use",
  );
  const summary = p
    .locator("summary")
    .filter({ hasText: /^Previous controller name$/ });
  await summary.click();
  await p
    .getByRole("button", { name: "Load retained name backups", exact: true })
    .click();
  await expect(
    p.getByLabel("Name recovery backup", { exact: true }),
  ).toBeDisabled();
  const choices = p.getByLabel("Retained local identity draft", {
    exact: true,
  });
  const first = await choices
    .locator("option")
    .filter({ hasText: "device,6000 at" })
    .getAttribute("value");
  await choices.selectOption(first!);
  await expect(
    p.getByRole("region", {
      name: "Retained native identity draft",
      exact: true,
    }),
  ).toContainText("Draft 0");
  await expect(page.getByLabel("Working context")).toContainText("device,6032");
  await p
    .getByRole("button", {
      name: "Discard selected retained draft",
      exact: true,
    })
    .click();
  await expect(p).toContainText("31 of 32 slots used");
  await p
    .getByLabel("Name recovery backup", { exact: true })
    .selectOption(data.request.capture_id);
  await expect(
    p.getByLabel("Captured native application", { exact: true }),
  ).toBeVisible();
  await p.getByLabel("New controller name", { exact: true }).fill("Draft 32");
  await expect(p).toContainText("32 of 32 slots used");
  p = await context(page, 1);
  await expect(
    p.getByLabel("New controller name", { exact: true }),
  ).toHaveValue("Draft 1");
  await p
    .getByLabel("New controller name", { exact: true })
    .fill("Draft 1 updated");
  await chooseWorkspaceTask(page, "Program");
  p = await identity(page, "name");
  await expect(
    p.getByLabel("New controller name", { exact: true }),
  ).toHaveValue("Draft 1 updated");
  await expect(
    p.getByRole("button", { name: "Review name change", exact: true }),
  ).toBeDisabled();
  expect(field).toEqual([]);
  expect(
    (await (await request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
  await page.setViewportSize({ width: 390, height: 1100 });
  await manager(page, "name");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: info.outputPath("identity-draft-capacity-phone.png"),
    fullPage: true,
  });
});
