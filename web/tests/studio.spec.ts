import {
  openCurrentGraph,
  importGraphFile,
  closeBlockProperties,
  showBlockProperties,
  graphSimulation,
  openBlockLibrary,
} from "./graph-workspace";
import {
  chooseWorkspaceSurface,
  chooseWorkspaceTask,
  chooseWorkspaceTool,
  openSystemSimulation,
} from "./workspace-navigation";
import { simulationServerResponseJSON } from "./simulationFixture";
import { test, expect, type Page } from "./simulationFixture";
import { readFile } from "node:fs/promises";
import {
  openDraftCaf,
  editScalar,
  cafChanges,
} from "./caf-scalar-draft-recovery-fixture";
import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import path from "node:path";

async function sandboxRuntime(page: Page) {
  await chooseWorkspaceSurface(page, "Settings");
  await chooseWorkspaceTool(page, "Local runtime", "settings tools");
}

test("copy a connected nested macro graph into a new project with its libraries", async ({
  page,
}) => {
  await openCurrentGraph(page);
  const root = path.resolve("..");
  const buffer = execFileSync(
    path.join(root, ".venv/bin/python"),
    [
      "-c",
      "from tests.test_macro_integration import nested_rate_program; p=nested_rate_program(); [(setattr(n,'x',(i//2)*280),setattr(n,'y',(i%2)*240+100)) for i,n in enumerate(p.nodes)]; print(p.model_dump_json())",
    ],
    { cwd: root },
  );
  await importGraphFile(page, {
    name: "nested.bms.json",
    mimeType: "application/json",
    buffer,
  });
  await page.locator('.react-flow__node[data-id="first"]').click();
  await closeBlockProperties(page);
  await page.keyboard.press("Control+a");
  await expect(page.locator(".selection-panel")).toContainText(
    "6 blocks selected",
  );
  await page.keyboard.press("Control+c");
  await page.getByRole("button", { name: "New program", exact: true }).click();
  await page.keyboard.press("Control+v");
  await expect(page.locator(".react-flow__node")).toHaveCount(6);
  await graphSimulation(page);
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
  await openCurrentGraph(page);
  const root = path.resolve("..");
  const buffer = execFileSync(
    path.join(root, ".venv/bin/python"),
    [
      "-c",
      "from bms_tool.models import Program,Node,Edge; p=Program(id='alarm-browser',nodes=[Node(id='sensor',kind='Input',params={'default':200},unit='degF',x=0),Node(id='high',kind='Alarm',label='High temperature',unit='degF',params={'limit':100},x=280),Node(id='result',kind='Output',value_type='boolean',x=560)],edges=[Edge(id='a',source='sensor',target='high'),Edge(id='b',source='high',target='result')]); print(p.model_dump_json())",
    ],
    { cwd: root },
  );
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  // A retained source with the same message makes unscoped/label-only selection
  // fail deterministically, even when this test starts with a fresh database.
  const unrelatedProgram = JSON.parse(buffer.toString());
  unrelatedProgram.id = "unrelated-alarm-" + randomUUID();
  const operation = randomUUID().replaceAll("-", "");
  const seeded = await request.post("/api/simulation/step", {
    headers,
    data: { program: unrelatedProgram, record: true, operation_id: operation },
  });
  expect(seeded.ok()).toBe(true);
  const unrelated = await seeded.json();
  expect(unrelated.session_creation_operation_id).toBe(operation);
  const occurrences = async (source: string) => {
    const response = await request.get(
      "/api/observations/alarms?source=" + encodeURIComponent(source),
    );
    expect(response.ok()).toBe(true);
    return response.json();
  };
  const retainedEvidence = async () =>
    Object.fromEntries(
      await Promise.all(
        ["alarms", "events", "trends"].map(async (name) => {
          const response = await request.get(
            `/api/observations/${name}?source=` +
              encodeURIComponent(unrelated.recording_source),
          );
          expect(response.ok()).toBe(true);
          return [name, await response.text()];
        }),
      ),
    );
  const before = await retainedEvidence();
  expect(JSON.parse(before.alarms)).toHaveLength(1);
  expect(JSON.parse(before.alarms)[0]).toMatchObject({
    active: true,
    acknowledged: false,
    message: "High temperature",
  });
  const occurrence = (id: number) =>
    page.locator(".alarm-occurrence").filter({
      has: page.getByRole("button", {
        name: `Events for alarm ${id}`,
        exact: true,
      }),
    });
  const showSource = async (source: string) => {
    await chooseWorkspaceSurface(page, "History");
    await chooseWorkspaceTool(
      page,
      "Recorded trends & alarms",
      "history tools",
    );
    await page
      .getByLabel("Observation source", { exact: true })
      .selectOption(source);
  };
  const step = async () => {
    const pending = page.waitForResponse(
      (r) =>
        r.url().endsWith("/api/simulation/step") &&
        r.request().method() === "POST",
    );
    await page
      .getByRole("button", { name: "Step simulation", exact: true })
      .click();
    const response = await pending;
    expect(response.ok()).toBe(true);
    const receipt = simulationServerResponseJSON(response);
    expect(receipt.operation_id).toBe(
      response.request().postDataJSON().operation_id,
    );
    expect(receipt.completed_steps).toBe(1);
    expect(receipt.recording_source).toBe(
      `simulation/${receipt.program_id}/${receipt.session}`,
    );
    return receipt;
  };
  try {
    await importGraphFile(page, {
      name: "alarm.bms.json",
      mimeType: "application/json",
      buffer,
    });
    await expect(page.locator(".toast")).toContainText(
      "Imported as a new local project",
    );
    await graphSimulation(page);
    await page.getByLabel("Persist history", { exact: true }).check();
    const first = await step();
    expect(first.session).not.toBe(unrelated.session);
    expect(first.session_creation_operation_id).toBe(first.operation_id);
    const [active] = await occurrences(first.recording_source);
    expect(await occurrences(first.recording_source)).toHaveLength(1);
    expect(active).toMatchObject({
      source: first.recording_source,
      signal: "high",
      active: true,
      acknowledged: false,
    });
    await showSource(first.recording_source);
    const firstRow = occurrence(active.id);
    await expect(firstRow).toHaveCount(1);
    await expect(firstRow).toContainText("High temperature");
    await expect(firstRow).toContainText(first.recording_source);
    await firstRow
      .getByLabel(`Alarm ${active.id} acknowledgment note`, { exact: true })
      .fill("Reviewed simulated high temperature");
    await firstRow
      .getByRole("button", {
        name: `Acknowledge alarm ${active.id}`,
        exact: true,
      })
      .click();
    await expect(firstRow).toContainText("active · acknowledged");
    expect(await retainedEvidence()).toEqual(before);
    await chooseWorkspaceSurface(page, "Workspace");
    await chooseWorkspaceTask(page, "Program");
    await graphSimulation(page);
    await page.getByLabel("Simulate sensor", { exact: true }).fill("50");
    expect((await step()).session).toBe(first.session);
    await showSource(first.recording_source);
    await expect(firstRow).toContainText("returned · acknowledged");
    await page.reload();
    await showSource(first.recording_source);
    await expect(firstRow).toContainText("Reviewed simulated high temperature");
    const returned = await occurrences(first.recording_source);
    expect(returned).toHaveLength(1);
    expect(returned[0]).toMatchObject({
      id: active.id,
      active: false,
      acknowledged: true,
      state: "returned",
    });
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
    expect(csv).toContain(first.recording_source);
    expect(csv).not.toContain(unrelated.recording_source);
    await chooseWorkspaceSurface(page, "Workspace");
    await chooseWorkspaceTask(page, "Program");
    await graphSimulation(page);
    await page.getByLabel("Persist history", { exact: true }).check();
    const restarted = await step();
    expect(restarted.session).not.toBe(first.session);
    expect(restarted.recording_source).not.toBe(first.recording_source);
    const fresh = await occurrences(restarted.recording_source);
    expect(fresh).toHaveLength(1);
    expect(fresh[0]).toMatchObject({
      source: restarted.recording_source,
      active: true,
      acknowledged: false,
    });
    expect(fresh[0].id).not.toBe(active.id);
    await showSource(restarted.recording_source);
    const endedRow = occurrence(fresh[0].id);
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
    await expect(endedRow).toContainText("source-ended · unacknowledged");
    await expect(endedRow).not.toContainText("Returned");
    await endedRow
      .getByLabel(`Alarm ${fresh[0].id} acknowledgment note`, { exact: true })
      .fill("Reviewed ended source");
    await endedRow
      .getByRole("button", {
        name: `Acknowledge alarm ${fresh[0].id}`,
        exact: true,
      })
      .click();
    await expect(endedRow).toContainText("source-ended · acknowledged");
    expect(await occurrences(first.recording_source)).toEqual(returned);
    expect(await retainedEvidence()).toEqual(before);
    await page.screenshot({
      path: "test-results/studio-observations.png",
      fullPage: true,
    });
  } finally {
    const retired = await request.post("/api/simulation/retire", {
      headers,
      data: {
        session: unrelated.session,
        retirement_token: unrelated.retirement_token,
        creation_operation_id: operation,
      },
    });
    expect(retired.ok()).toBe(true);
    expect((await retired.json()).recorded_evidence_unchanged).toBe(true);
    expect(await retainedEvidence()).toEqual(before);
  }
});

