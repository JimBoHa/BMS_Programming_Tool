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

for (const routed of [false, true])
  test(`${routed ? "routed phone" : "direct desktop"} transfers all selected types once and exports the exact receipt`, async ({
    page,
    request,
  }, info) => {
    const peer = await nativeDefaultPeer("consume", "default-batch");
    let headers: Record<string, string> = {};
    try {
      if (routed) await page.setViewportSize({ width: 390, height: 844 });
      const { batch, transfer } = await open(page, "/", peer, routed);
      headers = {
        "X-Studio-Token": (await (await request.get("/api/session")).json())
          .token,
      };
      const { apply } = await review(transfer);
      await expect(
        transfer.getByRole("table", {
          name: "Reviewed typed default values",
          exact: true,
        }),
      ).toContainText("0.10000000149011612");
      await page.screenshot({
        path: info.outputPath("typed-batch-review.png"),
        fullPage: true,
      });
      await peer.command("batch-other-fresh");
      const response = page.waitForResponse(
        (r) =>
          r.request().method() === "POST" &&
          r.url().endsWith("/default-batch/transfer/apply"),
      );
      await apply.click();
      await (await response).finished();
      await expect(
        transfer.getByRole("region", {
          name: "Typed default batch transfer result",
          exact: true,
        }),
      ).toContainText("Every selected typed default verified");
      const status = await (
        await request.get("/api/bacnet/controller/native-application/status")
      ).json();
      const row = status.receipts.find(
        (r: any) => r.change_kind === "default-batch",
      );
      const receipt = await (
        await request.get(
          "/api/bacnet/controller/native-application/receipts/" + row.id,
        )
      ).json();
      expect(receipt.result.status).toBe("verified");
      expect(receipt.pending).toBe(false);
      expect(receipt.result.preservation.selected_defaults).toHaveLength(4);
      const stats = await peer.command("stats");
      expect(
        stats.events.filter(
          (e: any) => e[0] === "state" && e[1] === "start-restore",
        ),
      ).toHaveLength(1);
      expect(stats.router_errors).toEqual([]);
      const download = page.waitForEvent("download");
      await transfer
        .getByRole("button", {
          name: "Save batch transfer receipt",
          exact: true,
        })
        .click();
      const bytes = await readFile((await (await download).path())!);
      expect(JSON.parse(bytes.toString())).toEqual(receipt);
      await page.screenshot({
        path: info.outputPath("typed-batch-transfer.png"),
        fullPage: true,
      });
      await batch.locator(":scope > summary").click();
      await batch.locator(":scope > summary").click();
      await expect(
        batch.getByLabel(`Proposed real value for ${c}`, { exact: true }),
      ).toHaveValue("0.1");
    } finally {
      if (headers["X-Studio-Token"])
        await request.post("/api/bacnet/disconnect", { headers, data: {} });
      peer.close();
    }
  });

for (const mode of ["draft", "task", "visibility"])
  test(`coalesced ${mode} ABA retires the original batch Apply handler`, async ({
    page,
    request,
  }) => {
    const peer = await nativeDefaultPeer("consume", "default-batch");
    let headers: Record<string, string> = {};
    try {
      const { batch, task, transfer } = await open(page, "/", peer, false);
      headers = {
        "X-Studio-Token": (await (await request.get("/api/session")).json())
          .token,
      };
      const { apply, plan } = await review(transfer),
        old = await apply.elementHandle();
      let posts = 0;
      page.on("request", (r) => {
        if (
          r.method() === "POST" &&
          r.url().endsWith("/default-batch/transfer/apply")
        )
          posts++;
      });
      if (mode === "draft") {
        await batch
          .getByLabel(`Proposed real value for ${c}`, { exact: true })
          .evaluate((input, old) => {
            const setter = Object.getOwnPropertyDescriptor(
              HTMLInputElement.prototype,
              "value",
            )!.set!;
            for (const value of ["9", "0.1"]) {
              setter.call(input, value);
              input.dispatchEvent(new Event("input", { bubbles: true }));
            }
            (old as HTMLElement).click();
          }, old);
      } else if (mode === "task") {
        await task.locator(":scope > summary").evaluate((summary, old) => {
          (summary as HTMLElement).click();
          (summary as HTMLElement).click();
          (old as HTMLElement).click();
        }, old);
      } else
        await page.evaluate((old) => {
          document.dispatchEvent(new Event("visibilitychange"));
          (old as HTMLElement).click();
        }, old);
      await expect(plan).toHaveCount(0);
      expect(posts).toBe(0);
      const stats = await peer.command("stats");
      expect(
        stats.events.filter(
          (e: any) =>
            e[0] === "write" || (e[0] === "state" && e[1].includes("restore")),
        ),
      ).toEqual([]);
      await expect(
        batch.getByLabel(`Proposed real value for ${c}`, { exact: true }),
      ).toHaveValue("0.1");
    } finally {
      if (headers["X-Studio-Token"])
        await request.post("/api/bacnet/disconnect", { headers, data: {} });
      peer.close();
    }
  });

