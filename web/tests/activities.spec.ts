import {
  test,
  expect,
  simulationServerResponseJSON,
  simulationServerResponseText,
  type Page,
  type Locator,
} from "./simulationFixture";
import { projectedSourceFixture } from "./sourceTransportFixtures";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = fileURLToPath(new URL("../..", import.meta.url)),
  python = path.join(root, ".venv/bin/python"),
  base = "/api/activities",
  sha = (value: Buffer) => createHash("sha256").update(value).digest("hex"),
  env = () => ({ ...process.env, PYTHONPATH: path.join(root, "backend") });
function py(script: string, input: Buffer | string = "") {
  return execFileSync(python, ["-c", script], { cwd: root, env: env(), input });
}
async function retain(name: string, body: Buffer | string) {
  await test.info().attach(name, { body, contentType: "application/json" });
}
const fixtureScript = `
import json,sys
from bms_tool.models import Program,Node,Edge
from tests.test_activities import caller
from tests.test_macros import caller as legacy
from bms_tool.activities import export_bundle,canonical
from bms_tool.macros import export_macro_library
mode=sys.stdin.read()
if mode=='legacy' or mode=='legacy-bundle':
 p=legacy(); p.name='Legacy source'; p.id='activity-browser-legacy'
 if mode=='legacy-bundle': print(json.dumps(export_macro_library(p,'adder')));raise SystemExit
else:
 p=caller(nested=mode=='nested',instances=2 if mode=='two' else 1)
 p.name='Mixed activity source';p.id='activity-browser'
 for item in p.metadata['macros']['definitions']:
  for n in item['program']['nodes']:
   if n['unit']=='kW':n['unit']='cfm'
   if n['kind']=='Slew':n['params']['rate']=10
   if n['id']=='zero':n['params']['value']=20
   positions={'demand':(0,50),'request':(0,50),'ramp':(300,50),'inner':(300,160),'zero':(300,420),'positive':(650,250),'first':(1000,50),'second':(1000,250),'enabled':(1000,480),'power':(800,80),'running':(800,420)}
   n['x'],n['y']=positions[n['id']]
 for n in p.nodes:
  if n.unit=='kW':n.unit='cfm'
  if n.kind=='Input':n.params['default']=100
 if mode=='bundle':print(canonical(export_bundle(p,'controller')).decode());raise SystemExit
 if mode=='empty':p.nodes=[n for n in p.nodes if n.kind!='Activity'];p.edges=[];p.metadata['macros']['definitions']=[]
 if mode=='raw':
  item=p.metadata['macros']['definitions'][0];g=Program.model_validate(item['program'])
  p.nodes=[n for n in g.nodes if n.id not in ['second']]
  p.edges=[e for e in g.edges if e.target!='second']
  next(n for n in p.nodes if n.id=='demand').params['default']=100
  p.metadata['macros']['definitions']=[]
 if mode=='prototype':
  d=p.metadata['macros']['definitions'][0];d['id']='constructor'
  names={'demand':'constructor','first':'toString','enabled':'hasOwnProperty'}
  for n in d['program']['nodes']:n['id']=names.get(n['id'],n['id'])
  for e in d['program']['edges']:
   e['source']=names.get(e['source'],e['source']);e['target']=names.get(e['target'],e['target'])
  p.nodes[1].params['definition']='constructor';p.edges[0].target_port='constructor';p.edges[1].source_port='toString';p.edges[2].source_port='hasOwnProperty'
 if mode=='unused':p.nodes=[n for n in p.nodes if n.kind!='Activity'];p.edges=[]
 if mode=='incomplete':p.edges=p.edges[1:]
 if mode=='conflict':p.metadata['macros']['definitions'][0]['program']['metadata']['original']['negative_zero']=0.0
for index,n in enumerate(p.nodes):
 if n.kind=='Input':n.x=0;n.y=90+index*70
 elif n.kind in ('Activity','Macro','Slew'):n.x=350;n.y=100+index*30
 elif n.kind=='Output':n.x=800;n.y=80+index*100
 else:n.x=550;n.y=300+index*50
 if mode=='raw':
  positions={'demand':(0,50),'ramp':(300,50),'zero':(300,420),'positive':(650,250),'first':(1000,50),'enabled':(1000,480)}
  n.x,n.y=positions[n.id]
p.metadata['source_atoms']={'signed':-0.0,'integer':0,'floating':0.0,'small':1e-6}
print(p.model_dump_json())
`;
function fixture(mode = "mixed") {
  return py(fixtureScript, mode);
}
async function load(page: Page, bytes: Buffer) {
  await page.getByRole("button", { name: "Program", exact: true }).click();
  await page.locator('input[type=file][accept*=".st"]').setInputFiles({
    name: "activities.json",
    mimeType: "application/json",
    buffer: bytes,
  });
  await expect(page.locator(".toast")).toContainText(
    "Imported as a new local project",
  );
}
async function open(page: Page, mode = "mixed") {
  await page.goto("/");
  await load(page, fixture(mode));
  if (mode === "legacy") {
    await page.getByRole("button", { name: "Macros", exact: true }).click();
    const card = page.getByRole("region", {
      name: "Multi-output activity migration",
      exact: true,
    });
    await expect(
      card.getByRole("button", {
        name: "Review migration to activities",
        exact: true,
      }),
    ).toBeEnabled();
    return card;
  }
  return library(page);
}
async function library(page: Page) {
  await page.getByRole("button", { name: "Macros", exact: true }).click();
  const card = page.getByRole("region", {
    name: "Reusable multi-output activities",
    exact: true,
  });
  await expect
    .poll(
      async () =>
        (await card
          .getByRole("button", { name: "Import activity archive", exact: true })
          .isEnabled()) || (await card.getByRole("alert").isVisible()),
    )
    .toBe(true);
  return card;
}
async function selectDefinition(card: Locator, id = "controller") {
  await card
    .locator(".activity-definition")
    .filter({
      has: card.page().locator("code", { hasText: new RegExp("^" + id + "$") }),
    })
    .click();
  await expect(
    card.getByRole("region", {
      name: "Selected activity definition",
      exact: true,
    }),
  ).toBeVisible();
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
      const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 });
      raw = await response.body();
      await retain(
        "original-" + endpoint.split("/").at(-1) + "-request",
        route.request().postDataBuffer()!,
      );
      await retain("original-" + endpoint.split("/").at(-1) + "-response", raw);
      expect(response.status()).toBe(status);
      await route.fulfill({ response, body: raw });
    },
    { times: 1 },
  );
  await action();
  await expect.poll(() => raw !== undefined).toBe(true);
  return raw!;
}
async function editor(page: Page) {
  await page.getByRole("button", { name: "Program", exact: true }).click();
  await page.getByLabel("Export format", { exact: true }).selectOption("json");
  const waiting = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export", exact: true }).click();
  const raw = readFileSync((await (await waiting).path())!);
  await retain("original-current-editor", raw);
  return raw;
}
async function step(page: Page) {
  await page.getByRole("button", { name: "Program", exact: true }).click();
  const waiting = page.waitForResponse(
    (r) =>
      new URL(r.url()).pathname === "/api/simulation/step" &&
      r.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Step simulation", exact: true })
    .click();
  const response = await waiting;
  expect(response.status()).toBe(200);
  const raw = simulationServerResponseJSON(response);
  await retain(
    "original-activity-scan",
    simulationServerResponseText(response),
  );
  return raw;
}
async function archive(page: Page, card: Locator) {
  // Retain the exact current catalog used by this export, through an explicit
  // criteria refresh before any simulation starts in these lifecycle cases.
  await capture(page, base + "/catalog", () =>
    card
      .getByRole("button", { name: "Reload activity criteria", exact: true })
      .click(),
  );
  let raw: Buffer | undefined,
    header = "";
  await page.route(
    "**" + base + "/export",
    async (route) => {
      const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 });
      expect(response.status()).toBe(200);
      raw = await response.body();
      header = response.headers()["x-file-sha256"];
      await retain(
        "original-archive-delivery-headers",
        JSON.stringify(response.headers()),
      );
      await retain(
        "original-archive-request",
        route.request().postDataBuffer()!,
      );
      await route.fulfill({ response, body: raw });
    },
    { times: 1 },
  );
  const waiting = page.waitForEvent("download");
  await card
    .getByRole("button", {
      name: "Export original activity archive",
      exact: true,
    })
    .click();
  const bytes = readFileSync((await (await waiting).path())!);
  expect(bytes).toEqual(raw);
  expect(sha(bytes)).toBe(header);
  await retain("original-archive-upstream", raw!);
  await retain("original-archive-download", bytes);
  return bytes;
}
async function wire(page: Page, from: Locator, to: Locator) {
  const a = await from.boundingBox(),
    b = await to.boundingBox();
  expect(a).not.toBeNull();
  expect(b).not.toBeNull();
  await page.mouse.move(a!.x + a!.width / 2, a!.y + a!.height / 2);
  await page.mouse.down();
  await page.mouse.move(b!.x + b!.width / 2, b!.y + b!.height / 2, {
    steps: 20,
  });
  await page.mouse.up();
}
async function held(page: Page, endpoint: string) {
  let ready!: () => void, release!: () => void, done!: () => void;
  const started = new Promise<void>((r) => (ready = r)),
    gate = new Promise<void>((r) => (release = r)),
    finished = new Promise<void>((r) => (done = r));
  const pattern = "**" + endpoint;
  let requests = 0;
  const handler = async (route: import("@playwright/test").Route) => {
    if (++requests !== 1) {
      await route.abort("failed");
      throw new Error(
        "Held response must own exactly one original browser request.",
      );
    }
    try {
      const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 }),
        raw = await response.body();
      expect(response.status()).toBe(200);
      await retain("held-original-request", route.request().postDataBuffer()!);
      await retain("held-original-response", raw);
      ready();
      await gate;
      await route.fulfill({ response, body: raw });
    } finally {
      done();
    }
  };
  // Keep the interception pattern until explicit release. A times:1 handler
  // disappears while held; registering another route can then continue the
  // pending browser request before this owner's intended fulfillment.
  await page.route(pattern, handler);
  return {
    started,
    async release() {
      release();
      try {
        await finished;
        expect(requests).toBe(1);
      } finally {
        await page.unroute(pattern, handler);
      }
    },
  };
}
async function migration(page: Page) {
  await page.getByRole("button", { name: "Macros", exact: true }).click();
  const card = page.getByRole("region", {
    name: "Multi-output activity migration",
    exact: true,
  });
  const raw = await capture(page, base + "/migration/preview", () =>
    card
      .getByRole("button", {
        name: "Review migration to activities",
        exact: true,
      })
      .click(),
  );
  await expect(
    card.getByRole("region", {
      name: "Activity migration review",
      exact: true,
    }),
  ).toBeVisible();
  return { card, raw };
}

