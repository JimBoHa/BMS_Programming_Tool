import { test, expect } from "./nativeScheduleWriteFixture";
import type { Page, Locator } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { nativeDefaultPeer } from "./native-default-peer";
import { freePort } from "./workflow-peer";
import {
  openNativeCompiler,
  expectWorkspaceNavigationLocked,
} from "./workspace-navigation";
const c = "controller/575_1.2_12";
test.describe.configure({ timeout: 60000 });
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
  ).toContainText("Authored native wire controller");
  await parent
    .getByLabel("Native Real default", { exact: true })
    .selectOption(c);
  const batch = parent.getByLabel("Native typed default batch", {
    exact: true,
  });
  await batch.locator(":scope > summary").click();
  await expect(
    batch.getByRole("table", {
      name: "Native batch default fields",
      exact: true,
    }),
  ).toBeVisible();
  const changes = [
    [c, "real", "0.1"],
    ["controller/575_1.2_13", "real", "-0"],
    ["controller/retained-boolean", "boolean", "false"],
    ["controller/saved-enum", "enum", "65535"],
  ];
  for (const [ref, kind, value] of changes) {
    await batch.getByLabel(`Include ${ref} in batch`, { exact: true }).check();
    if (kind === "boolean")
      await batch
        .getByLabel(`Proposed Boolean for ${ref}`, { exact: true })
        .uncheck();
    else
      await batch
        .getByLabel(`Proposed ${kind} value for ${ref}`, { exact: true })
        .fill(value);
  }
  const task = batch.getByLabel("Default batch field workflow", {
    exact: true,
  });
  await task.locator(":scope > summary").click();
  const transfer = task.getByRole("region", {
    name: "Native default batch controller transfer",
    exact: true,
  });
  await expect(
    transfer.getByRole("button", {
      name: "Review default batch transfer",
      exact: true,
    }),
  ).toBeEnabled();
  return { parent, batch, task, transfer };
}
async function review(transfer: Locator) {
  await transfer
    .getByRole("button", { name: "Review default batch transfer", exact: true })
    .click();
  const plan = transfer.getByRole("region", {
    name: "Reviewed controller default batch",
    exact: true,
  });
  await expect(plan).toContainText("4 of 4");
  await plan.getByRole("checkbox").nth(0).check();
  await plan.getByRole("checkbox").nth(1).check();
  const apply = transfer.getByRole("button", {
    name: "Apply default batch to controller",
    exact: true,
  });
  await expect(apply).toBeEnabled();
  return { plan, apply };
}

async function prepareRecovery(
  page: Page,
  request: any,
  peer: any,
  routed: boolean,
  openField = true,
) {
  const { parent, transfer } = await open(page, "/", peer, routed);
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  const { apply } = await review(transfer);
  const initialResponse = page.waitForResponse(
    (r) =>
      r.request().method() === "POST" &&
      r.url().endsWith("/default-batch/transfer/apply"),
  );
  await apply.click();
  await (await initialResponse).finished();
  await expect(
    transfer.getByRole("region", {
      name: "Typed default batch transfer result",
      exact: true,
    }),
  ).toContainText("Every selected typed default verified");
  const status = await (
    await request.get("/api/bacnet/controller/native-application/status")
  ).json();
  const originalRow = status.receipts.find(
    (r: any) => r.change_kind === "default-batch" && !r.recovery_profile,
  );
  const original = await (
    await request.get(
      "/api/bacnet/controller/native-application/receipts/" + originalRow.id,
    )
  ).json();
  await transfer
    .getByRole("button", {
      name: "Open verified application snapshot",
      exact: true,
    })
    .click();
  await expect(
    parent.getByLabel("Retained native backup", { exact: true }),
  ).toHaveValue(original.result.verification_capture_id);
  await parent
    .getByRole("button", { name: "Open retained backup", exact: true })
    .click();
  const batch = parent.getByLabel("Native typed default batch", {
    exact: true,
  });
  if (!(await batch.evaluate((e) => (e as HTMLDetailsElement).open)))
    await batch.locator(":scope > summary").click();
  await expect(
    batch.getByRole("table", {
      name: "Native batch default fields",
      exact: true,
    }),
  ).toBeVisible();
  const task = batch.getByLabel("Default batch field workflow", {
    exact: true,
  });
  if (!(await task.evaluate((e) => (e as HTMLDetailsElement).open)))
    await task.locator(":scope > summary").click();
  const ordinary = task.getByRole("region", {
    name: "Native default batch controller transfer",
    exact: true,
  });
  const retained = ordinary.getByText("Retained default-batch receipts", {
    exact: true,
  });
  if (
    !(await retained.evaluate(
      (e) => (e.parentElement as HTMLDetailsElement).open,
    ))
  )
    await retained.click();
  await ordinary
    .getByLabel("Typed default batch receipt", { exact: true })
    .selectOption(originalRow.id);
  await ordinary
    .getByRole("button", {
      name: "Load default batch receipt",
      exact: true,
    })
    .click();
  const preparing = ordinary.getByRole("region", {
    name: "Previous typed batch defaults",
    exact: true,
  });
  await preparing
    .getByRole("button", {
      name: "Prepare previous batch defaults",
      exact: true,
    })
    .click();
  await expect(
    preparing.getByRole("table", {
      name: "Previous typed batch values",
      exact: true,
    }),
  ).toBeVisible();
  const field = preparing.getByLabel("Previous batch field workflow", {
    exact: true,
  });
  if (openField) await field.locator(":scope > summary").click();
  const recovery = field.getByRole("region", {
    name: "Previous batch controller transfer",
    exact: true,
  });
  if (openField)
    await expect(
      recovery.getByRole("button", {
        name: "Review previous batch recovery transfer",
        exact: true,
      }),
    ).toBeEnabled();

  return {
    parent,
    batch,
    task,
    ordinary,
    preparing,
    field,
    recovery,
    original,
    originalRow,
    headers,
  };
}