test("an owned batch Apply locks tasks and navigation through one completed restore", async ({
  page,
  request,
}) => {
  const peer = await nativeDefaultPeer("consume", "default-batch");
  let headers: Record<string, string> = {},
    release = () => {},
    held = false;
  const gate = new Promise<void>((resolve) => (release = resolve));
  let finish!: (receipt: any) => void;
  const completed = new Promise<any>((resolve) => (finish = resolve));
  try {
    const { batch, task, transfer } = await open(page, "/", peer, false);
    headers = {
      "X-Studio-Token": (await (await request.get("/api/session")).json())
        .token,
    };
    const { apply } = await review(transfer);
    await page.route("**/default-batch/transfer/apply", async (route) => {
      held = true;
      await gate;
      const response = await route.fetch({ maxRetries: 0 });
      const receipt = await response.json();
      await route.fulfill({ response });
      finish(receipt);
    });
    await apply.click();
    await expect.poll(() => held).toBe(true);
    await expectWorkspaceNavigationLocked(page);
    await expect(batch.locator(":scope > summary")).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    await expect(
      batch.getByLabel(`Proposed real value for ${c}`, { exact: true }),
    ).toBeDisabled();
    await task
      .locator(":scope > summary")
      .evaluate((e) => (e as HTMLElement).click());
    await expect(task).toHaveAttribute("open", "");
    release();
    const receipt = await completed;
    expect(receipt.result.status).toBe("verified");
    await expect(
      transfer.getByRole("region", {
        name: "Typed default batch transfer result",
        exact: true,
      }),
    ).toContainText("Every selected typed default verified");
    expect(
      (await peer.command("stats")).events.filter(
        (e: any) => e[0] === "state" && e[1] === "start-restore",
      ),
    ).toHaveLength(1);
  } finally {
    release();
    if (held) await completed;
    if (headers["X-Studio-Token"])
      await request.post("/api/bacnet/disconnect", { headers, data: {} });
    peer.close();
  }
});

test("a lost browser acknowledgement loads the original verified receipt without a second restore", async ({
  page,
  request,
}) => {
  const peer = await nativeDefaultPeer("consume", "default-batch");
  let headers: Record<string, string> = {},
    sent = false;
  let finish!: (receipt: any) => void;
  const completed = new Promise<any>((resolve) => (finish = resolve));
  try {
    const { transfer } = await open(page, "/", peer, false);
    headers = {
      "X-Studio-Token": (await (await request.get("/api/session")).json())
        .token,
    };
    const { apply } = await review(transfer);
    await page.route("**/default-batch/transfer/apply", async (route) => {
      sent = true;
      const response = await route.fetch({ maxRetries: 0 }),
        receipt = await response.json();
      await route.abort("failed");
      finish(receipt);
    });
    await apply.click();
    const receipt = await completed;
    expect(receipt.result.status).toBe("verified");
    await expect(
      transfer.getByRole("alert").filter({ hasText: "Outcome is unconfirmed" }),
    ).toBeVisible();
    await transfer
      .getByText("Retained default-batch receipts", { exact: true })
      .click();
    await transfer
      .getByLabel("Typed default batch receipt", { exact: true })
      .selectOption(receipt.intent.id);
    await transfer
      .getByRole("button", { name: "Load default batch receipt", exact: true })
      .click();
    await expect(
      transfer.getByRole("region", {
        name: "Typed default batch transfer result",
        exact: true,
      }),
    ).toContainText("Every selected typed default verified");
    await expect(
      transfer.getByRole("alert").filter({ hasText: "Outcome is unconfirmed" }),
    ).toHaveCount(0);
    expect(
      (await peer.command("stats")).events.filter(
        (e: any) => e[0] === "state" && e[1] === "start-restore",
      ),
    ).toHaveLength(1);
  } finally {
    if (sent) await completed;
    if (headers["X-Studio-Token"])
      await request.post("/api/bacnet/disconnect", { headers, data: {} });
    peer.close();
  }
});

test("a lost native commit acknowledgement retains uncertainty and readback resolves without replay", async ({
  page,
  request,
}) => {
  const peer = await nativeDefaultPeer("drop-end", "default-batch");
  let headers: Record<string, string> = {};
  try {
    const { transfer } = await open(page, "/", peer, false);
    headers = {
      "X-Studio-Token": (await (await request.get("/api/session")).json())
        .token,
    };
    const { apply } = await review(transfer);
    const response = page.waitForResponse(
      (r) =>
        r.request().method() === "POST" &&
        r.url().endsWith("/default-batch/transfer/apply"),
    );
    await apply.click();
    await (await response).finished();
    const result = transfer.getByRole("region", {
      name: "Typed default batch transfer result",
      exact: true,
    });
    await expect(result).toContainText("Batch outcome uncertain");
    const before = (await peer.command("stats")).events.filter(
      (e: any) =>
        e[0] === "write" || (e[0] === "state" && e[1].includes("restore")),
    );
    await peer.command("mode normal");
    const readback = page.waitForResponse(
      (r) =>
        r.request().method() === "POST" &&
        r.url().endsWith("/native-application/readback"),
    );
    await transfer
      .getByRole("button", { name: "Read back default batch", exact: true })
      .click();
    await (await readback).finished();
    await expect(result).toContainText("Every selected typed default verified");
    expect(
      (await peer.command("stats")).events.filter(
        (e: any) =>
          e[0] === "write" || (e[0] === "state" && e[1].includes("restore")),
      ),
    ).toEqual(before);
  } finally {
    if (headers["X-Studio-Token"])
      await request.post("/api/bacnet/disconnect", { headers, data: {} });
    peer.close();
  }
});
