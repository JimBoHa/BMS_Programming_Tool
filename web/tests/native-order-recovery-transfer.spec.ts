import { test, expect } from "./nativeScheduleWriteFixture";
import { readFile } from "node:fs/promises";
import { nativeDefaultPeer } from "./native-default-peer";
import {
  seedPreviousOrderAPI,
  openPreviousOrderUI,
  choosePrevious,
  nativeBase,
} from "./native-order-recovery-transfer-browser-fixture";
import {
  chooseWorkspaceTask,
  chooseWorkspaceTool,
} from "./workspace-navigation";
import { orderRecoveryTransferProfile } from "../src/nativeOrderRecoveryTransferContract";
import { connectionSeal } from "../src/nativeConnectionContract";
import { expectWorkspaceNavigationLocked } from "./workspace-navigation";
import { originalOrderFixture } from "./native-order-original-fixture";
import { openOrder } from "./native-execution-order-fixture";

const routedOriginal = originalOrderFixture(true);

routedOriginal(
  "uncertain previous-order commit is loaded and read back without replay",
  async ({ page, originalOrder }) => {
    const { peer, seeded } = originalOrder;
    const opened = await openPreviousOrderUI(page, seeded),
      { apply } = await reviewedPrevious(page, opened);
    let receipt: any;
    await page.route("**/execution-order/transfer/apply", async (route) => {
      const response = await route.fetch({ maxRetries: 0 }),
        bytes = await response.body();
      receipt = JSON.parse(bytes.toString());
      await route.fulfill({ response, body: bytes });
    });
    await peer.command("mode drop-end");
    const applied = page.waitForResponse(
      (response) =>
        response.url().endsWith("/execution-order/transfer/apply") &&
        response.request().method() === "POST",
    );
    await apply.click();
    expect((await applied).ok()).toBe(true);
    expect(receipt.pending).toBe(true);
    const result = opened.transfer.getByRole("region", {
      name: "Execution-order transfer result",
      exact: true,
    });
    await expect(result).toContainText(receipt.intent.id);
    await expect(result).toContainText("Execution-order outcome uncertain");
    expect(receipt.intent.recovery_origin.parent_receipt_id).toBe(
      seeded.parent.intent.id,
    );
    await peer.command("mode normal");
    await opened.transfer
      .getByLabel("Execution-order receipt", { exact: true })
      .selectOption(receipt.intent.id);
    await opened.transfer
      .getByRole("button", {
        name: "Load execution-order receipt",
        exact: true,
      })
      .click();
    await expect(result).toContainText("Execution-order outcome uncertain");
    await opened.transfer
      .getByRole("button", { name: "Read back execution order", exact: true })
      .click();
    await expect(result).toContainText(
      "Execution order verified in the complete native readback.",
    );
    expect(restores((await peer.command("stats")).events)).toHaveLength(2);
    await expect(opened.table).toHaveText(opened.draft!);
  },
);

