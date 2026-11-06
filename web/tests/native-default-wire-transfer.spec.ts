import { test, expect } from "./nativeScheduleWriteFixture";
import type { Page, Locator } from "@playwright/test";
import { nativeDefaultPeer } from "./native-default-peer";
import { freePort } from "./workflow-peer";
import {
  openNativeCompiler,
  expectWorkspaceNavigationLocked,
  chooseWorkspaceTask,
  chooseWorkspaceSurface,
} from "./workspace-navigation";

const ref = "controller/575_1",
  b = ref + ".2_11",
  c = ref + ".2_12";
async function open(
  page: Page,
  url: string,
  peer: { direct: string; router: string },
  routed: boolean,
) {
  await page.goto(url);
  await page.getByRole("button", { name: /^Connect to a controller/ }).click();
  await page
    .getByLabel("Local bind address / UDP port", { exact: true })
    .fill(`127.0.0.1:${await freePort()}`);
  await page
    .getByRole("button", { name: "Open interface", exact: true })
    .click();
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
    .getByRole("region", { name: "Known controller connection" })
    .getByRole("button", { name: "Open controller", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Controller overview" }),
  ).toContainText("Authored native wire controller");
  await openNativeCompiler(page);
  const realTransfer = page.getByRole("region", {
    name: "Native default controller transfer",
    exact: true,
  });
  await realTransfer
    .getByText("Native backup and restore credentials", { exact: true })
    .click();
  await realTransfer
    .getByLabel("Native backup credential", { exact: true })
    .fill("authored-backup");
  await realTransfer
    .getByLabel("Native restore credential", { exact: true })
    .fill("authored-restore");
  await realTransfer
    .getByRole("button", {
      name: "Save native transfer credentials",
      exact: true,
    })
    .click();
  await realTransfer
    .getByRole("button", { name: "Read current native backup", exact: true })
    .click();
  const parent = page.getByRole("region", {
    name: "Native backup default compiler",
    exact: true,
  });
  await expect(
    parent.getByLabel("Native compiler snapshot source", { exact: true }),
  ).toContainText("5 saved application parameters");
  await parent
    .getByLabel("Native Real default", { exact: true })
    .selectOption(c);
  await parent
    .getByLabel("Proposed native Real default", { exact: true })
    .fill("0.1");
  const copy = parent.getByLabel("Combined native default and connection", {
    exact: true,
  });
  await copy.locator(":scope > summary").click();
  await copy
    .getByRole("button", { name: "Open combined compiler", exact: true })
    .click();
  await copy
    .getByRole("button", { name: "Inspect combined connection", exact: true })
    .click();
  await copy
    .getByLabel("Combined replacement source", { exact: true })
    .selectOption(b);
  const transfer = copy.getByRole("region", {
    name: "Native combined controller transfer",
    exact: true,
  });
  await expect(transfer).toBeVisible();
  await expect(realTransfer).toBeHidden();
  return { parent, copy, transfer };
}
async function review(transfer: Locator) {
  await transfer
    .getByRole("button", {
      name: "Review controller combined transfer",
      exact: true,
    })
    .click();
  const result = transfer.getByRole("region", {
    name: "Reviewed controller combined transfer",
    exact: true,
  });
  await expect(result).toBeVisible();
  await expect(result).toContainText("3.5 to 0.10000000149011612");
  return result;
}
async function confirm(result: Locator) {
  const apply = result.getByRole("button", {
    name: "Apply native default and connection to controller",
    exact: true,
  });
  await expect(apply).toBeDisabled();
  await result
    .getByLabel(
      "I confirm the selected controller, proposed Real default and connection source.",
      { exact: true },
    )
    .check();
  await expect(apply).toBeDisabled();
  await result
    .getByLabel(
      "I confirm the application transfer and controller interruption.",
      { exact: true },
    )
    .check();
  await expect(apply).toBeEnabled();
  return apply;
}

async function applyAndWait(page: Page, result: Locator) {
  const apply = await confirm(result);
  const finished = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url().endsWith("/default-wire/transfer/apply"),
  );
  await apply.click();
  return finished;
}

