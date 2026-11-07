import { test, expect } from "./nativeScheduleWriteFixture";
import type { Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { python } from "./caf-native-fixture";
import {
  seedBatchEvidence,
  alteredBatchEvidence,
} from "./native-default-batch-evidence-fixture";
import {
  openNativeCompiler,
  chooseWorkspaceTask,
} from "./workspace-navigation";
const endpoint = "/default-batch/result/evidence";
const metadataHeader = "x-native-batch-evidence";

async function enter(page: Page, data: any, caf = false) {
  await page.goto("/");
  if (caf) {
    const chooser = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: /^Open a CAF file/ }).click();
    await (
      await chooser
    ).setFiles({
      name: "batch-result-match.caf",
      mimeType: "application/octet-stream",
      buffer: Buffer.from(data.caf, "base64"),
    });
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
  const comparison = transfer.getByRole("region", {
      name: "Retained source result comparison",
      exact: true,
    }),
    compare = comparison.getByRole("button", {
      name: "Compare retained source with recorded result",
      exact: true,
    });
  await expect(compare).toBeVisible();
  return { compiler, batch, field, transfer, comparison, compare, draft };
}
async function prepared(page: Page, data: any, caf = false) {
  const entered = await enter(page, data, caf);
  await entered.compare.click();
  await expect(entered.comparison.getByRole("table")).toBeVisible();
  const save = entered.comparison.getByRole("button", {
    name: "Save comparison evidence bundle",
    exact: true,
  });
  await expect(save).toBeEnabled();
  return { ...entered, save };
}
function inspectBundle(path: string, comparison: string) {
  return JSON.parse(
    python(
      `
import io,json,sys,zipfile
from pathlib import Path
from bms_tool.moi_identity import seal,sha
raw=Path(sys.argv[1]).read_bytes()
with zipfile.ZipFile(io.BytesIO(raw)) as archive:
 assert archive.testzip() is None
 manifest=json.loads(archive.read('manifest.json'))
 assert manifest['evidence_sha256']==seal({k:v for k,v in manifest.items() if k!='evidence_sha256'})
 assert manifest['comparison_sha256']==sys.argv[2]
 for name,detail in manifest['members'].items():
  data=archive.read(name);assert detail==dict(bytes=len(data),sha256=sha(data))
 print(json.dumps(dict(state=manifest['comparison_state'],captures=len(manifest['captures']),bytes=len(raw))))
`,
      path,
      comparison,
    ),
  );
}

for (const caf of [false, true])
  for (const phone of [false, true])
    test(`${caf ? "CAF" : "workspace"} ${phone ? "phone" : "desktop"} saves checked comparison evidence offline`, async ({
      page,
      request,
      nativeScheduleWriteServer,
    }, testInfo) => {
      if (phone) await page.setViewportSize({ width: 390, height: 844 });
      const data = seedBatchEvidence(nativeScheduleWriteServer.directory),
        calls: string[] = [];
      let original!: Buffer;
      page.on("request", (r) => {
        if (
          r.method() === "POST" &&
          new URL(r.url()).pathname.startsWith("/api/bacnet/")
        )
          calls.push(new URL(r.url()).pathname);
      });
      await page.route("**" + endpoint, async (route) => {
        const response = await route.fetch();
        original = await response.body();
        expect(original.length).toBeGreaterThan(0);
        await route.fulfill({ response, body: original });
      });
      const { save, draft } = await prepared(page, data, caf),
        download = page.waitForEvent("download");
      await save.click();
      const result = await download,
        path = (await result.path())!;
      expect(result.suggestedFilename()).toBe(
        `native-batch-evidence-${data.id}.zip`,
      );
      expect(readFileSync(path)).toEqual(original);
      const checked = inspectBundle(path, data.report.evidence_sha256);
      expect(checked.state).toBe("application-and-values-match");
      expect(checked.captures).toBe(2);
      await expect(draft).toHaveValue("12.");
      expect(calls).toEqual([
        "/api/bacnet/controller/native-application/signal-default/source",
        "/api/bacnet/controller/native-application/inspection/default-batch/source",
        "/api/bacnet/controller/native-application/default-batch/result/compare",
        "/api/bacnet/controller/native-application/default-batch/result/evidence",
      ]);
      expect(
        (await (await request.get("/api/session")).json()).field_network_open,
      ).toBe(false);
      await page.screenshot({
        path: testInfo.outputPath("comparison-evidence-download.png"),
        fullPage: true,
      });
    });
for (const kind of [
  "historical",
  "recovery",
  "different",
  "routed",
  "same-capture",
  "reencoded",
])
  test(`${kind} comparison exports its actual checked source roles`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const data = seedBatchEvidence(nativeScheduleWriteServer.directory, kind),
      { save } = await prepared(page, data),
      download = page.waitForEvent("download");
    await save.click();
    const result = inspectBundle(
      (await (await download).path())!,
      data.report.evidence_sha256,
    );
    expect(result.captures).toBe(kind === "same-capture" ? 1 : 2);
    expect(result.state).toBe(data.report.state);
  });