test("mixed ports share one state, hold/release explicit aliases and roll back quality", async ({
  page,
}) => {
  await open(page);
  await page.getByRole("button", { name: "Program", exact: true }).click();
  const node = page.locator('.react-flow__node[data-id="use0"]');
  await node.click();
  await expect(node.locator(".react-flow__handle-right")).toHaveCount(3);
  const ports = page.getByRole("complementary", {
    name: "Activity output inspector",
  });
  await expect(
    ports.getByRole("region", { name: "Activity output enabled", exact: true }),
  ).toContainText("boolean");
  expect((await step(page)).last.outputs).toEqual({
    value0: 10,
    active0: false,
  });
  expect((await step(page)).last.outputs).toEqual({
    value0: 20,
    active0: false,
  });
  const first = ports.getByRole("region", {
    name: "Activity output first",
    exact: true,
  });
  await first.getByLabel("Simulation force value", { exact: true }).fill("77");
  await first
    .getByRole("button", { name: "Hold simulation value", exact: true })
    .click();
  let row = await step(page);
  expect(row.last.outputs).toEqual({ value0: 77, active0: true });
  await expect(first).toContainText("computed 30");
  await first
    .getByRole("button", { name: "Release simulation force", exact: true })
    .click();
  row = await step(page);
  expect(row.last.outputs).toEqual({ value0: 40, active0: true });
  const previous = row.snapshot;
  await page
    .getByLabel("Quality request0", { exact: true })
    .selectOption("open-circuit");
  row = await step(page);
  expect(row.scan_error).toContain("quality");
  expect(row.snapshot).toEqual(previous);
  await page
    .getByLabel("Quality request0", { exact: true })
    .selectOption("good");
  expect((await step(page)).last.outputs).toEqual({
    value0: 50,
    active0: true,
  });
  await first.getByLabel("Simulation force value", { exact: true }).fill("66");
  await first
    .getByRole("button", { name: "Hold simulation value", exact: true })
    .click();
  await step(page);
  await ports
    .getByRole("button", {
      name: "Refresh activity port authority",
      exact: true,
    })
    .click();
  const refreshed = await step(page);
  expect(refreshed.snapshot.time).toBe(1);
  expect(refreshed.snapshot.forces).toEqual({});
  expect(refreshed.last.outputs).toEqual({ value0: 10, active0: false });
});

