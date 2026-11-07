import { test, expect } from "./nativeScheduleWriteFixture";
import type { Page } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { seedBatchRecovery } from "./native-default-batch-recovery-fixture";
import {
  openNativeCompiler,
  chooseWorkspaceTask,
} from "./workspace-navigation";

test("loading the same receipt again retires the previous report", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const data = seedBatchRecovery(nativeScheduleWriteServer.directory),
    { recovery, transfer } = await enter(page, data);
  await recovery
    .getByRole("button", {
      name: "Prepare previous batch defaults",
      exact: true,
    })
    .click();
  await expect(recovery.getByRole("table")).toBeVisible();
  await transfer
    .getByRole("button", { name: "Load default batch receipt", exact: true })
    .click();
  await expect(recovery.getByRole("table")).toHaveCount(0);
  await recovery
    .getByRole("button", {
      name: "Prepare previous batch defaults",
      exact: true,
    })
    .click();
  await expect(recovery.getByRole("table")).toBeVisible();
});
for (const change of ["task", "source"])
  test(`late previous-batch preparation cannot revive a retired ${change}`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const data = seedBatchRecovery(nativeScheduleWriteServer.directory);
    let release!: () => void,
      held = false;
    const gate = new Promise<void>((r) => (release = r));
    await page.route("**/default-batch/recovery/prepare", async (route) => {
      const response = await route.fetch(),
        body = await response.body();
      held = true;
      await gate;
      await route.fulfill({ response, body });
    });
    const { compiler, recovery } = await enter(page, data);
    try {
      await recovery
        .getByRole("button", {
          name: "Prepare previous batch defaults",
          exact: true,
        })
        .click();
      await expect.poll(() => held).toBe(true);
      if (change === "task") {
        await chooseWorkspaceTask(page, "Overview");
        await openNativeCompiler(page);
      } else {
        await compiler
          .getByLabel("Retained native backup", { exact: true })
          .selectOption(data.proposal.capture_id);
        await compiler
          .getByRole("button", { name: "Open retained backup", exact: true })
          .click();
      }
      const late = page.waitForResponse((r) =>
        r.url().endsWith("/default-batch/recovery/prepare"),
      );
      release();
      await (await late).finished();
      await expect(
        page.getByRole("table", {
          name: "Previous typed batch values",
          exact: true,
        }),
      ).toHaveCount(0);
      await expect(
        page.getByRole("button", {
          name: "Save exact previous batch proposal",
          exact: true,
        }),
      ).toHaveCount(0);
    } finally {
      release();
    }
  });
