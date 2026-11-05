import { test, expect } from "./nativeScheduleWriteFixture";
import { nativeDefaultPeer } from "./native-default-peer";
import { openFieldInputs } from "./native-terminal-field-fixture";
import { encodedAnalogDraft } from "./native-encoded-analog-terminal-fixture";
test.setTimeout(60000);

for (const mode of ["direct", "routed", "unknown"] as const)
  test(`${mode} analog terminal reviews exact source, requires three confirmations and verifies readback`, async ({
    page,
    request,
  }) => {
    const peer = await nativeDefaultPeer("consume", "encoded-analog-input");
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
        analog = inputs.getByLabel("Analog input terminal movement", {
          exact: true,
        });
      await analog.locator(":scope > summary").click();
      await expect(
        analog.getByLabel("Configured analog input", { exact: true }),
      ).toBeVisible();
      await encodedAnalogDraft(analog);
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
      await expect(review).toBeVisible();
      const apply = review.getByRole("button", {
        name: "Apply analog terminal change to controller",
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
      const result = analog.getByRole("region", {
        name: "Analog terminal transfer result",
        exact: true,
      });
      await expect(result).toBeVisible();
      if (mode === "unknown") {
        await expect(result).toContainText("outcome uncertain");
        const before = await peer.command("stats");
        await peer.command("mode normal");
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
      await expect(analog).toContainText(
        "Capture native inputs again before another controller change",
      );
      await expect(
        analog.getByRole("button", {
          name: "Review analog controller change",
          exact: true,
        }),
      ).toBeDisabled();
      await analog.locator(":scope > summary").click();
      await expect(inputs).toContainText(
        "An analog terminal transfer changed this application",
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

for (const fault of [
  "proof",
  "late-review",
  "target-change",
  "receipt",
] as const)
  test(`analog field ${fault} retires authority and preserves recovery evidence`, async ({
    page,
    request,
  }) => {
    const peer = await nativeDefaultPeer("consume", "encoded-analog-input");
    try {
      const headers = {
        "X-Studio-Token": (await (await request.get("/api/session")).json())
          .token,
      };
      expect(
        (
          await request.post(
            "/api/bacnet/controller/native-application/credentials",
            {
              headers,
              data: { backup: "authored-backup", restore: "authored-restore" },
            },
          )
        ).ok(),
      ).toBe(true);
      const inputs = await openFieldInputs(page, peer, false, false),
        analog = inputs.getByLabel("Analog input terminal movement", {
          exact: true,
        });
      await analog.locator(":scope > summary").click();
      await expect(
        analog.getByLabel("Configured analog input", { exact: true }),
      ).toBeVisible();
      await encodedAnalogDraft(analog);
      const before = await peer.command("stats");
      let release!: () => void, seen!: () => void;
      const gate = new Promise<void>((r) => (release = r)),
        arrived = new Promise<void>((r) => (seen = r));
      if (fault === "proof" || fault === "late-review")
        await page.route(
          "**/native-application/input/preview",
          async (route) => {
            const response = await route.fetch();
            if (fault === "proof") {
              const data = await response.json();
              data.compilation.stored_configuration.output_low = 0;
              await route.fulfill({ response, json: data });
            } else {
              seen();
              await gate;
              await route.fulfill({ response });
            }
          },
        );
      const canceled =
        fault === "proof" ||
        fault === "late-review" ||
        fault === "target-change"
          ? page.waitForResponse(
              (r) =>
                r.request().method() === "POST" &&
                r.url().endsWith("/native-application/cancel"),
            )
          : null;
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
      if (fault === "proof") {
        await expect(analog.getByRole("alert")).toContainText("proof differs");
        await canceled;
      } else if (fault === "late-review") {
        await arrived;
        await page.evaluate(() => window.dispatchEvent(new Event("pagehide")));
        release();
        await canceled;
        await analog.locator(":scope > summary").click();
        await expect(
          analog.getByRole("button", {
            name: "Review analog controller change",
            exact: true,
          }),
        ).toBeEnabled();
      } else {
        await expect(review).toBeVisible();
        if (fault === "target-change") {
          await page
            .getByRole("button", { name: "Change controller", exact: true })
            .click();
          await canceled;
        } else {
          await page.route(
            "**/native-application/input/apply",
            async (route) => {
              const response = await route.fetch(),
                data = await response.json();
              data.intent.compilation.configuration_storage.linear_output_endpoints_present = true;
              await route.fulfill({ response, json: data });
            },
          );
          for (const box of await review.getByRole("checkbox").all())
            await box.check();
          const completed = page.waitForResponse(
            (r) =>
              r.request().method() === "POST" &&
              r.url().endsWith("/input/apply"),
          );
          await review
            .getByRole("button", {
              name: "Apply analog terminal change to controller",
              exact: true,
            })
            .click();
          await (await completed).finished();
          await expect(analog.getByRole("alert")).toContainText(
            "receipt differs",
          );
          await expect(
            analog.getByRole("region", {
              name: "Analog terminal transfer result",
              exact: true,
            }),
          ).toHaveCount(0);
          // The durable backend receipt remains available; no automatic second transfer.
          const response = await request.get(
              "/api/bacnet/controller/native-application/status",
            ),
            status = await response.json();
          expect(
            status.receipts.filter(
              (r: any) => r.input_edit?.action === "encoded-terminal",
            ),
          ).toHaveLength(1);
        }
      }
      await expect(
        page.getByRole("button", {
          name: "Apply analog terminal change to controller",
          exact: true,
        }),
      ).toHaveCount(0);
      const after = await peer.command("stats");
      if (fault !== "receipt")
        expect(after.events.filter((e: any[]) => e[0] === "write")).toEqual(
          before.events.filter((e: any[]) => e[0] === "write"),
        );
      else
        expect(
          after.events.filter(
            (e: any[]) => e[0] === "state" && e[1] === "start-restore",
          ),
        ).toHaveLength(1);
    } finally {
      peer.close();
    }
  });
