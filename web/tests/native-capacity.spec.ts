import { test, expect } from "./nativeScheduleWriteFixture";
import { readFile } from "node:fs/promises";
import { nativeDefaultPeer } from "./native-default-peer";
import { openOrderTransfer } from "./native-order-transfer-browser-fixture";
import { inspect } from "./native-connection-capability-fixture";
import { seedOrderCapabilities } from "./native-order-capability-fixture";
import {
  openNativeCompiler,
  expectWorkspaceNavigationLocked,
} from "./workspace-navigation";

const panel = (page: any) =>
  page.getByLabel("Native application size and capacity", { exact: true });
async function connected(page: any, peer: any, routed = false) {
  const { compiler } = await openOrderTransfer(
    page,
    routed ? peer.router : peer.direct,
    routed,
  );
  await inspect(compiler);
  const p = panel(page);
  await p.locator(":scope > summary").click();
  await p
    .getByRole("button", {
      name: "Inspect retained application size",
      exact: true,
    })
    .click();
  await expect(
    p.getByRole("region", { name: "Retained application sizes", exact: true }),
  ).toBeVisible();
  return p;
}
for (const routed of [false, true])
  test(`${routed ? "routed" : "direct"} capacity observation is advisory, read-only and exactly exportable`, async ({
    page,
  }) => {
    const peer = await nativeDefaultPeer("consume", "execution-order");
    let release = () => {};
    const gate = new Promise<void>((resolve) => (release = resolve));
    let received!: () => void;
    const arrived = new Promise<void>((resolve) => (received = resolve));
    try {
      const p = await connected(page, peer, routed),
        before = await peer.command("stats");
      let bytes: Buffer | undefined;
      await page.route("**/resources/read", async (route) => {
        const response = await route.fetch({ maxRetries: 0 });
        bytes = await response.body();
        received();
        await gate;
        await route.fulfill({ response, body: bytes });
      });
      await p
        .getByRole("button", {
          name: "Read controller application capacity",
          exact: true,
        })
        .click();
      await arrived;
      await expectWorkspaceNavigationLocked(page);
      release();
      const observation = p.getByRole("region", {
        name: "Observed controller application capacity",
        exact: true,
      });
      await expect(observation).toContainText(
        "Controller capacity observed: 131072 bytes.",
      );
      await expect(observation).toContainText(
        "The current program was not read",
      );
      const saved = page.waitForEvent("download");
      await p
        .getByRole("button", {
          name: "Save exact capacity evidence",
          exact: true,
        })
        .click();
      expect(await readFile((await (await saved).path())!)).toEqual(bytes);
      const after = await peer.command("stats");
      expect(after.events).toEqual(before.events);
      expect(
        after.request_types
          .slice(before.request_types.length)
          .every((x: string) =>
            ["ReadPropertyRequest", "ConfirmedPrivateTransferRequest"].includes(
              x,
            ),
          ),
      ).toBe(true);
      expect(after.router_errors).toEqual([]);
    } finally {
      release();
      peer.close();
    }
  });

test("offline archive size inspection does not open the field network", async ({
  page,
  request,
  nativeScheduleWriteServer,
}) => {
  const data = seedOrderCapabilities(nativeScheduleWriteServer.directory);
  await page.goto("/");
  await page
    .getByRole("button", { name: "New application", exact: true })
    .click();
  await openNativeCompiler(page);
  const compiler = page.getByRole("region", {
    name: "Native backup default compiler",
    exact: true,
  });
  await compiler
    .getByLabel("Retained native backup", { exact: true })
    .selectOption(data.cases.valid.id);
  await inspect(compiler);
  const p = panel(page);
  await p.locator(":scope > summary").click();
  await p
    .getByRole("button", {
      name: "Inspect retained application size",
      exact: true,
    })
    .click();
  await expect(
    p.getByRole("region", { name: "Retained application sizes", exact: true }),
  ).toBeVisible();
  await expect(
    p.getByRole("button", {
      name: "Read controller application capacity",
      exact: true,
    }),
  ).toBeDisabled();
  expect(
    (await (await request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
});

for (const field of ["capacity", "source", "wire", "authority"])
  test(`altered capacity ${field} cannot be displayed as an observation`, async ({
    page,
  }) => {
    const peer = await nativeDefaultPeer("consume", "execution-order");
    try {
      const p = await connected(page, peer);
      await page.route("**/resources/read", async (route) => {
        const response = await route.fetch({ maxRetries: 0 }),
          data = await response.json();
        if (field === "capacity") data.capacity.bytes++;
        if (field === "source") data.source.snapshot_sha256 = "f".repeat(64);
        if (field === "wire") data.capacity.wire.response_apdu_hex = "30010c";
        if (field === "authority") data.can_apply = true;
        await route.fulfill({ response, json: data });
      });
      await p
        .getByRole("button", {
          name: "Read controller application capacity",
          exact: true,
        })
        .click();
      await expect(p.getByRole("alert")).toContainText(
        "does not match the selected source",
      );
      await expect(
        p.getByRole("region", {
          name: "Observed controller application capacity",
          exact: true,
        }),
      ).toHaveCount(0);
    } finally {
      peer.close();
    }
  });

test("coalesced close/reopen retires a cached capacity export", async ({
  page,
}) => {
  const peer = await nativeDefaultPeer("consume", "execution-order");
  try {
    const p = await connected(page, peer);
    await p
      .getByRole("button", {
        name: "Read controller application capacity",
        exact: true,
      })
      .click();
    const save = p.getByRole("button", {
      name: "Save exact capacity evidence",
      exact: true,
    });
    await expect(save).toBeEnabled();
    const old = await save.elementHandle();
    let downloads = 0;
    page.on("download", () => downloads++);
    await p.locator(":scope > summary").evaluate((e, old) => {
      (e as HTMLElement).click();
      (e as HTMLElement).click();
      (old as HTMLElement).click();
    }, old);
    await expect(save).toHaveCount(0);
    expect(downloads).toBe(0);
    await expect(
      p.getByRole("button", {
        name: "Read controller application capacity",
        exact: true,
      }),
    ).toBeEnabled();
  } finally {
    peer.close();
  }
});

test("canceling a held read retires its result and a fresh query remains usable", async ({
  page,
}) => {
  const peer = await nativeDefaultPeer("consume", "execution-order");
  let release = () => {},
    held = false;
  const gate = new Promise<void>((r) => (release = r));
  try {
    const p = await connected(page, peer);
    await page.route(
      "**/resources/read",
      async (route) => {
        const response = await route.fetch({ maxRetries: 0 });
        held = true;
        await gate;
        await route.fulfill({ response });
      },
      { times: 1 },
    );
    await p
      .getByRole("button", {
        name: "Read controller application capacity",
        exact: true,
      })
      .click();
    await expect.poll(() => held).toBe(true);
    await p
      .getByRole("button", { name: "Cancel capacity query", exact: true })
      .click();
    release();
    await expect(
      p.getByRole("button", {
        name: "Read controller application capacity",
        exact: true,
      }),
    ).toBeEnabled();
    await expect(
      p.getByRole("region", {
        name: "Observed controller application capacity",
        exact: true,
      }),
    ).toHaveCount(0);
    await p
      .getByRole("button", {
        name: "Read controller application capacity",
        exact: true,
      })
      .click();
    await expect(
      p.getByRole("region", {
        name: "Observed controller application capacity",
        exact: true,
      }),
    ).toContainText("131072 bytes");
  } finally {
    release();
    peer.close();
  }
});
