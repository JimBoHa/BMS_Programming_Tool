import {
  test,
  expect,
  type APIRequestContext,
  type Page,
} from "@playwright/test";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
const root = path.resolve(".."),
  python = path.join(root, ".venv/bin/python");
const py = (code: string, input?: string) =>
  execFileSync(python, ["-c", code], {
    cwd: root,
    input,
    encoding: "utf8",
    env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
  });
async function seed(
  request: APIRequestContext,
  expression: string,
  suite = true,
) {
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
    "Content-Type": "application/json",
  };
  const body = py(
    `import json,uuid;from bms_tool.models import Program,Node;p=Program(id='source-'+uuid.uuid4().hex,name='Exact source',nodes=[Node(id='number',kind='Constant',label='Exact constant',params={'value':${expression}},x=100,y=100)],metadata={'opaque':{'values':[1.0,-0.0,9007199254740993],'text':'1.0 -0.0 9007199254740993'}});print(json.dumps({'program':p.model_dump(),'expected_revision':0}))`,
  );
  const savedResponse = await request.post("/api/projects", {
    headers,
    data: body,
  });
  expect(savedResponse.ok()).toBeTruthy();
  const raw = await savedResponse.text(),
    identity = JSON.parse(
      py(
        "import json,sys;from bms_tool.models import Program;p=Program.model_validate_json(sys.stdin.read());print(json.dumps({'id':p.id,'digest':p.digest()}))",
        raw,
      ),
    );
  if (suite) {
    const suiteBody = py(
      "import json,sys;from bms_tool.models import Program;from bms_tool.conformance import template;p=Program.model_validate_json(sys.stdin.read());s=template(p);s['name']='Exact source criteria';s['cases'][0]['checks']=[{'id':'declared','time':1.0,'signal':'number','expected':0.0,'unit':'','abs_tol':0.0,'rel_tol':0.0}];print(json.dumps({'program':p.model_dump(),'suite':s,'expected_revision':0}))",
      raw,
    );
    const result = await request.post("/api/conformance/save", {
      headers,
      data: suiteBody,
    });
    expect(result.ok(), await result.text()).toBeTruthy();
  }
  return { ...identity, raw };
}
async function open(page: Page, id: string) {
  await page.goto("/");
  await page.getByLabel("Open saved project", { exact: true }).selectOption(id);
  await expect(page.locator(".validation-bar")).toContainText("r1");
  await page.getByTitle("Fit view", { exact: true }).click();
  await expect(
    page.locator('.react-flow__node[data-id="number"]'),
  ).toBeVisible();
}
async function exported(page: Page) {
  const pending = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export", exact: true }).click();
  return readFileSync((await (await pending).path())!, "utf8");
}
function details(raw: string) {
  return JSON.parse(
    py(
      "import json,sys;from bms_tool.models import Program;p=Program.model_validate_json(sys.stdin.read());print(json.dumps({'digest':p.digest(),'value':repr(p.nodes[0].params['value']),'opaque':repr(p.metadata['opaque']['values']),'nodes':len(p.nodes),'labels':[n.label for n in p.nodes]}))",
      raw,
    ),
  );
}
for (const [name, expression] of [
  ["integral float", "1.0"],
  ["signed zero", "-0.0"],
  ["large opaque integer", "2.0"],
]) {
  test(`Open then conformance retains exact saved binding: ${name}`, async ({
    page,
    request,
  }) => {
    const seeded = await seed(request, expression);
    await open(page, seeded.id);
    expect(details(await exported(page)).digest).toBe(seeded.digest);
    const pending = page.waitForResponse((r) =>
      r.url().endsWith("/api/conformance/catalog"),
    );
    await page
      .getByRole("button", { name: "Conformance tests", exact: true })
      .click();
    const catalog = await (await pending).json();
    expect(catalog.template.program_sha256).toBe(seeded.digest);
    expect(catalog.saved).toHaveLength(1);
    await expect(
      page.getByLabel("Saved conformance suites", { exact: true }),
    ).toContainText("Exact source criteria");
    await page.reload();
    await page
      .getByRole("button", { name: "Conformance tests", exact: true })
      .click();
    await expect(
      page.getByLabel("Saved conformance suites", { exact: true }),
    ).toContainText("Exact source criteria");
  });
}
test("unsafe integer graph remains archival exact through unrelated edit, save and reload", async ({
  page,
  request,
}) => {
  const seeded = await seed(request, "9007199254740993", false);
  await open(page, seeded.id);
  expect(details(await exported(page)).value).toBe("9007199254740993");
  await page.locator('.react-flow__node[data-id="number"]').click();
  await page.getByLabel("Label", { exact: true }).fill("Changed only label");
  await page
    .getByRole("button", { name: "Save revision", exact: true })
    .click();
  await expect(
    page.getByLabel("Last saved revision", { exact: true }),
  ).toContainText("r2");
  await page.reload();
  const result = details(await exported(page));
  expect(result.value).toBe("9007199254740993");
  expect(result.opaque).toBe("[1.0, -0.0, 9007199254740993]");
  expect(result.labels).toEqual(["Changed only label"]);
});
test("explicit equal-Number type and sign edits, undo and duplicate keep independent tokens", async ({
  page,
  request,
}) => {
  const seeded = await seed(request, "1.0", false);
  await open(page, seeded.id);
  await page.locator('.react-flow__node[data-id="number"]').click();
  const value = page.getByLabel("value", { exact: true });
  await expect(value).toHaveValue("1.0");
  await value.fill("1");
  expect(details(await exported(page)).value).toBe("1");
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  expect(details(await exported(page)).value).toBe("1.0");
  await page.locator('.react-flow__node[data-id="number"]').click();
  await value.fill("-0.0");
  expect(details(await exported(page)).value).toBe("-0.0");
  await value.fill("0");
  expect(details(await exported(page)).value).toBe("0");
  await page.getByRole("button", { name: "Duplicate", exact: true }).click();
  const raw = await exported(page);
  const result = JSON.parse(
    py(
      "import json,sys;from bms_tool.models import Program;p=Program.model_validate_json(sys.stdin.read());print(json.dumps([repr(n.params['value']) for n in p.nodes]))",
      raw,
    ),
  );
  expect(result).toEqual(["0", "0"]);
});
test("nested macro source survives wiresheet recovery, library export/import and cross-project clipboard", async ({
  page,
}) => {
  await page.goto("/");
  const buffer = Buffer.from(
    py(
      "from tests.test_macro_integration import nested_rate_program;p=nested_rate_program();p.metadata['opaque']={'values':[1.0,-0.0,9007199254740993]};[(setattr(n,'x',(i//2)*280),setattr(n,'y',(i%2)*240+100)) for i,n in enumerate(p.nodes)];d=p.metadata['macros']['definitions'][0]['program'];d['metadata']['opaque']={'values':[1.0,-0.0,9007199254740993]};[(n['params'].update(rate=1.0,initial=-0.0)) for n in d['nodes'] if n['kind']=='Slew'];print(p.model_dump_json())",
    ),
  );
  await page
    .locator(
      'input[type=file][accept=".json,.st,.xml,.graphml,.sedona.zip,.sax,.sab,.bog,.bas"]',
    )
    .setInputFiles({
      name: "exact-nested.bms.json",
      mimeType: "application/json",
      buffer,
    });
  await expect(page.locator(".toast")).toContainText(
    "Imported as a new local project",
  );
  await page.getByRole("button", { name: "Macros", exact: true }).click();
  await page
    .getByRole("button", { name: "Edit definition on wiresheet", exact: true })
    .click();
  await expect(page.locator(".macro-edit-banner")).toContainText("limiter");
  await page
    .getByLabel("Program name", { exact: true })
    .fill("Only nested graph name changed");
  await page.reload();
  await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
    "Only nested graph name changed",
  );
  await page
    .getByRole("button", { name: "Apply definition changes", exact: true })
    .click();
  await expect(page.locator(".macro-edit-banner")).toHaveCount(0);
  await page.getByRole("button", { name: "Macros", exact: true }).click();
  const pending = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export macro", exact: true }).click();
  const bundle = readFileSync((await (await pending).path())!);
  const inspect = (raw: string) =>
    JSON.parse(
      py(
        "import json,sys;b=json.loads(sys.stdin.read());ds=b.get('library',b.get('metadata',{}).get('macros',{}))['definitions'];print(json.dumps([{'opaque':repr(d['program']['metadata'].get('opaque')), 'slew':[repr(n['params']['rate'])+':'+repr(n['params']['initial']) for n in d['program']['nodes'] if n['kind']=='Slew']} for d in ds]))",
        raw,
      ),
    );
  expect(
    inspect(bundle.toString()).some(
      (row: any) =>
        row.opaque.includes("9007199254740993") &&
        row.slew.includes("1.0:-0.0"),
    ),
  ).toBeTruthy();
  await page.getByRole("button", { name: "Program", exact: true }).click();
  await page.locator('.react-flow__node[data-id="first"]').click();
  await page.keyboard.press("Control+a");
  await page.keyboard.press("Control+c");
  await page.getByRole("button", { name: "New program", exact: true }).click();
  await page.keyboard.press("Control+v");
  await expect(page.locator(".react-flow__node")).toHaveCount(6);
  expect(
    inspect(await exported(page)).some((row: any) =>
      row.slew.includes("1.0:-0.0"),
    ),
  ).toBeTruthy();
  await page.getByRole("button", { name: "New program", exact: true }).click();
  await page.getByRole("button", { name: "Macros", exact: true }).click();
  await page
    .getByLabel("Import macro bundle file", { exact: true })
    .setInputFiles({
      name: "exact-library.bms-macro.json",
      mimeType: "application/json",
      buffer: bundle,
    });
  await expect(page.locator(".macro-count")).toContainText("definition");
  await page.getByRole("button", { name: "Program", exact: true }).click();
  expect(
    inspect(await exported(page)).some((row: any) =>
      row.slew.includes("1.0:-0.0"),
    ),
  ).toBeTruthy();
});

