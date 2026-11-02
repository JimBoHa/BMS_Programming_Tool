import {
  test,
  expect,
  type Page,
  type APIRequestContext,
} from "./nativeScheduleWriteFixture";
import type { Locator } from "@playwright/test";
import { readFileSync } from "node:fs";
import { nativeDefaultPeer } from "./native-default-peer";
import { freePort } from "./workflow-peer";
import {
  inspect,
  effective,
  load,
  python,
} from "./native-effective-enum-fixture";
import {
  openNativeCompiler,
  expectWorkspaceNavigationLocked,
} from "./workspace-navigation";

const base = "/api/bacnet/controller/native-application";
const outcome = (panel: Locator) =>
  panel.getByRole("region", {
    name: "Native default transfer outcome",
    exact: true,
  });
const mutations = (events: any[]) =>
  events.filter(
    (row) =>
      row[0] === "write" || (row[0] === "state" && row[1].includes("restore")),
  );
test.beforeEach(async ({}, info) => {
  info.setTimeout(60000);
});

async function open(
  page: Page,
  request: APIRequestContext,
  endpoint: string,
  routed = true,
  caf = false,
  value = "65535",
) {
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  await page.goto("/");
  if (caf) {
    const file = Buffer.from(
      python(
        "import base64;from tests.test_caf_native_correlation import caf_source;print(base64.b64encode(caf_source().original).decode())",
      ).trim(),
      "base64",
    );
    const chooser = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: /^Open a CAF file/ }).click();
    await (
      await chooser
    ).setFiles({
      name: "enum-transfer.caf",
      mimeType: "application/octet-stream",
      buffer: file,
    });
    await expect(
      page.getByLabel("Current CAF archive", { exact: true }),
    ).toHaveText("enum-transfer.caf");
    await page.getByRole("button", { name: "Connect", exact: true }).click();
  } else
    await page
      .getByRole("button", { name: /^Connect to a controller/ })
      .click();
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
  const compiler = page.getByRole("region", {
      name: "Native backup default compiler",
      exact: true,
    }),
    shared = compiler.getByRole("region", {
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
  const captured = page.waitForResponse(
    (r) =>
      r.url().endsWith(base + "/capture") && r.request().method() === "POST",
  );
  await shared
    .getByRole("button", { name: "Read current native backup", exact: true })
    .click();
  const source = await (await captured).json();
  await expect(
    compiler.getByLabel("Retained native backup", { exact: true }),
  ).toHaveValue(source.id);
  const records = await inspect(compiler),
    editor = await effective(compiler);
  await load(editor);
  const input = editor.getByLabel("Proposed effective Enum code", {
    exact: true,
  });
  await input.fill(value);
  const panel = editor.getByRole("region", {
    name: "Native Enum default controller transfer",
    exact: true,
  });
  await expect(
    panel.getByRole("button", {
      name: "Review controller default transfer",
      exact: true,
    }),
  ).toBeEnabled();
  return { headers, compiler, shared, records, editor, input, panel, source };
}
async function review(panel: Locator, value = 65535) {
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
  await expect(plan).toContainText(`513 → ${value} · stored value ${value}`);
  const apply = plan.getByRole("button", {
    name: "Apply native default to controller",
    exact: true,
  });
  await expect(apply).toBeDisabled();
  await plan
    .getByRole("checkbox", {
      name: "I confirm the selected controller, native Enum code and its intended meaning.",
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
async function close(
  request: APIRequestContext,
  headers: any,
  peer: Awaited<ReturnType<typeof nativeDefaultPeer>>,
) {
  await request
    .post("/api/bacnet/disconnect", { headers, data: {} })
    .catch(() => {});
  peer.close();
}

for (const variant of ["direct", "routed-phone", "CAF-routed"]) {
  test(`${variant} Enum web transfer preserves exact route, fresh settings, original evidence and one restore`, async ({
    page,
    request,
  }, info) => {
    const peer = await nativeDefaultPeer("consume", "enum"),
      value = variant === "routed-phone" ? 0 : 65535;
    let release = () => {};
    let headers: any;
    try {
      if (variant === "routed-phone")
        await page.setViewportSize({ width: 390, height: 844 });
      if (value === 0) await peer.command("enum-restore-zero");
      const view = await open(
        page,
        request,
        variant === "direct" ? peer.direct : peer.router,
        variant !== "direct",
        variant === "CAF-routed",
        String(value),
      );
      headers = view.headers;
      await expect(view.compiler.locator("button.primary:visible")).toHaveCount(
        1,
      );
      let reviewBytes = Buffer.alloc(0);
      await page.route("**/enum-default/transfer/preview", async (route) => {
        const response = await route.fetch({ maxRetries: 0 });
        reviewBytes = await response.body();
        await route.fulfill({ response });
      });
      await review(view.panel, value);
      await view.input.fill("65534");
      await expect(
        view.panel.getByRole("region", {
          name: "Reviewed controller default transfer",
          exact: true,
        }),
      ).toHaveCount(0);
      await view.input.fill(String(value));
      const { plan, apply } = await review(view.panel, value);
      await expect(view.compiler.locator("button.primary:visible")).toHaveCount(
        1,
      );
      const reviewJson = JSON.parse(reviewBytes.toString());
      expect(reviewJson.enum_semantics_verified).toBe(false);
      const reviewDownload = page.waitForEvent("download");
      await plan
        .getByRole("button", {
          name: "Export exact transfer review",
          exact: true,
        })
        .click();
      expect(readFileSync((await (await reviewDownload).path())!)).toEqual(
        reviewBytes,
      );
      await peer.command("enum-other9");
      let received!: () => void;
      const started = new Promise<void>((r) => (received = r)),
        gate = new Promise<void>((r) => (release = r));
      let bytes = Buffer.alloc(0);
      await page.route("**/enum-default/transfer/apply", async (route) => {
        const response = await route.fetch({ maxRetries: 0 });
        bytes = await response.body();
        received();
        await gate;
        await route.fulfill({ response });
      });
      await apply.click();
      await started;
      await expect(
        view.compiler.getByLabel("Retained native backup", { exact: true }),
      ).toBeDisabled();
      await expect(view.input).toBeDisabled();
      await expect(
        view.records.getByLabel("Enum default source", { exact: true }),
      ).toBeDisabled();
      await expect(
        view.records
          .getByRole("button", { name: "Inspect record", exact: true })
          .first(),
      ).toBeDisabled();
      await expectWorkspaceNavigationLocked(page);
      await expect(
        view.panel.getByRole("button", {
          name: "Stop native operation",
          exact: true,
        }),
      ).toBeEnabled();
      release();
      await expect(outcome(view.panel)).toContainText(
        "Verified native default transfer",
      );
      await expect(outcome(view.panel)).toContainText(
        "Physical control performance remains unverified",
      );
      const receipt = JSON.parse(bytes.toString());
      expect(receipt.intent.change_kind).toBe("enum-default");
      expect(receipt.intent.payload_sha256).not.toBe(reviewJson.payload_sha256);
      expect(receipt.intent.target).toEqual(
        variant === "direct"
          ? { address: peer.direct, router: null, dnet: null }
          : { address: "3001:7", router: peer.router, dnet: 3001 },
      );
      expect(receipt.result.preservation.selected_default.effective_value).toBe(
        value,
      );
      expect(
        receipt.result.preservation.selected_default.equal_typed_code,
      ).toBe(true);
      expect(receipt.result.preservation.enum_semantics_verified).toBe(false);
      const download = page.waitForEvent("download");
      await outcome(view.panel)
        .getByRole("button", {
          name: "Export exact transfer receipt",
          exact: true,
        })
        .click();
      expect(readFileSync((await (await download).path())!)).toEqual(bytes);
      const before = await peer.command("stats"),
        writes = mutations(before.events);
      expect(
        writes.filter(
          (row) => row[0] === "state" && row[1] === "start-restore",
        ),
      ).toHaveLength(1);
      expect(
        writes.filter((row) => row[0] === "state" && row[1] === "end-restore"),
      ).toHaveLength(1);
      expect(
        writes.filter((row) => row[0] === "write").every((row) => row[1] === 3),
      ).toBe(true);
      expect(before.enum_archive_tag).toBe(
        value === 0 ? "9200002f" : "92ffff2f",
      );
      expect(before.enum_effective_code).toBe(value);
      expect(before.router_errors).toEqual([]);
      if (variant !== "direct")
        expect(before.request_types).toContain("AtomicWriteFileRequest");
      const ledger = await (
        await request.post("/api/changes/query", {
          headers,
          data: { source: "native" },
        })
      ).json();
      expect(ledger.field_requests).toBe(0);
      expect(ledger.rows).toHaveLength(1);
      expect(ledger.rows[0].native_change_kind).toBe("enum-default");
      expect(ledger.rows[0].object).toBe("controller/enum-1");
      expect(ledger.rows[0].label).toBe("Native Enum code transfer");
      expect((await peer.command("stats")).events).toEqual(before.events);
      await view.panel.scrollIntoViewIfNeeded();
      await page.screenshot({
        path: info.outputPath(`enum-transfer-${variant}.png`),
      });
      await info.attach("review", {
        body: reviewBytes,
        contentType: "application/json",
      });
      await info.attach("receipt", {
        body: bytes,
        contentType: "application/json",
      });
      await info.attach("peer", {
        body: JSON.stringify(before),
        contentType: "application/json",
      });
    } finally {
      release();
      if (headers) await close(request, headers, peer);
      else peer.close();
    }
  });
}

test("a changed live saved Enum code refuses Apply before any restore", async ({
  page,
  request,
}) => {
  const peer = await nativeDefaultPeer("consume", "enum");
  let headers: any;
  try {
    const view = await open(page, request, peer.router);
    headers = view.headers;
    const { apply } = await review(view.panel);
    await peer.command("enum-selected42");
    await apply.click();
    await expect(outcome(view.panel)).toContainText(
      "Native default transfer not sent",
    );
    await expect(outcome(view.panel)).toContainText(
      "selected effective Enum code changed",
    );
    expect(mutations((await peer.command("stats")).events)).toEqual([]);
    await expect(view.input).toHaveValue("65535");
  } finally {
    if (headers) await close(request, headers, peer);
    else peer.close();
  }
});

test("a changed saved Enum state set refuses routed Apply even when its default code is unchanged", async ({
  page,
  request,
}) => {
  const peer = await nativeDefaultPeer("consume", "enum", true);
  let headers: any;
  try {
    const view = await open(page, request, peer.router);
    headers = view.headers;
    const { apply } = await review(view.panel);
    await peer.command("enum-states292");
    const applied = page.waitForResponse(
      (r) =>
        r.url().endsWith("/enum-default/transfer/apply") &&
        r.request().method() === "POST",
    );
    await apply.click();
    await (await applied).finished();
    await expect(outcome(view.panel)).toContainText(
      "Native default transfer not sent",
    );
    await expect(outcome(view.panel)).toContainText(
      "selected Enum state metadata changed",
    );
    expect(mutations((await peer.command("stats")).events)).toEqual([]);
    await expect(view.input).toHaveValue("65535");
  } finally {
    if (headers) await close(request, headers, peer);
    else peer.close();
  }
});

test("lost Enum commit acknowledgement retains uncertainty and readback verifies without replay", async ({
  page,
  request,
}, info) => {
  const peer = await nativeDefaultPeer("consume", "enum");
  let headers: any;
  try {
    const view = await open(page, request, peer.router);
    headers = view.headers;
    const { apply } = await review(view.panel);
    await peer.command("mode drop-end");
    const applied = page.waitForResponse(
      (r) =>
        r.url().endsWith("/enum-default/transfer/apply") &&
        r.request().method() === "POST",
    );
    await apply.click();
    await (await applied).finished();
    await expect(outcome(view.panel)).toContainText("unknown");
    const before = mutations((await peer.command("stats")).events);
    expect(
      before.filter((row) => row[0] === "state" && row[1] === "start-restore"),
    ).toHaveLength(1);
    await peer.command("mode normal");
    let bytes = Buffer.alloc(0);
    await page.route("**/native-application/readback", async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      bytes = await response.body();
      await route.fulfill({ response });
    });
    await outcome(view.panel)
      .getByRole("button", {
        name: "Read back native default transfer",
        exact: true,
      })
      .click();
    await expect(outcome(view.panel)).toContainText(
      "Verified native default transfer",
    );
    expect(
      JSON.parse(bytes.toString()).latest_readback.preservation.selected_default
        .effective_value,
    ).toBe(65535);
    expect(mutations((await peer.command("stats")).events)).toEqual(before);
    await info.attach("reconciled", {
      body: bytes,
      contentType: "application/json",
    });
  } finally {
    if (headers) await close(request, headers, peer);
    else peer.close();
  }
});

for (const altered of ["code", "storage", "semantics"]) {
  test(`substituted Enum field review ${altered} cannot enable Apply`, async ({
    page,
    request,
  }) => {
    const peer = await nativeDefaultPeer("consume", "enum");
    let headers: any;
    try {
      const view = await open(page, request, peer.router);
      headers = view.headers;
      await page.route("**/enum-default/transfer/preview", async (route) => {
        const response = await route.fetch({ maxRetries: 0 }),
          data = await response.json();
        if (altered === "code") data.default_edit.value = 0;
        if (altered === "storage") data.compilation.saved_storage.bytes = 4;
        if (altered === "semantics") data.enum_semantics_verified = true;
        await route.fulfill({ response, json: data });
      });
      await view.panel
        .getByRole("button", {
          name: "Review controller default transfer",
          exact: true,
        })
        .click();
      await expect(view.panel.getByRole("alert")).toContainText(
        "does not match this controller",
      );
      await expect(
        view.panel.getByRole("region", {
          name: "Reviewed controller default transfer",
          exact: true,
        }),
      ).toHaveCount(0);
      expect(mutations((await peer.command("stats")).events)).toEqual([]);
      await expect(view.input).toHaveValue("65535");
    } finally {
      if (headers) await close(request, headers, peer);
      else peer.close();
    }
  });
}

test("stopping a held Enum field review retires its late reply and retains the editable draft", async ({
  page,
  request,
}) => {
  const peer = await nativeDefaultPeer("consume", "enum");
  let headers: any;
  let release = () => {};
  try {
    const view = await open(page, request, peer.router);
    headers = view.headers;
    let received!: () => void;
    const started = new Promise<void>((r) => (received = r)),
      gate = new Promise<void>((r) => (release = r));
    await page.route("**/enum-default/transfer/preview", async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      received();
      await gate;
      await route.fulfill({ response });
    });
    await view.panel
      .getByRole("button", {
        name: "Review controller default transfer",
        exact: true,
      })
      .click();
    await started;
    await expect(view.input).toBeDisabled();
    const stopped = page.waitForResponse(
      (r) =>
        r.url().endsWith(base + "/cancel") && r.request().method() === "POST",
    );
    await view.panel
      .getByRole("button", { name: "Stop native operation", exact: true })
      .click();
    await (await stopped).finished();
    const ended = page.waitForResponse((r) =>
      r.url().endsWith("/enum-default/transfer/preview"),
    );
    release();
    await (await ended).finished();
    await expect(view.input).toBeEnabled();
    await expect(
      view.panel.getByRole("region", {
        name: "Reviewed controller default transfer",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(view.input).toHaveValue("65535");
    await view.input.fill("1e");
    await expect(
      view.panel.getByRole("button", {
        name: "Review controller default transfer",
        exact: true,
      }),
    ).toBeDisabled();
    await expect(
      view.panel.getByRole("region", {
        name: "Reviewed controller default transfer",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(view.input).toHaveValue("1e");
    expect(mutations((await peer.command("stats")).events)).toEqual([]);
  } finally {
    release();
    if (headers) await close(request, headers, peer);
    else peer.close();
  }
});

test("altered Enum Apply receipt cannot claim success and original journal evidence remains available", async ({
  page,
  request,
}) => {
  const peer = await nativeDefaultPeer("consume", "enum");
  let headers: any;
  try {
    const view = await open(page, request, peer.router);
    headers = view.headers;
    const { apply } = await review(view.panel);
    let identifier = "";
    await page.route("**/enum-default/transfer/apply", async (route) => {
      const response = await route.fetch({ maxRetries: 0 }),
        data = await response.json();
      identifier = data.intent.id;
      data.result.preservation.selected_default.effective_value = 0;
      await route.fulfill({ response, json: data });
    });
    const applied = page.waitForResponse(
      (r) =>
        r.url().endsWith("/enum-default/transfer/apply") &&
        r.request().method() === "POST",
    );
    await apply.click();
    await (await applied).finished();
    await expect(view.panel.getByRole("alert")).toContainText(
      "receipt does not match its reviewed code",
    );
    await expect(outcome(view.panel)).toHaveCount(0);
    await view.panel
      .getByText("Retained native default transfers (1)", { exact: true })
      .click();
    await view.panel
      .getByRole("button", {
        name: "Open receipt " + identifier.slice(0, 8),
        exact: true,
      })
      .click();
    await expect(outcome(view.panel)).toContainText(
      "Verified native default transfer",
    );
    expect(
      mutations((await peer.command("stats")).events).filter(
        (row) => row[0] === "state" && row[1] === "start-restore",
      ),
    ).toHaveLength(1);
  } finally {
    if (headers) await close(request, headers, peer);
    else peer.close();
  }
});
