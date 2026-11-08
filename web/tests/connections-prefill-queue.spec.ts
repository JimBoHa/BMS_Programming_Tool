import { test, expect, type Page } from "./nativeScheduleWriteFixture";
import { createSocket } from "node:dgram";

async function freePort(): Promise<number> {
  const socket = createSocket("udp4");
  return new Promise((resolve, reject) => {
    socket.once("error", reject);
    socket.bind(0, "127.0.0.1", () => {
      const address = socket.address();
      if (typeof address !== "string" && address.port === 47809) {
        // Keep that port reserved while choosing a different comparison value.
        void freePort().then(
          (port) => socket.close(() => resolve(port)),
          (error) => socket.close(() => reject(error)),
        );
        return;
      }
      socket.close(() =>
        resolve(typeof address === "string" ? 0 : address.port),
      );
    });
  });
}

/** Claim the visible draft between passive prefill scheduling and its commit.
 * This models a focus/text-selection event arriving after an automatic update
 * was queued. Merely holding the HTTP response until after focus misses it.
 * The hook observes React's existing commit boundary; the only injected product
 * interactions are focus and select, performed in the next browser microtask.
 */
async function claimQueuedPrefill(page: Page, kind: "network" | "status") {
  await page.addInitScript(
    ({ kind }) => {
      const state = {
        armed: false,
        claimed: false,
        value: "",
        automatic: "",
        selection: [] as number[],
        events: [] as { phase: string; value: string }[],
      };
      (window as any).__prefillClaim = state;
      (window as any).__REACT_DEVTOOLS_GLOBAL_HOOK__ = {
        supportsFiber: true,
        renderers: new Map(),
        inject(renderer: unknown) {
          this.renderers.set(1, renderer);
          return 1;
        },
        onCommitFiberRoot() {},
        onCommitFiberUnmount() {},
        onPostCommitFiberRoot() {
          if (!state.armed || state.claimed) return;
          const input = [...document.querySelectorAll("label")]
            .find(
              (label) =>
                label.textContent?.trim() === "Local bind address / UDP port",
            )
            ?.querySelector("input");
          if (!input || input.value !== "127.0.0.1:47809") return;
          const ready =
            kind === "network"
              ? document.querySelector('option[value="192.0.2.12"]')
              : document.body.textContent?.includes("BACnet interface open");
          if (!ready) return;
          state.claimed = true;
          state.events.push({
            phase: "post-passive-commit",
            value: input.value,
          });
          queueMicrotask(() => {
            state.events.push({
              phase: "before-native-focus",
              value: input.value,
            });
            input.addEventListener(
              "focus",
              () => {
                state.events.push({
                  phase: "native-focus",
                  value: input.value,
                });
              },
              { once: true },
            );
            input.addEventListener(
              "focusin",
              () => {
                state.events.push({
                  phase: "native-focusin",
                  value: input.value,
                });
              },
              { once: true },
            );
            input.focus();
            state.events.push({
              phase: "after-native-focus",
              value: input.value,
            });
            input.select();
            state.value = input.value;
            state.selection = [input.selectionStart!, input.selectionEnd!];
          });
        },
      };
    },
    { kind },
  );
}

for (const kind of ["network", "status"] as const)
  for (const width of [1440, 390])
    test(`${kind} queued prefill preserves focused selection and exact interface at ${width}px`, async ({
      page,
      request,
    }) => {
      await page.setViewportSize({ width, height: 1000 });
      await claimQueuedPrefill(page, kind);
      const headers = {
        "X-Studio-Token": (await (await request.get("/api/session")).json())
          .token,
      };
      await request.post("/api/bacnet/disconnect", { headers, data: {} });
      const savedLocalAddress = `127.0.0.1:${await freePort()}`;
      const automatic =
        kind === "network" ? "192.0.2.12:47809" : savedLocalAddress;
      if (kind === "status") {
        const response = await request.post("/api/bacnet/connect", {
          headers,
          data: {
            local_address: savedLocalAddress,
            instance: 4190032,
          },
        });
        expect(response.ok()).toBe(true);
      }
      let release!: () => void;
      const gate = new Promise<void>((resolve) => {
        release = resolve;
      });
      let observed!: () => void;
      const received = new Promise<void>((resolve) => {
        observed = resolve;
      });
      await page.route("**/api/bacnet/interfaces", async (route) => {
        if (kind === "network") {
          observed();
          await gate;
        }
        await route.fulfill({
          json: {
            interfaces:
              kind === "network"
                ? [
                    {
                      address: "192.0.2.12",
                      name: "Authored network",
                      network: "192.0.2.0/24",
                      recommended: true,
                      broadcast_available: true,
                    },
                  ]
                : [],
          },
        });
      });
      if (kind === "status") {
        let first = true;
        await page.route("**/api/bacnet/status", async (route) => {
          if (!first) return route.continue();
          first = false;
          const response = await route.fetch({ maxRetries: 0 });
          observed();
          await gate;
          await route.fulfill({ response });
        });
      }
      try {
        await page.goto("/");
        await page
          .getByRole("button", { name: /^Connect to a controller/ })
          .click();
        await received;
        await page.evaluate((automatic) => {
          (window as any).__prefillClaim.automatic = automatic;
          (window as any).__prefillClaim.armed = true;
        }, automatic);
        release();
        await expect
          .poll(() =>
            page.evaluate(() => !!(window as any).__prefillClaim.value),
          )
          .toBe(true);
        const claim = await page.evaluate(() => (window as any).__prefillClaim);
        const expected = claim.events.find(
          (event: { phase: string }) => event.phase === "before-native-focus",
        ).value;
        expect(claim.events[0]).toEqual({
          phase: "post-passive-commit",
          value: "127.0.0.1:47809",
        });
        expect(["127.0.0.1:47809", automatic]).toContain(expected);
        // A queued prefill can commit before the native focus call. Preserve
        // exactly what was displayed at focus, including that legitimate case.
        // If it is still pending, the original default must remain unchanged.
        expect(claim.value).toBe(expected);
        const input = page.getByLabel("Local bind address / UDP port", {
          exact: true,
        });
        await expect(input).toHaveValue(expected);
        expect(
          await input.evaluate((element) => {
            const input = element as HTMLInputElement;
            return [input.selectionStart, input.selectionEnd];
          }),
        ).toEqual([0, expected.length]);
        const desired = `127.0.0.1:${await freePort()}`;
        await page.keyboard.insertText(desired);
        await expect(input).toHaveValue(desired);
        const sent = page.waitForRequest("**/api/bacnet/connect");
        const opened = page.waitForResponse("**/api/bacnet/connect");
        await page
          .getByRole("button", { name: "Open interface", exact: true })
          .click();
        expect((await sent).postDataJSON().local_address).toBe(desired);
        expect((await opened).ok()).toBe(true);
        expect(
          (await (await request.get("/api/bacnet/status")).json()).config
            .local_address,
        ).toBe(desired);
      } finally {
        await test.info().attach("prefill-event-order.json", {
          body: JSON.stringify(
            await page.evaluate(() => (window as any).__prefillClaim),
          ),
          contentType: "application/json",
        });
        release();
        const closed = await request.post("/api/bacnet/disconnect", {
          headers,
          data: {},
        });
        expect(closed.ok()).toBe(true);
      }
    });