test("a late retired response cannot replace a newer exact recovery report", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const data = seedBatchRecovery(nativeScheduleWriteServer.directory);
  let release!: () => void,
    held = false,
    fresh!: Buffer;
  const gate = new Promise<void>((r) => (release = r));
  await page.route("**/default-batch/recovery/prepare", async (route) => {
    const response = await route.fetch(),
      body = await response.body();
    if (held) {
      fresh = body;
      return route.fulfill({ response, body });
    }
    held = true;
    await gate;
    await route.fulfill({
      response,
      body: Buffer.concat([body, Buffer.from("\n \n")]),
    });
  });
  const { recovery, field } = await enter(page, data);
  try {
    await recovery
      .getByRole("button", {
        name: "Prepare previous batch defaults",
        exact: true,
      })
      .click();
    await expect.poll(() => held).toBe(true);
    await field.locator(":scope > summary").evaluate((e) => {
      (e as HTMLElement).click();
      (e as HTMLElement).click();
    });
    await recovery
      .getByRole("button", {
        name: "Prepare previous batch defaults",
        exact: true,
      })
      .click();
    await expect(recovery.getByRole("table")).toBeVisible();
    const late = page.waitForResponse((r) =>
      r.url().endsWith("/default-batch/recovery/prepare"),
    );
    release();
    await (await late).finished();
    const saving = page.waitForEvent("download");
    await recovery
      .getByRole("button", {
        name: "Save exact previous batch proposal",
        exact: true,
      })
      .click();
    const saved = await (await saving).path();
    expect(await readFile(saved!)).toEqual(fresh);
  } finally {
    release();
  }
});
async function enter(page: Page, data: any, caf = false, candidate = true) {
  await page.goto("/");
  if (caf) {
    const select = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: /^Open a CAF file/ }).click();
    await (
      await select
    ).setFiles({
      name: "batch-recovery.caf",
      mimeType: "application/octet-stream",
      buffer: Buffer.from(data.caf, "base64"),
    });
    await expect(
      page.getByLabel("Current CAF archive", { exact: true }),
    ).toHaveText("batch-recovery.caf");
  } else
    await page
      .getByRole("button", { name: "New application", exact: true })
      .click();
  await openNativeCompiler(page);
  const compiler = page.getByRole("region", {
    name: "Native backup default compiler",
    exact: true,
  });
  await compiler
    .getByLabel("Retained native backup", { exact: true })
    .selectOption(data.opened.capture_id);
  await compiler
    .getByRole("button", { name: "Open retained backup", exact: true })
    .click();
  await compiler
    .getByLabel("Native Real default", { exact: true })
    .selectOption("controller/575_1.2_12");
  const draft = compiler.getByLabel("Proposed native Real default", {
    exact: true,
  });
  await draft.fill("12.");
  const batch = compiler.getByLabel("Native typed default batch", {
    exact: true,
  });
  await batch.locator(":scope > summary").click();
  await expect(
    batch.getByRole("table", {
      name: "Native batch default fields",
      exact: true,
    }),
  ).toBeVisible();
  const field = batch.getByLabel("Default batch field workflow", {
    exact: true,
  });
  await field.locator(":scope > summary").click();
  const transfer = field.getByRole("region", {
    name: "Native default batch controller transfer",
    exact: true,
  });
  await transfer
    .getByText("Retained default-batch receipts", { exact: true })
    .click();
  await transfer
    .getByLabel("Typed default batch receipt", { exact: true })
    .selectOption(data.id);
  await transfer
    .getByRole("button", { name: "Load default batch receipt", exact: true })
    .click();
  const recovery = transfer.getByRole("region", {
    name: "Previous typed batch defaults",
    exact: true,
  });
  const prepare = recovery.getByRole("button", {
    name: "Prepare previous batch defaults",
    exact: true,
  });
  if (candidate) await expect(prepare).toBeEnabled();
  else await expect(prepare).toBeVisible();
  return { compiler, batch, field, transfer, recovery, draft };
}
for (const caf of [false, true])
  test(`${caf ? "CAF phone" : "desktop"} prepares actual retained previous values and saves exact evidence offline`, async ({
    page,
    request,
    nativeScheduleWriteServer,
  }, info) => {
    if (caf) await page.setViewportSize({ width: 390, height: 844 });
    const data = seedBatchRecovery(nativeScheduleWriteServer.directory),
      { recovery, draft, transfer } = await enter(page, data, caf);
    let received!: (v: Buffer) => void;
    const bytes = new Promise<Buffer>((r) => (received = r));
    await page.route("**/default-batch/recovery/prepare", async (route) => {
      const original = await route.fetch();
      const body = await original.body();
      received(body);
      await route.fulfill({ response: original, body });
    });
    await recovery
      .getByRole("button", {
        name: "Prepare previous batch defaults",
        exact: true,
      })
      .click();
    const table = recovery.getByRole("table", {
      name: "Previous typed batch values",
      exact: true,
    });
    await expect(table.getByRole("row")).toHaveCount(5);
    await expect(table).toContainText("3.5");
    await expect(table).toContainText("-0");
    await expect(table).toContainText("513");
    await expect(draft).toHaveValue("12.");
    const saving = page.waitForEvent("download");
    await recovery
      .getByRole("button", {
        name: "Save exact previous batch proposal",
        exact: true,
      })
      .click();
    const saved = await (await saving).path();
    expect(await readFile(saved!)).toEqual(await bytes);
    await expect(
      transfer.getByRole("button", {
        name: "Review default batch transfer",
        exact: true,
      }),
    ).toBeDisabled();
    expect((await request.get("/api/session")).ok()).toBeTruthy();
    expect(
      (await (await request.get("/api/session")).json()).field_network_open,
    ).toBe(false);
    if (caf) {
      const viewport = recovery.getByRole("region", {
        name: "Previous batch values table viewport",
        exact: true,
      });
      await viewport.focus();
      await page.keyboard.press("ArrowRight");
      await expect
        .poll(() => viewport.evaluate((e) => e.scrollLeft))
        .toBeGreaterThan(0);
    }
    await page.screenshot({
      path: info.outputPath(
        caf ? "batch-recovery-phone.png" : "batch-recovery-desktop.png",
      ),
    });
  });

