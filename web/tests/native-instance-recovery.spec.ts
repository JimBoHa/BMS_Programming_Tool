import {
  test,
  expect,
  type Page,
  type Locator,
  type APIRequestContext,
} from "@playwright/test";
import { readFileSync } from "node:fs";
import { python } from "./caf-native-fixture";
import { nativeDefaultPeer } from "./native-default-peer";
import { freePort } from "./workflow-peer";
import { chooseWorkspaceTask } from "./workspace-navigation";
import { previousInstanceMatches } from "../src/nativeInstanceRecoveryContract";

const base = "/api/bacnet/controller/native-application";
const panel = (page: Page) =>
  page.getByRole("region", {
    name: "Native application instance commissioning",
    exact: true,
  });
const proposal = (page: Page) =>
  page.getByRole("region", {
    name: "Previous controller instance proposal",
    exact: true,
  });
const number = (p: Locator) =>
  p.getByLabel("New application Device instance (0–4194302)", { exact: true });
function seed(already = false) {
  return JSON.parse(
    python(
      `
import sys,json,base64
from pathlib import Path
from tests.test_native_instance_recovery import setup,current_source,rekey
from tests.test_caf_native_correlation import caf_source
from bms_tool.native_applications import NativeApplications
s,service,request,before,post,files=setup(Path(sys.argv[1]))
if sys.argv[2]=='already':
 output,_=NativeApplications.compile(files,5136)
 request=current_source(s,request,files|{3:output,11:rekey(files[11],5336,5136)},device='device,5136')
src={k:request[k] for k in ('capture_id','snapshot_sha256')};source=service.source(src)
capture=source|{'id':source['capture_id'],'snapshot_evidence_sha256':source['snapshot_sha256'],'identity':source['identity']|{'device':source['target']['device']}}
print(json.dumps({'request':request,'receipt':s.receipt(request['receipt_id']),'report':service.prepare(request),'capture':capture,'caf':base64.b64encode(caf_source().original).decode()}))
`,
      process.env.BMS_TEST_COMPILER_STATE!,
      already ? "already" : "changed",
    ),
  );
}
async function headers(request: APIRequestContext) {
  return {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
}
test.beforeEach(async ({ request }) => {
  expect(
    (
      await request.post("/api/bacnet/disconnect", {
        headers: await headers(request),
        data: {},
      })
    ).ok(),
  ).toBe(true);
});
async function openInstance(page: Page) {
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
    .selectOption("instance");
  await page
    .getByLabel("Instance change method", { exact: true })
    .selectOption("native");
  await expect(panel(page)).toBeVisible();
  return panel(page);
}
async function expand(p: Locator) {
  const summary = p
    .locator("summary")
    .filter({ hasText: /^Previous controller instance$/ });
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
    name: "instance-reference.caf",
    mimeType: "application/octet-stream",
    buffer: Buffer.from(data.caf, "base64"),
  });
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("instance-reference.caf");
  const p = await openInstance(page);
  await expand(p);
  await p
    .getByRole("button", {
      name: "Load retained instance backups",
      exact: true,
    })
    .click();
  await p
    .getByLabel("Instance recovery backup", { exact: true })
    .selectOption(data.request.capture_id);
  await expect(
    p.getByLabel("Captured native application", { exact: true }),
  ).toContainText("Authored controller");
  await p
    .getByLabel("Retained native transfer receipts", { exact: true })
    .selectOption(data.request.receipt_id);
  await expect(
    p.getByLabel("Native application transfer receipt", { exact: true }),
  ).toContainText("5136 → 5336");
  return p;
}
async function prepare(p: Locator) {
  await p
    .getByRole("button", {
      name: "Prepare previous controller instance",
      exact: true,
    })
    .click();
  const result = p.getByRole("region", {
    name: "Previous controller instance proposal",
    exact: true,
  });
  await expect(result).toBeVisible();
  return result;
}

