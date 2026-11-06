import { test, expect } from "./nativeScheduleWriteFixture";
import { nativeDefaultPeer } from "./native-default-peer";
import { freePort } from "./workflow-peer";
import { source, inspect } from "./caf-enum-selector-multiplexer-fixture";
import { logic } from "./caf-constant-fixture";
import { savedCopy, families, inspectFamily } from "./caf-open-copy-fixture";

for (const kind of ["float", "short", "interface-retired"])
  test(`controller entry retains the routed target while ${kind} proven CAF copy reopening stays local`, async ({
    page,
  }, info) => {
    const peer = await nativeDefaultPeer(),
      profiles: Promise<{
        status: number | undefined;
        finished: Error | null | undefined;
      }>[] = [];
    page.on("request", (request) => {
      if (request.url().endsWith("/api/bacnet/controller/profile"))
        profiles.push(
          request.response().then(async (response) => ({
            status: response?.status(),
            finished: await response?.finished(),
          })),
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
      // Claim the existing focused-draft guard before fill selects/replaces text;
      // an initial computer-network suggestion may otherwise race that action.
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
        name: "enum-selector.caf",
        mimeType: "application/octet-stream",
        buffer: source(kind),
      });
      await expect(
        page.getByLabel("Current CAF archive", { exact: true }),
      ).toHaveText("enum-selector.caf");
      await page.getByRole("button", { name: "Edit", exact: true }).click();
      await logic(page);
      const editor = await inspect(page);
      expect(profiles.length).toBeGreaterThan(0);
      for (const response of await Promise.all(profiles)) {
        expect(response.status).toBe(200);
        expect(response.finished).toBeNull();
      }
      const before = await peer.command("stats");
      const proof = await savedCopy(page, families[11], editor);
      let release!: () => void, started!: () => void;
      const held = new Promise<void>((r) => (release = r)),
        entered = new Promise<void>((r) => (started = r));
      if (kind === "interface-retired")
        await page.route("**/api/caf", async (route) => {
          if (route.request().method() === "POST") {
            started();
            await held;
          }
          await route.continue();
        });
      const returned = page.waitForResponse(
        (r) =>
          new URL(r.url()).pathname === "/api/caf" &&
          r.request().method() === "POST",
      );
      await editor
        .getByRole("button", { name: "Open CAF copy", exact: true })
        .click();
      if (kind === "interface-retired") {
        await entered;
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
        const response = await returned;
        expect(response.status()).toBe(200);
        expect(await response.finished()).toBeNull();
        await page.unroute("**/api/caf");
        await expect(
          page.getByLabel("Current CAF archive", { exact: true }),
        ).toHaveText("enum-selector.caf");
        const original = await inspectFamily(page, families[11]);
        await expect(
          original.getByRole("button", { name: "Open CAF copy", exact: true }),
        ).toHaveCount(0);
      } else {
        const response = await returned;
        expect(response.status()).toBe(200);
        expect(await response.finished()).toBeNull();
        await expect(
          page.getByLabel("Current CAF archive", { exact: true }),
        ).toHaveText("enum-selector-float-multiplexer-copy.caf");
        const reopened = await inspectFamily(page, families[11]);
        await expect(
          reopened.getByLabel("Block prototype", { exact: true }),
        ).toHaveValue(proof.creation.selection.new_ref);
      }
      const after = await peer.command("stats");
      await info.attach("local CAF reopening peer evidence", {
        body: Buffer.from(JSON.stringify({ before, after })),
        contentType: "application/json",
      });
      expect(after.request_types).toEqual(before.request_types);
      expect(after.events).toEqual(before.events);
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
