import { test, expect, type Locator } from "@playwright/test";
import { nativeDefaultPeer } from "./native-default-peer";
import { openMatchingConnection as open } from "./native-matching-connection-browser-fixture";
import { openRecord } from "./native-effective-connection-fixture";
import { d } from "./native-connection-fixture";
import {
  chooseWorkspaceTask,
  openNativeCompiler,
} from "./workspace-navigation";

async function review(panel: Locator) {
  await panel
    .getByRole("button", {
      name: "Review matching connection transfer",
      exact: true,
    })
    .click();
  await expect(
    panel.getByRole("region", {
      name: "Reviewed controller connection",
      exact: true,
    }),
  ).toBeVisible();
}
const restores = (events: any[]) =>
  events.filter((r) => r[0] === "state" && r[1] === "start-restore");

for (const boundary of ["pagehide", "shared-capture", "proposal"]) {
  test(`${boundary} retires a matching connection review without restoring a controller`, async ({
    page,
  }) => {
    const peer = await nativeDefaultPeer("consume", "connection");
    try {
      const { compiler, editor, transfer } = await open(
        page,
        peer.direct,
        false,
      );
      await review(transfer);
      const cancelled = page.waitForResponse((r) =>
        r.url().endsWith("/native-application/cancel"),
      );
      if (boundary === "pagehide")
        await page.evaluate(() => window.dispatchEvent(new Event("pagehide")));
      else if (boundary === "shared-capture") {
        const capture = compiler.getByLabel("Retained native backup", {
          exact: true,
        });
        const original = await capture.inputValue();
        await page
          .getByRole("region", {
            name: "Native default controller transfer",
            exact: true,
          })
          .getByRole("button", {
            name: "Read current native backup",
            exact: true,
          })
          .click();
        await expect(capture).not.toHaveValue(original);
      } else
        await editor
          .getByLabel("Unused native destination", { exact: true })
          .selectOption("");
      await cancelled;
      await expect(
        compiler.getByRole("region", {
          name: "Reviewed controller connection",
          exact: true,
        }),
      ).toHaveCount(0);
      await expect(
        compiler.getByRole("button", {
          name: "Save connection transfer review",
          exact: true,
        }),
      ).toHaveCount(0);
      expect(restores((await peer.command("stats")).events)).toHaveLength(0);
    } finally {
      peer.close();
    }
  });
}

test("task navigation preserves the local pair and retires connected review", async ({
  page,
}) => {
  const peer = await nativeDefaultPeer("consume", "connection");
  try {
    const { compiler, transfer } = await open(page, peer.direct, false);
    await review(transfer);
    const cancelled = page.waitForResponse((r) =>
      r.url().endsWith("/native-application/cancel"),
    );
    await chooseWorkspaceTask(page, "Overview");
    await cancelled;
    await openNativeCompiler(page);
    const reopened = await openRecord(page, compiler, true);
    await expect(
      reopened.editor.getByLabel("Unused native destination", { exact: true }),
    ).toHaveValue(d);
    await expect(
      reopened.editor.getByLabel("Matching connection destination", {
        exact: true,
      }),
    ).toHaveValue("controller");
    await expect(
      reopened.editor.getByRole("region", {
        name: "Reviewed controller connection",
        exact: true,
      }),
    ).toHaveCount(0);
    expect(restores((await peer.command("stats")).events)).toHaveLength(0);
  } finally {
    peer.close();
  }
});

