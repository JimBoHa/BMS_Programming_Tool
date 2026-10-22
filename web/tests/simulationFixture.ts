import { test as base, expect, type Response } from "@playwright/test";
export { expect } from "@playwright/test";
export type { Page, Locator } from "@playwright/test";

type Handle = {
  session: string;
  retirement_token: string;
  creation_operation_id: string;
};

/** Abrupt browser context disposal does not guarantee a document-exit request.
 * Retire only engines proved to have been created by this test's page requests.
 * This fixture never enumerates sessions or clears another test's cache entries.
 */
export const test = base.extend<{ _simulationOwnership: boolean }>({
  _simulationOwnership: [
    async ({ page, request }, use) => {
      const handles = new Map<string, Handle>();
      const pending = new Set<Promise<void>>();
      const observe = (response: Response) => {
        if (
          new URL(response.url()).pathname !== "/api/simulation/step" ||
          response.request().method() !== "POST" ||
          response.status() !== 200
        )
          return;
        const task = (async () => {
          try {
            const admitted = response.request().postDataJSON();
            if (
              admitted.session != null ||
              typeof admitted.operation_id !== "string" ||
              !/^[a-f0-9]{32}$/.test(admitted.operation_id)
            )
              return;
            const receipt = await response.json();
            if (
              receipt.operation_id !== admitted.operation_id ||
              receipt.session_creation_operation_id !== admitted.operation_id ||
              typeof receipt.session !== "string" ||
              !/^[A-Za-z0-9_-]{20,64}$/.test(receipt.session) ||
              typeof receipt.retirement_token !== "string" ||
              !/^[A-Za-z0-9_-]{32,64}$/.test(receipt.retirement_token)
            )
              return;
            handles.set(receipt.session, {
              session: receipt.session,
              retirement_token: receipt.retirement_token,
              creation_operation_id: admitted.operation_id,
            });
          } catch {
            // Missing/unverifiable replies remain subject to the product TTL.
            // Do not guess ownership or hide them with a global cache clear.
          }
        })();
        pending.add(task);
        void task.finally(() => pending.delete(task));
      };
      page.on("response", observe);
      try {
        await use(true);
      } finally {
        await Promise.all([...pending]);
        // Stop further page timers before retiring this test's known engines.
        // This is test resource teardown, not a guarantee about browser exit.
        if (!page.isClosed()) await page.close();
        await Promise.all([...pending]);
        page.off("response", observe);
        if (handles.size) {
          const session = await (await request.get("/api/session")).json();
          for (const handle of handles.values()) {
            const response = await request.post("/api/simulation/retire", {
              headers: { "X-Studio-Token": session.token },
              data: handle,
            });
            expect(response.ok(), "Owned test-session retirement failed").toBe(
              true,
            );
            const receipt = await response.json();
            expect(receipt.session).toBe(handle.session);
            expect(receipt.recorded_evidence_unchanged).toBe(true);
          }
        }
      }
    },
    { auto: true },
  ],
});
