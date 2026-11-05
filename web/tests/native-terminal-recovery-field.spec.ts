import { test, expect } from "./nativeScheduleWriteFixture";
import {
  allocatedPeer,
  openFieldInputs,
} from "./native-terminal-field-fixture";
import { apply, prepare } from "./native-terminal-recovery-fixture";

// Each case seeds an allocation, applies a forward move and applies its inverse.
test.setTimeout(60000);

for (const mode of ["direct", "routed", "unknown"] as const) {
  test(`${mode} previous-terminal recovery reviews exact lineage and restores the ordinary draft after verified completion`, async ({
    page,
    request,
  }) => {
    const peer = await allocatedPeer(request);
    try {
      const inputs = await openFieldInputs(page, peer, mode === "routed");
      await inputs
        .getByRole("button", {
          name: "Review controller input change",
          exact: true,
        })
        .click();
      await apply(page, inputs);
      await expect(
        inputs.getByRole("region", {
          name: "Input transfer result",
          exact: true,
        }),
      ).toContainText("verified");
      await expect(
        inputs.getByRole("button", {
          name: "Capture native inputs",
          exact: true,
        }),
      ).toBeEnabled();
      await inputs
        .getByRole("button", { name: "Capture native inputs", exact: true })
        .click();
      await expect(
        inputs.getByRole("button", {
          name: "Capture native inputs",
          exact: true,
        }),
      ).toBeEnabled();
      await inputs
        .getByLabel("Field terminal destination", { exact: true })
        .selectOption("2");
      const status = await (
        await request.get("/api/bacnet/controller/native-application/status")
      ).json();
      const parent = status.receipts.find(
        (r: any) =>
          r.operation_profile === "native-local-universal-input-transfer/2" &&
          r.input_edit.action === "terminal",
      );
      expect(parent).toBeTruthy();
      const recovery = await prepare(inputs, parent.id);
      await expect(
        recovery.getByRole("button", {
          name: "Use previous input terminal",
          exact: true,
        }),
      ).toBeEnabled();
      await recovery
        .getByRole("button", {
          name: "Use previous input terminal",
          exact: true,
        })
        .click();
      await expect(
        inputs.getByLabel("Field terminal destination", { exact: true }),
      ).toHaveValue("1");
      if (mode === "direct") {
        await inputs
          .getByRole("button", { name: "Capture native inputs", exact: true })
          .click();
        await expect(
          inputs.getByRole("button", {
            name: "Capture native inputs",
            exact: true,
          }),
        ).toBeEnabled();
        await expect(
          inputs.getByLabel("Field terminal destination", { exact: true }),
        ).toHaveValue("2");
        await expect(
          inputs.getByRole("region", {
            name: "Staged previous-terminal draft",
            exact: true,
          }),
        ).toHaveCount(0);
        await prepare(inputs, parent.id);
        await expect(
          recovery.getByRole("button", {
            name: "Use previous input terminal",
            exact: true,
          }),
        ).toBeEnabled();
        await recovery
          .getByRole("button", {
            name: "Use previous input terminal",
            exact: true,
          })
          .click();
      }
      let reviewed: any;
      await page.route("**/input/terminal-recovery/preview", async (route) => {
        reviewed = route.request().postDataJSON();
        await route.continue();
      });
      await inputs
        .getByRole("button", {
          name: "Review controller input change",
          exact: true,
        })
        .click();
      const review = inputs.getByRole("region", {
        name: "Input change review",
        exact: true,
      });
      await expect(review).toContainText(
        "Previous-terminal recovery from receipt " + parent.id.slice(0, 8),
      );
      expect(reviewed.recovery_parent_receipt).toBe(parent.id);
      expect(reviewed.edit.slot).toBe(1);
      await expect(
        review.getByRole("button", {
          name: "Apply input change to controller",
          exact: true,
        }),
      ).toBeDisabled();
      if (mode === "unknown") await peer.command("mode drop-end");
      await apply(page, inputs);
      const result = inputs.getByRole("region", {
        name: "Input transfer result",
        exact: true,
      });
      await expect(result).toContainText(
        mode === "unknown" ? "unknown" : "verified",
      );
      if (mode === "unknown") {
        await expect(
          inputs.getByRole("region", {
            name: "Staged previous-terminal draft",
            exact: true,
          }),
        ).toBeVisible();
        const before = await peer.command("mode normal");
        const done = page.waitForResponse(
          (r) =>
            r.request().method() === "POST" &&
            r.url().endsWith("/native-application/readback"),
        );
        await result
          .getByRole("button", {
            name: "Read back input transfer",
            exact: true,
          })
          .click();
        await (await done).finished();
        await expect(result).toContainText("verified");
        expect(
          (await peer.command("stats")).events.filter(
            (e: any[]) => e[0] === "write",
          ),
        ).toEqual(before.events.filter((e: any[]) => e[0] === "write"));
      }
      await expect(
        inputs.getByLabel("Field terminal destination", { exact: true }),
      ).toHaveValue("2");
      await expect(
        inputs.getByRole("region", {
          name: "Staged previous-terminal draft",
          exact: true,
        }),
      ).toHaveCount(0);
      const final = await (
        await request.get("/api/bacnet/controller/native-application/status")
      ).json();
      const child = final.receipts.find(
        (r: any) => r.id !== parent.id && r.input_edit?.action === "terminal",
      );
      const receipt = await (
        await request.get(
          "/api/bacnet/controller/native-application/receipts/" + child.id,
        )
      ).json();
      expect(receipt.intent.terminal_recovery_lineage_enforced).toBe(true);
      expect(receipt.intent.recovery_parent_receipt).toBe(parent.id);
      expect(receipt.intent.input_edit.slot).toBe(1);
    } finally {
      peer.close();
    }
  });
}
