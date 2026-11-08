import { test, expect, type Page } from "./nativeScheduleWriteFixture";
import { chooseWorkspaceSurface } from "./workspace-navigation";

const key = "A".repeat(32),
  objectId = "11111111-1111-4111-8111-111111111111";
const signedIn = {
  connection_id: key,
  account: "Authored configuration user",
  server_origin: "https://configuration.example",
  tool_version: { major: 18, minor: 0 },
  connected: true,
  read_only: true,
  archive_edit_available: false,
  device_transfer_available: false,
};

async function fixture(
  page: Page,
  options: {
    reject?: boolean;
    holdConnect?: Promise<void>;
    holdProfile?: Promise<void>;
    expired?: boolean;
  } = {},
) {
  const posts: any[] = [];
  await page.route("**/api/jct/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: any = {};
    if (route.request().method() === "POST") {
      body = route.request().postDataJSON();
      posts.push({ path, body });
    }
    if (path.endsWith("/profile")) {
      await options.holdProfile;
      return route.fulfill({
        json: {
          service_hint: {
            server_origin: "https://configuration.example",
            certificate_sha256: "1".repeat(64),
          },
        },
      });
    }
    if (path.endsWith("/connect")) {
      await options.holdConnect;
      return route.fulfill(
        options.reject
          ? {
              status: 422,
              json: {
                detail:
                  "JCT configuration sign-in was not accepted (HTTP 400).",
              },
            }
          : { json: signedIn },
      );
    }
    if (path.endsWith("/disconnect"))
      return route.fulfill({ json: { connected: false } });
    if (path.endsWith("/status"))
      return route.fulfill({
        json: { ...signedIn, connected: !options.expired },
      });
    if (path.endsWith("/archives"))
      return route.fulfill(
        options.expired
          ? {
              status: 422,
              json: { detail: "The JCT connection expired. Sign in again." },
            }
          : { json: { items: [{ name: "ExampleArchive" }] } },
      );
    if (path.endsWith("/archive/devices"))
      return route.fulfill({
        json: {
          items: [
            {
              id: objectId,
              name: "Authored engine",
              itemReference: "Example:Engine",
            },
          ],
        },
      });
    if (path.endsWith("/archive/object"))
      return route.fulfill({
        json: {
          document: {
            item: {
              id: objectId,
              name: "Authored engine",
              firmwareVersion: "Authored version",
              objectIdentifier: { instance: 42 },
            },
            objectType: "Authored engine type",
          },
          redacted_fields: ["/item/credential"],
          editable: false,
          native_backup: false,
        },
      });
    throw new Error("Unexpected configuration operation: " + path);
  });
  return posts;
}

async function open(page: Page) {
  await page.goto("/");
  await expect(page.getByRole("link", { name: /^BMS Studio/ })).toBeVisible();
  if ((page.viewportSize()?.width || 1440) < 800)
    await expect(
      page.getByRole("button", { name: "Open navigation", exact: true }),
    ).toBeVisible();
  await chooseWorkspaceSurface(page, "Settings");
  const tools = page.getByRole("navigation", {
    name: "Controller task tools",
    exact: true,
  });
  await expect(tools).toBeVisible();
  const select = tools.getByRole("combobox", {
    name: "Controller task tools",
    exact: true,
  });
  if (await select.isVisible())
    await select.selectOption({ label: "JCT configuration connection" });
  else
    await tools
      .getByRole("button", {
        name: "JCT configuration connection",
        exact: true,
      })
      .click();
  return page.getByRole("region", {
    name: "JCT configuration connection",
    exact: true,
  });
}

async function signIn(panel: ReturnType<Page["getByRole"]>) {
  await expect(
    panel.getByLabel("Configuration service URL", { exact: true }),
  ).toHaveValue("https://configuration.example");
  await panel
    .getByLabel("Configuration username", { exact: true })
    .fill("authored-user");
  await panel
    .getByLabel("Configuration password", { exact: true })
    .fill("authored-password");
  await panel
    .getByRole("button", {
      name: "Sign in to configuration service",
      exact: true,
    })
    .click();
}

