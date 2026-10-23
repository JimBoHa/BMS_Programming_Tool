import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";

const root = path.resolve("..");
for (const mode of ["verify", "scenario"] as const) {
  test(`native IEC ${mode} trace preserves actual response bytes and signed state`, async ({
    page,
  }) => {
    const program = execFileSync(
      path.join(root, ".venv/bin/python"),
      [
        "-c",
        "from tests.test_iec_signed_zero import signed_zero_program; print(signed_zero_program().model_dump_json())",
      ],
      { cwd: root },
    );
    await page.goto("/");
    await page.locator('input[type=file][accept*=".st"]').setInputFiles({
      name: "signed-zero.bms.json",
      mimeType: "application/json",
      buffer: program,
    });
    await page.getByRole("button", { name: "IEC native", exact: true }).click();
    await expect(
      page.getByText("MatIEC compiler available", { exact: true }),
    ).toBeVisible();
    if (mode === "verify") {
      await page.getByLabel("IEC scan count", { exact: true }).fill("2");
      await page.getByLabel("IEC value input", { exact: true }).fill("-0.0");
    } else {
      await page
        .getByLabel("IEC scenario events", { exact: true })
        .fill('[{"time":0,"inputs":{"input":-0.0}}]');
      await page.getByLabel("IEC scenario duration", { exact: true }).fill("2");
    }
    const receiving = page.waitForResponse(
      (response) =>
        response.url().endsWith(`/api/iec/${mode}`) &&
        response.request().method() === "POST",
    );
    await page
      .getByRole("button", {
        name:
          mode === "verify" ? "Run IEC verification" : "Run native scenario",
        exact: true,
      })
      .click();
    const response = await receiving;
    expect(response.status()).toBe(200);
    const original = await response.text();
    const authoritative = JSON.parse(original);
    for (const row of authoritative.rows) {
      expect(Object.is(row.outputs.output, -0)).toBe(true);
      expect(Object.is(row.outputs.stored, -0)).toBe(true);
      expect(Object.is(row.native_state.n_delay_memory, -0)).toBe(true);
    }
    const result = page.getByRole("region", {
      name: "IEC verification results",
    });
    await expect(result.getByRole("status")).toHaveText(
      "Matched compiled IEC/reference outputs",
    );
    const downloading = page.waitForEvent("download");
    await result
      .getByRole("button", { name: "Download full IEC trace", exact: true })
      .click();
    const downloaded = readFileSync(
      (await (await downloading).path())!,
      "utf8",
    );
    const trace = JSON.parse(downloaded);
    expect(Object.is(trace.rows[0].outputs.output, -0)).toBe(true);
    expect(Object.is(trace.rows[0].native_state.n_delay_memory, -0)).toBe(true);
    expect(downloaded).toBe(original);
    await page
      .getByLabel(
        mode === "verify" ? "IEC value input" : "IEC scenario duration",
        { exact: true },
      )
      .fill("3");
    await expect(result).toHaveCount(0);
    await expect(
      page.getByRole("button", {
        name: "Download full IEC trace",
        exact: true,
      }),
    ).toHaveCount(0);
  });
}
