import { test, expect, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
const root = path.resolve(".."),
  python = path.join(root, ".venv/bin/python");
function py(code: string, input?: string) {
  return execFileSync(python, ["-c", code], {
    cwd: root,
    input,
    encoding: "utf8",
    env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
  });
}
async function holdNativeMeasurements(page: Page) {
  await page.addInitScript(() => {
    const Native = window.ResizeObserver,
      pending: (() => void)[] = [];
    (window as any).__nodeDeliveries = 0;
    (window as any).__deliverNodeMeasurements = () => {
      const all = pending.splice(0);
      all.forEach((run) => run());
      return all.length;
    };
    (window as any).__pendingNodeMeasurements = () => pending.length;
    window.ResizeObserver = class extends Native {
      constructor(callback: ResizeObserverCallback) {
        super((entries, observer) => {
          if (
            entries.some((entry) =>
              entry.target.classList.contains("react-flow__node"),
            )
          )
            pending.push(() => {
              (window as any).__nodeDeliveries++;
              callback(entries, observer);
            });
          else callback(entries, observer);
        });
      }
    };
  });
}
async function importGraph(
  page: Page,
  kind = "Constant",
  name = "Measured graph",
  waitVisible = true,
) {
  const buffer = Buffer.from(
    py(
      `from bms_tool.models import Program,Node;from bms_tool.blocks import BLOCKS;assert ${JSON.stringify(kind)} in BLOCKS;p=Program(id='layout-source',name=${JSON.stringify(name)},nodes=[Node(id='reused',kind=${JSON.stringify(kind)},label='Measured node',params={'value':1.0} if ${JSON.stringify(kind)}=='Constant' else {},x=200,y=100)]);print(p.model_dump_json())`,
    ),
  );
  await page
    .locator(
      'input[type=file][accept=".json,.st,.xml,.graphml,.sedona.zip,.sax,.sab,.bog,.bas"]',
    )
    .setInputFiles({
      name: "layout.bms.json",
      mimeType: "application/json",
      buffer,
    });
  await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
    name,
  );
  await expect(
    page.locator('.react-flow__node[data-id="reused"]'),
  ).toBeAttached();
  if (waitVisible)
    await expect(
      page.locator('.react-flow__node[data-id="reused"]'),
    ).toBeVisible();
}
async function exported(page: Page) {
  const event = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export", exact: true }).click();
  return readFileSync((await (await event).path())!, "utf8");
}
function geometry(page: Page) {
  return page
    .locator('.react-flow__node[data-id="reused"]')
    .evaluate((element) => ({
      visibility: getComputedStyle(element).visibility,
      width: (element as HTMLElement).offsetWidth,
      height: (element as HTMLElement).offsetHeight,
      handles: element.querySelectorAll(".input-port .react-flow__handle")
        .length,
    }));
}
test("delivered measurement survives parent renders and undo/redo without another observer delivery", async ({
  page,
}) => {
  await holdNativeMeasurements(page);
  await page.goto("/");
  await importGraph(page, "Constant", "Measured graph", false);
  await expect
    .poll(() =>
      page.evaluate(() => (window as any).__pendingNodeMeasurements()),
    )
    .toBeGreaterThan(0);
  expect(
    await page.evaluate(() => (window as any).__deliverNodeMeasurements()),
  ).toBeGreaterThan(0);
  await expect(
    page.locator('.react-flow__node[data-id="reused"]'),
  ).toBeVisible();
  const deliveries = await page.evaluate(
    () => (window as any).__nodeDeliveries,
  );
  const before = await exported(page),
    size = await geometry(page);
  await page.locator('.react-flow__node[data-id="reused"]').click();
  const value = page.getByLabel("value", { exact: true });
  await value.fill("2.0");
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(
    page.locator('.react-flow__node[data-id="reused"]'),
  ).toBeVisible();
  await page.locator('.react-flow__node[data-id="reused"]').click();
  await expect(value).toHaveValue("1.0");
  await page.getByRole("button", { name: "Redo", exact: true }).click();
  await expect(value).toHaveValue("2.0");
  await expect(
    page.locator('.react-flow__node[data-id="reused"]'),
  ).toBeVisible();
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await page
    .getByLabel("Program name", { exact: true })
    .fill("Parent render with retained dimensions");
  await expect(
    page.locator('.react-flow__node[data-id="reused"]'),
  ).toBeVisible();
  expect(await geometry(page)).toEqual(size);
  // Native measurement callbacks remain held after the first explicit delivery.
  expect(await page.evaluate(() => (window as any).__nodeDeliveries)).toBe(
    deliveries,
  );
  const after = await exported(page);
  const info = JSON.parse(
    py(
      "import json,sys;from bms_tool.models import Program;a,b=json.loads(sys.stdin.read());p=Program.model_validate_json(a);q=Program.model_validate_json(b);q.name=p.name;assert p.digest()==q.digest();assert all(not ({'measured','width','height','owner'}&set(n)) for n in json.loads(b)['nodes']);print(json.dumps({'value':repr(q.nodes[0].params['value'])}))",
      JSON.stringify([before, after]),
    ),
  );
  expect(info.value).toBe("1.0");
});
test("removed/readded nodes and replacement with reused ID use current DOM port geometry", async ({
  page,
}) => {
  await holdNativeMeasurements(page);
  await page.goto("/");
  await importGraph(page);
  await page.locator('.react-flow__node[data-id="reused"]').click();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(page.locator('.react-flow__node[data-id="reused"]')).toHaveCount(
    0,
  );
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(
    page.locator('.react-flow__node[data-id="reused"]'),
  ).toBeVisible();
  const constantSize = await geometry(page);
  await importGraph(page, "Abs", "Replacement with same box and new port");
  await expect(
    page.locator('.react-flow__node[data-id="reused"] .input-port'),
  ).toHaveCount(1);
  expect((await geometry(page)).height).toBe(constantSize.height);
  await page.evaluate(() => (window as any).__deliverNodeMeasurements());
  await page
    .getByLabel("Program name", { exact: true })
    .fill("After equal-size port replacement");
  await expect(
    page.locator('.react-flow__node[data-id="reused"]'),
  ).toBeVisible();
  await importGraph(page, "PI", "Replacement with ports");
  await expect(
    page.locator('.react-flow__node[data-id="reused"] .input-port'),
  ).toHaveCount(2);
  const current = await geometry(page);
  expect(current.height).toBeGreaterThan(108);
  expect(current.handles).toBe(2);
  await page.evaluate(() => (window as any).__deliverNodeMeasurements());
  await page
    .getByLabel("Program name", { exact: true })
    .fill("After delayed old measurement delivery");
  await expect(
    page.locator('.react-flow__node[data-id="reused"]'),
  ).toBeVisible();
  expect(await geometry(page)).toEqual(current);
  await page.locator('.react-flow__node[data-id="reused"]').click();
  await expect(page.getByLabel("Label", { exact: true })).toHaveValue(
    "Measured node",
  );
});
