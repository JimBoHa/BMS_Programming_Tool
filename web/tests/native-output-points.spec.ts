import type { APIRequestContext, Page } from "@playwright/test";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { createInterface } from "node:readline";
import { expect, test } from "./nativeScheduleWriteFixture";
import { freePort } from "./workflow-peer";
import { chooseWorkspaceTask } from "./workspace-navigation";

async function withRuntimeController(
  page: Page,
  request: APIRequestContext,
  work: () => Promise<void>,
) {
  const peer = spawn(
    "../.venv/bin/python",
    [
      "-u",
      "-c",
      `
import asyncio, tempfile
from contextlib import aclosing
from pathlib import Path
from pytest import MonkeyPatch
from tests.test_native_output_points import native_link, io_link, output_link
async def main():
    with tempfile.TemporaryDirectory() as tmp, MonkeyPatch.context() as patch:
        async with aclosing(native_link.__wrapped__(Path(tmp), patch)) as native:
            async with aclosing(io_link.__wrapped__(await anext(native), patch)) as io:
                _, _, target, _ = await output_link.__wrapped__(await anext(io))
                print(target["address"], flush=True)
                await asyncio.to_thread(input)
asyncio.run(main())
`,
    ],
    {
      cwd: process.cwd(),
      env: { ...process.env, PYTHONPATH: "../backend:.." },
    },
  );
  const lines = createInterface({ input: peer.stdout });
  try {
    const [endpoint] = await Promise.race([
      once(lines, "line"),
      once(peer, "exit").then(() => {
        throw Error("Loopback controller failed to start.");
      }),
    ]);
    const headers = {
      "X-Studio-Token": (await (await request.get("/api/session")).json())
        .token,
    };
    const credentials = await request.post(
      "/api/bacnet/controller/native-application/credentials",
      {
        headers,
        data: { backup: "authored-backup", restore: "authored-restore" },
      },
    );
    expect(credentials.ok()).toBe(true);
    await page.goto("/");
    await page
      .getByRole("button", { name: /^Connect to a controller/ })
      .click();
    await page
      .getByLabel("Local bind address / UDP port", { exact: true })
      .fill(`127.0.0.1:${await freePort()}`);
    await page
      .getByRole("button", { name: "Open interface", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Known controller address", exact: true })
      .click();
    await page
      .getByLabel("Known controller address", { exact: true })
      .fill(endpoint);
    await page
      .getByLabel("Known Device object", { exact: true })
      .fill("device,5136");
    await page.getByLabel("Known router", { exact: true }).fill("");
    await page.getByLabel("Known network", { exact: true }).fill("");
    await page
      .getByRole("region", { name: "Known controller connection" })
      .getByRole("button", { name: "Open controller", exact: true })
      .click();
    await expect(
      page.getByRole("region", { name: "Controller overview" }),
    ).toContainText("Authored controller");
    await chooseWorkspaceTask(page, "Points & I/O");
    await work();
  } finally {
    lines.close();
    peer.stdin.end("\n");
    if (peer.exitCode === null) peer.kill("SIGTERM");
  }
}

test("review output assignments, retire edited reviews and apply on a loopback controller", async ({
  page,
  request,
}, testInfo) => {
  test.setTimeout(120000);
  await withRuntimeController(page, request, async () => {
    await page
      .getByRole("button", { name: "Configure output points", exact: true })
      .click();
    const editor = page.getByRole("region", {
      name: "Native output configuration",
      exact: true,
    });
    await editor
      .getByRole("button", { name: "Capture current application" })
      .click();
    const source = editor.getByLabel("Output source");
    await expect(source).toBeVisible({ timeout: 20000 });
    await expect(editor.getByLabel("New point instance")).toHaveValue(
      "3200100",
    );
    await source.selectOption("new-discrete");
    await expect(
      editor.getByRole("option", { name: "Move existing point" }),
    ).toHaveCount(0);
    await expect(
      editor
        .getByLabel("Destination terminal")
        .getByRole("option", { name: /OUT4/ }),
    ).toHaveCount(0);
    await editor.getByLabel("New point name").fill("Independent relay");
    await editor
      .getByRole("button", { name: "Review local output edit" })
      .click();
    await expect(
      editor.getByRole("button", { name: "Review on controller" }),
    ).toBeEnabled();
    const independentReview = testInfo.outputPath(
      "independent-output-review.png",
    );
    await editor.screenshot({ path: independentReview });
    await source.selectOption("binary-output,71");
    const destination = editor.getByLabel("Destination terminal");
    await expect(
      destination.getByRole("option", {
        name: "OUT4 · externally powered 24 VAC triac",
      }),
    ).toHaveCount(1);
    await expect(
      destination.getByRole("option", {
        name: "OUT3 · internally powered 24 VAC triac",
      }),
    ).toHaveCount(1);
    await destination.selectOption("4");
    await editor.getByLabel("New point name").fill("Browser independent relay");
    await editor.getByLabel("New point instance").fill("3300123");
    await editor
      .getByRole("button", { name: "Review local output edit" })
      .click();
    await editor.getByRole("button", { name: "Review on controller" }).click();
    const apply = editor.getByRole("button", { name: "Apply output change" });
    await expect(apply).toBeDisabled();
    await source.selectOption("analog-output,72");
    await expect(apply).toHaveCount(0);
    await expect(editor.getByLabel("Destination terminal")).toHaveValue("4");
    await editor
      .getByLabel("New point name")
      .fill("Browser independent modulator");
    await editor
      .getByRole("button", { name: "Review local output edit" })
      .click();
    await editor.getByRole("button", { name: "Review on controller" }).click();
    await expect(apply).toBeDisabled();
    const screenshot = testInfo.outputPath("output-point-review.png");
    await editor.screenshot({ path: screenshot });
    await testInfo.attach("output-point-review", {
      path: screenshot,
      contentType: "image/png",
    });
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(editor.getByLabel("Destination terminal")).toBeVisible();
    expect(
      await editor.evaluate((el) => el.scrollWidth <= el.clientWidth + 1),
    ).toBe(true);
    await apply.scrollIntoViewIfNeeded();
    await expect(apply).toBeInViewport();
    await page.screenshot({
      path: testInfo.outputPath("output-point-review-narrow.png"),
    });
    await page.setViewportSize({ width: 1440, height: 1000 });
    await editor
      .getByLabel(
        "I verified the connected load, terminal wiring and signal type.",
      )
      .check();
    await editor
      .getByLabel(
        "The controller can restart during this application transfer.",
      )
      .check();
    await apply.focus();
    await expect(apply).toBeFocused();
    await apply.press("Enter");
    await expect(editor.getByRole("status")).toContainText(
      "output readback verified",
      { timeout: 35000 },
    );
    await editor
      .getByText("Recorded output transfers", { exact: true })
      .click();
    await editor.getByRole("button", { name: "Read back transfer" }).click();
    await expect(editor.getByRole("status")).toContainText(
      "output readback verified",
      { timeout: 20000 },
    );
  });
});

test("assign a dry contact, move it and invert its reported state", async ({
  page,
  request,
}, testInfo) => {
  test.setTimeout(150000);
  await withRuntimeController(page, request, async () => {
    await page
      .getByRole("button", { name: "Configure native inputs", exact: true })
      .click();
    await page.getByLabel("Input configuration task").selectOption("contacts");
    const editor = page.getByRole("region", {
      name: "Dry contact configuration",
    });
    const capture = editor.getByRole("button", {
      name: "Capture current application",
    });
    const operation = editor.getByLabel("Input operation");
    const local = editor.getByRole("button", {
      name: "Review local input edit",
    });
    const field = editor.getByRole("button", { name: "Review on controller" });
    const apply = editor.getByRole("button", { name: "Apply input change" });
    const finish = async (want: string) => {
      await local.click();
      await field.click();
      await expect(apply).toBeDisabled();
      await editor
        .getByLabel(
          "I verified the input terminal, contact wiring and intended polarity.",
        )
        .check();
      await editor
        .getByLabel(
          "The controller can restart during this application transfer.",
        )
        .check();
      await apply.focus();
      await expect(apply).toBeFocused();
      await apply.press("Enter");
      await expect(editor.getByRole("status")).toContainText(
        "Contact state at readback was " + want + ".",
        { timeout: 35000 },
      );
    };
    await capture.click();
    await expect(operation).toHaveValue("add");
    await editor.getByLabel("Destination input terminal").selectOption("2");
    await editor.getByLabel("New point name").fill("Fixture airflow proof");
    await editor.getByLabel("New point instance").fill("3300456");
    await local.click();
    await field.click();
    await expect(apply).toBeDisabled();
    await editor
      .getByLabel("Reported contact polarity")
      .selectOption("reverse");
    await expect(apply).toHaveCount(0);
    await page
      .getByRole("button", { name: "Close input configuration", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Configure native inputs", exact: true })
      .click();
    await expect(editor.getByLabel("New point name")).toHaveValue(
      "Fixture airflow proof",
    );
    await expect(editor.getByLabel("Reported contact polarity")).toHaveValue(
      "reverse",
    );
    await finish("active");
    await editor.getByText("Recorded input transfers", { exact: true }).click();
    await editor.getByRole("button", { name: "Read back transfer" }).click();
    await expect(editor.getByRole("status")).toContainText(
      "Contact state at readback was active.",
    );
    await capture.click();
    await operation.selectOption("move");
    await expect(editor.getByLabel("Configured dry contact")).toContainText(
      "Fixture airflow proof · IN2",
    );
    await expect(editor.getByLabel("Destination input terminal")).toHaveValue(
      "3",
    );
    await editor.screenshot({
      path: testInfo.outputPath("dry-contact-move.png"),
    });
    await finish("active");
    await capture.click();
    await operation.selectOption("polarity");
    await expect(editor.getByLabel("Configured dry contact")).toContainText(
      "Fixture airflow proof · IN3",
    );
    await editor.getByLabel("Reported contact polarity").selectOption("normal");
    await page.setViewportSize({ width: 390, height: 844 });
    await local.scrollIntoViewIfNeeded();
    await expect(local).toBeInViewport();
    expect(
      await editor.evaluate((e) => e.scrollWidth <= e.clientWidth + 1),
    ).toBe(true);
    await page.screenshot({
      path: testInfo.outputPath("dry-contact-phone.png"),
    });
    await finish("inactive");
  });
});