test("a different controller with the same Device instance cannot adopt the old source or review", async ({
  page,
}) => {
  const first = await nativeDefaultPeer("consume", "connection"),
    second = await nativeDefaultPeer("consume", "connection");
  try {
    const { compiler, transfer } = await open(page, first.direct, false);
    const capture = await compiler
      .getByLabel("Retained native backup", { exact: true })
      .inputValue();
    await review(transfer);
    const cancelled = page.waitForResponse((r) =>
      r.url().endsWith("/native-application/cancel"),
    );
    await page
      .getByRole("button", { name: "Change controller", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Known controller address", exact: true })
      .click();
    for (const [label, value] of [
      ["Known controller address", second.direct],
      ["Known Device object", "device,5136"],
      ["Known router", ""],
      ["Known network", ""],
    ]) {
      await page.getByLabel(label, { exact: true }).fill(value);
    }
    await page
      .getByRole("region", { name: "Known controller connection", exact: true })
      .getByRole("button", { name: "Open controller", exact: true })
      .click();
    await cancelled;
    await openNativeCompiler(page);
    await compiler
      .getByLabel("Retained native backup", { exact: true })
      .selectOption(capture);
    const { editor } = await openRecord(page, compiler, true);
    await editor
      .getByLabel("Matching connection destination", { exact: true })
      .selectOption("controller");
    const panel = editor.getByRole("region", {
      name: "Native matching connection controller transfer",
      exact: true,
    });
    await expect(panel).toContainText(second.direct);
    await expect(panel).toContainText(
      "This retained source belongs to another controller",
    );
    await expect(
      panel.getByRole("button", {
        name: "Review matching connection transfer",
        exact: true,
      }),
    ).toBeDisabled();
    await expect(
      panel.getByRole("region", {
        name: "Reviewed controller connection",
        exact: true,
      }),
    ).toHaveCount(0);
    expect(restores((await first.command("stats")).events)).toHaveLength(0);
    expect(restores((await second.command("stats")).events)).toHaveLength(0);
  } finally {
    first.close();
    second.close();
  }
});

test("a late review after closing the task never revives field authority", async ({
  page,
}) => {
  const peer = await nativeDefaultPeer("consume", "connection");
  let release = () => {};
  const gate = new Promise<void>((resolve) => (release = resolve));
  try {
    const { editor, transfer } = await open(page, peer.direct, false);
    let received!: () => void;
    const waiting = new Promise<void>((resolve) => (received = resolve));
    await page.route(
      "**/matching-connection/transfer/preview",
      async (route) => {
        const response = await route.fetch({ maxRetries: 0 });
        received();
        await gate;
        await route.fulfill({ response });
      },
    );
    await transfer
      .getByRole("button", {
        name: "Review matching connection transfer",
        exact: true,
      })
      .click();
    await waiting;
    const cancelled = page.waitForResponse((r) =>
      r.url().endsWith("/native-application/cancel"),
    );
    await editor.locator(":scope > summary").click();
    await cancelled;
    release();
    await editor.locator(":scope > summary").click();
    await expect(
      transfer.getByRole("button", {
        name: "Review matching connection transfer",
        exact: true,
      }),
    ).toBeEnabled();
    await expect(
      transfer.getByRole("region", {
        name: "Reviewed controller connection",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      editor.getByLabel("Unused native destination", { exact: true }),
    ).toHaveValue(d);
    expect(restores((await peer.command("stats")).events)).toHaveLength(0);
  } finally {
    release();
    peer.close();
  }
});

test("compact keyboard review retains one primary action and the exact target", async ({
  page,
}, info) => {
  const peer = await nativeDefaultPeer("consume", "connection");
  try {
    await page.setViewportSize({ width: 820, height: 1100 });
    const { editor, transfer } = await open(page, peer.router, true);
    const action = transfer.getByRole("button", {
      name: "Review matching connection transfer",
      exact: true,
    });
    await action.focus();
    await page.keyboard.press("Enter");
    await expect(
      transfer.getByRole("region", {
        name: "Reviewed controller connection",
        exact: true,
      }),
    ).toBeVisible();
    for (const name of [
      "I confirm this existing-member connection and unused input.",
      "I confirm the application transfer and possible control interruption.",
    ]) {
      await transfer.getByRole("checkbox", { name, exact: true }).focus();
      await page.keyboard.press("Space");
    }
    await expect(
      transfer.getByRole("button", {
        name: "Apply matching connection to controller",
        exact: true,
      }),
    ).toBeEnabled();
    await expect(editor.locator("button.primary:visible")).toHaveCount(1);
    await expect(transfer).toContainText(
      `device,5136 · 3001:7 via ${peer.router}`,
    );
    expect(
      await page.evaluate(
        () =>
          document.documentElement.scrollWidth <=
          document.documentElement.clientWidth,
      ),
    ).toBe(true);
    await transfer.scrollIntoViewIfNeeded();
    await page.screenshot({
      path: info.outputPath("native-matching-connection-review-820.png"),
    });
    expect(restores((await peer.command("stats")).events)).toHaveLength(0);
  } finally {
    peer.close();
  }
});

test("recorded matching connection opens Program without changing target or preparing another transfer", async ({
  page,
  request,
}) => {
  const peer = await nativeDefaultPeer("consume", "connection");
  try {
    const { transfer } = await open(page, peer.direct, false);
    await review(transfer);
    for (const name of [
      "I confirm this existing-member connection and unused input.",
      "I confirm the application transfer and possible control interruption.",
    ]) {
      await transfer.getByRole("checkbox", { name, exact: true }).check();
    }
    await transfer
      .getByRole("button", {
        name: "Apply matching connection to controller",
        exact: true,
      })
      .click();
    await expect(
      transfer.getByRole("region", {
        name: "Matching connection transfer result",
        exact: true,
      }),
    ).toContainText("Connection verified", { timeout: 20000 });
    const status = await (
      await request.get("/api/bacnet/controller/native-application/status")
    ).json();
    const receipt = status.receipts.find(
      (row: any) =>
        row.change_kind === "connection" && row.target.address === peer.direct,
    );
    expect(receipt).toBeTruthy();
    const before = (await peer.command("stats")).events;
    await chooseWorkspaceTask(page, "Changes");
    await page
      .getByLabel("Record family", { exact: true })
      .selectOption("native");
    const records = page.getByRole("region", {
      name: "Recorded changes",
      exact: true,
    });
    await records
      .getByRole("button", {
        name: "Details for native " + receipt.id,
        exact: true,
      })
      .click();
    const detail = page.getByRole("region", {
      name: "Recorded native matching connection",
      exact: true,
    });
    await expect(detail).toContainText("Recorded matching connection");
    await expect(detail).toContainText(d);
    await expect(detail).toContainText("No original-backup revalidation");
    await page
      .getByRole("button", { name: "Open native program tools", exact: true })
      .click();
    await expect(
      page.getByLabel("Working context", { exact: true }),
    ).toContainText(peer.direct);
    await expect(
      page.getByRole("region", {
        name: "Native backup default compiler",
        exact: true,
      }),
    ).toBeVisible();
    expect((await peer.command("stats")).events).toEqual(before);
  } finally {
    peer.close();
  }
});
