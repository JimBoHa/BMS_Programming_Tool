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
  base = "/api/activities/templates/co2-minimum-flow",
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
function seed(wired = false, scan = 1, unit = "cfm") {
  return py(
    `import sys,json
from tests.test_co2_minimum_flow_template import parent,caller
from bms_tool.co2_minimum_flow_template import Choices,convert_units
from bms_tool.models import Node
v=json.load(sys.stdin);c=convert_units(Choices(),v['unit']);p=caller(c,v['scan'])if v['wired']else parent(v['scan'],c)
p.name='CO2 template source';p.id='co2-browser'
p.metadata['opaque_numbers']={'large':9007199254740993,'signed':-0.0,'integer':0,'floating':0.0,'tiny':1e-6}
if not any(n.kind=='Output'for n in p.nodes):p.nodes.extend([Node(id='flow0',kind='Output',unit=c.flow_unit),Node(id='valid0',kind='Output',value_type='boolean')])
for n in p.nodes:n.x,n.y={'co2':(0,0),'co2_reset_a':(0,200),'co2_reset_b':(0,400),'flow_low':(0,600),'flow_high':(0,800),'flow0':(1000,100),'valid0':(1000,650)}.get(n.id,(400,250))
print(p.model_dump_json())`,
    JSON.stringify({ wired, scan, unit }),
  );
}
async function load(page: Page, body: Buffer) {
  await page.getByRole("button", { name: "Program", exact: true }).click();
  await page.locator('input[type=file][accept*=".st"]').setInputFiles({
    name: "co2-source.json",
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
    name: "CO2 minimum-airflow template",
    exact: true,
  });
  await expect
    .poll(
      async () =>
        (await card
          .getByRole("button", {
            name: "Preview CO2 minimum airflow",
            exact: true,
          })
          .isEnabled()) || (await card.getByRole("alert").isVisible()),
    )
    .toBe(true);
  return card;
}
async function open(page: Page, wired = false, scan = 1, unit = "cfm") {
  await page.goto("/");
  await load(page, seed(wired, scan, unit));
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
      .getByRole("button", { name: "Preview CO2 minimum airflow", exact: true })
      .click(),
  );
  await expect(
    card.getByRole("region", {
      name: "CO2 minimum-airflow preview",
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
  await retain("original-co2-scan", simulationServerResponseText(r));
  return simulationServerResponseJSON(r);
}
async function imported(page: Page, card: Locator) {
  return capture(page, base + "/import", () =>
    card
      .getByRole("button", {
        name: "Import reviewed CO2 airflow definition",
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
          ? "Export original CO2 airflow review JSON"
          : "Export original CO2 airflow activity bundle",
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
      throw Error("Held CO2 owner received another browser request");
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
    for (const port of [
      "co2",
      "co2_reset_a",
      "co2_reset_b",
      "flow_low",
      "flow_high",
    ])
      await wire(
        page,
        page.locator(
          `.react-flow__node[data-id="${port}"] [data-handleid="out"]`,
        ),
        actor.locator(`[data-handleid="${port}"]`),
      );
    await wire(
      page,
      actor.locator('[data-handleid="minimum_airflow"]'),
      page.locator('.react-flow__node[data-id="flow0"] [data-handleid="in"]'),
    );
    await wire(
      page,
      actor.locator('[data-handleid="reset_configuration_valid"]'),
      page.locator('.react-flow__node[data-id="valid0"] [data-handleid="in"]'),
    );
    await expect(page.locator(".react-flow__edge")).toHaveCount(7);
  } else {
    const wired = py(
      `import sys,json
from bms_tool.models import Program,Edge
v=json.load(sys.stdin);p=Program.model_validate(json.loads(v['source_json']));i=next(n.id for n in p.nodes if n.kind=='Activity');p.edges=[Edge(id=name,source=name,target=i,target_port=name)for name in('co2','co2_reset_a','co2_reset_b','flow_low','flow_high')]+[Edge(id='outflow',source=i,source_port='minimum_airflow',target='flow0'),Edge(id='outvalid',source=i,source_port='reset_configuration_valid',target='valid0')];print(p.model_dump_json())`,
      raw,
    );
    await load(page, wired);
  }
  return instance;
}
async function set(page: Page, id: string, n: string) {
  await page.getByLabel("Simulate " + id, { exact: true }).fill(n);
}

for (const [unit, scan] of [
  ["cfm", 0.5],
  ["L/s", 3],
] as const)
  test(`original artifacts reviewed import wiring simulation revision and four formats ${unit} h${scan}`, async ({
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
    const card = await open(page, false, scan, unit);
    if (unit !== "cfm")
      await capture(page, base + "/units", () =>
        card.getByLabel("CO2 airflow unit", { exact: true }).selectOption(unit),
      );
    const p = await preview(page, card);
    expect(p.data.program.nodes).toHaveLength(38);
    expect(p.data.program.edges).toHaveLength(57);
    expect(p.data.parent_reference.scan_seconds).toBe(scan);
    expect(p.data.program.scan_seconds).toBe(1);
    const pending = page.waitForEvent("download");
    await card
      .getByRole("button", {
        name: "Download original CO2 airflow preview response",
        exact: true,
      })
      .click();
    expect(readFileSync((await (await pending).path())!)).toEqual(p.raw);
    const review = await download(page, card, "review"),
      bundle = await download(page, card, "bundle"),
      parent = await imported(page, card);
    expect(value(parent).nodes.some((n: any) => n.kind === "Activity")).toBe(
      false,
    );
    expect(saves).toBe(0);
    expect(dialogs).toBe(0);
    await placed(page, p.data.definition_id, unit === "cfm");
    await page.getByRole("button", { name: "Program", exact: true }).click();
    await set(page, "co2", "900");
    const f = 0.4719474432;
    expect((await step(page)).last.outputs).toEqual({
      flow0: unit === "cfm" ? 625 : 425 * f + 0.5 * (825 * f - 425 * f),
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
      await retain("original-co2-interchange-" + format, raw);
    }
    const checked = py(
      `import sys,json,base64,math
from bms_tool.models import Program
from bms_tool.formats import import_program
v=json.load(sys.stdin);p=Program.model_validate_json(v['program']);assert all(import_program(base64.b64decode(b),n).digest()==p.digest()for n,b in v['files'].items());assert p.metadata['opaque_numbers']['large']==9007199254740993;assert type(p.metadata['opaque_numbers']['integer'])is int and type(p.metadata['opaque_numbers']['floating'])is float;assert math.copysign(1,p.metadata['opaque_numbers']['signed'])<0;print(p.digest())`,
      JSON.stringify({ program: source.toString(), files }),
    );
    await retain("independent-source-interchange", checked);
    const saved = await capture(page, "/api/projects", () =>
        page
          .getByRole("button", { name: "Save revision", exact: true })
          .click(),
      ),
      data = value(saved);
    expect(data.revision).toBe(1);
    const original = await page.request.get("/api/projects/" + data.id);
    expect(original.status()).toBe(200);
    await retain("original-co2-saved-http", await original.body());
    expect(saves).toBe(1);
    expect(
      (await (await page.request.get("/api/session")).json())
        .field_network_open,
    ).toBe(false);
    await retain("original-co2-reviewed-report", review);
    await retain("original-co2-reviewed-bundle", bundle);
  });

test("live endpoint changes invalid hold repair and extreme finite samples stay bounded", async ({
  page,
}) => {
  await open(page, true);
  await page.getByRole("button", { name: "Program", exact: true }).click();
  await set(page, "co2", "900");
  expect((await step(page)).last.outputs).toEqual({ flow0: 625, valid0: true });
  await set(page, "co2_reset_b", "800");
  expect((await step(page)).last.outputs).toEqual({
    flow0: 625,
    valid0: false,
  });
  await set(page, "co2_reset_b", "700");
  expect((await step(page)).last.outputs).toEqual({
    flow0: 625,
    valid0: false,
  });
  await set(page, "co2_reset_b", "1000");
  await set(page, "flow_low", "900");
  expect((await step(page)).last.outputs).toEqual({
    flow0: 625,
    valid0: false,
  });
  await set(page, "flow_low", "100");
  await set(page, "flow_high", "200");
  await set(page, "co2", "1e308");
  expect((await step(page)).last.outputs).toEqual({ flow0: 200, valid0: true });
  await set(page, "co2", "-1e308");
  expect((await step(page)).last.outputs).toEqual({ flow0: 100, valid0: true });
});

test("first bad quality preserves empty startup invalid first commit zero and later fault retains true flow", async ({
  page,
}) => {
  await open(page, true);
  await page.getByRole("button", { name: "Program", exact: true }).click();
  await page
    .getByLabel("Quality co2", { exact: true })
    .selectOption("open-circuit");
  const first = await step(page);
  expect(first.last).toBeNull();
  expect(first.history).toEqual([]);
  expect(first.session).toBeNull();
  await page.getByLabel("Quality co2", { exact: true }).selectOption("good");
  await set(page, "co2_reset_b", "800");
  expect((await step(page)).last.outputs).toEqual({ flow0: 0, valid0: false });
  await set(page, "co2_reset_b", "1000");
  await set(page, "co2", "900");
  const previous = await step(page);
  expect(previous.last.outputs).toEqual({ flow0: 625, valid0: true });
  await set(page, "co2_reset_b", "800");
  await page
    .getByLabel("Quality flow_low", { exact: true })
    .selectOption("open-circuit");
  expect((await step(page)).snapshot).toEqual(previous.snapshot);
  await page
    .getByLabel("Quality flow_low", { exact: true })
    .selectOption("good");
  expect((await step(page)).last.outputs).toEqual({
    flow0: 625,
    valid0: false,
  });
});

test("terminal output force does not rewrite retained unforced selected airflow", async ({
  page,
}) => {
  await open(page, true);
  await page.getByRole("button", { name: "Program", exact: true }).click();
  await set(page, "co2", "900");
  await step(page);
  const source = await exported(page),
    id = JSON.parse(source.toString()).nodes.find(
      (n: any) => n.kind === "Activity",
    ).id;
  await page.locator(`.react-flow__node[data-id="${id}"]`).click();
  const port = page.getByRole("region", {
    name: "Activity output minimum_airflow",
    exact: true,
  });
  await port.getByLabel("Simulation force value", { exact: true }).fill("91");
  await port
    .getByRole("button", { name: "Hold simulation value", exact: true })
    .click();
  await set(page, "co2_reset_b", "800");
  expect((await step(page)).last.outputs).toEqual({ flow0: 91, valid0: false });
  await port
    .getByRole("button", { name: "Release simulation force", exact: true })
    .click();
  expect((await step(page)).last.outputs).toEqual({
    flow0: 625,
    valid0: false,
  });
});

test("signed zero scientific controls convert and persist while real underflow retains original unit draft", async ({
  page,
}) => {
  let card = await open(page);
  await card
    .getByLabel("CO2 Low minimum airflow default", { exact: true })
    .fill("-0");
  await card
    .getByLabel("CO2 Measured CO2 default", { exact: true })
    .fill("1e-6");
  const p = await preview(page, card);
  await capture(page, base + "/units", () =>
    card.getByLabel("CO2 airflow unit", { exact: true }).selectOption("L/s"),
  );
  await expect(
    card.getByLabel("CO2 Low minimum airflow default", { exact: true }),
  ).toHaveValue("-0.0");
  const converted = await preview(page, card);
  expect(Object.is(converted.data.choices.flow_low_default, -0)).toBe(true);
  expect(converted.data.choices.co2_default).toBe(1e-6);
  await imported(page, card);
  const source = await exported(page);
  await retain(
    "independent-signedzero-import",
    py(
      "import sys,math;from bms_tool.models import Program;p=Program.model_validate_json(sys.stdin.read());g=p.metadata['macros']['definitions'][0]['program'];assert math.copysign(1,g['metadata']['co2_minimum_flow_template']['choices']['flow_low_default'])<0;assert math.copysign(1,next(n for n in g['nodes']if n['id']=='flow_low')['params']['default'])<0;assert next(n for n in g['nodes']if n['id']=='co2')['params']['default']==1e-6;print(p.digest())",
      source,
    ),
  );
  card = await macros(page);
  await card
    .getByLabel("CO2 Low minimum airflow default", { exact: true })
    .fill("0");
  await card
    .getByLabel("CO2 High minimum airflow default", { exact: true })
    .fill("5e-324");
  await capture(
    page,
    base + "/units",
    () =>
      card.getByLabel("CO2 airflow unit", { exact: true }).selectOption("L/s"),
    422,
  );
  await expect(card.getByRole("alert")).toContainText("underflow");
  await expect(
    card.getByLabel("CO2 airflow unit", { exact: true }),
  ).toHaveValue("cfm");
  await expect(
    card.getByLabel("CO2 High minimum airflow default", { exact: true }),
  ).toHaveValue("5e-324");
  expect(p.data.definition_id).not.toBe(converted.data.definition_id);
});

test("local invalid endpoint order and flow domain refuse before request", async ({
  page,
}) => {
  const card = await open(page);
  let requests = 0;
  page.on("request", (r) => {
    if (new URL(r.url()).pathname === base + "/preview") requests++;
  });
  await card.getByLabel("CO2 Reset B default", { exact: true }).fill("800");
  await card
    .getByRole("button", { name: "Preview CO2 minimum airflow", exact: true })
    .click();
  await expect(card.getByRole("alert")).toContainText("greater than A");
  await card.getByLabel("CO2 Reset B default", { exact: true }).fill("1000");
  await card
    .getByLabel("CO2 High minimum airflow default", { exact: true })
    .fill("1e308");
  await card
    .getByRole("button", { name: "Preview CO2 minimum airflow", exact: true })
    .click();
  await expect(card.getByRole("alert")).toContainText("Airflow defaults");
  expect(requests).toBe(0);
});

for (const kind of [
  "preview-discard",
  "units-ABA",
  "import-source",
  "export-unmount",
])
  test(`held ${kind} cannot adopt stale template response`, async ({
    page,
  }) => {
    const card = await open(page);
    if (kind !== "preview-discard" && kind !== "units-ABA")
      await preview(page, card);
    const endpoint = kind.startsWith("preview")
        ? "/preview"
        : kind.startsWith("units")
          ? "/units"
          : kind.startsWith("import")
            ? "/import"
            : "/export",
      gate = await held(page, base + endpoint);
    let downloads = 0;
    page.on("download", () => downloads++);
    try {
      if (kind === "units-ABA")
        await card
          .getByLabel("CO2 airflow unit", { exact: true })
          .selectOption("L/s");
      else
        await card
          .getByRole("button", {
            name: kind.startsWith("preview")
              ? "Preview CO2 minimum airflow"
              : kind.startsWith("import")
                ? "Import reviewed CO2 airflow definition"
                : "Export original CO2 airflow review JSON",
            exact: true,
          })
          .click();
      await gate.started;
      if (kind === "preview-discard") {
        await card
          .getByRole("button", {
            name: "Discard pending CO2 airflow response",
            exact: true,
          })
          .click();
        await card
          .getByLabel("CO2 Measured CO2 default", { exact: true })
          .fill("900");
      } else if (kind === "units-ABA") {
        await page.getByLabel("Program name", { exact: true }).fill("B source");
        await page
          .getByLabel("Program name", { exact: true })
          .fill("CO2 template source");
      } else if (kind === "import-source")
        await page
          .getByLabel("Program name", { exact: true })
          .fill("Newer source");
      else
        await page
          .getByRole("button", { name: "Program", exact: true })
          .click();
    } finally {
      await gate.release();
    }
    expect(downloads).toBe(0);
    if (kind === "units-ABA")
      await expect(
        card.getByLabel("CO2 airflow unit", { exact: true }),
      ).toHaveValue("cfm");
    if (kind.startsWith("import")) {
      const p = JSON.parse((await exported(page)).toString());
      expect(p.name).toBe("Newer source");
      expect(p.metadata.macros.definitions).toHaveLength(0);
    }
  });

test("unknown profile refuses current template criteria", async ({ page }) => {
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
      name: "Preview CO2 minimum airflow",
      exact: true,
    }),
  ).toBeDisabled();
});

test("forged second Program descriptor refuses import authority", async ({
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
    .getByRole("button", { name: "Preview CO2 minimum airflow", exact: true })
    .click();
  await expect(card.getByRole("alert")).toBeVisible();
  await expect(
    card.getByRole("button", {
      name: "Import reviewed CO2 airflow definition",
      exact: true,
    }),
  ).toHaveCount(0);
});

test("wrong original export hash refuses download and retains current review", async ({
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
      name: "Export original CO2 airflow activity bundle",
      exact: true,
    })
    .click();
  await expect(card.getByRole("alert")).toContainText("byte-digest");
  expect(downloads).toBe(0);
  await expect(
    card.getByRole("region", {
      name: "CO2 minimum-airflow preview",
      exact: true,
    }),
  ).toBeVisible();
});

test("failed parent criteria reload retires review and recovery requires fresh preview", async ({
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
      name: "CO2 minimum-airflow preview",
      exact: true,
    }),
  ).toHaveCount(0);
  await expect(
    card.getByRole("button", {
      name: "Preview CO2 minimum airflow",
      exact: true,
    }),
  ).toBeDisabled();
  await lib
    .getByRole("button", { name: "Reload activity criteria", exact: true })
    .click();
  await expect(
    card.getByRole("button", {
      name: "Preview CO2 minimum airflow",
      exact: true,
    }),
  ).toBeEnabled();
  await preview(page, card);
});

test("idempotent reviewed import adds no instance and numeric source conflict refuses replacement", async ({
  page,
}) => {
  let card = await open(page);
  await card
    .getByLabel("CO2 Low minimum airflow default", { exact: true })
    .fill("0");
  await preview(page, card);
  await imported(page, card);
  await preview(page, card);
  const again = await imported(page, card);
  expect(value(again).metadata.macros.definitions).toHaveLength(1);
  expect(value(again).nodes.some((n: any) => n.kind === "Activity")).toBe(
    false,
  );
  const edited = py(
    "import sys,json;from bms_tool.models import Program;v=json.load(sys.stdin);p=Program.model_validate(json.loads(v['source_json']));g=p.metadata['macros']['definitions'][0]['program'];next(n for n in g['nodes']if n['id']=='flow_low')['params']['default']=-0.0;print(p.model_dump_json())",
    again,
  );
  await load(page, edited);
  const before = await exported(page);
  card = await macros(page);
  await card
    .getByLabel("CO2 Low minimum airflow default", { exact: true })
    .fill("0");
  await capture(
    page,
    base + "/preview",
    () =>
      card
        .getByRole("button", {
          name: "Preview CO2 minimum airflow",
          exact: true,
        })
        .click(),
    422,
  );
  await expect(card.getByRole("alert")).toBeVisible();
  expect(await exported(page)).toEqual(before);
});
