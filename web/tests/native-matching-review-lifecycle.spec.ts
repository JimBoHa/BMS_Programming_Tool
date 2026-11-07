import { test, expect } from "./nativeScheduleWriteFixture";
import type { Locator } from "@playwright/test";
import { nativeDefaultPeer } from "./native-default-peer";
import { openMatchingConnection as open } from "./native-matching-connection-browser-fixture";
import { expectWorkspaceNavigationLocked } from "./workspace-navigation";
import { readFile } from "node:fs/promises";

async function reviewed(transfer: Locator) {
  await transfer
    .getByRole("button", {
      name: "Review matching connection transfer",
      exact: true,
    })
    .click();
  const plan = transfer.getByRole("region", {
    name: "Reviewed controller connection",
    exact: true,
  });
  await expect(plan).toBeVisible();
  await plan.getByRole("checkbox").nth(0).check();
  await plan.getByRole("checkbox").nth(1).check();
  const apply = transfer.getByRole("button", {
    name: "Apply matching connection to controller",
    exact: true,
  });
  await expect(apply).toBeEnabled();
  return { plan, apply };
}
for (const mode of [
  "visibility",
  "pagehide",
  "surface",
  "destination",
  "pair",
  "workspace",
])
  test(`${mode} retirement rejects the old matching-connection Apply handler before dispatch`, async ({
    page,
    request,
  }) => {
    const peer = await nativeDefaultPeer("consume", "connection");
    let headers: Record<string, string> = {};
    try {
      const { transfer, editor, compiler } = await open(
        page,
        peer.direct,
        false,
      );
      headers = {
        "X-Studio-Token": (await (await request.get("/api/session")).json())
          .token,
      };
      const { plan, apply } = await reviewed(transfer),
        old = await apply.elementHandle();
      let posts = 0;
      await page.route(
        "**/matching-connection/transfer/apply",
        async (route) => {
          posts++;
          await route.abort();
        },
      );
      if (mode === "visibility" || mode === "pagehide")
        await page.evaluate(
          ({ old, mode }) => {
            if (mode === "pagehide")
              window.dispatchEvent(new Event("pagehide"));
            else document.dispatchEvent(new Event("visibilitychange"));
            (old as HTMLElement).click();
          },
          { old, mode },
        );
      else if (mode === "surface" || mode === "workspace") {
        const summary = (
          mode === "surface"
            ? editor
            : compiler.getByLabel("Native typed default batch", { exact: true })
        ).locator(":scope > summary");
        await summary.evaluate((summary, old) => {
          (summary as HTMLElement).click();
          (summary as HTMLElement).click();
          (old as HTMLElement).click();
        }, old);
      } else {
        const label =
          mode === "destination"
            ? "Matching connection destination"
            : "Unused native destination";
        await editor
          .getByLabel(label, { exact: true })
          .evaluate((select, old) => {
            const element = select as HTMLSelectElement,
              previous = element.value;
            for (const value of [
              element.getAttribute("aria-label") ===
              "Matching connection destination"
                ? "file"
                : "",
              previous,
            ]) {
              element.value = value;
              element.dispatchEvent(new Event("change", { bubbles: true }));
            }
            (old as HTMLElement).click();
          }, old);
      }
      await expect(plan).toHaveCount(0);
      expect(posts).toBe(0);
      expect(
        (await peer.command("stats")).events.filter(
          (r: any) =>
            r[0] === "write" || (r[0] === "state" && r[1].includes("restore")),
        ),
      ).toEqual([]);
    } finally {
      try {
        if (headers["X-Studio-Token"])
          await request.post("/api/bacnet/disconnect", { headers, data: {} });
      } finally {
        peer.close();
      }
    }
  });

