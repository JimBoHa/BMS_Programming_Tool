import { test, expect } from "./nativeScheduleWriteFixture";
import { readFileSync } from "node:fs";
import { seedLabelCapabilities } from "./native-terminal-label-capability-fixture";
import {
  openTerminal,
  terminalTable,
} from "./native-terminal-capability-fixture";
for (const kind of ["ucs2", "unknown", "unverified", "output"] as const)
  test(`${kind} report shows current local-copy operations and retains exact full evidence`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const f = seedLabelCapabilities(nativeScheduleWriteServer.directory),
      calls: string[] = [];
    page.on("request", (r) => {
      if (r.method() === "POST" && r.url().includes("/api/bacnet/"))
        calls.push(new URL(r.url()).pathname);
    });
    let raw = Buffer.alloc(0);
    await page.route("**/inspection/capabilities", async (route) => {
      const response = await route.fetch();
      if (route.request().postDataJSON().capability_profile.endsWith("/17"))
        raw = await response.body();
      await route.fulfill({ response });
    });
    const { terminal } = await openTerminal(page, f[kind].id),
      table = await terminalTable(terminal);
    const statuses = await table
      .locator('tbody tr:not([data-operation="binary-terminal-transfer"]) td:first-of-type')
      .allTextContents();
    expect(statuses).toEqual([
      "source qualified",
      kind === "unknown" || kind === "unverified"
        ? "unsupported source"
        : "source qualified",
      kind === "unverified" ? "source mismatch" : "unsupported source",
    ]);
    expect(
      await table.locator('[data-operation="local-terminal-copy"]').count(),
    ).toBe(0);
    await expect(
      table.locator('[data-operation="encoded-local-terminal-copy"]'),
    ).toBeVisible();
    const download = page.waitForEvent("download");
    await terminal
      .getByRole("button", {
        name: "Save exact terminal analysis",
        exact: true,
      })
      .click();
    expect(readFileSync((await (await download).path())!)).toEqual(raw);
    expect(
      calls.every(
        (p) =>
          p.includes("/inspection/") || p.endsWith("/signal-default/source"),
      ),
    ).toBe(true);
  });
test("unknown encoded witness refuses its table while original support stays available", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seedLabelCapabilities(nativeScheduleWriteServer.directory);
  await page.route("**/inspection/capabilities", async (route) => {
    const response = await route.fetch();
    if (route.request().postDataJSON().capability_profile.endsWith("/17")) {
      const v = await response.json();
      v.qualification.encoded_archive_terminal.device_type_character_encoding = 5;
      await route.fulfill({ response, json: v });
    } else await route.fulfill({ response });
  });
  const { terminal, support } = await openTerminal(page, f.ucs2.id);
  await expect(terminal.getByRole("alert")).toContainText(
    "differs from this retained source",
  );
  await expect(terminal.getByRole("table")).toHaveCount(0);
  await expect(
    support
      .getByRole("table", { name: "Native backup operations", exact: true })
      .getByRole("row"),
  ).toHaveCount(28);
});