test("configure date exceptions and run an explicit UTC calendar scan", async ({
  page,
}) => {
  await openCurrentGraph(page);
  const root = path.resolve("..");
  const buffer = execFileSync(
    path.join(root, ".venv/bin/python"),
    [
      "-c",
      "from tests.test_calendar_integration import calendar_program; p=calendar_program(); p.nodes[1].x=280; print(p.model_dump_json())",
    ],
    { cwd: root },
  );
  await importGraphFile(page, {
    name: "calendar.bms.json",
    mimeType: "application/json",
    buffer,
  });
  await page.locator('.react-flow__node[data-id="occupied"]').click();
  await showBlockProperties(page);
  await page
    .getByLabel("Calendar exception JSON", { exact: true })
    .fill('[{"date":"2026-01-07","enabled":false}]');
  await page
    .getByRole("button", { name: "Apply calendar exceptions", exact: true })
    .click();
  await graphSimulation(page);
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
  await openCurrentGraph(page);
  const root = path.resolve("..");
  const buffer = execFileSync(
    path.join(root, ".venv/bin/python"),
    [
      "-c",
      "from tests.test_simulation_forces import rate_program; p=rate_program(); [(setattr(n,'x',i*280),setattr(n,'y',100)) for i,n in enumerate(p.nodes)]; print(p.model_dump_json())",
    ],
    { cwd: root },
  );
  await importGraphFile(page, {
    name: "selection.bms.json",
    mimeType: "application/json",
    buffer,
  });
  const rate = page.locator('.react-flow__node[data-id="rate"]');
  const out = page.locator('.react-flow__node[data-id="out"]');
  await rate.click();
  await closeBlockProperties(page);
  await out.click({ modifiers: ["Shift"] });
  await showBlockProperties(page);
  await expect(page.locator(".selection-panel")).toContainText(
    "2 blocks selected",
  );
  await page
    .getByRole("button", { name: "Duplicate selection", exact: true })
    .click();
  await expect(page.locator(".react-flow__node")).toHaveCount(5);
  await expect(page.locator(".react-flow__edge")).toHaveCount(3);
  await expect(page.locator(".react-flow__node.selected")).toHaveCount(2);
  await closeBlockProperties(page);
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
  await showBlockProperties(page);
  await page
    .getByRole("button", { name: "Delete selection", exact: true })
    .click();
  await expect(page.locator(".react-flow__node")).toHaveCount(3);
  await closeBlockProperties(page);
  await page.getByTitle("Undo", { exact: true }).click();
  await expect(page.locator(".react-flow__node")).toHaveCount(5);
});