for (const mode of ["nested", "two"])
  test(`${mode} instances retain shared state paths and original hierarchy through four formats and revision`, async ({
    page,
  }) => {
    let card = await open(page, mode);
    await selectDefinition(card, mode === "nested" ? "outer" : "controller");
    const bundle = await archive(page, card);
    expect(JSON.parse(bundle.toString()).library.definitions.length).toBe(
      mode === "nested" ? 2 : 1,
    );
    expect((await step(page)).last.outputs.value0).toBe(10);
    expect((await step(page)).last.outputs.value0).toBe(20);
    const original = await editor(page),
      files: Record<string, string> = {};
    for (const format of ["json", "st", "plcopen", "graphml"]) {
      await page
        .getByLabel("Export format", { exact: true })
        .selectOption(format);
      const pending = page.waitForEvent("download");
      await page.getByRole("button", { name: "Export", exact: true }).click();
      const file = await pending,
        raw = readFileSync((await file.path())!);
      files[file.suggestedFilename()] = raw.toString("base64");
      await retain("original-interchange-" + format, raw);
    }
    const saved = await capture(page, "/api/projects", () =>
      page.getByRole("button", { name: "Save revision", exact: true }).click(),
    );
    const p = projectedSourceFixture(JSON.parse(saved.toString()));
    expect(p.revision).toBe(1);
    const fetched = await page.request.get("/api/projects/" + p.id);
    expect(fetched.status()).toBe(200);
    const body = await fetched.body();
    await retain("original-saved-http", body);
    const validation = py(
      "import sys,json,base64;from bms_tool.models import Program,canonical;from bms_tool.formats import import_program;v=json.load(sys.stdin);p=Program.model_validate_json(v['program']);assert all(import_program(base64.b64decode(b),n).digest()==p.digest()for n,b in v['files'].items());s=Program.model_validate_json(v['saved']);assert s.revision==1;assert s.metadata==p.metadata;assert b'\"signed\": -0.0'in canonical(s);print(json.dumps({'program_sha256':p.digest(),'saved_sha256':s.digest(),'formats':len(v['files'])}))",
      JSON.stringify({
        program: original.toString(),
        files,
        saved: body.toString(),
      }),
    );
    await retain("independent-original-interchange-check", validation);
    await page.reload();
    await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
      "Mixed activity source",
    );
    expect(
      (await (await page.request.get("/api/session")).json())
        .field_network_open,
    ).toBe(false);
  });

