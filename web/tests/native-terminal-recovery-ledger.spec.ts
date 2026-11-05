import { test, expect } from "./nativeScheduleWriteFixture";
import { readFileSync } from "node:fs";
import {
  seed,
  openTerminalLedger,
  openTerminalEvidence,
} from "./native-terminal-recovery-ledger-fixture";
import { python } from "./native-connection-fixture";
import { chooseWorkspaceTask } from "./workspace-navigation";

for (const history of [false, true])
  for (const width of [1440, 390])
    test(`${history ? "History" : "Changes"} displays recorded inverse lineage and local parent search at ${width}px`, async ({
      page,
      request,
      nativeScheduleWriteServer,
    }, info) => {
      const f = seed(nativeScheduleWriteServer.directory),
        field: string[] = [];
      await page.setViewportSize({ width, height: 1000 });
      page.on("request", (r) => {
        if (
          r.method() === "POST" &&
          new URL(r.url()).pathname.startsWith("/api/bacnet/")
        )
          field.push(r.url());
      });
      await openTerminalLedger(page, history);
      const evidence = await openTerminalEvidence(page, f.id),
        lineage = evidence.getByRole("region", {
          name: "Recorded terminal recovery lineage",
          exact: true,
        });
      await expect(lineage).toContainText(f.parent);
      await expect(lineage).toContainText("UI IN3 to UI IN1");
      await expect(lineage).toContainText("No parent/source lookup");
      await expect(
        lineage.getByRole("button", {
          name: "Apply to controller",
          exact: true,
        }),
      ).toHaveCount(0);
      await expect(evidence).not.toContainText("Recovery metadata unavailable");
      const download = page.waitForEvent("download");
      await evidence
        .getByRole("button", { name: "Download evidence JSON", exact: true })
        .click();
      const bytes = readFileSync((await (await download).path())!);
      expect(bytes).toEqual(
        await (
          await request.get(
            "/api/bacnet/controller/native-application/receipts/" + f.id,
          )
        ).body(),
      );
      await lineage.scrollIntoViewIfNeeded();
      await page.screenshot({
        path: info.outputPath("terminal-recovery-ledger.png"),
      });
      await lineage
        .getByRole("button", {
          name: "Search recorded terminal parent receipt",
          exact: true,
        })
        .click();
      await expect(
        page.getByRole("button", {
          name: "Details for native " + f.parent,
          exact: true,
        }),
      ).toBeVisible();
      expect(field).toEqual([]);
      expect(
        (await (await request.get("/api/session")).json()).field_network_open,
      ).toBe(false);
    });

test("unsupported recorded lineage retains original evidence without a parent link", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seed(nativeScheduleWriteServer.directory);
  await openTerminalLedger(page);
  const evidence = await openTerminalEvidence(page, f.invalid),
    lineage = evidence.getByRole("region", {
      name: "Recorded terminal recovery lineage",
      exact: true,
    });
  await expect(lineage).toContainText("metadata unavailable");
  await expect(
    lineage.getByRole("button", {
      name: "Search recorded terminal parent receipt",
      exact: true,
    }),
  ).toHaveCount(0);
  await expect(
    evidence.getByRole("button", {
      name: "Download evidence JSON",
      exact: true,
    }),
  ).toBeEnabled();
});

test("substituted metadata cannot grant recorded parent search", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seed(nativeScheduleWriteServer.directory);
  await page.route("**/api/changes/query", async (route) => {
    const response = await route.fetch(),
      v = await response.json();
    for (const r of v.rows ?? [])
      if (r.id === f.id) r.native_terminal_recovery.transfer_authority = true;
    await route.fulfill({ response, json: v });
  });
  await openTerminalLedger(page);
  const evidence = await openTerminalEvidence(page, f.id);
  const lineage = evidence.getByRole("region", {
    name: "Recorded terminal recovery lineage",
    exact: true,
  });
  await expect(lineage).toContainText("metadata unavailable");
  await expect(
    lineage.getByRole("button", {
      name: "Search recorded terminal parent receipt",
      exact: true,
    }),
  ).toHaveCount(0);
});

test("CAF context remains separate while inspecting inverse lineage", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seed(nativeScheduleWriteServer.directory);
  await page.goto("/");
  await page
    .getByLabel("Open local CAF application", { exact: true })
    .setInputFiles({
      name: "recorded-inverse.caf",
      mimeType: "application/octet-stream",
      buffer: Buffer.from(
        python(
          "from tests.test_caf_graph import make_graph;import base64;print(base64.b64encode(make_graph()).decode())",
        ),
        "base64",
      ),
    });
  await expect(
    page.getByLabel("Working context", { exact: true }),
  ).toContainText("recorded-inverse.caf");
  await chooseWorkspaceTask(page, "Changes");
  await page
    .getByLabel("Record family", { exact: true })
    .selectOption("native");
  const evidence = await openTerminalEvidence(page, f.id);
  await expect(
    evidence.getByRole("region", {
      name: "Recorded terminal recovery lineage",
      exact: true,
    }),
  ).toContainText(f.parent);
  await expect(
    page.getByLabel("Working context", { exact: true }),
  ).toContainText("recorded-inverse.caf");
});