for (const routed of [false, true])
  for (const caf of [false, true])
    for (const width of [1440, 390])
      originalOrderFixture(routed, routed && caf && width === 1440)(
        `${routed ? "routed" : "direct"} ${caf ? "CAF" : "graph"} previous order uses a new verified restore at ${width}px`,
        async ({ page, request, originalOrder }, info) => {
          await page.setViewportSize({ width, height: 1000 });
          const { peer, seeded } = originalOrder;
          const original = await (
            await request.get(
              nativeBase + "/receipts/" + seeded.parent.intent.id,
            )
          ).json();
          const opened = await openPreviousOrderUI(page, seeded, caf);
          const plan = await choosePrevious(page, opened);
          const apply = opened.transfer.getByRole("button", {
            name: "Apply previous execution order to controller",
            exact: true,
          });
          await expect(apply).toBeDisabled();
          await plan.getByRole("checkbox").nth(0).check();
          await expect(apply).toBeDisabled();
          await plan.getByRole("checkbox").nth(1).check();
          if (!routed && !caf) {
            await opened.transfer
              .getByRole("region", {
                name: "Selected previous execution-order transfer",
                exact: true,
              })
              .scrollIntoViewIfNeeded();
            await page.screenshot({
              path: info.outputPath(`previous-order-review-${width}.png`),
            });
          }
          await peer.command("wire-other-fresh");
          let exact: Buffer | undefined;
          await page.route(
            "**/execution-order/transfer/apply",
            async (route) => {
              const response = await route.fetch({ maxRetries: 0 });
              exact = await response.body();
              await route.fulfill({ response, body: exact });
            },
          );
          const applied = page.waitForResponse(
            (response) =>
              response.url().endsWith("/execution-order/transfer/apply") &&
              response.request().method() === "POST",
          );
          await apply.click();
          expect((await applied).ok()).toBe(true);
          expect(exact).toBeTruthy();
          const receipt = JSON.parse(exact!.toString());
          expect(receipt.result.status).toBe("verified");
          expect(receipt.pending).toBe(false);
          await expect(
            opened.transfer.getByRole("region", {
              name: "Execution-order transfer result",
              exact: true,
            }),
          ).toContainText(receipt.intent.id);
          await expect(
            opened.transfer.getByRole("region", {
              name: "Execution-order transfer result",
              exact: true,
            }),
          ).toContainText(
            "Execution order verified in the complete native readback.",
          );
          expect(receipt.intent.id).not.toBe(seeded.parent.intent.id);
          expect(receipt.intent.recovery_profile).toBe(
            orderRecoveryTransferProfile,
          );
          expect(receipt.intent.recovery_origin.parent_receipt_id).toBe(
            seeded.parent.intent.id,
          );
          expect(receipt.intent.recovery_origin.verified_proof.kind).toBe(
            routed && caf && width === 1440 ? "readback-event" : "result",
          );
          const actual = await peer.command("stats");
          expect(actual.execution_order).toEqual([0, 1, 2, 3]);
          expect(
            actual.events.filter(
              (e: any[]) => e[0] === "state" && e[1] === "start-restore",
            ),
          ).toHaveLength(2);
          expect(actual.router_errors).toEqual([]);
          await expect(opened.table).toHaveText(opened.draft!);
          const saving = page.waitForEvent("download");
          await opened.transfer
            .getByRole("button", {
              name: "Save execution-order transfer receipt",
              exact: true,
            })
            .click();
          expect(await readFile((await (await saving).path())!)).toEqual(exact);
          expect(
            await (
              await request.get(
                nativeBase + "/receipts/" + seeded.parent.intent.id,
              )
            ).json(),
          ).toEqual(original);
          await chooseWorkspaceTask(page, "Changes");
          const ledger = page.getByRole("region", {
            name: "Change ledger",
            exact: true,
          });
          await expect(ledger).toContainText(
            "Previous execution-order recovery",
          );
          await ledger
            .getByRole("button", {
              name: "Details for native " + receipt.intent.id,
              exact: true,
            })
            .click();
          await expect(
            page.getByRole("region", {
              name: "Recorded previous execution-order recovery",
              exact: true,
            }),
          ).toContainText(seeded.parent.intent.id);
          await chooseWorkspaceTask(page, "Program");
          await chooseWorkspaceTool(page, "Local graph editor");
          await expect(
            page.getByLabel("Program name", { exact: true }),
          ).toHaveValue("Preserved previous-order local graph");
          if (caf)
            await expect(
              page.getByLabel("Current CAF archive", { exact: true }),
            ).toHaveText("previous-order-controller.caf");
          expect(
            await page.evaluate(
              () => document.documentElement.scrollWidth <= innerWidth + 1,
            ),
          ).toBe(true);
        },
      );

const restores = (events: any[]) =>
  events.filter((row) => row[0] === "state" && row[1] === "start-restore");
