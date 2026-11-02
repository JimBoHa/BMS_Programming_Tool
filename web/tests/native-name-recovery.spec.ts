import {
  test,
  expect,
  type Page,
  type APIRequestContext,
  type Locator,
} from "./nativeScheduleWriteFixture";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import { nativeDefaultPeer } from "./native-default-peer";
import { freePort } from "./workflow-peer";
import { chooseWorkspaceTask } from "./workspace-navigation";
import { previousNameMatches } from "../src/nativeNameRecoveryContract";

const root = path.resolve(".."),
  base = "/api/bacnet/controller/native-application";
const panel = (page: Page) =>
  page.getByRole("region", {
    name: "Native application name commissioning",
    exact: true,
  });
const proposal = (page: Page) =>
  page.getByRole("region", {
    name: "Previous controller name proposal",
    exact: true,
  });
function seed(directory: string, already = false) {
  const state = directory;
  if (!state) throw new Error("An isolated state directory is required.");
  return JSON.parse(
    execFileSync(
      path.join(root, ".venv/bin/python"),
      [
        "-c",
        `
import sys,json,base64
from pathlib import Path
from tests.test_native_name_recovery import setup,current_source
from tests.test_caf_native_correlation import caf_source
from bms_tool.native_applications import NativeApplications
from bms_tool.native_backup_records import NativeBackupRecords
s,service,request,before,files=setup(Path(sys.argv[1]))
if sys.argv[2]=='already':
 output,_=NativeApplications.compile(files,5136,'Authored controller')
 request=current_source(s,request,files|{3:output},identity=before['identity'])
source=service.source({'capture_id':request['capture_id'],'snapshot_sha256':request['snapshot_sha256']})
capture=source|{'id':source['capture_id'],'snapshot_evidence_sha256':source['snapshot_sha256'],'identity':source['identity']|{'device':source['target']['device']}}
print(json.dumps({'request':request,'receipt':s.receipt(request['receipt_id']),'report':service.prepare(request),'capture':capture,'caf':base64.b64encode(caf_source().original).decode()}))
`,
        state,
        already ? "already" : "changed",
      ],
      {
        cwd: root,
        env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
        encoding: "utf8",
      },
    ),
  );
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
async function openName(page: Page) {
  await chooseWorkspaceTask(page, "Overview");
  const tools = page.getByRole("navigation", {
    name: "Controller task tools",
    exact: true,
  });
  await expect(tools).toBeVisible();
  const select = tools.getByRole("combobox", {
    name: "Controller task tools",
    exact: true,
  });
  if (await select.isVisible())
    await select.selectOption({ label: "Identity settings" });
  else
    await tools
      .getByRole("button", { name: "Identity settings", exact: true })
      .click();
  await page
    .getByLabel("Identity setting", { exact: true })
    .selectOption("name");
  await expect(panel(page)).toBeVisible();
  return panel(page);
}
async function expandRecovery(p: Locator) {
  const summary = p
    .locator("summary")
    .filter({ hasText: /^Previous controller name$/ });
  if ((await summary.locator("..").getAttribute("open")) === null)
    await summary.click();
}
async function local(page: Page, data: ReturnType<typeof seed>) {
  await page.goto("/");
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: /^Open a CAF file/ }).click();
  await (
    await chooser
  ).setFiles({
    name: "name-reference.caf",
    mimeType: "application/octet-stream",
    buffer: Buffer.from(data.caf, "base64"),
  });
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("name-reference.caf");
  const p = await openName(page);
  await expandRecovery(p);
  await p
    .getByRole("button", { name: "Load retained name backups", exact: true })
    .click();
  await p
    .getByLabel("Name recovery backup", { exact: true })
    .selectOption(data.request.capture_id);
  await expect(
    p.getByLabel("Captured native application", { exact: true }),
  ).toContainText(data.report.current_name);
  await p
    .getByLabel("Retained native transfer receipts", { exact: true })
    .selectOption(data.request.receipt_id);
  await expect(
    p.getByLabel("Native application transfer receipt", { exact: true }),
  ).toContainText("Renamed controller");
  return p;
}
async function prepare(p: Locator) {
  await p
    .getByRole("button", {
      name: "Prepare previous controller name",
      exact: true,
    })
    .click();
  const result = p.getByRole("region", {
    name: "Previous controller name proposal",
    exact: true,
  });
  await expect(result).toBeVisible();
  return result;
}
test.beforeEach(async ({ request }) => {
  await reset(request);
});

