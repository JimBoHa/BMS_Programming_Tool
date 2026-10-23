import {
  test,
  expect,
  simulationServerResponseJSON,
  simulationServerResponseText,
  type Page,
  type Locator,
} from "./simulationFixture";
import { projectedSourceFixture } from "./sourceTransportFixtures";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
const root = fileURLToPath(new URL("../..", import.meta.url)),
  python = path.join(root, ".venv/bin/python"),
  base = "/api/macros/templates/cancelable-pulse";
const environment = () => ({
  ...process.env,
  PYTHONPATH: path.join(root, "backend"),
});
const sha = (body: Buffer) => createHash("sha256").update(body).digest("hex");
async function retained(name: string, body: Buffer | string) {
  await test.info().attach(name, { body, contentType: "application/json" });
}
function source(script: string, body: Buffer | string) {
  return execFileSync(python, ["-c", script], {
    cwd: root,
    env: environment(),
    input: body,
  });
}
async function load(page: Page, body: Buffer) {
  await page.getByRole("button", { name: "Program", exact: true }).click();
  await page.locator('input[type=file][accept*=".st"]').setInputFiles({
    name: "pulse-source.json",
    mimeType: "application/json",
    buffer: body,
  });
  await expect(page.locator(".toast")).toContainText(
    "Imported as a new local project",
  );
}
async function open(page: Page, scan = 1) {
  await page.goto("/");
  const body = execFileSync(
    python,
    [
      "-c",
      "import sys;from bms_tool.models import Program,Node;p=Program(id='pulse-browser',name='Pulse source editor',scan_seconds=int(sys.argv[1]),nodes=[Node(id='request',kind='Input',label='Logical request',value_type='boolean',params={'default':False})],metadata={'original_source':{'signed_zero':-0.0,'small':1e-6,'integer':0}});print(p.model_dump_json())",
      String(scan),
    ],
    { cwd: root, env: environment() },
  );
  await load(page, body);
  return macros(page);
}
async function macros(page: Page) {
  await page.getByRole("button", { name: "Macros", exact: true }).click();
  const card = page.getByRole("region", {
    name: "Cancelable pulse template",
    exact: true,
  });
  await expect(
    card.getByRole("button", { name: "Preview cancelable pulse", exact: true }),
  ).toBeEnabled();
  return card;
}
async function capture(
  page: Page,
  endpoint: string,
  action: () => Promise<void>,
  status = 200,
) {
  let raw: Buffer | undefined;
  await page.route(
    "**" + endpoint,
    async (route) => {
      const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 });
      expect(response.status()).toBe(status);
      raw = await response.body();
      await retained(
        "original-" + endpoint.split("/").at(-1) + "-request",
        route.request().postDataBuffer()!,
      );
      await route.fulfill({ response, body: raw });
    },
    { times: 1 },
  );
  await action();
  await expect.poll(() => raw !== undefined).toBe(true);
  await retained("original-" + endpoint.split("/").at(-1) + "-response", raw!);
  return raw!;
}
async function preview(page: Page, card: Locator, duration = 5, scan = 1) {
  await card
    .getByLabel("Pulse duration seconds", { exact: true })
    .fill(String(duration));
  await card
    .getByLabel("Pulse scan seconds", { exact: true })
    .fill(String(scan));
  const raw = await capture(page, base + "/preview", () =>
    card
      .getByRole("button", { name: "Preview cancelable pulse", exact: true })
      .click(),
  );
  await expect(
    card.getByRole("region", { name: "Cancelable pulse preview", exact: true }),
  ).toBeVisible();
  return { raw, data: projectedSourceFixture(JSON.parse(raw.toString())) };
}
async function exportedEditor(page: Page) {
  await page.getByRole("button", { name: "Program", exact: true }).click();
  await page.getByLabel("Export format", { exact: true }).selectOption("json");
  const waiting = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export", exact: true }).click();
  return readFileSync((await (await waiting).path())!);
}
async function download(page: Page, card: Locator, kind: "review" | "bundle") {
  let raw: Buffer | undefined,
    header = "";
  await page.route(
    "**" + base + "/export",
    async (route) => {
      const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 });
      raw = await response.body();
      header = response.headers()["x-file-sha256"];
      await retained(
        "original-" + kind + "-request",
        route.request().postDataBuffer()!,
      );
      await route.fulfill({ response, body: raw });
    },
    { times: 1 },
  );
  const waiting = page.waitForEvent("download");
  await card
    .getByRole("button", {
      name:
        kind === "review"
          ? "Download original pulse review"
          : "Download original pulse bundle",
      exact: true,
    })
    .click();
  const file = await waiting,
    body = readFileSync((await file.path())!);
  expect(body).toEqual(raw);
  expect(sha(body)).toBe(header);
  await retained("original-" + kind + "-upstream", raw!);
  await retained("original-" + kind + "-download", body);
  await retained("original-" + kind + "-header", header);
  return body;
}
async function step(page: Page) {
  const waiting = page.waitForResponse(
    (r) => new URL(r.url()).pathname === "/api/simulation/step",
  );
  await page
    .getByRole("button", { name: "Step simulation", exact: true })
    .click();
  const response = await waiting;
  expect(response.status()).toBe(200);
  const raw = simulationServerResponseText(response);
  await retained("original-pulse-simulation", raw);
  return simulationServerResponseJSON(response);
}
async function held(page: Page, endpoint: string) {
  let seen!: () => void, release!: () => void, done!: () => void;
  const incoming = new Promise<void>((r) => (seen = r)),
    gate = new Promise<void>((r) => (release = r)),
    finished = new Promise<void>((r) => (done = r));
  await page.route("**" + endpoint, async (route) => {
    const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 }),
      raw = await response.body();
    await retained("original-held-" + endpoint.split("/").at(-1), raw);
    seen();
    await gate;
    await route.fulfill({ response, body: raw });
    done();
  });
  return { incoming, release, finished };
}

