import { test, expect } from "./nativeScheduleWriteFixture";
import { readFileSync } from "node:fs";
import { seedEncodedAnalogLedger } from "./native-encoded-analog-ledger-fixture";
import {
  openTerminalLedger,
  openTerminalEvidence,
} from "./native-terminal-ledger-fixture";
for (const history of [false, true])
  for (const width of [1440, 390]) {
    test(`${history ? "History" : "Changes"} analog record stays local at ${width}px`, async ({
      page,
      request,
      nativeScheduleWriteServer,
    }, info) => {
      const f = seedEncodedAnalogLedger(nativeScheduleWriteServer.directory),
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
      const records = page.getByRole("region", {
        name: "Recorded changes",
        exact: true,
      });
      await expect(records).toContainText(
        "Move analog input · UI IN1 to UI IN3",
      );
      const evidence = await openTerminalEvidence(page, f.id),
        analog = evidence.getByRole("region", {
          name: "Recorded analog terminal movement",
          exact: true,
        });
      await expect(analog).toContainText("analog-input,101");
      await expect(analog).toContainText("UI IN3");
      await expect(analog).toContainText("No source/parent revalidation");
      const table = analog.getByRole("table", {
        name: "Preserved recorded analog configuration and field presence",
        exact: true,
      });
      await expect(table).toContainText("Not stored");
      expect(
        await table.evaluate(
          (n) => n.getBoundingClientRect().right <= innerWidth,
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
      const bytes = readFileSync((await (await download).path())!),
        direct = await request.get(
          "/api/bacnet/controller/native-application/receipts/" + f.id,
        );
      expect(direct.ok()).toBe(true);
      expect(bytes).toEqual(await direct.body());
      expect(calls).toHaveLength(0);
      await analog.scrollIntoViewIfNeeded();
      await page.screenshot({
        path: info.outputPath(`analog-ledger-${width}.png`),
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
test("uncertain analog record retains metadata without promoting its outcome", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seedEncodedAnalogLedger(nativeScheduleWriteServer.directory);
  await openTerminalLedger(page);
  const evidence = await openTerminalEvidence(page, f.uncertain);
  await expect(
    evidence.getByRole("region", {
      name: "Recorded analog terminal movement",
      exact: true,
    }),
  ).toContainText("Move analog input");
  await expect(evidence).toContainText("Needs attention");
});
for (const inject of [false, true])
  test(`invalid analog metadata withholds tools${inject ? " despite injected earlier input records" : ""}`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const f = seedEncodedAnalogLedger(nativeScheduleWriteServer.directory);
    let intercepted = 0;
    if (inject)
      await page.route("**/api/changes/query", async (route) => {
        intercepted++;
        const response = await route.fetch(),
          v = await response.json();
        for (const row of v.rows ?? [])
          if (row.id === f.invalid) {
            row.native_input = f.legacy;
            row.native_terminal = f.terminal;
            row.native_binary_terminal = f.binary;
            row.native_recovery = {
              state: "recorded",
              scope: "Injected generic recovery",
            };
          }
        await route.fulfill({ response, json: v });
      });
    await openTerminalLedger(page);
    const evidence = await openTerminalEvidence(page, f.invalid);
    await expect(evidence).toContainText(
      "Analog terminal metadata unavailable",
    );
    await expect(
      evidence.getByRole("button", { name: "Open input tools", exact: true }),
    ).toHaveCount(0);
    await expect(
      evidence.getByRole("region", {
        name: "Recorded terminal movement",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      evidence.getByRole("region", {
        name: "Recorded binary terminal movement",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      evidence.getByRole("region", {
        name: "Recorded native recovery lineage",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      evidence.getByRole("button", {
        name: "Download evidence JSON",
        exact: true,
      }),
    ).toBeVisible();
    if (inject) expect(intercepted).toBeGreaterThan(0);
  });
