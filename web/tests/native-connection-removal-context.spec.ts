import { test, expect } from "./nativeScheduleWriteFixture";
import { seed, openRecord, prepare } from "./native-connection-removal-fixture";
import {
  chooseWorkspaceSurface,
  openNativeCompiler,
} from "./workspace-navigation";
import { nativeDefaultPeer } from "./native-default-peer";
import { freePort } from "./workflow-peer";

for (const effective of [false, true])
  test(`${effective ? "saved" : "archive"} local removal keeps exact routed controller context and retires review on route change`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const f = seed(nativeScheduleWriteServer.directory),
      peer = await nativeDefaultPeer();
    async function select(routed: boolean) {
      await page
        .getByRole("button", { name: "Known controller address", exact: true })
        .click();
      await page
        .getByLabel("Known controller address", { exact: true })
        .fill(routed ? "3001:7" : peer.direct);
      await page
        .getByLabel("Known Device object", { exact: true })
        .fill("device,5136");
      await page
        .getByLabel("Known router", { exact: true })
        .fill(routed ? peer.router : "");
      await page
        .getByLabel("Known network", { exact: true })
        .fill(routed ? "3001" : "");
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
      return openRecord(page, compiler, effective);
    }
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
      const { editor } = await select(true),
        before = await peer.command("stats");
      await editor
        .getByLabel("Existing connection to remove", { exact: true })
        .selectOption("2");
      const review = await prepare(editor),
        downloading = page.waitForEvent("download");
      await review
        .getByRole("button", {
          name: "Save native connection removal copy",
          exact: true,
        })
        .click();
      await downloading;
      const after = await peer.command("stats");
      expect(after.request_types).toEqual(before.request_types);
      expect(after.events).toEqual(before.events);
      await page
        .getByRole("button", { name: "Change controller", exact: true })
        .click();
      const changed = await select(false);
      await expect(
        changed.editor.getByLabel("Existing connection to remove", {
          exact: true,
        }),
      ).toHaveValue("2");
      await expect(
        changed.editor.getByRole("region", {
          name: "Reviewed connection removal",
          exact: true,
        }),
      ).toHaveCount(0);
      const directBefore = await peer.command("stats");
      await prepare(changed.editor);
      const directAfter = await peer.command("stats");
      expect(directAfter.events).toEqual(directBefore.events);
      expect(
        directAfter.events.filter(
          (r: any[]) => r[0] === "write" || r[0] === "state",
        ),
      ).toEqual([]);
      expect(directAfter.router_errors).toEqual([]);
      await page
        .getByRole("button", { name: "Change controller", exact: true })
        .click();
      await page
        .getByRole("button", { name: "Close BACnet interface", exact: true })
        .click();
      await chooseWorkspaceSurface(page, "Workspace");
      await openNativeCompiler(page);
      const compiler = page.getByRole("region", {
        name: "Native backup default compiler",
        exact: true,
      });
      const offline = await openRecord(page, compiler, effective);
      await expect(
        offline.editor.getByLabel("Existing connection to remove", {
          exact: true,
        }),
      ).toHaveValue("2");
      await expect(
        offline.editor.getByRole("region", {
          name: "Reviewed connection removal",
          exact: true,
        }),
      ).toHaveCount(0);
      await prepare(offline.editor);
      expect((await peer.command("stats")).events).toEqual(directAfter.events);
    } finally {
      peer.close();
    }
  });