for (const routed of [false, true])
  test(`combined ${routed ? "routed" : "direct"} web transfer preserves fresh settings and verifies both edits once`, async ({
    page,
    nativeScheduleWriteServer,
  }, info) => {
    const peer = await nativeDefaultPeer("consume", "default-wire-transfer");
    try {
      const { transfer } = await open(
        page,
        nativeScheduleWriteServer.url,
        peer,
        routed,
      );
      const result = await review(transfer);
      await peer.command("combined-other-fresh");
      const apply = await confirm(result);
      const finished = page.waitForResponse(
        (response) =>
          response.request().method() === "POST" &&
          response.url().endsWith("/default-wire/transfer/apply"),
      );
      await apply.click();
      await expectWorkspaceNavigationLocked(page);
      expect((await finished).ok()).toBe(true);
      const outcome = transfer.getByRole("region", {
        name: "Native combined transfer outcome",
        exact: true,
      });
      await expect(
        outcome.getByRole("heading", {
          name: "Verified native combined transfer",
          exact: true,
        }),
      ).toBeVisible();
      await expect(outcome).toContainText(
        "Native application bytes and effective saved settings verified.",
      );
      const stats = await peer.command("stats");
      expect(stats.source_default).toBe(45);
      expect(stats.other_default).toBe(17);
      expect(stats.combined_real_bits).toBe("3dcccccd");
      expect(stats.connections[0].source_ref).toBe(b);
      expect(
        stats.events.filter(
          (e: any) => e[0] === "state" && e[1] === "start-restore",
        ),
      ).toHaveLength(1);
      expect(
        stats.events.filter(
          (e: any) => e[0] === "state" && e[1] === "end-restore",
        ),
      ).toHaveLength(1);
      expect(stats.router_errors).toEqual([]);
      await outcome.scrollIntoViewIfNeeded();
      await page.screenshot({
        path: info.outputPath("combined-transfer-verified.png"),
      });
    } finally {
      peer.close();
    }
  });

for (const fault of ["combined-selected9", "combined-config2"])
  test(`${fault} changed after review refuses the web transfer without a restore`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const peer = await nativeDefaultPeer("consume", "default-wire-transfer");
    try {
      const { transfer } = await open(
        page,
        nativeScheduleWriteServer.url,
        peer,
        true,
      );
      const result = await review(transfer);
      await peer.command(fault);
      expect((await applyAndWait(page, result)).ok()).toBe(true);
      await expect(
        transfer.getByRole("heading", {
          name: "Native combined transfer not sent",
          exact: true,
        }),
      ).toBeVisible();
      const stats = await peer.command("stats");
      expect(
        stats.events.filter(
          (e: any) =>
            e[0] === "write" || (e[0] === "state" && e[1].includes("restore")),
        ),
      ).toEqual([]);
    } finally {
      peer.close();
    }
  });

test("stopping a held controller review cancels its token without a restore", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const peer = await nativeDefaultPeer("consume", "default-wire-transfer");
  let release = () => {};
  try {
    const { parent, transfer } = await open(
      page,
      nativeScheduleWriteServer.url,
      peer,
      true,
    );
    let started!: () => void, complete!: () => void;
    const received = new Promise<void>((r) => (started = r)),
      gate = new Promise<void>((r) => (release = r)),
      delivered = new Promise<void>((r) => (complete = r));
    let token = "",
      digest = "";
    await page.route(
      "**/default-wire/transfer/preview",
      async (route) => {
        const response = await route.fetch({ maxRetries: 0 });
        const data = await response.json();
        token = data.token;
        digest = data.review_sha256;
        started();
        await gate;
        await route.fulfill({ response });
        complete();
      },
      { times: 1 },
    );
    await transfer
      .getByRole("button", {
        name: "Review controller combined transfer",
        exact: true,
      })
      .click();
    await received;
    await transfer
      .getByRole("button", { name: "Stop native operation", exact: true })
      .click();
    release();
    await delivered;
    await expect(
      parent.getByLabel("Proposed native Real default", { exact: true }),
    ).toBeEnabled();
    await expect(
      transfer.getByRole("region", {
        name: "Reviewed controller combined transfer",
        exact: true,
      }),
    ).toHaveCount(0);
    const response = await page.request.post(
      nativeScheduleWriteServer.url +
        "/api/bacnet/controller/native-application/default-wire/transfer/apply",
      {
        headers: {
          "X-Studio-Token": (
            await (
              await page.request.get(
                nativeScheduleWriteServer.url + "/api/session",
              )
            ).json()
          ).token,
        },
        data: {
          operation_id: "cancelled-held-combined-review",
          token,
          review_sha256: digest,
          default_change_confirmed: true,
          wire_change_confirmed: true,
          application_transfer_confirmed: true,
        },
      },
    );
    expect(response.status()).toBe(422);
    expect(
      (await peer.command("stats")).events.filter((e: any) => e[0] === "write"),
    ).toEqual([]);
  } finally {
    release();
    peer.close();
  }
});

