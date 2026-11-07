import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import {
  orderFixture,
  enterOrder,
  openOrder,
  stageOrder,
  reviewOrder,
  nativeOrderPanel,
  nativeOrderReview,
  python,
} from "./native-execution-order-fixture";
import {
  openNativeCompiler,
  chooseWorkspaceTask,
} from "./workspace-navigation";

for (const caf of [false, true])
  for (const width of [1440, 390])
    test(`${caf ? "CAF" : "workspace"} ${width}px compiles and exports the exact saved-effective native order`, async ({
      page,
    }, info) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
      const f = orderFixture(process.env.BMS_TEST_COMPILER_STATE!);
      await enterOrder(page, f, caf);
      const field: string[] = [];
      page.on("request", (r) => {
        if (
          /\/(connect|apply|capture|reconcile|preview-transfer)$/.test(
            new URL(r.url()).pathname,
          )
        )
          field.push(r.url());
      });
      let exact: Buffer | undefined;
      await page.route(
        "**/inspection/execution-order/preview",
        async (route) => {
          const r = await route.fetch({ maxRetries: 0 });
          exact = await r.body();
          await route.fulfill({ response: r });
        },
      );
      await stageOrder(page);
      await expect(
        nativeOrderPanel(page).getByRole("button", {
          name: "Move native block later",
          exact: true,
        }),
      ).toBeDisabled();
      await reviewOrder(page);
      const reviewDownload = page.waitForEvent("download");
      await nativeOrderReview(page)
        .getByRole("button", {
          name: "Save exact native order review",
          exact: true,
        })
        .click();
      expect(readFileSync((await (await reviewDownload).path())!)).toEqual(
        exact,
      );
      const saved = page.waitForEvent("download");
      await nativeOrderReview(page)
        .getByRole("button", {
          name: "Save native execution-order copy",
          exact: true,
        })
        .click();
      const path = (await (await saved).path())!;
      expect(readFileSync(path)).toEqual(Buffer.from(f.output, "base64"));
      const actual = JSON.parse(
        python(
          `
import json,sys
from pathlib import Path
from bms_tool.moi_identity import MoiIdentity
from tests.test_moi_wire_sources import REF,A,B
from tests.test_native_wire_compiler import BOOLEAN
x=MoiIdentity(Path(sys.argv[1]).read_bytes());r=x.reader
print(json.dumps(dict(order=r.diagram(REF)['execution_order'],real_a=r.scalar(r.records[A],3113),real_b=r.scalar(r.records[B],3113),boolean=r.scalar(r.records[BOOLEAN],3113))))
`,
          path,
        ),
      );
      expect(actual).toEqual({
        order: [1, 0, 2, 3],
        real_a: 42,
        real_b: 17,
        boolean: true,
      });
      await expect(nativeOrderPanel(page)).toContainText(
        "retained originals are unchanged",
      );
      expect(field).toEqual([]);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= window.innerWidth,
        ),
      ).toBe(true);
      await nativeOrderPanel(page)
        .getByRole("button", {
          name: "Discard native order proposal",
          exact: true,
        })
        .scrollIntoViewIfNeeded();
      await page.screenshot({
        path: info.outputPath(`native-order-${width}.png`),
      });
    });

for (const kind of ["raw", "activity", "empty", "backward", "serial", "noop"])
  test(`${kind} source exports its independently checked effective order`, async ({
    page,
  }) => {
    const f = orderFixture(process.env.BMS_TEST_COMPILER_STATE!, kind);
    await enterOrder(page, f);
    if (kind !== "noop") await stageOrder(page);
    await reviewOrder(page);
    const saved = page.waitForEvent("download");
    await nativeOrderReview(page)
      .getByRole("button", {
        name: "Save native execution-order copy",
        exact: true,
      })
      .click();
    expect(readFileSync((await (await saved).path())!)).toEqual(
      Buffer.from(f.output, "base64"),
    );
  });

test("mode and task navigation retain the proposal and retire its review", async ({
  page,
}) => {
  const f = orderFixture(process.env.BMS_TEST_COMPILER_STATE!),
    x = await enterOrder(page, f);
  await stageOrder(page);
  await reviewOrder(page);
  await x.operations
    .getByLabel("Native diagram operation", { exact: true })
    .selectOption("source");
  await x.operations
    .getByLabel("Native diagram operation", { exact: true })
    .selectOption("order");
  await expect(nativeOrderReview(page)).toHaveCount(0);
  await expect(nativeOrderPanel(page)).toContainText(
    "proposal has not been exported",
  );
  await reviewOrder(page);
  await chooseWorkspaceTask(page, "Overview");
  await openNativeCompiler(page);
  await openOrder(page, x.compiler);
  await expect(nativeOrderReview(page)).toHaveCount(0);
  await expect(nativeOrderPanel(page)).toContainText(
    "proposal has not been exported",
  );
  await nativeOrderPanel(page)
    .getByRole("button", { name: "Move native block earlier", exact: true })
    .click();
  await expect(
    nativeOrderPanel(page).getByRole("button", {
      name: "Discard native order proposal",
      exact: true,
    }),
  ).toHaveCount(0);
});