for (const kind of ["partial", "already", "historical", "later-unknown"])
  test(`${kind} retained previous batch shows only its actual outcome`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const data = seedBatchRecovery(nativeScheduleWriteServer.directory, kind),
      { recovery, draft } = await enter(page, data);
    await recovery
      .getByRole("button", {
        name: "Prepare previous batch defaults",
        exact: true,
      })
      .click();
    await expect(recovery.getByRole("table").getByRole("row")).toHaveCount(
      kind === "already" ? 4 : 5,
    );
    await expect(recovery).toContainText(
      kind === "already"
        ? "No recovery proposal was created"
        : "Previous values have a source-bound local compilation",
    );
    await expect(draft).toHaveValue("12.");
  });
for (const fault of ["authority", "origin", "compiler"])
  test(`altered ${fault} response cannot publish recovery evidence`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const data = seedBatchRecovery(nativeScheduleWriteServer.directory),
      { recovery } = await enter(page, data);
    await page.route("**/default-batch/recovery/prepare", async (route) => {
      const response = await route.fetch(),
        r = await response.json();
      if (fault === "authority") r.can_apply = true;
      if (fault === "origin") r.origin.fields[0].previous.bits = "00000000";
      if (fault === "compiler")
        r.compilation.batch_guard.fields[0].prior_bits = "00000000";
      await route.fulfill({ response, json: r });
    });
    await recovery
      .getByRole("button", {
        name: "Prepare previous batch defaults",
        exact: true,
      })
      .click();
    await expect(recovery.getByRole("alert")).toContainText(
      "differs from this retained source",
    );
    await expect(recovery.getByRole("table")).toHaveCount(0);
    await expect(
      recovery.getByRole("button", {
        name: "Save exact previous batch proposal",
        exact: true,
      }),
    ).toHaveCount(0);
  });
for (const change of ["pagehide", "visibility", "disclosure"])
  test(`${change} retires the prior exact download before dispatch`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const data = seedBatchRecovery(nativeScheduleWriteServer.directory),
      { recovery, field } = await enter(page, data);
    await recovery
      .getByRole("button", {
        name: "Prepare previous batch defaults",
        exact: true,
      })
      .click();
    const save = recovery.getByRole("button", {
      name: "Save exact previous batch proposal",
      exact: true,
    });
    await expect(save).toBeVisible();
    const old = await save.elementHandle();
    let downloads = 0;
    page.on("download", () => downloads++);
    if (change === "disclosure")
      await field.locator(":scope > summary").evaluate((summary, button) => {
        (summary as HTMLElement).click();
        (summary as HTMLElement).click();
        (button as HTMLElement).click();
      }, old);
    else
      await page.evaluate(
        ({ kind, button }) => {
          if (kind === "pagehide") window.dispatchEvent(new Event("pagehide"));
          else document.dispatchEvent(new Event("visibilitychange"));
          (button as HTMLElement).click();
        },
        { kind: change, button: old },
      );
    await expect(save).toHaveCount(0);
    expect(downloads).toBe(0);
  });

test("a no-dispatch receipt explains unavailable recovery and makes no preparation request", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const data = seedBatchRecovery(nativeScheduleWriteServer.directory);
  let requests = 0;
  page.on("request", (r) => {
    if (r.url().endsWith("/default-batch/recovery/prepare")) requests++;
  });
  await page.route("**/receipts/" + data.id, async (route) => {
    const response = await route.fetch(),
      text = await response.text();
    const start = text.indexOf(',"result":'),
      end = text.indexOf(',"pending":', start);
    expect(start).toBeGreaterThan(0);
    expect(end).toBeGreaterThan(start);
    // Preserve the original signed-zero compilation evidence outside this result.
    const body =
      text.slice(0, start) +
      ',"result":' +
      JSON.stringify({
        status: "not_sent",
        may_have_applied: false,
        protocol_accepted: false,
      }) +
      text.slice(end);
    await route.fulfill({ status: 200, contentType: "application/json", body });
  });
  const { recovery, draft } = await enter(page, data, false, false);
  const prepare = recovery.getByRole("button", {
    name: "Prepare previous batch defaults",
    exact: true,
  });
  await expect(prepare).toBeDisabled();
  await expect(recovery).toContainText("no possible batch restore");
  await prepare.evaluate((button) => (button as HTMLElement).click());
  expect(requests).toBe(0);
  await expect(draft).toHaveValue("12.");
});
