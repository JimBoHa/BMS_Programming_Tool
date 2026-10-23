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
  base = "/api/macros/templates/sum8",
  environment = () => ({
    ...process.env,
    PYTHONPATH: path.join(root, "backend"),
  }),
  sha = (v: Buffer) => createHash("sha256").update(v).digest("hex");
const units = ["", "A", "kW", "cfm", "L/s"];
async function retained(name: string, body: Buffer | string) {
  await test.info().attach(name, { body, contentType: "application/json" });
}
function pythonSource(script: string, body: Buffer | string) {
  return execFileSync(python, ["-c", script], {
    cwd: root,
    env: environment(),
    input: body,
  });
}
async function load(page: Page, body: Buffer) {
  await page.getByRole("button", { name: "Program", exact: true }).click();
  await page.locator('input[type=file][accept*=".st"]').setInputFiles({
    name: "sum-source.json",
    mimeType: "application/json",
    buffer: body,
  });
  await expect(page.locator(".toast")).toContainText(
    "Imported as a new local project",
  );
}
async function open(page: Page, unit = "") {
  await page.goto("/");
  return openSeed(page, unit);
}
async function openSeed(page: Page, unit: string) {
  const body = execFileSync(
    python,
    [
      "-c",
      "import sys;from bms_tool.models import Program,Node;p=Program(id='sum-browser',name='Sum source editor',nodes=[Node(id='v'+str(i),kind='Input',unit=sys.argv[1],params={'default':float(i)},x=40,y=i*100) for i in range(1,9)]+[Node(id='total',kind='Output',unit=sys.argv[1],x=1300,y=300)]);print(p.model_dump_json())",
      unit,
    ],
    { cwd: root, env: environment() },
  );
  await load(page, body);
  await page.getByRole("button", { name: "Macros", exact: true }).click();
  const card = page.getByRole("region", {
    name: "Eight-input sum template",
    exact: true,
  });
  await expect(
    card.getByLabel("Sum template units", { exact: true }),
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
      const r = await route.fetch({ maxRetries: 0, maxRedirects: 0 });
      expect(r.status()).toBe(status);
      raw = await r.body();
      await route.fulfill({ response: r, body: raw });
    },
    { times: 1 },
  );
  await action();
  await expect.poll(() => raw !== undefined).toBe(true);
  await retained("original-" + endpoint.split("/").at(-1) + "-response", raw!);
  return raw!;
}
async function preview(page: Page, card: Locator, unit: string) {
  await card
    .getByLabel("Sum template units", { exact: true })
    .selectOption(unit);
  const raw = await capture(page, base + "/preview", () =>
    card
      .getByRole("button", { name: "Preview eight-input sum", exact: true })
      .click(),
  );
  await expect(
    card.getByRole("region", { name: "Eight-input sum preview", exact: true }),
  ).toBeVisible();
  return { raw, data: projectedSourceFixture(JSON.parse(raw.toString())) };
}
async function download(
  page: Page,
  card: Locator,
  format: "review" | "bundle",
) {
  let raw: Buffer | undefined,
    header = "";
  await page.route(
    "**" + base + "/export",
    async (route) => {
      const r = await route.fetch({ maxRetries: 0, maxRedirects: 0 });
      raw = await r.body();
      header = r.headers()["x-file-sha256"];
      await route.fulfill({ response: r, body: raw });
    },
    { times: 1 },
  );
  const waiting = page.waitForEvent("download");
  await card
    .getByRole("button", {
      name:
        format === "review"
          ? "Download original sum review"
          : "Download original sum bundle",
      exact: true,
    })
    .click();
  const file = await waiting,
    bytes = readFileSync((await file.path())!);
  expect(bytes).toEqual(raw);
  expect(sha(bytes)).toBe(header);
  await retained("original-" + format + "-upstream", raw!);
  await retained("original-" + format + "-download", bytes);
  await retained("original-" + format + "-header", header);
  return bytes;
}
async function imported(page: Page, card: Locator) {
  page.once("dialog", (d) => d.accept());
  const raw = await capture(page, "/api/macros/import", () =>
    card
      .getByRole("button", {
        name: "Import reviewed sum definition",
        exact: true,
      })
      .click(),
  );
  await expect(page.locator(".macro-count")).toHaveText("1 definition");
  return raw;
}
async function exportEditor(page: Page) {
  await page.getByRole("button", { name: "Program", exact: true }).click();
  await page.getByLabel("Export format", { exact: true }).selectOption("json");
  const waiting = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export", exact: true }).click();
  return readFileSync((await (await waiting).path())!);
}
async function held(page: Page, endpoint: string) {
  let seen!: () => void, release!: () => void, done!: () => void;
  const incoming = new Promise<void>((r) => (seen = r)),
    gate = new Promise<void>((r) => (release = r)),
    finished = new Promise<void>((r) => (done = r));
  await page.route("**" + endpoint, async (route) => {
    const r = await route.fetch({ maxRetries: 0, maxRedirects: 0 }),
      body = await r.body();
    await retained("original-held-" + endpoint.split("/").at(-1), body);
    seen();
    await gate;
    await route.fulfill({ response: r, body });
    done();
  });
  return { incoming, release, finished };
}

