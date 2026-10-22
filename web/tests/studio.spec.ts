import { test, expect } from "./simulationFixture";
import { execFileSync } from "node:child_process";
import path from "node:path";

test("copy a connected nested macro graph into a new project with its libraries", async ({
  page,
}) => {
  await page.goto("/");
  const root = path.resolve("..");
  const buffer = execFileSync(
    path.join(root, ".venv/bin/python"),
    [
      "-c",
      "from tests.test_macro_integration import nested_rate_program; p=nested_rate_program(); [(setattr(n,'x',(i//2)*280),setattr(n,'y',(i%2)*240+100)) for i,n in enumerate(p.nodes)]; print(p.model_dump_json())",
    ],
    { cwd: root },
  );
  await page
    .locator(
      'input[type=file][accept=".json,.st,.xml,.graphml,.sedona.zip,.sax,.sab,.bog,.bas"]',
    )
    .setInputFiles({
      name: "nested.bms.json",
      mimeType: "application/json",
      buffer,
    });
  await page.locator('.react-flow__node[data-id="first"]').click();
  await page.keyboard.press("Control+a");
  await expect(page.locator(".selection-panel")).toContainText(
    "6 blocks selected",
  );
  await page.keyboard.press("Control+c");
  await page.getByRole("button", { name: "New program", exact: true }).click();
  await page.keyboard.press("Control+v");
  await expect(page.locator(".react-flow__node")).toHaveCount(6);
  await page
    .getByRole("button", { name: "Step simulation", exact: true })
    .click();
  await expect(page.locator(".elapsed")).toHaveText("1.0 s");
  await expect(page.locator(".trend-legend")).toContainText("-1");
  const event = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export", exact: true }).click();
  const file = await event;
  const copied = JSON.parse(
    execFileSync("/bin/cat", [(await file.path())!], { encoding: "utf8" }),
  );
  expect(copied.metadata.macros.definitions).toHaveLength(2);
  expect(copied.nodes.filter((n: any) => n.kind === "Macro")).toHaveLength(2);
});