for (const width of [1440, 390])
  test(
    "configuration connection and archive reads stay in Settings at " +
      width +
      "px",
    async ({ page, nativeScheduleWriteServer }, info) => {
      await page.setViewportSize({ width, height: 1000 });
      const posts = await fixture(page),
        panel = await open(page);
      await signIn(panel);
      await expect(panel.getByRole("status")).toContainText(
        "Configuration login established",
      );
      await panel
        .getByRole("button", { name: "Read archives", exact: true })
        .click();
      await panel
        .getByRole("combobox", { name: "Configuration archive", exact: true })
        .selectOption("ExampleArchive");
      await panel
        .getByRole("button", { name: "Read archive devices", exact: true })
        .click();
      await panel
        .getByRole("button", { name: "Inspect configuration", exact: true })
        .click();
      await expect(
        panel.getByRole("region", { name: "Selected archive object" }),
      ).toContainText("offline engineering configuration");
      await expect(panel).toContainText("Credential fields are withheld");
      await expect(panel).toContainText(
        "transfer to a controller remain unavailable",
      );
      await page.screenshot({
        path: info.outputPath("jct-connection-" + width + ".png"),
      });
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      expect(posts.filter((x) => x.path.endsWith("/connect"))).toHaveLength(1);
      expect(
        posts
          .filter((x) => x.path.includes("archive/"))
          .every(
            (x) =>
              x.body.connection_id === key &&
              x.body.archive === "ExampleArchive",
          ),
      ).toBe(true);
      const status = await (
        await page.request.get(
          nativeScheduleWriteServer.url + "/api/bacnet/status",
        )
      ).json();
      expect(status.connected).toBe(false);
      await panel
        .getByRole("button", {
          name: "Close configuration connection",
          exact: true,
        })
        .click();
      await expect(
        panel.getByLabel("Configuration password", { exact: true }),
      ).toHaveValue("");
    },
  );

test("a rejected configuration sign-in clears the credential draft", async ({
  page,
}) => {
  await fixture(page, { reject: true });
  const panel = await open(page);
  await signIn(panel);
  await expect(panel.getByRole("alert")).toContainText("not accepted");
  await expect(
    panel.getByLabel("Configuration password", { exact: true }),
  ).toHaveValue("");
});

test("leaving Settings retires a late sign-in and closes its new session", async ({
  page,
}) => {
  let release!: () => void;
  const hold = new Promise<void>((resolve) => (release = resolve));
  const posts = await fixture(page, { holdConnect: hold });
  const panel = await open(page);
  await signIn(panel);
  await expect
    .poll(() => posts.filter((x) => x.path.endsWith("/connect")).length)
    .toBe(1);
  await expect(
    panel.getByLabel("Configuration password", { exact: true }),
  ).toHaveValue("");
  await chooseWorkspaceSurface(page, "Help");
  release();
  await expect
    .poll(() => posts.filter((x) => x.path.endsWith("/disconnect")).length)
    .toBe(1);
  await expect(panel).not.toBeVisible();
});

test("a delayed profile preserves an origin already being edited", async ({
  page,
}) => {
  let release!: () => void;
  const hold = new Promise<void>((resolve) => (release = resolve));
  await fixture(page, { holdProfile: hold });
  const panel = await open(page);
  await panel
    .getByLabel("Configuration service URL", { exact: true })
    .fill("https://other.example");
  release();
  await expect(
    panel.getByLabel("Configuration service URL", { exact: true }),
  ).toHaveValue("https://other.example");
});

test("an expired configuration session returns to sign-in without another login request", async ({
  page,
}) => {
  const posts = await fixture(page, { expired: true });
  const panel = await open(page);
  await signIn(panel);
  await panel
    .getByRole("button", { name: "Read archives", exact: true })
    .click();
  await expect(
    panel.getByLabel("Configuration password", { exact: true }),
  ).toHaveValue("");
  await expect(
    panel.getByRole("button", {
      name: "Sign in to configuration service",
      exact: true,
    }),
  ).toBeVisible();
  expect(posts.filter((x) => x.path.endsWith("/connect"))).toHaveLength(1);
});
