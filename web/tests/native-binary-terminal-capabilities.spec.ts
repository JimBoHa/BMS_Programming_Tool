import { test, expect } from "./nativeScheduleWriteFixture";
import { readFileSync } from "node:fs";
import { seedBinaryCapabilities } from "./native-binary-terminal-capability-fixture";
import {
  openTerminal,
  terminalTable,
} from "./native-terminal-capability-fixture";
for (const [kind, status] of Object.entries({
  ucs2: "preflight required",
  ascii: "preflight required",
  unknown: "unsupported source",
  unverified: "source mismatch",
  serial: "transport unavailable",
  output: "preflight required",
  analog: "unsupported source",
  configuration: "unsupported source",
  counter: "unsupported source",
}))
  test(`${kind} binary support uses actual source and remains local`, async ({
    page,
    request,
    nativeScheduleWriteServer,
  }, info) => {
    const f = seedBinaryCapabilities(nativeScheduleWriteServer.directory),
      calls: string[] = [];
    await page.setViewportSize({
      width: kind === "ascii" ? 390 : 1440,
      height: 1000,
    });
    page.on("request", (r) => {
      if (
        r.method() === "POST" &&
        new URL(r.url()).pathname.startsWith("/api/bacnet/")
      )
        calls.push(new URL(r.url()).pathname);
    });
    let raw = Buffer.alloc(0);
    await page.route("**/inspection/capabilities", async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      if (route.request().postDataJSON().capability_profile.endsWith("/18"))
        raw = await response.body();
      await route.fulfill({ response });
    });
    const { terminal, support } = await openTerminal(page, f[kind].id),
      table = await terminalTable(terminal),
      row = table.locator('[data-operation="binary-terminal-transfer"]');
    await expect(row.locator("td").first()).toHaveText(status);
    await expect(row).toContainText(
      "This analysis grants no plan or transfer authority.",
    );
    await expect(
      terminal.getByRole("button", {
        name: "Apply to controller",
        exact: true,
      }),
    ).toHaveCount(0);
    expect(
      (await (await request.get("/api/session")).json()).field_network_open,
    ).toBe(false);
    expect(
      calls.every(
        (p) =>
          p.includes("/inspection/") || p.endsWith("/signal-default/source"),
      ),
    ).toBe(true);
    await expect(
      support
        .getByRole("table", { name: "Native backup operations", exact: true })
        .getByRole("row"),
    ).toHaveCount(28);
    const download = page.waitForEvent("download");
    await terminal
      .getByRole("button", {
        name: "Save exact terminal analysis",
        exact: true,
      })
      .click();
    expect(readFileSync((await (await download).path())!)).toEqual(raw);
    if (kind === "ascii" || kind === "ucs2") {
      expect(
        await table.evaluate((n) => {
          const wrapper = n.parentElement!,
            bounds = wrapper.getBoundingClientRect();
          return (
            bounds.right <= innerWidth &&
            getComputedStyle(wrapper).overflowX === "auto" &&
            document.documentElement.scrollWidth <= innerWidth
          );
        }),
      ).toBe(true);
      if (kind === "ascii") {
        expect(
          await table.evaluate(
            (n) => n.parentElement!.scrollWidth > n.parentElement!.clientWidth,
          ),
        ).toBe(true);
        await table.evaluate((n) => {
          n.parentElement!.scrollLeft = n.parentElement!.scrollWidth;
        });
        expect(
          await table
            .locator("tbody tr:last-child td:last-child")
            .evaluate((n) => n.getBoundingClientRect().right <= innerWidth),
        ).toBe(true);
      }
      await terminal.scrollIntoViewIfNeeded();
      await page.screenshot({
        path: info.outputPath(`binary-capabilities-${kind}.png`),
        fullPage: true,
      });
    }
  });
for (const fault of ["counter", "configuration", "merge", "row"] as const)
  test(`malformed binary ${fault} withholds its table and preserves original support`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const f = seedBinaryCapabilities(nativeScheduleWriteServer.directory);
    let corrupt = true;
    await page.route("**/inspection/capabilities", async (route) => {
      const response = await route.fetch();
      if (
        corrupt &&
        route.request().postDataJSON().capability_profile.endsWith("/18")
      ) {
        const v = await response.json(),
          w = v.qualification.binary_terminal;
        if (fault === "counter") w.counter_values_are_live = true;
        if (fault === "configuration") w.stored_configuration.polarity = true;
        if (fault === "merge") w.parameter_merge.static_sha256 = "0".repeat(64);
        if (fault === "row") v.operations.find((r: any) => r.id === "binary-terminal-transfer").status = "source-qualified";
        await route.fulfill({ response, json: v });
      } else await route.fulfill({ response });
    });
    const { terminal, support } = await openTerminal(page, f.ucs2.id);
    await expect(terminal.getByRole("alert")).toContainText(
      "differs from this retained source",
    );
    await expect(terminal.getByRole("table")).toHaveCount(0);
    await expect(
      terminal.getByRole("button", {
        name: "Save exact terminal analysis",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      support
        .getByRole("table", { name: "Native backup operations", exact: true })
        .getByRole("row"),
    ).toHaveCount(28);
    corrupt = false;
    await terminal
      .getByRole("button", {
        name: "Analyze terminal support again",
        exact: true,
      })
      .click();
    await terminalTable(terminal);
  });
