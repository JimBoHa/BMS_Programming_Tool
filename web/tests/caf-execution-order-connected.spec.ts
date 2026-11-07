import { test, expect } from "./nativeScheduleWriteFixture";
import { nativeDefaultPeer } from "./native-default-peer";
import { freePort } from "./workflow-peer";
import {
  orderFixture,
  showOrder,
  stageOrder,
  reviewOrder,
  reviewedOrder,
  orderPanel,
} from "./caf-execution-order-fixture";

for (const closeInterface of [false, true])
  test(`routed controller entry keeps execution-order copying local${closeInterface ? " and retires review on interface close" : ""}`, async ({
    page,
  }, info) => {
    const peer = await nativeDefaultPeer(),
      profiles: Promise<void>[] = [];
    page.on("request", (r) => {
      if (r.url().endsWith("/api/bacnet/controller/profile"))
        profiles.push(
          r.response().then(async (response) => {
            expect(response?.status()).toBe(200);
            expect(await response?.finished()).toBeNull();
          }),
        );
    });
    try {
      await page.goto("/");
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
        .getByRole("button", { name: "Known controller address", exact: true })
        .click();
      for (const [name, value] of [
        ["Known controller address", "3001:7"],
        ["Known Device object", "device,5136"],
        ["Known router", peer.router],
        ["Known network", "3001"],
      ])
        await page.getByLabel(name, { exact: true }).fill(value);
      await page
        .getByRole("region", {
          name: "Known controller connection",
          exact: true,
        })
        .getByRole("button", { name: "Open controller", exact: true })
        .click();
      await expect(
        page.getByRole("region", { name: "Controller overview", exact: true }),
      ).toContainText("Authored controller");
      const chosen = page.waitForEvent("filechooser");
      await page.getByRole("button", { name: "Open CAF", exact: true }).click();
      await (
        await chosen
      ).setFiles({
        name: "authored-routed-order.caf",
        mimeType: "application/octet-stream",
        buffer: Buffer.from(orderFixture().caf, "base64"),
      });
      await expect(
        page.getByLabel("Current CAF archive", { exact: true }),
      ).toHaveText("authored-routed-order.caf");
      await page.getByRole("button", { name: "Edit", exact: true }).click();
      await showOrder(page);
      expect(profiles.length).toBeGreaterThan(0);
      await Promise.all(profiles);
      const before = await peer.command("stats");
      await stageOrder(page);
      await reviewOrder(page);
      if (closeInterface) {
        await page
          .getByLabel("Working context")
          .getByRole("button", { name: "Change controller", exact: true })
          .click();
        await page
          .getByRole("button", { name: "Close BACnet interface", exact: true })
          .click();
        await expect(page.getByLabel("Working context")).toContainText(
          "Interface closed",
        );
        await showOrder(page);
        await expect(reviewedOrder(page)).toHaveCount(0);
        await expect(orderPanel(page)).toContainText(
          "proposal has not been exported",
        );
      } else {
        const saved = page.waitForEvent("download");
        await reviewedOrder(page)
          .getByRole("button", {
            name: "Save execution-order CAF copy",
            exact: true,
          })
          .click();
        await saved;
      }
      const after = await peer.command("stats");
      expect(after.request_types).toEqual(before.request_types);
      expect(after.events).toEqual(before.events);
      await info.attach("local order copy peer evidence", {
        body: Buffer.from(JSON.stringify({ before, after })),
        contentType: "application/json",
      });
    } finally {
      peer.close();
    }
  });
