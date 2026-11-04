import { test, expect } from "./nativeScheduleWriteFixture";
import { nativeDefaultPeer } from "./native-default-peer";
import { freePort } from "./workflow-peer";
import { source, inspect } from "./caf-enum-selector-multiplexer-fixture";
import { logic } from "./caf-constant-fixture";
import { prepare } from "./caf-enum-selector-multiplexer-fixture";

for (const kind of ["float", "short"])
  test(`controller entry retains the routed target while ${kind} Enum-selector Float Multiplexer creation and export stay local`, async ({
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
      await page
        .getByLabel("Local bind address / UDP port", { exact: true })
        .fill(`127.0.0.1:${await freePort()}`);
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
      await prepare(page);
      const downloading = page.waitForEvent("download");
      await editor
        .getByRole("button", { name: "Save block CAF copy", exact: true })
        .click();
      await downloading;
      const after = await peer.command("stats");
      await info.attach(
        "local Enum-selector Float Multiplexer copy peer evidence",
        {
          body: Buffer.from(JSON.stringify({ before, after })),
          contentType: "application/json",
        },
      );
      expect(after.request_types).toEqual(before.request_types);
      expect(after.events).toEqual(before.events);
      await expect(
        page.getByLabel("Selected controller path", { exact: true }),
      ).toContainText("3001:7");
      await expect(editor.getByRole("status")).toContainText(
        "No controller write was sent",
      );
    } finally {
      peer.close();
    }
  });
