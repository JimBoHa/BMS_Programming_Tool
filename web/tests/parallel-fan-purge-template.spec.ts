import {
  test,
  expect,
  simulationServerResponseJSON,
  simulationServerResponseText,
  type Page,
  type Locator,
} from "./simulationFixture";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
const root = fileURLToPath(new URL("../..", import.meta.url)),
  python = path.join(root, ".venv/bin/python"),
  base = "/api/activities/templates/parallel-fan-purge",
  sha = (b: Buffer) => createHash("sha256").update(b).digest("hex");
function py(code: string, input: Buffer | string = "") {
  return execFileSync(python, ["-c", code], {
    cwd: root,
    env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
    input,
  });
}
async function retain(name: string, body: Buffer | string) {
  await test.info().attach(name, { body, contentType: "application/json" });
}
const ports = [
  "heating_percent_command",
  "cooling_percent_command",
  "fan_on_threshold",
  "fan_off_threshold",
  "heating_purge_duration",
];
function seed(wired = false, scan = 1, duration = 3) {
  return py(
    `import sys,json
from bms_tool.models import Program,Node,Edge
from bms_tool.parallel_fan_purge_template import Choices,ImportRequest,PROFILE_SHA,definition,import_reviewed
from bms_tool.activities import instantiate
v=json.load(sys.stdin);c=Choices(scan_seconds=v['scan'],heating_purge_duration_default=float(v['duration']));ports=('heating_percent_command','cooling_percent_command','fan_on_threshold','fan_off_threshold','heating_purge_duration')
p=Program(id='parallel-purge-browser',name='Parallel purge source',scan_seconds=v['scan'],metadata={'macros':{'version':2,'definitions':[]},'opaque_numbers':{'large':9007199254740993,'signed':-0.0,'integer':0,'floating':0.0,'tiny':1e-6}},nodes=[Node(id=n,kind='Input',unit='s'if n=='heating_purge_duration'else'%',params={'default':getattr(c,n+'_default')},x=0,y=i*200)for i,n in enumerate(ports)]+[Node(id='fan0',kind='Output',value_type='boolean',x=1000,y=100),Node(id='valid0',kind='Output',value_type='boolean',x=1000,y=650)])
if v['wired']:
 p=import_reviewed(ImportRequest(program=p,choices=c,profile_sha256=PROFILE_SHA,reviewed_parent_sha256=p.digest()));p=instantiate(p,definition(c).id,x=400,y=250);i=p.nodes[-1].id;p.edges=[Edge(id=n,source=n,target=i,target_port=n)for n in ports]+[Edge(id='fanout',source=i,source_port='fan_request',target='fan0'),Edge(id='validout',source=i,source_port='request_configuration_valid',target='valid0')]
print(p.model_dump_json())`,
    JSON.stringify({ wired, scan, duration }),
  );
}
async function load(page: Page, body: Buffer) {
  await page.getByRole("button", { name: "Program", exact: true }).click();
  await page.locator('input[type=file][accept*=".st"]').setInputFiles({
    name: "parallel-purge-source.json",
    mimeType: "application/json",
    buffer: body,
  });
  await expect(page.locator(".toast")).toContainText(
    "Imported as a new local project",
  );
}
async function macros(page: Page) {
  await page.getByRole("button", { name: "Macros", exact: true }).click();
  const card = page.getByRole("region", {
    name: "Parallel fan purge template",
    exact: true,
  });
  await expect
    .poll(
      async () =>
        (await card
          .getByRole("button", {
            name: "Preview parallel fan purge",
            exact: true,
          })
          .isEnabled()) || (await card.getByRole("alert").isVisible()),
    )
    .toBe(true);
  return card;
}
async function open(page: Page, wired = false, scan = 1, duration = 3) {
  await page.goto("/");
  await load(page, seed(wired, scan, duration));
  return macros(page);
}
async function capture(
  page: Page,
  endpoint: string,
  action: () => Promise<unknown>,
  status = 200,
) {
  let raw: Buffer | undefined;
  await page.route(
    "**" + endpoint,
    async (route) => {
      const r = await route.fetch({ maxRetries: 0, maxRedirects: 0 });
      raw = await r.body();
      await retain(
        "original-" + endpoint.split("/").at(-1) + "-request",
        route.request().postDataBuffer()!,
      );
      await retain("original-" + endpoint.split("/").at(-1) + "-response", raw);
      await retain("original-delivery-headers", JSON.stringify(r.headers()));
      expect(r.status()).toBe(status);
      await route.fulfill({ response: r, body: raw });
    },
    { times: 1 },
  );
  await action();
  await expect.poll(() => raw !== undefined).toBe(true);
  return raw!;
}
const value = (raw: Buffer) => {
  const v = JSON.parse(raw.toString());
  return v.source_json ? JSON.parse(v.source_json) : v;
};
async function preview(page: Page, card: Locator) {
  const raw = await capture(page, base + "/preview", () =>
    card
      .getByRole("button", { name: "Preview parallel fan purge", exact: true })
      .click(),
  );
  await expect(
    card.getByRole("region", {
      name: "Parallel fan purge preview",
      exact: true,
    }),
  ).toBeVisible();
  return { raw, data: value(raw) };
}
async function exported(page: Page) {
  await page.getByRole("button", { name: "Program", exact: true }).click();
  await page.getByLabel("Export format", { exact: true }).selectOption("json");
  const pending = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export", exact: true }).click();
  const raw = readFileSync((await (await pending).path())!);
  await retain("original-editor", raw);
  return raw;
}
async function step(page: Page) {
  await page.getByRole("button", { name: "Program", exact: true }).click();
  const pending = page.waitForResponse(
    (r) =>
      new URL(r.url()).pathname === "/api/simulation/step" &&
      r.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Step simulation", exact: true })
    .click();
  const r = await pending;
  expect(r.status()).toBe(200);
  await retain("original-parallel-purge-scan", simulationServerResponseText(r));
  return simulationServerResponseJSON(r);
}
async function imported(page: Page, card: Locator) {
  return capture(page, base + "/import", () =>
    card
      .getByRole("button", {
        name: "Import reviewed parallel fan purge definition",
        exact: true,
      })
      .click(),
  );
}
async function download(page: Page, card: Locator, kind: "review" | "bundle") {
  let raw: Buffer | undefined,
    header = "";
  await page.route(
    "**" + base + "/export",
    async (route) => {
      const r = await route.fetch({ maxRetries: 0, maxRedirects: 0 });
      expect(r.status()).toBe(200);
      raw = await r.body();
      header = r.headers()["x-file-sha256"];
      await retain(
        "original-export-request",
        route.request().postDataBuffer()!,
      );
      await retain("original-export-headers", JSON.stringify(r.headers()));
      await route.fulfill({ response: r, body: raw });
    },
    { times: 1 },
  );
  const pending = page.waitForEvent("download");
  await card
    .getByRole("button", {
      name:
        kind === "review"
          ? "Export original parallel fan purge review JSON"
          : "Export original parallel fan purge activity bundle",
      exact: true,
    })
    .click();
  const bytes = readFileSync((await (await pending).path())!);
  expect(bytes).toEqual(raw);
  expect(sha(bytes)).toBe(header);
  await retain("original-" + kind + "-upstream", raw!);
  await retain("original-" + kind + "-download", bytes);
  return bytes;
}
async function held(page: Page, endpoint: string) {
  let ready!: () => void,
    release!: () => void,
    done!: () => void,
    count = 0;
  const started = new Promise<void>((r) => (ready = r)),
    gate = new Promise<void>((r) => (release = r)),
    finished = new Promise<void>((r) => (done = r)),
    pattern = "**" + endpoint;
  const handler = async (route: import("@playwright/test").Route) => {
    if (++count !== 1) {
      await route.abort("failed");
      throw Error("Held parallel purge owner received another browser request");
    }
    try {
      const r = await route.fetch({ maxRetries: 0, maxRedirects: 0 }),
        raw = await r.body();
      expect(r.status()).toBe(200);
      await retain("held-original-request", route.request().postDataBuffer()!);
      await retain("held-original-response", raw);
      ready();
      await gate;
      await route.fulfill({ response: r, body: raw });
    } finally {
      done();
    }
  };
  await page.route(pattern, handler);
  return {
    started,
    async release() {
      release();
      try {
        await finished;
        expect(count).toBe(1);
      } finally {
        await page.unroute(pattern, handler);
      }
    },
  };
}
async function wire(page: Page, source: Locator, target: Locator) {
  const a = await source.boundingBox(),
    b = await target.boundingBox();
  expect(a).not.toBeNull();
  expect(b).not.toBeNull();
  await page.mouse.move(a!.x + a!.width / 2, a!.y + a!.height / 2);
  await page.mouse.down();
  await page.mouse.move(b!.x + b!.width / 2, b!.y + b!.height / 2, {
    steps: 20,
  });
  await page.mouse.up();
}
async function placed(page: Page, id: string, graphical = false) {
  const lib = page.getByRole("region", {
    name: "Reusable multi-output activities",
    exact: true,
  });
  await expect(lib.locator(".activity-definition")).toHaveCount(1);
  const raw = await capture(page, "/api/activities/instantiate", () =>
      lib
        .getByRole("button", {
          name: "Add activity instance to program",
          exact: true,
        })
        .click(),
    ),
    p = value(raw),
    instance = p.nodes.find((n: any) => n.kind === "Activity").id;
  expect(p.metadata.macros.definitions[0].id).toBe(id);
  if (graphical) {
    await page.getByRole("button", { name: "Program", exact: true }).click();
    const actor = page.locator(`.react-flow__node[data-id="${instance}"]`);
    for (const port of ports)
      await wire(
        page,
        page.locator(
          `.react-flow__node[data-id="${port}"] [data-handleid="out"]`,
        ),
        actor.locator(`[data-handleid="${port}"]`),
      );
    await wire(
      page,
      actor.locator('[data-handleid="fan_request"]'),
      page.locator('.react-flow__node[data-id="fan0"] [data-handleid="in"]'),
    );
    await wire(
      page,
      actor.locator('[data-handleid="request_configuration_valid"]'),
      page.locator('.react-flow__node[data-id="valid0"] [data-handleid="in"]'),
    );
    await expect(page.locator(".react-flow__edge")).toHaveCount(7);
  } else {
    const wired = py(
      `import sys,json
from bms_tool.models import Program,Edge
v=json.load(sys.stdin);p=Program.model_validate(json.loads(v['source_json']));i=next(n.id for n in p.nodes if n.kind=='Activity');p.edges=[Edge(id=n,source=n,target=i,target_port=n)for n in('heating_percent_command','cooling_percent_command','fan_on_threshold','fan_off_threshold','heating_purge_duration')]+[Edge(id='fanout',source=i,source_port='fan_request',target='fan0'),Edge(id='validout',source=i,source_port='request_configuration_valid',target='valid0')];print(p.model_dump_json())`,
      raw,
    );
    await load(page, wired);
  }
  return instance;
}
async function set(page: Page, id: string, n: string) {
  await page.getByLabel("Simulate " + id, { exact: true }).fill(n);
}

for (const [scan, duration] of [
  [1, 4],
  [2, 3.5],
] as const)
  test(`original reviewed import wire simulate save and interchange h${scan} duration${duration}`, async ({
    page,
  }) => {
    let saves = 0,
      dialogs = 0;
    page.on("request", (r) => {
      if (
        new URL(r.url()).pathname === "/api/projects" &&
        r.method() === "POST"
      )
        saves++;
    });
    page.on("dialog", (d) => {
      dialogs++;
      void d.dismiss();
    });
    const card = await open(page, false, scan, duration);
    await card
      .getByLabel("Parallel purge Declared scan seconds", { exact: true })
      .fill(String(scan));
    await card
      .getByLabel("Parallel purge Heating purge seconds default", {
        exact: true,
      })
      .fill(String(duration));
    await card
      .getByLabel("Parallel purge Heating command default", { exact: true })
      .fill("-0");
    await card
      .getByLabel("Parallel purge Fan-off threshold default", { exact: true })
      .fill("1e-6");
    const p = await preview(page, card);
    expect(p.data.program.nodes).toHaveLength(51);
    expect(p.data.program.edges).toHaveLength(73);
    expect(p.data.parent_reference.scan_seconds).toBe(scan);
    expect(p.data.program.scan_seconds).toBe(scan);
    expect(Object.is(p.data.choices.heating_percent_command_default, -0)).toBe(
      true,
    );
    const pending = page.waitForEvent("download");
    await card
      .getByRole("button", {
        name: "Download original parallel fan purge preview response",
        exact: true,
      })
      .click();
    expect(readFileSync((await (await pending).path())!)).toEqual(p.raw);
    await download(page, card, "review");
    await download(page, card, "bundle");
    const parent = await imported(page, card);
    expect(value(parent).nodes.some((n: any) => n.kind === "Activity")).toBe(
      false,
    );
    expect(saves).toBe(0);
    expect(dialogs).toBe(0);
    await preview(page, card);
    const again = await imported(page, card);
    expect(value(again).metadata.macros.definitions).toHaveLength(1);
    await placed(page, p.data.definition_id, scan === 1);
    await page.getByRole("button", { name: "Program", exact: true }).click();
    await set(page, "heating_percent_command", "10");
    expect((await step(page)).last.outputs).toEqual({
      fan0: true,
      valid0: true,
    });
    await set(page, "heating_percent_command", "0");
    for (let t = scan; t < duration; t += scan)
      expect((await step(page)).last.outputs).toEqual({
        fan0: true,
        valid0: true,
      });
    expect((await step(page)).last.outputs).toEqual({
      fan0: false,
      valid0: true,
    });
    const source = await exported(page),
      files: Record<string, string> = {};
    for (const format of ["json", "st", "plcopen", "graphml"]) {
      await page
        .getByLabel("Export format", { exact: true })
        .selectOption(format);
      const waiting = page.waitForEvent("download");
      await page.getByRole("button", { name: "Export", exact: true }).click();
      const f = await waiting,
        raw = readFileSync((await f.path())!);
      files[f.suggestedFilename()] = raw.toString("base64");
      await retain("original-parallel-purge-interchange-" + format, raw);
    }
    await retain(
      "independent-source-interchange",
      py(
        `import sys,json,base64,math
from bms_tool.models import Program
from bms_tool.formats import import_program
v=json.load(sys.stdin);p=Program.model_validate_json(v['program']);assert all(import_program(base64.b64decode(b),n).digest()==p.digest()for n,b in v['files'].items());g=p.metadata['macros']['definitions'][0]['program'];assert math.copysign(1,g['metadata']['parallel_fan_purge_template']['choices']['heating_percent_command_default'])<0;assert math.copysign(1,next(n for n in g['nodes']if n['id']=='heating_percent_command')['params']['default'])<0;assert next(n for n in g['nodes']if n['id']=='fan_off_threshold')['params']['default']==1e-6;assert p.metadata['opaque_numbers']['large']==9007199254740993 and type(p.metadata['opaque_numbers']['integer'])is int and type(p.metadata['opaque_numbers']['floating'])is float;print(p.digest())`,
        JSON.stringify({ program: source.toString(), files }),
      ),
    );
    const saved = await capture(page, "/api/projects", () =>
        page
          .getByRole("button", { name: "Save revision", exact: true })
          .click(),
      ),
      data = value(saved);
    expect(data.revision).toBe(1);
    const original = await page.request.get("/api/projects/" + data.id);
    expect(original.status()).toBe(200);
    await retain("original-parallel-purge-saved-http", await original.body());
    expect(saves).toBe(1);
    expect(
      (await (await page.request.get("/api/session")).json())
        .field_network_open,
    ).toBe(false);
  });

test("raw in-band heating resets purge while cooling in-band retains and new cooling starts", async ({
  page,
}) => {
  await open(page, true);
  await page.getByRole("button", { name: "Program", exact: true }).click();
  await set(page, "heating_percent_command", "10");
  expect((await step(page)).last.outputs.fan0).toBe(true);
  await set(page, "heating_percent_command", "0");
  expect((await step(page)).last.outputs.fan0).toBe(true);
  await set(page, "heating_percent_command", "1");
  expect((await step(page)).last.outputs.fan0).toBe(true);
  await set(page, "heating_percent_command", "0");
  await set(page, "cooling_percent_command", "1");
  for (let i = 0; i < 3; i++)
    expect((await step(page)).last.outputs.fan0).toBe(true);
  await set(page, "cooling_percent_command", "0");
  expect((await step(page)).last.outputs.fan0).toBe(false);
  await set(page, "cooling_percent_command", "6");
  expect((await step(page)).last.outputs.fan0).toBe(true);
  await set(page, "cooling_percent_command", "0");
  await set(page, "heating_purge_duration", "0");
  expect((await step(page)).last.outputs.fan0).toBe(false);
});

test("live duration changes preserve elapsed and invalid good configuration resets trusted interval", async ({
  page,
}) => {
  await open(page, true);
  await page.getByRole("button", { name: "Program", exact: true }).click();
  await set(page, "fan_off_threshold", "0");
  expect((await step(page)).last.outputs).toEqual({
    fan0: false,
    valid0: false,
  });
  await set(page, "fan_off_threshold", "0.1");
  await set(page, "heating_percent_command", "10");
  expect((await step(page)).last.outputs.fan0).toBe(true);
  await set(page, "heating_percent_command", "0");
  await set(page, "heating_purge_duration", "4");
  expect((await step(page)).last.outputs.fan0).toBe(true);
  await set(page, "heating_purge_duration", "6");
  expect((await step(page)).last.outputs.fan0).toBe(true);
  await set(page, "heating_purge_duration", "2");
  expect((await step(page)).last.outputs.fan0).toBe(false);
  await set(page, "heating_percent_command", "10");
  await step(page);
  await set(page, "heating_percent_command", "0");
  await set(page, "heating_purge_duration", "3");
  await step(page);
  await set(page, "fan_on_threshold", "100");
  expect((await step(page)).last.outputs).toEqual({
    fan0: true,
    valid0: false,
  });
  await set(page, "fan_on_threshold", "5");
  expect((await step(page)).last.outputs).toEqual({ fan0: true, valid0: true });
  expect((await step(page)).last.outputs.fan0).toBe(true);
  expect((await step(page)).last.outputs.fan0).toBe(false);
});

test("quality rollback and terminal fan force preserve internal request and elapsed memory", async ({
  page,
}) => {
  await open(page, true, 1, 4);
  await page.getByRole("button", { name: "Program", exact: true }).click();
  await set(page, "heating_percent_command", "10");
  await step(page);
  await set(page, "heating_percent_command", "0");
  await step(page);
  const source = await exported(page),
    id = JSON.parse(source.toString()).nodes.find(
      (n: any) => n.kind === "Activity",
    ).id;
  await page.locator(`.react-flow__node[data-id="${id}"]`).click();
  const port = page.getByRole("region", {
    name: "Activity output fan_request",
    exact: true,
  });
  await port
    .getByLabel("Simulation force value", { exact: true })
    .selectOption("false");
  await port
    .getByRole("button", { name: "Hold simulation value", exact: true })
    .click();
  const forced = await step(page);
  expect(forced.last.outputs).toEqual({ fan0: false, valid0: true });
  await page
    .getByLabel("Quality heating_percent_command", { exact: true })
    .selectOption("open-circuit");
  expect((await step(page)).snapshot).toEqual(forced.snapshot);
  await port
    .getByRole("button", { name: "Release simulation force", exact: true })
    .click();
  await page
    .getByLabel("Quality heating_percent_command", { exact: true })
    .selectOption("good");
  expect((await step(page)).last.outputs.fan0).toBe(true);
  expect((await step(page)).last.outputs.fan0).toBe(false);
});

test("strict threshold boundaries command duration and mismatched clock refuse before preview request", async ({
  page,
}) => {
  const card = await open(page);
  let calls = 0;
  page.on("request", (r) => {
    if (new URL(r.url()).pathname === base + "/preview") calls++;
  });
  const run = async () =>
    card
      .getByRole("button", { name: "Preview parallel fan purge", exact: true })
      .click();
  await card
    .getByLabel("Parallel purge Fan-off threshold default", { exact: true })
    .fill("0");
  await run();
  await expect(card.getByRole("alert")).toContainText("0 < off < on < 100");
  await card
    .getByLabel("Parallel purge Fan-off threshold default", { exact: true })
    .fill("0.1");
  await card
    .getByLabel("Parallel purge Fan-on threshold default", { exact: true })
    .fill("100");
  await run();
  await expect(card.getByRole("alert")).toContainText("0 < off < on < 100");
  await card
    .getByLabel("Parallel purge Fan-on threshold default", { exact: true })
    .fill("5");
  await card
    .getByLabel("Parallel purge Heating command default", { exact: true })
    .fill("101");
  await run();
  await expect(card.getByRole("alert")).toContainText("0–100%");
  await card
    .getByLabel("Parallel purge Heating command default", { exact: true })
    .fill("0");
  await card
    .getByLabel("Parallel purge Heating purge seconds default", { exact: true })
    .fill("86401");
  await run();
  await expect(card.getByRole("alert")).toContainText("0–86400");
  await card
    .getByLabel("Parallel purge Heating purge seconds default", { exact: true })
    .fill("3.5");
  await card
    .getByLabel("Parallel purge Declared scan seconds", { exact: true })
    .fill("2");
  await run();
  await expect(card.getByRole("alert")).toContainText("parent Program scan");
  expect(calls).toBe(0);
});

for (const kind of ["preview-discard", "import-ABA", "export-unmount"])
  test(`held ${kind} cannot adopt stale purge response`, async ({ page }) => {
    const card = await open(page);
    if (kind !== "preview-discard") await preview(page, card);
    const endpoint = kind.startsWith("preview")
        ? "/preview"
        : kind.startsWith("import")
          ? "/import"
          : "/export",
      gate = await held(page, base + endpoint);
    let downloads = 0;
    page.on("download", () => downloads++);
    try {
      await card
        .getByRole("button", {
          name: kind.startsWith("preview")
            ? "Preview parallel fan purge"
            : kind.startsWith("import")
              ? "Import reviewed parallel fan purge definition"
              : "Export original parallel fan purge review JSON",
          exact: true,
        })
        .click();
      await gate.started;
      if (kind === "preview-discard") {
        await card
          .getByRole("button", {
            name: "Discard pending parallel fan purge response",
            exact: true,
          })
          .click();
        await card
          .getByLabel("Parallel purge Heating purge seconds default", {
            exact: true,
          })
          .fill("30");
      } else if (kind === "import-ABA") {
        await page.getByLabel("Program name", { exact: true }).fill("B source");
        await page
          .getByLabel("Program name", { exact: true })
          .fill("Parallel purge source");
      } else
        await page
          .getByRole("button", { name: "Program", exact: true })
          .click();
    } finally {
      await gate.release();
    }
    expect(downloads).toBe(0);
    if (kind === "import-ABA")
      expect(
        JSON.parse((await exported(page)).toString()).metadata.macros
          .definitions,
      ).toHaveLength(0);
  });

test("unknown profile then forged Program descriptor cannot establish import authority", async ({
  page,
}) => {
  await page.route(
    "**" + base + "/catalog",
    async (route) => {
      const r = await route.fetch({ maxRetries: 0, maxRedirects: 0 }),
        raw = await r.body(),
        data = JSON.parse(raw.toString());
      await retain("original-catalog-before-forgery", raw);
      data.profile_sha256 = "0".repeat(64);
      await route.fulfill({ response: r, json: data });
    },
    { times: 1 },
  );
  const card = await open(page);
  await expect(card.getByRole("alert")).toBeVisible();
  await expect(
    card.getByRole("button", {
      name: "Preview parallel fan purge",
      exact: true,
    }),
  ).toBeDisabled();
  await card
    .getByRole("button", {
      name: "Reload parallel fan purge criteria",
      exact: true,
    })
    .click();
  await expect(
    card.getByRole("button", {
      name: "Preview parallel fan purge",
      exact: true,
    }),
  ).toBeEnabled();
  await page.route(
    "**" + base + "/preview",
    async (route) => {
      const r = await route.fetch({ maxRetries: 0, maxRedirects: 0 }),
        raw = await r.body(),
        data = JSON.parse(raw.toString());
      await retain("original-preview-before-forgery", raw);
      data.programs[1].canonical_sha256 = "0".repeat(64);
      await route.fulfill({ response: r, json: data });
    },
    { times: 1 },
  );
  await card
    .getByRole("button", { name: "Preview parallel fan purge", exact: true })
    .click();
  await expect(card.getByRole("alert")).toBeVisible();
  await expect(
    card.getByRole("button", {
      name: "Import reviewed parallel fan purge definition",
      exact: true,
    }),
  ).toHaveCount(0);
});

test("wrong original export digest refuses download and preserves current review", async ({
  page,
}) => {
  const card = await open(page);
  await preview(page, card);
  let downloads = 0;
  page.on("download", () => downloads++);
  await page.route(
    "**" + base + "/export",
    async (route) => {
      const r = await route.fetch({ maxRetries: 0, maxRedirects: 0 }),
        raw = await r.body();
      await retain("original-export-before-header-forgery", raw);
      await route.fulfill({
        response: r,
        body: raw,
        headers: { ...r.headers(), "x-file-sha256": "0".repeat(64) },
      });
    },
    { times: 1 },
  );
  await card
    .getByRole("button", {
      name: "Export original parallel fan purge activity bundle",
      exact: true,
    })
    .click();
  await expect(card.getByRole("alert")).toContainText("byte-digest");
  expect(downloads).toBe(0);
  await expect(
    card.getByRole("region", {
      name: "Parallel fan purge preview",
      exact: true,
    }),
  ).toBeVisible();
});

test("failed current parent criteria retires purge review and fresh recovery restores preview", async ({
  page,
}) => {
  const card = await open(page);
  await preview(page, card);
  await page.route(
    "**/api/activities/catalog",
    async (route) => {
      const r = await route.fetch({ maxRetries: 0, maxRedirects: 0 });
      await retain("original-parent-catalog-before-503", await r.body());
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "deliberate parent criteria failure" }),
      });
    },
    { times: 1 },
  );
  const lib = page.getByRole("region", {
    name: "Reusable multi-output activities",
    exact: true,
  });
  await lib
    .getByRole("button", { name: "Reload activity criteria", exact: true })
    .click();
  await expect(
    card.getByRole("region", {
      name: "Parallel fan purge preview",
      exact: true,
    }),
  ).toHaveCount(0);
  await expect(
    card.getByRole("button", {
      name: "Preview parallel fan purge",
      exact: true,
    }),
  ).toBeDisabled();
  await lib
    .getByRole("button", { name: "Reload activity criteria", exact: true })
    .click();
  await expect(
    card.getByRole("button", {
      name: "Preview parallel fan purge",
      exact: true,
    }),
  ).toBeEnabled();
  await preview(page, card);
});
