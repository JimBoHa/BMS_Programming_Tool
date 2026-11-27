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
import { readFileSync } from "node:fs";
const root = fileURLToPath(new URL("../..", import.meta.url));
test.afterEach(async ({ request }) => disconnectPointInterface(request));

for (const routed of [false, true]) {
  test(`opt-in ${routed ? "routed" : "direct"} trace downloads original envelope and exact native core bytes`, async ({
    page,
  }) => {
    const server = await startPointPeer(routed);
    try {
      const panel = await openPointInspection(page, server, routed);
      const selectionReads = server.reads();
      expect(selectionReads).toBeGreaterThan(0);
      const toggle = panel.getByLabel(
        "Include diagnostic trace for this read",
        { exact: true },
      );
      await expect(toggle).not.toBeChecked();
      await toggle.check();
      await page.request.get("/api/session");
      expect(server.reads()).toBe(selectionReads);
      await panel
        .getByText("Read optional priority slots and relinquish defaults", {
          exact: true,
        })
        .check();
      let received: Buffer | undefined;
      await page.route(
        "**/api/bacnet/point-status/read-diagnostics",
        async (route) => {
          const response = await route.fetch({
            maxRedirects: 0,
            maxRetries: 0,
          });
          expect(response.status()).toBe(200);
          received = await response.body();
          expect(received.length).toBe(
            Number(response.headers()["content-length"]),
          );
          await route.fulfill({ response, body: received });
        },
      );
      await readPointStatus(panel);
      expect(received).toBeDefined();
      const original = received!,
        envelope = JSON.parse(original.toString());
      const core = Buffer.from(envelope.core_report_json, "utf8"),
        report = JSON.parse(envelope.core_report_json);
      await expect(
        panel.getByRole("region", {
          name: "Read diagnostic trace",
          exact: true,
        }),
      ).toContainText("Diagnostic capture truncated");
      expect(report.complete).toBe(true);
      await expect
        .poll(server.reads)
        .toBe(selectionReads + report.read_budget.requests);
      const count = server.reads();
      let downloading = page.waitForEvent("download");
      await panel
        .getByRole("button", {
          name: "Download original diagnostic bundle",
          exact: true,
        })
        .click();
      const file = (await (await downloading).path())!;
      expect(readFileSync(file)).toEqual(original);
      execFileSync(
        path.join(root, ".venv/bin/python"),
        [
          "-c",
          "import json,hashlib,sys;r=json.load(open(sys.argv[1]));b=r['core_report_json'].encode();assert hashlib.sha256(b).hexdigest()==r['core_report_sha256'];c=json.loads(b);assert c['id']==r['core_report_id'];assert r['trace']['profile']=='studio-readproperty-phase-trace/1';assert 'not all UDP ingress' in r['trace']['visibility'];assert 'trace' not in c;u=dict(c);s=u.pop('evidence_sha256');assert hashlib.sha256(json.dumps(u,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()==s",
          file,
        ],
        { cwd: root },
      );
      downloading = page.waitForEvent("download");
      await panel
        .getByRole("button", {
          name: "Export exact point evidence",
          exact: true,
        })
        .click();
      const coreFile = (await (await downloading).path())!;
      expect(readFileSync(coreFile)).toEqual(core);
      expect(core.toString()).toContain('"value":-0.0');
      expect(core.toString()).toContain('"value":2.0');
      expect(server.reads()).toBe(count);
      await toggle.uncheck();
      await expect(
        panel.getByRole("region", {
          name: "Read diagnostic trace",
          exact: true,
        }),
      ).toHaveCount(0);
      expect(server.reads()).toBe(count);
    } finally {
      await server.stop();
    }
  });
}

test("default-off keeps the original native read endpoint and does not manufacture a trace", async ({
  page,
}) => {
  const server = await startPointPeer();
  try {
    const panel = await openPointInspection(page, server);
    const receiving = page.waitForResponse((r) =>
      r.url().endsWith("/api/bacnet/point-status/read"),
    );
    await readPointStatus(panel);
    const report = await (await receiving).json();
    expect(report.profile).toBe("native-point-status/1");
    expect(report.format).toBeUndefined();
    await expect(
      panel.getByRole("region", { name: "Read diagnostic trace", exact: true }),
    ).toHaveCount(0);
    await expect(
      panel.getByRole("button", {
        name: "Download original diagnostic bundle",
        exact: true,
      }),
    ).toHaveCount(0);
  } finally {
    await server.stop();
  }
});