test("offline CAF entry keeps ordinary number draft, exact evidence, focus and phone navigation", async ({
  page,
  request,
}, info) => {
  const data = seed();
  expect(previousInstanceMatches(data.report, data.capture, data.receipt)).toBe(
    true,
  );
  await page.setViewportSize({ width: 390, height: 1100 });
  const field: string[] = [];
  page.on("request", (r) => {
    if (
      /\/native-application\/(capture|preview|apply|readback|instance\/recovery\/preview)$/.test(
        r.url(),
      )
    )
      field.push(r.url());
  });
  let exact = Buffer.alloc(0);
  await page.route(
    "**/native-application/instance/recovery/prepare",
    async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      exact = await response.body();
      await route.fulfill({ response });
    },
  );
  let p = await local(page, data);
  await number(p).fill("5151");
  const result = await prepare(p);
  await expect(result).toBeFocused();
  await expect(result).toContainText("does not allocate a number");
  await expect(number(p)).toHaveValue("5136");
  await expect(
    p.getByRole("button", {
      name: "Review application instance change",
      exact: true,
    }),
  ).toBeDisabled();
  const downloading = page.waitForEvent("download");
  await result
    .getByRole("button", {
      name: "Save exact instance recovery evidence",
      exact: true,
    })
    .click();
  expect(readFileSync((await (await downloading).path())!)).toEqual(exact);
  expect(JSON.parse(exact.toString()).origin.verified_after_capture_id).toBe(
    data.report.origin.verified_after_capture_id,
  );
  await chooseWorkspaceTask(page, "Points & I/O");
  p = await openInstance(page);
  await expect(proposal(page)).toBeVisible();
  await proposal(page)
    .getByRole("button", {
      name: "Return to ordinary instance draft",
      exact: true,
    })
    .click();
  await expect(proposal(page)).toHaveCount(0);
  await expect(number(p)).toHaveValue("5151");
  await expand(p);
  await prepare(p);
  await proposal(page).scrollIntoViewIfNeeded();
  await page.screenshot({
    path: info.outputPath("offline-instance-recovery.png"),
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(field).toEqual([]);
  expect(
    (await (await request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
});
test("already recorded old number supplies evidence without a live claim", async ({
  page,
}) => {
  const p = await local(page, seed(true));
  const result = await prepare(p);
  await expect(result).toContainText("already records the previous instance");
  await expect(result).toContainText("does not verify the current controller");
  await expect(
    p.getByRole("button", {
      name: "Review application instance change",
      exact: true,
    }),
  ).toBeDisabled();
});
for (const change of ["source", "task", "receipt", "visibility"]) {
  test(`held previous-instance reply retires on ${change} lifecycle`, async ({
    page,
  }) => {
    const data = seed(),
      other = seed();
    let p = await local(page, data);
    await number(p).fill("5151");
    let release!: () => void, arrived!: () => void, released!: () => void;
    const gate = new Promise<void>((done) => {
        release = done;
      }),
      held = new Promise<void>((done) => {
        arrived = done;
      }),
      complete = new Promise<void>((done) => {
        released = done;
      });
    await page.route(
      "**/native-application/instance/recovery/prepare",
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
          name: "Prepare previous controller instance",
          exact: true,
        })
        .click();
      await held;
      if (change === "visibility")
        await page.evaluate(() => {
          document.dispatchEvent(new Event("visibilitychange"));
          document.dispatchEvent(new Event("visibilitychange"));
        });
      else if (change === "receipt") {
        const select = p.getByLabel("Retained native transfer receipts", {
          exact: true,
        });
        await select.selectOption(other.request.receipt_id);
        await select.selectOption(data.request.receipt_id);
      } else {
        await chooseWorkspaceTask(page, "Points & I/O");
        p = await openInstance(page);
        if (change === "source") {
          await expand(p);
          await p
            .getByRole("button", {
              name: "Load retained instance backups",
              exact: true,
            })
            .click();
          const select = p.getByLabel("Instance recovery backup", {
            exact: true,
          });
          await select.selectOption(other.request.capture_id);
          await select.selectOption(data.request.capture_id);
        }
      }
      release();
      await complete;
      await expect(proposal(page)).toHaveCount(0);
      await expect(number(p)).toHaveValue("5151");
    } finally {
      release();
    }
  });
}
test("unbound verified-after source cannot replace an ordinary number draft", async ({
  page,
}) => {
  const data = seed(),
    p = await local(page, data);
  await number(p).fill("5151");
  const changed = structuredClone(data.report);
  changed.origin.verified_after_capture_id = "0".repeat(32);
  expect(previousInstanceMatches(changed, data.capture, data.receipt)).toBe(
    false,
  );
  await page.route(
    "**/native-application/instance/recovery/prepare",
    async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      await route.fulfill({ response, json: changed });
    },
  );
  await p
    .getByRole("button", {
      name: "Prepare previous controller instance",
      exact: true,
    })
    .click();
  await expect(p.getByRole("alert")).toContainText(
    "does not match this backup and receipt",
  );
  await expect(proposal(page)).toHaveCount(0);
  await expect(number(p)).toHaveValue("5151");
});

async function connect(
  page: Page,
  request: APIRequestContext,
  endpoint: string,
  routed: boolean,
) {
  expect(
    (
      await request.post(base + "/credentials", {
        headers: await headers(request),
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
  ).toContainText("Authored controller");
  return openInstance(page);
}
async function confirm(
  p: Locator,
  desired: string,
  action?: () => Promise<void>,
) {
  const reviewing = p
    .page()
    .waitForResponse(
      (r) =>
        r.url().endsWith("/native-application/preview") ||
        r.url().endsWith("/instance/recovery/preview"),
    );
  await p
    .getByRole("button", {
      name: "Review application instance change",
      exact: true,
    })
    .click();
  expect((await reviewing).ok()).toBe(true);
  const review = p.getByLabel("Reviewed native application transfer", {
    exact: true,
  });
  await expect(review).toContainText(desired);
  await review
    .getByRole("checkbox", {
      name: "I reserved this instance across the BACnet internetwork, including offline devices.",
      exact: true,
    })
    .check();
  await review
    .getByRole("checkbox", {
      name: "I reviewed this application transfer and its possible brief interruption of controller operation.",
      exact: true,
    })
    .check();
  if (action) await action();
  const applying = p
    .page()
    .waitForResponse(
      (r) =>
        r.url().endsWith("/native-application/apply") &&
        r.request().method() === "POST",
    );
  await review
    .getByRole("button", {
      name: "Apply application instance change",
      exact: true,
    })
    .click();
  const result = await (await applying).json();
  expect(result.result.status).toBe("verified");
  return result;
}
for (const routed of [false, true]) {
  test(`actual ${routed ? "routed" : "direct"} previous-instance transfer preserves values and records lineage`, async ({
    page,
    request,
  }, info) => {
    test.setTimeout(90000);
    const peer = await nativeDefaultPeer("consume", "instance");
    try {
      let p = await connect(
        page,
        request,
        routed ? peer.router : peer.direct,
        routed,
      );
      await p
        .getByRole("button", { name: "Read application backup", exact: true })
        .click();
      await number(p).fill("5336");
      const parent = await confirm(p, "5136 → 5336");
      await expect(
        page.getByLabel("Working context", { exact: true }),
      ).toContainText("device,5336");
      p = panel(page);
      await p
        .getByRole("button", { name: "Read application backup", exact: true })
        .click();
      await expect(
        p.getByLabel("Captured native application", { exact: true }),
      ).toContainText("Authored controller");
      await p
        .getByLabel("Retained native transfer receipts", { exact: true })
        .selectOption(parent.intent.id);
      await expand(p);
      await prepare(p);
      await expect(number(p)).toHaveValue("5136");
      const start = (await peer.command("stats")).events.length;
      const child = await confirm(p, "5336 → 5136", async () => {
        await peer.command("second17");
      });
      expect(child.intent.id).not.toBe(parent.intent.id);
      expect(child.intent.recovery_origin.parent_receipt_id).toBe(
        parent.intent.id,
      );
      expect(child.intent.recovery_origin.verified_after_capture_id).toBe(
        parent.result.verification_capture_id,
      );
      expect(
        child.result.preservation.application_identical_except_instance,
      ).toBe(true);
      expect(child.intent.old_name).toBe("Authored controller");
      expect(child.intent.new_name).toBe("Authored controller");
      const stats = await peer.command("stats");
      expect(stats.instance).toBe(5136);
      expect(stats.router_errors).toEqual([]);
      if (routed) {
        expect(
          stats.discovery_requests.map((row: any) => row.candidate),
        ).toEqual([5336, 5336, 5136, 5136]);
        expect(stats.discovery_responses).toEqual([]);
        expect(
          stats.events.filter((row: any[]) => row[0] === "who-is"),
        ).toEqual([
          ["who-is", 5336, 5336, 5136],
          ["who-is", 5336, 5336, 5136],
          ["who-is", 5136, 5136, 5336],
          ["who-is", 5136, 5136, 5336],
        ]);
      }
      const events = stats.events.slice(start);
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
      const source = await (
        await request.post(base + "/signal-default/source", {
          headers: await headers(request),
          data: { capture_id: child.result.verification_capture_id },
        })
      ).json();
      expect(
        source.fields.find((row: any) => row.ref === "controller/signal-11")
          .effective_value,
      ).toBe(17.5);
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
      await expect(lineage).toContainText(
        "Recorded controller instance change",
      );
      await expect(lineage).toContainText("Device 5336 to 5136");
      await expect(lineage).toContainText(parent.intent.id);
      if (routed) {
        await page.setViewportSize({ width: 820, height: 1100 });
        await lineage.scrollIntoViewIfNeeded();
        await page.screenshot({
          path: info.outputPath("routed-instance-lineage.png"),
          fullPage: true,
        });
      }
    } finally {
      peer.close();
    }
  });
}