test("an active matching restore stays locked and retains its exact late receipt after review retirement", async ({
  page,
  request,
}) => {
  const peer = await nativeDefaultPeer("consume", "connection");
  let headers: Record<string, string> = {},
    release = () => {},
    held = false;
  const gate = new Promise<void>((resolve) => (release = resolve));
  let completed!: (value: { data: any; bytes: Buffer }) => void;
  const restored = new Promise<{ data: any; bytes: Buffer }>(
    (resolve) => (completed = resolve),
  );
  try {
    const { editor, transfer } = await open(page, peer.direct, false);
    headers = {
      "X-Studio-Token": (await (await request.get("/api/session")).json())
        .token,
    };
    const { apply } = await reviewed(transfer);
    await page.route("**/matching-connection/transfer/apply", async (route) => {
      held = true;
      const response = await route.fetch({ maxRetries: 0 }),
        bytes = await response.body();
      completed({ data: JSON.parse(bytes.toString()), bytes });
      await gate;
      await route.fulfill({ response });
    });
    await apply.click();
    await expect.poll(() => held).toBe(true);
    await expectWorkspaceNavigationLocked(page);
    const summary = editor.locator(":scope > summary");
    await expect(summary).toHaveAttribute("aria-disabled", "true");
    await summary.evaluate((e) => (e as HTMLElement).click());
    await expect(editor).toHaveAttribute("open", "");
    const actual = await restored;
    expect(actual.data.result.status).toBe("verified");
    await page.evaluate(() =>
      document.dispatchEvent(new Event("visibilitychange")),
    );
    release();
    await expect(
      transfer.getByRole("region", {
        name: "Matching connection transfer result",
        exact: true,
      }),
    ).toContainText("Connection verified in the complete native readback.");
    const download = page.waitForEvent("download");
    await transfer
      .getByRole("button", {
        name: "Save connection transfer receipt",
        exact: true,
      })
      .click();
    expect(await readFile((await (await download).path())!)).toEqual(
      actual.bytes,
    );
    expect(
      (await peer.command("stats")).events.filter(
        (r: any) => r[0] === "state" && r[1] === "start-restore",
      ),
    ).toHaveLength(1);
  } finally {
    release();
    if (held) await restored;
    try {
      if (headers["X-Studio-Token"])
        await request.post("/api/bacnet/disconnect", { headers, data: {} });
    } finally {
      peer.close();
    }
  }
});

test("a late review through a coalesced close and reopen loses both browser and server authority", async ({
  page,
  request,
}) => {
  const peer = await nativeDefaultPeer("consume", "connection");
  let headers: Record<string, string> = {},
    release = () => {},
    original: any;
  const gate = new Promise<void>((resolve) => (release = resolve));
  let ready!: () => void;
  const prepared = new Promise<void>((resolve) => (ready = resolve));
  try {
    const { editor, transfer } = await open(page, peer.direct, false);
    headers = {
      "X-Studio-Token": (await (await request.get("/api/session")).json())
        .token,
    };
    await page.route(
      "**/matching-connection/transfer/preview",
      async (route) => {
        original = route.request().postDataJSON();
        const response = await route.fetch({ maxRetries: 0 });
        ready();
        await gate;
        await route.fulfill({ response });
      },
    );
    const finished = page.waitForResponse((r) =>
      r.url().endsWith("/matching-connection/transfer/preview"),
    );
    await transfer
      .getByRole("button", {
        name: "Review matching connection transfer",
        exact: true,
      })
      .click();
    await prepared;
    const summary = editor.locator(":scope > summary");
    await expect(summary).toHaveAttribute("aria-disabled", "false");
    const cancelled = page.waitForResponse(
      (r) =>
        r.url().endsWith("/native-application/cancel") &&
        r.request().postDataJSON().operation_id === original.operation_id,
    );
    await summary.evaluate((e) => {
      (e as HTMLElement).click();
      (e as HTMLElement).click();
    });
    await cancelled;
    release();
    await (await finished).finished();
    await expect(editor).toHaveAttribute("open", "");
    await expect(
      transfer.getByRole("button", {
        name: "Review matching connection transfer",
        exact: true,
      }),
    ).toBeEnabled();
    await expect(
      transfer.getByRole("region", {
        name: "Reviewed controller connection",
        exact: true,
      }),
    ).toHaveCount(0);
    const events = (await peer.command("stats")).events;
    const refused = await request.post(
      "/api/bacnet/controller/native-application/matching-connection/transfer/preview",
      { headers, data: original },
    );
    expect(refused.status()).toBe(422);
    expect((await refused.json()).detail).toContain("cancelled");
    expect((await peer.command("stats")).events).toEqual(events);
    expect(
      events.filter(
        (r: any) =>
          r[0] === "write" || (r[0] === "state" && r[1].includes("restore")),
      ),
    ).toEqual([]);
  } finally {
    release();
    try {
      if (headers["X-Studio-Token"])
        await request.post("/api/bacnet/disconnect", { headers, data: {} });
    } finally {
      peer.close();
    }
  }
});
