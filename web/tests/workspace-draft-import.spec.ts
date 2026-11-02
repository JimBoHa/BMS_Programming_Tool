import { test, expect, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { freePort, peer } from "./workflow-peer";
import { chooseWorkspaceTask } from "./workspace-navigation";

const root = path.resolve("..");
async function tool(page: Page, label: string) {
  const navigation = page.getByRole("navigation", {
    name: "Controller task tools",
    exact: true,
  });
  await expect(navigation).toBeVisible();
  const select = navigation.getByRole("combobox");
  if (await select.isVisible()) await select.selectOption({ label });
  else
    await navigation.getByRole("button", { name: label, exact: true }).click();
}

for (const caf of [false, true])
  for (const compact of [false, true])
    test(`imported enum draft retains provenance through task navigation from ${caf ? "CAF" : "Connect"} entry on ${compact ? "compact" : "desktop"} layout`, async ({
      page,
      request,
    }) => {
      const token = (await (await request.get("/api/session")).json()).token;
      const headers = { "X-Studio-Token": token };
      await request.post("/api/bacnet/disconnect", { headers, data: {} });
      if (compact) await page.setViewportSize({ width: 600, height: 1000 });
      const router = await peer();
      try {
        await page.goto("/");
        if (caf) {
          const choosing = page.waitForEvent("filechooser");
          await page.getByRole("button", { name: /^Open a CAF file/ }).click();
          await (
            await choosing
          ).setFiles({
            name: "draft-reference.caf",
            mimeType: "application/octet-stream",
            buffer: execFileSync(
              path.join(root, ".venv/bin/python"),
              [
                "-c",
                "from tests.test_caf_graph import make_graph; import sys; sys.stdout.buffer.write(make_graph())",
              ],
              { cwd: root },
            ),
          });
          await expect(
            page.getByLabel("Current CAF archive", { exact: true }),
          ).toHaveText("draft-reference.caf");
          expect(
            (await (await request.get("/api/session")).json())
              .field_network_open,
          ).toBe(false);
          await page
            .getByLabel("Working context", { exact: true })
            .getByRole("button", { name: "Connect", exact: true })
            .click();
        } else
          await page
            .getByRole("button", { name: /^Connect to a controller/ })
            .click();
        await page
          .getByLabel("Local bind address / UDP port", { exact: true })
          .fill(`127.0.0.1:${await freePort()}`);
        await page
          .getByRole("button", { name: "Open interface", exact: true })
          .click();
        await page
          .getByRole("button", {
            name: "Known controller address",
            exact: true,
          })
          .click();
        await page
          .getByLabel("Known controller address", { exact: true })
          .fill("3001:8");
        await page
          .getByLabel("Known Device object", { exact: true })
          .fill("device,5136");
        await page
          .getByLabel("Known router", { exact: true })
          .fill(router.endpoint);
        await page.getByLabel("Known network", { exact: true }).fill("3001");
        await page
          .getByRole("region", {
            name: "Known controller connection",
            exact: true,
          })
          .getByRole("button", { name: "Open controller", exact: true })
          .click();
        await expect(
          page.getByRole("region", {
            name: "Controller overview",
            exact: true,
          }),
        ).toContainText("Authored 3001 MAC 8");
        await chooseWorkspaceTask(page, "Points & I/O");
        await tool(page, "State mapping");
        const panel = page.getByRole("region", {
          name: "Operator enum mapping review",
          exact: true,
        });
        await panel
          .getByRole("button", {
            name: "Load operator mapping example",
            exact: true,
          })
          .click();
        await panel
          .getByRole("button", { name: "Review enum mapping", exact: true })
          .click();
        await expect(
          panel.getByLabel("Enum mapping review result", { exact: true }),
        ).toContainText("valid_declared_mapping");
        const downloading = page.waitForEvent("download");
        await panel
          .getByRole("button", {
            name: "Export reviewed enum plan",
            exact: true,
          })
          .click();
        const source = (await (await downloading).path())!;
        await panel
          .getByRole("button", { name: "Clear enum declaration", exact: true })
          .click();
        await panel
          .getByLabel("Import enum plan", { exact: true })
          .setInputFiles(source);
        const provenance = panel.getByText(/^Imported operator plan /);
        await expect(provenance).toContainText(
          "Review required; no native binding.",
        );
        const originalProvenance = await provenance.textContent();
        const sourceId = await panel
          .getByLabel("Source enum domain ID", { exact: true })
          .inputValue();
        await panel
          .getByRole("button", { name: "Review enum mapping", exact: true })
          .click();
        await expect(
          panel.getByLabel("Enum mapping review result", { exact: true }),
        ).toBeVisible();
        await chooseWorkspaceTask(page, "Overview");
        await chooseWorkspaceTask(page, "Points & I/O");
        await tool(page, "State mapping");
        await expect(provenance).toHaveText(originalProvenance!);
        await expect(
          panel.getByLabel("Source enum domain ID", { exact: true }),
        ).toHaveValue(sourceId);
        await expect(
          panel.getByLabel("Enum mapping review result", { exact: true }),
        ).toHaveCount(0);
        await expect(
          panel.getByRole("button", {
            name: "Export exact enum review",
            exact: true,
          }),
        ).toBeDisabled();
        await panel
          .getByLabel("Source enum domain ID", { exact: true })
          .fill("new-local-declaration");
        await expect(provenance).toHaveCount(0);
        await tool(page, "Read properties");
        await tool(page, "State mapping");
        await expect(
          panel.getByLabel("Source enum domain ID", { exact: true }),
        ).toHaveValue("new-local-declaration");
        await expect(provenance).toHaveCount(0);
        expect(router.writes).toEqual([]);
        expect(router.errors).toEqual([]);
      } finally {
        try {
          await request.post("/api/bacnet/disconnect", { headers, data: {} });
        } finally {
          router.close();
        }
      }
    });
