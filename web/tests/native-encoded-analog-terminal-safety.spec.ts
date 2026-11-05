import { test, expect } from "./nativeScheduleWriteFixture";
import {
  seedEncodedAnalog,
  openEncodedAnalog,
  encodedAnalogDraft,
} from "./native-encoded-analog-terminal-fixture";
for (const fault of ["source", "review", "export"] as const)
  test(`malformed analog ${fault} cannot enable an unsafe action`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const f = seedEncodedAnalog(nativeScheduleWriteServer.directory);
    if (fault === "source")
      await page.route("**/input/encoded-terminal/source", async (route) => {
        const response = await route.fetch(),
          v = await response.json();
        v.inputs[0].configuration_sha256 = "bad";
        await route.fulfill({ response, json: v });
      });
    if (fault === "source") {
      await page.goto("/");
      await page
        .getByRole("button", { name: "New application", exact: true })
        .click();
      const { chooseWorkspaceTask } = await import("./workspace-navigation");
      await chooseWorkspaceTask(page, "Points & I/O");
      await page
        .getByLabel("Retained native input source", { exact: true })
        .selectOption(f.id);
      const analog = page.getByLabel("Analog input terminal movement", {
        exact: true,
      });
      await analog.locator(":scope > summary").click();
      await expect(analog.getByRole("alert")).toContainText(
        "differs from this retained capture",
      );
      await expect(analog.getByLabel("Configured analog input")).toHaveCount(0);
      return;
    }
    const { analog } = await openEncodedAnalog(page, f.id);
    await encodedAnalogDraft(analog);
    if (fault === "review")
      await page.route("**/input/copy/preview", async (route) => {
        const response = await route.fetch(),
          v = await response.json();
        v.compilation.stored_configuration.output_low = 0;
        await route.fulfill({ response, json: v });
      });
    await analog
      .getByRole("button", {
        name: "Review local analog terminal copy",
        exact: true,
      })
      .click();
    if (fault === "review") {
      await expect(analog.getByRole("alert")).toContainText("proof differs");
      await expect(
        analog.getByRole("button", {
          name: "Save native analog terminal copy",
          exact: true,
        }),
      ).toHaveCount(0);
      return;
    }
    await expect(
      analog.getByRole("region", {
        name: "Analog terminal review",
        exact: true,
      }),
    ).toBeVisible();
    let downloads = 0;
    page.on("download", () => downloads++);
    await page.route("**/input/copy/export", async (route) => {
      const response = await route.fetch(),
        body = await response.body();
      await route.fulfill({
        response,
        body: Buffer.concat([body, Buffer.from([0])]),
      });
    });
    await analog
      .getByRole("button", {
        name: "Save native analog terminal copy",
        exact: true,
      })
      .click();
    await expect(analog.getByRole("alert")).toContainText(
      "differs from its reviewed bytes",
    );
    expect(downloads).toBe(0);
  });
test("a delayed analog proof digest cannot revive a review after page hide", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seedEncodedAnalog(nativeScheduleWriteServer.directory),
    { analog } = await openEncodedAnalog(page, f.id);
  await encodedAnalogDraft(analog);
  await page.evaluate(() => {
    const w = window as any,
      original = crypto.subtle.digest.bind(crypto.subtle);
    w.analogWaiting = [];
    w.analogDelay = true;
    w.analogDone = 0;
    crypto.subtle.digest = async (a: any, v: any) => {
      const tracked = new TextDecoder()
        .decode(v)
        .includes("tagged-moi-local-terminal-copy/3");
      if (tracked && w.analogDelay)
        await new Promise<void>((r) => w.analogWaiting.push(r));
      const result = await original(a, v);
      if (tracked) w.analogDone++;
      return result;
    };
  });
  await analog
    .getByRole("button", {
      name: "Review local analog terminal copy",
      exact: true,
    })
    .click();
  await page.waitForFunction(() => (window as any).analogWaiting.length > 0);
  await page.evaluate(() => {
    const w = window as any;
    window.dispatchEvent(new Event("pagehide"));
    w.analogDelay = false;
    w.analogWaiting.splice(0).forEach((r: any) => r());
  });
  await page.waitForFunction(() => (window as any).analogDone >= 2);
  await analog.locator(":scope > summary").click();
  await expect(
    analog.getByRole("button", {
      name: "Review local analog terminal copy",
      exact: true,
    }),
  ).toBeEnabled();
  await expect(
    analog.getByRole("region", { name: "Analog terminal review", exact: true }),
  ).toHaveCount(0);
});

for (const change of ["collapse", "navigation"] as const)
  test(`late analog export cannot download after ${change}`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const f = seedEncodedAnalog(nativeScheduleWriteServer.directory),
      { analog } = await openEncodedAnalog(page, f.id);
    await encodedAnalogDraft(analog);
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
    let release!: () => void,
      seen!: () => void,
      downloads = 0;
    const gate = new Promise<void>((r) => (release = r)),
      arrived = new Promise<void>((r) => (seen = r));
    page.on("download", () => downloads++);
    await page.route("**/input/copy/export", async (route) => {
      const response = await route.fetch();
      seen();
      await gate;
      await route.fulfill({ response });
    });
    await review
      .getByRole("button", {
        name: "Save native analog terminal copy",
        exact: true,
      })
      .click();
    await arrived;
    const { chooseWorkspaceTask } = await import("./workspace-navigation");
    if (change === "collapse") await analog.locator(":scope > summary").click();
    else await chooseWorkspaceTask(page, "Program");
    const settled = page.waitForResponse(
      (r) =>
        r.request().method() === "POST" &&
        r.url().endsWith("/input/copy/export"),
    );
    release();
    await settled;
    if (change === "navigation")
      await chooseWorkspaceTask(page, "Points & I/O");
    await analog.locator(":scope > summary").click();
    await expect(
      analog.getByRole("button", {
        name: "Review local analog terminal copy",
        exact: true,
      }),
    ).toBeEnabled();
    await expect(
      analog.getByRole("region", {
        name: "Analog terminal review",
        exact: true,
      }),
    ).toHaveCount(0);
    expect(downloads).toBe(0);
    await expect(
      analog.getByLabel("Configured analog input", { exact: true }),
    ).toHaveValue("analog-input,101");
  });