async function reviewedPrevious(page: any, opened: any) {
  const plan = await choosePrevious(page, opened);
  await plan.getByRole("checkbox").nth(0).check();
  await plan.getByRole("checkbox").nth(1).check();
  const apply = opened.transfer.getByRole("button", {
    name: "Apply previous execution order to controller",
    exact: true,
  });
  await expect(apply).toBeEnabled();
  return { plan, apply };
}
for (const boundary of [
  "visibility",
  "pagehide",
  "surface",
  "destination",
  "operation",
  "proposal",
  "local-draft",
  "receipt-selection",
])
  test(`previous-order ${boundary} retires the old Apply callback synchronously`, async ({
    page,
    request,
  }) => {
    const peer = await nativeDefaultPeer("consume", "execution-order");
    try {
      const seeded = await seedPreviousOrderAPI(request, peer, false);
      const opened = await openPreviousOrderUI(page, seeded);
      const { plan, apply } = await reviewedPrevious(page, opened);
      const old = await apply.elementHandle();
      let posts = 0;
      await page.route("**/execution-order/transfer/apply", async (route) => {
        posts++;
        await route.abort();
      });
      await page.route("**/execution-order/transfer/preview", async (route) => {
        posts++;
        await route.abort();
      });
      if (boundary === "visibility" || boundary === "pagehide") {
        await page.evaluate(
          ({ old, boundary }) => {
            if (boundary === "pagehide")
              window.dispatchEvent(new Event("pagehide"));
            else document.dispatchEvent(new Event("visibilitychange"));
            (old as HTMLElement).click();
          },
          { old, boundary },
        );
      } else if (boundary === "surface") {
        await opened.editor
          .locator(":scope > summary")
          .evaluate((summary: Element, old: any) => {
            (summary as HTMLElement).click();
            (summary as HTMLElement).click();
            old.click();
          }, old);
      } else if (boundary === "proposal" || boundary === "local-draft") {
        await opened.editor
          .getByRole("button", {
            name:
              boundary === "proposal"
                ? "Move native block earlier"
                : "Use local order draft for controller review",
            exact: true,
          })
          .evaluate((button: Element, old: any) => {
            (button as HTMLElement).click();
            old.click();
          }, old);
      } else {
        const select =
          boundary === "destination"
            ? opened.editor.getByLabel("Native execution-order destination", {
                exact: true,
              })
            : boundary === "operation"
              ? page.getByLabel("Native diagram operation", { exact: true })
              : opened.transfer.getByLabel("Execution-order receipt", {
                  exact: true,
                });
        await select.evaluate(
          (element: Element, { old, boundary }: any) => {
            const select = element as HTMLSelectElement,
              before = select.value;
            for (const value of [
              boundary === "destination"
                ? "file"
                : boundary === "operation"
                  ? "remove"
                  : "",
              before,
            ]) {
              select.value = value;
              select.dispatchEvent(new Event("change", { bubbles: true }));
            }
            old.click();
          },
          { old, boundary },
        );
      }
      await expect(plan).toHaveCount(0);
      expect(posts).toBe(0);
      expect(restores((await peer.command("stats")).events)).toHaveLength(1);
      if (boundary === "local-draft" || boundary === "receipt-selection") {
        await expect(opened.table).toHaveText(opened.draft!);
        await expect(
          opened.transfer.getByRole("button", {
            name: "Review execution-order transfer",
            exact: true,
          }),
        ).toBeEnabled();
      }
      expect(posts).toBe(0);
    } finally {
      peer.close();
    }
  });

for (const fault of ["profile", "scope", "parent", "missing", "extra"])
  test(`resealed ${fault} recovery review is refused before any new restore`, async ({
    page,
    request,
  }) => {
    const peer = await nativeDefaultPeer("consume", "execution-order");
    try {
      const seeded = await seedPreviousOrderAPI(request, peer, true);
      const opened = await openPreviousOrderUI(page, seeded);
      const plan = await choosePrevious(page, opened, false);
      await page.route("**/execution-order/transfer/preview", async (route) => {
        const response = await route.fetch({ maxRetries: 0 }),
          data = await response.json();
        if (fault === "profile") data.recovery_profile += "future";
        else if (fault === "scope") data.recovery_scope += "future";
        else if (fault === "parent") {
          data.recovery_origin.parent_receipt_id = "a".repeat(32);
          data.recovery_origin_sha256 = await connectionSeal(
            data.recovery_origin,
          );
        } else if (fault === "missing") delete data.recovery_origin;
        else data.recovery_authority = true;
        const { token, review_sha256, ...body } = data;
        data.review_sha256 = await connectionSeal(body);
        await route.fulfill({ response, json: data });
      });
      await opened.transfer
        .getByRole("button", {
          name: "Review previous execution-order transfer",
          exact: true,
        })
        .click();
      await expect(opened.transfer.getByRole("alert")).toContainText(
        "does not match",
      );
      await expect(plan).toHaveCount(0);
      await expect(
        opened.transfer.getByRole("button", {
          name: "Apply previous execution order to controller",
          exact: true,
        }),
      ).toHaveCount(0);
      expect(restores((await peer.command("stats")).events)).toHaveLength(1);
      await expect(opened.table).toHaveText(opened.draft!);
    } finally {
      peer.close();
    }
  });