test("persist simulation trends and acknowledge returned alarms across reloads", async ({
  page,
  request,
}) => {
  await page.goto("/");
  const root = path.resolve("..");
  const buffer = execFileSync(
    path.join(root, ".venv/bin/python"),
    [
      "-c",
      "from bms_tool.models import Program,Node,Edge; p=Program(id='alarm-browser',nodes=[Node(id='sensor',kind='Input',params={'default':200},unit='degF',x=0),Node(id='high',kind='Alarm',label='High temperature',unit='degF',params={'limit':100},x=280),Node(id='result',kind='Output',value_type='boolean',x=560)],edges=[Edge(id='a',source='sensor',target='high'),Edge(id='b',source='high',target='result')]); print(p.model_dump_json())",
    ],
    { cwd: root },
  );
  await page
    .locator(
      'input[type=file][accept=".json,.st,.xml,.graphml,.sedona.zip,.sax,.sab,.bog,.bas"]',
    )
    .setInputFiles({
      name: "alarm.bms.json",
      mimeType: "application/json",
      buffer,
    });
  await page.getByLabel("Persist history", { exact: true }).check();
  await page
    .getByRole("button", { name: "Step simulation", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Trends & alarms", exact: true })
    .click();
  await expect(page.locator(".alarm-occurrence")).toContainText(
    "High temperature",
  );
  await page
    .getByLabel(/acknowledgment note$/)
    .fill("Reviewed simulated high temperature");
  await page.getByRole("button", { name: /^Acknowledge alarm/ }).click();
  await expect(page.locator(".alarm-occurrence")).toContainText(
    "active · acknowledged",
  );
  await page.getByRole("button", { name: "Program", exact: true }).click();
  await page.getByLabel("Simulate sensor", { exact: true }).fill("50");
  await page
    .getByRole("button", { name: "Step simulation", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Trends & alarms", exact: true })
    .click();
  await expect(page.locator(".alarm-occurrence")).toContainText(
    "returned · acknowledged",
  );
  await page.reload();
  await page
    .getByRole("button", { name: "Trends & alarms", exact: true })
    .click();
  await expect(page.locator(".alarm-occurrence")).toContainText(
    "Reviewed simulated high temperature",
  );
  const event = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Export shown trends CSV", exact: true })
    .click();
  const file = await event;
  const csv = execFileSync("/bin/cat", [(await file.path())!], {
    encoding: "utf8",
  });
  expect(csv).toContain('"quality","unit"');
  expect(csv).toContain('"good","degF"');
  await page.getByRole("button", { name: "Program", exact: true }).click();
  await page.getByLabel("Persist history", { exact: true }).check();
  await page
    .getByRole("button", { name: "Step simulation", exact: true })
    .click();
  const active = await (
    await request.get("/api/observations/alarms?active=true")
  ).json();
  expect(active).toHaveLength(1);
  await page
    .getByRole("button", { name: "Trends & alarms", exact: true })
    .click();
  await page
    .getByLabel("Observation source", { exact: true })
    .selectOption(active[0].source);
  await page
    .getByText("Retention and source retirement", { exact: true })
    .click();
  await page
    .getByLabel("Reason for ending source", { exact: true })
    .fill("Simulation reset; close abandoned source");
  await page
    .getByRole("button", {
      name: "End selected simulation source",
      exact: true,
    })
    .click();
  await expect(page.locator(".alarm-occurrence")).toContainText(
    "source-ended · unacknowledged",
  );
  await expect(page.locator(".alarm-occurrence")).not.toContainText("Returned");
  await page
    .getByLabel(`Alarm ${active[0].id} acknowledgment note`, { exact: true })
    .fill("Reviewed ended source");
  await page
    .getByRole("button", {
      name: `Acknowledge alarm ${active[0].id}`,
      exact: true,
    })
    .click();
  await expect(page.locator(".alarm-occurrence")).toContainText(
    "source-ended · acknowledged",
  );
  await page.screenshot({
    path: "test-results/studio-observations.png",
    fullPage: true,
  });
});

test("configure date exceptions and run an explicit UTC calendar scan", async ({
  page,
}) => {
  await page.goto("/");
  const root = path.resolve("..");
  const buffer = execFileSync(
    path.join(root, ".venv/bin/python"),
    [
      "-c",
      "from tests.test_calendar_integration import calendar_program; p=calendar_program(); p.nodes[1].x=280; print(p.model_dump_json())",
    ],
    { cwd: root },
  );
  await page
    .locator(
      'input[type=file][accept=".json,.st,.xml,.graphml,.sedona.zip,.sax,.sab,.bog,.bas"]',
    )
    .setInputFiles({
      name: "calendar.bms.json",
      mimeType: "application/json",
      buffer,
    });
  await page.locator('.react-flow__node[data-id="occupied"]').click();
  await page
    .getByLabel("Calendar exception JSON", { exact: true })
    .fill('[{"date":"2026-01-07","enabled":false}]');
  await page
    .getByRole("button", { name: "Apply calendar exceptions", exact: true })
    .click();
  await page
    .getByLabel("Next scan UTC clock", { exact: true })
    .fill("2026-01-07T17:00");
  await page
    .getByRole("button", { name: "Step simulation", exact: true })
    .click();
  await expect(page.locator(".trend-legend")).toContainText("out: FALSE");
  await page
    .getByLabel("Next scan UTC clock", { exact: true })
    .fill("2026-01-08T17:00");
  await page
    .getByRole("button", { name: "Step simulation", exact: true })
    .click();
  await expect(page.locator(".trend-legend")).toContainText("out: TRUE");
});

test("select, duplicate and delete connected groups as one undoable edit", async ({
  page,
}) => {
  await page.goto("/");
  const root = path.resolve("..");
  const buffer = execFileSync(
    path.join(root, ".venv/bin/python"),
    [
      "-c",
      "from tests.test_simulation_forces import rate_program; p=rate_program(); [(setattr(n,'x',i*280),setattr(n,'y',100)) for i,n in enumerate(p.nodes)]; print(p.model_dump_json())",
    ],
    { cwd: root },
  );
  await page
    .locator(
      'input[type=file][accept=".json,.st,.xml,.graphml,.sedona.zip,.sax,.sab,.bog,.bas"]',
    )
    .setInputFiles({
      name: "selection.bms.json",
      mimeType: "application/json",
      buffer,
    });
  const rate = page.locator('.react-flow__node[data-id="rate"]');
  const out = page.locator('.react-flow__node[data-id="out"]');
  await rate.click();
  await out.click({ modifiers: ["Shift"] });
  await expect(page.locator(".selection-panel")).toContainText(
    "2 blocks selected",
  );
  await page
    .getByRole("button", { name: "Duplicate selection", exact: true })
    .click();
  await expect(page.locator(".react-flow__node")).toHaveCount(5);
  await expect(page.locator(".react-flow__edge")).toHaveCount(3);
  await expect(page.locator(".react-flow__node.selected")).toHaveCount(2);
  const event = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export", exact: true }).click();
  const file = await event;
  const project = JSON.parse(
    execFileSync("/bin/cat", [(await file.path())!], { encoding: "utf8" }),
  );
  const copies = project.nodes.filter((n: any) => n.id.startsWith("copy_"));
  expect(copies).toHaveLength(2);
  const copyIds = copies.map((n: any) => n.id);
  expect(
    project.edges.filter(
      (e: any) => copyIds.includes(e.source) && copyIds.includes(e.target),
    ),
  ).toHaveLength(1);
  await page
    .getByRole("button", { name: "Delete selection", exact: true })
    .click();
  await expect(page.locator(".react-flow__node")).toHaveCount(3);
  await page.getByTitle("Undo", { exact: true }).click();
  await expect(page.locator(".react-flow__node")).toHaveCount(5);
});

test("force and release internal values, retain fault state and export force evidence", async ({
  page,
}) => {
  await page.goto("/");
  const root = path.resolve("..");
  const buffer = execFileSync(
    path.join(root, ".venv/bin/python"),
    [
      "-c",
      "from tests.test_simulation_forces import rate_program; p=rate_program(); [(setattr(n,'x',i*280),setattr(n,'y',100)) for i,n in enumerate(p.nodes)]; print(p.model_dump_json())",
    ],
    { cwd: root },
  );
  await page
    .locator(
      'input[type=file][accept=".json,.st,.xml,.graphml,.sedona.zip,.sax,.sab,.bog,.bas"]',
    )
    .setInputFiles({
      name: "force-example.bms.json",
      mimeType: "application/json",
      buffer,
    });
  await page
    .locator(".react-flow__node")
    .filter({ hasText: "Rate limiter" })
    .click();
  await page.getByLabel("Simulation force value", { exact: true }).fill("50");
  await page
    .getByRole("button", { name: "Hold simulation value", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Step simulation", exact: true })
    .click();
  await expect(page.locator(".trend-legend")).toContainText("out: 50");
  await expect(page.locator(".force-badge")).toHaveCount(1);
  await page
    .getByLabel("Quality input", { exact: true })
    .selectOption("open-circuit");
  await page
    .getByRole("button", { name: "Step simulation", exact: true })
    .click();
  await expect(page.locator(".simulation .inline-error")).toContainText(
    "open-circuit",
  );
  await expect(page.locator(".elapsed")).toHaveText("1.0 s");
  await page
    .getByRole("button", { name: "Release simulation force", exact: true })
    .click();
  await expect(page.locator(".force-status")).toContainText(
    "Next scan: automatic. Last completed scan: 50",
  );
  await page.getByLabel("Quality input", { exact: true }).selectOption("good");
  await page
    .getByRole("button", { name: "Step simulation", exact: true })
    .click();
  await expect(page.locator(".trend-legend")).toContainText("out: 2");
  await expect(page.locator(".force-badge")).toHaveCount(0);
  const csvEvent = page.waitForEvent("download");
  await page.getByTitle("Export simulation CSV", { exact: true }).click();
  const csvFile = await csvEvent;
  const csv = execFileSync("/bin/cat", [(await csvFile.path())!], {
    encoding: "utf8",
  });
  expect(csv).toContain("force_overrides");
  expect(csv).toContain('""rate"":50');
  await page.getByRole("button", { name: "Scenarios", exact: true }).click();
  await page
    .getByLabel("Timed simulation events", { exact: true })
    .fill('[{"time":0,"forces":{"rate":20}},{"time":2,"forces":{}}]');
  await page.getByLabel("Scenario duration seconds", { exact: true }).fill("4");
  await page.getByRole("button", { name: "Run scenario", exact: true }).click();
  await expect(page.locator(".elapsed")).toHaveText("4.0 s");
  await expect(page.locator(".trend-legend")).toContainText("out: 4");
});

test("shared-signal simulation preserves cycle boundaries, faults and workspace files", async ({
  page,
  request,
}) => {
  await page.goto("/");
  const projects = await (await request.get("/api/projects")).json();
  await page.getByRole("button", { name: "System sim", exact: true }).click();
  await page
    .getByRole("button", { name: "Load shared-signal demo", exact: true })
    .click();
  await expect(page.locator(".group-elapsed")).toHaveText("0.0 s");
  await page.getByRole("button", { name: "Step group", exact: true }).click();
  await expect(page.locator(".group-trace tbody tr").last()).toContainText(
    '"scaled":0',
  );
  await page.getByRole("button", { name: "Step group", exact: true }).click();
  await expect(page.locator(".group-trace tbody tr").last()).toContainText(
    '"scaled":84',
  );
  await page
    .getByLabel("Group input producer.value", { exact: true })
    .fill("50");
  await page.getByRole("button", { name: "Step group", exact: true }).click();
  await page.getByRole("button", { name: "Step group", exact: true }).click();
  await expect(page.locator(".group-trace tbody tr").last()).toContainText(
    '"scaled":104',
  );
  await page
    .getByLabel("Group quality producer.value", { exact: true })
    .selectOption("open-circuit");
  await page.getByRole("button", { name: "Step group", exact: true }).click();
  await expect(page.locator(".system-simulation .inline-error")).toContainText(
    "all programs remain at the previous cycle",
  );
  await expect(page.locator(".group-elapsed")).toHaveText("4.0 s");
  await page
    .getByLabel("Group quality producer.value", { exact: true })
    .selectOption("good");
  await page
    .getByRole("button", { name: "Run 10 group cycles", exact: true })
    .click();
  await expect(page.locator(".group-elapsed")).toHaveText("14.0 s");
  await page.getByRole("button", { name: "Program", exact: true }).click();
  await page.getByRole("button", { name: "System sim", exact: true }).click();
  await expect(page.locator(".group-elapsed")).toHaveText("14.0 s");
  await expect(
    page.getByLabel("Group input producer.value", { exact: true }),
  ).toHaveValue("50");
  const event = page.waitForEvent("download");
  await page.keyboard.press("Control+s");
  const saved = await event;
  expect(saved.suggestedFilename()).toBe("simulation.bms-workspace.json");
  expect(await (await request.get("/api/projects")).json()).toEqual(projects);
  await page
    .locator('input[type=file][accept=".bms-workspace.json"]')
    .setInputFiles({
      name: saved.suggestedFilename(),
      mimeType: "application/json",
      buffer: execFileSync("/bin/cat", [(await saved.path())!]),
    });
  await expect(page.locator(".group-elapsed")).toHaveText("0.0 s");
  await page.getByRole("button", { name: "Step group", exact: true }).click();
  await page.getByRole("button", { name: "Step group", exact: true }).click();
  await expect(page.locator(".group-trace tbody tr").last()).toContainText(
    '"scaled":84',
  );
  await page.screenshot({
    path: "test-results/studio-system.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Close group", exact: true }).click();
  await expect(page.locator(".group-elapsed")).toHaveCount(0);
});

test("convert foreign native SAX and review its execution differences", async ({
  page,
  request,
}) => {
  const support = await (await request.get("/api/native/status")).json();
  test.skip(!support.available, "Optional Sedona SDK is not installed");
  await page.goto("/");
  const root = path.resolve("..");
  const buffer = execFileSync(
    path.join(root, ".venv/bin/python"),
    [
      "-c",
      "from tests.test_sedona_import import sax; import sys; sys.stdout.buffer.write(sax())",
    ],
    { cwd: root },
  );
  await page
    .locator(
      'input[type=file][accept=".json,.st,.xml,.graphml,.sedona.zip,.sax,.sab,.bog,.bas"]',
    )
    .setInputFiles({
      name: "foreign.sax",
      mimeType: "application/xml",
      buffer,
    });
  await expect(page.locator(".conversion-report")).toContainText(
    "strict scan faults",
  );
  await page.getByRole("button", { name: "Close settings" }).click();
  await page.getByRole("button", { name: "Step simulation" }).click();
  await expect(page.locator(".trend-legend")).toContainText("42");
  await expect(page.getByLabel("Program name")).toHaveValue(
    "Imported Sedona application",
  );
});

test("export and reimport a real native Sedona application bundle", async ({
  page,
  request,
}) => {
  test.setTimeout(60000);
  const support = await (await request.get("/api/native/status")).json();
  test.skip(!support.available, "Optional Sedona SDK is not installed");
  await page.goto("/");
  await page
    .getByLabel("Choose VAV template")
    .selectOption("universal-runtime-parallel-fan-reheat");
  await page.getByLabel("Export format").selectOption("sedona");
  const event = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export", exact: true }).click();
  const bundle = await event;
  expect(bundle.suggestedFilename()).toMatch(/\.sedona.zip$/);
  const saved = await bundle.path();
  await page
    .locator(
      'input[type=file][accept=".json,.st,.xml,.graphml,.sedona.zip,.sax,.sab,.bog,.bas"]',
    )
    .setInputFiles({
      name: "native.sedona.zip",
      mimeType: "application/zip",
      buffer: execFileSync("/bin/cat", [saved!]),
    });
  await expect(page.locator(".toast")).toContainText(
    "Imported as a new local project",
  );
  await expect(page.locator(".react-flow__node")).toHaveCount(11);
});

test("native controller compiles, scans, adds an unconnected input and rolls back", async ({
  page,
  request,
}) => {
  test.setTimeout(120000);
  const support = await (await request.get("/api/native/status")).json();
  test.skip(
    !support.available,
    "Optional native Sedona compiler/SVM is not installed",
  );
  await page.goto("/");
  await page
    .getByLabel("Choose VAV template")
    .selectOption("universal-runtime-inline-reheat");
  await page.getByRole("button", { name: "Native sim", exact: true }).click();
  await page
    .getByRole("button", { name: "Compile and start", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Step native controller" }),
  ).toBeVisible();
  await page.getByLabel("Native input zone", { exact: true }).fill("80");
  await page.getByRole("button", { name: "Step native controller" }).click();
  await expect(page.locator(".native-trace tbody")).toContainText(
    '"damper":100',
  );
  await expect(page.locator(".native-trace tbody")).toContainText("Match");
  await page
    .getByLabel("Native quality zone", { exact: true })
    .selectOption("open-circuit");
  await page.getByRole("button", { name: "Step native controller" }).click();
  await expect(page.locator(".native-trace tbody")).toContainText(
    "Fault; outputs held",
  );
  await page
    .getByRole("button", { name: "Add unused input", exact: true })
    .click();
  await expect(page.locator(".native-block.proposed")).toContainText("sensor");
  await page
    .getByRole("button", { name: "Preview native change", exact: true })
    .click();
  await expect(page.locator(".native-preview")).toContainText(
    "Preflight passed",
  );
  await page
    .getByRole("button", { name: "Apply native change", exact: true })
    .click();
  await expect(page.locator(".native-block")).toContainText(
    "null / unconnected",
  );
  await expect(page.locator(".native-block.proposed")).toHaveCount(0);
  await page.keyboard.press("Control+s");
  await expect(page.locator(".toast")).toContainText(
    "Saved native revision 1 locally.",
  );
  const nativeDownload = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Export native application", exact: true })
    .click();
  const nativeFile = await nativeDownload;
  const exported = JSON.parse(
    execFileSync(
      path.resolve("../.venv/bin/python"),
      [
        "-c",
        "import json,sys,zipfile; z=zipfile.ZipFile(sys.argv[1]); p=json.loads(z.read('program.bms.json')); print(json.dumps({'components':p['metadata']['native_sedona']['components'],'sax':z.read('app.sax').decode()}))",
        (await nativeFile.path())!,
      ],
      { encoding: "utf8" },
    ),
  );
  expect(exported.components).toEqual([
    {
      path: "/online/sensor",
      type: "types::WriteFloat",
      properties: { in: "null" },
    },
  ]);
  expect(exported.sax).toContain('name="sensor"');
  expect(exported.sax).not.toContain("sox::SoxService");
  await page.screenshot({
    path: "test-results/studio-native.png",
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Roll back native change", exact: true })
    .click();
  await expect(page.locator(".native-block")).toHaveCount(0);
  await page
    .getByRole("button", { name: "Save native revision", exact: true })
    .click();
  await expect(page.locator(".toast")).toContainText(
    "Saved native revision 2 locally.",
  );
  await page
    .getByRole("button", { name: "Stop native simulator", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Step native controller" }),
  ).toHaveCount(0);
});

test("simulation runs real blocks and refuses open-circuit inputs", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Step simulation" }),
  ).toBeVisible();
  await page.getByLabel("Simulate zone", { exact: true }).fill("80");
  await page.getByRole("button", { name: "Step simulation" }).click();
  await expect(page.locator(".elapsed")).toHaveText("1.0 s");
  await expect(page.locator(".trend-legend")).toContainText(
    "Damper command: 100",
  );
  await page
    .getByLabel("Quality zone", { exact: true })
    .selectOption("open-circuit");
  await page.getByRole("button", { name: "Step simulation" }).click();
  await expect(page.locator(".simulation .inline-error")).toContainText(
    "open-circuit",
  );
  await expect(page.locator(".elapsed")).toHaveText("1.0 s");
  await page.screenshot({
    path: "test-results/studio-editor.png",
    fullPage: true,
  });
});

test("drag blocks, wire pins, edit values and undo", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "New program", exact: true }).click();
  const before = await page.locator(".react-flow__node").count();
  const constant = page
    .locator(".palette-block")
    .filter({ hasText: "Constant" });
  await constant.dragTo(page.locator(".canvas"), {
    targetPosition: { x: 220, y: 180 },
  });
  await expect(page.locator(".react-flow__node")).toHaveCount(before + 1);
  await page.locator(".palette-block").filter({ hasText: "Output" }).click();
  await expect(page.locator(".react-flow__node")).toHaveCount(2);
  await page.getByTitle("Fit view", { exact: true }).click();
  await page
    .locator(".react-flow__node")
    .filter({ hasText: "Constant" })
    .click();
  await page
    .locator(".inspector label")
    .filter({ hasText: /^value$/ })
    .locator("input")
    .fill("37.5");
  const source = page
    .locator(".react-flow__node")
    .filter({ hasText: "Constant" })
    .locator(".react-flow__handle-right");
  const target = page
    .locator(".react-flow__node")
    .filter({ hasText: "Output" })
    .locator(".react-flow__handle-left");
  const s = await source.boundingBox(),
    t = await target.boundingBox();
  await page.mouse.move(s!.x + s!.width / 2, s!.y + s!.height / 2);
  await page.mouse.down();
  await page.mouse.move(t!.x + t!.width / 2, t!.y + t!.height / 2, {
    steps: 20,
  });
  await page.mouse.up();
  await expect(page.locator(".react-flow__edge")).toHaveCount(1);
  await page.getByRole("button", { name: "Step simulation" }).click();
  await expect(page.locator(".trend-legend")).not.toBeEmpty();
  await page
    .locator(".react-flow__node")
    .filter({ hasText: "Constant" })
    .click();
  await expect(page.locator(".dependency-view")).toContainText(
    "1 affected output",
  );
  await page.getByRole("button", { name: "Trace Output", exact: true }).click();
  await expect(page.locator(".inspector h3")).toHaveText("Output");
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(page.locator(".react-flow__edge")).toHaveCount(0);
});

test("save, export and import a graph through the GUI", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByLabel("Program name")).toBeVisible();
  await page
    .getByLabel("Choose VAV template")
    .selectOption("universal-runtime-inline-reheat");
  await page
    .getByLabel("Program name")
    .fill("Browser acceptance " + Date.now());
  await page.getByRole("button", { name: "Save revision" }).click();
  await expect(page.locator(".toast")).toContainText("Saved revision 1");
  await page.getByLabel("Export format").selectOption("plcopen");
  const downloadEvent = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export", exact: true }).click();
  const file = await downloadEvent;
  await expect(file.suggestedFilename()).toMatch(/\.xml$/);
  const saved = await file.path();
  expect(saved).toBeTruthy();
  await page
    .locator(
      'input[type=file][accept=".json,.st,.xml,.graphml,.sedona.zip,.sax,.sab,.bog,.bas"]',
    )
    .setInputFiles({
      name: "program.xml",
      mimeType: "application/xml",
      buffer: execFileSync("/bin/cat", [saved!]),
    });
  await expect(page.locator(".toast")).toContainText(
    "Imported as a new local project",
  );
  await expect(page.locator(".react-flow__node")).toHaveCount(8);
});

test("inspect and patch a synthetic CAF without changing its model", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "CAF files", exact: true }).click();
  const root = path.resolve("..");
  const buffer = execFileSync(
    path.join(root, ".venv/bin/python"),
    [
      "-c",
      "from tests.test_formats_caf import make_caf; import sys; sys.stdout.buffer.write(make_caf())",
    ],
    { cwd: root },
  );
  await page.locator('input[type=file][accept=".caf"]').setInputFiles({
    name: "synthetic.caf",
    mimeType: "application/octet-stream",
    buffer,
  });
  await expect(page.locator(".stat-grid")).toContainText("MS-VMA1630-0");
  await page.getByRole("row").filter({ hasText: "Example" }).click();
  await page.getByLabel("CAF property 3113", { exact: true }).fill("75");
  await expect(page.locator(".export-strip")).toContainText(
    "1 proposed scalar changes",
  );
  const event = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CAF copy" }).click();
  const exported = await event;
  expect(exported.suggestedFilename()).toBe("synthetic-scalars.caf");
  execFileSync(
    path.join(root, ".venv/bin/python"),
    [
      "-c",
      "from bms_tool.caf import CafArchive; from pathlib import Path; import sys; a=CafArchive(Path(sys.argv[1]).read_bytes()); assert a.summary()['model']=='MS-VMA1630-0'; assert next(p for p in a.properties('8-1') if p['id']=='3113')['scalar']['text']=='75'",
      (await exported.path())!,
    ],
    { cwd: root },
  );
  await page.screenshot({
    path: "test-results/studio-caf.png",
    fullPage: true,
  });
});

