import {
  test,
  expect,
  type Page,
  type APIRequestContext,
} from "./nativeScheduleWriteFixture";
import {
  chooseWorkspaceTask,
  chooseWorkspaceSurface,
} from "./workspace-navigation";
import { execFileSync } from "node:child_process";
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
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
  await expect(
    page.getByLabel("Working context", { exact: true }),
  ).toContainText("identity-work.caf");
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

type Kind = "name" | "instance";
type RawFile = { name: string; bytes: Buffer; document?: any };
const importPath = base + "/local-drafts/import";
const proposalLabel = (kind: Kind) =>
  kind === "name"
    ? "New controller name"
    : "New application Device instance (0–4194302)";
const rawProposal = (kind: Kind) =>
  kind === "name" ? "  unfinished 🌡  " : " 1e- ";
async function launch(page: Page, kind: Kind, caf = true) {
  if (caf) return openLocal(page, kind);
  await page.goto("/");
  const create = page.getByRole("button", {
    name: "New application",
    exact: true,
  });
  if (await create.isVisible()) await create.click();
  await chooseWorkspaceSurface(page, "Workspace");
  return identity(page, kind);
}
async function saved(page: Page, kind: Kind): Promise<RawFile> {
  const p = await manager(page, kind),
    chooser = p.getByLabel("Retained local identity draft", { exact: true });
  await chooser.selectOption(
    (await chooser
      .locator("option:not([disabled])")
      .first()
      .getAttribute("value"))!,
  );
  const download = page.waitForEvent("download");
  await p
    .getByRole("button", { name: "Save local identity draft", exact: true })
    .click();
  const file = await download,
    bytes = readFileSync((await file.path())!);
  return {
    name: file.suggestedFilename(),
    bytes,
    document: JSON.parse(bytes.toString()),
  };
}
async function restore(page: Page, kind: Kind, file: RawFile) {
  const p = await manager(page, kind);
  await p
    .getByLabel("Import local identity draft file", { exact: true })
    .setInputFiles({
      name: file.name,
      mimeType: "application/json",
      buffer: file.bytes,
    });
}
async function discard(page: Page, kind: Kind) {
  await panel(page, kind)
    .getByRole("button", { name: "Discard local identity draft", exact: true })
    .click();
  await expect(
    panel(page, kind).getByLabel("Captured native application", {
      exact: true,
    }),
  ).toHaveCount(0);
}
async function setup(
  page: Page,
  request: APIRequestContext,
  directory: string,
  kind: Kind,
  caf = true,
) {
  const data = seed(directory, kind),
    headers = await auth(request);
  expect(
    (await request.post("/api/bacnet/disconnect", { headers, data: {} })).ok(),
  ).toBe(true);
  const calls: string[] = [];
  page.on("request", (r) => {
    if (
      r.method() === "POST" &&
      /\/native-application\/(capture|preview|apply|readback|credentials)$/.test(
        r.url(),
      )
    )
      calls.push(r.url());
  });
  await launch(page, kind, caf);
  await load(page, kind, data.request.capture_id);
  await panel(page, kind)
    .getByLabel(proposalLabel(kind), { exact: true })
    .fill(rawProposal(kind));
  return { data, headers, calls };
}
for (const kind of ["name", "instance"] as const) {
  for (const caf of [false, true])
    test(`${kind} unfinished text recovers after ${caf ? "CAF" : "graph"} reload without restoring authority`, async ({
      page,
      request,
      nativeScheduleWriteServer,
    }, info) => {
      const { data, calls } = await setup(
          page,
          request,
          nativeScheduleWriteServer.directory,
          kind,
          caf,
        ),
        before = storedContents(data.folder);
      const file = await saved(page, kind);
      file.document.receipt_id = data.request.receipt_id;
      file.document.recovery_origin_sha256 = "f".repeat(64);
      file.bytes = Buffer.from(JSON.stringify(file.document));
      await page.reload();
      await launch(page, kind, caf);
      await restore(page, kind, file);
      let p = panel(page, kind);
      await expect(
        p.getByLabel(proposalLabel(kind), { exact: true }),
      ).toHaveValue(rawProposal(kind));
      await expect(
        p.getByLabel("Reviewed native application transfer", { exact: true }),
      ).toHaveCount(0);
      await expect(
        p.getByRole("region", {
          name: `Previous controller ${kind} proposal`,
          exact: true,
        }),
      ).toHaveCount(0);
      await expect(
        p.getByLabel("Native application transfer receipt", { exact: true }),
      ).toHaveCount(0);
      await expect(p).toContainText("1 of 32 slots used");
      const again = await saved(page, kind);
      expect(
        again.document[kind === "name" ? "new_name" : "new_instance_text"],
      ).toBe(rawProposal(kind));
      expect(again.document.receipt_id).toBe(file.document.receipt_id);
      expect(again.document.recovery_origin_sha256).toBe("f".repeat(64));
      expect(again.document.raw_imported).toEqual({
        filename: file.name,
        file_sha256: createHash("sha256").update(file.bytes).digest("hex"),
      });
      await p
        .getByLabel(proposalLabel(kind), { exact: true })
        .fill(kind === "name" ? "  still raw  " : "42e-");
      await chooseWorkspaceTask(page, "Program");
      p = await identity(page, kind);
      await manager(page, kind);
      await expect(
        p.getByLabel(proposalLabel(kind), { exact: true }),
      ).toHaveValue(kind === "name" ? "  still raw  " : "42e-");
      expect((await saved(page, kind)).document.raw_imported).toEqual(
        again.document.raw_imported,
      );
      await page.setViewportSize({ width: 390, height: 1100 });
      await p
        .getByText("Retained identity drafts", { exact: true })
        .scrollIntoViewIfNeeded();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await page.screenshot({
        path: info.outputPath(`identity-${kind}-phone.png`),
        fullPage: true,
      });
      expect(storedContents(data.folder)).toEqual(before);
      expect(calls).toEqual([]);
      expect(
        (await (await request.get("/api/session")).json()).field_network_open,
      ).toBe(false);
    });
  test(`${kind} replacement and damaged source references keep retained text`, async ({
    page,
    request,
    nativeScheduleWriteServer,
  }) => {
    const { calls } = await setup(
        page,
        request,
        nativeScheduleWriteServer.directory,
        kind,
      ),
      file = await saved(page, kind),
      p = panel(page, kind);
    await restore(page, kind, file);
    await expect(p.getByRole("alert")).toContainText(
      "Discard this retained identity draft",
    );
    await expect(
      p.getByLabel(proposalLabel(kind), { exact: true }),
    ).toHaveValue(rawProposal(kind));
    await discard(page, kind);
    const wrong = {
      ...file.document,
      selection: {
        ...file.document.selection,
        change_kind: kind === "name" ? "instance" : "name",
      },
    };
    await restore(page, kind, {
      name: "wrong-kind.json",
      bytes: Buffer.from(JSON.stringify(wrong)),
    });
    await expect(p.getByRole("alert")).toContainText(
      "same interface configuration",
    );
    await restore(page, kind, {
      name: "wrong-source.json",
      bytes: Buffer.from(
        JSON.stringify({ ...file.document, snapshot_sha256: "e".repeat(64) }),
      ),
    });
    await expect(p.getByRole("alert")).toContainText("evidence changed");
    await expect(
      p.getByLabel("Captured native application", { exact: true }),
    ).toHaveCount(0);
    await restore(page, kind, file);
    await expect(
      p.getByLabel(proposalLabel(kind), { exact: true }),
    ).toHaveValue(rawProposal(kind));
    expect(calls).toEqual([]);
  });
  test(`${kind} malformed and oversized imports preserve existing fields and do not post`, async ({
    page,
    request,
    nativeScheduleWriteServer,
  }) => {
    await setup(page, request, nativeScheduleWriteServer.directory, kind);
    const posts: string[] = [];
    page.on("request", (r) => {
      if (r.method() === "POST" && r.url().endsWith(importPath))
        posts.push(r.url());
    });
    await restore(page, kind, {
      name: "duplicate.json",
      bytes: Buffer.from('{"selection":1,"selection":2}'),
    });
    await expect(panel(page, kind).getByRole("alert")).toContainText(
      "Duplicate",
    );
    await restore(page, kind, {
      name: "oversized.json",
      bytes: Buffer.alloc(128 * 1024 + 1, 32),
    });
    await expect(panel(page, kind).getByRole("alert")).toContainText("128 KiB");
    await expect(
      panel(page, kind).getByLabel(proposalLabel(kind), { exact: true }),
    ).toHaveValue(rawProposal(kind));
    expect(posts).toEqual([]);
  });
  for (const boundary of [
    "edit",
    "family ABA",
    "task",
    "visibility",
    "pagehide",
  ] as const)
    test(`held ${kind} raw reply retires after ${boundary}`, async ({
      page,
      request,
      nativeScheduleWriteServer,
    }) => {
      const { headers, calls } = await setup(
          page,
          request,
          nativeScheduleWriteServer.directory,
          kind,
        ),
        file = await saved(page, kind);
      const actual = await request.post(importPath, {
        headers,
        multipart: {
          file: {
            name: file.name,
            mimeType: "application/json",
            buffer: file.bytes,
          },
        },
      });
      expect(actual.ok(), await actual.text()).toBe(true);
      const body = await actual.body();
      if (boundary !== "edit") await discard(page, kind);
      let release!: () => void, reached!: () => void;
      const held = new Promise<void>((r) => (release = r)),
        seen = new Promise<void>((r) => (reached = r));
      await page.route("**" + importPath, async (route) => {
        reached();
        await held;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body,
        });
      });
      try {
        await restore(page, kind, file);
        await seen;
        if (boundary === "edit")
          await panel(page, kind)
            .getByLabel(proposalLabel(kind), { exact: true })
            .fill(kind === "name" ? "later proposal" : "900e-");
        else if (boundary === "family ABA") {
          await identity(page, kind === "name" ? "instance" : "name");
          await identity(page, kind);
        } else if (boundary === "task") {
          await chooseWorkspaceTask(page, "Program");
          await identity(page, kind);
        } else
          await page.evaluate((type) => {
            if (type === "visibility")
              document.dispatchEvent(new Event("visibilitychange"));
            else window.dispatchEvent(new Event("pagehide"));
          }, boundary);
        const reply = page.waitForResponse((r) => r.url().endsWith(importPath));
        release();
        await reply;
        const p = await manager(page, kind);
        if (boundary === "edit")
          await expect(
            p.getByLabel(proposalLabel(kind), { exact: true }),
          ).toHaveValue(kind === "name" ? "later proposal" : "900e-");
        else
          await expect(
            p.getByLabel("Captured native application", { exact: true }),
          ).toHaveCount(0);
        await expect(
          p.getByRole("button", {
            name: "Import local identity draft",
            exact: true,
          }),
        ).toBeEnabled();
        await expect(
          p.getByLabel("Reviewed native application transfer", { exact: true }),
        ).toHaveCount(0);
        expect(calls).toEqual([]);
      } finally {
        release();
      }
    });
  for (const changed of [
    "file hash",
    "proposal",
    "source proof",
    "authority",
  ] as const)
    test(`${kind} substituted ${changed} response is refused`, async ({
      page,
      request,
      nativeScheduleWriteServer,
    }) => {
      const { headers, calls } = await setup(
          page,
          request,
          nativeScheduleWriteServer.directory,
          kind,
        ),
        file = await saved(page, kind);
      const actual = await request.post(importPath, {
        headers,
        multipart: {
          file: {
            name: file.name,
            mimeType: "application/json",
            buffer: file.bytes,
          },
        },
      });
      expect(actual.ok(), await actual.text()).toBe(true);
      const body = await actual.json();
      await discard(page, kind);
      if (changed === "file hash") body.file_sha256 = "a".repeat(64);
      else if (changed === "proposal") body.document.new_name = "substituted";
      else if (changed === "source proof") body.source_evidence_text += " ";
      else body.field_authority = true;
      await page.route("**" + importPath, (route) =>
        route.fulfill({ json: body }),
      );
      await restore(page, kind, file);
      await expect(panel(page, kind).getByRole("alert")).toContainText(
        "differs",
      );
      await expect(
        panel(page, kind).getByLabel("Captured native application", {
          exact: true,
        }),
      ).toHaveCount(0);
      expect(calls).toEqual([]);
    });
}

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

