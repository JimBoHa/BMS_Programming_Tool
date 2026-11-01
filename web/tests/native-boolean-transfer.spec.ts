import {
  openNativeCompiler,
  expectWorkspaceNavigationLocked,
} from "./workspace-navigation";
import {
  test,
  expect,
  type Page,
  type Locator,
  type APIRequestContext,
} from "@playwright/test";
import { readFileSync } from "node:fs";
import { nativeDefaultPeer } from "./native-default-peer";
import { freePort } from "./workflow-peer";
import { inspect, record } from "./native-boolean-fixture";

const base = "/api/bacnet/controller/native-application";
async function reset(request: APIRequestContext) {
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  expect(
    (await request.post("/api/bacnet/disconnect", { headers, data: {} })).ok(),
  ).toBe(true);
  return headers;
}
async function selectController(page: Page, endpoint: string, routed: boolean) {
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
  ).toContainText("Authored controller");
  await openNativeCompiler(page);
}
async function fields(page: Page) {
  const compiler = page.getByRole("region", {
    name: "Native backup default compiler",
    exact: true,
  });
  const { inspection, records } = await inspect(compiler);
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
  const panel = editor.getByRole("region", {
    name: "Native Boolean default controller transfer",
    exact: true,
  });
  await expect(
    panel.getByRole("button", {
      name: "Review controller default transfer",
      exact: true,
    }),
  ).toBeEnabled();
  return { compiler, inspection, records, editor, panel };
}
async function open(page: Page, endpoint: string, routed: boolean) {
  await page.goto("/");
  await page.getByRole("button", { name: /^Connect to a controller/ }).click();
  await page
    .getByLabel("Local bind address / UDP port", { exact: true })
    .fill(`127.0.0.1:${await freePort()}`);
  await page
    .getByRole("button", { name: "Open interface", exact: true })
    .click();
  await selectController(page, endpoint, routed);
  const shared = page.getByRole("region", {
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
    page.getByLabel("Native compiler snapshot source", { exact: true }),
  ).toContainText("11 saved application parameters");
  await page
    .getByLabel("Native Real default", { exact: true })
    .selectOption("controller/signal-10");
  return { shared, ...(await fields(page)) };
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
  await expect(plan).toContainText("true → false · stored value false");
  const apply = plan.getByRole("button", {
    name: "Apply native default to controller",
    exact: true,
  });
  await expect(apply).toBeDisabled();
  await plan
    .getByRole("checkbox", {
      name: "I confirm the selected controller, native default and proposed value.",
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
const mutations = (events: any[]) =>
  events.filter(
    (row) =>
      row[0] === "write" || (row[0] === "state" && row[1].includes("restore")),
  );

for (const routed of [false, true]) {
  test(`Boolean ${routed ? "routed" : "direct"} web transfer locks source/navigation and verifies one restore`, async ({
    page,
    request,
  }, info) => {
    test.setTimeout(60000);
    const peer = await nativeDefaultPeer("consume", "boolean"),
      headers = await reset(request);
    let release = () => {};
    try {
      await page.setViewportSize({ width: 820, height: 1100 });
      const { compiler, inspection, records, editor, panel } = await open(
        page,
        routed ? peer.router : peer.direct,
        routed,
      );
      await review(panel);
      await editor
        .getByLabel("Proposed effective Boolean default", { exact: true })
        .check();
      await expect(
        panel.getByRole("region", {
          name: "Reviewed controller default transfer",
          exact: true,
        }),
      ).toHaveCount(0);
      await editor
        .getByLabel("Proposed effective Boolean default", { exact: true })
        .uncheck();
      const { apply } = await review(panel);
      let started!: () => void;
      const gate = new Promise<void>((resolve) => {
          release = resolve;
        }),
        received = new Promise<void>((resolve) => {
          started = resolve;
        });
      let receipt = Buffer.alloc(0);
      await page.route("**/boolean-default/transfer/apply", async (route) => {
        const response = await route.fetch({ maxRetries: 0 });
        receipt = await response.body();
        started();
        await gate;
        await route.fulfill({ response });
      });
      await apply.click();
      await received;
      await expect(
        compiler.getByLabel("Retained native backup", { exact: true }),
      ).toBeDisabled();
      await expect(
        compiler.getByLabel("Proposed native Real default", { exact: true }),
      ).toBeDisabled();
      await expect(
        compiler.getByRole("button", {
          name: "Discard selected field draft",
          exact: true,
        }),
      ).toBeDisabled();
      await expect(
        inspection.getByRole("button", {
          name: "Inspect retained native backup",
          exact: true,
        }),
      ).toBeDisabled();
      await expect(
        records.getByLabel("Boolean default source", { exact: true }),
      ).toBeDisabled();
      await expect(
        editor.getByLabel("Proposed effective Boolean default", {
          exact: true,
        }),
      ).toBeDisabled();
      await expect(
        records
          .getByRole("button", { name: "Inspect record", exact: true })
          .first(),
      ).toBeDisabled();
      await expectWorkspaceNavigationLocked(page);
      await expect(
        panel.getByRole("button", {
          name: "Stop native operation",
          exact: true,
        }),
      ).toBeEnabled();
      release();
      const outcome = panel.getByRole("region", {
        name: "Native default transfer outcome",
        exact: true,
      });
      await expect(outcome).toContainText("Verified native default transfer");
      const data = JSON.parse(receipt.toString());
      expect(data.intent.change_kind).toBe("boolean-default");
      expect(data.result.preservation.selected_default.effective_value).toBe(
        false,
      );
      const pending = page.waitForEvent("download");
      await outcome
        .getByRole("button", {
          name: "Export exact transfer receipt",
          exact: true,
        })
        .click();
      const file = await pending;
      expect(readFileSync((await file.path())!)).toEqual(receipt);
      const stats = await peer.command("stats"),
        events = mutations(stats.events);
      expect(
        events.filter(
          (row) => row[0] === "state" && row[1] === "start-restore",
        ),
      ).toHaveLength(1);
      expect(
        events.filter((row) => row[0] === "state" && row[1] === "end-restore"),
      ).toHaveLength(1);
      expect(
        events.filter((row) => row[0] === "write").every((row) => row[1] === 3),
      ).toBe(true);
      expect(stats.router_errors).toEqual([]);
      if (routed)
        expect(stats.request_types).toContain("AtomicWriteFileRequest");
      await panel.scrollIntoViewIfNeeded();
      await page.screenshot({
        path: info.outputPath("boolean-native-transfer-820.png"),
      });
    } finally {
      release();
      await request
        .post("/api/bacnet/disconnect", { headers, data: {} })
        .catch(() => {});
      peer.close();
    }
  });
}

test("changed selected saved Boolean refuses Apply before any restore", async ({
  page,
  request,
}) => {
  test.setTimeout(60000);
  const peer = await nativeDefaultPeer("consume", "boolean"),
    headers = await reset(request);
  try {
    const { panel } = await open(page, peer.router, true),
      { apply } = await review(panel);
    await peer.command("boolean-selected-false");
    await apply.click();
    const outcome = panel.getByRole("region", {
      name: "Native default transfer outcome",
      exact: true,
    });
    await expect(outcome).toContainText("Native default transfer not sent");
    await expect(outcome).toContainText(
      "selected effective Boolean default changed",
    );
    expect(mutations((await peer.command("stats")).events)).toEqual([]);
  } finally {
    await request
      .post("/api/bacnet/disconnect", { headers, data: {} })
      .catch(() => {});
    peer.close();
  }
});

test("Boolean and Real review ownership invalidates the other profile without discarding drafts", async ({
  page,
  request,
}) => {
  test.setTimeout(60000);
  const peer = await nativeDefaultPeer("consume", "boolean"),
    headers = await reset(request);
  try {
    const { compiler, shared, editor, panel } = await open(
      page,
      peer.router,
      true,
    );
    await compiler
      .getByLabel("Native Real default", { exact: true })
      .selectOption("controller/signal-10");
    await compiler
      .getByLabel("Proposed native Real default", { exact: true })
      .fill("0.1");
    await shared
      .getByRole("button", {
        name: "Review controller default transfer",
        exact: true,
      })
      .click();
    await expect(
      shared.getByRole("region", {
        name: "Reviewed controller default transfer",
        exact: true,
      }),
    ).toContainText("42280000 → 3dcccccd");
    await review(panel);
    await expect(
      shared.getByRole("region", {
        name: "Reviewed controller default transfer",
        exact: true,
      }),
    ).toHaveCount(0);
    await shared
      .getByRole("button", {
        name: "Review controller default transfer",
        exact: true,
      })
      .click();
    await expect(
      shared.getByRole("region", {
        name: "Reviewed controller default transfer",
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      panel.getByRole("region", {
        name: "Reviewed controller default transfer",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      editor.getByLabel("Proposed effective Boolean default", { exact: true }),
    ).not.toBeChecked();
    await expect(
      compiler.getByLabel("Proposed native Real default", { exact: true }),
    ).toHaveValue("0.1");
    expect(mutations((await peer.command("stats")).events)).toEqual([]);
  } finally {
    await request
      .post("/api/bacnet/disconnect", { headers, data: {} })
      .catch(() => {});
    peer.close();
  }
});

test("altered Boolean transfer review is rejected and its server token cancelled", async ({
  page,
  request,
}) => {
  test.setTimeout(60000);
  const peer = await nativeDefaultPeer("consume", "boolean"),
    headers = await reset(request);
  try {
    const { panel } = await open(page, peer.router, true);
    let original: any,
      operation = "";
    await page.route("**/boolean-default/transfer/preview", async (route) => {
      operation = route.request().postDataJSON().operation_id;
      const response = await route.fetch({ maxRetries: 0 });
      original = JSON.parse((await response.body()).toString());
      const altered = structuredClone(original);
      altered.compilation.selected_edit.after_value = true;
      await route.fulfill({ response, json: altered });
    });
    const cancelled = page.waitForResponse(
      (response) =>
        response.url().endsWith("/native-application/cancel") &&
        response.request().postDataJSON()?.operation_id === operation,
    );
    await panel
      .getByRole("button", {
        name: "Review controller default transfer",
        exact: true,
      })
      .click();
    await expect(panel.getByRole("alert")).toContainText("does not match");
    await cancelled;
    const replay = await request.post(
      base + "/boolean-default/transfer/apply",
      {
        headers,
        data: {
          operation_id: "replay-cancelled-bool-review",
          token: original.token,
          review_sha256: original.review_sha256,
          default_change_confirmed: true,
          application_transfer_confirmed: true,
        },
      },
    );
    expect(replay.status()).toBe(422);
    expect(mutations((await peer.command("stats")).events)).toEqual([]);
  } finally {
    await request
      .post("/api/bacnet/disconnect", { headers, data: {} })
      .catch(() => {});
    peer.close();
  }
});

test("lost Boolean commit acknowledgement reconciles after reload without another restore", async ({
  page,
  request,
}) => {
  test.setTimeout(60000);
  const peer = await nativeDefaultPeer("consume", "boolean"),
    headers = await reset(request);
  try {
    const { panel } = await open(page, peer.router, true),
      { apply } = await review(panel);
    await peer.command("mode drop-end");
    await apply.click();
    await expect(
      panel.getByRole("region", {
        name: "Native default transfer outcome",
        exact: true,
      }),
    ).toContainText("outcome uncertain", { timeout: 15000 });
    const status = await (await request.get(base + "/status")).json(),
      pending = status.receipts.find(
        (row: any) => row.pending && row.target.router === peer.router,
      );
    expect(pending.change_kind).toBe("boolean-default");
    const before = mutations((await peer.command("stats")).events);
    const data = await (
      await request.get(base + "/receipts/" + pending.id)
    ).json();
    await page.reload();
    await page
      .getByRole("button", { name: /^Connect to a controller/ })
      .click();
    await selectController(page, peer.router, true);
    const compiler = page.getByRole("region", {
      name: "Native backup default compiler",
      exact: true,
    });
    await compiler
      .getByLabel("Retained native backup", { exact: true })
      .selectOption(data.intent.review_capture_id);
    const { panel: recovered } = await fields(page);
    await recovered
      .getByRole("button", {
        name: "Open receipt " + pending.id.slice(0, 8),
        exact: true,
      })
      .click();
    await peer.command("mode normal");
    await recovered
      .getByRole("button", {
        name: "Read back native default transfer",
        exact: true,
      })
      .click();
    await expect(
      recovered.getByRole("region", {
        name: "Native default transfer outcome",
        exact: true,
      }),
    ).toContainText("Verified native default transfer");
    expect(mutations((await peer.command("stats")).events)).toEqual(before);
  } finally {
    await request
      .post("/api/bacnet/disconnect", { headers, data: {} })
      .catch(() => {});
    peer.close();
  }
});