test("array and whole JSON parameter replacements preserve type sign and order; malformed edits stay unapplied", async ({
  page,
}) => {
  await page.goto("/");
  const buffer = Buffer.from(
    py(
      "from bms_tool.models import Program,Node;p=Program(id='source-calendar',nodes=[Node(id='calendar',kind='Schedule',value_type='boolean',params={'weekdays':[1.0,-0.0,9007199254740993],'exceptions':[{'date':'2026-01-01','enabled':True,'on_hour':1.0,'off_hour':-0.0}]},x=100,y=100)]);print(p.model_dump_json())",
    ),
  );
  await page
    .locator(
      'input[type=file][accept=".json,.st,.xml,.graphml,.sedona.zip,.sax,.sab,.bog,.bas"]',
    )
    .setInputFiles({
      name: "exact-calendar.bms.json",
      mimeType: "application/json",
      buffer,
    });
  await expect(page.locator(".toast")).toContainText(
    "Imported as a new local project",
  );
  await page.locator('.react-flow__node[data-id="calendar"]').click();
  await page
    .getByLabel("weekdays", { exact: true })
    .fill("9007199254740993,-0.0,1.0");
  const editor = page.getByLabel("Calendar exception JSON", { exact: true });
  await expect(editor).toContainText("");
  await editor.fill(
    '[{"date":"2026-01-01","enabled":true,"on_hour":-0.0,"off_hour":1.0,"evidence":[9007199254740993,1.0]}]',
  );
  await page
    .getByRole("button", { name: "Apply calendar exceptions", exact: true })
    .click();
  const raw = await exported(page);
  const params = (text: string) =>
    py(
      "import sys;from bms_tool.models import Program;p=Program.model_validate_json(sys.stdin.read());print(repr(p.nodes[0].params))",
      text,
    ).trim();
  expect(params(raw)).toContain("'weekdays': [9007199254740993, -0.0, 1.0]");
  expect(params(raw)).toContain("'on_hour': -0.0");
  expect(params(raw)).toContain("'evidence': [9007199254740993, 1.0]");
  await editor.fill('[{"on_hour":1,"on_hour":2}]');
  await page
    .getByRole("button", { name: "Apply calendar exceptions", exact: true })
    .click();
  await expect(page.locator(".inspector .inline-error")).toContainText(
    "Duplicate",
  );
  expect(params(await exported(page))).toBe(params(raw));
  await page.reload();
  expect(params(await exported(page))).toBe(params(raw));
});
test("a corrupt exact-source response is refused without adopting a rounded fallback", async ({
  page,
  request,
}) => {
  const seeded = await seed(request, "1.0", false);
  await page.goto("/");
  await expect(page.getByLabel("Program name", { exact: true })).toBeVisible();
  const before = await page
    .getByLabel("Program name", { exact: true })
    .inputValue();
  await page.route("**/api/projects/" + seeded.id, async (route) => {
    const response = await route.fetch(),
      data = await response.json();
    data.source_sha256 = "0".repeat(64);
    await route.fulfill({ response, json: data });
  });
  await page
    .getByLabel("Open saved project", { exact: true })
    .selectOption(seeded.id);
  await expect(page.locator(".toast")).toContainText(
    "Invalid exact Program source",
  );
  await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
    before,
  );
  await expect(page.locator('.react-flow__node[data-id="number"]')).toHaveCount(
    0,
  );
});