test("authored UI target ABA retires raw import and preserves a foreign backup without field access", async ({
  page,
  request,
  nativeScheduleWriteServer,
}) => {
  const data = seed(nativeScheduleWriteServer.directory, "name"),
    headers = await auth(request);
  expect(
    (await request.post("/api/bacnet/disconnect", { headers, data: {} })).ok(),
  ).toBe(true);
  // Explicitly authored HTTP identities exercise UI context ownership only.
  // The real backend interface remains closed throughout this test.
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
  const calls: string[] = [];
  page.on("request", (r) => {
    if (
      r.method() === "POST" &&
      /\/native-application\/(capture|preview|apply|readback)$/.test(r.url())
    )
      calls.push(r.url());
  });
  await context(page, 0, true);
  await load(page, "name", data.request.capture_id);
  await panel(page, "name")
    .getByLabel("New controller name", { exact: true })
    .fill("  retained local text  ");
  const file = await saved(page, "name");
  await discard(page, "name");
  const actual = await request.post(importPath, {
    headers,
    multipart: {
      file: {
        name: file.name,
        mimeType: "application/json",
        buffer: file.bytes,
      },
    },
  });
  expect(actual.ok(), await actual.text()).toBe(true);
  const body = await actual.body();
  let release!: () => void, reached!: () => void;
  const held = new Promise<void>((r) => (release = r)),
    seen = new Promise<void>((r) => (reached = r));
  await page.route("**" + importPath, async (route) => {
    reached();
    await held;
    await route.fulfill({ status: 200, contentType: "application/json", body });
  });
  try {
    await restore(page, "name", file);
    await seen;
    await context(page, 1);
    await context(page, 0);
    const reply = page.waitForResponse((r) => r.url().endsWith(importPath));
    release();
    await reply;
    await expect(
      panel(page, "name").getByLabel("Captured native application", {
        exact: true,
      }),
    ).toHaveCount(0);
    await page.unroute("**" + importPath);
    await restore(page, "name", file);
    await expect(
      panel(page, "name").getByLabel("New controller name", { exact: true }),
    ).toHaveValue("  retained local text  ");
    await expect(
      panel(page, "name").getByRole("button", {
        name: "Review name change",
        exact: true,
      }),
    ).toBeDisabled();
    await expect(
      page.getByLabel("Working context", { exact: true }),
    ).toContainText("device,6000");
    expect(
      (await (await request.get("/api/session")).json()).field_network_open,
    ).toBe(false);
    expect(calls).toEqual([]);
  } finally {
    release();
  }
});