for (const [duration, scan] of [
  [5, 1],
  [1, 1],
  [6, 3],
])
  test(`original pulse D${duration} h${scan} import simulation and interchange lifecycle`, async ({
    page,
  }) => {
    const card = await open(page, scan);
    let saves = 0;
    page.on("request", (r) => {
      if (
        new URL(r.url()).pathname === "/api/projects" &&
        r.method() === "POST"
      )
        saves++;
    });
    const beforePower = await (
        await page.request.get("/api/operation-power")
      ).json(),
      report = await preview(page, card, duration, scan);
    expect(report.data.program.nodes).toHaveLength(6);
    expect(report.data.program.edges).toHaveLength(6);
    await expect(
      card
        .getByRole("table", { name: "Pulse ordinary graph", exact: true })
        .locator("tbody tr"),
    ).toHaveCount(6);
    await download(page, card, "review");
    expect(sha(await download(page, card, "bundle"))).toBe(
      report.data.bundle_sha256,
    );
    page.once("dialog", (d) => d.accept());
    const imported = await capture(page, base + "/import", () =>
      card
        .getByRole("button", {
          name: "Import reviewed pulse definition",
          exact: true,
        })
        .click(),
    );
    await expect(page.locator(".macro-count")).toHaveText("1 definition");
    await expect(page.locator(".macro-interface .macro-port code")).toHaveCount(
      1,
    );
    expect(saves).toBe(0);
    const added = await capture(page, "/api/macros/instantiate", () =>
      page
        .getByRole("button", { name: "Add instance to program", exact: true })
        .click(),
    );
    const wired = source(
      "import json,sys;from bms_tool.models import Program,Node,Edge;e=json.load(sys.stdin);p=Program.model_validate(json.loads(e['source_json']));m=next(n.id for n in p.nodes if n.kind=='Macro');p.nodes.append(Node(id='pulse_result',kind='Output',value_type='boolean'));p.edges=[Edge(id='request_wire',source='request',target=m,target_port='request'),Edge(id='pulse_wire',source=m,target='pulse_result')];print(p.model_dump_json())",
      added,
    );
    await load(page, wired);
    await page.getByLabel("Simulate request", { exact: true }).check();
    let row = await step(page);
    expect(row.last.outputs).toEqual({ pulse_result: true });
    if (duration === 5) {
      const previous = row.snapshot;
      await page.getByLabel("Simulate request", { exact: true }).uncheck();
      await page
        .getByLabel("Quality request", { exact: true })
        .selectOption("stale");
      const fault = await step(page);
      expect(fault.scan_error).toContain("stale");
      expect(fault.snapshot).toEqual(previous);
      expect(fault.snapshot.outputs).toEqual({ pulse_result: true });
      await page
        .getByLabel("Quality request", { exact: true })
        .selectOption("good");
      row = await step(page);
      expect(row.last.outputs).toEqual({ pulse_result: false });
      await page.getByLabel("Simulate request", { exact: true }).check();
      row = await step(page);
      expect(row.last.outputs).toEqual({ pulse_result: true });
    }
    for (let i = 1; i <= duration / scan; i++) row = await step(page);
    expect(row.last.outputs).toEqual({ pulse_result: false });
    await page.getByTitle("Reset simulation", { exact: true }).click();
    row = await step(page);
    expect(row.last.outputs).toEqual({ pulse_result: true });
    const interchanges: Record<string, string> = {};
    let exportedSource: Buffer | undefined;
    for (const format of ["json", "st", "plcopen", "graphml"]) {
      await page
        .getByLabel("Export format", { exact: true })
        .selectOption(format);
      const waiting = page.waitForEvent("download");
      await page.getByRole("button", { name: "Export", exact: true }).click();
      const file = await waiting,
        raw = readFileSync((await file.path())!);
      interchanges[file.suggestedFilename()] = raw.toString("base64");
      if (format === "json") exportedSource = raw;
      await retained("original-pulse-interchange-" + format, raw);
    }
    source(
      "import base64,json,sys;from bms_tool.models import Program;from bms_tool.formats import import_program;v=json.load(sys.stdin);p=Program.model_validate_json(v['program']);[(_ for _ in ()).throw(AssertionError(name))if import_program(base64.b64decode(raw),name).digest()!=p.digest()else None for name,raw in v['files'].items()];print('all4original interchange bodies restore the exact Program digest')",
      JSON.stringify({
        program: exportedSource!.toString(),
        files: interchanges,
      }),
    );
    if (duration === 5) {
      const saved = await capture(page, "/api/projects", () =>
        page
          .getByRole("button", { name: "Save revision", exact: true })
          .click(),
      );
      const p = projectedSourceFixture(JSON.parse(saved.toString()));
      expect(p.revision).toBe(1);
      await expect(
        page.getByLabel("Last saved revision", { exact: true }),
      ).toContainText("r1");
      const restored = await page.request.get("/api/projects/" + p.id);
      expect(restored.status()).toBe(200);
      await retained("original-saved-pulse-http", await restored.body());
      expect(saves).toBe(1);
    } else expect(saves).toBe(0);
    await retained("original-pulse-imported-parent", imported);
    const afterPower = await (
      await page.request.get("/api/operation-power")
    ).json();
    expect(afterPower.active).toEqual(beforePower.active);
    expect(afterPower.recent).toEqual(beforePower.recent);
    expect(
      (await (await page.request.get("/api/session")).json())
        .field_network_open,
    ).toBe(false);
  });

