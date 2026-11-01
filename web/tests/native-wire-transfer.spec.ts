import { test, expect, type Page, type Locator } from "@playwright/test";
import { nativeDefaultPeer } from "./native-default-peer";
import { freePort } from "./workflow-peer";
import { inspect } from "./native-boolean-fixture";

const ref = "controller/575_1",
  replacement = ref + ".2_11";
async function select(page: Page, endpoint: string, routed: boolean) {
  await page
    .getByRole("button", { name: "Known controller address", exact: true })
    .click();
  await page
    .getByLabel("Known controller address", { exact: true })
    .fill(routed ? "3001:7" : endpoint);
  await page
    .getByLabel("Known Device object", { exact: true })
    .fill("device,5136");
  await page
    .getByLabel("Known router", { exact: true })
    .fill(routed ? endpoint : "");
  await page
    .getByLabel("Known network", { exact: true })
    .fill(routed ? "3001" : "");
  await page
    .getByRole("region", { name: "Known controller connection", exact: true })
    .getByRole("button", { name: "Open controller", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Controller overview", exact: true }),
  ).toContainText("Authored native wire controller");
  await page
    .getByRole("navigation", { name: "Workspace tasks", exact: true })
    .getByRole("button", { name: "Program", exact: true })
    .click();
  await page
    .getByRole("navigation", { name: "Current task tools", exact: true })
    .getByRole("button", { name: "Native backup defaults", exact: true })
    .click();
}
async function open(
  page: Page,
  endpoint: string,
  routed: boolean,
  resume?: string,
) {
  await page.goto("/");
  await page.getByRole("button", { name: /^Connect to a controller/ }).click();
  if (!resume) {
    await page
      .getByLabel("Local bind address / UDP port", { exact: true })
      .fill(`127.0.0.1:${await freePort()}`);
    await page
      .getByRole("button", { name: "Open interface", exact: true })
      .click();
  }
  await select(page, endpoint, routed);
  const shared = page.getByRole("region", {
    name: "Native default controller transfer",
    exact: true,
  });
  if (!resume) {
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
      page.getByLabel("Native compiler snapshot source", { exact: true }),
    ).toContainText("3 saved application parameters");
  }
  const compiler = page.getByRole("region", {
    name: "Native backup default compiler",
    exact: true,
  });
  if (resume)
    await compiler
      .getByLabel("Retained native backup", { exact: true })
      .selectOption(resume);
  const { inspection, records } = await inspect(compiler, 9);
  await records
    .getByRole("table", { name: "Captured native records", exact: true })
    .getByRole("row")
    .filter({
      has: page.getByRole("cell", { name: ref + " engineering", exact: true }),
    })
    .getByRole("button", { name: "Inspect record", exact: true })
    .click();
  const editor = records.getByLabel(
    /^(Native archive wire source copy|Effective native wire compilation)$/,
  );
  await editor.locator(":scope > summary").click();
  await editor
    .getByLabel("Native wire source basis", { exact: true })
    .selectOption("effective");
  await editor
    .getByRole("button", { name: "Open saved wire sources", exact: true })
    .click();
  await editor
    .getByLabel("Replacement native source", { exact: true })
    .selectOption(replacement);
  const panel = editor.getByRole("region", {
    name: "Native wire source controller transfer",
    exact: true,
  });
  await expect(
    panel.getByRole("button", {
      name: "Review controller wire transfer",
      exact: true,
    }),
  ).toBeEnabled();
  return { compiler, inspection, records, editor, panel };
}
async function review(panel: Locator) {
  await panel
    .getByRole("button", {
      name: "Review controller wire transfer",
      exact: true,
    })
    .click();
  const plan = panel.getByRole("region", {
    name: "Reviewed controller wire transfer",
    exact: true,
  });
  await expect(plan).toContainText(ref + ".2_10 → " + replacement);
  const apply = plan.getByRole("button", {
    name: "Apply native wire to controller",
    exact: true,
  });
  await expect(apply).toBeDisabled();
  await plan
    .getByRole("checkbox", {
      name: "I confirm the selected controller, native connection and proposed wire source.",
      exact: true,
    })
    .check();
  await expect(apply).toBeDisabled();
  await plan
    .getByRole("checkbox", {
      name: "I confirm the application transfer and controller interruption.",
      exact: true,
    })
    .check();
  await expect(apply).toBeEnabled();
  return { plan, apply };
}
const mutations = (rows: any[]) =>
  rows.filter(
    (r) => r[0] === "write" || (r[0] === "state" && r[1].includes("restore")),
  );
