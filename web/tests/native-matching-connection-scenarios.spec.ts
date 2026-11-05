import { test, expect, type Locator } from "@playwright/test";
import { readFileSync } from "node:fs";
import { nativeDefaultPeer } from "./native-default-peer";
import { openMatchingConnection as open } from "./native-matching-connection-browser-fixture";
import { d } from "./native-connection-fixture";

async function review(transfer: Locator) {
  await transfer
    .getByRole("button", {
      name: "Review matching connection transfer",
      exact: true,
    })
    .click();
  await expect(
    transfer.getByRole("region", {
      name: "Reviewed controller connection",
      exact: true,
    }),
  ).toBeVisible();
  await transfer
    .getByRole("checkbox", {
      name: "I confirm this existing-member connection and unused input.",
      exact: true,
    })
    .check();
  await transfer
    .getByRole("checkbox", {
      name: "I confirm the application transfer and possible control interruption.",
      exact: true,
    })
    .check();
  const apply = transfer.getByRole("button", {
    name: "Apply matching connection to controller",
    exact: true,
  });
  await expect(apply).toBeEnabled();
  return apply;
}
const restores = (events: any[]) =>
  events.filter((r) => r[0] === "state" && r[1] === "start-restore");

for (const recoverOriginal of [false, true]) {
  test(`${recoverOriginal ? "original recovery" : "verified connection"} after uncertain restore reloads its receipt without replay`, async ({
    page,
    request,
  }) => {
    test.setTimeout(60000);
    const peer = await nativeDefaultPeer("drop-end", "connection");
    try {
      const { compiler, transfer } = await open(page, peer.direct, false);
      const capture = await compiler
        .getByLabel("Retained native backup", { exact: true })
        .inputValue();
      await (await review(transfer)).click();
      await expect(
        transfer.getByRole("region", {
          name: "Matching connection transfer result",
          exact: true,
        }),
      ).toContainText("Connection outcome uncertain", { timeout: 25000 });
      const status = await (
        await request.get("/api/bacnet/controller/native-application/status")
      ).json();
      const matches = status.receipts.filter(
        (row: any) =>
          row.change_kind === "connection" &&
          row.connection_edit?.capture_id === capture,
      );
      expect(matches).toHaveLength(1);
      const receiptId = matches[0].id;
      const before = restores((await peer.command("stats")).events);
      expect(before).toHaveLength(1);
      await peer.command(
        recoverOriginal ? "connection-recover-original" : "mode normal",
      );
      const reopened = await open(page, peer.direct, false, capture);
      await reopened.transfer
        .getByText("Retained matching-connection receipts", { exact: true })
        .click();
      await reopened.transfer
        .getByLabel("Matching connection receipt", { exact: true })
        .selectOption(receiptId);
      await reopened.transfer
        .getByRole("button", {
          name: "Load matching connection receipt",
          exact: true,
        })
        .click();
      await expect(
        reopened.transfer.getByRole("button", {
          name: "Read back matching connection",
          exact: true,
        }),
      ).toBeEnabled();
      await reopened.transfer
        .getByRole("button", {
          name: "Read back matching connection",
          exact: true,
        })
        .click();
      await expect(
        reopened.transfer.getByRole("region", {
          name: "Matching connection transfer result",
          exact: true,
        }),
      ).toContainText(
        recoverOriginal
          ? "Original application recovered. The proposed connection is not verified."
          : "Connection verified in the complete native readback.",
      );
      const actual = await peer.command("stats");
      expect(restores(actual.events)).toEqual(before);
      expect(actual.connections).toHaveLength(recoverOriginal ? 1 : 2);
      const retained = await (
        await request.get(
          "/api/bacnet/controller/native-application/receipts/" + receiptId,
        )
      ).json();
      expect(retained.result.status).toBe("unknown");
      expect(retained.latest_readback.status).toBe(
        recoverOriginal ? "recovered_original" : "verified",
      );
    } finally {
      peer.close();
    }
  });
}