test("offline CAF entry preserves ordinary draft, exact evidence, task navigation and phone layout", async ({
  page,
  request,
  nativeScheduleWriteServer,
}, info) => {
  const data = seed(nativeScheduleWriteServer.directory);
  expect(previousNameMatches(data.report, data.capture, data.receipt)).toBe(
    true,
  );
  await page.setViewportSize({ width: 390, height: 1100 });
  const calls: string[] = [];
  page.on("request", (r) => {
    if (
      /\/native-application\/(capture|preview|apply|readback|name\/recovery\/preview)$/.test(
        r.url(),
      )
    )
      calls.push(r.url());
  });
  let exact = Buffer.alloc(0);
  await page.route(
    "**/native-application/name/recovery/prepare",
    async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      exact = await response.body();
      await route.fulfill({ response });
    },
  );
  let p = await local(page, data);
  await p
    .getByLabel("New controller name", { exact: true })
    .fill("Ordinary offline draft");
  const result = await prepare(p);
  await expect(result).toBeFocused();
  await expect(
    p.getByLabel("New controller name", { exact: true }),
  ).toHaveValue("Authored controller");
  await expect(
    p.getByRole("button", { name: "Review name change", exact: true }),
  ).toBeDisabled();
  const downloading = page.waitForEvent("download");
  await result
    .getByRole("button", {
      name: "Save exact name recovery evidence",
      exact: true,
    })
    .click();
  expect(readFileSync((await (await downloading).path())!)).toEqual(exact);
  expect(JSON.parse(exact.toString()).origin.parent_receipt_id).toBe(
    data.request.receipt_id,
  );
  await chooseWorkspaceTask(page, "Points & I/O");
  p = await openName(page);
  await expect(proposal(page)).toBeVisible();
  await proposal(page)
    .getByRole("button", { name: "Return to ordinary name draft", exact: true })
    .click();
  await expect(proposal(page)).toHaveCount(0);
  await expect(
    p.getByLabel("New controller name", { exact: true }),
  ).toHaveValue("Ordinary offline draft");
  await expandRecovery(p);
  await prepare(p);
  await proposal(page).scrollIntoViewIfNeeded();
  await page.screenshot({
    path: info.outputPath("offline-name-recovery.png"),
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(calls).toEqual([]);
  expect(
    (await (await request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
});

test("already recorded previous name has evidence and no implicit controller verification", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const p = await local(page, seed(nativeScheduleWriteServer.directory, true));
  const result = await prepare(p);
  await expect(result).toContainText("already records the previous name");
  await expect(result).toContainText("does not verify the current controller");
  await expect(
    p.getByRole("button", { name: "Review name change", exact: true }),
  ).toBeDisabled();
});

for (const change of ["source", "task", "receipt", "visibility"]) {
  test(`held previous-name response is retired by ${change} ABA`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const data = seed(nativeScheduleWriteServer.directory),
      other = seed(nativeScheduleWriteServer.directory);
    let p = await local(page, data);
    await p
      .getByLabel("New controller name", { exact: true })
      .fill("Preserved ordinary draft");
    let release!: () => void, arrived!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const held = new Promise<void>((resolve) => {
      arrived = resolve;
    });
    let released!: () => void;
    const done = new Promise<void>((resolve) => {
      released = resolve;
    });
    await page.route(
      "**/native-application/name/recovery/prepare",
      async (route) => {
        const response = await route.fetch({ maxRetries: 0 });
        arrived();
        await gate;
        await route.fulfill({ response });
        released();
      },
    );
    try {
      await p
        .getByRole("button", {
          name: "Prepare previous controller name",
          exact: true,
        })
        .click();
      await held;
      if (change === "visibility") {
        await page.evaluate(() =>
          document.dispatchEvent(new Event("visibilitychange")),
        );
      } else if (change === "task") {
        await chooseWorkspaceTask(page, "Points & I/O");
        p = await openName(page);
      } else if (change === "receipt") {
        const receipts = p.getByLabel("Retained native transfer receipts", {
          exact: true,
        });
        await receipts.selectOption(other.request.receipt_id);
        await expect(
          p.getByLabel("Native application transfer receipt", { exact: true }),
        ).toContainText("Renamed controller");
        await receipts.selectOption(data.request.receipt_id);
      } else {
        // A local source change is allowed to retire a pending local response.
        await chooseWorkspaceTask(page, "Points & I/O");
        p = await openName(page);
        await expandRecovery(p);
        await p
          .getByRole("button", {
            name: "Load retained name backups",
            exact: true,
          })
          .click();
        await p
          .getByLabel("Name recovery backup", { exact: true })
          .selectOption(other.request.capture_id);
        await expect(
          p.getByLabel("Captured native application", { exact: true }),
        ).toContainText("Renamed controller");
        await p
          .getByLabel("Name recovery backup", { exact: true })
          .selectOption(data.request.capture_id);
      }
      release();
      await done;
      await expect(proposal(page)).toHaveCount(0);
      await expect(
        p.getByLabel("New controller name", { exact: true }),
      ).toHaveValue("Preserved ordinary draft");
    } finally {
      release();
    }
  });
}

test("malformed previous-name report cannot replace the ordinary draft", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const data = seed(nativeScheduleWriteServer.directory),
    p = await local(page, data);
  await p
    .getByLabel("New controller name", { exact: true })
    .fill("Ordinary draft");
  const changed = structuredClone(data.report);
  changed.origin.instance++;
  expect(previousNameMatches(changed, data.capture, data.receipt)).toBe(false);
  await page.route(
    "**/native-application/name/recovery/prepare",
    async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      await route.fulfill({ response, json: changed });
    },
  );
  await p
    .getByRole("button", {
      name: "Prepare previous controller name",
      exact: true,
    })
    .click();
  await expect(p.getByRole("alert")).toContainText(
    "does not match this backup and receipt",
  );
  await expect(proposal(page)).toHaveCount(0);
  await expect(
    p.getByLabel("New controller name", { exact: true }),
  ).toHaveValue("Ordinary draft");
});

