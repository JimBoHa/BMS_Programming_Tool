import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";

const root = path.resolve("..");
const python = path.join(root, ".venv/bin/python");

function example(unsafe = false) {
  return execFileSync(
    python,
    [
      "-c",
      unsafe
        ? "from tests.test_caf_graph import make_graph,pack,REF; from bms_tool.caf import CafArchive; import sys; x=CafArchive(make_graph()).xml; at=x.index(('ref=\"'+REF+'.2_11\"').encode()); x=x[:at]+x[at:].replace(b'<opaque><unsignedShort>44</unsignedShort></opaque>',b'<opaque><unsignedShort>45</unsignedShort></opaque>',1); sys.stdout.buffer.write(pack(x))"
        : "from tests.test_caf_graph import make_graph; import sys; sys.stdout.buffer.write(make_graph())",
    ],
    { cwd: root },
  );
}

test("inspect native CAF graph and export one verified source-index change", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "CAF files", exact: true }).click();
  const original = example();
  await page.locator('input[type=file][accept=".caf"]').setInputFiles({
    name: "native-graph.caf",
    mimeType: "application/octet-stream",
    buffer: original,
  });
  const panel = page.getByRole("region", {
    name: "Native CAF graph",
    exact: true,
  });
  await expect(
    panel.getByRole("heading", { name: "Native CAF diagrams" }),
  ).toBeVisible();
  await expect(panel.locator(".caf-graph-summary")).toContainText(
    "4 blocks · 2 connections",
  );
  await expect(panel).toContainText(
    "CCT/PCT acceptance and controller execution remain unverified",
  );
  await expect(
    panel.getByLabel("Native CAF diagram", { exact: true }),
  ).toHaveValue("8-1/575_1");
  await panel
    .getByText("Inspect 4 native blocks and execution order", { exact: true })
    .click();
  await expect(panel.locator(".caf-graph-blocks")).toContainText(
    "BACnet type 2, instance 10",
  );
  await panel
    .getByLabel("Native replacement source", { exact: true })
    .selectOption("8-1/575_1.2_11");
  await expect(
    panel.getByLabel("Native rewire review", { exact: true }),
  ).toContainText("[0,663,2,513]");
  await expect(
    panel.getByLabel("Native rewire review", { exact: true }),
  ).toContainText("[1,663,2,513]");
  const downloaded = page.waitForEvent("download");
  await panel
    .getByRole("button", {
      name: "Check and export native CAF rewire",
      exact: true,
    })
    .click();
  const file = await downloaded;
  expect(file.suggestedFilename()).toMatch(/-rewired\.caf$/);
  const inspected = JSON.parse(
    execFileSync(
      python,
      [
        "-c",
        "from bms_tool.caf_graph import CafGraph; from pathlib import Path; import sys,json; g=CafGraph(Path(sys.argv[1]).read_bytes()); print(json.dumps({'connections':[w['raw']for w in g.diagram('8-1/575_1')['connections']],'count':len(g.archive.objects)}))",
        (await file.path())!,
      ],
      { cwd: root, encoding: "utf8" },
    ),
  );
  expect(inspected).toEqual({
    connections: [
      [1, 663, 2, 513],
      [1, 663, 3, 513],
    ],
    count: 5,
  });
  await expect(panel.getByRole("status")).toContainText(
    "This view still shows the original archive",
  );
  await expect(
    panel.getByLabel("Native rewire review", { exact: true }),
  ).toContainText("[0,663,2,513]");
  await page.screenshot({
    path: "test-results/studio-caf-native-graph.png",
    fullPage: true,
  });
});

test("native CAF source export rejects incompatible opaque configuration", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "CAF files", exact: true }).click();
  await page.locator('input[type=file][accept=".caf"]').setInputFiles({
    name: "native-config-mismatch.caf",
    mimeType: "application/octet-stream",
    buffer: example(true),
  });
  const panel = page.getByRole("region", {
    name: "Native CAF graph",
    exact: true,
  });
  await panel
    .getByLabel("Native replacement source", { exact: true })
    .selectOption("8-1/575_1.2_11");
  await panel
    .getByRole("button", {
      name: "Check and export native CAF rewire",
      exact: true,
    })
    .click();
  await expect(panel.getByRole("alert")).toContainText(
    "different native configuration/type information",
  );
  await expect(
    panel.getByLabel("Native rewire review", { exact: true }),
  ).toContainText("[0,663,2,513]");
});

test("add a native CAF connection from an observed prototype without adding objects", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "CAF files", exact: true }).click();
  const buffer = execFileSync(
    python,
    [
      "-c",
      "from tests.test_caf_graph import make_graph; import sys; sys.stdout.buffer.write(make_graph(wires=[(0,663,2,513)]))",
    ],
    { cwd: root },
  );
  await page
    .locator('input[type=file][accept=".caf"]')
    .setInputFiles({
      name: "native-create.caf",
      mimeType: "application/octet-stream",
      buffer,
    });
  const panel = page.getByRole("region", {
    name: "Native CAF graph",
    exact: true,
  });
  await panel
    .getByText("Add native connection between existing blocks", { exact: true })
    .click();
  await panel
    .getByLabel("Native new connection source", { exact: true })
    .selectOption("8-1/575_1.2_11");
  await panel
    .getByLabel("Native new connection destination", { exact: true })
    .selectOption("8-1/575_1.2_13");
  await expect(
    panel.getByLabel("Native new connection review", { exact: true }),
  ).toContainText("[1,663,3,513]");
  const pending = page.waitForEvent("download");
  await panel
    .getByRole("button", {
      name: "Check and export new native CAF connection",
      exact: true,
    })
    .click();
  const file = await pending;
  expect(file.suggestedFilename()).toBe("native-create-connected.caf");
  const inspected = JSON.parse(
    execFileSync(
      python,
      [
        "-c",
        "from bms_tool.caf_graph import CafGraph; from pathlib import Path; import json,sys; g=CafGraph(Path(sys.argv[1]).read_bytes()); print(json.dumps({'wires':[w['raw']for w in g.diagram('8-1/575_1')['connections']],'count':len(g.archive.objects)}))",
        (await file.path())!,
      ],
      { cwd: root, encoding: "utf8" },
    ),
  );
  expect(inspected).toEqual({
    wires: [
      [0, 663, 2, 513],
      [1, 663, 3, 513],
    ],
    count: 5,
  });
  await expect(panel.locator(".caf-graph-summary")).toContainText(
    "4 blocks · 1 connections",
  );
  await expect(panel.getByRole("status")).toContainText(
    "added native connection",
  );
});