test.beforeEach(async ({ request }) => {
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  expect(
    (await request.post("/api/bacnet/disconnect", { headers, data: {} })).ok(),
  ).toBe(true);
});
for (const routed of [false, true]) {
  test(`wire ${routed ? "routed" : "direct"} web transfer keeps its source while locked and verifies one restore`, async ({
    page,
  }, info) => {
    test.setTimeout(60000);
    const peer = await nativeDefaultPeer("consume", "wire");
    let release = () => {};
    try {
      await page.setViewportSize({ width: 820, height: 1100 });
      const { compiler, inspection, editor, panel } = await open(
        page,
        routed ? peer.router : peer.direct,
        routed,
      );
      const { apply } = await review(panel);
      await peer.command("wire-other-fresh");
      let started!: () => void;
      const gate = new Promise<void>((r) => (release = r)),
        received = new Promise<void>((r) => (started = r));
      await page.route("**/wire-source/transfer/apply", async (route) => {
        const response = await route.fetch({ maxRetries: 0 });
        started();
        await gate;
        await route.fulfill({ response });
      });
      await apply.click();
      await expect(
        editor.getByLabel("Native wire source basis", { exact: true }),
      ).toBeDisabled();
      await expect(
        editor.getByLabel("Replacement native source", { exact: true }),
      ).toBeDisabled();
      await expect(
        compiler.getByLabel("Retained native backup", { exact: true }),
      ).toBeDisabled();
      await expect(
        inspection.getByRole("button", {
          name: "Inspect retained native backup",
          exact: true,
        }),
      ).toBeDisabled();
      await expect(
        page
          .getByRole("navigation", { name: "Main navigation", exact: true })
          .getByRole("button", { name: "Library", exact: true }),
      ).toBeDisabled();
      await expect(
        panel.getByRole("button", {
          name: "Stop native operation",
          exact: true,
        }),
      ).toBeEnabled();
      await received;
      release();
      const result = panel.getByRole("region", {
        name: "Native wire transfer outcome",
        exact: true,
      });
      await expect(result).toContainText("Verified native wire transfer");
      await expect(
        editor.getByLabel("Native wire source basis", { exact: true }),
      ).toBeEnabled();
      const stats = await peer.command("stats");
      expect(
        mutations(stats.events).filter(
          (r) => r[0] === "state" && r[1] === "start-restore",
        ),
      ).toHaveLength(1);
      await result
        .getByText("Transfer and preservation evidence", { exact: true })
        .click();
      await expect(result.locator("pre")).toContainText(
        '"effective_connection_verified": true',
      );
      await panel.scrollIntoViewIfNeeded();
      await page.screenshot({
        path: info.outputPath(
          `native-wire-transfer-${routed ? "routed" : "direct"}-820.png`,
        ),
      });
    } finally {
      release();
      peer.close();
    }
  });
}

test("a changed application refuses wire restore and retains the original draft", async ({
  page,
}) => {
  test.setTimeout(60000);
  const peer = await nativeDefaultPeer("consume", "wire");
  try {
    const { editor, panel } = await open(page, peer.direct, false),
      { apply } = await review(panel);
    await peer.command("wire-application-changed");
    await apply.click();
    await expect(
      panel.getByRole("region", {
        name: "Native wire transfer outcome",
        exact: true,
      }),
    ).toContainText("Native wire transfer not sent");
    await expect(
      editor.getByLabel("Replacement native source", { exact: true }),
    ).toHaveValue(replacement);
    expect(mutations((await peer.command("stats")).events)).toEqual([]);
  } finally {
    peer.close();
  }
});

test("altered wire review is rejected and its server plan is cancelled", async ({
  page,
  request,
}) => {
  test.setTimeout(60000);
  const peer = await nativeDefaultPeer("consume", "wire");
  try {
    const { panel } = await open(page, peer.direct, false);
    let original: any;
    await page.route("**/wire-source/transfer/preview", async (route) => {
      const response = await route.fetch({ maxRetries: 0 }),
        data = await response.json();
      original = structuredClone(data);
      data.compilation.wire_edit.new[0] = 0;
      await route.fulfill({ response, body: JSON.stringify(data) });
    });
    const cancelled = page.waitForResponse(
      (r) =>
        r.url().endsWith("/native-application/cancel") &&
        r.request().method() === "POST",
    );
    await panel
      .getByRole("button", {
        name: "Review controller wire transfer",
        exact: true,
      })
      .click();
    await expect(panel.getByRole("alert")).toContainText(
      "Native transfer review does not match",
    );
    await cancelled;
    const headers = {
      "X-Studio-Token": (await (await request.get("/api/session")).json())
        .token,
    };
    const result = await request.post(
      "/api/bacnet/controller/native-application/wire-source/transfer/apply",
      {
        headers,
        data: {
          operation_id: "cancelled-wire-plan-test",
          token: original.token,
          review_sha256: original.review_sha256,
          wire_change_confirmed: true,
          application_transfer_confirmed: true,
        },
      },
    );
    expect(result.status(), await result.text()).toBe(422);
    expect((await result.json()).detail).toContain("already consumed");
    expect(mutations((await peer.command("stats")).events)).toEqual([]);
  } finally {
    peer.close();
  }
});

