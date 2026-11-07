import { test, expect } from "./nativeScheduleWriteFixture";
import { nativeDefaultPeer } from "./native-default-peer";
import { freePort } from "./workflow-peer";
import { openNativeCompiler } from "./workspace-navigation";
import {
  orderFixture,
  openOrder,
  stageOrder,
  reviewOrder,
  nativeOrderPanel,
  nativeOrderReview,
} from "./native-execution-order-fixture";

for (const closeInterface of [false, true])
  test(`routed controller context keeps native order compilation local${closeInterface ? " and retires it on close" : ""}`, async ({
    page,
    nativeScheduleWriteServer,
  }, info) => {
    const f = orderFixture(nativeScheduleWriteServer.directory),
      peer = await nativeDefaultPeer(),
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
      await openNativeCompiler(page);
      const compiler = page.getByRole("region", {
        name: "Native backup default compiler",
        exact: true,
      });
      await compiler
        .getByLabel("Retained native backup", { exact: true })
        .selectOption(f.id);
      await openOrder(page, compiler);
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
        await openNativeCompiler(page);
        await openOrder(page, compiler);
        await expect(nativeOrderReview(page)).toHaveCount(0);
        await expect(nativeOrderPanel(page)).toContainText(
          "proposal has not been exported",
        );
      } else {
        const saved = page.waitForEvent("download");
        await nativeOrderReview(page)
          .getByRole("button", {
            name: "Save native execution-order copy",
            exact: true,
          })
          .click();
        await saved;
      }
      const after = await peer.command("stats");
      expect(after.request_types).toEqual(before.request_types);
      expect(after.events).toEqual(before.events);
      await info.attach("native order local-only peer evidence", {
        body: Buffer.from(JSON.stringify({ before, after })),
        contentType: "application/json",
      });
    } finally {
      peer.close();
    }
  });
