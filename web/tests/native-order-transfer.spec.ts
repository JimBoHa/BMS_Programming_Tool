import { test, expect } from "./nativeScheduleWriteFixture";
import { nativeDefaultPeer } from "./native-default-peer";
import {
  chooseWorkspaceTask,
  expectWorkspaceNavigationLocked,
} from "./workspace-navigation";
import { openOrderTransfer as open } from "./native-order-transfer-browser-fixture";

for (const routed of [false, true]) {
  test(`${routed ? "routed" : "direct"} execution-order uses the selected target and verifies fresh settings`, async ({
    page,
  }) => {
    const peer = await nativeDefaultPeer("consume", "execution-order");
    try {
      const { editor, transfer } = await open(
        page,
        routed ? peer.router : peer.direct,
        routed,
      );
      await expect(transfer).toContainText(
        routed
          ? `device,5136 · 3001:7 via ${peer.router}`
          : `device,5136 · ${peer.direct}`,
      );
      await expect(editor.locator("button.primary:visible")).toHaveCount(1);
      await transfer
        .getByRole("button", {
          name: "Review execution-order transfer",
          exact: true,
        })
        .click();
      await expect(
        transfer.getByRole("region", {
          name: "Reviewed controller execution order",
          exact: true,
        }),
      ).toBeVisible();
      await expect(
        transfer.getByRole("button", {
          name: "Apply execution order to controller",
          exact: true,
        }),
      ).toBeDisabled();
      await transfer
        .getByRole("checkbox", {
          name: "I confirm this execution order and the retained wire timing relationships.",
          exact: true,
        })
        .check();
      await transfer
        .getByRole("checkbox", {
          name: "I confirm the application transfer and possible control interruption.",
          exact: true,
        })
        .check();
      await peer.command("wire-other-fresh");
      let receipt: any;
      await page.route("**/execution-order/transfer/apply", async (route) => {
        const response = await route.fetch({ maxRetries: 0 }),
          bytes = await response.body();
        receipt = JSON.parse(bytes.toString());
        await route.fulfill({ response, body: bytes });
      });
      await transfer
        .getByRole("button", {
          name: "Apply execution order to controller",
          exact: true,
        })
        .click();
      await expectWorkspaceNavigationLocked(page);
      await expect(
        transfer.getByRole("region", {
          name: "Execution-order transfer result",
          exact: true,
        }),
      ).toContainText(
        "Execution order verified in the complete native readback.",
        {
          timeout: 20000,
        },
      );
      const actual = await peer.command("stats");
      expect(actual.connections).toHaveLength(2);
      expect(actual.execution_order).toEqual([1, 0, 2, 3]);
      expect(actual.source_default).toBe(45);
      expect(actual.other_default).toBe(17);
      expect(
        actual.events.filter(
          (row: any[]) => row[0] === "state" && row[1] === "start-restore",
        ),
      ).toHaveLength(1);
      expect(actual.router_errors).toEqual([]);
      await expect(editor.locator("button.primary:visible")).toHaveCount(1);
      await expect(
        transfer.getByRole("button", {
          name: "Open verified application snapshot",
          exact: true,
        }),
      ).toBeEnabled();
      const beforeHistory = await peer.command("stats");
      await chooseWorkspaceTask(page, "Changes");
      await page
        .getByLabel("Record family", { exact: true })
        .selectOption("native");
      await page
        .getByRole("button", {
          name: "Details for native " + receipt.intent.id,
          exact: true,
        })
        .click();
      const evidence = page.getByRole("region", {
        name: "Change evidence",
        exact: true,
      });
      await expect(evidence).toContainText("Native execution-order transfer");
      await expect(evidence).toContainText("controller/575_1");
      await evidence
        .getByRole("button", { name: "Open native program tools", exact: true })
        .click();
      await expect(
        page.getByRole("region", {
          name: "Native backup default compiler",
          exact: true,
        }),
      ).toBeVisible();
      expect((await peer.command("stats")).events).toEqual(
        beforeHistory.events,
      );
    } finally {
      peer.close();
    }
  });
}
