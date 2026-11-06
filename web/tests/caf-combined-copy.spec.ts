import { test, expect } from "@playwright/test";
import { python } from "./caf-simulation-fixture";
import {
  openCombined,
  showCombined,
  panel,
  editScalar,
  logic,
} from "./caf-combined-copy-fixture";
import { cafChanges, cafObjects } from "./caf-scalar-draft-recovery-fixture";

for (const width of [1440, 390])
  for (const kind of ["rewire", "connect"])
    for (const enumValue of [false, true])
      test(`${width} ${kind} ${enumValue ? "Enum" : "Float"} combined review, exact output and explicit open`, async ({
        page,
      }) => {
        await page.setViewportSize({ width, height: 1000 });
        const f = await openCombined(page, kind, enumValue),
          p = panel(page);
        await p
          .getByRole("button", {
            name: "Review scalar + wiring copy",
            exact: true,
          })
          .click();
        await expect(
          p.getByRole("button", {
            name: "Save combined CAF copy",
            exact: true,
          }),
        ).toBeEnabled();
        await expect(
          p.getByRole("region", { name: "Combined scalar review" }),
        ).toContainText(enumValue ? "0002" : "12.5000");
        await expect(p).toContainText("1 changed fields and 1 wiring changes");
        if (width === 390 && kind === "rewire" && !enumValue) {
          const table = p.getByRole("region", {
            name: "Combined scalar review",
          });
          await table.focus();
          await table.press("End");
          expect(await table.evaluate((el) => el.scrollLeft)).toBeGreaterThan(
            0,
          );
          await table.press("Home");
          await p.scrollIntoViewIfNeeded();
          await page.screenshot({
            path: test.info().outputPath("combined-review-phone.png"),
          });
          expect(
            await page.evaluate(
              () => document.documentElement.scrollWidth <= window.innerWidth,
            ),
          ).toBe(true);
        }
        const downloading = page.waitForEvent("download");
        await p
          .getByRole("button", { name: "Save combined CAF copy", exact: true })
          .click();
        const download = await downloading;
        expect(download.suggestedFilename()).toBe(
          "combined-example-combined.caf",
        );
        const checked = JSON.parse(
          python(
            `
import json,sys
from pathlib import Path
from bms_tool.caf import CafArchive
from bms_tool.caf_graph import CafGraph
from tests.test_caf_combined_copy import combined_fixture
from tests.test_caf_graph import REF,record,shorts,prop
kind=sys.argv[2];enum=sys.argv[3]=='yes';raw,_=combined_fixture(kind,enum=enum);original=CafArchive(raw)
a=CafArchive(Path(sys.argv[1]).read_bytes());x=original.xml.replace(b'<enum set="510">10</enum>' if enum else b'<float>10.000</float>',b'<enum set="510">2</enum>' if enum else b'<float>12.5</float>',1)
if kind=='rewire':x=x.replace(record(*shorts(0,663,2,513)).encode(),record(*shorts(1,663,2,513)).encode(),1)
else:
 old=record(*shorts(0,663,2,513));x=x.replace(prop('3118','<array>'+old+'</array>').encode(),prop('3118','<array>'+old+record(*shorts(1,663,3,513))+'</array>').encode(),1)
 at=x.index(b'<property id="3384">');end=x.index(b'</listof>',at);x=x[:end]+b'<struct><structElement><boolean>0</boolean></structElement><structElement><string /></structElement></struct>'+x[end:]
print(json.dumps({'exact':a.xml==x,'objects':len(a.objects),'hash':a.hash}))
`,
            (await download.path())!,
            kind,
            enumValue ? "yes" : "no",
          ).toString(),
        );
        expect(checked.exact).toBe(true);
        expect(checked.objects).toBe(5);
        await expect(
          page.getByLabel("Current CAF archive", { exact: true }),
        ).toHaveText("combined-example.caf");
        await expect(
          p.getByRole("button", { name: "Open CAF copy", exact: true }),
        ).toBeEnabled();
        await p
          .getByRole("button", { name: "Open CAF copy", exact: true })
          .click();
        await expect(
          page.getByLabel("Current CAF archive", { exact: true }),
        ).toHaveText("combined-example-combined.caf");
        await expect(
          page.getByRole("region", { name: "Native CAF graph", exact: true }),
        ).toContainText(
          kind === "connect"
            ? "4 blocks · 2 connections"
            : "4 blocks · 2 connections",
        );
        expect(f.hash).not.toBe(checked.hash);
        if (width === 390 && kind === "rewire" && !enumValue)
          await page.screenshot({
            path: test.info().outputPath("combined-open-phone.png"),
          });
      });

