import { test, expect } from "./nativeScheduleWriteFixture";
import {
  allocatedPeer,
  openFieldInputs,
} from "./native-terminal-field-fixture";

for (const routed of [false, true]) {
  test(`${routed ? "routed" : "direct"} existing analog terminal moves through review Apply and complete readback`, async ({
    page,
    request,
  }) => {
    const peer = await allocatedPeer(request);
    try {
      const inputs = await openFieldInputs(page, peer, routed);
      await expect(
        inputs.getByLabel("Native input electrical mode", { exact: true }),
      ).toHaveCount(0);
      await inputs
        .getByRole("button", {
          name: "Review controller input change",
          exact: true,
        })
        .click();
      const review = inputs.getByRole("region", {
        name: "Input change review",
        exact: true,
      });
      await expect(review).toContainText("from UI IN1 to UI IN3");
      const apply = review.getByRole("button", {
        name: "Apply input change to controller",
        exact: true,
      });
      await expect(apply).toBeDisabled();
      await review
        .getByLabel(
          "Wiring, sensor mode, common and any required jumpers match this terminal.",
          { exact: true },
        )
        .check();
      await review
        .getByLabel(
          "I confirm this input terminal move with unchanged mode and scaling.",
          { exact: true },
        )
        .check();
      await expect(apply).toBeDisabled();
      await review
        .getByLabel(
          "I confirm the application transfer and possible control restart.",
          { exact: true },
        )
        .check();
      const before = await peer.command("stats");
      const response = page.waitForResponse(
        (r) =>
          r.request().method() === "POST" &&
          r.url().endsWith("/native-application/input/apply"),
      );
      await apply.click();
      await (await response).finished();
      await expect(
        inputs.getByRole("region", {
          name: "Input transfer result",
          exact: true,
        }),
      ).toContainText("verified");
      const after = await peer.command("stats");
      expect(
        after.events.filter((e: any[]) => e[0] === "write").length,
      ).toBeGreaterThan(
        before.events.filter((e: any[]) => e[0] === "write").length,
      );
      await inputs
        .getByRole("button", { name: "Read back input transfer", exact: true })
        .click();
      await expect(
        inputs.getByRole("button", {
          name: "Read back input transfer",
          exact: true,
        }),
      ).toBeEnabled();
      expect(
        (await peer.command("stats")).events.filter(
          (e: any[]) => e[0] === "write",
        ),
      ).toEqual(after.events.filter((e: any[]) => e[0] === "write"));
    } finally {
      peer.close();
    }
  });
}

test("unknown terminal outcome retains its receipt and readback never repeats the download", async ({
  page,
  request,
}) => {
  const peer = await allocatedPeer(request);
  try {
    const inputs = await openFieldInputs(page, peer);
    await inputs
      .getByRole("button", {
        name: "Review controller input change",
        exact: true,
      })
      .click();
    const review = inputs.getByRole("region", {
      name: "Input change review",
      exact: true,
    });
    await expect(review).toBeVisible();
    await review
      .getByLabel(
        "Wiring, sensor mode, common and any required jumpers match this terminal.",
        { exact: true },
      )
      .check();
    await review
      .getByLabel(
        "I confirm this input terminal move with unchanged mode and scaling.",
        { exact: true },
      )
      .check();
    await review
      .getByLabel(
        "I confirm the application transfer and possible control restart.",
        { exact: true },
      )
      .check();
    await peer.command("mode drop-end");
    const response = page.waitForResponse(
      (r) =>
        r.request().method() === "POST" && r.url().endsWith("/input/apply"),
    );
    await review
      .getByRole("button", {
        name: "Apply input change to controller",
        exact: true,
      })
      .click();
    await (await response).finished();
    const result = inputs.getByRole("region", {
      name: "Input transfer result",
      exact: true,
    });
    await expect(result).toContainText("unknown");
    await expect(
      inputs.getByRole("button", {
        name: "Apply input change to controller",
        exact: true,
      }),
    ).toHaveCount(0);
    const before = await peer.command("mode normal"),
      readback = page.waitForResponse(
        (r) =>
          r.request().method() === "POST" &&
          r.url().endsWith("/native-application/readback"),
      );
    await result
      .getByRole("button", { name: "Read back input transfer", exact: true })
      .click();
    await (await readback).finished();
    await expect(result).toContainText("verified");
    expect(
      (await peer.command("stats")).events.filter(
        (e: any[]) => e[0] === "write",
      ),
    ).toEqual(before.events.filter((e: any[]) => e[0] === "write"));
  } finally {
    peer.close();
  }
});
