import { test, expect } from "./nativeScheduleWriteFixture";
import { python } from "./native-connection-fixture";
import { chooseWorkspaceTask } from "./workspace-navigation";
import { readFileSync } from "node:fs";
function seed(directory: string) {
  return JSON.parse(
    python(
      `
from pathlib import Path
import json,sys
from bms_tool.app import create_app
from bms_tool.hardware_survey import analyze_archive
from tests.test_hardware_survey import authored_archive,survey_from_archive
p=Path(sys.argv[1]);app=create_app(p);raw=authored_archive(root_input_ref=True)
a=app.state.hardware_workbench.import_archive(raw,'ambiguous.moi')
r=survey_from_archive(a);r['modules']=a['modules'];r['inventory']={'complete':True,'total':3,'read':3,'objects':['device,123','binary-input,55','analog-input,56']};r['target']={'address':'127.0.0.1:47809','device':'device,123','router':None,'dnet':None}
saved=app.state.hardware_workbench.save_report(r,origin='uploaded-report')
print(json.dumps({'archive':a['id'],'report':saved['id']}))
`,
      directory,
    ),
  );
}
for (const caf of [false, true])
  for (const width of [1440, 390])
    test(`${caf ? "CAF" : "graph"} ${width}px ambiguous host evidence stays unverified in the existing survey`, async ({
      page,
      request,
      nativeScheduleWriteServer,
    }, info) => {
      const f = seed(nativeScheduleWriteServer.directory),
        calls: string[] = [];
      await page.setViewportSize({ width, height: 1000 });
      page.on("request", (r) => {
        if (
          r.method() === "POST" &&
          new URL(r.url()).pathname.startsWith("/api/bacnet/")
        )
          calls.push(new URL(r.url()).pathname);
      });
      await page.goto("/");
      if (caf) {
        const buffer = Buffer.from(
          python(
            "from tests.test_caf_graph import make_graph; import base64; print(base64.b64encode(make_graph()).decode())",
          ),
          "base64",
        );
        await page
          .getByLabel("Open local CAF application", { exact: true })
          .setInputFiles({
            name: "host-evidence.caf",
            mimeType: "application/octet-stream",
            buffer,
          });
      } else
        await page
          .getByRole("button", { name: "New application", exact: true })
          .click();
      await chooseWorkspaceTask(page, "Points & I/O");
      const tools = page.getByRole("navigation", {
          name: "Controller task tools",
          exact: true,
        }),
        select = tools.getByRole("combobox");
      await expect(tools).toBeVisible();
      if (await select.isVisible())
        await select.selectOption({ label: "Hardware survey" });
      else
        await tools
          .getByRole("button", { name: "Hardware survey", exact: true })
          .click();
      const panel = page.getByRole("region", {
        name: "Controller hardware and input survey",
        exact: true,
      });
      await expect(
        panel.getByRole("button", {
          name: "Survey controller inputs",
          exact: true,
        }),
      ).toBeDisabled();
      await panel
        .getByLabel("Saved hardware report", { exact: true })
        .selectOption(f.report);
      await panel
        .getByRole("button", {
          name: "Open saved hardware report",
          exact: true,
        })
        .click();
      const results = panel.getByRole("region", {
          name: "Hardware survey results",
          exact: true,
        }),
        unknown = results.getByRole("region", {
          name: "Unknown host input assignments",
          exact: true,
        });
      await expect(unknown).toContainText("analog-input,56");
      await expect(unknown).toContainText("does not establish a local host");
      const candidates = results.getByRole("region", {
        name: "Candidate spare input terminals",
        exact: true,
      });
      await expect(candidates).toContainText("unverified");
      expect(await candidates.locator("tbody tr").count()).toBeGreaterThan(0);
      expect(
        (await candidates.locator("tbody tr").allTextContents()).every((t) =>
          t.includes("unverified"),
        ),
      ).toBe(true);
      const pending = page.waitForEvent("download");
      await results
        .getByRole("button", { name: "Download hardware JSON", exact: true })
        .click();
      const direct = await request.get(
        "/api/bacnet/hardware/reports/" + f.report + "/export?format=json",
      );
      expect(readFileSync((await (await pending).path())!)).toEqual(
        await direct.body(),
      );
      await panel
        .getByLabel("Configured hardware archive", { exact: true })
        .selectOption(f.archive);
      await panel
        .getByRole("button", {
          name: "Correlate archive with input survey",
          exact: true,
        })
        .click();
      await expect(results).toContainText("incomplete");
      await expect(
        results.getByRole("region", {
          name: "Unknown host input assignments",
          exact: true,
        }),
      ).toContainText("analog-input,56");
      expect(calls.every((p) => p === "/api/bacnet/hardware/enrich")).toBe(
        true,
      );
      expect(
        (await (await request.get("/api/session")).json()).field_network_open,
      ).toBe(false);
      const inputTable = unknown.locator(".hardware-table");
      if (width === 390)
        await info.attach("compact-layout.json", {
          contentType: "application/json",
          body: JSON.stringify(
            await inputTable.evaluate((n) => {
              const row = (e: Element) => {
                const r = e.getBoundingClientRect(),
                  s = getComputedStyle(e);
                return {
                  tag: e.tagName,
                  cls: e.className,
                  x: r.x,
                  right: r.right,
                  width: r.width,
                  min: s.minWidth,
                  grid: s.gridTemplateColumns,
                  overflow: s.overflowX,
                };
              };
              const chain = [];
              for (let e: Element | null = n; e; e = e.parentElement)
                chain.push(row(e));
              return {
                viewport: innerWidth,
                scroll: document.documentElement.scrollWidth,
                chain,
                overflow: Array.from(document.querySelectorAll("*"))
                  .filter((e) => {
                    const r = e.getBoundingClientRect();
                    return (
                      r.width > 0 &&
                      r.right > innerWidth + 2 &&
                      getComputedStyle(e).display !== "none"
                    );
                  })
                  .map(row)
                  .slice(0, 40),
              };
            }),
            null,
            2,
          ),
        });

      expect(
        await inputTable.evaluate(
          (n) =>
            n.getBoundingClientRect().right <= innerWidth &&
            document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      if (width === 390) {
        expect(
          await inputTable.evaluate((n) => n.scrollWidth > n.clientWidth),
        ).toBe(true);
        await inputTable.evaluate((n) => {
          n.scrollLeft = n.scrollWidth;
        });
        expect(
          await unknown
            .locator("td:last-child")
            .evaluate((n) => n.getBoundingClientRect().right <= innerWidth),
        ).toBe(true);
        await inputTable.evaluate((n) => {
          n.scrollLeft = 0;
        });
      }
      await unknown.scrollIntoViewIfNeeded();
      await page.screenshot({
        path: info.outputPath(`host-evidence-${width}.png`),
        fullPage: true,
      });
      if (caf) {
        await chooseWorkspaceTask(page, "Program");
        await expect(
          page.getByLabel("Working context", { exact: true }),
        ).toContainText("host-evidence.caf");
      }
    });