for (const routed of [false, true])
  test(`${routed ? "routed phone" : "direct desktop"} restores previous typed values through a separate fresh review`, async ({
    page,
    request,
  }, info) => {
    const peer = await nativeDefaultPeer("consume", "default-batch");
    let headers: Record<string, string> = {};
    try {
      if (routed) await page.setViewportSize({ width: 390, height: 844 });
      const {
        parent,
        ordinary,
        preparing,
        field,
        recovery,
        originalRow,
        headers: auth,
      } = await prepareRecovery(page, request, peer, routed);
      headers = auth;
      await recovery
        .getByRole("button", {
          name: "Review previous batch recovery transfer",
          exact: true,
        })
        .click();
      const reviewed = recovery.getByRole("region", {
        name: "Reviewed previous batch recovery",
        exact: true,
      });
      await expect(reviewed).toContainText("4 of 4");
      await reviewed.getByRole("checkbox").nth(0).check();
      await reviewed.getByRole("checkbox").nth(1).check();
      await peer.command("batch-other-fresh");
      const recoveryResponse = page.waitForResponse(
        (r) =>
          r.request().method() === "POST" &&
          r.url().endsWith("/default-batch/transfer/apply"),
      );
      await recovery
        .getByRole("button", {
          name: "Apply previous batch values to controller",
          exact: true,
        })
        .evaluate((element) => {
          const key = Object.keys(element).find((k) =>
            k.startsWith("__reactProps$"),
          )!;
          (window as any).__retiredRecoveryApply = (element as any)[
            key
          ].onClick;
        });
      await recovery
        .getByRole("button", {
          name: "Apply previous batch values to controller",
          exact: true,
        })
        .click();
      await (await recoveryResponse).finished();
      await expect(
        recovery.getByRole("region", {
          name: "Typed default batch transfer result",
          exact: true,
        }),
      ).toContainText("Every selected typed default verified");
      const retiredFetches = await page.evaluate(() => {
        const original = window.fetch;
        let posts = 0;
        window.fetch = ((input: any, init: any) => {
          if (String(input).endsWith("/default-batch/transfer/apply")) {
            posts++;
            return Promise.reject(
              new Error("Blocked retired recovery request"),
            );
          }
          return original(input, init);
        }) as typeof fetch;
        try {
          (window as any).__retiredRecoveryApply();
        } finally {
          window.fetch = original;
        }
        return posts;
      });
      expect(retiredFetches).toBe(0);
      const finalStatus = await (
        await request.get("/api/bacnet/controller/native-application/status")
      ).json();
      const row = finalStatus.receipts.find(
        (r: any) =>
          r.recovery_profile === "native-default-batch-recovery-transfer/1",
      );
      expect(row.recovery_parent_receipt).toBe(originalRow.id);
      const receipt = await (
        await request.get(
          "/api/bacnet/controller/native-application/receipts/" + row.id,
        )
      ).json();
      expect(receipt.result.status).toBe("verified");
      expect(receipt.intent.recovery_origin.parent_receipt_id).toBe(
        originalRow.id,
      );
      expect(
        receipt.result.preservation.selected_defaults.map(
          (r: any) => r.after_bits ?? r.after_value,
        ),
      ).toEqual(["40600000", "40800000", true, 513]);
      const stats = await peer.command("stats");
      expect(
        stats.events.filter(
          (e: any) => e[0] === "state" && e[1] === "start-restore",
        ),
      ).toHaveLength(2);
      expect(stats.router_errors).toEqual([]);
      const saving = page.waitForEvent("download");
      await recovery
        .getByRole("button", {
          name: "Save previous batch recovery receipt",
          exact: true,
        })
        .click();
      expect(
        JSON.parse((await readFile((await (await saving).path())!)).toString()),
      ).toEqual(receipt);
      await page.screenshot({
        path: info.outputPath("previous-batch-transfer.png"),
        fullPage: true,
      });
    } finally {
      await request.post("/api/bacnet/disconnect", { headers });
      await peer.close();
    }
  });

