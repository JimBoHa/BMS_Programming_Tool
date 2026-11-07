import { test, expect } from "./nativeScheduleWriteFixture";
import { nativeDefaultPeer } from "./native-default-peer";
import { openOrderTransfer } from "./native-order-transfer-browser-fixture";
import { inspect, analyze } from "./native-connection-capability-fixture";

test("routed controller order analysis uses retained files without querying the open interface", async ({
  page,
}) => {
  const peer = await nativeDefaultPeer("consume", "execution-order");
  try {
    const { compiler } = await openOrderTransfer(page, peer.router, true);
    const support = await inspect(compiler);
    await analyze(support);
    const before = await peer.command("stats");
    await support
      .getByLabel("Include native execution-order support", { exact: true })
      .check();
    const table = support.getByRole("table", {
      name: "Native backup operations",
      exact: true,
    });
    await expect(table.getByRole("row")).toHaveCount(30);
    await expect(
      table.locator(
        '[data-operation="execution-order-transfer-prerequisites"]',
      ),
    ).toContainText("preflight required");
    const after = await peer.command("stats");
    expect(after.events).toEqual(before.events);
    expect(after.request_types).toEqual(before.request_types);
    expect(after.router_errors).toEqual([]);
    await expect(
      page.getByLabel("Working context", { exact: true }),
    ).toContainText("Authored native wire controller");
  } finally {
    peer.close();
  }
});
