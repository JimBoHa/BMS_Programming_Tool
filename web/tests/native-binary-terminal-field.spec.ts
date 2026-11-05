import { test, expect } from "./nativeScheduleWriteFixture";
import { nativeDefaultPeer } from "./native-default-peer";
import { openFieldInputs } from "./native-terminal-field-fixture";
import { binaryDraft } from "./native-binary-terminal-fixture";
test.setTimeout(60000);

for (const mode of ["direct", "routed", "unknown"] as const)
  test(`${mode} binary terminal reviews exact source, requires three confirmations and verifies readback`, async ({
    page,
    request,
  }) => {
    const peer = await nativeDefaultPeer("consume", "binary-input");
    try {
      const headers = {
        "X-Studio-Token": (await (await request.get("/api/session")).json())
          .token,
      };
      const credentials = await request.post(
        "/api/bacnet/controller/native-application/credentials",
        {
          headers,
          data: { backup: "authored-backup", restore: "authored-restore" },
        },
      );
      expect(credentials.ok()).toBe(true);
      const inputs = await openFieldInputs(
          page,
          peer,
          mode === "routed",
          false,
        ),
        binary = inputs.getByLabel("Binary input terminal movement", {
          exact: true,
        });
      await binary.locator(":scope > summary").click();
      await expect(
        binary.getByLabel("Configured binary input", { exact: true }),
      ).toBeVisible();
      await binaryDraft(binary);
      await binary
        .getByRole("button", {
          name: "Review binary controller change",
          exact: true,
        })
        .click();
      const review = binary.getByRole("region", {
        name: "Binary terminal review",
        exact: true,
      });
      await expect(review).toBeVisible();
      const apply = review.getByRole("button", {
        name: "Apply binary terminal change to controller",
        exact: true,
      });
      await expect(apply).toBeDisabled();
      const boxes = review.getByRole("checkbox");
      for (let i = 0; i < 3; i++) {
        await boxes.nth(i).check();
        if (i < 2) await expect(apply).toBeDisabled();
      }
      await expect(apply).toBeEnabled();
      if (mode === "unknown") await peer.command("mode drop-end");
      const response = page.waitForResponse(
        (r) =>
          r.request().method() === "POST" && r.url().endsWith("/input/apply"),
      );
      await apply.click();
      await (await response).finished();
      const result = binary.getByRole("region", {
        name: "Binary terminal transfer result",
        exact: true,
      });
      await expect(result).toBeVisible();
      if (mode === "unknown") {
        await expect(result).toContainText("outcome uncertain");
        const before = await peer.command("stats");
        await peer.command("mode normal");
        await result
          .getByRole("button", {
            name: "Read back binary transfer",
            exact: true,
          })
          .click();
        await expect(result).toContainText("verified", { timeout: 15000 });
        expect(
          (await peer.command("stats")).events.filter(
            (e: any[]) => e[0] === "write",
          ),
        ).toEqual(before.events.filter((e: any[]) => e[0] === "write"));
      } else await expect(result).toContainText("verified");
      await expect(binary).toContainText(
        "Capture native inputs again before another controller change",
      );
      await expect(
        binary.getByRole("button", {
          name: "Review binary controller change",
          exact: true,
        }),
      ).toBeDisabled();
      await binary.locator(":scope > summary").click();
      await expect(inputs).toContainText(
        "A binary transfer changed this application",
      );
      const stats = await peer.command("stats");
      expect(
        stats.events.filter(
          (e: any[]) => e[0] === "state" && e[1] === "start-restore",
        ),
      ).toHaveLength(1);
      expect(stats.router_errors).toEqual([]);
    } finally {
      peer.close();
    }
  });