async function recoveryReview(recovery: Locator) {
  await recovery
    .getByRole("button", {
      name: "Review previous batch recovery transfer",
      exact: true,
    })
    .click();
  const reviewed = recovery.getByRole("region", {
    name: "Reviewed previous batch recovery",
    exact: true,
  });
  await expect(reviewed).toBeVisible();
  await reviewed.getByRole("checkbox").nth(0).check();
  await reviewed.getByRole("checkbox").nth(1).check();
  const apply = recovery.getByRole("button", {
    name: "Apply previous batch values to controller",
    exact: true,
  });
  await expect(apply).toBeEnabled();
  return { reviewed, apply };
}

test("coalesced recovery task focus retires an ordinary Apply and preserves its raw draft", async ({
  page,
  request,
}) => {
  const peer = await nativeDefaultPeer("consume", "default-batch");
  let headers: Record<string, string> = {};
  try {
    const {
      batch,
      ordinary,
      preparing,
      field,
      headers: auth,
    } = await prepareRecovery(page, request, peer, false, false);
    headers = auth;
    await batch
      .getByLabel("Include " + c + " in batch", { exact: true })
      .check();
    const draft = batch.getByLabel("Proposed real value for " + c, {
      exact: true,
    });
    await draft.fill("77");
    await ordinary
      .getByRole("button", {
        name: "Review default batch transfer",
        exact: true,
      })
      .click();
    const reviewed = ordinary.getByRole("region", {
      name: "Reviewed controller default batch",
      exact: true,
    });
    await expect(reviewed).toBeVisible();
    await reviewed.getByRole("checkbox").nth(0).check();
    await reviewed.getByRole("checkbox").nth(1).check();
    const old = await ordinary
      .getByRole("button", {
        name: "Apply default batch to controller",
        exact: true,
      })
      .elementHandle();
    await preparing
      .getByRole("button", {
        name: "Prepare previous batch defaults",
        exact: true,
      })
      .click();
    await expect(
      preparing.getByRole("table", {
        name: "Previous typed batch values",
        exact: true,
      }),
    ).toBeVisible();
    let posts = 0;
    page.on("request", (r) => {
      if (
        r.method() === "POST" &&
        r.url().endsWith("/default-batch/transfer/apply")
      )
        posts++;
    });
    await field.locator(":scope > summary").evaluate((summary, button) => {
      (summary as HTMLElement).click();
      (summary as HTMLElement).click();
      (button as HTMLElement).click();
    }, old);
    await expect(reviewed).toHaveCount(0);
    expect(posts).toBe(0);
    await expect(draft).toHaveValue("77");
    const stats = await peer.command("stats");
    expect(
      stats.events.filter(
        (e: any) => e[0] === "state" && e[1] === "start-restore",
      ),
    ).toHaveLength(1);
  } finally {
    await request.post("/api/bacnet/disconnect", { headers });
    await peer.close();
  }
});

for (const boundary of ["pagehide", "disclosure"])
  test(`${boundary} retires a recovery Apply before dispatch`, async ({
    page,
    request,
  }) => {
    const peer = await nativeDefaultPeer("consume", "default-batch");
    let headers: Record<string, string> = {};
    try {
      const {
        recovery,
        field,
        headers: auth,
      } = await prepareRecovery(page, request, peer, false);
      headers = auth;
      const { reviewed, apply } = await recoveryReview(recovery),
        old = await apply.elementHandle();
      let posts = 0;
      page.on("request", (r) => {
        if (
          r.method() === "POST" &&
          r.url().endsWith("/default-batch/transfer/apply")
        )
          posts++;
      });
      if (boundary === "pagehide")
        await page.evaluate((button) => {
          window.dispatchEvent(new Event("pagehide"));
          (button as HTMLElement).click();
        }, old);
      else
        await field.locator(":scope > summary").evaluate((summary, button) => {
          (summary as HTMLElement).click();
          (summary as HTMLElement).click();
          (button as HTMLElement).click();
        }, old);
      await expect(reviewed).toHaveCount(0);
      expect(posts).toBe(0);
      const stats = await peer.command("stats");
      expect(
        stats.events.filter(
          (e: any) => e[0] === "state" && e[1] === "start-restore",
        ),
      ).toHaveLength(1);
    } finally {
      await request.post("/api/bacnet/disconnect", { headers });
      await peer.close();
    }
  });

