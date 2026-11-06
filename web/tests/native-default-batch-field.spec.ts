import { test, expect } from "./nativeScheduleWriteFixture";
import type { Page, Locator } from "@playwright/test";
import { nativeDefaultPeer } from "./native-default-peer";
import { freePort } from "./workflow-peer";
import { openNativeCompiler } from "./workspace-navigation";
import { inspect, record } from "./native-boolean-fixture";

async function connected(page: Page, endpoint: string, boolean: boolean) {
  await page.goto("/");
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
    .fill(endpoint);
  await page
    .getByLabel("Known Device object", { exact: true })
    .fill("device,5136");
  await page
    .getByRole("region", { name: "Known controller connection", exact: true })
    .getByRole("button", { name: "Open controller", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Controller overview", exact: true }),
  ).toContainText("Authored controller");
  await openNativeCompiler(page);
  const compiler = page.getByRole("region", {
    name: "Native backup default compiler",
    exact: true,
  });
  const shared = compiler.getByRole("region", {
    name: "Native default controller transfer",
    exact: true,
  });
  await shared
    .getByText("Native backup and restore credentials", { exact: true })
    .click();
  await shared
    .getByLabel("Native backup credential", { exact: true })
    .fill("authored-backup");
  await shared
    .getByLabel("Native restore credential", { exact: true })
    .fill("authored-restore");
  await shared
    .getByRole("button", {
      name: "Save native transfer credentials",
      exact: true,
    })
    .click();
  await expect(
    shared.getByLabel("Native backup credential", { exact: true }),
  ).toHaveValue("");
  await shared
    .getByRole("button", { name: "Read current native backup", exact: true })
    .click();
  await expect(
    compiler.getByLabel("Native compiler snapshot source", { exact: true }),
  ).toContainText(
    boolean
      ? "11 saved application parameters"
      : "9 saved application parameters",
  );
  await compiler
    .getByLabel("Native Real default", { exact: true })
    .selectOption("controller/signal-10");
  if (!boolean) {
    await compiler
      .getByLabel("Proposed native Real default", { exact: true })
      .fill("0.1");
    return { compiler, panel: shared };
  }
  const { records } = await inspect(compiler);
  await record(records);
  await records
    .getByLabel("Boolean default source", { exact: true })
    .selectOption("effective");
  await records
    .getByRole("button", { name: "Open saved Boolean defaults", exact: true })
    .click();
  const editor = records.getByLabel("Effective Boolean default compilation", {
    exact: true,
  });
  await editor
    .getByLabel("Proposed effective Boolean default", { exact: true })
    .uncheck();
  return {
    compiler,
    panel: editor.getByRole("region", {
      name: "Native Boolean default controller transfer",
      exact: true,
    }),
  };
}
async function review(panel: Locator) {
  await panel
    .getByRole("button", {
      name: "Review controller default transfer",
      exact: true,
    })
    .click();
  const plan = panel.getByRole("region", {
    name: "Reviewed controller default transfer",
    exact: true,
  });
  await expect(plan).toBeVisible();
  await plan
    .getByRole("checkbox", {
      name: "I confirm the selected controller, native default and proposed value.",
      exact: true,
    })
    .check();
  await plan
    .getByRole("checkbox", {
      name: "I confirm the application transfer and controller interruption.",
      exact: true,
    })
    .check();
  const apply = plan.getByRole("button", {
    name: "Apply native default to controller",
    exact: true,
  });
  await expect(apply).toBeEnabled();
  return { plan, apply };
}
for (const boolean of [false, true])
  test(`batch open-close retires an existing ${boolean ? "Boolean context" : "Real"} Apply before paint without a restore`, async ({
    page,
    request,
  }) => {
    const peer = await nativeDefaultPeer(
      "consume",
      boolean ? "boolean" : "real",
    );
    const headers = {
      "X-Studio-Token": (await (await request.get("/api/session")).json())
        .token,
    };
    try {
      const { compiler, panel } = await connected(page, peer.direct, boolean),
        { plan, apply } = await review(panel);
      const old = await apply.elementHandle();
      let posts = 0;
      page.on("request", (r) => {
        if (r.method() === "POST" && r.url().endsWith("/transfer/apply"))
          posts++;
      });
      const batch = compiler.getByLabel("Native typed default batch", {
        exact: true,
      });
      await batch.locator(":scope > summary").evaluate((summary, old) => {
        (summary as HTMLElement).click();
        (summary as HTMLElement).click();
        (old as HTMLElement).click();
      }, old);
      await expect(batch).not.toHaveAttribute("open", "");
      await expect(plan).toHaveCount(0);
      expect(posts).toBe(0);
      const mutations = (await peer.command("stats")).events.filter(
        (e: any) =>
          e[0] === "write" || (e[0] === "state" && e[1].includes("restore")),
      );
      expect(mutations).toEqual([]);
      await review(panel);
      expect(posts).toBe(0);
      expect(
        (await peer.command("stats")).events.filter(
          (e: any) =>
            e[0] === "write" || (e[0] === "state" && e[1].includes("restore")),
        ),
      ).toEqual([]);
    } finally {
      await request.post("/api/bacnet/disconnect", { headers, data: {} });
      peer.close();
    }
  });

test("an owned native transfer keeps the batch switch locked and completes one restore", async ({
  page,
  request,
}) => {
  const peer = await nativeDefaultPeer(),
    headers = {
      "X-Studio-Token": (await (await request.get("/api/session")).json())
        .token,
    };
  let release = () => {};
  const gate = new Promise<void>((resolve) => (release = resolve));
  let held = false;
  let completed!: (receipt: any) => void;
  const applied = new Promise<any>((resolve) => (completed = resolve));
  try {
    const { compiler, panel } = await connected(page, peer.direct, false),
      { apply } = await review(panel);
    await page.route("**/transfer/apply", async (route) => {
      held = true;
      await gate;
      const response = await route.fetch({ maxRetries: 0 });
      const receipt = await response.json();
      await route.fulfill({ response });
      completed(receipt);
    });
    await apply.click();
    await expect.poll(() => held).toBe(true);
    const batch = compiler.getByLabel("Native typed default batch", {
        exact: true,
      }),
      summary = batch.locator(":scope > summary");
    await expect(summary).toHaveAttribute("aria-disabled", "true");
    // Exercise admission even if an old DOM activation bypasses the visual lock.
    await summary.evaluate((e) => (e as HTMLElement).click());
    await expect(batch).not.toHaveAttribute("open", "");
    release();
    const receipt = await applied;
    expect(receipt.result.status, JSON.stringify(receipt)).toBe("verified");
    expect(receipt.pending).toBe(false);
    await expect(
      panel.getByRole("region", {
        name: "Native default transfer outcome",
        exact: true,
      }),
    ).toContainText("Verified native default transfer");
    const events = (await peer.command("stats")).events;
    expect(
      events.filter((e: any) => e[0] === "state" && e[1] === "start-restore"),
    ).toHaveLength(1);
    expect(
      events.filter((e: any) => e[0] === "write").every((e: any) => e[1] === 3),
    ).toBe(true);
    await expect(
      compiler
        .getByLabel("Native typed default batch", { exact: true })
        .locator(":scope > summary"),
    ).toHaveAttribute("aria-disabled", "false");
  } finally {
    release();
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    peer.close();
  }
});
