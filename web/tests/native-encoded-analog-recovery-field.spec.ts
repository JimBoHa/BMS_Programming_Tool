import { test, expect } from "./nativeScheduleWriteFixture";
import { nativeDefaultPeer } from "./native-default-peer";
import { freePort } from "./workflow-peer";
import { openFieldInputs } from "./native-terminal-field-fixture";
import { prepare } from "./native-encoded-analog-recovery-fixture";
test.setTimeout(90000);
for (const mode of ["direct", "routed", "unknown", "late-proof"] as const)
  test(`${mode} configured analog recovery preserves origin, confirmations, draft and no-replay readback`, async ({
    page,
    request,
  }) => {
    const peer = await nativeDefaultPeer("consume", "encoded-analog-input");
    try {
      const base = "/api/bacnet/controller/native-application",
        headers = {
          "X-Studio-Token": (await (await request.get("/api/session")).json())
            .token,
        };
      const post = async (p: string, data: any) => {
        const r = await request.post(p, { headers, data });
        expect(r.ok(), await r.text()).toBe(true);
        return r.json();
      };
      await post(base + "/credentials", {
        backup: "authored-backup",
        restore: "authored-restore",
      });
      await post("/api/bacnet/connect", {
        local_address: `127.0.0.1:${await freePort()}`,
      });
      const target = {
        address: mode === "routed" ? "3001:7" : peer.direct,
        device: "device,5136",
        router: mode === "routed" ? peer.router : null,
        dnet: mode === "routed" ? 3001 : null,
      };
      const captured = await post(base + "/capture", {
          ...target,
          operation_id: "seed-recovery-capture",
        }),
        q = {
          capture_id: captured.id,
          snapshot_sha256: captured.snapshot_evidence_sha256,
        };
      const source = await post(base + "/input/encoded-terminal/source", q),
        edit = {
          action: "encoded-terminal",
          object_instance: 101,
          slot: 3,
          configuration_sha256: source.inputs[0].configuration_sha256,
        };
      const plan = await post(base + "/input/preview", {
        ...target,
        ...q,
        edit,
        operation_id: "seed-recovery-parent",
      });
      const parent = await post(base + "/input/apply", {
        operation_id: "seed-recovery-parent-apply",
        token: plan.token,
        review_sha256: plan.review_sha256,
        physical_wiring_confirmed: true,
        input_change_confirmed: true,
        application_transfer_confirmed: true,
      });
      expect(parent.result.status).toBe("verified");
      await post("/api/bacnet/disconnect", {});
      const inputs = await openFieldInputs(
        page,
        peer,
        mode === "routed",
        false,
      );
      await inputs
        .getByLabel("Engineering range high", { exact: true })
        .fill("9.");
      const analog = inputs.getByLabel("Analog input terminal movement", {
        exact: true,
      });
      await analog.locator(":scope > summary").click();
      await expect(
        analog.getByLabel("Configured analog input", { exact: true }),
      ).toBeVisible();
      await analog
        .getByLabel("Configured analog input", { exact: true })
        .selectOption("analog-input,101");
      await analog
        .getByLabel("Analog terminal destination", { exact: true })
        .selectOption("2");
      const recovery = await prepare(analog, parent.intent.id);
      await expect(
        recovery.getByRole("button", {
          name: "Stage previous analog terminal",
          exact: true,
        }),
      ).toBeVisible();
      await recovery
        .getByRole("button", {
          name: "Stage previous analog terminal",
          exact: true,
        })
        .click();
      await analog
        .getByRole("button", {
          name: "Review analog controller change",
          exact: true,
        })
        .click();
      const review = analog.getByRole("region", {
        name: "Analog terminal review",
        exact: true,
      });
      await expect(review).toContainText(`bound to parent ${parent.intent.id}`);
      const apply = review.getByRole("button", {
        name: "Apply analog terminal change to controller",
        exact: true,
      });
      await expect(apply).toBeDisabled();
      for (let i = 0; i < 3; i++) {
        await review.getByRole("checkbox").nth(i).check();
        if (i < 2) await expect(apply).toBeDisabled();
      }
      if (mode === "unknown") await peer.command("mode drop-end");
      if (mode === "late-proof")
        await page.evaluate(() => {
          const w = window as any,
            original = crypto.subtle.digest.bind(crypto.subtle);
          w.recoveryWaiting = [];
          w.recoveryDelay = true;
          w.recoveryDone = 0;
          crypto.subtle.digest = async (a: any, v: any) => {
            const tracked = new TextDecoder()
              .decode(v)
              .includes("native-encoded-analog-terminal-recovery-draft/1");
            if (tracked && w.recoveryDelay)
              await new Promise<void>((r) => w.recoveryWaiting.push(r));
            const result = await original(a, v);
            if (tracked) w.recoveryDone++;
            return result;
          };
        });
      const done = page.waitForResponse(
        (r) =>
          r.request().method() === "POST" && r.url().endsWith("/input/apply"),
      );
      await apply.click();
      await (await done).finished();
      if (mode === "late-proof") {
        await page.waitForFunction(
          () => (window as any).recoveryWaiting.length > 0,
        );
        await page.evaluate(() => {
          const w = window as any;
          window.dispatchEvent(new Event("pagehide"));
          w.recoveryDelay = false;
          w.recoveryWaiting.splice(0).forEach((r: any) => r());
        });
        await page.waitForFunction(() => (window as any).recoveryDone >= 1);
        await analog.locator(":scope > summary").click();
        await expect(
          analog.getByRole("button", {
            name: "Review local analog terminal copy",
            exact: true,
          }),
        ).toBeEnabled();
        await expect(
          analog.getByRole("region", {
            name: "Analog terminal transfer result",
            exact: true,
          }),
        ).toHaveCount(0);
        expect(
          (await peer.command("stats")).events.filter(
            (e: any[]) => e[0] === "state" && e[1] === "start-restore",
          ),
        ).toHaveLength(2);
        return;
      }
      const result = analog.getByRole("region", {
        name: "Analog terminal transfer result",
        exact: true,
      });
      await expect(result).toBeVisible();
      if (mode === "unknown") {
        await expect(result).toContainText("outcome uncertain");
        await peer.command("mode normal");
        const before = await peer.command("stats");
        await result
          .getByRole("button", {
            name: "Read back analog transfer",
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
      await expect(result).toContainText(`parent ${parent.intent.id}`);
      await expect(
        analog.getByLabel("Analog terminal destination", { exact: true }),
      ).toHaveValue("2");
      await expect(
        analog.getByRole("region", {
          name: "Staged previous analog terminal",
          exact: true,
        }),
      ).toHaveCount(0);
      await expect(
        analog.getByRole("button", {
          name: "Review analog controller change",
          exact: true,
        }),
      ).toBeDisabled();
      await analog.locator(":scope > summary").click();
      await expect(
        inputs.getByLabel("Engineering range high", { exact: true }),
      ).toHaveValue("9.");
      const stats = await peer.command("stats");
      expect(
        stats.events.filter(
          (e: any[]) => e[0] === "state" && e[1] === "start-restore",
        ),
      ).toHaveLength(2);
      expect(stats.router_errors).toEqual([]);
    } finally {
      peer.close();
    }
  });