test("an uncertain routed recovery reloads and reads back without preparing or restoring again", async ({
  page,
  request,
}) => {
  const peer = await nativeDefaultPeer("consume", "default-batch");
  let headers: Record<string, string> = {};
  try {
    const {
      recovery,
      original,
      headers: auth,
    } = await prepareRecovery(page, request, peer, true);
    headers = auth;
    const { apply } = await recoveryReview(recovery);
    await peer.command("mode drop-end");
    const response = page.waitForResponse(
      (r) =>
        r.request().method() === "POST" &&
        r.url().endsWith("/default-batch/transfer/apply"),
    );
    await apply.click();
    await (await response).finished();
    await expect(
      recovery.getByRole("region", {
        name: "Typed default batch transfer result",
        exact: true,
      }),
    ).toContainText("Batch outcome uncertain");
    const status = await (
      await request.get("/api/bacnet/controller/native-application/status")
    ).json();
    const row = status.receipts.find(
      (r: any) =>
        r.recovery_profile === "native-default-batch-recovery-transfer/1" &&
        r.pending,
    );
    expect(row).toBeTruthy();
    const changes = (events: any[]) =>
      events.filter(
        (e) =>
          e[0] === "write" || (e[0] === "state" && e[1].includes("restore")),
      );
    const before = changes((await peer.command("stats")).events);
    await page.reload();
    await page
      .getByRole("button", { name: /^Connect to a controller/ })
      .click();
    await page
      .getByRole("button", { name: "Known controller address", exact: true })
      .click();
    await page
      .getByLabel("Known controller address", { exact: true })
      .fill("3001:7");
    await page
      .getByLabel("Known Device object", { exact: true })
      .fill("device,5136");
    await page.getByLabel("Known router", { exact: true }).fill(peer.router);
    await page.getByLabel("Known network", { exact: true }).fill("3001");
    await page
      .getByRole("region", { name: "Known controller connection" })
      .getByRole("button", { name: "Open controller", exact: true })
      .click();
    await openNativeCompiler(page);
    const parent = page.getByRole("region", {
      name: "Native backup default compiler",
      exact: true,
    });
    await parent
      .getByLabel("Retained native backup", { exact: true })
      .selectOption(original.intent.review_capture_id);
    await parent
      .getByRole("button", { name: "Open retained backup", exact: true })
      .click();
    const batch = parent.getByLabel("Native typed default batch", {
      exact: true,
    });
    await batch.locator(":scope > summary").click();
    await expect(
      batch.getByRole("table", {
        name: "Native batch default fields",
        exact: true,
      }),
    ).toBeVisible();
    const task = batch.getByLabel("Default batch field workflow", {
      exact: true,
    });
    await task.locator(":scope > summary").click();
    const transfer = task.getByRole("region", {
      name: "Native default batch controller transfer",
      exact: true,
    });
    await transfer
      .getByText("Retained default-batch receipts", { exact: true })
      .click();
    await transfer
      .getByLabel("Typed default batch receipt", { exact: true })
      .selectOption(row.id);
    await transfer
      .getByRole("button", { name: "Load default batch receipt", exact: true })
      .click();
    const result = transfer.getByRole("region", {
      name: "Typed default batch transfer result",
      exact: true,
    });
    await expect(result).toContainText("Batch outcome uncertain");
    await peer.command("mode normal");
    const checked = page.waitForResponse(
      (r) =>
        r.request().method() === "POST" &&
        r.url().endsWith("/native-application/readback"),
    );
    await transfer
      .getByRole("button", {
        name: "Read back previous batch recovery",
        exact: true,
      })
      .click();
    await (await checked).finished();
    await expect(result).toContainText("Every selected typed default verified");
    expect(changes((await peer.command("stats")).events)).toEqual(before);
  } finally {
    await request.post("/api/bacnet/disconnect", { headers });
    await peer.close();
  }
});
