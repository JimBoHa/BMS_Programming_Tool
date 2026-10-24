import { test, expect } from "./simulationFixture";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import { projectedSourceFixture } from "./sourceTransportFixtures";

const root = path.resolve("..");
const python = path.join(root, ".venv/bin/python");

// Authored graph only; no private controller files or simulated HTTP responses.
function sourceProgram() {
  return execFileSync(
    python,
    [
      "-c",
      `from bms_tool.models import Edge, Node, Program
p=Program(id='niagara-extended-browser',nodes=[
Node(id='sensor',kind='Input',unit='degF',params={'default':77}),
Node(id='temperature',kind='Convert',unit='degC',params={'from':'degF','to':'degC'}),
Node(id='bounded',kind='Clamp',unit='degC',params={'min':0,'max':40}),
Node(id='scale',kind='Scale',unit='cfm',params={'in_min':10,'in_max':30,'out_min':200,'out_max':600,'clamp':False}),
Node(id='flow',kind='Output',unit='cfm'),
Node(id='reset',kind='Scale',unit='degC',params={'in_min':0,'in_max':50,'out_min':10,'out_max':20,'clamp':True}),
Node(id='reset_out',kind='Output',unit='degC')],edges=[
Edge(id='a',source='sensor',target='temperature'),
Edge(id='b',source='temperature',target='bounded'),
Edge(id='c',source='bounded',target='scale'),
Edge(id='d',source='scale',target='flow'),
Edge(id='e',source='bounded',target='reset'),
Edge(id='f',source='reset',target='reset_out')])
print(p.model_dump_json())`,
    ],
    { cwd: root },
  );
}

test("Clamp, Scale and Convert export genuine native BOG and preserve reviewed foreign finite behavior", async ({
  page,
  request,
}) => {
  await page.goto("/");
  const fileInput = page.locator('input[type=file][accept*=".st"]');
  await fileInput.setInputFiles({
    name: "extended.bms.json",
    mimeType: "application/json",
    buffer: sourceProgram(),
  });
  await expect(page.locator(".react-flow__node")).toHaveCount(7);
  const profile = await (await request.get("/api/niagara/profile")).json();
  expect(profile.native_types).toHaveLength(23);
  expect(profile.native_types).toEqual(
    expect.arrayContaining(["Clamp", "Scale", "Convert"]),
  );
  expect(profile.native_runtime_verified).toBe(false);
  await page.getByLabel("Export format").selectOption("bog");
  const pending = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export", exact: true }).click();
  const downloaded = await pending;
  expect(downloaded.suggestedFilename()).toMatch(/\.bog$/);
  const filename = (await downloaded.path())!;
  const content = readFileSync(filename);
  expect(content.subarray(0, 2).toString()).toBe("PK");
  // Inspect ZIP/XML independently of the semantic importer.
  const inspected = JSON.parse(
    execFileSync(
      python,
      [
        "-c",
        `import json,re,sys,zipfile,xml.etree.ElementTree as X
with zipfile.ZipFile(sys.argv[1]) as z:
 assert z.namelist()==['file.xml']
 xml=z.read('file.xml')
root=X.fromstring(xml)
types=sorted({p.get('t') for p in root.iter('p') if p.get('h')})
print(json.dumps({'types':types,'foreign':re.sub(rb'<!-- BMS_STUDIO_BOG_V1 [A-Za-z0-9+/=]+ -->',b'',xml).decode()}))`,
        filename,
      ],
      { cwd: root, encoding: "utf8" },
    ),
  );
  expect(inspected.types).toEqual(
    expect.arrayContaining([
      "kitControl:NumericUnitConverter",
      "kitControl:Minimum",
      "kitControl:Maximum",
      "kitControl:Subtract",
      "kitControl:Divide",
      "kitControl:Multiply",
      "kitControl:Add",
      "kitControl:Reset",
    ]),
  );
  await expect(
    page.getByText("native runtime acceptance is unverified", { exact: false }),
  ).toBeVisible();

  await page.getByRole("button", { name: "New program", exact: true }).click();
  await expect(page.locator(".react-flow__node")).toHaveCount(0);
  await fileInput.setInputFiles({
    name: "original.bog",
    mimeType: "application/zip",
    buffer: content,
  });
  await expect(page.locator(".react-flow__node")).toHaveCount(7);
  await page
    .getByRole("button", { name: "Step simulation", exact: true })
    .click();
  await expect(page.locator(".trend-legend")).toContainText("flow: 500 cfm");
  await expect(page.locator(".trend-legend")).toContainText(
    "reset_out: 15 degC",
  );

  // Removing checked Studio source exercises actual native semantic conversion.
  const importing = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/import") &&
      response.request().method() === "POST",
  );
  await fileInput.setInputFiles({
    name: "foreign-native.bog",
    mimeType: "application/xml",
    buffer: Buffer.from(inspected.foreign),
  });
  const foreign = projectedSourceFixture(await (await importing).json());
  expect(foreign.metadata.conversion.review_required).toBe(true);
  expect(
    foreign.nodes.filter((node: any) => node.kind === "Convert"),
  ).toHaveLength(1);
  expect(
    foreign.nodes.filter((node: any) => node.kind === "Clamp"),
  ).toHaveLength(0);
  await expect(page.locator(".conversion-report")).toContainText(
    "can round differently",
  );
  await expect(page.locator(".conversion-report")).toContainText(
    "Niagara links update on events",
  );
  await page
    .getByRole("button", { name: "Close settings", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Step simulation", exact: true })
    .click();
  await expect(page.locator(".trend-legend")).toContainText("n_flow: 500 cfm");
  await expect(page.locator(".trend-legend")).toContainText(
    "n_reset_out: 15 degC",
  );
  const sensor = foreign.nodes.find((node: any) => node.kind === "Input");
  await page.getByLabel("Simulate " + sensor.id, { exact: true }).fill("212");
  await page
    .getByRole("button", { name: "Step simulation", exact: true })
    .click();
  await expect(page.locator(".trend-legend")).toContainText("n_flow: 800 cfm");
  await expect(page.locator(".trend-legend")).toContainText(
    "n_reset_out: 18 degC",
  );
  const before = await page.locator(".react-flow__node").count();
  const invalid = execFileSync(
    python,
    [
      "-c",
      "from tests.test_niagara_extended import foreign_converter,TEMPERATURE_FACETS; import sys; sys.stdout.buffer.write(foreign_converter(TEMPERATURE_FACETS['degF'],'units=u:percent;%;;;'))",
    ],
    { cwd: root },
  );
  await fileInput.setInputFiles({
    name: "incompatible-units.bog",
    mimeType: "application/xml",
    buffer: invalid,
  });
  await expect(
    page.getByText("requires explicit supported temperature units", {
      exact: false,
    }),
  ).toBeVisible();
  await expect(page.locator(".react-flow__node")).toHaveCount(before);
  expect(
    (await (await request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
});
