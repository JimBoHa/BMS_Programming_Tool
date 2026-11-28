import { expect, test } from "@playwright/test";
import {
  disconnectPointInterface,
  openPointInspection,
  readPointStatus,
  startPointPeer,
} from "./point-status-workspace";

test.afterEach(async ({ request }) => disconnectPointInterface(request));

test("compare two identified command arrays from Points & I/O without another field request", async ({
  page,
}) => {
  const peer = await startPointPeer(true, "slot-change");
  try {
    const panel = await openPointInspection(page, peer, true);
    await panel
      .getByLabel("Read optional priority slots and relinquish defaults")
      .check();
    await readPointStatus(panel);
    await panel.getByText("Compare command slots", { exact: true }).click();
    await expect(panel.getByRole("status")).toContainText(
      "No earlier complete command slots",
    );
    const fresh = page.waitForResponse((r) =>
      r.url().endsWith("/point-status/read"),
    );
    await readPointStatus(panel);
    await fresh;
    await panel.getByText("Compare command slots", { exact: true }).click();
    const compare = panel.getByRole("region", {
      name: "Compare retained command slots",
    });
    const action = compare.getByRole("button", {
      name: "Compare retained readings",
    });
    await expect(action).toBeEnabled();
    const requests = peer.reads();
    await action.focus();
    await page.keyboard.press("Enter");
    await expect(compare.getByRole("status")).toHaveText(
      "2 of 16 command slots changed.",
    );
    const table = compare.getByRole("table");
    await expect(table.getByRole("row")).toHaveCount(3);
    await expect(table.getByRole("row").nth(1).getByRole("cell")).toHaveText([
      "Filled",
      "Empty",
      "real 0.0",
    ]);
    await expect(
      table.getByRole("row").nth(2).getByRole("rowheader"),
    ).toHaveText("15");
    await expect(table.getByRole("row").nth(2).getByRole("cell")).toHaveText([
      "Cleared",
      "real 12.5",
      "Empty",
    ]);
    expect(peer.reads()).toBe(requests);
    let release!: () => void;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    let received!: () => void;
    const responseReceived = new Promise<void>((resolve) => {
      received = resolve;
    });
    await page.route(
      "**/api/bacnet/point-status/compare-command-slots",
      async (route) => {
        const response = await route.fetch();
        received();
        await held;
        await route.fulfill({ response });
      },
    );
    await action.click();
    await responseReceived;
    await panel.getByText("Compare command slots", { exact: true }).click();
    release();
    await panel.getByText("Compare command slots", { exact: true }).click();
    await expect(action).toBeEnabled();
    await expect(compare.getByRole("table")).toHaveCount(0);
    expect(peer.reads()).toBe(requests);
  } finally {
    await peer.stop();
  }
});
