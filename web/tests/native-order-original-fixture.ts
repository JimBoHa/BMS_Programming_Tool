import { test as base } from "./nativeScheduleWriteFixture";
import { nativeDefaultPeer } from "./native-default-peer";
import { seedPreviousOrderAPI } from "./native-order-recovery-transfer-browser-fixture";

/** Prepare a completed original transfer before testing its new recovery UI.
 * Both phases retain their own 30-second deadline. Real restore preparation,
 * acknowledgment waits and readback use the installed application's defaults.
 * Each test still owns its server, controller, original files and cleanup.
 */
export function originalOrderFixture(routed: boolean, historical = false) {
  return base.extend<{
    originalOrder: {
      peer: Awaited<ReturnType<typeof nativeDefaultPeer>>;
      seeded: Awaited<ReturnType<typeof seedPreviousOrderAPI>>;
    };
  }>({
    originalOrder: [
      async ({ request }, use) => {
        const peer = await nativeDefaultPeer("consume", "execution-order");
        try {
          const seeded = await seedPreviousOrderAPI(
            request,
            peer,
            routed,
            historical,
          );
          await use({ peer, seeded });
        } finally {
          peer.close();
        }
      },
      { timeout: 30000 },
    ],
  });
}
