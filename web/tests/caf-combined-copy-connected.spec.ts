import { test, expect } from "./nativeScheduleWriteFixture";
import { nativeDefaultPeer } from "./native-default-peer";
import { freePort } from "./workflow-peer";
import {
  combinedFixture,
  showCombined,
  panel,
  editScalar,
  logic,
} from "./caf-combined-copy-fixture";

for (const retireInterface of [false, true])
  test(`routed controller context keeps combined CAF work local${retireInterface ? " and retires a held copy on interface close" : " through verified opening"}`, async ({
    page,
  }, info) => {
    const peer = await nativeDefaultPeer();
    const profiles: Promise<void>[] = [];
    page.on("request", (request) => {
      if (request.url().endsWith("/api/bacnet/controller/profile"))
        profiles.push(
          request.response().then(async (response) => {
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
      const bind = page.getByLabel("Local bind address / UDP port", {
          exact: true,
        }),
        address = `127.0.0.1:${await freePort()}`;
      await bind.focus();
      await expect(bind).toBeFocused();
      await bind.fill(address);
      await expect(bind).toHaveValue(address);
      await page
        .getByRole("button", { name: "Open interface", exact: true })
        .click();
      await page
        .getByRole("button", { name: "Known controller address", exact: true })
        .click();
      await page
        .getByLabel("Known controller address", { exact: true })
        .fill("3001:7");
      await page
        .getByLabel("Known Device object", { exact: true })
        .fill("device,5136");
      await page.getByLabel("Known router", { exact: true }).fill(peer.router);
      await page.getByLabel("Known network", { exact: true }).fill("3001");
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
      const choosing = page.waitForEvent("filechooser");
      await page.getByRole("button", { name: "Open CAF", exact: true }).click();
      await (
        await choosing
      ).setFiles({
        name: "routed-local.caf",
        mimeType: "application/octet-stream",
        buffer: Buffer.from(combinedFixture().caf, "base64"),
      });
      await expect(
        page.getByLabel("Current CAF archive", { exact: true }),
      ).toHaveText("routed-local.caf");
      await page.getByRole("button", { name: "Edit", exact: true }).click();
      await editScalar(page, "Block 10", "3113", "12.5000");
      await showCombined(page);
      expect(profiles.length).toBeGreaterThan(0);
      await Promise.all(profiles);
      const before = await peer.command("stats");
      await panel(page)
        .getByRole("button", {
          name: "Review scalar + wiring copy",
          exact: true,
        })
        .click();
      await expect(
        panel(page).getByRole("button", {
          name: "Save combined CAF copy",
          exact: true,
        }),
      ).toBeEnabled();
      const downloading = page.waitForEvent("download");
      await panel(page)
        .getByRole("button", { name: "Save combined CAF copy", exact: true })
        .click();
      await downloading;
      await expect(
        panel(page).getByRole("button", { name: "Open CAF copy", exact: true }),
      ).toBeEnabled();
      let release!: () => void, entered!: () => void;
      const held = new Promise<void>((r) => (release = r)),
        started = new Promise<void>((r) => (entered = r));
      if (retireInterface)
        await page.route("**/api/caf", async (route) => {
          if (route.request().method() === "POST") {
            entered();
            await held;
          }
          await route.continue();
        });
      const returned = page.waitForResponse(
        (r) =>
          new URL(r.url()).pathname === "/api/caf" &&
          r.request().method() === "POST",
      );
      await panel(page)
        .getByRole("button", { name: "Open CAF copy", exact: true })
        .click();
      if (retireInterface) {
        await started;
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
        await logic(page);
        release();
      }
      const response = await returned;
      expect(response.status()).toBe(200);
      expect(await response.finished()).toBeNull();
      await expect(
        page.getByLabel("Current CAF archive", { exact: true }),
      ).toHaveText(
        retireInterface ? "routed-local.caf" : "routed-local-combined.caf",
      );
      const after = await peer.command("stats");
      expect(after.request_types).toEqual(before.request_types);
      expect(after.events).toEqual(before.events);
      await info.attach("combined local-only peer evidence", {
        body: Buffer.from(JSON.stringify({ before, after })),
        contentType: "application/json",
      });
      await expect(
        page.getByLabel("Selected controller path", { exact: true }),
      ).toContainText("3001:7");
      await expect(page.getByLabel("Working context")).toContainText(
        "unverified",
      );
    } finally {
      peer.close();
    }
  });
