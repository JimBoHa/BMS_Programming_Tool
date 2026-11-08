import { expect, test } from "@playwright/test";
import { python } from "./caf-native-fixture";

const html = python(`
from bms_tool.nae_signin_page import native_signin_page
print(native_signin_page(name='Example NAE',origin='engine.example',
    device='Device 123',model='Example NAE',firmware='example',certificate_sha256='a'*64))
`);

for (const viewport of [
  { width: 1440, height: 1000 },
  { width: 390, height: 844 },
]) {
  test(`native sign-in submits once without refresh, reports refusal, accepts retry and closes at ${viewport.width}px`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    const errors: string[] = [],
      documents: string[] = [];
    const logins: unknown[] = [];
    let accepted = false,
      closeCount = 0,
      release: () => void = () => {};
    const pending = new Promise<void>((resolve) => {
      release = resolve;
    });
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("request", (request) => {
      if (request.isNavigationRequest()) documents.push(request.url());
    });
    await page.route("**/native-nae-qualification", (route) =>
      route.fulfill({ contentType: "text/html", body: html }),
    );
    await page.route("**/api/session", (route) =>
      route.fulfill({ json: { token: "authored-local-token" } }),
    );
    await page.route("**/api/nae-qualification/*", async (route) => {
      const request = route.request();
      expect(request.method()).toBe("POST");
      expect(request.headers()["x-studio-token"]).toBe("authored-local-token");
      if (new URL(request.url()).pathname.endsWith("/login")) {
        logins.push(request.postDataJSON());
        if (!accepted) await pending;
        await route.fulfill(
          accepted
            ? { json: { authenticated: true, account: "authored-user" } }
            : {
                status: 400,
                json: { detail: "The native NAE rejected this account." },
              },
        );
      } else {
        expect(new URL(request.url()).pathname).toBe(
          "/api/nae-qualification/close",
        );
        expect(request.postDataJSON()).toEqual({});
        closeCount++;
        await route.fulfill({ json: { authenticated: false } });
      }
    });
    await page.goto("/native-nae-qualification");
    const button = page.getByRole("button", {
      name: "Sign in directly to NAE",
      exact: true,
    });
    const password = page.getByLabel("NAE account password", { exact: true });
    await expect(button).toBeEnabled();
    await page
      .getByLabel("NAE account username", { exact: true })
      .fill("authored-user");
    await password.fill("authored & <password>");
    await button.click();
    await expect(password).toHaveValue("");
    await expect(button).toBeDisabled();
    await expect.poll(() => logins.length).toBe(1);
    // A second form event while the request is outstanding must not dispatch again.
    await page.locator("#signin").dispatchEvent("submit");
    release();
    await expect(page.getByRole("status")).toHaveText(
      "The native NAE rejected this account.",
    );
    expect(logins).toEqual([
      { username: "authored-user", password: "authored & <password>" },
    ]);
    await expect(button).toBeEnabled();
    accepted = true;
    await password.fill("authored & <password>");
    await password.press("Enter");
    await expect(page.getByRole("status")).toHaveText(
      "Native NAE login accepted for authored-user.\nNo JCT/SCT dependency. No configuration writes performed.",
    );
    await expect(page.locator("#signin")).toBeHidden();
    await page
      .getByRole("button", { name: "Close native engine session" })
      .click();
    await expect(button).toBeVisible();
    await expect(page.getByRole("status")).toHaveText(
      "Native engine session closed.",
    );
    expect(closeCount).toBe(1);
    expect(logins).toHaveLength(2);
    expect(documents).toHaveLength(1);
    expect(errors).toEqual([]);
    expect(page.url()).toMatch(/\/native-nae-qualification$/);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  });
}

test("native sign-in remains disabled without JavaScript", async ({
  browser,
}) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  try {
    const page = await context.newPage();
    await page.route("**/native-nae-qualification", (route) =>
      route.fulfill({ contentType: "text/html", body: html }),
    );
    await page.goto("http://127.0.0.1:8766/native-nae-qualification");
    await expect(
      page.getByRole("button", { name: "Sign in directly to NAE" }),
    ).toBeDisabled();
    await expect(page.locator("noscript")).toContainText(
      "No credentials have been sent.",
      { useInnerText: true },
    );
  } finally {
    await context.close();
  }
});
