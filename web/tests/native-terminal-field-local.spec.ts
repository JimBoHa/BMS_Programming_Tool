import { test, expect } from "./nativeScheduleWriteFixture";
import { readFileSync } from "node:fs";
import { fieldDocuments } from "./native-terminal-field-fixture";
import { python } from "./native-connection-fixture";
import { chooseWorkspaceTask } from "./workspace-navigation";

for (const { width, caf } of [
  { width: 1440, caf: false },
  { width: 390, caf: false },
  { width: 390, caf: true },
]) {
  test(`${caf ? "CAF" : "graph"} offline analog terminal copy retains mode and source at ${width}px`, async ({
    page,
    request,
    nativeScheduleWriteServer,
  }, info) => {
    const f = fieldDocuments(nativeScheduleWriteServer.directory),
      calls: string[] = [];
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("/");
    if (caf) {
      const buffer = Buffer.from(
        python(
          "from tests.test_caf_graph import make_graph; import base64; print(base64.b64encode(make_graph()).decode())",
        ),
        "base64",
      );
      await page
        .getByLabel("Open local CAF application", { exact: true })
        .setInputFiles({
          name: "terminal-move.caf",
          mimeType: "application/octet-stream",
          buffer,
        });
      await expect(
        page.getByLabel("Working context", { exact: true }),
      ).toContainText("terminal-move.caf");
    } else
      await page
        .getByRole("button", { name: "New application", exact: true })
        .click();
    await chooseWorkspaceTask(page, "Points & I/O");
    page.on("request", (r) => {
      if (
        r.method() === "POST" &&
        new URL(r.url()).pathname.startsWith("/api/bacnet/")
      )
        calls.push(new URL(r.url()).pathname);
    });
    const inputs = page.getByRole("region", {
      name: "Native input configuration",
      exact: true,
    });
    await inputs
      .getByLabel("Retained native input source", { exact: true })
      .selectOption(f.source.capture_id);
    await inputs
      .getByLabel("Input operation", { exact: true })
      .selectOption("terminal");
    await inputs
      .getByLabel("Configured native input", { exact: true })
      .selectOption("analog-input,101");
    await inputs
      .getByLabel("Field terminal destination", { exact: true })
      .selectOption("3");
    await expect(
      inputs.getByLabel("Native input electrical mode", { exact: true }),
    ).toHaveCount(0);
    await inputs
      .getByRole("button", { name: "Review local input copy", exact: true })
      .click();
    await expect(inputs).toContainText("Local copy reviewed.");
    const download = page.waitForEvent("download");
    await inputs
      .getByRole("button", { name: "Save native copy", exact: true })
      .click();
    expect(readFileSync((await (await download).path())!)).toEqual(
      Buffer.from(f.local_output, "base64"),
    );
    await inputs
      .getByLabel("Field terminal destination", { exact: true })
      .selectOption("2");
    await expect(
      inputs.getByRole("button", { name: "Save native copy", exact: true }),
    ).toBeDisabled();
    await chooseWorkspaceTask(page, "Overview");
    await chooseWorkspaceTask(page, "Points & I/O");
    await expect(
      inputs.getByLabel("Field terminal destination", { exact: true }),
    ).toHaveValue("2");
    expect(
      (await (await request.get("/api/session")).json()).field_network_open,
    ).toBe(false);
    if (caf)
      await expect(
        page.getByLabel("Working context", { exact: true }),
      ).toContainText("terminal-move.caf");
    expect(
      calls.every((p) =>
        ["/input/source", "/input/copy/preview", "/input/copy/export"].some(
          (s) => p.endsWith(s),
        ),
      ),
    ).toBe(true);
    await page.screenshot({
      path: info.outputPath(`terminal-field-local-${width}.png`),
      fullPage: true,
    });
  });
}