test("import a dependency archive, place an instance and wire both output handles graphically", async ({
  page,
}) => {
  const card = await open(page, "empty"),
    bundle = fixture("bundle");
  await capture(page, base + "/import", () =>
    card
      .getByLabel("Import activity bundle file", { exact: true })
      .setInputFiles({
        name: "mixed.json",
        mimeType: "application/json",
        buffer: bundle,
      }),
  );
  await expect(card.locator(".activity-definition")).toHaveCount(1);
  await selectDefinition(card);
  await card.getByLabel("Activity canvas X", { exact: true }).fill("350");
  await card.getByLabel("Activity canvas Y", { exact: true }).fill("150");
  const raw = await capture(page, base + "/instantiate", () =>
    card
      .getByRole("button", {
        name: "Add activity instance to program",
        exact: true,
      })
      .click(),
  );
  const p = projectedSourceFixture(JSON.parse(raw.toString())),
    id = p.nodes.find((n: any) => n.kind === "Activity").id;
  await page.getByRole("button", { name: "Program", exact: true }).click();
  const node = page.locator(`.react-flow__node[data-id="${id}"]`);
  await wire(
    page,
    page.locator('.react-flow__node[data-id="request0"] [data-handleid="out"]'),
    node.locator('[data-handleid="demand"]'),
  );
  await wire(
    page,
    node.locator('[data-handleid="first"]'),
    page.locator('.react-flow__node[data-id="value0"] [data-handleid="in"]'),
  );
  await wire(
    page,
    node.locator('[data-handleid="enabled"]'),
    page.locator('.react-flow__node[data-id="active0"] [data-handleid="in"]'),
  );
  await expect(page.locator(".react-flow__edge")).toHaveCount(3);
  expect((await step(page)).last.outputs).toEqual({
    value0: 10,
    active0: false,
  });
});

test("extract mixed-output selection and retain distinct source ports and fanout", async ({
  page,
}) => {
  await open(page, "raw");
  await page.getByRole("button", { name: "Program", exact: true }).click();
  await page.locator('.react-flow__node[data-id="ramp"]').click();
  await page
    .locator('.react-flow__node[data-id="zero"]')
    .click({ modifiers: ["Shift"] });
  await page
    .locator('.react-flow__node[data-id="positive"]')
    .click({ modifiers: ["Shift"] });
  const card = await library(page);
  await card
    .getByLabel("Activity name", { exact: true })
    .fill("Mixed controller");
  const created = await capture(page, base + "/create", () =>
    card
      .getByRole("button", {
        name: "Create multi-output activity",
        exact: true,
      })
      .click(),
  );
  const p = projectedSourceFixture(JSON.parse(created.toString()));
  expect(p.metadata.macros.definitions).toHaveLength(1);
  expect(
    p.metadata.macros.definitions[0].program.nodes.filter(
      (n: any) => n.kind === "Output",
    ),
  ).toHaveLength(2);
  expect((await step(page)).last.outputs).toEqual({
    first: 10,
    enabled: false,
  });
});

