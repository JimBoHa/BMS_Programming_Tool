import { test, expect } from "./nativeScheduleWriteFixture";
import type { Locator } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { nativeDefaultPeer } from "./native-default-peer";
import { openOrder } from "./native-execution-order-fixture";
import { openOrderTransfer as open } from "./native-order-transfer-browser-fixture";
import {
  chooseWorkspaceTask,
  expectWorkspaceNavigationLocked,
  openNativeCompiler,
} from "./workspace-navigation";

async function reviewed(transfer: Locator) {
  await transfer
    .getByRole("button", {
      name: "Review execution-order transfer",
      exact: true,
    })
    .click();
  const plan = transfer.getByRole("region", {
    name: "Reviewed controller execution order",
    exact: true,
  });
  await expect(plan).toBeVisible();
  await plan.getByRole("checkbox").nth(0).check();
  await plan.getByRole("checkbox").nth(1).check();
  const apply = transfer.getByRole("button", {
    name: "Apply execution order to controller",
    exact: true,
  });
  await expect(apply).toBeEnabled();
  return { plan, apply };
}
const restores = (events: any[]) =>
  events.filter((r) => r[0] === "state" && r[1] === "start-restore");
for (const boundary of [
  "visibility",
  "pagehide",
  "surface",
  "destination",
  "operation",
  "proposal",
])
  test(`${boundary} retires the old order Apply callback before dispatch`, async ({
    page,
  }) => {
    const peer = await nativeDefaultPeer("consume", "execution-order");
    try {
      const { editor, transfer } = await open(page, peer.direct, false);
      const { plan, apply } = await reviewed(transfer),
        old = await apply.elementHandle();
      let posts = 0;
      await page.route("**/execution-order/transfer/apply", async (r) => {
        posts++;
        await r.abort();
      });
      if (boundary === "visibility" || boundary === "pagehide")
        await page.evaluate(
          ({ old, boundary }) => {
            if (boundary === "pagehide")
              window.dispatchEvent(new Event("pagehide"));
            else document.dispatchEvent(new Event("visibilitychange"));
            (old as HTMLElement).click();
          },
          { old, boundary },
        );
      else if (boundary === "surface")
        await editor.locator(":scope > summary").evaluate((e, old) => {
          (e as HTMLElement).click();
          (e as HTMLElement).click();
          (old as HTMLElement).click();
        }, old);
      else if (boundary === "proposal") {
        await editor
          .getByRole("button", {
            name: "Move native block earlier",
            exact: true,
          })
          .evaluate((e, old) => {
            (e as HTMLElement).click();
            (old as HTMLElement).click();
          }, old);
      } else {
        const select =
          boundary === "destination"
            ? editor.getByLabel("Native execution-order destination", {
                exact: true,
              })
            : page.getByLabel("Native diagram operation", { exact: true });
        await select.evaluate(
          (e, { old, boundary }) => {
            const s = e as HTMLSelectElement,
              previous = s.value;
            for (const value of [
              boundary === "destination" ? "file" : "remove",
              previous,
            ]) {
              s.value = value;
              s.dispatchEvent(new Event("change", { bubbles: true }));
            }
            (old as HTMLElement).click();
          },
          { old, boundary },
        );
      }
      await expect(plan).toHaveCount(0);
      expect(posts).toBe(0);
      expect(restores((await peer.command("stats")).events)).toEqual([]);
    } finally {
      peer.close();
    }
  });

test("task navigation keeps the order draft and retires field authority", async ({
  page,
}) => {
  const peer = await nativeDefaultPeer("consume", "execution-order");
  try {
    const { editor, transfer, compiler } = await open(page, peer.direct, false);
    const capture = await compiler
      .getByLabel("Retained native backup", { exact: true })
      .inputValue();
    await reviewed(transfer);
    await chooseWorkspaceTask(page, "Overview");
    await openNativeCompiler(page);
    await compiler
      .getByLabel("Retained native backup", { exact: true })
      .selectOption(capture);
    await openOrder(page, compiler);
    await expect(editor).toBeVisible();
    await expect(
      editor.getByLabel("Native execution-order destination", { exact: true }),
    ).toHaveValue("controller");
    await expect(editor).toContainText("proposal has not been exported");
    await expect(
      transfer.getByRole("region", {
        name: "Reviewed controller execution order",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      transfer.getByRole("button", {
        name: "Review execution-order transfer",
        exact: true,
      }),
    ).toBeEnabled();
    expect(restores((await peer.command("stats")).events)).toEqual([]);
  } finally {
    peer.close();
  }
});

test("active restore locks its workspace and keeps exact late receipt after page retirement", async ({
  page,
}) => {
  const peer = await nativeDefaultPeer("consume", "execution-order");
  let release = () => {},
    held = false;
  const gate = new Promise<void>((r) => (release = r));
  let complete!: (v: { data: any; bytes: Buffer }) => void;
  const restored = new Promise<{ data: any; bytes: Buffer }>(
    (r) => (complete = r),
  );
  try {
    const { editor, transfer } = await open(page, peer.direct, false);
    const { apply } = await reviewed(transfer);
    await page.route("**/execution-order/transfer/apply", async (route) => {
      held = true;
      const response = await route.fetch({ maxRetries: 0 }),
        bytes = await response.body();
      complete({ data: JSON.parse(bytes.toString()), bytes });
      await gate;
      await route.fulfill({ response });
    });
    await apply.click();
    await expect.poll(() => held).toBe(true);
    await expectWorkspaceNavigationLocked(page);
    await expect(editor.locator(":scope > summary")).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    await editor
      .locator(":scope > summary")
      .evaluate((e) => (e as HTMLElement).click());
    await expect(editor).toHaveAttribute("open", "");
    const actual = await restored;
    expect(actual.data.result.status).toBe("verified");
    await page.evaluate(() => window.dispatchEvent(new Event("pagehide")));
    release();
    await expect(
      transfer.getByRole("region", {
        name: "Execution-order transfer result",
        exact: true,
      }),
    ).toContainText(
      "Execution order verified in the complete native readback.",
    );
    await page.evaluate(() => window.dispatchEvent(new Event("pageshow")));
    const saved = page.waitForEvent("download");
    await transfer
      .getByRole("button", {
        name: "Save execution-order transfer receipt",
        exact: true,
      })
      .click();
    expect(await readFile((await (await saved).path())!)).toEqual(actual.bytes);
    expect(restores((await peer.command("stats")).events)).toHaveLength(1);
  } finally {
    release();
    if (held) await restored;
    peer.close();
  }
});

test("lost commit acknowledgment remains uncertain until explicit readback, without replay", async ({
  page,
}) => {
  const peer = await nativeDefaultPeer("drop-end", "execution-order");
  try {
    const { transfer } = await open(page, peer.direct, false);
    await (await reviewed(transfer)).apply.click();
    const result = transfer.getByRole("region", {
      name: "Execution-order transfer result",
      exact: true,
    });
    await expect(result).toContainText("Execution-order outcome uncertain", {
      timeout: 20000,
    });
    await peer.command("mode normal");
    await transfer
      .getByRole("button", { name: "Read back execution order", exact: true })
      .click();
    await expect(result).toContainText(
      "Execution order verified in the complete native readback.",
    );
    expect(restores((await peer.command("stats")).events)).toHaveLength(1);
  } finally {
    peer.close();
  }
});