test("lost commit acknowledgement reloads its durable receipt and reads back without a second restore", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const peer = await nativeDefaultPeer("consume", "default-wire-transfer");
  try {
    const { transfer } = await open(
      page,
      nativeScheduleWriteServer.url,
      peer,
      true,
    );
    const result = await review(transfer);
    await peer.command("mode drop-end");
    expect((await applyAndWait(page, result)).ok()).toBe(true);
    await expect(
      transfer.getByRole("heading", {
        name: "Native combined transfer outcome uncertain",
        exact: true,
      }),
    ).toBeVisible();
    const before = await peer.command("stats");
    await peer.command("mode normal");
    await transfer
      .getByRole("button", {
        name: "Refresh transfer receipts",
        exact: true,
      })
      .click();
    await transfer.getByRole("button", { name: /^Open receipt / }).click();
    const finished = page.waitForResponse(
      (r) =>
        r.request().method() === "POST" &&
        r.url().endsWith("/native-application/readback"),
    );
    await transfer
      .getByRole("button", {
        name: "Read back native combined transfer",
        exact: true,
      })
      .click();
    expect((await finished).ok()).toBe(true);
    await expect(
      transfer.getByRole("heading", {
        name: "Verified native combined transfer",
        exact: true,
      }),
    ).toBeVisible();
    const after = await peer.command("stats");
    expect(
      after.events.filter(
        (e: any) =>
          e[0] === "write" || (e[0] === "state" && e[1].includes("restore")),
      ),
    ).toEqual(
      before.events.filter(
        (e: any) =>
          e[0] === "write" || (e[0] === "state" && e[1].includes("restore")),
      ),
    );
  } finally {
    peer.close();
  }
});

