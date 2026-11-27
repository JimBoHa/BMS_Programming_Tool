import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chooseWorkspaceTask } from "./workspace-navigation";
import {
  startPointPeer,
  openPointInspection,
  changePointController,
  readPointStatus,
  disconnectPointInterface,
} from "./point-status-workspace";
const root = fileURLToPath(new URL("../..", import.meta.url));
test.afterEach(async ({ request }) => disconnectPointInterface(request));

test("native point quality and command evidence remain distinct and exact on export", async ({
  page,
}) => {
  const server = await startPointPeer();
  try {
    const panel = await openPointInspection(page, server);
    const selectionReads = server.reads();
    expect(selectionReads).toBeGreaterThan(0);
    await panel
      .getByLabel("Read optional priority slots and relinquish defaults", {
        exact: true,
      })
      .check();
    expect(server.reads()).toBe(selectionReads);
    await readPointStatus(panel);
    expect(server.reads()).toBeGreaterThan(selectionReads);
    const evidence = panel.getByLabel("Native point evidence report", {
      exact: true,
    });
    await expect(evidence).toContainText("degrees-fahrenheit");
    await expect(evidence).toContainText("no-fault-detected");
    await expect(evidence).toContainText("[0,0,0,0]");
    await expect(evidence).toContainText("Not established");
    const pending = page.waitForEvent("download");
    await panel
      .getByRole("button", { name: "Export exact point evidence", exact: true })
      .click();
    const file = (await (await pending).path())!;
    expect(
      execFileSync(
        path.join(root, ".venv/bin/python"),
        [
          "-c",
          `
import hashlib,json,math,sys
raw=open(sys.argv[1],'rb').read();d=json.loads(raw);seal=d.pop('evidence_sha256')
assert hashlib.sha256(json.dumps(d,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()==seal
p=d['objects'][1]['properties'];assert p['priority-array']['elements'][0]['value']=={'type':'null','value':None}
assert math.copysign(1,p['priority-array']['elements'][1]['value']['value'])==-1
assert b'"value":-0.0' in raw and b'"value":2.0' in raw
assert d['objects'][0]['properties']['units']['value']['name']=='degrees-fahrenheit'
print('verified')
`,
          file,
        ],
        { encoding: "utf8" },
      ).trim(),
    ).toBe("verified");
    const count = server.reads();
    await panel
      .getByRole("button", {
        name: "Refresh retained point reports",
        exact: true,
      })
      .click();
    await panel
      .getByText("Retained point reports and limits", { exact: true })
      .click();
    await panel
      .getByRole("button", { name: /^Open point report/ })
      .last()
      .click();
    await expect(evidence).toBeVisible();
    expect(server.reads()).toBe(count);
  } finally {
    await server.stop();
  }
});

test("routed optional native unsupported quality remains partial and does not imply bad health", async ({
  page,
}) => {
  const server = await startPointPeer(true, "unsupported");
  try {
    const panel = await openPointInspection(page, server, true);
    await readPointStatus(panel);
    const evidence = panel.getByLabel("Native point evidence report", {
      exact: true,
    });
    await expect(evidence).toContainText("partial");
    await expect(evidence).toContainText("unsupported_property");
    await expect(evidence).toContainText("Not established");
    await expect(evidence).toContainText(
      `device,42 at 3001:7 via 127.0.0.1:${server.port} / DNET 3001`,
    );
    await panel
      .getByText("Complete point report and transport provenance", {
        exact: true,
      })
      .click();
    await expect(evidence).toContainText('"npdu_source": "3001:7"');
  } finally {
    await server.stop();
  }
});
for (const action of ["source", "receipt", "navigation"] as const)
  test(`late point export discarded after ${action} change`, async ({
    page,
  }) => {
    const server = await startPointPeer();
    const next = action === "source" ? await startPointPeer() : null;
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    let entered!: () => void;
    const started = new Promise<void>((resolve) => {
      entered = resolve;
    });
    let downloads = 0;
    page.on("download", () => downloads++);
    try {
      const panel = await openPointInspection(page, server);
      await readPointStatus(panel);
      if (action === "receipt") {
        await readPointStatus(panel);
        await panel
          .getByRole("button", {
            name: "Refresh retained point reports",
            exact: true,
          })
          .click();
        await panel
          .getByText("Retained point reports and limits", { exact: true })
          .click();
      }
      await page.route("**/api/bacnet/point-status/export", async (route) => {
        const response = await route.fetch();
        entered();
        await gate;
        await route.fulfill({ response });
      });
      await panel
        .getByRole("button", {
          name: "Export exact point evidence",
          exact: true,
        })
        .click();
      await started;
      if (next) await changePointController(page, next);
      else if (action === "receipt")
        await panel
          .getByRole("button", { name: /^Open point report/ })
          .first()
          .click();
      else await chooseWorkspaceTask(page, "Program");
      release();
      await page.waitForTimeout(350);
      expect(downloads).toBe(0);
    } finally {
      release();
      await server.stop();
      await next?.stop();
    }
  });
test("cancel and navigation stop point reads without polling or retries", async ({
  page,
  request,
}) => {
  const server = await startPointPeer(false, "hold");
  try {
    const panel = await openPointInspection(page, server);
    await server.hold();
    const setupReads = server.reads();
    await panel
      .getByRole("button", { name: "Inspect native point status", exact: true })
      .click();
    await expect.poll(server.reads).toBe(setupReads + 1);
    await panel
      .getByRole("button", { name: "Cancel point inspection", exact: true })
      .click();
    await expect(
      panel.getByLabel("Native point evidence report", { exact: true }),
    ).toContainText("cancelled");
    await page.waitForTimeout(150);
    expect(server.reads()).toBe(setupReads + 1);
    await panel
      .getByRole("button", { name: "Inspect native point status", exact: true })
      .click();
    await expect.poll(server.reads).toBe(setupReads + 2);
    const cancelled = page.waitForResponse((response) =>
      response.url().endsWith("/api/bacnet/point-status/cancel"),
    );
    await chooseWorkspaceTask(page, "Program");
    expect((await cancelled).ok()).toBe(true);
    await expect
      .poll(
        async () =>
          (await (await request.get("/api/bacnet/point-status/profile")).json())
            .active_operation,
      )
      .toBeNull();
  } finally {
    await server.stop();
  }
});

test("late point read cannot populate a newly selected source", async ({
  page,
}) => {
  const server = await startPointPeer();
  const next = await startPointPeer();
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let entered!: () => void;
  const started = new Promise<void>((resolve) => {
    entered = resolve;
  });
  try {
    const panel = await openPointInspection(page, server);
    await page.route("**/api/bacnet/point-status/read", async (route) => {
      const response = await route.fetch();
      entered();
      await gate;
      await route.fulfill({ response });
    });
    await panel
      .getByRole("button", { name: "Inspect native point status", exact: true })
      .click();
    await started;
    await changePointController(page, next);
    release();
    await expect(
      panel.getByRole("button", {
        name: "Inspect native point status",
        exact: true,
      }),
    ).toBeEnabled();
    await expect(
      panel.getByLabel("Native point evidence report", { exact: true }),
    ).toHaveCount(0);
  } finally {
    release();
    await server.stop();
    await next.stop();
  }
});