test("inspect and edit shared definition, discard later edits and preserve numeric source atoms", async ({
  page,
}) => {
  let card = await open(page);
  await selectDefinition(card);
  await capture(page, base + "/definition", () =>
    card
      .getByRole("button", { name: "Inspect activity graph", exact: true })
      .click(),
  );
  await expect(
    card.getByRole("region", {
      name: "Activity graph inspection",
      exact: true,
    }),
  ).toContainText("Slew");
  await card
    .getByRole("button", { name: "Edit activity graph", exact: true })
    .click();
  await expect(page.locator(".macro-edit-banner")).toBeVisible();
  await page.locator('.react-flow__node[data-id="ramp"]').click();
  await page
    .locator(".inspector label")
    .filter({ hasText: /^rate$/ })
    .locator("input")
    .fill("25");
  await capture(page, base + "/update", () =>
    page
      .getByRole("button", { name: "Apply definition changes", exact: true })
      .click(),
  );
  expect((await step(page)).last.outputs).toEqual({
    value0: 25,
    active0: true,
  });
  card = await library(page);
  await selectDefinition(card);
  await card
    .getByRole("button", { name: "Edit activity graph", exact: true })
    .click();
  await page.locator('.react-flow__node[data-id="ramp"]').click();
  await page
    .locator(".inspector label")
    .filter({ hasText: /^rate$/ })
    .locator("input")
    .fill("99");
  await page
    .getByRole("button", { name: "Discard definition changes", exact: true })
    .click();
  const original = await editor(page);
  const check = py(
    "import sys;from bms_tool.models import Program,canonical;p=Program.model_validate_json(sys.stdin.read());g=p.metadata['macros']['definitions'][0]['program'];assert next(n for n in g['nodes']if n['id']=='ramp')['params']['rate']==25;assert b'\"negative_zero\": -0.0'in canonical(p);print(p.digest())",
    original,
  );
  await retain("independent-edit-source-check", check);
});

test("delete only an unused definition after confirmation; used definitions remain guarded", async ({
  page,
}) => {
  let card = await open(page);
  await selectDefinition(card);
  await expect(
    card.getByRole("button", { name: "Delete unused activity", exact: true }),
  ).toBeDisabled();
  await load(page, fixture("unused"));
  card = await library(page);
  await selectDefinition(card);
  page.once("dialog", (d) => d.dismiss());
  await card
    .getByRole("button", { name: "Delete unused activity", exact: true })
    .click();
  await expect(card.locator(".activity-definition")).toHaveCount(1);
  page.once("dialog", (d) => d.accept());
  await capture(page, base + "/delete", () =>
    card
      .getByRole("button", { name: "Delete unused activity", exact: true })
      .click(),
  );
  await expect(card.locator(".activity-definition")).toHaveCount(0);
});

test("review original migration bytes, dismiss confirmation, then promote with fresh simulation and no forces", async ({
  page,
}) => {
  await open(page, "legacy");
  await page.getByRole("button", { name: "Program", exact: true }).click();
  await page.locator('.react-flow__node[data-id="instance"]').click();
  await page.getByLabel("Simulation force value", { exact: true }).fill("99");
  await page
    .getByRole("button", { name: "Hold simulation value", exact: true })
    .click();
  const before = await step(page);
  expect(before.last.outputs).toEqual({ out: 99 });
  const { card, raw } = await migration(page);
  const waiting = page.waitForEvent("download");
  await card
    .getByRole("button", {
      name: "Download original migration response",
      exact: true,
    })
    .click();
  expect(readFileSync((await (await waiting).path())!)).toEqual(raw);
  page.once("dialog", (d) => d.dismiss());
  await card
    .getByRole("button", {
      name: "Apply reviewed activity migration",
      exact: true,
    })
    .click();
  await expect(card).toBeVisible();
  page.once("dialog", (d) => d.accept());
  await capture(page, base + "/migration/apply", () =>
    card
      .getByRole("button", {
        name: "Apply reviewed activity migration",
        exact: true,
      })
      .click(),
  );
  await expect(
    page.getByRole("region", {
      name: "Reusable multi-output activities",
      exact: true,
    }),
  ).toBeVisible();
  const after = await step(page);
  expect(after.last.outputs).toEqual({ out: 5 });
  expect(after.snapshot.time).toBe(1);
  expect(after.snapshot.forces).toEqual({});
  expect(after.session).not.toBe(before.session);
});