test("apply an online sandbox revision and roll back", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Runtime", exact: true }).click();
  await page
    .getByRole("button", { name: "Validate and preview deployment" })
    .click();
  await page.getByRole("button", { name: "Apply to sandbox runtime" }).click();
  await expect(page.locator(".stat-grid")).toContainText("Cooling Only");
  await page.getByRole("button", { name: "Program", exact: true }).click();
  await page.locator(".palette-block").filter({ hasText: /Input/ }).click();
  await page
    .locator(".inspector label")
    .filter({ hasText: /^Label$/ })
    .locator("input")
    .fill("Unused test input");
  await page.getByRole("button", { name: "Runtime", exact: true }).click();
  await page
    .getByRole("button", { name: "Validate and preview deployment" })
    .click();
  await expect(page.locator(".diff-summary")).toContainText("+1 added");
  await page.getByRole("button", { name: "Apply to sandbox runtime" }).click();
  await expect(
    page.getByRole("button", { name: "Roll back" }).first(),
  ).toBeVisible();
  await page.getByRole("button", { name: "Roll back" }).last().click();
  const state = await page.request.get("/api/runtime");
  expect((await state.json()).program.nodes).toHaveLength(5);
  await page.screenshot({
    path: "test-results/studio-runtime.png",
    fullPage: true,
  });
});

test("capabilities disclose native and hardware gaps", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Reference", exact: true }).click();
  await expect(
    page.getByRole("row").filter({ hasText: "Native vendor formats" }),
  ).toContainText("partial");
  await expect(
    page
      .getByRole("row")
      .filter({ hasText: "Direct MS/TP and BTCVT Bluetooth" }),
  ).toContainText("partial");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(page.locator(".connection-badge")).toContainText(
    "No BACnet interface open",
  );
  await expect(page.getByText("SERIAL MASTER", { exact: true })).toBeVisible();
});