test("large exact live force reaches Python as the declared integer without shortest-decimal substitution", async ({
  page,
  request,
}) => {
  const seeded = await seed(request, "1.0", false);
  await open(page, seeded.id);
  await page.locator('.react-flow__node[data-id="number"]').click();
  await page
    .getByLabel("Simulation force value", { exact: true })
    .fill("1152921504606846976");
  await page
    .getByRole("button", { name: "Hold simulation value", exact: true })
    .click();
  const pending = page.waitForResponse((r) =>
    r.url().endsWith("/api/simulation/step"),
  );
  await page
    .getByRole("button", { name: "Step simulation", exact: true })
    .click();
  const response = await pending;
  expect(response.ok(), await response.text()).toBeTruthy();
  const inspected = JSON.parse(
    py(
      "import json,sys;b=json.loads(sys.stdin.read());assert type(b['forces']['number']) is int;print(json.dumps({'value':str(b['forces']['number'])}))",
      response.request().postData()!,
    ),
  );
  expect(inspected.value).toBe("1152921504606846976");
  const actual = JSON.parse(
    py(
      "import json,sys;b=json.loads(sys.stdin.read());print(json.dumps({'value':str(b['history'][0]['values']['number'])}))",
      await response.text(),
    ),
  );
  expect(actual.value).toBe("1152921504606846976");
  await page
    .getByLabel("Simulation force value", { exact: true })
    .fill("1152921504606846977");
  await page
    .getByRole("button", { name: "Hold simulation value", exact: true })
    .click();
  await expect(page.locator(".simulation-force .inline-error")).toContainText(
    "not exactly representable",
  );
});