test("version-one bundle requires reviewed promotion and preserves original/review/promoted downloads", async ({
  page,
}) => {
  const card = await open(page, "empty"),
    original = fixture("legacy-bundle");
  const raw = await capture(page, base + "/migration/bundle-preview", () =>
    card
      .getByLabel("Import activity bundle file", { exact: true })
      .setInputFiles({
        name: "legacy.json",
        mimeType: "application/json",
        buffer: original,
      }),
  );
  const review = card.getByRole("region", {
    name: "Version-one bundle promotion review",
    exact: true,
  });
  await expect(review).toBeVisible();
  for (const [label, expected] of [
    ["Download original version-one bundle", original],
    ["Download original promotion response", raw],
  ] as const) {
    const pending = page.waitForEvent("download");
    await review.getByRole("button", { name: label, exact: true }).click();
    expect(readFileSync((await (await pending).path())!)).toEqual(expected);
  }
  const pending = page.waitForEvent("download");
  await review
    .getByRole("button", {
      name: "Download original promoted bundle",
      exact: true,
    })
    .click();
  const promoted = readFileSync((await (await pending).path())!);
  expect(JSON.parse(promoted.toString()).format).toBe("bms-macro-library/2");
  await retain("original-promoted-bundle-download", promoted);
  await capture(page, base + "/import", () =>
    review
      .getByRole("button", {
        name: "Promote and import reviewed bundle",
        exact: true,
      })
      .click(),
  );
  await expect(card.locator(".activity-definition")).toHaveCount(1);
});

test("unfinished parent retains named handles and diagnostics without alias force authority", async ({
  page,
}) => {
  const card = await open(page, "incomplete");
  await expect(card).toContainText("unfinished or not executable");
  await page.getByRole("button", { name: "Program", exact: true }).click();
  const node = page.locator('.react-flow__node[data-id="use0"]');
  await node.click();
  await expect(node.locator(".react-flow__handle-right")).toHaveCount(3);
  await expect(
    page.getByRole("complementary", { name: "Activity output inspector" }),
  ).toContainText("No old alias authority");
  await expect(
    page.getByRole("button", { name: "Hold simulation value", exact: true }),
  ).toHaveCount(0);
});

test("prototype-like definition and port IDs render and simulate as ordinary case-sensitive names", async ({
  page,
}) => {
  const card = await open(page, "prototype");
  await selectDefinition(card, "constructor");
  await expect(
    card.getByRole("table", { name: "Activity port contracts", exact: true }),
  ).toContainText("hasOwnProperty");
  await page.getByRole("button", { name: "Program", exact: true }).click();
  const node = page.locator('.react-flow__node[data-id="use0"]');
  await expect(node.locator('[data-handleid="toString"]')).toHaveCount(1);
  expect((await step(page)).last.outputs).toEqual({
    value0: 10,
    active0: false,
  });
});

for (const kind of ["source", "discard", "unmount", "ABA"])
  test(`held v2 instance ${kind} cannot adopt a stale Activity source`, async ({
    page,
  }) => {
    const card = await open(page);
    await selectDefinition(card);
    const gate = await held(page, base + "/instantiate");
    try {
      await card
        .getByRole("button", {
          name: "Add activity instance to program",
          exact: true,
        })
        .click();
      await gate.started;
      if (kind === "discard")
        await card
          .getByRole("button", {
            name: "Discard pending activity response",
            exact: true,
          })
          .click();
      else if (kind === "unmount")
        await page
          .getByRole("button", { name: "Program", exact: true })
          .click();
      else {
        await page
          .getByLabel("Program name", { exact: true })
          .fill("Changed source");
        if (kind === "ABA")
          await page
            .getByLabel("Program name", { exact: true })
            .fill("Mixed activity source");
      }
    } finally {
      await gate.release();
    }
    const current = JSON.parse((await editor(page)).toString());
    expect(
      current.nodes.filter((n: any) => n.kind === "Activity"),
    ).toHaveLength(1);
    if (kind === "source") expect(current.name).toBe("Changed source");
  });