for (const action of ["source", "navigation"]) {
  test(`held diagnostic ${action} reply cannot repopulate stale evidence or downloads`, async ({
    page,
  }) => {
    const server = await startPointPeer();
    const next = action === "source" ? await startPointPeer() : null;
    let release!: () => void;
    try {
      const panel = await openPointInspection(page, server);
      await panel
        .getByLabel("Include diagnostic trace for this read", { exact: true })
        .check();
      let seen!: () => void, done!: () => void;
      const entered = new Promise<void>((r) => (seen = r)),
        gate = new Promise<void>((r) => (release = r)),
        completed = new Promise<void>((r) => (done = r));
      await page.route(
        "**/api/bacnet/point-status/read-diagnostics",
        async (route) => {
          const response = await route.fetch({
            maxRedirects: 0,
            maxRetries: 0,
          });
          seen();
          await gate;
          await route.fulfill({ response });
          done();
        },
      );
      await panel
        .getByRole("button", {
          name: "Inspect native point status",
          exact: true,
        })
        .click();
      await entered;
      if (next) await changePointController(page, next);
      else await chooseWorkspaceTask(page, "Program");
      release();
      await completed;
      await expect(
        page.getByRole("region", {
          name: "Read diagnostic trace",
          exact: true,
        }),
      ).toHaveCount(0);
      await expect(
        page.getByRole("button", {
          name: "Download original diagnostic bundle",
          exact: true,
        }),
      ).toHaveCount(0);
      if (action === "source")
        await expect(
          panel.getByLabel("Native point evidence report", { exact: true }),
        ).toHaveCount(0);
    } finally {
      release?.();
      await server.stop();
      await next?.stop();
    }
  });
}
for (const corruption of ["core-hash", "core-id", "trace-profile"]) {
  test(`corrupted ${corruption} cannot authorize diagnostic exports`, async ({
    page,
  }) => {
    const server = await startPointPeer();
    try {
      const panel = await openPointInspection(page, server);
      await panel
        .getByLabel("Include diagnostic trace for this read", { exact: true })
        .check();
      await page.route(
        "**/api/bacnet/point-status/read-diagnostics",
        async (route) => {
          const response = await route.fetch({
              maxRedirects: 0,
              maxRetries: 0,
            }),
            value = await response.json();
          if (corruption === "core-hash")
            value.core_report_sha256 = "0".repeat(64);
          else if (corruption === "core-id")
            value.core_report_id = "0".repeat(32);
          else value.trace.profile = "unsupported-trace/9";
          await route.fulfill({ response, json: value });
        },
      );
      await panel
        .getByRole("button", {
          name: "Inspect native point status",
          exact: true,
        })
        .click();
      await expect(panel.getByRole("alert")).toContainText(
        corruption === "core-id" ? "another core report" : "invalid",
      );
      await expect(
        panel.getByRole("button", {
          name: "Download original diagnostic bundle",
          exact: true,
        }),
      ).toHaveCount(0);
      await expect(
        panel.getByLabel("Native point evidence report", { exact: true }),
      ).toHaveCount(0);
    } finally {
      await server.stop();
    }
  });
}
for (const declared of [false, true]) {
  test(`plain-core fallback ${declared ? "with" : "without"} explicit unavailable header preserves its qualification`, async ({
    page,
  }) => {
    const server = await startPointPeer();
    let original: Buffer | undefined;
    try {
      const panel = await openPointInspection(page, server);
      await panel
        .getByLabel("Include diagnostic trace for this read", { exact: true })
        .check();
      await page.route(
        "**/api/bacnet/point-status/read-diagnostics",
        async (route) => {
          const response = await route.fetch({
              maxRedirects: 0,
              maxRetries: 0,
            }),
            value = await response.json();
          original = Buffer.from(value.core_report_json, "utf8");
          const headers = { ...response.headers() };
          if (declared) headers["x-studio-diagnostics"] = "unavailable";
          await route.fulfill({ response, headers, body: original });
        },
      );
      await panel
        .getByRole("button", {
          name: "Inspect native point status",
          exact: true,
        })
        .click();
      if (declared) {
        await expect(
          panel.getByRole("region", {
            name: "Read diagnostic trace",
            exact: true,
          }),
        ).toContainText("Diagnostic capture unavailable");
        const downloading = page.waitForEvent("download");
        await panel
          .getByRole("button", {
            name: "Export exact point evidence",
            exact: true,
          })
          .click();
        expect(readFileSync((await (await downloading).path())!)).toEqual(
          original,
        );
      } else {
        await expect(panel.getByRole("alert")).toContainText(
          "lacks its explicit server state",
        );
        await expect(
          panel.getByLabel("Native point evidence report", { exact: true }),
        ).toHaveCount(0);
      }
      await expect(
        panel.getByRole("button", {
          name: "Download original diagnostic bundle",
          exact: true,
        }),
      ).toHaveCount(0);
    } finally {
      await server.stop();
    }
  });
}

test("cancelled diagnostic read retains only the existing cancelled core result without another query", async ({
  page,
}) => {
  const server = await startPointPeer(false, "hold");
  try {
    const panel = await openPointInspection(page, server);
    await server.hold();
    const selectionReads = server.reads();
    await panel
      .getByLabel("Include diagnostic trace for this read", { exact: true })
      .check();
    await panel
      .getByRole("button", { name: "Inspect native point status", exact: true })
      .click();
    await expect.poll(server.reads).toBe(selectionReads + 1);
    await panel
      .getByRole("button", { name: "Cancel point inspection", exact: true })
      .click();
    await expect(
      panel.getByLabel("Native point evidence report", { exact: true }),
    ).toContainText("cancelled");
    await expect(
      panel.getByRole("region", { name: "Read diagnostic trace", exact: true }),
    ).toBeVisible();
    expect(server.reads()).toBe(selectionReads + 1);
  } finally {
    await server.stop();
  }
});