test("local/controller mode retains the draft and retires the owned server review", async ({
  page,
  request,
}) => {
  const peer = await nativeDefaultPeer("consume", "connection");
  try {
    const { editor, transfer } = await open(page, peer.direct, false);
    await review(transfer);
    const downloading = page.waitForEvent("download");
    await transfer
      .getByRole("button", {
        name: "Save connection transfer review",
        exact: true,
      })
      .click();
    const original = JSON.parse(
      readFileSync((await (await downloading).path())!, "utf8"),
    );
    const cancelled = page.waitForResponse((r) =>
      r.url().endsWith("/native-application/cancel"),
    );
    await editor
      .getByLabel("Matching connection destination", { exact: true })
      .selectOption("file");
    await cancelled;
    await expect(
      editor.getByLabel("Unused native destination", { exact: true }),
    ).toHaveValue(d);
    await expect(
      editor.getByRole("button", {
        name: "Review saved connection compilation",
        exact: true,
      }),
    ).toBeVisible();
    await editor
      .getByLabel("Matching connection destination", { exact: true })
      .selectOption("controller");
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
    const token = (await (await request.get("/api/session")).json()).token;
    const response = await request.post(
      "/api/bacnet/controller/native-application/matching-connection/transfer/apply",
      {
        headers: { "X-Studio-Token": token },
        data: {
          operation_id: "retired-connection-mode-review",
          token: original.token,
          review_sha256: original.review_sha256,
          connection_change_confirmed: true,
          application_transfer_confirmed: true,
        },
      },
    );
    expect(response.status(), await response.text()).toBe(422);
    expect((await response.json()).detail).toContain("already consumed");
    expect(restores((await peer.command("stats")).events)).toHaveLength(0);
  } finally {
    peer.close();
  }
});

test("closing the task retires review authority and keeps the local pair", async ({
  page,
}) => {
  const peer = await nativeDefaultPeer("consume", "connection");
  try {
    const { editor, transfer } = await open(page, peer.direct, false);
    await review(transfer);
    const cancelled = page.waitForResponse((r) =>
      r.url().endsWith("/native-application/cancel"),
    );
    await editor.locator(":scope > summary").click();
    await cancelled;
    await editor.locator(":scope > summary").click();
    await expect(
      editor.getByLabel("Unused native destination", { exact: true }),
    ).toHaveValue(d);
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
    expect(restores((await peer.command("stats")).events)).toHaveLength(0);
  } finally {
    peer.close();
  }
});

test("altered review is refused and cancelled before a restore", async ({
  page,
}) => {
  const peer = await nativeDefaultPeer("consume", "connection");
  try {
    const { transfer } = await open(page, peer.direct, false);
    await page.route(
      "**/matching-connection/transfer/preview",
      async (route) => {
        const response = await route.fetch({ maxRetries: 0 }),
          data = await response.json();
        data.connection_guard.configuration_sha256 = "f".repeat(64);
        await route.fulfill({ response, body: JSON.stringify(data) });
      },
    );
    const cancelled = page.waitForResponse((r) =>
      r.url().endsWith("/native-application/cancel"),
    );
    await transfer
      .getByRole("button", {
        name: "Review matching connection transfer",
        exact: true,
      })
      .click();
    await expect(transfer.getByRole("alert")).toContainText(
      "does not match this controller",
    );
    await cancelled;
    await expect(
      transfer.getByRole("button", {
        name: "Apply matching connection to controller",
        exact: true,
      }),
    ).toHaveCount(0);
    expect(restores((await peer.command("stats")).events)).toHaveLength(0);
  } finally {
    peer.close();
  }
});

for (const fault of ["edge", "operation"])
  test(`altered receipt ${fault} cannot claim verification and the original receipt can be loaded`, async ({
    page,
  }) => {
    const peer = await nativeDefaultPeer("consume", "connection");
    try {
      const { transfer } = await open(page, peer.direct, false);
      const apply = await review(transfer);
      let id = "";
      await page.route(
        "**/matching-connection/transfer/apply",
        async (route) => {
          const response = await route.fetch({ maxRetries: 0 }),
            data = await response.json();
          id = data.intent.id;
          if (fault === "edge")
            data.result.preservation.selected_connection.new[2]++;
          else data.intent.operation_id = "another-owned-apply";
          await route.fulfill({ response, body: JSON.stringify(data) });
        },
      );
      await apply.click();
      await expect(transfer).toContainText("Outcome is unconfirmed", {
        timeout: 20000,
      });
      await expect(
        transfer.getByRole("region", {
          name: "Matching connection transfer result",
          exact: true,
        }),
      ).toHaveCount(0);
      await transfer
        .getByRole("button", {
          name: "Refresh connection transfer status",
          exact: true,
        })
        .click();
      await transfer
        .getByText("Retained matching-connection receipts", { exact: true })
        .click();
      await transfer
        .getByLabel("Matching connection receipt", { exact: true })
        .selectOption(id);
      await transfer
        .getByRole("button", {
          name: "Load matching connection receipt",
          exact: true,
        })
        .click();
      await expect(
        transfer.getByRole("region", {
          name: "Matching connection transfer result",
          exact: true,
        }),
      ).toContainText("Connection verified in the complete native readback.");
      await expect(transfer).not.toContainText("Outcome is unconfirmed");
      expect(restores((await peer.command("stats")).events)).toHaveLength(1);
    } finally {
      peer.close();
    }
  });