for (const kind of [
  "preview-source",
  "export-discard",
  "import-discard",
  "import-unmount",
  "import-source",
])
  test(`held ${kind} cannot adopt or download a stale pulse`, async ({
    page,
  }) => {
    let card = await open(page),
      before: Buffer | undefined;
    if (kind.startsWith("import")) {
      before = await exportedEditor(page);
      card = await macros(page);
    }
    if (!kind.startsWith("preview")) await preview(page, card);
    const endpoint = kind.startsWith("import")
        ? base + "/import"
        : base + "/" + kind.split("-")[0],
      gate = await held(page, endpoint);
    let downloads = 0;
    page.on("download", () => downloads++);
    try {
      if (kind.startsWith("import")) page.once("dialog", (d) => d.accept());
      await card
        .getByRole("button", {
          name: kind.startsWith("preview")
            ? "Preview cancelable pulse"
            : kind.startsWith("export")
              ? "Download original pulse bundle"
              : "Import reviewed pulse definition",
          exact: true,
        })
        .click();
      await gate.incoming;
      if (kind.endsWith("source"))
        await page
          .getByLabel("Program name", { exact: true })
          .fill("Changed pulse source");
      else if (kind === "import-unmount")
        await page
          .getByRole("button", { name: "Program", exact: true })
          .click();
      else
        await card
          .getByRole("button", {
            name: "Discard pending pulse response",
            exact: true,
          })
          .click();
      gate.release();
      await gate.finished;
      if (kind === "import-unmount") card = await macros(page);
      if (kind.startsWith("import")) {
        await expect(page.locator(".macro-count")).toHaveText("0 definitions");
        const after = await exportedEditor(page);
        if (kind === "import-source")
          source(
            "import json,sys;v=json.load(sys.stdin);a=json.loads(v['before']);b=json.loads(v['after']);a['name']='Changed pulse source';assert a==b;assert '-0.0'in v['after'];print('only deliberate current-source name changed')",
            JSON.stringify({
              before: before!.toString(),
              after: after.toString(),
            }),
          );
        else expect(after).toEqual(before);
        await retained("original-stale-pulse-editor-before", before!);
        await retained("original-stale-pulse-editor-after", after);
      } else
        await expect(
          card.getByRole("button", {
            name: "Import reviewed pulse definition",
            exact: true,
          }),
        ).toHaveCount(0);
      expect(downloads).toBe(kind.startsWith("import") ? 1 : 0);
    } finally {
      gate.release();
    }
  });

