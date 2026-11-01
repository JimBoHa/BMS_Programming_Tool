import {
  test,
  expect,
  type Page,
  type APIRequestContext,
  type Locator,
} from "@playwright/test";
import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { nativeDefaultPeer } from "./native-default-peer";
import { freePort } from "./workflow-peer";

const base = "/api/bacnet/controller/native-application";
async function observeDocument(page: Page, pattern: string) {
  let resolve!: (value: any) => void;
  let reject!: (error: unknown) => void;
  const document = new Promise<any>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  await page.route(pattern, async (route) => {
    try {
      const response = await route.fetch({ maxRetries: 0 });
      const body = await response.body();
      await route.fulfill({ response });
      resolve(JSON.parse(body.toString()));
    } catch (error) {
      reject(error);
      throw error;
    }
  });
  return { document };
}
async function reset(request: APIRequestContext) {
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  expect(
    (await request.post("/api/bacnet/disconnect", { headers, data: {} })).ok(),
  ).toBe(true);
  return headers;
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
    .getByRole("region", { name: "Known controller connection" })
    .getByRole("button", { name: "Open controller", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Controller overview" }),
  ).toContainText("Authored controller");
  await page
    .getByRole("navigation", { name: "Workspace tasks" })
    .getByRole("button", { name: "Program", exact: true })
    .click();
  await page
    .getByRole("navigation", { name: "Current task tools" })
    .getByRole("button", { name: "Native backup defaults", exact: true })
    .click();
  const panel = page.getByRole("region", {
    name: "Native default controller transfer",
    exact: true,
  });
  await panel
    .getByText("Native backup and restore credentials", { exact: true })
    .click();
  await panel
    .getByLabel("Native backup credential", { exact: true })
    .fill("authored-backup");
  await panel
    .getByLabel("Native restore credential", { exact: true })
    .fill("authored-restore");
  await panel
    .getByRole("button", {
      name: "Save native transfer credentials",
      exact: true,
    })
    .click();
  await expect(
    panel.getByLabel("Native backup credential", { exact: true }),
  ).toHaveValue("");
  await panel
    .getByRole("button", { name: "Read current native backup", exact: true })
    .click();
  const compiler = page.getByRole("region", {
    name: "Native backup default compiler",
    exact: true,
  });
  await expect(
    compiler.getByLabel("Native compiler snapshot source", { exact: true }),
  ).toContainText("9 saved application parameters");
  await compiler
    .getByLabel("Native Real default", { exact: true })
    .selectOption("controller/signal-10");
  await compiler
    .getByLabel("Proposed native Real default", { exact: true })
    .fill("0.1");
  return { panel, compiler };
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
  await expect(plan).toContainText("42280000 → 3dcccccd");
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
function mutationEvents(events: any[]) {
  return events.filter(
    (row) =>
      row[0] === "write" || (row[0] === "state" && row[1].includes("restore")),
  );
}

for (const routed of [false, true]) {
  test(`native default ${routed ? "routed" : "direct"} web capture, stale review, one transfer and effective readback`, async ({
    page,
    request,
  }, info) => {
    test.setTimeout(60000);
    const peer = await nativeDefaultPeer(),
      headers = await reset(request);
    try {
      if (routed) await page.setViewportSize({ width: 820, height: 1100 });
      const { panel, compiler } = await open(
        page,
        routed ? peer.router : peer.direct,
        routed,
      );
      const beforeBackup = await peer.command("stats");
      const backupDownload = page.waitForEvent("download");
      await panel
        .getByRole("button", {
          name: "Save original native backup",
          exact: true,
        })
        .click();
      const backupPath = await (await backupDownload).path();
      const root = path.resolve("..");
      const backupProof = JSON.parse(
        execFileSync(
          path.join(root, ".venv/bin/python"),
          [
            "-c",
            `
import sys,json,zipfile
from bms_tool.application_store import checked
from bms_tool.moi_identity import MoiIdentity,sha
from bms_tool.native_signal_compiler import EffectiveSignalCompiler
with zipfile.ZipFile(sys.argv[1]) as z:
 manifest=checked(z.read('manifest.json'));files={i:z.read(f'file-{i}.bin') for i in (3,11,12)}
 assert all(sha(data)==manifest['files'][str(i)]['sha256'] for i,data in files.items())
 fields=EffectiveSignalCompiler(files).fields();field=next(row for row in fields if row['ref']=='controller/signal-10')
 print(json.dumps({'id':manifest['id'],'archive':field['archive_value'],'effective':field['effective_value'],'read_only':manifest['read_only']}))
`,
            backupPath!,
          ],
          {
            cwd: root,
            env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
          },
        ).toString(),
      );
      expect(backupProof).toEqual({
        id: await compiler
          .getByLabel("Retained native backup", { exact: true })
          .inputValue(),
        archive: 23.5,
        effective: 42,
        read_only: false,
      });
      expect((await peer.command("stats")).events).toEqual(beforeBackup.events);
      let returned: any;
      let originalBytes: Buffer | undefined;
      await page.route("**/signal-default/transfer/preview", async (route) => {
        const response = await route.fetch({ maxRetries: 0 });
        originalBytes = await response.body();
        returned = JSON.parse(originalBytes.toString());
        await route.fulfill({ response });
      });
      await review(panel);
      const cancelled = page.waitForResponse((response) =>
        response.url().endsWith("/native-application/cancel"),
      );
      await compiler
        .getByLabel("Proposed native Real default", { exact: true })
        .fill("0.2");
      await cancelled;
      await expect(
        panel.getByRole("region", {
          name: "Reviewed controller default transfer",
          exact: true,
        }),
      ).toHaveCount(0);
      expect(
        (
          await request.post(base + "/signal-default/transfer/apply", {
            headers,
            data: {
              operation_id: "stale-browser-default",
              token: returned.token,
              review_sha256: returned.review_sha256,
              default_change_confirmed: true,
              application_transfer_confirmed: true,
            },
          })
        ).status(),
      ).toBe(422);
      await compiler
        .getByLabel("Proposed native Real default", { exact: true })
        .fill("0.1");
      const { plan, apply } = await review(panel);
      await expect(compiler.locator("button.primary:visible")).toHaveCount(1);
      const saving = page.waitForEvent("download");
      await plan
        .getByRole("button", {
          name: "Export exact transfer review",
          exact: true,
        })
        .click();
      const file = await (await saving).path();
      expect(readFileSync(file!)).toEqual(originalBytes);
      const response = await observeDocument(
        page,
        "**/signal-default/transfer/apply",
      );
      await apply.click();
      await expect(
        page
          .getByRole("navigation", { name: "Main navigation" })
          .getByRole("button", { name: "Library", exact: true }),
      ).toBeDisabled();
      await expect(
        page
          .getByLabel("Working context")
          .getByRole("button", { name: "Change controller", exact: true }),
      ).toBeDisabled();
      const applied = await response.document;
      expect(applied.result.status, JSON.stringify(applied)).toBe("verified");
      expect(applied.pending).toBe(false);
      const outcome = panel.getByRole("region", {
        name: "Native default transfer outcome",
        exact: true,
      });
      await expect(outcome).toContainText("Verified native default transfer");
      await expect(outcome).toContainText(
        "Native application bytes and effective saved settings verified",
      );
      await expect(page.getByLabel("Working context")).toContainText(
        "device,5136",
      );
      const before = await peer.command("stats");
      expect(before.instance).toBe(5136);
      expect(before.router_errors).toEqual([]);
      expect(
        before.events.filter(
          (row: any[]) => row[0] === "state" && row[1] === "start-restore",
        ),
      ).toHaveLength(1);
      expect(
        before.events
          .filter((row: any[]) => row[0] === "write")
          .every((row: any[]) => row[1] === 3),
      ).toBe(true);
      const reread = await observeDocument(
        page,
        "**/native-application/readback",
      );
      await outcome
        .getByRole("button", {
          name: "Read back native default transfer",
          exact: true,
        })
        .click();
      expect((await reread.document).latest_readback.status).toBe("verified");
      expect(mutationEvents((await peer.command("stats")).events)).toEqual(
        mutationEvents(before.events),
      );
      await panel.screenshot({
        path: info.outputPath("native-default-verified.png"),
      });
    } finally {
      await request
        .post("/api/bacnet/disconnect", { headers, data: {} })
        .catch(() => {});
      peer.close();
    }
  });
}

test("changed selected saved value refuses web apply before restore", async ({
  page,
  request,
}) => {
  test.setTimeout(60000);
  const peer = await nativeDefaultPeer(),
    headers = await reset(request);
  try {
    const { panel, compiler } = await open(page, peer.router, true);
    const { apply } = await review(panel);
    await peer.command("selected43");
    await apply.click();
    const outcome = panel.getByRole("region", {
      name: "Native default transfer outcome",
      exact: true,
    });
    await expect(outcome).toContainText("Native default transfer not sent");
    await expect(outcome).toContainText("selected effective default changed");
    expect(mutationEvents((await peer.command("stats")).events)).toEqual([]);
    await expect(
      compiler.getByLabel("Proposed native Real default", { exact: true }),
    ).toHaveValue("0.1");
  } finally {
    await request
      .post("/api/bacnet/disconnect", { headers, data: {} })
      .catch(() => {});
    peer.close();
  }
});

test("lost commit acknowledgement recovers retained web receipt after reload without another restore", async ({
  page,
  request,
}) => {
  test.setTimeout(60000);
  const peer = await nativeDefaultPeer(),
    headers = await reset(request);
  try {
    const { panel } = await open(page, peer.router, true);
    const { apply } = await review(panel);
    await peer.command("mode drop-end");
    await apply.click();
    const outcome = panel.getByRole("region", {
      name: "Native default transfer outcome",
      exact: true,
    });
    await expect(outcome).toContainText("outcome uncertain", {
      timeout: 15000,
    });
    const before = await peer.command("stats");
    expect(
      mutationEvents(before.events).filter(
        (row) => row[0] === "state" && row[1] === "start-restore",
      ),
    ).toHaveLength(1);
    const status = await (await request.get(base + "/status")).json();
    const pending = status.receipts.find(
      (row: any) => row.pending && row.target.router === peer.router,
    );
    expect(pending).toBeTruthy();
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
    await page
      .getByRole("navigation", { name: "Workspace tasks" })
      .getByRole("button", { name: "Program", exact: true })
      .click();
    await page
      .getByRole("navigation", { name: "Current task tools" })
      .getByRole("button", { name: "Native backup defaults", exact: true })
      .click();
    const recovered = page.getByRole("region", {
      name: "Native default controller transfer",
      exact: true,
    });
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
    expect(mutationEvents((await peer.command("stats")).events)).toEqual(
      mutationEvents(before.events),
    );
  } finally {
    await request
      .post("/api/bacnet/disconnect", { headers, data: {} })
      .catch(() => {});
    peer.close();
  }
});

test("altered native transfer bits are refused and their server review is cancelled", async ({
  page,
  request,
}) => {
  test.setTimeout(60000);
  const peer = await nativeDefaultPeer(),
    headers = await reset(request);
  try {
    const { panel } = await open(page, peer.direct, false);
    let original: any;
    await page.route("**/signal-default/transfer/preview", async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      original = JSON.parse((await response.body()).toString());
      const altered = structuredClone(original);
      altered.compilation.selected_edit.after_bits = "00000000";
      await route.fulfill({ response, json: altered });
    });
    const cancelled = page.waitForResponse((response) =>
      response.url().endsWith("/native-application/cancel"),
    );
    await panel
      .getByRole("button", {
        name: "Review controller default transfer",
        exact: true,
      })
      .click();
    await cancelled;
    await expect(panel.getByRole("alert")).toContainText(
      "does not match this controller",
    );
    await expect(
      panel.getByRole("region", {
        name: "Reviewed controller default transfer",
        exact: true,
      }),
    ).toHaveCount(0);
    expect(
      (
        await request.post(base + "/signal-default/transfer/apply", {
          headers,
          data: {
            operation_id: "rejected-review-bits",
            token: original.token,
            review_sha256: original.review_sha256,
            default_change_confirmed: true,
            application_transfer_confirmed: true,
          },
        })
      ).status(),
    ).toBe(422);
    expect(mutationEvents((await peer.command("stats")).events)).toEqual([]);
  } finally {
    await request
      .post("/api/bacnet/disconnect", { headers, data: {} })
      .catch(() => {});
    peer.close();
  }
});

test("changing the selected station retires transfer review and retains the original local draft", async ({
  page,
  request,
}) => {
  test.setTimeout(60000);
  const first = await nativeDefaultPeer(),
    second = await nativeDefaultPeer(),
    headers = await reset(request);
  try {
    const { panel, compiler } = await open(page, first.direct, false);
    await review(panel);
    await page
      .getByLabel("Working context")
      .getByRole("button", { name: "Change controller", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Known controller address", exact: true })
      .click();
    await page
      .getByLabel("Known controller address", { exact: true })
      .fill(second.direct);
    await page
      .getByLabel("Known Device object", { exact: true })
      .fill("device,5136");
    await page.getByLabel("Known router", { exact: true }).fill("");
    await page.getByLabel("Known network", { exact: true }).fill("");
    await page
      .getByRole("region", { name: "Known controller connection" })
      .getByRole("button", { name: "Open controller", exact: true })
      .click();
    await page
      .getByRole("navigation", { name: "Workspace tasks" })
      .getByRole("button", { name: "Program", exact: true })
      .click();
    await page
      .getByRole("navigation", { name: "Current task tools" })
      .getByRole("button", { name: "Native backup defaults", exact: true })
      .click();
    await expect(
      panel.getByRole("region", {
        name: "Reviewed controller default transfer",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(panel).toContainText(
      "retained backup belongs to another station",
    );
    await expect(
      panel.getByRole("button", {
        name: "Review controller default transfer",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      compiler.getByLabel("Proposed native Real default", { exact: true }),
    ).toHaveValue("0.1");
    expect(mutationEvents((await first.command("stats")).events)).toEqual([]);
    expect(mutationEvents((await second.command("stats")).events)).toEqual([]);
  } finally {
    await request
      .post("/api/bacnet/disconnect", { headers, data: {} })
      .catch(() => {});
    first.close();
    second.close();
  }
});
