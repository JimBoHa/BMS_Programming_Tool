import { test, expect, type Page, type Locator } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { chooseWorkspaceTask } from "./workspace-navigation";
const root = path.resolve(".."),
  python = path.join(root, ".venv/bin/python"),
  ref = "8-1/575_1";
function fixture(kind = "basic", title = "Authored example") {
  return execFileSync(
    python,
    [
      "-c",
      kind === "nested"
        ? "from tests.test_caf_logic_display import nested_graph; import sys; sys.stdout.buffer.write(nested_graph())"
        : `from tests.test_caf_graph import make_graph,pack; from bms_tool.caf import CafArchive; import sys; data=make_graph(${kind === "single" ? "wires=[(0,663,2,513)]" : ""}); sys.stdout.buffer.write(pack(CafArchive(data).xml.replace(b'Authored example',sys.argv[1].encode())))`,
      title,
    ],
    {
      cwd: root,
      env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
    },
  );
}
async function logic(page: Page) {
  const nav = page.getByRole("navigation", {
      name: "CAF application tasks",
      exact: true,
    }),
    select = nav.getByRole("combobox", {
      name: "CAF application tasks",
      exact: true,
    });
  if (await select.isVisible()) await select.selectOption({ label: "Logic" });
  else await nav.getByRole("button", { name: "Logic", exact: true }).click();
  const p = page.getByRole("region", { name: "Native CAF graph", exact: true });
  await expect(p.locator(".react-flow__node").first()).toBeVisible();
  return p;
}
async function open(page: Page, kind = "basic", title = "Authored example") {
  await page.goto("/");
  await page
    .getByLabel("Open local CAF application", { exact: true })
    .setInputFiles({
      name: "logic-template.caf",
      mimeType: "application/octet-stream",
      buffer: fixture(kind, title),
    });
  return logic(page);
}
async function wire(page: Page, p: Locator, source: string, target: string) {
  await p.getByRole("button", { name: "Fit diagram", exact: true }).click();
  await p.locator(".caf-logic-canvas").scrollIntoViewIfNeeded();
  const a = await p
    .locator(`.react-flow__node[data-id="${source}"] [data-handleid="out:663"]`)
    .boundingBox();
  const b = await p
    .locator(`.react-flow__node[data-id="${target}"] [data-handleid="in:513"]`)
    .boundingBox();
  expect(a).not.toBeNull();
  expect(b).not.toBeNull();
  await page.mouse.move(a!.x + a!.width / 2, a!.y + a!.height / 2);
  await page.mouse.down();
  await page.mouse.move(b!.x + b!.width / 2, b!.y + b!.height / 2, {
    steps: 20,
  });
  await page.mouse.up();
}
test("CAF canvas shows actual ports, traces wires and retains view positions without file edits", async ({
  page,
  request,
}, info) => {
  const calls: string[] = [];
  page.on("request", (r) => {
    if (r.method() === "POST" && /\/api\/bacnet\//.test(r.url()))
      calls.push(r.url());
  });
  let p = await open(page);
  await expect(p.locator(".react-flow__node")).toHaveCount(4);
  await expect(p.locator(".react-flow__edge")).toHaveCount(2);
  await p.getByRole("button", { name: /^Block 11/ }).click();
  await expect(
    p.getByRole("region", { name: "CAF selected logic block", exact: true }),
  ).toContainText("Stored CAF values");
  await expect(p.locator(".caf-logic-node.in-trace")).toHaveCount(1);
  await p.getByRole("button", { name: "Fit diagram", exact: true }).click();
  const node = p.locator(`.react-flow__node[data-id="${ref}.2_11"]`),
    before = await node.getAttribute("style"),
    box = await node.locator(".caf-logic-node-heading").boundingBox();
  await page.mouse.move(box!.x + 40, box!.y + 10);
  await page.mouse.down();
  await page.mouse.move(box!.x + 110, box!.y + 65, { steps: 12 });
  await page.mouse.up();
  await expect(node).not.toHaveAttribute("style", before!);
  const moved = await node.getAttribute("style");
  await chooseWorkspaceTask(page, "Changes");
  await chooseWorkspaceTask(page, "Program");
  p = await logic(page);
  await expect(
    p.locator(`.react-flow__node[data-id="${ref}.2_11"]`),
  ).toHaveAttribute("style", moved!);
  await p
    .getByRole("button", { name: "Reset view positions", exact: true })
    .click();
  await expect(p.locator(".react-flow__node")).toHaveCount(4);
  await p.getByRole("button", { name: /^Block 12/ }).click();
  await p
    .getByRole("button", { name: "Edit object properties", exact: true })
    .click();
  await expect(
    page.getByLabel("CAF property 3113", { exact: true }),
  ).toHaveValue("12.000");
  p = await logic(page);
  expect(calls).toEqual([]);
  expect(
    (await (await request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
  await page.screenshot({
    path: info.outputPath("caf-logic-desktop.png"),
    fullPage: true,
  });
});
test("dragging native ports reviews and exports an existing connection source change", async ({
  page,
}) => {
  const p = await open(page);
  await wire(page, p, ref + ".2_11", ref + ".2_12");
  await expect(
    p.getByLabel("Native rewire review", { exact: true }),
  ).toContainText("[1,663,2,513]");
  const download = page.waitForEvent("download");
  await p
    .getByRole("button", {
      name: "Check and export native CAF rewire",
      exact: true,
    })
    .click();
  const file = await download;
  const result = JSON.parse(
    execFileSync(
      python,
      [
        "-c",
        "from bms_tool.caf_graph import CafGraph; from pathlib import Path; import sys,json; d=CafGraph(Path(sys.argv[1]).read_bytes()).diagram('8-1/575_1'); print(json.dumps({'wires':[w['raw'] for w in d['connections']],'layout':[b['layout'] for b in d['blocks']],'order':d['execution_order']}))",
        (await file.path())!,
      ],
      {
        cwd: root,
        env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
        encoding: "utf8",
      },
    ),
  );
  expect(result.wires).toEqual([
    [1, 663, 2, 513],
    [1, 663, 3, 513],
  ]);
  expect(result.order).toEqual([0, 1, 2, 3]);
  expect(result.layout[0]).toEqual({ x: "1.000", y: "2.000", opaque_code: 0 });
});
test("dragging to an unused native input uses an original prototype and preserves object inventory", async ({
  page,
}) => {
  const p = await open(page, "single");
  await wire(page, p, ref + ".2_11", ref + ".2_13");
  await expect(
    p.getByLabel("Native new connection review", { exact: true }),
  ).toContainText("[1,663,3,513]");
  const download = page.waitForEvent("download");
  await p
    .getByRole("button", {
      name: "Check and export new native CAF connection",
      exact: true,
    })
    .click();
  const file = await download;
  const result = JSON.parse(
    execFileSync(
      python,
      [
        "-c",
        "from bms_tool.caf_graph import CafGraph; from pathlib import Path; import sys,json; g=CafGraph(Path(sys.argv[1]).read_bytes()); print(json.dumps({'objects':len(g.archive.objects),'wires':[w['raw'] for w in g.diagram('8-1/575_1')['connections']]}))",
        (await file.path())!,
      ],
      {
        cwd: root,
        env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
        encoding: "utf8",
      },
    ),
  );
  expect(result).toEqual({
    objects: 5,
    wires: [
      [0, 663, 2, 513],
      [1, 663, 3, 513],
    ],
  });
});
test("nested module navigation and compact inspector keep exact CAF source", async ({
  page,
}, info) => {
  const p = await open(page, "nested");
  await p.locator(`.react-flow__node[data-id="${ref}.536_20"]`).dblclick();
  await expect(p.getByLabel("Native CAF diagram", { exact: true })).toHaveValue(
    ref + ".536_20",
  );
  await p.getByRole("button", { name: /^Valve demand/ }).click();
  await expect(
    p.getByRole("region", { name: "CAF selected logic block", exact: true }),
  ).toContainText("35.000");
  await page.setViewportSize({ width: 390, height: 1000 });
  await p
    .getByRole("button", { name: "Open CAF logic inspector", exact: true })
    .click();
  await expect(
    p.getByRole("dialog", { name: "CAF logic inspector", exact: true }),
  ).toContainText("Valve demand");
  await p
    .getByRole("button", { name: "Close CAF logic inspector", exact: true })
    .click();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: info.outputPath("caf-logic-phone.png"),
    fullPage: true,
  });
  await p.getByRole("button", { name: /^Up to / }).click();
  await expect(p.getByLabel("Native CAF diagram", { exact: true })).toHaveValue(
    ref,
  );
});

test("CAF view layouts and delayed inspector responses stay with their source archive", async ({
  page,
}) => {
  const calls: string[] = [];
  page.on("request", (r) => {
    if (r.method() === "POST" && /\/api\/bacnet\//.test(r.url()))
      calls.push(r.url());
  });
  let release!: () => void, reached!: () => void;
  const pending = new Promise<void>((r) => (release = r));
  const held = new Promise<void>((r) => (reached = r));
  let intercepted = false;
  await page.route(/\/api\/caf\/[^/]+\/properties\?ref=/, async (route) => {
    const response = await route.fetch();
    if (!intercepted) {
      intercepted = true;
      reached();
      await pending;
    }
    await route.fulfill({ response });
  });
  try {
    let p = await open(page, "basic", "Archive Alpha");
    await p.getByRole("button", { name: /^Block 11/ }).click();
    await held;
    await expect(p.locator(".react-flow__viewport")).toHaveAttribute(
      "style",
      /scale\(1\.2\)/,
    );
    const n = p.locator(`.react-flow__node[data-id="${ref}.2_11"]`);
    await p.locator(".caf-logic-canvas").scrollIntoViewIfNeeded();
    const box = await n.locator(".caf-logic-node-heading").boundingBox();
    const original = await n.evaluate(
      (el) => (el as HTMLElement).style.transform,
    );
    await page.mouse.move(box!.x + 30, box!.y + 10);
    await page.mouse.down();
    await page.mouse.move(box!.x + 100, box!.y + 60, { steps: 12 });
    await page.mouse.up();
    const moved = await n.evaluate((el) => (el as HTMLElement).style.transform);
    expect(moved).not.toBe(original);
    async function replace(title: string) {
      await page
        .getByLabel("Open local CAF application", { exact: true })
        .setInputFiles({
          name: `${title}.caf`,
          mimeType: "application/octet-stream",
          buffer: fixture("basic", title),
        });
      p = await logic(page);
      await expect(
        p
          .getByLabel("Native CAF diagram", { exact: true })
          .locator("option")
          .first(),
      ).toContainText(title);
    }
    await replace("Archive Beta");
    expect(
      await p
        .locator(`.react-flow__node[data-id="${ref}.2_11"]`)
        .evaluate((el) => (el as HTMLElement).style.transform),
    ).toBe(original);
    await p.getByRole("button", { name: /^Block 12/ }).click();
    const inspector = p.getByRole("region", {
      name: "CAF selected logic block",
      exact: true,
    });
    await expect(inspector).toContainText("12.000");
    const delivered = page.waitForResponse(
      (r) =>
        r.url().includes("/properties?ref=") &&
        decodeURIComponent(r.url()).endsWith(".2_11"),
    );
    release();
    await delivered;
    await expect(inspector).toContainText("12.000");
    await expect(inspector).not.toContainText("11.000");
    await replace("Archive Alpha");
    expect(
      await p
        .locator(`.react-flow__node[data-id="${ref}.2_11"]`)
        .evaluate((el) => (el as HTMLElement).style.transform),
    ).toBe(moved);
    await expect(
      p.getByRole("region", { name: "CAF selected logic block", exact: true }),
    ).toContainText("11.000");
    expect(calls).toEqual([]);
  } finally {
    release();
  }
});
