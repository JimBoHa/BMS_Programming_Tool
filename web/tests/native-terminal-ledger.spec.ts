import { test, expect } from "./nativeScheduleWriteFixture";
import { readFileSync } from "node:fs";
import {
  seedTerminalLedger,
  openTerminalLedger,
  openTerminalEvidence,
} from "./native-terminal-ledger-fixture";

for (const history of [false, true])
  for (const width of [1440, 390]) {
    test(`${history ? "History" : "Changes"} terminal record remains local at ${width}px`, async ({
      page,
      request,
      nativeScheduleWriteServer,
    }, info) => {
      const f = seedTerminalLedger(nativeScheduleWriteServer.directory),
        calls: string[] = [];
      await page.setViewportSize({ width, height: 1000 });
      page.on("request", (r) => {
        if (
          r.method() === "POST" &&
          new URL(r.url()).pathname.startsWith("/api/bacnet/")
        )
          calls.push(r.url());
      });
      await openTerminalLedger(page, history);
      await expect(
        page.getByRole("region", { name: "Recorded changes", exact: true }),
      ).toContainText("Move analog input · UI IN1 to UI IN3");
      const evidence = await openTerminalEvidence(page, f.id),
        terminal = evidence.getByRole("region", {
          name: "Recorded terminal movement",
          exact: true,
        });
      await expect(terminal).toContainText("analog-input,101");
      await expect(terminal).toContainText("UI IN1");
      await expect(terminal).toContainText("UI IN3");
      await expect(
        terminal.getByRole("table", {
          name: "Preserved recorded input configuration",
          exact: true,
        }),
      ).toBeVisible();
      const table = terminal.getByRole("table", {
        name: "Preserved recorded input configuration",
        exact: true,
      });
      expect(
        await table.evaluate(
          (node) => node.getBoundingClientRect().right <= innerWidth,
        ),
      ).toBe(true);
      await expect(
        evidence.getByRole("region", {
          name: "Recorded native input configuration",
          exact: true,
        }),
      ).toHaveCount(0);
      const download = page.waitForEvent("download");
      await evidence
        .getByRole("button", { name: "Download evidence JSON", exact: true })
        .click();
      const downloaded = readFileSync((await (await download).path())!);
      // Compare the exact endpoint document rather than JSON reserialization.
      const direct = await request.get(
        "/api/bacnet/controller/native-application/receipts/" + f.id,
      );
      expect(direct.ok()).toBe(true);
      expect(downloaded).toEqual(await direct.body());
      expect(calls).toHaveLength(0);
      await terminal.scrollIntoViewIfNeeded();
      await page.screenshot({
        path: info.outputPath(`terminal-ledger-${width}.png`),
        fullPage: true,
      });
      await evidence
        .getByRole("button", { name: "Open input tools", exact: true })
        .click();
      await expect(
        page.getByRole("region", {
          name: "Native input configuration",
          exact: true,
        }),
      ).toBeVisible();
      expect(
        (await (await request.get("/api/session")).json()).field_network_open,
      ).toBe(false);
      expect(
        calls.every(
          (url) =>
            url.endsWith("/input/sources") ||
            url.endsWith("/native-application/status"),
        ),
      ).toBe(true);
    });
  }

for (const which of ["invalid", "unknown"] as const) {
  test(`${which} terminal version keeps original evidence and withholds tool links`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const f = seedTerminalLedger(nativeScheduleWriteServer.directory);
    await openTerminalLedger(page);
    const evidence = await openTerminalEvidence(page, f[which]);
    await expect(evidence).toContainText("metadata unavailable");
    await expect(
      evidence.getByRole("button", { name: "Open input tools", exact: true }),
    ).toHaveCount(0);
    await expect(
      evidence.getByRole("button", {
        name: "Download evidence JSON",
        exact: true,
      }),
    ).toBeVisible();
  });
}

test("invalid terminal metadata cannot fall back to an injected legacy input record", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seedTerminalLedger(nativeScheduleWriteServer.directory);
  let intercepted = 0;
  await page.route("**/api/changes/query", async (route) => {
    intercepted++;
    const response = await route.fetch();
    const v = await response.json();
    if (Array.isArray(v.rows))
      for (const row of v.rows)
        if (row.id === f.invalid) row.native_input = f.legacy;
    await route.fulfill({ response, json: v });
  });
  await openTerminalLedger(page);
  const evidence = await openTerminalEvidence(page, f.invalid);
  await expect(
    evidence.getByRole("button", { name: "Open input tools", exact: true }),
  ).toHaveCount(0);
  expect(intercepted).toBeGreaterThan(0);
});