for (const change of ["task", "source", "same-receipt", "new-comparison"])
  test(`late evidence response cannot download after ${change} retirement`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const data = seedBatchEvidence(nativeScheduleWriteServer.directory);
    let release!: () => void,
      held = false,
      downloads = 0;
    const gate = new Promise<void>((r) => (release = r));
    await page.route("**" + endpoint, async (route) => {
      const response = await route.fetch(),
        body = await response.body();
      held = true;
      await gate;
      await route.fulfill({ response, body });
    });
    const { save, compiler, transfer, compare } = await prepared(page, data);
    page.on("download", () => downloads++);
    try {
      await save.click();
      await expect.poll(() => held).toBe(true);
      if (change === "task") {
        await chooseWorkspaceTask(page, "Overview");
        await openNativeCompiler(page);
      } else if (change === "source") {
        await compiler
          .getByLabel("Retained native backup", { exact: true })
          .selectOption(data.receipt.intent.backup_id);
        await compiler
          .getByRole("button", { name: "Open retained backup", exact: true })
          .click();
      } else if (change === "same-receipt")
        await transfer
          .getByRole("button", {
            name: "Load default batch receipt",
            exact: true,
          })
          .click();
      else {
        await compare.click();
        await expect(
          page.getByRole("button", {
            name: "Save comparison evidence bundle",
            exact: true,
          }),
        ).toBeEnabled();
      }
      const late = page.waitForResponse((r) => r.url().endsWith(endpoint));
      release();
      await (await late).finished();
      await expect(
        page.getByText("The evidence bundle does not match", { exact: false }),
      ).toHaveCount(0);
      expect(downloads).toBe(0);
    } finally {
      release();
    }
  });
test("coalesced field disclosure blocks the retained evidence callback before dispatch", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const data = seedBatchEvidence(nativeScheduleWriteServer.directory),
    { save, field } = await prepared(page, data);
  let calls = 0;
  page.on("request", (r) => {
    if (r.url().endsWith(endpoint)) calls++;
  });
  const button = await save.elementHandle(),
    summary = await field.locator(":scope > summary").elementHandle();
  await page.evaluate(
    ({ button, summary }) => {
      (summary as HTMLElement).click();
      (summary as HTMLElement).click();
      (button as HTMLElement).click();
    },
    { button, summary },
  );
  expect(calls).toBe(0);
});
for (const kind of ["pagehide", "visibility"])
  test(`${kind} discards a pending evidence response`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const data = seedBatchEvidence(nativeScheduleWriteServer.directory);
    let release!: () => void,
      held = false,
      downloads = 0;
    const gate = new Promise<void>((r) => (release = r));
    await page.route("**" + endpoint, async (route) => {
      const response = await route.fetch(),
        body = await response.body();
      held = true;
      await gate;
      await route.fulfill({ response, body });
    });
    const { save } = await prepared(page, data);
    page.on("download", () => downloads++);
    try {
      await save.click();
      await expect.poll(() => held).toBe(true);
      await page.evaluate((kind) => {
        if (kind === "pagehide") window.dispatchEvent(new Event("pagehide"));
        else document.dispatchEvent(new Event("visibilitychange"));
      }, kind);
      const late = page.waitForResponse((r) => r.url().endsWith(endpoint));
      release();
      await (await late).finished();
      expect(downloads).toBe(0);
    } finally {
      release();
    }
  });
for (const fault of ["header", "body", "manifest", "source"])
  test(`${fault} mismatch refuses the evidence download`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const data = seedBatchEvidence(nativeScheduleWriteServer.directory);
    let downloads = 0;
    await page.route("**" + endpoint, async (route) => {
      const response = await route.fetch(),
        raw = await response.body(),
        headers = { ...response.headers() },
        metadata = JSON.parse(headers[metadataHeader]);
      let body = raw;
      if (fault === "header") metadata.can_apply = true;
      else if (fault === "source") metadata.current_capture_id = "a".repeat(32);
      else if (fault === "body") {
        body = Buffer.from(raw);
        body[50] ^= 1;
      } else {
        const altered = alteredBatchEvidence(
          { ...data, bundle: raw.toString("base64"), metadata },
          "manifest-authority",
        );
        body = Buffer.from(altered.bundle, "base64");
        Object.assign(metadata, altered.metadata);
      }
      delete headers["content-length"];
      headers[metadataHeader] = JSON.stringify(metadata);
      await route.fulfill({ response, headers, body });
    });
    const { save, comparison } = await prepared(page, data);
    page.on("download", () => downloads++);
    await save.click();
    await expect(comparison.getByRole("alert")).toContainText(
      "does not match this comparison",
    );
    expect(downloads).toBe(0);
  });
test("a cached callback from a replaced report sends no export request", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const data = seedBatchEvidence(nativeScheduleWriteServer.directory),
    { save, compare } = await prepared(page, data);
  await save.evaluate((button) => {
    const key = Object.keys(button).find((k) => k.startsWith("__reactProps$"))!;
    (window as any).__retiredEvidence = (button as any)[key].onClick;
  });
  await compare.click();
  await expect(
    page.getByRole("button", {
      name: "Save comparison evidence bundle",
      exact: true,
    }),
  ).toBeEnabled();
  const calls = await page.evaluate(async () => {
    const original = window.fetch;
    let count = 0;
    window.fetch = async (...args: any[]) => {
      if (String(args[0]).endsWith("/default-batch/result/evidence")) {
        count++;
        throw Error("Blocked retained callback before server");
      }
      return (original as any)(...args);
    };
    try {
      await (window as any).__retiredEvidence();
      await Promise.resolve();
      return count;
    } finally {
      window.fetch = original;
    }
  });
  expect(calls).toBe(0);
});
