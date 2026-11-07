import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import {
  orderFixture,
  enterOrder,
  stageOrder,
  reviewOrder,
  orderPanel,
  reviewedOrder,
  showOrder,
} from "./caf-execution-order-fixture";
import { removalPython } from "./caf-connection-removal-fixture";
import { chooseWorkspaceTask } from "./workspace-navigation";

for (const workspace of [false, true])
  for (const width of [1440, 390])
    test(`${workspace ? "workspace" : "CAF"} ${width}px exports actual reviewed order and exact proof offline`, async ({
      page,
    }, info) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
      const f = orderFixture();
      await enterOrder(page, f, workspace);
      const field: string[] = [];
      page.on("request", (r) => {
        if (new URL(r.url()).pathname.startsWith("/api/bacnet/"))
          field.push(r.url());
      });
      let exact: Buffer | undefined;
      await page.route("**/execution-order/preview", async (route) => {
        const r = await route.fetch({ maxRetries: 0 });
        exact = await r.body();
        await route.fulfill({ response: r });
      });
      await stageOrder(page);
      await expect(
        orderPanel(page).getByRole("button", {
          name: "Move block later",
          exact: true,
        }),
      ).toBeDisabled();
      await reviewOrder(page);
      const proof = page.waitForEvent("download");
      await reviewedOrder(page)
        .getByRole("button", {
          name: "Save exact execution-order review",
          exact: true,
        })
        .click();
      expect(readFileSync((await (await proof).path())!)).toEqual(exact);
      const download = page.waitForEvent("download");
      await reviewedOrder(page)
        .getByRole("button", {
          name: "Save execution-order CAF copy",
          exact: true,
        })
        .click();
      const file = (await (await download).path())!;
      expect(readFileSync(file)).toEqual(Buffer.from(f.output, "base64"));
      const independent = JSON.parse(
        removalPython(
          `
from pathlib import Path
import json,sys
from bms_tool.caf import CafArchive
from bms_tool.caf_graph import CafGraph
a=CafArchive(Path(sys.argv[1]).read_bytes());g=CafGraph(a).diagram(sys.argv[2])
print(json.dumps(dict(order=g['execution_order'],wires=[w['raw'] for w in g['connections']],hash=a.hash)))
`,
          file,
          f.diagram.ref,
        ),
      );
      expect(independent).toEqual({
        order: [1, 0, 2, 3],
        wires: f.diagram.connections.map((w: any) => w.raw),
        hash: f.review.result.output_sha256,
      });
      await expect(orderPanel(page)).toContainText(
        "The opened original remains unchanged",
      );
      await expect(
        page.getByLabel("Current CAF archive", { exact: true }),
      ).toHaveText("authored-order.caf");
      expect(field).toEqual([]);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= window.innerWidth,
        ),
      ).toBe(true);
      await orderPanel(page)
        .getByRole("button", {
          name: "Discard execution-order proposal",
          exact: true,
        })
        .scrollIntoViewIfNeeded();
      await page.screenshot({
        path: info.outputPath(`execution-order-${width}.png`),
      });
    });

for (const kind of ["activity", "backward", "empty"])
  test(`${kind} diagram retains structure through a real order export`, async ({
    page,
  }) => {
    const f = orderFixture(kind);
    await enterOrder(page, f);
    await stageOrder(page);
    await reviewOrder(page);
    const saved = page.waitForEvent("download");
    await reviewedOrder(page)
      .getByRole("button", {
        name: "Save execution-order CAF copy",
        exact: true,
      })
      .click();
    expect(readFileSync((await (await saved).path())!)).toEqual(
      Buffer.from(f.output, "base64"),
    );
  });

test("drafts survive task navigation, while reviews and downloads retire", async ({
  page,
}) => {
  await enterOrder(page);
  await stageOrder(page);
  await reviewOrder(page);
  await chooseWorkspaceTask(page, "Overview");
  await showOrder(page);
  await expect(reviewedOrder(page)).toHaveCount(0);
  await expect(orderPanel(page)).toContainText(
    "proposal has not been exported",
  );
  await expect(
    orderPanel(page).getByRole("table").locator("tbody tr").first(),
  ).toContainText("Block 11");
  await reviewOrder(page);
  await orderPanel(page)
    .getByRole("button", { name: "Move block earlier", exact: true })
    .click();
  await expect(reviewedOrder(page)).toHaveCount(0);
  await expect(
    orderPanel(page).getByRole("button", {
      name: "Inspect execution order",
      exact: true,
    }),
  ).toBeVisible();
});

for (const stage of ["preview", "export"])
  for (const change of ["task", "source", "pagehide"])
    test(`late ${stage} after ${change} cannot review or download`, async ({
      page,
    }) => {
      await enterOrder(page);
      await stageOrder(page);
      if (stage === "export") await reviewOrder(page);
      let release!: () => void, started!: () => void;
      const gate = new Promise<void>((r) => (release = r)),
        seen = new Promise<void>((r) => (started = r));
      await page.route(`**/execution-order/${stage}`, async (route) => {
        const response = await route.fetch({ maxRetries: 0 });
        started();
        await gate;
        await route.fulfill({ response });
      });
      const downloads: string[] = [];
      page.on("download", (d) => downloads.push(d.suggestedFilename()));
      if (stage === "export")
        await reviewedOrder(page)
          .getByRole("button", {
            name: "Save execution-order CAF copy",
            exact: true,
          })
          .click();
      else
        await orderPanel(page)
          .getByRole("button", { name: "Review execution order", exact: true })
          .click();
      await seen;
      try {
        if (change === "task") await chooseWorkspaceTask(page, "Overview");
        else if (change === "source") {
          page.once("dialog", (d) => void d.accept());
          await page
            .getByLabel("Open local CAF application", { exact: true })
            .setInputFiles({
              name: "other-order.caf",
              mimeType: "application/octet-stream",
              buffer: Buffer.from(orderFixture("activity").caf, "base64"),
            });
          await expect(
            page.getByLabel("Current CAF archive", { exact: true }),
          ).toHaveText("other-order.caf");
        } else
          await page.evaluate(() =>
            window.dispatchEvent(new Event("pagehide")),
          );
      } finally {
        release();
      }
      await page.unrouteAll({ behavior: "wait" });
      await showOrder(page);
      await expect(reviewedOrder(page)).toHaveCount(0);
      expect(downloads).toEqual([]);
      if (change !== "source")
        await expect(orderPanel(page)).toContainText(
          "proposal has not been exported",
        );
    });

