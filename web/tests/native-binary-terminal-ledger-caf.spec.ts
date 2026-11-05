import { seedBinaryLedger } from "./native-binary-terminal-ledger-fixture";
import { test, expect } from "./nativeScheduleWriteFixture";
import { python } from "./native-connection-fixture";
import { openTerminalEvidence } from "./native-terminal-ledger-fixture";
import {
  chooseWorkspaceSurface,
  chooseWorkspaceTask,
} from "./workspace-navigation";

for (const history of [false, true]) {
  test(`CAF ${history ? "History" : "Changes"} retains its file while opening recorded binary terminal tools`, async ({
    page,
    request,
    nativeScheduleWriteServer,
  }) => {
    const f = seedBinaryLedger(nativeScheduleWriteServer.directory),
      buffer = Buffer.from(
        python(
          "from tests.test_caf_graph import make_graph; import base64; print(base64.b64encode(make_graph()).decode())",
        ),
        "base64",
      );
    await page.setViewportSize({ width: history ? 390 : 1440, height: 1000 });
    await page.goto("/");
    await page
      .getByLabel("Open local CAF application", { exact: true })
      .setInputFiles({
        name: "binary-terminal-ledger.caf",
        mimeType: "application/octet-stream",
        buffer,
      });
    await expect(
      page.getByLabel("Working context", { exact: true }),
    ).toContainText("binary-terminal-ledger.caf");
    if (history) {
      await chooseWorkspaceSurface(page, "History");
      const tools = page.getByRole("navigation", {
          name: "history tools",
          exact: true,
        }),
        select = tools.getByRole("combobox");
      if (await select.isVisible())
        await select.selectOption({ label: "Recorded changes" });
      else
        await tools
          .getByRole("button", { name: "Recorded changes", exact: true })
          .click();
    } else await chooseWorkspaceTask(page, "Changes");
    await page
      .getByLabel("Record family", { exact: true })
      .selectOption("native");
    const evidence = await openTerminalEvidence(page, f.id);
    await expect(
      evidence.getByRole("region", {
        name: "Recorded binary terminal movement",
        exact: true,
      }),
    ).toContainText("UI IN1");
    await evidence
      .getByRole("button", { name: "Open input tools", exact: true })
      .click();
    await expect(
      page.getByRole("region", {
        name: "Native input configuration",
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      page.getByLabel("Working context", { exact: true }),
    ).toContainText("binary-terminal-ledger.caf");
    expect(
      (await (await request.get("/api/session")).json()).field_network_open,
    ).toBe(false);
  });
}