test("altered wire receipt cannot claim verification; its original retained evidence remains available", async ({
  page,
}) => {
  test.setTimeout(60000);
  const peer = await nativeDefaultPeer("consume", "wire");
  try {
    const { panel } = await open(page, peer.direct, false),
      { apply } = await review(panel);
    let id = "";
    await page.route("**/wire-source/transfer/apply", async (route) => {
      const response = await route.fetch({ maxRetries: 0 }),
        data = await response.json();
      id = data.intent.id;
      data.result.preservation.selected_wire.source_ref = ref + ".2_10";
      await route.fulfill({ response, body: JSON.stringify(data) });
    });
    const response = page.waitForResponse(
      (r) =>
        r.url().endsWith("/wire-source/transfer/apply") &&
        r.request().method() === "POST",
    );
    await apply.click();
    await response;
    await expect(panel.getByRole("alert")).toContainText(
      "Native wire receipt does not match",
    );
    await expect(
      panel.getByRole("region", {
        name: "Native wire transfer outcome",
        exact: true,
      }),
    ).toHaveCount(0);
    await panel
      .getByRole("button", { name: "Refresh transfer receipts", exact: true })
      .click();
    const list = panel.getByRole("table", {
      name: "Native wire transfer receipts",
      exact: true,
    });
    const history = panel.locator("details").filter({
      has: page.getByRole("table", {
        name: "Native wire transfer receipts",
        exact: true,
        includeHidden: true,
      }),
    });
    if ((await history.getAttribute("open")) === null)
      await history.locator(":scope > summary").click();
    await list
      .getByRole("button", {
        name: "Open receipt " + id.slice(0, 8),
        exact: true,
      })
      .click();
    await expect(
      panel.getByRole("region", {
        name: "Native wire transfer outcome",
        exact: true,
      }),
    ).toContainText("Verified native wire transfer");
    expect(
      mutations((await peer.command("stats")).events).filter(
        (r) => r[0] === "state" && r[1] === "start-restore",
      ),
    ).toHaveLength(1);
  } finally {
    peer.close();
  }
});

test("lost wire commit acknowledgement survives reload and readback never restores again", async ({
  page,
  request,
}) => {
  test.setTimeout(60000);
  const peer = await nativeDefaultPeer("drop-end", "wire");
  try {
    const { compiler, panel } = await open(page, peer.direct, false),
      capture = await compiler
        .getByLabel("Retained native backup", { exact: true })
        .inputValue();
    const { apply } = await review(panel);
    const response = page.waitForResponse(
      (r) =>
        r.url().endsWith("/wire-source/transfer/apply") &&
        r.request().method() === "POST",
    );
    await apply.click();
    await response;
    await expect(
      panel.getByRole("region", {
        name: "Native wire transfer outcome",
        exact: true,
      }),
    ).toContainText("Native wire transfer outcome uncertain");
    const status = await (
      await request.get("/api/bacnet/controller/native-application/status")
    ).json();
    const matches = status.receipts.filter(
      (row: any) =>
        row.change_kind === "wire-source" &&
        row.wire_edit?.capture_id === capture,
    );
    expect(matches).toHaveLength(1);
    const receiptId = matches[0].id;
    const before = mutations((await peer.command("stats")).events);
    await peer.command("mode normal");
    const reopened = await open(page, peer.direct, false, capture);
    const list = reopened.panel.getByRole("table", {
      name: "Native wire transfer receipts",
      exact: true,
    });
    await list
      .getByRole("button", {
        name: "Open receipt " + receiptId.slice(0, 8),
        exact: true,
      })
      .click();
    await reopened.panel
      .getByRole("button", {
        name: "Read back native wire transfer",
        exact: true,
      })
      .click();
    await expect(
      reopened.panel.getByRole("region", {
        name: "Native wire transfer outcome",
        exact: true,
      }),
    ).toContainText("Verified native wire transfer");
    expect(mutations((await peer.command("stats")).events)).toEqual(before);
  } finally {
    peer.close();
  }
});
