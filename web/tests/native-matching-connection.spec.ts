import { test, expect } from "@playwright/test";
import { nativeDefaultPeer } from "./native-default-peer";
import { expectWorkspaceNavigationLocked } from "./workspace-navigation";
import { d } from "./native-connection-fixture";
import { openMatchingConnection as open } from "./native-matching-connection-browser-fixture";

for (const routed of [false, true]) {
  test(`${routed ? "routed" : "direct"} matching connection uses the selected target and verifies fresh settings`, async ({
    page,
  }) => {
    const peer = await nativeDefaultPeer("consume", "connection");
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
          name: "Review matching connection transfer",
          exact: true,
        })
        .click();
      await expect(
        transfer.getByRole("region", {
          name: "Reviewed controller connection",
          exact: true,
        }),
      ).toBeVisible();
      await expect(
        transfer.getByRole("button", {
          name: "Apply matching connection to controller",
          exact: true,
        }),
      ).toBeDisabled();
      await transfer
        .getByRole("checkbox", {
          name: "I confirm this existing-member connection and unused input.",
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
      await transfer
        .getByRole("button", {
          name: "Apply matching connection to controller",
          exact: true,
        })
        .click();
      await expectWorkspaceNavigationLocked(page);
      await expect(
        transfer.getByRole("region", {
          name: "Matching connection transfer result",
          exact: true,
        }),
      ).toContainText("Connection verified in the complete native readback.", {
        timeout: 20000,
      });
      const actual = await peer.command("stats");
      expect(actual.connections).toHaveLength(2);
      expect(actual.connections[1].target_ref).toBe(d);
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
    } finally {
      peer.close();
    }
  });
}