test("a loaded recovery review cannot dispatch while a receipt replacement is pending", async ({
  page,
  request,
}) => {
  const peer = await nativeDefaultPeer("consume", "execution-order");
  let release = () => {};
  const gate = new Promise<void>((resolve) => (release = resolve));
  try {
    const seeded = await seedPreviousOrderAPI(request, peer, false);
    const opened = await openPreviousOrderUI(page, seeded);
    const { plan, apply } = await reviewedPrevious(page, opened),
      old = await apply.elementHandle();
    let posts = 0,
      arrived = false;
    await page.route("**/execution-order/transfer/apply", async (route) => {
      posts++;
      await route.abort();
    });
    await page.route("**/execution-order/transfer/preview", async (route) => {
      posts++;
      await route.abort();
    });
    await page.route(
      "**/native-application/receipts/" + seeded.parent.intent.id,
      async (route) => {
        const response = await route.fetch({ maxRetries: 0 });
        arrived = true;
        await gate;
        await route.fulfill({ response });
      },
    );
    await opened.transfer
      .getByRole("button", {
        name: "Load execution-order receipt",
        exact: true,
      })
      .evaluate((button: Element, old: any) => {
        (button as HTMLElement).click();
        old.click();
      }, old);
    await expect.poll(() => arrived).toBe(true);
    await expect(plan).toHaveCount(0);
    expect(posts).toBe(0);
    release();
    await expect(
      opened.transfer.getByRole("button", {
        name: "Load execution-order receipt",
        exact: true,
      }),
    ).toBeEnabled();
    await expect(opened.table).toHaveText(opened.draft!);
    expect(restores((await peer.command("stats")).events)).toHaveLength(1);
  } finally {
    release();
    peer.close();
  }
});

