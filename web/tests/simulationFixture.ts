import {
  test as base,
  expect,
  type APIResponse,
  type Page,
  type Request,
  type Response,
  type Route,
} from "@playwright/test";
export { expect } from "@playwright/test";
export type { Page, Locator, APIRequestContext } from "@playwright/test";

type Handle = {
  session: string;
  retirement_token: string;
  creation_operation_id: string;
};
type Capture = {
  page: Page;
  pageURL: string;
  request: Request;
  url: string;
  status: number;
  body: Buffer;
};
type Owner = {
  failures: string[];
  pending: Set<Promise<APIResponse>>;
  observe: (capture: Capture) => void;
};
const captures = new WeakMap<Request, Capture>(),
  owners = new WeakMap<Page, Owner>();
const path = (url: string) => new URL(url).pathname;
const simulationPath = (url: string) =>
  ["/api/simulation/step", "/api/simulation/scenario"].includes(path(url));

/** Only actual same-request HTTP replies can nominate a newly created owned engine. */
export function ownedSimulationHandle(proof: {
  pageURL: string;
  requestURL: string;
  responseURL: string;
  method: string;
  status: number;
  requestBody: string | null;
  responseBody: string;
}): Handle | null {
  try {
    if (
      proof.method !== "POST" ||
      proof.status !== 200 ||
      proof.requestURL !== proof.responseURL ||
      new URL(proof.pageURL).origin !== new URL(proof.requestURL).origin ||
      path(proof.requestURL) !== "/api/simulation/step"
    )
      return null;
    const admitted = JSON.parse(proof.requestBody || ""),
      receipt = JSON.parse(proof.responseBody);
    if (
      admitted.session != null ||
      typeof admitted.operation_id !== "string" ||
      !/^[a-f0-9]{32}$/.test(admitted.operation_id) ||
      receipt.operation_id !== admitted.operation_id ||
      receipt.session_creation_operation_id !== admitted.operation_id ||
      typeof receipt.session !== "string" ||
      !/^[A-Za-z0-9_-]{20,64}$/.test(receipt.session) ||
      typeof receipt.retirement_token !== "string" ||
      !/^[A-Za-z0-9_-]{32,64}$/.test(receipt.retirement_token)
    )
      return null;
    return {
      session: receipt.session,
      retirement_token: receipt.retirement_token,
      creation_operation_id: admitted.operation_id,
    };
  } catch {
    return null;
  }
}

/** One real HTTP request, no redirects/retries; retain private bytes before held/fault delivery. */
export async function fetchSimulationResponse(
  route: Route,
): Promise<APIResponse> {
  const request = route.request();
  if (request.method() !== "POST" || !simulationPath(request.url()))
    throw new Error("Simulation capture requires its exact POST source.");
  const page = request.frame().page(),
    pageURL = page.url();
  if (new URL(pageURL).origin !== new URL(request.url()).origin)
    throw new Error("Simulation capture cannot change its page's HTTP origin.");
  const owner = owners.get(page);
  if (!owner || page.isClosed())
    throw new Error("Simulation capture requires its still-owned open page.");
  const task = (async () => {
    const response = await route.fetch({ maxRedirects: 0, maxRetries: 0 });
    const body = await response.body();
    if (response.url() !== request.url())
      throw new Error("Simulation HTTP source changed.");
    const capture = {
      request,
      page,
      pageURL,
      url: response.url(),
      status: response.status(),
      body: Buffer.from(body),
    };
    captures.set(request, capture);
    owner?.observe(capture);
    return response;
  })();
  owner?.pending.add(task);
  try {
    return await task;
  } catch (error) {
    if (owner.failures.length < 16)
      owner.failures.push(String(error).slice(0, 200));
    throw error;
  } finally {
    owner?.pending.delete(task);
  }
}
/** Backend receipt evidence, not a replacement for intentionally forged UI-delivery assertions. */
export function simulationServerResponseText(response: Response): string {
  const capture = captures.get(response.request());
  if (
    !capture ||
    capture.request !== response.request() ||
    capture.url !== response.url()
  )
    throw new Error(
      "No exact actual-HTTP simulation response was captured for this PageRequest.",
    );
  return capture.body.toString("utf8");
}
export const simulationServerResponseJSON = (response: Response): any =>
  JSON.parse(simulationServerResponseText(response));

/** Release only engines proved to belong to this page's original creation nonce.
 * Chromium may expose an empty CDP body for fetch().blob(), even with valid HTTP/UI.
 * Capturing actual HTTP bytes also preserves ownership before a held response is delivered.
 */
export const test = base.extend<{ _simulationOwnership: boolean }>({
  _simulationOwnership: [
    async ({ page, context, request }, use, info) => {
      const handles = new Map<string, Handle>(),
        pending = new Set<Promise<APIResponse>>(),
        failures: string[] = [];
      owners.set(page, {
        pending,
        failures,
        observe(capture) {
          if (capture.page !== page) return;
          const handle = ownedSimulationHandle({
            pageURL: capture.pageURL,
            requestURL: capture.request.url(),
            responseURL: capture.url,
            method: capture.request.method(),
            status: capture.status,
            requestBody: capture.request.postData(),
            responseBody: capture.body.toString("utf8"),
          });
          if (handle) handles.set(handle.session, handle);
        },
      });
      const pattern = /\/api\/simulation\/(?:step|scenario)$/;
      const forward = async (route: Route) => {
        if (route.request().method() !== "POST") return route.fallback();
        const response = await fetchSimulationResponse(route);
        // A fresh copy prevents a fault handler from modifying private original evidence.
        const body = Buffer.from(captures.get(route.request())!.body);
        if (!captures.get(route.request())!.page.isClosed())
          await route.fulfill({ response, body });
      };
      // Context routes survive page.unroute() used to retire later held/fault handlers.
      await context.route(pattern, forward);
      let closed = false;
      const close = () => {
        closed = true;
      };
      context.on("close", close);
      try {
        await use(true);
      } finally {
        const cleanupErrors: unknown[] = [];
        try {
          if (!page.isClosed()) await page.close();
        } catch (error) {
          cleanupErrors.push(error);
        }
        // A failed/aborted acquisition is unknown, never proof of no server commit.
        // It must not prevent cleanup of already proved independent receipts.
        await Promise.allSettled([...pending]);
        owners.delete(page);
        try {
          if (!closed) await context.unroute(pattern, forward);
        } catch (error) {
          cleanupErrors.push(error);
        } finally {
          context.off("close", close);
        }
        if (failures.length)
          info.annotations.push({
            type: "unverified-simulation-capture",
            description:
              "Failed acquisition has no proved handle; product idle expiry remains. " +
              failures.join("; "),
          });
        if (handles.size) {
          try {
            const session = await (await request.get("/api/session")).json();
            for (const handle of handles.values()) {
              try {
                const response = await request.post("/api/simulation/retire", {
                  headers: { "X-Studio-Token": session.token },
                  data: handle,
                });
                expect(
                  response.ok(),
                  "Owned test-session retirement failed",
                ).toBe(true);
                const receipt = await response.json();
                expect(receipt.session).toBe(handle.session);
                expect(receipt.recorded_evidence_unchanged).toBe(true);
              } catch (error) {
                cleanupErrors.push(error);
              }
            }
          } catch (error) {
            cleanupErrors.push(error);
          }
        }
        expect(
          cleanupErrors,
          "Fixture cleanup must finish for every proved owned handle",
        ).toEqual([]);
      }
    },
    { auto: true },
  ],
});
