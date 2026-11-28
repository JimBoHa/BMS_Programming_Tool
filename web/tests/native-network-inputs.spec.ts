import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { expect } from "@playwright/test";
import {
  nativeBase,
  openSnapshot,
  snapshotFixture,
} from "./native-snapshot-restore-browser-fixture";

const base = nativeBase + "/network-inputs";
const test = snapshotFixture();
test("inspect, compare and reopen network input priorities in the restore workflow", async ({
  page,
  snapshot,
}) => {
  const { seeded } = snapshot;
  const { panel } = await openSnapshot(page, seeded);
  const section = panel.getByRole("region", {
    name: "Network input command readings",
  });
  const capture = seeded.original;
  const baseline = "a".repeat(32),
    next = "b".repeat(32);
  const readings = new Map<string, string>();
  const field: string[] = [];
  let wrong = false;
  await page.route("**" + base + "/**", async (route) => {
    const url = new URL(route.request().url()).pathname;
    let raw: string;
    if (url.endsWith("/read")) {
      const request = route.request().postDataJSON();
      expect(request).toMatchObject({
        ...seeded.target,
        capture_id: capture.id,
        snapshot_sha256: capture.snapshot_evidence_sha256,
        offset: 0,
        limit: 16,
      });
      const compared = !!request.baseline_id;
      if (compared) expect(request.baseline_id).toBe(baseline);
      field.push(request.operation_id);
      const slots = Array.from(
        { length: 16 },
        () =>
          ({ type: "null", value: null }) as {
            type: string;
            value: number | null;
          },
      );
      const active = { type: "real", value: 0 };
      if (!compared) slots[7] = active;
      const id = compared ? next : baseline;
      const report = {
        profile: "native-network-input-commands/1",
        read_only: true,
        id,
        evidence_sha256: "c".repeat(64),
        source_sha256: capture.files["3"].sha256,
        selection: {
          target: seeded.target,
          capture_id: wrong ? next : capture.id,
          snapshot_sha256: capture.snapshot_evidence_sha256,
          offset: 0,
          limit: 16,
          scope: "root-exposed-commandable-file-3",
        },
        finished_at: "2026-01-01T10:00:00Z",
        input_count: 1,
        unclassified_root_inputs: [],
        baseline_id: compared ? baseline : null,
        points: [
          {
            object: "analog-value,11",
            name: "Room target",
            verified: true,
            unavailable: {},
            values: {
              "present-value": compared ? 21 : 0,
              "relinquish-default": 21,
              "priority-array": slots,
            },
          },
        ],
        comparison: compared
          ? [
              {
                object: "analog-value,11",
                status: "changed",
                priority_changes: [
                  { priority: 8, before: active, after: slots[7] },
                ],
                changed_fields: ["present-value"],
              },
            ]
          : null,
      };
      raw = JSON.stringify(report);
      if (!wrong) readings.set(id, raw);
    } else if (url.includes("/history/")) {
      raw = JSON.stringify(
        Array.from(readings.keys())
          .reverse()
          .map((id) => ({
            id,
            finished_at: "2026-01-01T10:00:00Z",
            offset: 0,
            limit: 16,
            verified: 1,
            points: 1,
          })),
      );
    } else raw = readings.get(url.split("/").at(-1)!)!;
    await route.fulfill({
      contentType: "application/json",
      headers: {
        "X-Studio-Artifact-Sha256": createHash("sha256")
          .update(raw)
          .digest("hex"),
      },
      body: raw,
    });
  });
  const summary = panel.getByText(
    "Check network inputs before and after restart",
    { exact: true },
  );
  await summary.focus();
  await page.keyboard.press("Enter");
  await expect(
    section.getByRole("button", { name: "Compare with baseline" }),
  ).toBeDisabled();
  await section.getByRole("button", { name: "List saved readings" }).click();
  await expect(section.getByRole("status")).toContainText("No saved readings");
  expect(field).toHaveLength(0);
  await section.getByRole("button", { name: "Read network inputs" }).click();
  await expect(section.getByRole("table")).toContainText("P8 0");
  await section.getByRole("button", { name: "Compare with baseline" }).click();
  await expect(section.getByRole("table")).toContainText("P8 0 → Released");
  await expect(section.getByRole("table")).toContainText(
    "Other changes: present-value",
  );
  const delivery = page.waitForEvent("download");
  await section.getByRole("button", { name: "Save exact reading" }).click();
  const download = await delivery;
  expect(await readFile((await download.path())!, "utf8")).toBe(
    readings.get(next),
  );
  await section.getByRole("button", { name: "List saved readings" }).click();
  await section.getByLabel("Baseline reading").selectOption(baseline);
  await section.getByRole("button", { name: "Open saved reading" }).click();
  await expect(section.getByRole("table")).toContainText("P8 0");
  expect(field).toHaveLength(2);
  wrong = true;
  await section.getByRole("button", { name: "Compare with baseline" }).click();
  await expect(section.getByRole("status")).toContainText("does not match");
  wrong = false;
  await section.getByRole("button", { name: "Compare with baseline" }).click();
  await expect(section.getByRole("table")).toContainText("P8 0 → Released");
  await section.getByRole("table").scrollIntoViewIfNeeded();
});

test("local captures permit only local network input history while disconnected", async ({
  page,
  snapshot,
}) => {
  const { panel } = await openSnapshot(page, snapshot.seeded, true, false);
  const calls: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes(base + "/read")) calls.push(r.url());
  });
  await panel
    .getByText("Check network inputs before and after restart", { exact: true })
    .click();
  const area = panel.getByRole("region", {
    name: "Network input command readings",
  });
  await expect(
    area.getByRole("button", { name: "Read network inputs" }),
  ).toBeDisabled();
  await area.getByRole("button", { name: "List saved readings" }).click();
  await expect(area.getByRole("status")).toContainText("No saved readings");
  expect(calls).toEqual([]);
});