test("pending proposal admission cannot resurrect previous mode after a same-turn receipt load", async ({
  page,
  request,
}) => {
  const peer = await nativeDefaultPeer("consume", "execution-order");
  try {
    const seeded = await seedPreviousOrderAPI(request, peer, false);
    const opened = await openPreviousOrderUI(page, seeded);
    const load = await opened.transfer
      .getByRole("button", {
        name: "Load execution-order receipt",
        exact: true,
      })
      .elementHandle();
    await opened.prepared
      .getByRole("button", {
        name: "Use previous order for controller review",
        exact: true,
      })
      .evaluate((button: Element, load: any) => {
        (button as HTMLElement).click();
        load.click();
      }, load);
    await expect(
      opened.transfer.getByRole("button", {
        name: "Load execution-order receipt",
        exact: true,
      }),
    ).toBeEnabled();
    await expect(
      opened.transfer.getByRole("region", {
        name: "Selected previous execution-order transfer",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(opened.table).toHaveText(opened.draft!);
    expect(restores((await peer.command("stats")).events)).toHaveLength(1);
  } finally {
    peer.close();
  }
});

originalOrderFixture(false)(
  "a late previous-order review is cancelled after page retirement",
  async ({ page, originalOrder }) => {
    const { peer, seeded } = originalOrder;
    let release = () => {},
      finish = () => {};
    const gate = new Promise<void>((resolve) => (release = resolve)),
      done = new Promise<void>((resolve) => (finish = resolve));
    try {
      const opened = await openPreviousOrderUI(page, seeded);
      const plan = await choosePrevious(page, opened, false);
      let arrived = false;
      await page.route("**/execution-order/transfer/preview", async (route) => {
        try {
          const response = await route.fetch({ maxRetries: 0 });
          arrived = true;
          await gate;
          await route.fulfill({ response });
        } finally {
          finish();
        }
      });
      await opened.transfer
        .getByRole("button", {
          name: "Review previous execution-order transfer",
          exact: true,
        })
        .click();
      await expect.poll(() => arrived).toBe(true);
      await page.evaluate(() => window.dispatchEvent(new Event("pagehide")));
      release();
      await done;
      await expect(plan).toHaveCount(0);
      await expect(opened.table).toHaveText(opened.draft!);
      await expect(
        opened.transfer.getByRole("button", {
          name: "Review execution-order transfer",
          exact: true,
        }),
      ).toBeDisabled();
      await page.evaluate(() => window.dispatchEvent(new Event("pageshow")));
      await openOrder(page, opened.compiler);
      await opened.editor
        .getByLabel("Native execution-order destination", { exact: true })
        .selectOption("controller");
      await expect(
        opened.transfer.getByRole("button", {
          name: "Review execution-order transfer",
          exact: true,
        }),
      ).toBeEnabled();
      await expect(opened.table).toHaveText(opened.draft!);
      expect(restores((await peer.command("stats")).events)).toHaveLength(1);
    } finally {
      release();
    }
  },
);

routedOriginal(
  "an active previous-order restore retains its exact late receipt after page retirement",
  async ({ page, originalOrder }) => {
    const { peer, seeded } = originalOrder;
    let release = () => {};
    const gate = new Promise<void>((resolve) => (release = resolve));
    let complete!: (value: { bytes: Buffer; data: any }) => void;
    const received = new Promise<{ bytes: Buffer; data: any }>(
      (resolve) => (complete = resolve),
    );
    try {
      const opened = await openPreviousOrderUI(page, seeded),
        { apply } = await reviewedPrevious(page, opened);
      await page.route("**/execution-order/transfer/apply", async (route) => {
        const response = await route.fetch({ maxRetries: 0 }),
          bytes = await response.body();
        complete({ bytes, data: JSON.parse(bytes.toString()) });
        await gate;
        await route.fulfill({ response, body: bytes });
      });
      await apply.click();
      await expectWorkspaceNavigationLocked(page);
      const actual = await received;
      expect(actual.data.result.status).toBe("verified");
      expect(actual.data.intent.recovery_origin.parent_receipt_id).toBe(
        seeded.parent.intent.id,
      );
      await page.evaluate(() => window.dispatchEvent(new Event("pagehide")));
      release();
      await expect(
        opened.transfer.getByRole("region", {
          name: "Execution-order transfer result",
          exact: true,
        }),
      ).toContainText(actual.data.intent.id);
      await expect(
        opened.transfer.getByRole("region", {
          name: "Execution-order transfer result",
          exact: true,
        }),
      ).toContainText(
        "Execution order verified in the complete native readback.",
      );
      await page.evaluate(() => window.dispatchEvent(new Event("pageshow")));
      const saving = page.waitForEvent("download");
      await opened.transfer
        .getByRole("button", {
          name: "Save execution-order transfer receipt",
          exact: true,
        })
        .click();
      expect(await readFile((await (await saving).path())!)).toEqual(
        actual.bytes,
      );
      expect(restores((await peer.command("stats")).events)).toHaveLength(2);
    } finally {
      release();
    }
  },
);

test("an unavailable recovery profile preserves the local proposal without enabling controller review", async ({
  page,
  request,
}) => {
  const peer = await nativeDefaultPeer("consume", "execution-order");
  try {
    const seeded = await seedPreviousOrderAPI(request, peer, false);
    await page.route("**/native-application/status", async (route) => {
      const response = await route.fetch({ maxRetries: 0 }),
        data = await response.json();
      delete data.execution_order_recovery_transfer_profile;
      await route.fulfill({ response, json: data });
    });
    const opened = await openPreviousOrderUI(page, seeded);
    await expect(
      opened.prepared.getByRole("button", {
        name: "Use previous order for controller review",
        exact: true,
      }),
    ).toBeDisabled();
    await expect(
      opened.prepared.getByRole("button", {
        name: "Replace local order proposal with previous order",
        exact: true,
      }),
    ).toBeEnabled();
    await expect(
      opened.transfer.getByRole("region", {
        name: "Selected previous execution-order transfer",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(opened.table).toHaveText(opened.draft!);
    expect(restores((await peer.command("stats")).events)).toHaveLength(1);
  } finally {
    peer.close();
  }
});