test("coalesced default A B A retires a completed controller review", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const peer = await nativeDefaultPeer("consume", "default-wire-transfer");
  try {
    const { parent, transfer } = await open(
      page,
      nativeScheduleWriteServer.url,
      peer,
      false,
    );
    await review(transfer);
    await parent
      .getByLabel("Proposed native Real default", { exact: true })
      .evaluate((element: HTMLInputElement) => {
        const set = Object.getOwnPropertyDescriptor(
          HTMLInputElement.prototype,
          "value",
        )!.set!;
        for (const value of ["2", "0.1"]) {
          set.call(element, value);
          element.dispatchEvent(new Event("input", { bubbles: true }));
        }
      });
    await expect(
      transfer.getByRole("region", {
        name: "Reviewed controller combined transfer",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      parent.getByLabel("Proposed native Real default", { exact: true }),
    ).toHaveValue("0.1");
    await review(transfer);
    expect(
      (await peer.command("stats")).events.filter((e: any) => e[0] === "write"),
    ).toEqual([]);
  } finally {
    peer.close();
  }
});

test("coalesced connection source A B A retires a completed controller review", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const peer = await nativeDefaultPeer("consume", "default-wire-transfer");
  try {
    const { copy, transfer } = await open(
      page,
      nativeScheduleWriteServer.url,
      peer,
      false,
    );
    await review(transfer);
    await copy
      .getByLabel("Combined replacement source", { exact: true })
      .evaluate(
        (element: HTMLSelectElement, values) => {
          const set = Object.getOwnPropertyDescriptor(
            HTMLSelectElement.prototype,
            "value",
          )!.set!;
          for (const value of values) {
            set.call(element, value);
            element.dispatchEvent(new Event("change", { bubbles: true }));
          }
        },
        [ref + ".2_10", b],
      );
    await expect(
      transfer.getByRole("region", {
        name: "Reviewed controller combined transfer",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      copy.getByLabel("Combined replacement source", { exact: true }),
    ).toHaveValue(b);
    await review(transfer);
    expect(
      (await peer.command("stats")).events.filter((e: any) => e[0] === "write"),
    ).toEqual([]);
  } finally {
    peer.close();
  }
});

test("compact combined task keeps its draft and retires review when closed", async ({
  page,
  nativeScheduleWriteServer,
}, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const peer = await nativeDefaultPeer("consume", "default-wire-transfer");
  try {
    const { parent, copy, transfer } = await open(
      page,
      nativeScheduleWriteServer.url,
      peer,
      true,
    );
    const result = await review(transfer);
    await result.scrollIntoViewIfNeeded();
    await page.screenshot({
      path: testInfo.outputPath("combined-review-phone.png"),
    });
    await copy.locator(":scope > summary").click();
    await expect(transfer).toBeHidden();
    await expect(
      parent.getByRole("region", {
        name: "Native default controller transfer",
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      parent.getByLabel("Proposed native Real default", { exact: true }),
    ).toHaveValue("0.1");
    await copy.locator(":scope > summary").click();
    await expect(
      copy.getByLabel("Combined replacement source", { exact: true }),
    ).toHaveValue(b);
    await expect(
      transfer.getByRole("region", {
        name: "Reviewed controller combined transfer",
        exact: true,
      }),
    ).toHaveCount(0);
    await review(transfer);
    expect(
      (await peer.command("stats")).events.filter((e: any) => e[0] === "write"),
    ).toEqual([]);
  } finally {
    peer.close();
  }
});

test("a verified combined change appears in Changes and History as reference-only evidence", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const peer = await nativeDefaultPeer("consume", "default-wire-transfer");
  try {
    const { transfer } = await open(
      page,
      nativeScheduleWriteServer.url,
      peer,
      true,
    );
    const result = await review(transfer);
    expect((await applyAndWait(page, result)).ok()).toBe(true);
    await expect(
      transfer.getByRole("heading", {
        name: "Verified native combined transfer",
        exact: true,
      }),
    ).toBeVisible();
    const before = await peer.command("stats");
    for (const location of ["Changes", "History"]) {
      if (location === "Changes") await chooseWorkspaceTask(page, "Changes");
      else {
        await chooseWorkspaceSurface(page, "History");
        const tools = page.getByRole("navigation", {
          name: "history tools",
          exact: true,
        });
        const select = tools.getByRole("combobox");
        if (await select.isVisible())
          await select.selectOption({ label: "Recorded changes" });
        else
          await tools
            .getByRole("button", { name: "Recorded changes", exact: true })
            .click();
      }
      const ledger = page.getByRole("region", {
        name: "Recorded changes",
        exact: true,
      });
      await page
        .getByLabel("Record family", { exact: true })
        .selectOption("native");
      const rows = ledger
        .getByRole("row")
        .filter({ hasText: "Native Real default and connection transfer" });
      await expect(rows).toHaveCount(1);
      await rows.getByRole("button", { name: /^Details for native / }).click();
      const detail = page.getByRole("region", {
        name: "Recorded combined native edit",
        exact: true,
      });
      await expect(detail).toContainText("3.5 to 0.10000000149011612");
      await expect(detail).toContainText(
        "Current source and controller state are not revalidated",
      );
      await expect(detail).toContainText(b);
      const close = page.getByRole("button", {
        name: "Close evidence",
        exact: true,
      });
      await close.click();
    }
    const after = await peer.command("stats");
    expect(after.request_types).toEqual(before.request_types);
  } finally {
    peer.close();
  }
});