async function connect(
  page: Page,
  request: APIRequestContext,
  endpoint: string,
  routed: boolean,
) {
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  expect(
    (
      await request.post(base + "/credentials", {
        headers,
        data: { backup: "authored-backup", restore: "authored-restore" },
      })
    ).ok(),
  ).toBe(true);
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
    .getByRole("region", { name: "Known controller connection", exact: true })
    .getByRole("button", { name: "Open controller", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Controller overview", exact: true }),
  ).toContainText("Authored native wire controller");
  await page
    .getByRole("button", { name: "Edit controller name", exact: true })
    .click();
  return panel(page);
}
async function confirm(p: Locator, suffix: string) {
  await p
    .getByRole("button", { name: "Review name change", exact: true })
    .click();
  const review = p.getByLabel("Reviewed native application transfer", {
    exact: true,
  });
  await expect(review).toContainText(suffix);
  await review
    .getByRole("checkbox", {
      name: "I confirm this controller name change.",
      exact: true,
    })
    .check();
  await review
    .getByRole("checkbox", {
      name: "I reviewed this application transfer and its possible brief interruption of controller operation.",
      exact: true,
    })
    .check();
  const response = p
    .page()
    .waitForResponse(
      (r) =>
        r.url().endsWith("/native-application/apply") &&
        r.request().method() === "POST",
    );
  await review
    .getByRole("button", { name: "Apply controller name", exact: true })
    .click();
  const result = await (await response).json();
  expect(result.result.status).toBe("verified");
  return result;
}
for (const routed of [false, true]) {
  test(`actual ${routed ? "routed" : "direct"} name recovery requires a new transfer and records lineage`, async ({
    page,
    request,
    nativeScheduleWriteServer,
  }, info) => {
    test.setTimeout(60000);
    const peer = await nativeDefaultPeer("consume", "wire");
    try {
      const p = await connect(
        page,
        request,
        routed ? peer.router : peer.direct,
        routed,
      );
      await p
        .getByRole("button", { name: "Read application backup", exact: true })
        .click();
      await p
        .getByLabel("New controller name", { exact: true })
        .fill("Renamed controller");
      const parent = await confirm(p, "→ Renamed controller");
      const capturing = page.waitForResponse(
        (response) =>
          response.url().endsWith("/native-application/capture") &&
          response.request().method() === "POST",
      );
      await p
        .getByRole("button", { name: "Read application backup", exact: true })
        .click();
      const currentCapture = await (await capturing).json();
      await expect(
        p.getByLabel("Captured native application", { exact: true }),
      ).toContainText("Renamed controller");
      await expandRecovery(p);
      if (routed) {
        const unrelated = seed(nativeScheduleWriteServer.directory);
        const beforeLocal = (await peer.command("stats")).events;
        await p
          .getByRole("button", {
            name: "Load retained name backups",
            exact: true,
          })
          .click();
        const picker = p.getByLabel("Name recovery backup", { exact: true });
        await picker.selectOption(unrelated.request.capture_id);
        await p
          .getByLabel("New controller name", { exact: true })
          .fill("Ordinary station draft");
        await expect(
          p.getByRole("button", { name: "Review name change", exact: true }),
        ).toBeDisabled();
        await picker.selectOption(currentCapture.id);
        await expect(
          p.getByRole("button", { name: "Review name change", exact: true }),
        ).toBeEnabled();
        expect((await peer.command("stats")).events).toEqual(beforeLocal);
      }
      await prepare(p);
      await expect(
        p.getByLabel("New controller name", { exact: true }),
      ).toHaveValue("Authored native wire controller");
      const start = (await peer.command("stats")).events.length;
      await peer.command("wire-other-fresh");
      const child = await confirm(p, "→ Authored native wire controller");
      expect(child.intent.id).not.toBe(parent.intent.id);
      expect(child.intent.recovery_origin.parent_receipt_id).toBe(
        parent.intent.id,
      );
      expect(child.intent.old_instance).toBe(5136);
      expect(child.intent.new_instance).toBe(5136);
      expect(child.result.preservation.application_identical_except_name).toBe(
        true,
      );
      const events = (await peer.command("stats")).events.slice(start);
      expect(
        events.filter(
          (e: any[]) => e[0] === "state" && e[1] === "start-restore",
        ),
      ).toHaveLength(1);
      expect(
        events.filter((e: any[]) => e[0] === "state" && e[1] === "end-restore"),
      ).toHaveLength(1);
      expect(
        await (
          await request.get(base + "/receipts/" + parent.intent.id)
        ).json(),
      ).toEqual(parent);
      await chooseWorkspaceTask(page, "Changes");
      const ledger = page.getByRole("region", {
        name: "Change ledger",
        exact: true,
      });
      await ledger
        .getByRole("button", {
          name: "Details for native " + child.intent.id,
          exact: true,
        })
        .click();
      const lineage = ledger.getByRole("region", {
        name: "Recorded native recovery lineage",
        exact: true,
      });
      await expect(lineage).toContainText("Recorded controller name change");
      await expect(lineage).toContainText(
        "Renamed controller to Authored native wire controller",
      );
      await expect(lineage).toContainText(parent.intent.id);
      if (routed) {
        await page.setViewportSize({ width: 820, height: 1100 });
        await lineage.scrollIntoViewIfNeeded();
        await page.screenshot({
          path: info.outputPath("routed-name-lineage.png"),
          fullPage: true,
        });
      }
    } finally {
      peer.close();
    }
  });
}