for (const stage of ["preview", "export"])
  for (const change of ["mode", "source", "pagehide"])
    test(`late native order ${stage} after ${change} cannot review or save`, async ({
      page,
    }) => {
      const f = orderFixture(process.env.BMS_TEST_COMPILER_STATE!),
        x = await enterOrder(page, f);
      await stageOrder(page);
      if (stage === "export") await reviewOrder(page);
      let release!: () => void, started!: () => void;
      const gate = new Promise<void>((r) => (release = r)),
        seen = new Promise<void>((r) => (started = r));
      await page.route(
        `**/inspection/execution-order/${stage}`,
        async (route) => {
          const response = await route.fetch({ maxRetries: 0 });
          started();
          await gate;
          await route.fulfill({ response });
        },
      );
      const downloads: string[] = [];
      page.on("download", (d) => downloads.push(d.suggestedFilename()));
      await (
        stage === "export"
          ? nativeOrderReview(page).getByRole("button", {
              name: "Save native execution-order copy",
              exact: true,
            })
          : nativeOrderPanel(page).getByRole("button", {
              name: "Review native execution-order compilation",
              exact: true,
            })
      ).click();
      await seen;
      try {
        if (change === "mode")
          await x.operations
            .getByLabel("Native diagram operation", { exact: true })
            .selectOption("source");
        else if (change === "source")
          await x.compiler
            .getByLabel("Retained native backup", { exact: true })
            .selectOption(f.other);
        else
          await page.evaluate(() =>
            window.dispatchEvent(new Event("pagehide")),
          );
      } finally {
        release();
      }
      await page.unrouteAll({ behavior: "wait" });
      expect(downloads).toEqual([]);
      if (change === "mode")
        await x.operations
          .getByLabel("Native diagram operation", { exact: true })
          .selectOption("order");
      await expect(nativeOrderReview(page)).toHaveCount(0);
    });

for (const fault of ["source", "header", "body"])
  test(`altered ${fault} refuses native order authority or download`, async ({
    page,
  }) => {
    const f = orderFixture(process.env.BMS_TEST_COMPILER_STATE!);
    await enterOrder(page, f);
    await stageOrder(page);
    const downloads: string[] = [];
    page.on("download", (d) => downloads.push(d.suggestedFilename()));
    if (fault === "source") {
      await page.route(
        "**/inspection/execution-order/source",
        async (route) => {
          const response = await route.fetch({ maxRetries: 0 });
          const data = await response.json();
          data.target.address = "99";
          await route.fulfill({ response, json: data });
        },
      );
      await nativeOrderPanel(page)
        .getByRole("button", {
          name: "Review native execution-order compilation",
          exact: true,
        })
        .click();
      await expect(nativeOrderPanel(page).getByRole("alert")).toContainText(
        "source proof",
      );
    } else {
      await reviewOrder(page);
      await page.route(
        "**/inspection/execution-order/export",
        async (route) => {
          const response = await route.fetch({ maxRetries: 0 });
          if (fault === "header")
            await route.fulfill({
              response,
              headers: {
                ...response.headers(),
                "x-studio-compilation-sha256": "0".repeat(64),
              },
            });
          else
            await route.fulfill({
              response,
              body: Buffer.from("wrong native bytes"),
            });
        },
      );
      await nativeOrderReview(page)
        .getByRole("button", {
          name: "Save native execution-order copy",
          exact: true,
        })
        .click();
      await expect(nativeOrderPanel(page).getByRole("alert")).toContainText(
        "do not match",
      );
    }
    expect(downloads).toEqual([]);
    await expect(nativeOrderPanel(page)).toContainText(
      "proposal has not been exported",
    );
  });

for (const change of ["coalesced mode return", "pagehide"])
  test(`retained prepare callback sends no request after ${change}`, async ({
    page,
  }) => {
    const f = orderFixture(process.env.BMS_TEST_COMPILER_STATE!),
      x = await enterOrder(page, f);
    await stageOrder(page);
    await nativeOrderPanel(page)
      .getByRole("button", {
        name: "Review native execution-order compilation",
        exact: true,
      })
      .evaluate((e: any) => {
        (window as any).oldNativeOrder =
          e[Object.keys(e).find((k) => k.startsWith("__reactProps$"))!].onClick;
      });
    const count = await x.operations
      .getByLabel("Native diagram operation", { exact: true })
      .evaluate(async (e: any, change) => {
        const old = window.fetch;
        let count = 0;
        window.fetch = async () => {
          count++;
          throw Error("Retired preparation must not fetch");
        };
        try {
          if (change === "pagehide")
            window.dispatchEvent(new Event("pagehide"));
          else {
            const p =
              e[Object.keys(e).find((k) => k.startsWith("__reactProps$"))!];
            p.onChange({ target: { value: "source" } });
            p.onChange({ target: { value: "order" } });
          }
          (window as any).oldNativeOrder();
          await Promise.resolve();
          return count;
        } finally {
          window.fetch = old;
        }
      }, change);
    expect(count).toBe(0);
    if (change === "coalesced mode return") {
      await expect(
        nativeOrderPanel(page).getByRole("button", {
          name: "Review native execution-order compilation",
          exact: true,
        }),
      ).toBeEnabled();
      await reviewOrder(page);
    }
  });

test("keyboard movement and coalesced review clicks share the guarded path", async ({
  page,
}) => {
  const f = orderFixture(process.env.BMS_TEST_COMPILER_STATE!);
  await enterOrder(page, f);
  const later = nativeOrderPanel(page).getByRole("button", {
    name: "Move native block later",
    exact: true,
  });
  await expect(later).toBeEnabled();
  await later.focus();
  await expect(later).toBeFocused();
  await later.press("Enter");
  let previews = 0;
  page.on("request", (r) => {
    if (r.url().endsWith("/inspection/execution-order/preview")) previews++;
  });
  await nativeOrderPanel(page)
    .getByRole("button", {
      name: "Review native execution-order compilation",
      exact: true,
    })
    .evaluate((e: any) => {
      const p = e[Object.keys(e).find((k) => k.startsWith("__reactProps$"))!];
      p.onClick();
      p.onClick();
    });
  await expect(nativeOrderReview(page)).toBeVisible();
  expect(previews).toBe(1);
});