for (const fault of ["header", "body"])
  test(`altered ${fault} export stays unexported`, async ({ page }) => {
    const f = orderFixture();
    await enterOrder(page, f);
    await stageOrder(page);
    await reviewOrder(page);
    await page.route("**/execution-order/export", async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      if (fault === "header")
        await route.fulfill({
          response,
          headers: {
            ...response.headers(),
            "x-studio-order-sha256": "0".repeat(64),
          },
        });
      else
        await route.fulfill({ response, body: Buffer.from(f.caf, "base64") });
    });
    const downloads: string[] = [];
    page.on("download", (d) => downloads.push(d.suggestedFilename()));
    await reviewedOrder(page)
      .getByRole("button", {
        name: "Save execution-order CAF copy",
        exact: true,
      })
      .click();
    await expect(orderPanel(page).getByRole("alert")).toContainText(
      "do not match",
    );
    await expect(orderPanel(page)).toContainText(
      "proposal has not been exported",
    );
    expect(downloads).toEqual([]);
  });

test("repeated review clicks coalesce and a retained save callback cannot fetch after retirement", async ({
  page,
}) => {
  await enterOrder(page);
  await stageOrder(page);
  let reads = 0;
  page.on("request", (r) => {
    if (r.url().endsWith("/execution-order/preview")) reads++;
  });
  const button = orderPanel(page).getByRole("button", {
    name: "Review execution order",
    exact: true,
  });
  await button.evaluate((e: any) => {
    const props = e[Object.keys(e).find((k) => k.startsWith("__reactProps$"))!];
    props.onClick();
    props.onClick();
  });
  await expect(reviewedOrder(page)).toBeVisible();
  expect(reads).toBe(1);
  await reviewedOrder(page)
    .getByRole("button", { name: "Save execution-order CAF copy", exact: true })
    .evaluate((e: any) => {
      (window as any).savedOrderClick =
        e[Object.keys(e).find((k) => k.startsWith("__reactProps$"))!].onClick;
    });
  await chooseWorkspaceTask(page, "Overview");
  const count = await page.evaluate(async () => {
    const old = window.fetch;
    let count = 0;
    window.fetch = async () => {
      count++;
      throw Error("Retired callback must not fetch");
    };
    try {
      await (window as any).savedOrderClick();
      await Promise.resolve();
      return count;
    } finally {
      window.fetch = old;
    }
  });
  expect(count).toBe(0);
});

test("unsupported diagram remains inspectable and cannot prepare an order export", async ({
  page,
}) => {
  await enterOrder(page, orderFixture("unsupported"));
  await expect(orderPanel(page).getByRole("table")).toBeVisible();
  await expect(
    orderPanel(page).getByRole("button", {
      name: "Inspect execution order",
      exact: true,
    }),
  ).toBeDisabled();
  await expect(
    orderPanel(page).getByRole("button", {
      name: "Move block later",
      exact: true,
    }),
  ).toBeDisabled();
});

test("keyboard move and review use the same guarded workflow", async ({
  page,
}) => {
  await enterOrder(page);
  const later = orderPanel(page).getByRole("button", {
    name: "Move block later",
    exact: true,
  });
  await expect(later).toBeEnabled();
  await later.focus();
  await expect(later).toBeFocused();
  await later.press("Enter");
  const review = orderPanel(page).getByRole("button", {
    name: "Review execution order",
    exact: true,
  });
  await review.focus();
  await review.press("Enter");
  await expect(reviewedOrder(page)).toBeVisible();
  await expect(
    orderPanel(page).getByRole("button", {
      name: "Move block later",
      exact: true,
    }),
  ).toBeDisabled();
});

for (const change of ["pagehide", "task-return"])
  test(`retained prepare callback cannot fetch after ${change}`, async ({
    page,
  }) => {
    await enterOrder(page);
    await stageOrder(page);
    await orderPanel(page)
      .getByRole("button", { name: "Review execution order", exact: true })
      .evaluate((e: any) => {
        (window as any).savedOrderPrepare =
          e[Object.keys(e).find((k) => k.startsWith("__reactProps$"))!].onClick;
      });
    if (change === "task-return") {
      await chooseWorkspaceTask(page, "Overview");
      await showOrder(page);
    }
    const count = await page.evaluate(async (change) => {
      const old = window.fetch;
      let count = 0;
      window.fetch = async () => {
        count++;
        throw Error("Retired prepare must not fetch");
      };
      try {
        if (change === "pagehide") window.dispatchEvent(new Event("pagehide"));
        (window as any).savedOrderPrepare();
        await Promise.resolve();
        return count;
      } finally {
        window.fetch = old;
      }
    }, change);
    expect(count).toBe(0);
  });