test("dismissed pulse import confirmation leaves current editor and revision untouched", async ({
  page,
}) => {
  let card = await open(page);
  const before = await exportedEditor(page);
  card = await macros(page);
  await preview(page, card);
  let imports = 0;
  page.on("request", (r) => {
    if (new URL(r.url()).pathname === base + "/import") imports++;
  });
  page.once("dialog", (d) => d.dismiss());
  await card
    .getByRole("button", {
      name: "Import reviewed pulse definition",
      exact: true,
    })
    .click();
  expect(imports).toBe(0);
  await expect(page.locator(".macro-count")).toHaveText("0 definitions");
  expect(await exportedEditor(page)).toEqual(before);
});

test("parent clock and blank or nonaligned declarations refuse before preview then recover", async ({
  page,
}) => {
  const card = await open(page, 3);
  let previews = 0;
  page.on("request", (r) => {
    if (new URL(r.url()).pathname === base + "/preview") previews++;
  });
  for (const [d, h] of [
    ["5", "1"],
    ["5", "3"],
    ["", "3"],
    ["6", "0.5"],
  ]) {
    await card.getByLabel("Pulse duration seconds", { exact: true }).fill(d);
    await card.getByLabel("Pulse scan seconds", { exact: true }).fill(h);
    await card
      .getByRole("button", { name: "Preview cancelable pulse", exact: true })
      .click();
    await expect(card.getByRole("alert")).toBeVisible();
  }
  expect(previews).toBe(0);
  await preview(page, card, 6, 3);
  expect(previews).toBe(1);
  await page.getByRole("button", { name: "Program", exact: true }).click();
  await page.getByTitle("Program settings", { exact: true }).click();
  await page.getByLabel("Scan interval (seconds)", { exact: true }).fill("2");
  await page.getByLabel("Close settings", { exact: true }).click();
  const afterClock = await macros(page);
  await expect(
    afterClock.getByRole("button", {
      name: "Import reviewed pulse definition",
      exact: true,
    }),
  ).toHaveCount(0);
  await afterClock
    .getByRole("button", { name: "Preview cancelable pulse", exact: true })
    .click();
  await expect(afterClock.getByRole("alert")).toBeVisible();
  expect(previews).toBe(1);
  await preview(page, afterClock, 6, 2);
  expect(previews).toBe(2);
});

for (const kind of ["manifest", "descriptor", "parent-reference"])
  test(`source-bound ${kind} corruption refuses pulse preview`, async ({
    page,
  }) => {
    const card = await open(page);
    await page.route("**" + base + "/preview", async (route) => {
      const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 }),
        raw = await response.body();
      await retained("original-before-forged-" + kind, raw);
      const forged = execFileSync(
        python,
        [
          "-c",
          `import json,sys,hashlib
from bms_tool.models import Program
e=json.load(sys.stdin);v=json.loads(e['source_json']);mode=sys.argv[1]
if mode=='manifest':
 for p in [v['program'],v['bundle']['library']['definitions'][0]['program']]:next(n for n in p['nodes']if n['id']=='elapsed')['params']['seconds']=6
if mode=='parent-reference':v['parent_reference']['revision']+=1
if mode=='descriptor':e['programs'][0]['canonical_sha256']='0'*64
def c(x):return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
if mode=='manifest':
 v['program_sha256']=Program.model_validate(v['program']).digest();v['definition_sha256']=hashlib.sha256(c(v['bundle']['library']['definitions'][0])).hexdigest();v['bundle_sha256']=hashlib.sha256(c(v['bundle'])).hexdigest()
 for item in e['programs']:item['canonical_sha256']=v['program_sha256']
e['source_json']=c(v).decode();e['source_sha256']=hashlib.sha256(e['source_json'].encode()).hexdigest();print(json.dumps(e))`,
          kind,
        ],
        { cwd: root, env: environment(), input: raw },
      );
      await route.fulfill({ response, body: forged });
    });
    await card
      .getByRole("button", { name: "Preview cancelable pulse", exact: true })
      .click();
    await expect(card.getByRole("alert")).toBeVisible();
    await expect(
      card.getByRole("button", {
        name: "Import reviewed pulse definition",
        exact: true,
      }),
    ).toHaveCount(0);
  });

