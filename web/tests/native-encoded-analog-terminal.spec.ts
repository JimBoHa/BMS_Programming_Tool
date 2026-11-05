import { test, expect } from "./nativeScheduleWriteFixture";
import { readFileSync } from "node:fs";
import {
  seedEncodedAnalog,
  openEncodedAnalog,
  encodedAnalogDraft,
} from "./native-encoded-analog-terminal-fixture";
import { chooseWorkspaceTask } from "./workspace-navigation";
for (const caf of [false, true])
  for (const width of [1440, 390])
    test(`${caf ? "CAF" : "graph"} ${width}px analog move retains stored absence, exact copies and original form draft`, async ({
      page,
      nativeScheduleWriteServer,
    }, info) => {
      const f = seedEncodedAnalog(nativeScheduleWriteServer.directory),
        calls: string[] = [];
      await page.setViewportSize({ width, height: 1000 });
      page.on("request", (r) => {
        if (
          r.method() === "POST" &&
          new URL(r.url()).pathname.startsWith("/api/bacnet/")
        )
          calls.push(new URL(r.url()).pathname);
      });
      const { inputs, analog } = await openEncodedAnalog(page, f.id, caf);
      await encodedAnalogDraft(analog);
      const table = analog.getByRole("table", {
        name: "Preserved analog configuration",
        exact: true,
      });
      await expect(table).toContainText("Not stored");
      expect(
        await table.getByRole("row").filter({ hasText: "Not stored" }).count(),
      ).toBe(2);
      expect(
        await table.evaluate(
          (n) => n.getBoundingClientRect().right <= innerWidth,
        ),
      ).toBe(true);
      await analog
        .getByRole("button", {
          name: "Review local analog terminal copy",
          exact: true,
        })
        .click();
      const review = analog.getByRole("region", {
        name: "Analog terminal review",
        exact: true,
      });
      await expect(review).toBeVisible();
      const download = page.waitForEvent("download");
      await review
        .getByRole("button", {
          name: "Save native analog terminal copy",
          exact: true,
        })
        .click();
      expect(readFileSync((await (await download).path())!)).toEqual(
        Buffer.from(f.output, "base64"),
      );
      expect(
        calls.every(
          (p) =>
            p.endsWith("/input/source") ||
            p.endsWith("/input/encoded-terminal/source") ||
            p.endsWith("/input/copy/preview") ||
            p.endsWith("/input/copy/export"),
        ),
      ).toBe(true);
      await table.scrollIntoViewIfNeeded();
      await page.screenshot({
        path: info.outputPath(`analog-config-${width}.png`),
        fullPage: true,
      });
      await analog.locator(":scope > summary").click();
      await expect(
        inputs.getByLabel("Engineering range high", { exact: true }),
      ).toHaveValue("9.");
      await analog.locator(":scope > summary").click();
      await expect(
        analog.getByLabel("Configured analog input", { exact: true }),
      ).toHaveValue("analog-input,101");
      await chooseWorkspaceTask(page, "Program");
      if (caf)
        await expect(
          page.getByLabel("Working context", { exact: true }),
        ).toContainText("analog-work.caf");
    });
for (const fault of ["scaling", "presence", "charset"] as const)
  test(`damaged analog ${fault} source cannot enable review`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const f = seedEncodedAnalog(nativeScheduleWriteServer.directory);
    await page.route("**/input/encoded-terminal/source", async (route) => {
      const response = await route.fetch(),
        v = await response.json();
      if (fault === "scaling") v.inputs[0].configuration.output_low = 0;
      if (fault === "presence")
        v.inputs[0].configuration_storage.linear_output_endpoints_present = true;
      if (fault === "charset") v.inputs[0].device_type_character_encoding = 5;
      await route.fulfill({ response, json: v });
    });
    await page.goto("/");
    await page
      .getByRole("button", { name: "New application", exact: true })
      .click();
    await chooseWorkspaceTask(page, "Points & I/O");
    const inputs = page.getByRole("region", {
      name: "Native input configuration",
      exact: true,
    });
    await inputs
      .getByLabel("Retained native input source", { exact: true })
      .selectOption(f.id);
    const analog = inputs.getByLabel("Analog input terminal movement", {
      exact: true,
    });
    await analog.locator(":scope > summary").click();
    await expect(analog.getByRole("alert")).toContainText(
      "differs from this retained capture",
    );
    await expect(
      analog.getByRole("button", {
        name: "Review local analog terminal copy",
        exact: true,
      }),
    ).toHaveCount(0);
  });