for (const kind of ["unmount", "migration"])
  test(`held legacy import ${kind} cannot overwrite a later editor or migrated version`, async ({
    page,
  }) => {
    await open(page, "legacy");
    const gate = await held(page, "/api/macros/import");
    try {
      await page
        .getByLabel("Import macro bundle file", { exact: true })
        .setInputFiles({
          name: "legacy.json",
          mimeType: "application/json",
          buffer: fixture("legacy-bundle"),
        });
      await gate.started;
      if (kind === "unmount") {
        await page
          .getByRole("button", { name: "Program", exact: true })
          .click();
        await page
          .getByLabel("Program name", { exact: true })
          .fill("Keep later editor");
      } else {
        const { card } = await migration(page);
        page.once("dialog", (d) => d.accept());
        await capture(page, base + "/migration/apply", () =>
          card
            .getByRole("button", {
              name: "Apply reviewed activity migration",
              exact: true,
            })
            .click(),
        );
        await expect(
          page.getByRole("region", {
            name: "Reusable multi-output activities",
            exact: true,
          }),
        ).toBeVisible();
      }
    } finally {
      await gate.release();
    }
    const current = JSON.parse((await editor(page)).toString());
    expect(current.metadata.macros.version).toBe(kind === "migration" ? 2 : 1);
    if (kind === "unmount") expect(current.name).toBe("Keep later editor");
  });

test("held original archive download retires on a source change", async ({
  page,
}) => {
  const card = await open(page);
  await selectDefinition(card);
  const gate = await held(page, base + "/export");
  let downloads = 0;
  page.on("download", () => downloads++);
  try {
    await card
      .getByRole("button", {
        name: "Export original activity archive",
        exact: true,
      })
      .click();
    await gate.started;
    await page
      .getByLabel("Program name", { exact: true })
      .fill("Changed while exporting");
  } finally {
    await gate.release();
  }
  await expect(
    card.getByRole("button", { name: "Reload activity criteria", exact: true }),
  ).toBeEnabled();
  expect(downloads).toBe(0);
});

for (const fault of ["profile", "alias", "source"])
  test(`corrupt catalog ${fault} refuses named output force authority`, async ({
    page,
  }) => {
    await page.route("**" + base + "/catalog", async (route) => {
      const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 }),
        raw = await response.body(),
        body = JSON.parse(raw.toString());
      await retain("original-catalog-before-forgery", raw);
      if (fault === "profile") body.profile_sha256 = "0".repeat(64);
      else if (fault === "source") body.source_sha256 = "0".repeat(64);
      else body.bindings.outputs[0].alias_node_id = "request0";
      await retain("delivered-forged-catalog", JSON.stringify(body));
      await route.fulfill({ response, json: body });
    });
    const card = await open(page);
    await expect(card.getByRole("alert")).toBeVisible();
    await page.getByRole("button", { name: "Program", exact: true }).click();
    await page.locator('.react-flow__node[data-id="use0"]').click();
    await expect(
      page.getByRole("button", { name: "Hold simulation value", exact: true }),
    ).toHaveCount(0);
  });

test("same-ID source-only numeric conflict returns422 and preserves exact current editor", async ({
  page,
}) => {
  const card = await open(page, "conflict"),
    before = await editor(page);
  await library(page);
  await capture(
    page,
    base + "/import",
    () =>
      card
        .getByLabel("Import activity bundle file", { exact: true })
        .setInputFiles({
          name: "original.json",
          mimeType: "application/json",
          buffer: fixture("bundle"),
        }),
    422,
  );
  await expect(card.getByRole("alert")).toContainText("conflict");
  expect(await editor(page)).toEqual(before);
});

test("forged migration descriptor refuses review before replacement confirmation", async ({
  page,
}) => {
  await open(page, "legacy");
  await page.route(
    "**" + base + "/migration/preview",
    async (route) => {
      const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 }),
        raw = await response.body(),
        body = JSON.parse(raw.toString());
      await retain("original-migration-before-descriptor-forgery", raw);
      body.programs[0].canonical_sha256 = "0".repeat(64);
      await route.fulfill({ response, json: body });
    },
    { times: 1 },
  );
  await page
    .getByRole("button", {
      name: "Review migration to activities",
      exact: true,
    })
    .click();
  await expect(
    page
      .getByRole("region", {
        name: "Multi-output activity migration",
        exact: true,
      })
      .getByRole("alert"),
  ).toBeVisible();
  await expect(
    page.getByRole("button", {
      name: "Apply reviewed activity migration",
      exact: true,
    }),
  ).toHaveCount(0);
});

test("archive bytes with a valid delivery hash but different reviewed source are refused", async ({
  page,
}) => {
  const card = await open(page);
  await selectDefinition(card);
  let downloads = 0;
  page.on("download", () => downloads++);
  await page.route(
    "**" + base + "/export",
    async (route) => {
      const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 }),
        raw = await response.body(),
        body = JSON.parse(raw.toString());
      await retain("original-archive-before-context-forgery", raw);
      body.library.definitions[0].name = "Wrong same-format archive";
      const forged = Buffer.from(JSON.stringify(body));
      await retain("delivered-forged-archive", forged);
      await route.fulfill({
        response,
        body: forged,
        headers: { ...response.headers(), "x-file-sha256": sha(forged) },
      });
    },
    { times: 1 },
  );
  await card
    .getByRole("button", {
      name: "Export original activity archive",
      exact: true,
    })
    .click();
  await expect(card.getByRole("alert")).toContainText("SHA-256");
  expect(downloads).toBe(0);
});

