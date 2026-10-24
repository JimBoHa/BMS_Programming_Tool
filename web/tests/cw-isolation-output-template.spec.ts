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
  base = "/api/activities/templates/cw-iso-output",
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
function seed(wired = false) {
  return py(
    `import sys
from tests.test_cw_isolation_output_template import parent,caller
from bms_tool.models import Node
p=caller()if sys.stdin.read()=='wired'else parent()
p.name='CW template source';p.id='cw-browser'
if not any(n.kind=='Output'for n in p.nodes):p.nodes.extend([Node(id='on0',kind='Output',value_type='boolean'),Node(id='effective0',kind='Output',unit='%')])
p.metadata['opaque_numbers']={'large':9007199254740993,'signed':-0.0,'integer':0,'floating':0.0,'tiny':1e-6}
for n in p.nodes:
 n.x,n.y={'enable':(0,70),'requested':(0,350),'on0':(850,70),'effective0':(850,420)}.get(n.id,(350,170))
print(p.model_dump_json())`,
    wired ? "wired" : "plain",
  );
}
async function load(page: Page, body: Buffer) {
  await page.getByRole("button", { name: "Program", exact: true }).click();
  await page.locator('input[type=file][accept*=".st"]').setInputFiles({
    name: "cw-source.json",
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
    name: "CW isolation output template",
    exact: true,
  });
  await expect
    .poll(
      async () =>
        (await card
          .getByRole("button", {
            name: "Preview CW isolation output",
            exact: true,
          })
          .isEnabled()) || (await card.getByRole("alert").isVisible()),
    )
    .toBe(true);
  return card;
}
async function open(page: Page, wired = false) {
  await page.goto("/");
  await load(page, seed(wired));
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
async function preview(
  page: Page,
  card: Locator,
  minimum = "20",
  stroke = 4,
  scan = 1,
) {
  await card
    .getByLabel("CW minimum target command", { exact: true })
    .fill(minimum);
  await card
    .getByLabel("CW stroke seconds", { exact: true })
    .fill(String(stroke));
  await card.getByLabel("CW scan seconds", { exact: true }).fill(String(scan));
  const raw = await capture(page, base + "/preview", () =>
    card
      .getByRole("button", { name: "Preview CW isolation output", exact: true })
      .click(),
  );
  await expect(
    card.getByRole("region", {
      name: "CW isolation output preview",
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
  await retain("original-cw-scan", simulationServerResponseText(r));
  return simulationServerResponseJSON(r);
}
async function imported(page: Page, card: Locator) {
  page.once("dialog", (d) => d.accept());
  return capture(page, base + "/import", () =>
    card
      .getByRole("button", {
        name: "Import reviewed CW isolation definition",
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
          ? "Export original CW isolation review JSON"
          : "Export original CW isolation activity bundle",
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
      throw Error("Held CW owner received another browser request");
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
  );
  const p = value(raw),
    instance = p.nodes.find((n: any) => n.kind === "Activity").id;
  expect(p.metadata.macros.definitions[0].id).toBe(id);
  if (graphical) {
    await page.getByRole("button", { name: "Program", exact: true }).click();
    const actor = page.locator(`.react-flow__node[data-id="${instance}"]`);
    await wire(
      page,
      page.locator('.react-flow__node[data-id="enable"] [data-handleid="out"]'),
      actor.locator('[data-handleid="device_enable"]'),
    );
    await wire(
      page,
      page.locator(
        '.react-flow__node[data-id="requested"] [data-handleid="out"]',
      ),
      actor.locator('[data-handleid="command"]'),
    );
    await wire(
      page,
      actor.locator('[data-handleid="device_on_off"]'),
      page.locator('.react-flow__node[data-id="on0"] [data-handleid="in"]'),
    );
    await wire(
      page,
      actor.locator('[data-handleid="effective_command"]'),
      page.locator(
        '.react-flow__node[data-id="effective0"] [data-handleid="in"]',
      ),
    );
    await expect(page.locator(".react-flow__edge")).toHaveCount(4);
  } else {
    const wired = py(
      "import sys,json;from bms_tool.models import Program,Edge;e=json.load(sys.stdin);p=Program.model_validate(json.loads(e['source_json']));i=next(n.id for n in p.nodes if n.kind=='Activity');p.edges=[Edge(id='enable',source='enable',target=i,target_port='device_enable'),Edge(id='command',source='requested',target=i,target_port='command'),Edge(id='on',source=i,source_port='device_on_off',target='on0'),Edge(id='percent',source=i,source_port='effective_command',target='effective0')];print(p.model_dump_json())",
      raw,
    );
    await load(page, wired);
  }
  return instance;
}

for (const [minimum, stroke, scan] of [
  ["20", 4, 1],
  ["-0", 60, 1],
  ["12.5", 6, 3],
] as const)
  test(`review import wire simulate and preserve original artifacts m${minimum} T${stroke} h${scan}`, async ({
    page,
  }) => {
    let saves = 0;
    page.on("request", (r) => {
      if (
        new URL(r.url()).pathname === "/api/projects" &&
        r.method() === "POST"
      )
        saves++;
    });
    let card = await open(page);
    if (scan !== 1) {
      await page.getByRole("button", { name: "Program", exact: true }).click();
      const next = py(
        "import sys;from bms_tool.models import Program;p=Program.model_validate_json(sys.stdin.read());p.scan_seconds=3;print(p.model_dump_json())",
        seed(),
      );
      await load(page, next);
      card = await macros(page);
    }
    const p = await preview(page, card, minimum, stroke, scan);
    expect(p.data.program.nodes).toHaveLength(13);
    expect(p.data.program.edges).toHaveLength(14);
    expect(p.data.outputs.map((x: any) => x.id)).toEqual([
      "device_on_off",
      "effective_command",
    ]);
    const pending = page.waitForEvent("download");
    await card
      .getByRole("button", {
        name: "Download original CW isolation preview response",
        exact: true,
      })
      .click();
    expect(readFileSync((await (await pending).path())!)).toEqual(p.raw);
    const review = await download(page, card, "review"),
      bundle = await download(page, card, "bundle");
    const parent = await imported(page, card);
    expect(value(parent).nodes.some((n: any) => n.kind === "Activity")).toBe(
      false,
    );
    expect(saves).toBe(0);
    await placed(page, p.data.definition_id, minimum === "20");
    await page.getByLabel("Simulate enable", { exact: true }).check();
    await page.getByLabel("Simulate requested", { exact: true }).fill("100");
    const first = await step(page);
    expect(first.last.outputs).toEqual({
      on0: true,
      effective0: (100 * scan) / stroke,
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
      await retain("original-cw-interchange-" + format, raw);
    }
    const checked = py(
      "import sys,json,base64,math;from bms_tool.models import Program;from bms_tool.formats import import_program;v=json.load(sys.stdin);p=Program.model_validate_json(v['program']);assert all(import_program(base64.b64decode(b),n).digest()==p.digest()for n,b in v['files'].items());m=p.metadata['macros']['definitions'][0]['program']['metadata']['cw_isolation_output_template']['choices']['minimum_command'];assert math.copysign(1,m)==(-1 if v['negative']else 1);assert p.metadata['opaque_numbers']['large']==9007199254740993;assert type(p.metadata['opaque_numbers']['integer'])is int and type(p.metadata['opaque_numbers']['floating'])is float;print(p.digest())",
      JSON.stringify({
        program: source.toString(),
        files,
        negative: minimum === "-0",
      }),
    );
    await retain("independent-source-interchange", checked);
    if (minimum === "20") {
      const saved = await capture(page, "/api/projects", () =>
        page
          .getByRole("button", { name: "Save revision", exact: true })
          .click(),
      );
      const data = value(saved);
      expect(data.revision).toBe(1);
      const original = await page.request.get("/api/projects/" + data.id);
      expect(original.status()).toBe(200);
      await retain("original-cw-saved-http", await original.body());
      expect(saves).toBe(1);
    } else expect(saves).toBe(0);
    await retain("original-cw-reviewed-report", review);
    await retain("original-cw-reviewed-bundle", bundle);
    expect(
      (await (await page.request.get("/api/session")).json())
        .field_network_open,
    ).toBe(false);
  });

test("enabled up/down tracking, target floor, immediate disable and terminal output force preserve one q", async ({
  page,
}) => {
  await open(page, true);
  await page.getByRole("button", { name: "Program", exact: true }).click();
  await page.getByLabel("Simulate enable", { exact: true }).check();
  await page.getByLabel("Simulate requested", { exact: true }).fill("100");
  expect((await step(page)).last.outputs.effective0).toBe(25);
  expect((await step(page)).last.outputs.effective0).toBe(50);
  await page.getByLabel("Simulate requested", { exact: true }).fill("0");
  expect((await step(page)).last.outputs.effective0).toBe(25);
  expect((await step(page)).last.outputs.effective0).toBe(20);
  await page.getByLabel("Simulate enable", { exact: true }).uncheck();
  expect((await step(page)).last.outputs).toEqual({
    on0: false,
    effective0: 0,
  });
  await page.getByLabel("Simulate enable", { exact: true }).check();
  await page.getByLabel("Simulate requested", { exact: true }).fill("100");
  await step(page);
  const source = await exported(page);
  const id = JSON.parse(source.toString()).nodes.find(
    (n: any) => n.kind === "Activity",
  ).id;
  await page.locator(`.react-flow__node[data-id="${id}"]`).click();
  const port = page.getByRole("region", {
    name: "Activity output effective_command",
    exact: true,
  });
  await port.getByLabel("Simulation force value", { exact: true }).fill("91");
  await port
    .getByRole("button", { name: "Hold simulation value", exact: true })
    .click();
  expect((await step(page)).last.outputs.effective0).toBe(91);
  await port
    .getByRole("button", { name: "Release simulation force", exact: true })
    .click();
  expect((await step(page)).last.outputs.effective0).toBe(75);
});

test("bad command quality with false enable retains positive complete transaction then resumes", async ({
  page,
}) => {
  await open(page, true);
  await page.getByRole("button", { name: "Program", exact: true }).click();
  await page.getByLabel("Simulate enable", { exact: true }).check();
  await page.getByLabel("Simulate requested", { exact: true }).fill("100");
  const previous = await step(page);
  await page.getByLabel("Simulate enable", { exact: true }).uncheck();
  await page
    .getByLabel("Quality requested", { exact: true })
    .selectOption("open-circuit");
  const fault = await step(page);
  expect(fault.snapshot).toEqual(previous.snapshot);
  expect(fault.snapshot.outputs).toEqual({ on0: true, effective0: 25 });
  await page
    .getByLabel("Quality requested", { exact: true })
    .selectOption("good");
  expect((await step(page)).last.outputs).toEqual({
    on0: false,
    effective0: 0,
  });
});

test("invalid local alignment and parent clock choices refuse without preview or editor mutation", async ({
  page,
}) => {
  const card = await open(page);
  let requests = 0;
  page.on("request", (r) => {
    if (new URL(r.url()).pathname === base + "/preview") requests++;
  });
  await card.getByLabel("CW stroke seconds", { exact: true }).fill("5");
  await card.getByLabel("CW scan seconds", { exact: true }).fill("2");
  await card
    .getByRole("button", { name: "Preview CW isolation output", exact: true })
    .click();
  await expect(card.getByRole("alert")).toBeVisible();
  expect(requests).toBe(0);
  await card.getByLabel("CW stroke seconds", { exact: true }).fill("6");
  await card
    .getByRole("button", { name: "Preview CW isolation output", exact: true })
    .click();
  await expect(card.getByRole("alert")).toContainText("current parent");
  expect(requests).toBe(0);
});

for (const kind of [
  "preview-choices",
  "import-source",
  "import-discard",
  "export-unmount",
])
  test(`held ${kind} retires template adoption or download`, async ({
    page,
  }) => {
    const card = await open(page);
    if (!kind.startsWith("preview")) await preview(page, card);
    const endpoint = kind.startsWith("preview")
        ? "/preview"
        : kind.startsWith("import")
          ? "/import"
          : "/export",
      gate = await held(page, base + endpoint);
    let downloads = 0;
    page.on("download", () => downloads++);
    try {
      if (kind.startsWith("import")) page.once("dialog", (d) => d.accept());
      await card
        .getByRole("button", {
          name: kind.startsWith("preview")
            ? "Preview CW isolation output"
            : kind.startsWith("import")
              ? "Import reviewed CW isolation definition"
              : "Export original CW isolation review JSON",
          exact: true,
        })
        .click();
      await gate.started;
      if (kind === "preview-choices") {
        await card
          .getByRole("button", {
            name: "Discard pending CW isolation response",
            exact: true,
          })
          .click();
        await card
          .getByLabel("CW minimum target command", { exact: true })
          .fill("21");
      } else if (kind === "import-source")
        await page
          .getByLabel("Program name", { exact: true })
          .fill("Newer source");
      else if (kind === "import-discard")
        await card
          .getByRole("button", {
            name: "Discard pending CW isolation response",
            exact: true,
          })
          .click();
      else
        await page
          .getByRole("button", { name: "Program", exact: true })
          .click();
    } finally {
      await gate.release();
    }
    expect(downloads).toBe(0);
    if (kind.startsWith("import")) {
      const current = JSON.parse((await exported(page)).toString());
      expect(current.metadata.macros.definitions).toHaveLength(0);
    }
  });

test("unknown profile criteria refuse current template review", async ({
  page,
}) => {
  await page.route("**" + base + "/catalog", async (route) => {
    const r = await route.fetch({ maxRetries: 0, maxRedirects: 0 }),
      raw = await r.body(),
      data = JSON.parse(raw.toString());
    await retain("original-catalog-before-forgery", raw);
    data.profile_sha256 = "0".repeat(64);
    await route.fulfill({ response: r, json: data });
  });
  const card = await open(page);
  await expect(card.getByRole("alert")).toBeVisible();
  await expect(
    card.getByRole("button", {
      name: "Preview CW isolation output",
      exact: true,
    }),
  ).toBeDisabled();
});

test("forged Program descriptor refuses preview before definition import", async ({
  page,
}) => {
  const card = await open(page);
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
    .getByRole("button", { name: "Preview CW isolation output", exact: true })
    .click();
  await expect(card.getByRole("alert")).toBeVisible();
  await expect(
    card.getByRole("button", {
      name: "Import reviewed CW isolation definition",
      exact: true,
    }),
  ).toHaveCount(0);
});

test("wrong original export hash refuses download and keeps current review", async ({
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
      name: "Export original CW isolation activity bundle",
      exact: true,
    })
    .click();
  await expect(card.getByRole("alert")).toContainText("byte-digest");
  expect(downloads).toBe(0);
});

test("typed minus zero invalidates prior plus zero and survives preview import and original source", async ({
  page,
}) => {
  const card = await open(page);
  const plus = await preview(page, card, "0");
  await card
    .getByLabel("CW minimum target command", { exact: true })
    .fill("-0");
  await expect(
    card.getByRole("region", {
      name: "CW isolation output preview",
      exact: true,
    }),
  ).toHaveCount(0);
  const raw = await capture(page, base + "/preview", () =>
    card
      .getByRole("button", { name: "Preview CW isolation output", exact: true })
      .click(),
  );
  expect(Object.is(value(raw).choices.minimum_command, -0)).toBe(true);
  expect(value(raw).definition_id).not.toBe(plus.data.definition_id);
  await imported(page, card);
  const source = await exported(page);
  const check = py(
    "import sys,math;from bms_tool.models import Program;p=Program.model_validate_json(sys.stdin.read());g=p.metadata['macros']['definitions'][0]['program'];assert math.copysign(1,g['metadata']['cw_isolation_output_template']['choices']['minimum_command'])<0;assert math.copysign(1,next(n for n in g['nodes']if n['id']=='minimum')['params']['value'])<0;print(p.digest())",
    source,
  );
  await retain("independent-negative-zero-source", check);
});

test("dismissing import confirmation preserves current parent and no revision is saved", async ({
  page,
}) => {
  let calls = 0;
  page.on("request", (r) => {
    if (
      new URL(r.url()).pathname === base + "/import" ||
      new URL(r.url()).pathname === "/api/projects"
    )
      if (r.method() === "POST") calls++;
  });
  let card = await open(page);
  const before = await exported(page);
  card = await macros(page);
  await preview(page, card);
  page.once("dialog", (d) => d.dismiss());
  await card
    .getByRole("button", {
      name: "Import reviewed CW isolation definition",
      exact: true,
    })
    .click();
  expect(calls).toBe(0);
  expect(await exported(page)).toEqual(before);
});

test("parent criteria refresh retires a template review while unchanged source remains in editor", async ({
  page,
}) => {
  let card = await open(page);
  await preview(page, card);
  await page
    .getByRole("region", {
      name: "Reusable multi-output activities",
      exact: true,
    })
    .getByRole("button", { name: "Reload activity criteria", exact: true })
    .click();
  await expect(
    card.getByRole("region", {
      name: "CW isolation output preview",
      exact: true,
    }),
  ).toHaveCount(0);
  await expect(
    card.getByRole("button", {
      name: "Preview CW isolation output",
      exact: true,
    }),
  ).toBeEnabled();
  await preview(page, card);
});