for (const unit of units)
  test(`preview original exports import and instantiate eight required ${unit || "dimensionless"} ports`, async ({
    page,
  }) => {
    const card = await open(page, unit);
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
      report = await preview(page, card, unit);
    expect(report.data.program.nodes).toHaveLength(16);
    expect(report.data.program.edges).toHaveLength(15);
    expect(report.data.inputs).toHaveLength(8);
    expect(report.data.can_import).toBe(true);
    await expect(
      card
        .getByRole("table", { name: "Sum template ports", exact: true })
        .locator("tbody tr"),
    ).toHaveCount(9);
    await download(page, card, "review");
    const bundle = await download(page, card, "bundle");
    expect(sha(bundle)).toBe(report.data.bundle_sha256);
    await imported(page, card);
    await expect(page.locator(".macro-interface .macro-port code")).toHaveCount(
      8,
    );
    await expect(page.locator(".macro-stat-row")).toContainText(
      "16 internal blocks",
    );
    const added = await capture(page, "/api/macros/instantiate", () =>
      page
        .getByRole("button", { name: "Add instance to program", exact: true })
        .click(),
    );
    await page.getByRole("button", { name: "Program", exact: true }).click();
    const graph = projectedSourceFixture(JSON.parse(added.toString())),
      instance = graph.nodes.find((n: any) => n.kind === "Macro");
    expect(instance.params.definition).toBe(report.data.definition_id);
    await expect(
      page.locator(
        `.react-flow__node[data-id="${instance.id}"] .react-flow__handle-left`,
      ),
    ).toHaveCount(8);
    expect(saves).toBe(0);
    if (unit === "") {
      const wired = pythonSource(
        "import json,sys;from bms_tool.models import Program,Edge;e=json.load(sys.stdin);p=Program.model_validate(json.loads(e['source_json']));m=next(n.id for n in p.nodes if n.kind=='Macro');p.edges=[Edge(id='w'+str(i),source='v'+str(i),target=m,target_port='i'+str(i)) for i in range(1,9)]+[Edge(id='publish',source=m,target='total')];print(p.model_dump_json())",
        added,
      );
      await load(page, wired);
      const waiting = page.waitForResponse(
        (r) => new URL(r.url()).pathname === "/api/simulation/step",
      );
      await page
        .getByRole("button", { name: "Step simulation", exact: true })
        .click();
      const response = await waiting;
      expect(response.status()).toBe(200);
      const simulated = simulationServerResponseJSON(response);
      expect(simulated.last.outputs).toEqual({ total: 36 });
      await retained(
        "original-wired-simulation",
        simulationServerResponseText(response),
      );
      await page
        .getByLabel("Quality v3", { exact: true })
        .selectOption("stale");
      const faultWait = page.waitForResponse(
        (r) => new URL(r.url()).pathname === "/api/simulation/step",
      );
      await page
        .getByRole("button", { name: "Step simulation", exact: true })
        .click();
      const fault = await faultWait;
      expect(
        simulationServerResponseJSON(fault).history.at(-1).outputs,
      ).toEqual({ total: 36 });
      expect(simulationServerResponseJSON(fault).scan_error).toContain("stale");
      await retained(
        "original-wired-rollback",
        simulationServerResponseText(fault),
      );
      const saved = await capture(page, "/api/projects", () =>
        page
          .getByRole("button", { name: "Save revision", exact: true })
          .click(),
      );
      const savedProgram = projectedSourceFixture(JSON.parse(saved.toString()));
      expect(savedProgram.revision).toBe(1);
      await expect(
        page.getByLabel("Last saved revision", { exact: true }),
      ).toContainText("r1");
      const restored = await page.request.get(
        "/api/projects/" + savedProgram.id,
      );
      expect(restored.status()).toBe(200);
      await retained("original-saved-sum-project-http", await restored.body());
      expect(saves).toBe(1);
      await retained("original-saved-sum-project", saved);
    }
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

test("unit choice is explicit and dismissed import confirmation leaves the current editor untouched", async ({
  page,
}) => {
  const card = await open(page);
  await expect(
    card.getByLabel("Sum template units", { exact: true }),
  ).toHaveValue("__choose__");
  await expect(
    card.getByRole("button", { name: "Preview eight-input sum", exact: true }),
  ).toBeDisabled();
  let imports = 0;
  page.on("request", (r) => {
    if (new URL(r.url()).pathname === "/api/macros/import") imports++;
  });
  await preview(page, card, "");
  let message = "";
  page.once("dialog", async (d) => {
    message = d.message();
    await d.dismiss();
  });
  await card
    .getByRole("button", {
      name: "Import reviewed sum definition",
      exact: true,
    })
    .click();
  expect(message).toContain("Sum source editor");
  expect(imports).toBe(0);
  await expect(page.locator(".macro-count")).toHaveText("0 definitions");
  await expect(
    card.getByRole("region", { name: "Eight-input sum preview", exact: true }),
  ).toBeVisible();
});
for (const kind of [
  "preview-source",
  "export-discard",
  "import-discard",
  "import-unmount",
])
  test(`held ${kind} cannot adopt a stale sum definition or download`, async ({
    page,
  }) => {
    let card = await open(page),
      before: Buffer | undefined;
    if (kind.startsWith("import")) {
      before = await exportEditor(page);
      await page.getByRole("button", { name: "Macros", exact: true }).click();
      card = page.getByRole("region", {
        name: "Eight-input sum template",
        exact: true,
      });
      await expect(
        card.getByLabel("Sum template units", { exact: true }),
      ).toBeEnabled();
    }
    if (!kind.startsWith("preview")) await preview(page, card, "");
    else
      await card
        .getByLabel("Sum template units", { exact: true })
        .selectOption("");
    const endpoint = kind.startsWith("import")
        ? "/api/macros/import"
        : base + "/" + kind.split("-")[0],
      gate = await held(page, endpoint);
    let downloads = 0;
    page.on("download", () => downloads++);
    try {
      if (kind.startsWith("import")) page.once("dialog", (d) => d.accept());
      await card
        .getByRole("button", {
          name: kind.startsWith("preview")
            ? "Preview eight-input sum"
            : kind.startsWith("export")
              ? "Download original sum bundle"
              : "Import reviewed sum definition",
          exact: true,
        })
        .click();
      await gate.incoming;
      if (kind === "preview-source")
        await page
          .getByLabel("Program name", { exact: true })
          .fill("Changed current source");
      else if (kind === "import-unmount")
        await page
          .getByRole("button", { name: "Program", exact: true })
          .click();
      else
        await card
          .getByRole("button", {
            name: "Discard pending sum template response",
            exact: true,
          })
          .click();
      gate.release();
      await gate.finished;
      if (kind === "import-unmount") {
        const refreshed = page.waitForResponse(
          (r) => new URL(r.url()).pathname === "/api/macros/catalog",
        );
        await page.getByRole("button", { name: "Macros", exact: true }).click();
        await refreshed;
        card = page.getByRole("region", {
          name: "Eight-input sum template",
          exact: true,
        });
      }
      if (kind.startsWith("import")) {
        await expect(
          card.getByLabel("Sum template units", { exact: true }),
        ).toBeEnabled();
        await expect(page.locator(".macro-count")).toHaveText("0 definitions");
        expect(await exportEditor(page)).toEqual(before);
      } else
        await expect(
          card.getByRole("button", {
            name: "Import reviewed sum definition",
            exact: true,
          }),
        ).toHaveCount(0);
      expect(downloads).toBe(kind.startsWith("import") ? 1 : 0);
    } finally {
      gate.release();
    }
  });
for (const kind of ["unit", "fold", "bundle-copy"])
  test(`refuse a source-sealed but inconsistent ${kind} sum preview`, async ({
    page,
  }) => {
    const card = await open(page);
    await page.route("**" + base + "/preview", async (route) => {
      const r = await route.fetch({ maxRetries: 0, maxRedirects: 0 }),
        original = await r.body();
      await retained("original-before-forged-" + kind, original);
      const body = execFileSync(
        python,
        [
          "-c",
          "import json,hashlib,sys;from bms_tool.models import Program;e=json.load(sys.stdin);v=json.loads(e['source_json']);mode=sys.argv[1];p=v['program'];nested=v['bundle']['library']['definitions'][0]['program'];\nif mode=='unit':v['choices']['unit']='A'\nif mode=='fold':\n p['edges'][0]['source']='i8';nested['edges'][0]['source']='i8'\nif mode=='bundle-copy':nested['description']+=' edited copy'\nfor d in e['programs']:\n t=v\n for k in d['path']:t=t[k]\n d['canonical_sha256']=Program.model_validate(t).digest()\ndef canonical(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()\nv['program_sha256']=Program.model_validate(p).digest();v['choices_sha256']=hashlib.sha256(canonical(v['choices'])).hexdigest();v['definition_sha256']=hashlib.sha256(canonical(v['bundle']['library']['definitions'][0])).hexdigest();v['bundle_sha256']=hashlib.sha256(canonical(v['bundle'])).hexdigest();e['source_json']=canonical(v).decode();e['source_sha256']=hashlib.sha256(e['source_json'].encode()).hexdigest();print(json.dumps(e))",
          kind,
        ],
        { cwd: root, env: environment(), input: original },
      );
      await route.fulfill({ response: r, body });
    });
    await card
      .getByLabel("Sum template units", { exact: true })
      .selectOption("");
    await card
      .getByRole("button", { name: "Preview eight-input sum", exact: true })
      .click();
    await expect(card.getByRole("alert")).toBeVisible();
    await expect(
      card.getByRole("button", {
        name: "Import reviewed sum definition",
        exact: true,
      }),
    ).toHaveCount(0);
  });
test("wrong original bundle byte header refuses download", async ({ page }) => {
  const card = await open(page);
  await preview(page, card, "kW");
  let downloads = 0;
  page.on("download", () => downloads++);
  await page.route("**" + base + "/export", async (route) => {
    const r = await route.fetch({ maxRetries: 0, maxRedirects: 0 });
    await route.fulfill({
      response: r,
      headers: { ...r.headers(), "x-file-sha256": "0".repeat(64) },
      body: await r.body(),
    });
  });
  await card
    .getByRole("button", { name: "Download original sum bundle", exact: true })
    .click();
  await expect(card.getByRole("alert")).toBeVisible();
  expect(downloads).toBe(0);
});
test("a conflicting edited definition is refused by the existing import API without overwriting editor bytes", async ({
  page,
}) => {
  await page.goto("/");
  const session = await (await page.request.get("/api/session")).json(),
    response = await page.request.post(base + "/preview", {
      headers: {
        "X-Studio-Token": session.token,
        "X-Studio-Program-Source": "true",
      },
      data: { unit: "" },
    });
  expect(response.status()).toBe(200);
  const raw = await response.body();
  await retained("original-conflict-seed-template", raw);
  const seed = pythonSource(
    "import json,sys;from bms_tool.models import Program;e=json.load(sys.stdin);v=json.loads(e['source_json']);b=v['bundle'];next(n for n in b['library']['definitions'][0]['program']['nodes']if n['id']=='sum_2')['label']='Existing custom addition';p=Program(id='conflict-sum',name='Existing edited sum',metadata={'macros':b['library']});print(p.model_dump_json())",
    raw,
  );
  await load(page, seed);
  const before = await exportEditor(page);
  await page.getByRole("button", { name: "Macros", exact: true }).click();
  const card = page.getByRole("region", {
    name: "Eight-input sum template",
    exact: true,
  });
  await expect(
    card.getByLabel("Sum template units", { exact: true }),
  ).toBeEnabled();
  await preview(page, card, "");
  page.once("dialog", (d) => d.accept());
  await capture(
    page,
    "/api/macros/import",
    () =>
      card
        .getByRole("button", {
          name: "Import reviewed sum definition",
          exact: true,
        })
        .click(),
    422,
  );
  await expect(page.locator(".macro-error")).toContainText(
    "identifier conflict",
  );
  expect(await exportEditor(page)).toEqual(before);
  await retained("original-conflict-editor-before", before);
});
test("failed criteria reload retires old preview and requires a new review after recovery", async ({
  page,
}) => {
  const card = await open(page);
  await preview(page, card, "A");
  await page.route("**" + base + "/catalog", async (route) => {
    const r = await route.fetch({ maxRetries: 0, maxRedirects: 0 }),
      v = await r.json();
    v.profile.semantics.order += " altered";
    await route.fulfill({ response: r, json: v });
  });
  await card
    .getByRole("button", { name: "Reload sum template criteria", exact: true })
    .click();
  await expect(card.getByRole("alert")).toBeVisible();
  await expect(
    card.getByRole("button", {
      name: "Import reviewed sum definition",
      exact: true,
    }),
  ).toHaveCount(0);
  await expect(
    card.getByLabel("Sum template units", { exact: true }),
  ).toBeDisabled();
  await page.unroute("**" + base + "/catalog");
  await card
    .getByRole("button", { name: "Reload sum template criteria", exact: true })
    .click();
  await expect(
    card.getByLabel("Sum template units", { exact: true }),
  ).toBeEnabled();
  await expect(
    card.getByRole("button", {
      name: "Import reviewed sum definition",
      exact: true,
    }),
  ).toHaveCount(0);
  await preview(page, card, "A");
});

for (const difference of ["negative-zero", "integer-zero"] as const)
  test(`same-ID ${difference} source-only definition collision refuses import and preserves exact editor bytes`, async ({
    page,
  }) => {
    await page.goto("/");
    const session = await (await page.request.get("/api/session")).json(),
      response = await page.request.post(base + "/preview", {
        headers: {
          "X-Studio-Token": session.token,
          "X-Studio-Program-Source": "true",
        },
        data: { unit: "" },
      });
    expect(response.status()).toBe(200);
    const original = await response.body();
    await retained("original-numeric-collision-template", original);
    const seed = execFileSync(
      python,
      [
        "-c",
        `import copy,json,sys
from bms_tool.models import Program,canonical
v=json.loads(json.load(sys.stdin)['source_json']); library=v['bundle']['library']
item=library['definitions'][0]; original=copy.deepcopy(item)
node=next(n for n in item['program']['nodes'] if n['id']=='i1')
assert type(node['params']['default']) is float and node['params']['default']==0
node['params']['default']=-0.0 if sys.argv[1]=='negative-zero' else 0
assert item==original and canonical(Program.model_validate(item['program']))!=canonical(Program.model_validate(original['program']))
restored=copy.deepcopy(item);next(n for n in restored['program']['nodes']if n['id']=='i1')['params']['default']=0.0
assert json.dumps(restored,sort_keys=True)==json.dumps(original,sort_keys=True)
p=Program(id='numeric-source-conflict',name='Existing source-only sum edit',metadata={'macros':library})
print(p.model_dump_json())`,
        difference,
      ],
      { cwd: root, env: environment(), input: original },
    );
    await retained("original-numeric-collision-seed", seed);
    await load(page, seed);
    const before = await exportEditor(page);
    pythonSource(
      `import json,sys,math
from bms_tool.models import Program,canonical
v=json.load(sys.stdin);a=Program.model_validate_json(v['seed']);b=Program.model_validate_json(v['before'])
assert canonical(Program.model_validate(a.metadata['macros']['definitions'][0]['program']))==canonical(Program.model_validate(b.metadata['macros']['definitions'][0]['program']))
x=b.metadata['macros']['definitions'][0]['program']['nodes'][0]['params']['default']
assert (type(x) is float and math.copysign(1,x)<0) if v['difference']=='negative-zero' else type(x) is int
print('exact source-only definition retained before attempted import')`,
      JSON.stringify({
        seed: seed.toString(),
        before: before.toString(),
        difference,
      }),
    );
    await page.getByRole("button", { name: "Macros", exact: true }).click();
    const card = page.getByRole("region", {
      name: "Eight-input sum template",
      exact: true,
    });
    await expect(
      card.getByLabel("Sum template units", { exact: true }),
    ).toBeEnabled();
    await preview(page, card, "");
    page.once("dialog", (d) => d.accept());
    await capture(
      page,
      "/api/macros/import",
      () =>
        card
          .getByRole("button", {
            name: "Import reviewed sum definition",
            exact: true,
          })
          .click(),
      422,
    );
    await expect(page.locator(".macro-error")).toContainText(
      "identifier conflict",
    );
    const after = await exportEditor(page);
    expect(after).toEqual(before);
    await retained("original-numeric-collision-editor-before", before);
    await retained("original-numeric-collision-editor-after", after);
    expect(
      (await (await page.request.get("/api/session")).json())
        .field_network_open,
    ).toBe(false);
  });
