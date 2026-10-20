import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";

test("review native hardware aliases, metric profiles and explicit migration bindings", async ({
  page,
}) => {
  const root = path.resolve("..");
  const python = path.join(root, ".venv/bin/python");
  const fixture = (newer = false) =>
    execFileSync(
      python,
      [
        "-c",
        `from tests.test_jci_hardware import definition; import sys; sys.stdout.buffer.write(definition(${newer ? "revision=1,instance=4,maximum=120,default=75" : ""}))`,
      ],
      { cwd: root },
    );
  const original = fixture();
  await page.goto("/");
  await page.getByRole("button", { name: "JCI hardware", exact: true }).click();
  const panel = page.getByRole("region", {
    name: "JCI hardware definitions",
    exact: true,
  });
  await panel
    .getByLabel("Current hardware XML", { exact: true })
    .setInputFiles({
      name: "current-native.xml",
      mimeType: "application/xml",
      buffer: original,
    });
  await expect(
    panel.getByRole("region", {
      name: "Current hardware definition",
      exact: true,
    }),
  ).toContainText("ExampleSensor · revision 0");
  await panel
    .getByLabel("Select hardware point temperature", { exact: true })
    .check();
  await panel
    .getByLabel("Select hardware point alternate", { exact: true })
    .check();
  await panel
    .getByRole("button", { name: "Review point selection", exact: true })
    .click();
  await expect(panel.getByRole("alert")).toContainText(
    "alias the same BACnet object",
  );
  await panel
    .getByLabel("Native hardware preset", { exact: true })
    .selectOption("temperatureOnly");
  await panel
    .getByLabel("Hardware measurement system", { exact: true })
    .selectOption("metric");
  await panel
    .getByRole("button", { name: "Review point selection", exact: true })
    .click();
  await expect(
    panel.getByRole("region", {
      name: "Hardware engineering selection",
      exact: true,
    }),
  ).toContainText('"units": 62');
  await panel
    .getByLabel("Replacement hardware XML", { exact: true })
    .setInputFiles({
      name: "replacement-native.xml",
      mimeType: "application/xml",
      buffer: fixture(true),
    });
  await panel
    .getByRole("button", {
      name: "Compare selected point migration",
      exact: true,
    })
    .click();
  const report = panel.getByRole("region", {
    name: "Native hardware migration report",
    exact: true,
  });
  await expect(report).toContainText("temperature · rebinding required");
  await expect(report).toContainText('"new": 4');
  await expect(report).toContainText("This report does not apply changes");
  const pending = page.waitForEvent("download");
  await panel
    .getByRole("button", { name: "Export current XML original", exact: true })
    .click();
  expect(
    execFileSync("/bin/cat", [(await (await pending).path())!]).equals(
      original,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/studio-jci-hardware.png",
    fullPage: true,
  });
});