test("force and release internal values, retain fault state and export force evidence", async ({
  page,
}) => {
  await openCurrentGraph(page);
  const root = path.resolve("..");
  const buffer = execFileSync(
    path.join(root, ".venv/bin/python"),
    [
      "-c",
      "from tests.test_simulation_forces import rate_program; p=rate_program(); [(setattr(n,'x',i*280),setattr(n,'y',100)) for i,n in enumerate(p.nodes)]; print(p.model_dump_json())",
    ],
    { cwd: root },
  );
  await importGraphFile(page, {
    name: "force-example.bms.json",
    mimeType: "application/json",
    buffer,
  });
  await graphSimulation(page);
  const rate = page.locator('.react-flow__node[data-id="rate"]');
  await rate.click();
  await showBlockProperties(page);
  await page.getByLabel("Simulation force value", { exact: true }).fill("50");
  await page
    .getByRole("button", { name: "Hold simulation value", exact: true })
    .click();
  await closeBlockProperties(page);
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
  await showBlockProperties(page);
  await page
    .getByRole("button", { name: "Release simulation force", exact: true })
    .click();
  await expect(page.locator(".force-status")).toContainText(
    "Next scan: automatic. Last completed scan: 50",
  );
  await closeBlockProperties(page);
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
  await openSystemSimulation(page);
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
  await chooseWorkspaceTool(page, "Graph simulation");
  await expect(page.locator(".group-elapsed")).toBeHidden();
  await openSystemSimulation(page);
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
  await openCurrentGraph(page);
  const root = path.resolve("..");
  const buffer = execFileSync(
    path.join(root, ".venv/bin/python"),
    [
      "-c",
      "from tests.test_sedona_import import sax; import sys; sys.stdout.buffer.write(sax())",
    ],
    { cwd: root },
  );
  await importGraphFile(page, {
    name: "foreign.sax",
    mimeType: "application/xml",
    buffer,
  });
  await expect(page.locator(".conversion-report")).toContainText(
    "strict scan faults",
  );
  await page.getByRole("button", { name: "Close settings" }).click();
  await page.getByRole("button", { name: "Simulate", exact: true }).click();
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
  await openCurrentGraph(page);
  await page
    .getByLabel("Choose VAV template")
    .selectOption("universal-runtime-parallel-fan-reheat");
  await page.getByLabel("Export format").selectOption("sedona");
  const event = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export", exact: true }).click();
  const bundle = await event;
  expect(bundle.suggestedFilename()).toMatch(/\.sedona.zip$/);
  const saved = await bundle.path();
  await importGraphFile(page, {
    name: "native.sedona.zip",
    mimeType: "application/zip",
    buffer: await readFile(saved!),
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
  await openCurrentGraph(page);
  await page
    .getByLabel("Choose VAV template")
    .selectOption("universal-runtime-inline-reheat");
  await graphSimulation(page);
  await chooseWorkspaceTool(page, "Sedona");
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
  await openCurrentGraph(page);
  await page.getByRole("button", { name: "Simulate", exact: true }).click();
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
  await page
    .getByRole("button", { name: "New application", exact: true })
    .click();
  const before = await page.locator(".react-flow__node").count();
  const compact = await page
    .getByRole("button", { name: "Open block library", exact: true })
    .isVisible();
  await openBlockLibrary(page);
  const constant = page
    .locator(".palette-block")
    .filter({ hasText: "Constant" });
  if (compact) {
    await constant.click();
    await closeBlockProperties(page);
    const node = page.locator(".react-flow__node").first();
    const initial = await node.evaluate(
      (el) => (el as HTMLElement).style.transform,
    );
    const box = await node.boundingBox();
    expect(box).toBeTruthy();
    await page.mouse.move(box!.x + 18, box!.y + 10);
    await page.mouse.down();
    await page.mouse.move(box!.x + 75, box!.y + 52, { steps: 10 });
    await page.mouse.up();
    await expect
      .poll(() => node.evaluate((el) => (el as HTMLElement).style.transform))
      .not.toBe(initial);
    await closeBlockProperties(page);
  } else {
    await constant.dragTo(page.locator(".canvas"), {
      targetPosition: { x: 220, y: 180 },
    });
  }
  await expect(page.locator(".react-flow__node")).toHaveCount(before + 1);
  await openBlockLibrary(page);
  await page.locator(".palette-block").filter({ hasText: "Output" }).click();
  await expect(page.locator(".react-flow__node")).toHaveCount(2);
  await closeBlockProperties(page);
  await page.getByTitle("Fit view", { exact: true }).click();
  await page
    .locator(".react-flow__node")
    .filter({ hasText: "Constant" })
    .click();
  await showBlockProperties(page);
  await page.getByLabel("value", { exact: true }).fill("37.5");
  await closeBlockProperties(page);
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
  await graphSimulation(page);
  await page.getByRole("button", { name: "Step simulation" }).click();
  await expect(page.locator(".trend-legend")).not.toBeEmpty();
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await page
    .locator(".react-flow__node")
    .filter({ hasText: "Constant" })
    .click();
  await showBlockProperties(page);
  await expect(page.locator(".dependency-view")).toContainText(
    "1 affected output",
  );
  await page.getByRole("button", { name: "Trace Output", exact: true }).click();
  await expect(page.locator(".inspector h3")).toHaveText("Output");
  await closeBlockProperties(page);
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(page.locator(".react-flow__edge")).toHaveCount(0);
});

test("save, export and import a graph through the GUI", async ({ page }) => {
  await openCurrentGraph(page);
  await expect(page.getByLabel("Program name")).toBeVisible();
  await page
    .getByLabel("Choose VAV template")
    .selectOption("universal-runtime-inline-reheat");
  await page
    .getByLabel("Program name")
    .fill("Browser acceptance " + Date.now());
  await page.getByRole("button", { name: "Save project", exact: true }).click();
  await expect(page.locator(".toast")).toContainText("Saved revision 1");
  await page.getByLabel("Export format").selectOption("plcopen");
  const downloadEvent = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export", exact: true }).click();
  const file = await downloadEvent;
  await expect(file.suggestedFilename()).toMatch(/\.xml$/);
  const saved = await file.path();
  expect(saved).toBeTruthy();
  await importGraphFile(page, {
    name: "program.xml",
    mimeType: "application/xml",
    buffer: await readFile(saved!),
  });
  await expect(page.locator(".toast")).toContainText(
    "Imported as a new local project",
  );
  await expect(page.locator(".react-flow__node")).toHaveCount(8);
});

test("inspect and patch a synthetic CAF without changing its model", async ({
  page,
}) => {
  const root = path.resolve("..");
  const buffer = execFileSync(
    path.join(root, ".venv/bin/python"),
    [
      "-c",
      "from tests.test_formats_caf import make_caf; import sys; sys.stdout.buffer.write(make_caf())",
    ],
    { cwd: root },
  );
  await openDraftCaf(page, buffer.toString("base64"), "synthetic.caf");
  await expect(page.locator(".caf-statistics")).toContainText("MS-VMA1630-0");
  await editScalar(page, "Example", "3113", "75");
  await cafChanges(page);
  const exportStrip = page.locator(".export-strip:visible");
  await expect(exportStrip).toContainText("1 proposed scalar changes");
  const event = page.waitForEvent("download");
  await exportStrip
    .getByRole("button", { name: "Save CAF copy", exact: true })
    .click();
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
  await openCurrentGraph(page);
  await sandboxRuntime(page);
  await page
    .getByRole("button", { name: "Validate and preview deployment" })
    .click();
  await page.getByRole("button", { name: "Apply to sandbox runtime" }).click();
  await expect(page.locator(".stat-grid")).toContainText("Cooling Only");
  const originalResponse = await page.request.get("/api/runtime");
  expect(originalResponse.ok()).toBe(true);
  const original = await originalResponse.json();
  expect(original.program.nodes).toHaveLength(5);
  await chooseWorkspaceSurface(page, "Workspace");
  await chooseWorkspaceTask(page, "Program");
  await openBlockLibrary(page);
  await page
    .locator(".palette-block")
    .filter({ hasText: /^IInputsource/ })
    .click();
  await showBlockProperties(page);
  await page
    .locator(".inspector label")
    .filter({ hasText: /^Label$/ })
    .locator("input")
    .fill("Unused test input");
  await closeBlockProperties(page);
  await sandboxRuntime(page);
  await page
    .getByRole("button", { name: "Validate and preview deployment" })
    .click();
  await expect(page.locator(".diff-summary")).toContainText("+1 added");
  await page.getByRole("button", { name: "Apply to sandbox runtime" }).click();
  const originalBackup = page
    .getByRole("row")
    .filter({
      has: page.getByRole("cell", {
        name: String(original.generation),
        exact: true,
      }),
    })
    .filter({
      has: page.getByRole("cell", { name: original.program.name, exact: true }),
    });
  const completed = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/runtime/rollback" &&
      response.request().method() === "POST",
  );
  await originalBackup
    .getByRole("button", { name: "Roll back", exact: true })
    .click();
  expect((await completed).status()).toBe(200);
  const state = await page.request.get("/api/runtime");
  expect(state.ok()).toBe(true);
  expect((await state.json()).program).toEqual(original.program);
  await page.screenshot({
    path: "test-results/studio-runtime.png",
    fullPage: true,
  });
});

test("capabilities disclose native and hardware gaps", async ({ page }) => {
  await openCurrentGraph(page);
  await chooseWorkspaceSurface(page, "Help");
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
  await chooseWorkspaceTool(page, "Direct MS/TP", "Connection transport");
  await expect(page.getByText("SERIAL MASTER", { exact: true })).toBeVisible();
});
