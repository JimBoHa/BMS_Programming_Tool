import { test, expect } from "./nativeScheduleWriteFixture";

import { freePort } from "./workflow-peer";
import { openFieldInputs } from "./native-terminal-field-fixture";
import {
  prepare,
  binaryRecoveryPeer,
} from "./native-binary-terminal-recovery-fixture";
test.setTimeout(90000);
for (const mode of [
  "direct",
  "routed",
  "unknown",
  "late-proof",
  "fresh-counters",
] as const)
  test(`${mode} configured binary recovery preserves origin, confirmations, draft and no-replay readback`, async ({
    page,
    request,
  }) => {
    const peer = await binaryRecoveryPeer();
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
      const source = await post(base + "/input/binary-terminal/source", q),
        edit = {
          action: "binary-terminal",
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
      const binary = inputs.getByLabel("Binary input terminal movement", {
        exact: true,
      });
      await binary.locator(":scope > summary").click();
      await expect(
        binary.getByLabel("Configured binary input", { exact: true }),
      ).toBeVisible();
      await binary
        .getByLabel("Configured binary input", { exact: true })
        .selectOption("binary-input,101");
      await binary
        .getByLabel("Binary terminal destination", { exact: true })
        .selectOption("2");
      const recovery = await prepare(binary, parent.intent.id);
      await expect(
        recovery.getByRole("button", {
          name: "Stage previous binary terminal",
          exact: true,
        }),
      ).toBeVisible();
      await recovery
        .getByRole("button", {
          name: "Stage previous binary terminal",
          exact: true,
        })
        .click();
      if (mode === "fresh-counters") await peer.command("counters 12345 12346");
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
      await expect(review).toContainText(`bound to parent ${parent.intent.id}`);
      const apply = review.getByRole("button", {
        name: "Apply binary terminal change to controller",
        exact: true,
      });
      await expect(apply).toBeDisabled();
      for (let i = 0; i < 3; i++) {
        await review.getByRole("checkbox").nth(i).check();
        if (i < 2) await expect(apply).toBeDisabled();
      }
      if (mode === "unknown") await peer.command("mode drop-end");
      if (mode === "fresh-counters")
        await peer.command("counters 4294967295 0");
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
              .includes("native-binary-terminal-recovery-draft/1");
            if (tracked && w.recoveryDelay)
              await new Promise<void>((r) => w.recoveryWaiting.push(r));
            const result = await original(a, v);
            if (tracked) w.recoveryDone++;
            return result;
          };
        });
      let appliedEvidence = Buffer.alloc(0);
      if (mode === "fresh-counters")
        await page.route("**/input/apply", async (route) => {
          const response = await route.fetch({ maxRetries: 0 });
          appliedEvidence = await response.body();
          await route.fulfill({ response, body: appliedEvidence });
        });
      const done = page.waitForResponse(
        (r) =>
          r.request().method() === "POST" && r.url().endsWith("/input/apply"),
      );
      await apply.click();
      const applied = await done;
      await applied.finished();
      if (mode === "fresh-counters") {
        expect(appliedEvidence.length).toBeGreaterThan(0);
        const result = JSON.parse(appliedEvidence.toString("utf8"));
        expect(result.intent.compilation.captured_counter_values).toEqual({
          "15": 4294967295,
          "33": 0,
        });
        expect((await peer.command("stats")).counters).toEqual({
          "15": 4294967295,
          "33": 0,
        });
      }
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
        await binary.locator(":scope > summary").click();
        await expect(
          binary.getByRole("button", {
            name: "Review local binary terminal copy",
            exact: true,
          }),
        ).toBeEnabled();
        await expect(
          binary.getByRole("region", {
            name: "Binary terminal transfer result",
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
      const result = binary.getByRole("region", {
        name: "Binary terminal transfer result",
        exact: true,
      });
      await expect(result).toBeVisible();
      if (mode === "unknown") {
        await expect(result).toContainText("outcome uncertain");
        await peer.command("mode normal");
        const before = await peer.command("stats");
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
      await expect(result).toContainText(`parent ${parent.intent.id}`);
      await expect(
        binary.getByLabel("Binary terminal destination", { exact: true }),
      ).toHaveValue("2");
      await expect(
        binary.getByRole("region", {
          name: "Staged previous binary terminal",
          exact: true,
        }),
      ).toHaveCount(0);
      await expect(
        binary.getByRole("button", {
          name: "Review binary controller change",
          exact: true,
        }),
      ).toBeDisabled();
      await binary.locator(":scope > summary").click();
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
