import { test, expect } from "./nativeScheduleWriteFixture";
import {
  allocatedPeer,
  openFieldInputs,
} from "./native-terminal-field-fixture";

test("substituted terminal mode proof cancels review and never offers Apply", async ({
  page,
  request,
}) => {
  const peer = await allocatedPeer(request);
  try {
    const inputs = await openFieldInputs(page, peer),
      before = await peer.command("stats");
    await page.route("**/native-application/input/preview", async (route) => {
      const response = await route.fetch(),
        v = await response.json();
      v.compilation.stored_configuration.setup = 9;
      await route.fulfill({ response, json: v });
    });
    const canceled = page.waitForResponse(
      (r) =>
        r.request().method() === "POST" &&
        r.url().endsWith("/native-application/cancel"),
    );
    await inputs
      .getByRole("button", {
        name: "Review controller input change",
        exact: true,
      })
      .click();
    await expect(inputs.getByRole("alert")).toContainText(
      "Terminal transfer proof differs",
    );
    await canceled;
    await expect(
      inputs.getByRole("button", {
        name: "Apply input change to controller",
        exact: true,
      }),
    ).toHaveCount(0);
    expect(
      (await peer.command("stats")).events.filter(
        (e: any[]) => e[0] === "write",
      ),
    ).toEqual(before.events.filter((e: any[]) => e[0] === "write"));
  } finally {
    peer.close();
  }
});

test("page hide retires a pending terminal preview and its returned token", async ({
  page,
  request,
}) => {
  const peer = await allocatedPeer(request);
  try {
    const inputs = await openFieldInputs(page, peer);
    let release!: () => void, seen!: () => void;
    const gate = new Promise<void>((r) => (release = r)),
      arrived = new Promise<void>((r) => (seen = r));
    await page.route("**/native-application/input/preview", async (route) => {
      const response = await route.fetch();
      seen();
      await gate;
      await route.fulfill({ response });
    });
    await inputs
      .getByRole("button", {
        name: "Review controller input change",
        exact: true,
      })
      .click();
    await arrived;
    await page.evaluate(() => window.dispatchEvent(new Event("pagehide")));
    release();
    await expect(
      inputs.getByRole("button", {
        name: "Review controller input change",
        exact: true,
      }),
    ).toBeEnabled();
    await expect(
      inputs.getByRole("region", { name: "Input change review", exact: true }),
    ).toHaveCount(0);
    await expect(
      inputs.getByRole("button", {
        name: "Apply input change to controller",
        exact: true,
      }),
    ).toHaveCount(0);
  } finally {
    peer.close();
  }
});

test("a delayed digest cannot resurrect a terminal review after lifecycle retirement", async ({
  page,
  request,
}) => {
  const peer = await allocatedPeer(request);
  try {
    const inputs = await openFieldInputs(page, peer);
    await page.evaluate(() => {
      const w = window as any,
        original = crypto.subtle.digest.bind(crypto.subtle);
      w.terminalDigestWaiting = [];
      w.terminalDigestDone = 0;
      w.terminalDigestDelay = true;
      crypto.subtle.digest = async (algorithm: any, value: any) => {
        const tracked = new TextDecoder()
          .decode(value)
          .includes("tagged-moi-local-terminal-copy/2");
        if (tracked && w.terminalDigestDelay)
          await new Promise<void>((r) => w.terminalDigestWaiting.push(r));
        const result = await original(algorithm, value);
        if (tracked) w.terminalDigestDone++;
        return result;
      };
    });
    await inputs
      .getByRole("button", {
        name: "Review controller input change",
        exact: true,
      })
      .click();
    await page.waitForFunction(
      () => (window as any).terminalDigestWaiting.length > 0,
    );
    await page.evaluate(() => {
      const w = window as any;
      window.dispatchEvent(new Event("pagehide"));
      w.terminalDigestDelay = false;
      w.terminalDigestWaiting.splice(0).forEach((r: any) => r());
    });
    await page.waitForFunction(() => (window as any).terminalDigestDone >= 2);
    await expect(
      inputs.getByRole("button", {
        name: "Review controller input change",
        exact: true,
      }),
    ).toBeEnabled();
    await expect(
      inputs.getByRole("region", { name: "Input change review", exact: true }),
    ).toHaveCount(0);
    await expect(
      inputs.getByRole("button", {
        name: "Apply input change to controller",
        exact: true,
      }),
    ).toHaveCount(0);
  } finally {
    peer.close();
  }
});