test("failed pulse criteria reload clears old review and cannot authorize import", async ({
  page,
}) => {
  const card = await open(page);
  await preview(page, card);
  await page.route("**" + base + "/catalog", async (route) => {
    const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 }),
      raw = await response.body();
    await retained("original-before-forged-catalog", raw);
    const value = JSON.parse(raw.toString());
    value.profile.semantics.phase += " altered";
    await route.fulfill({ response, json: value });
  });
  await card
    .getByRole("button", {
      name: "Reload pulse template criteria",
      exact: true,
    })
    .click();
  await expect(card.getByRole("alert")).toBeVisible();
  await expect(
    card.getByRole("button", { name: "Preview cancelable pulse", exact: true }),
  ).toBeDisabled();
  await expect(
    card.getByRole("button", {
      name: "Import reviewed pulse definition",
      exact: true,
    }),
  ).toHaveCount(0);
  await page.unroute("**" + base + "/catalog");
  await card
    .getByRole("button", {
      name: "Reload pulse template criteria",
      exact: true,
    })
    .click();
  await expect(
    card.getByRole("button", { name: "Preview cancelable pulse", exact: true }),
  ).toBeEnabled();
  await preview(page, card);
});

test("wrong original pulse export byte digest prevents download", async ({
  page,
}) => {
  const card = await open(page);
  await preview(page, card);
  let downloads = 0;
  page.on("download", () => downloads++);
  await page.route("**" + base + "/export", async (route) => {
    const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 }),
      raw = await response.body();
    await retained("original-before-wrong-pulse-header", raw);
    await route.fulfill({
      response,
      body: raw,
      headers: { ...response.headers(), "x-file-sha256": "0".repeat(64) },
    });
  });
  await card
    .getByRole("button", {
      name: "Download original pulse bundle",
      exact: true,
    })
    .click();
  await expect(card.getByRole("alert")).toBeVisible();
  expect(downloads).toBe(0);
});

test("fresh parent review reuses an identical pulse definition and refuses a later edited same-ID collision", async ({
  page,
}) => {
  let card = await open(page),
    first = await preview(page, card);
  page.once("dialog", (d) => d.accept());
  const once = await capture(page, base + "/import", () =>
    card
      .getByRole("button", {
        name: "Import reviewed pulse definition",
        exact: true,
      })
      .click(),
  );
  await expect(page.locator(".macro-count")).toHaveText("1 definition");
  const second = await preview(page, card);
  expect(second.data.parent_reference.program_sha256).not.toBe(
    first.data.parent_reference.program_sha256,
  );
  expect(second.data.bundle_sha256).toBe(first.data.bundle_sha256);
  expect(second.data.program_sha256).toBe(first.data.program_sha256);
  page.once("dialog", (d) => d.accept());
  const twice = await capture(page, base + "/import", () =>
    card
      .getByRole("button", {
        name: "Import reviewed pulse definition",
        exact: true,
      })
      .click(),
  );
  expect(JSON.parse(twice.toString()).source_json).toBe(
    JSON.parse(once.toString()).source_json,
  );
  const edited = source(
    "import json,sys;from bms_tool.models import Program;p=Program.model_validate(json.loads(json.load(sys.stdin)['source_json']));next(n for n in p.metadata['macros']['definitions'][0]['program']['nodes']if n['id']=='elapsed')['params']['seconds']=6;print(p.model_dump_json())",
    twice,
  );
  await retained("original-edited-pulse-definition", edited);
  await load(page, edited);
  const before = await exportedEditor(page);
  card = await macros(page);
  await preview(page, card);
  page.once("dialog", (d) => d.accept());
  await capture(
    page,
    base + "/import",
    () =>
      card
        .getByRole("button", {
          name: "Import reviewed pulse definition",
          exact: true,
        })
        .click(),
    422,
  );
  await expect(page.locator(".macro-error")).toContainText(
    "identifier conflict",
  );
  const after = await exportedEditor(page);
  expect(after).toEqual(before);
  await retained("original-conflict-pulse-editor-before", before);
  await retained("original-conflict-pulse-editor-after", after);
});