test("failed current criteria reload retires a held alias and session before fresh recovery", async ({
  page,
}) => {
  await open(page);
  await page.getByRole("button", { name: "Program", exact: true }).click();
  await page.locator('.react-flow__node[data-id="use0"]').click();
  const port = page.getByRole("region", {
    name: "Activity output first",
    exact: true,
  });
  await port.getByLabel("Simulation force value", { exact: true }).fill("83");
  await port
    .getByRole("button", { name: "Hold simulation value", exact: true })
    .click();
  const previous = await step(page);
  expect(previous.last.outputs).toEqual({ value0: 83, active0: false });
  expect(Object.keys(previous.snapshot.forces)).toHaveLength(1);
  const card = await library(page);
  await page.route(
    "**" + base + "/catalog",
    async (route) => {
      const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 }),
        raw = await response.body();
      expect(response.status()).toBe(200);
      await retain(
        "original-failed-reload-request",
        route.request().postDataBuffer()!,
      );
      await retain("original-success-before-delivery-failure", raw);
      const failure = JSON.stringify({
        detail: "Fixture delivery: current criteria unavailable",
      });
      await retain("delivered-current-catalog-failure", failure);
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: failure,
      });
    },
    { times: 1 },
  );
  await card
    .getByRole("button", { name: "Reload activity criteria", exact: true })
    .click();
  await expect(card.getByRole("alert")).toContainText(
    "current criteria unavailable",
  );
  await page.getByRole("button", { name: "Program", exact: true }).click();
  await page.locator('.react-flow__node[data-id="use0"]').click();
  await expect(
    page.getByRole("button", { name: "Step simulation", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByTitle("Run simulation", { exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Hold simulation value", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Scenarios", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Run scenario", exact: true }),
  ).toBeDisabled();
  const current = await library(page);
  await capture(page, base + "/catalog", () =>
    current
      .getByRole("button", { name: "Reload activity criteria", exact: true })
      .click(),
  );
  const recovered = await step(page);
  expect(recovered.session).not.toBe(previous.session);
  expect(recovered.snapshot.time).toBe(1);
  expect(recovered.snapshot.forces).toEqual({});
  expect(recovered.last.outputs).toEqual({ value0: 10, active0: false });
});

test("activity mixed outputs compile and execute through the existing Temco web profile", async ({
  page,
}) => {
  await open(page);
  await page.getByRole("button", { name: "Temco native", exact: true }).click();
  const panel = page.locator(".temco-simulator");
  await expect(panel).toContainText("Native compiler available");
  await expect(panel.getByRole("alert")).toHaveCount(0);
  const raw = await capture(page, "/api/temco/compile", () =>
    panel
      .getByRole("button", { name: "Compile Control Basic", exact: true })
      .click(),
  );
  const compiled = JSON.parse(raw.toString());
  expect(compiled.source).toContain("BMS STUDIO CONTROL BASIC");
  const pending = page.waitForEvent("download");
  await panel
    .getByRole("button", { name: "Download Temco bytecode", exact: true })
    .click();
  const bytes = readFileSync((await (await pending).path())!);
  expect(bytes).toEqual(Buffer.from(compiled.bytecode_base64, "base64"));
  expect(bytes.length).toBeGreaterThan(9);
  expect(bytes.length).toBeLessThan(2000);
  await retain("original-temco-bytecode-download", bytes);
  await panel.getByLabel("Native scan count", { exact: true }).fill("3");
  const checked = await capture(page, "/api/temco/verify", () =>
    panel
      .getByRole("button", { name: "Run native verification", exact: true })
      .click(),
  );
  const result = JSON.parse(checked.toString());
  expect(result.matches_reference).toBe(true);
  expect(result.outputs).toEqual({ value0: 30, active0: true });
  expect(result.history.map((r: any) => r.outputs)).toEqual([
    { value0: 10, active0: false },
    { value0: 20, active0: false },
    { value0: 30, active0: true },
  ]);
  await expect(
    panel.getByRole("region", {
      name: "Native verification results",
      exact: true,
    }),
  ).toContainText("Matched native/reference outputs");
  expect(
    (await (await page.request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
});