test("invalid scalar produces no combined artifact and retains raw proposal", async ({
  page,
}) => {
  await openCombined(page, "rewire", false, "1e");
  let exports = 0;
  page.on("request", (r) => {
    if (r.url().endsWith("/combined-copy/export")) exports++;
  });
  await panel(page)
    .getByRole("button", { name: "Review scalar + wiring copy", exact: true })
    .click();
  await expect(panel(page).getByRole("alert")).toBeVisible();
  await expect(
    panel(page).getByRole("button", { name: "Save combined CAF copy" }),
  ).toHaveCount(0);
  await cafChanges(page);
  await expect(
    page.getByRole("region", { name: "Local CAF change review" }),
  ).toContainText("1e");
  expect(exports).toBe(0);
});

test("task exit during held export retires download and keeps both drafts unsaved", async ({
  page,
}) => {
  await openCombined(page);
  const p = panel(page);
  await p
    .getByRole("button", { name: "Review scalar + wiring copy", exact: true })
    .click();
  await expect(
    p.getByRole("button", { name: "Save combined CAF copy" }),
  ).toBeEnabled();
  let release!: () => void;
  const held = new Promise<void>((r) => (release = r));
  let arrived!: () => void;
  const sent = new Promise<void>((r) => (arrived = r));
  await page.route("**/combined-copy/export", async (route) => {
    arrived();
    await held;
    await route.continue();
  });
  let downloads = 0;
  page.on("download", () => downloads++);
  await p.getByRole("button", { name: "Save combined CAF copy" }).click();
  await sent;
  await cafObjects(page);
  release();
  await page.waitForResponse((r) => r.url().endsWith("/combined-copy/export"));
  await showCombined(page, "rewire", false);
  await expect(
    panel(page).getByRole("button", { name: "Save combined CAF copy" }),
  ).toHaveCount(0);
  await expect(
    page.getByLabel("Native replacement source", { exact: true }),
  ).toHaveValue("8-1/575_1.2_11");
  expect(downloads).toBe(0);
  await panel(page)
    .getByRole("button", { name: "Review scalar + wiring copy" })
    .click();
  await expect(
    panel(page).getByRole("button", { name: "Save combined CAF copy" }),
  ).toBeEnabled();
});

test("scalar edit ABA retires an earlier review while retaining the wire", async ({
  page,
}) => {
  await openCombined(page);
  await panel(page)
    .getByRole("button", { name: "Review scalar + wiring copy" })
    .click();
  await expect(
    panel(page).getByRole("button", { name: "Save combined CAF copy" }),
  ).toBeEnabled();
  await editScalar(page, "Block 10", "3113", "13");
  await editScalar(page, "Block 10", "3113", "12.5000");
  await showCombined(page, "rewire", false);
  await expect(
    panel(page).getByRole("button", { name: "Save combined CAF copy" }),
  ).toHaveCount(0);
  await expect(
    page.getByLabel("Native replacement source", { exact: true }),
  ).toHaveValue("8-1/575_1.2_11");
});

test("altered artifact is rejected without download or saved markers", async ({
  page,
}) => {
  await openCombined(page);
  await panel(page)
    .getByRole("button", { name: "Review scalar + wiring copy" })
    .click();
  await expect(
    panel(page).getByRole("button", { name: "Save combined CAF copy" }),
  ).toBeEnabled();
  await page.route("**/combined-copy/export", async (route) => {
    const response = await route.fetch();
    await route.fulfill({ response, body: Buffer.from("altered") });
  });
  let downloads = 0;
  page.on("download", () => downloads++);
  await panel(page)
    .getByRole("button", { name: "Save combined CAF copy" })
    .click();
  await expect(panel(page).getByRole("alert")).toContainText("bytes or proof");
  expect(downloads).toBe(0);
  await expect(
    panel(page).getByRole("button", { name: "Open CAF copy" }),
  ).toHaveCount(0);
});

test("both wiring candidates require an explicit included operation", async ({
  page,
}) => {
  await openCombined(page, "both");
  await expect(
    panel(page).getByRole("button", { name: "Review scalar + wiring copy" }),
  ).toBeDisabled();
  await panel(page)
    .getByLabel("Combined wiring operation")
    .selectOption("rewire");
  await panel(page)
    .getByRole("button", { name: "Review scalar + wiring copy" })
    .click();
  await expect(
    panel(page).getByRole("button", { name: "Save combined CAF copy" }),
  ).toBeEnabled();
  await expect(panel(page)).toContainText(
    "other wiring proposal remains excluded and retained",
  );
  const downloaded = page.waitForEvent("download");
  await panel(page)
    .getByRole("button", { name: "Save combined CAF copy" })
    .click();
  await downloaded;
  await expect(
    page.getByLabel("Native new connection destination", { exact: true }),
  ).toHaveValue("8-1/575_1.2_13");
  page.once("dialog", (dialog) => dialog.dismiss());
  await panel(page).getByRole("button", { name: "Open CAF copy" }).click();
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("combined-example.caf");
});
