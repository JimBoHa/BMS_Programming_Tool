import { test, expect, type Page, type Locator } from "@playwright/test";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import {
  openScheduleController,
  scheduleTracePeer,
} from "./schedule-trace-peer";

type Peer = Awaited<ReturnType<typeof scheduleTracePeer>>;
async function usingPeer(
  routed: boolean,
  action: (peer: Peer) => Promise<void>,
) {
  const peer = await scheduleTracePeer(routed);
  let primary: unknown, cleanup: unknown;
  try {
    await action(peer);
  } catch (failure) {
    primary = failure;
  }
  try {
    const audit = await peer.stop();
    await test.info().attach("authored-peer-audit", {
      body: Buffer.from(JSON.stringify(audit)),
      contentType: "application/json",
    });
  } catch (failure) {
    cleanup = failure;
  }
  if (primary && cleanup)
    throw new AggregateError(
      [primary, cleanup],
      "UDP observation case and cleanup failed",
    );
  if (primary) throw primary;
  if (cleanup) throw cleanup;
}
test.afterEach(async ({ request }) => {
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  expect(
    (await request.post("/api/bacnet/disconnect", { headers, data: {} })).ok(),
  ).toBeTruthy();
});
async function selectTrace(panel: Locator) {
  await panel.getByText("Read diagnostics", { exact: true }).click();
  await panel
    .getByLabel("Include one-property Schedule trace", { exact: true })
    .check();
  await panel
    .getByLabel("Trace Calendar/Schedule object", { exact: true })
    .fill("schedule,1");
  return panel.getByLabel("Include owned UDP callback observations", {
    exact: true,
  });
}
async function read(panel: Locator) {
  await panel
    .getByRole("button", { name: "Read native schedules", exact: true })
    .click();
  await expect(
    panel.getByLabel("Schedule evidence report", { exact: true }),
  ).toBeVisible();
  await expect(
    panel.getByRole("button", { name: "Cancel schedule read", exact: true }),
  ).toBeDisabled();
}
async function download(page: Page, button: Locator) {
  const pending = page.waitForEvent("download");
  await button.click();
  return readFileSync((await (await pending).path())!);
}

for (const routed of [false, true])
  test(`${routed ? "routed" : "direct"} optional owned UDP callbacks retain actual response bytes without another read`, async ({
    page,
    request,
  }, info) => {
    await usingPeer(routed, async (peer) => {
      const panel = await openScheduleController(page, request, peer, routed);
      const udp = await selectTrace(panel);
      await expect(udp).not.toBeChecked();
      await udp.focus();
      await page.keyboard.press("Space");
      await expect(udp).toBeChecked();
      const before = peer.reads();
      await read(panel);
      const trace = panel.getByRole("region", {
        name: "Schedule property diagnostic trace",
        exact: true,
      });
      await expect(trace).toContainText(
        "Owned UDP callback observations requested",
      );
      const original = await download(
        page,
        trace.getByRole("button", {
          name: "Download original Schedule diagnostic bundle",
          exact: true,
        }),
      );
      const envelope = JSON.parse(original.toString());
      const core = Buffer.from(envelope.core_report_json, "utf8"),
        report = JSON.parse(core.toString());
      expect(envelope.include_udp_ingress).toBe(true);
      expect(envelope.trace.udp_ingress_requested).toBe(true);
      expect(report.complete).toBe(true);
      expect(createHash("sha256").update(core).digest("hex")).toBe(
        envelope.core_report_sha256,
      );
      const packets = envelope.trace.events.filter(
        (row: any) => row.event === "owned_udp_callback_enter",
      );
      expect(packets).toHaveLength(1);
      const row =
        report.objects[1].properties["list-of-object-property-references"];
      expect(packets[0].sha256).toBe(row.transport_evidence.udp_payload_sha256);
      expect(
        createHash("sha256")
          .update(Buffer.from(packets[0].prefix_hex, "hex"))
          .digest("hex"),
      ).toBe(packets[0].sha256);
      expect(packets[0].peer_port).toBe(Number(peer.endpoint.split(":")[1]));
      expect(packets[0].association).toContain("not a matched response");
      expect(
        (
          await download(
            page,
            panel.getByRole("button", {
              name: "Export exact schedule evidence",
              exact: true,
            }),
          )
        ).equals(core),
      ).toBe(true);
      expect(peer.reads() - before).toBe(28);
      await trace.scrollIntoViewIfNeeded();
      await page.screenshot({ path: info.outputPath("owned-udp-trace.png") });
      // Disabling only this observation scope retires the old pair, then a new
      // explicit read retains the original multiplexer-only behavior.
      await udp.uncheck();
      await expect(trace).toHaveCount(0);
      await expect(
        panel.getByRole("button", {
          name: "Export exact schedule evidence",
          exact: true,
        }),
      ).toBeDisabled();
      await read(panel);
      const off = JSON.parse(
        (
          await download(
            page,
            trace.getByRole("button", {
              name: "Download original Schedule diagnostic bundle",
              exact: true,
            }),
          )
        ).toString(),
      );
      expect(off.include_udp_ingress).toBe(false);
      expect(
        off.trace.events.some(
          (row: any) => row.event === "owned_udp_callback_enter",
        ),
      ).toBe(false);
      expect(peer.reads() - before).toBe(56);
    });
  });

for (const changed of ["envelope", "trace"])
  test(`mismatched ${changed} UDP scope cannot authorize displayed evidence`, async ({
    page,
    request,
  }) => {
    await usingPeer(false, async (peer) => {
      const panel = await openScheduleController(page, request, peer);
      await (await selectTrace(panel)).check();
      await page.route(
        "**/api/bacnet/schedules/read-diagnostics",
        async (route) => {
          const response = await route.fetch({ maxRetries: 0 }),
            data = await response.json();
          if (changed === "envelope") data.include_udp_ingress = false;
          else data.trace.udp_ingress_requested = false;
          await route.fulfill({ response, json: data });
        },
      );
      const before = peer.reads();
      await panel
        .getByRole("button", { name: "Read native schedules", exact: true })
        .click();
      await expect(panel.getByRole("alert")).toContainText("invalid");
      await expect(
        panel.getByLabel("Schedule evidence report", { exact: true }),
      ).toHaveCount(0);
      await expect(
        panel.getByRole("button", {
          name: "Export exact schedule evidence",
          exact: true,
        }),
      ).toBeDisabled();
      expect(peer.reads() - before).toBe(28);
    });
  });
