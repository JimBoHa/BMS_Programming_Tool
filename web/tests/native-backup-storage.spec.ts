import { test, expect, type Page } from "@playwright/test";
import { python } from "./caf-native-fixture";
import { chooseWorkspaceSurface } from "./workspace-navigation";

const endpoint =
  "/api/bacnet/controller/native-application/backup-library/list";
const panel = (page: Page) =>
  page.getByRole("region", { name: "Native backup library", exact: true });
function seed() {
  return JSON.parse(
    python(
      `
import sys,json,base64
from bms_tool.storage import Store
from bms_tool.application_store import ApplicationStore,native_storage_profile
from tests.test_native_signal_compiler import retained
from tests.test_caf_native_correlation import caf_source
s=ApplicationStore(Store(sys.argv[1]));capture=retained(s)
print(json.dumps({'capture':capture,'storage':native_storage_profile(),'caf':base64.b64encode(caf_source().original).decode()}))
`,
      process.env.BMS_TEST_COMPILER_STATE!,
    ),
  );
}
async function enter(page: Page, data: ReturnType<typeof seed>, caf = false) {
  await page.goto("/");
  if (caf) {
    const choosing = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: /^Open a CAF file/ }).click();
    await (
      await choosing
    ).setFiles({
      name: "storage-reference.caf",
      mimeType: "application/octet-stream",
      buffer: Buffer.from(data.caf, "base64"),
    });
    await expect(
      page.getByLabel("Current CAF archive", { exact: true }),
    ).toHaveText("storage-reference.caf");
  } else
    await page
      .getByRole("button", { name: "New application", exact: true })
      .click();
  await chooseWorkspaceSurface(page, "History");
  const tools = page.getByRole("navigation", {
    name: "history tools",
    exact: true,
  });
  await expect(tools).toBeVisible();
  const picker = tools.getByRole("combobox");
  if (await picker.isVisible())
    await picker.selectOption({ label: "Native backups" });
  else
    await tools
      .getByRole("button", { name: "Native backups", exact: true })
      .click();
  await expect(
    panel(page).getByRole("button", { name: "Refresh backups", exact: true }),
  ).toBeEnabled();
  const details = panel(page).getByLabel("Native backup storage", {
    exact: true,
  });
  await details.locator(":scope > summary").click();
  return details;
}

for (const caf of [false, true])
  test(`current storage policy from ${caf ? "CAF" : "new application"} entry retains original manifest and makes no field calls`, async ({
    page,
    request,
  }) => {
    const data = seed(),
      field: string[] = [];
    page.on("request", (request) => {
      if (
        /\/api\/bacnet\/(connect|controller\/native-application\/(capture|apply|preview|readback))$/.test(
          request.url(),
        )
      )
        field.push(request.url());
    });
    const details = await enter(page, data, caf);
    expect(JSON.parse((await details.locator("pre").textContent())!)).toEqual(
      data.storage,
    );
    await expect(details).toContainText("current computer’s storage policy");
    await expect(details).toContainText(
      "does not establish controller acceptance",
    );
    expect(data.storage.profile).toBe("native-application-storage/1");
    expect(data.storage).not.toHaveProperty("process_lock");
    await panel(page)
      .getByRole("button", {
        name: "Select backup " + data.capture.id.slice(0, 8),
        exact: true,
      })
      .click();
    const source = page.getByRole("region", {
      name: "Selected native backup",
      exact: true,
    });
    await source.locator("summary").click();
    const row = JSON.parse((await source.locator("pre").textContent())!);
    expect(row.evidence_sha256).toBe(data.capture.evidence_sha256);
    expect(row.files).toEqual(data.capture.files);
    expect(row).not.toHaveProperty("storage");
    expect(field).toEqual([]);
    expect(
      (await (await request.get("/api/session")).json()).field_network_open,
    ).toBe(false);
  });

test("authored Windows policy displays its actual directory durability limitation", async ({
  page,
}) => {
  const data = seed();
  const windows = {
    ...data.storage,
    platform: "nt",
    directory_flush: false,
    regular_file_guard: "Win32 handle attributes; final reparse points refused",
    durability:
      "File data flushed; namespace/power-loss durability unverified on Windows.",
  };
  await page.route("**" + endpoint, async (route) => {
    const response = await route.fetch(),
      result = await response.json();
    await route.fulfill({ response, json: { ...result, storage: windows } });
  });
  const details = await enter(page, data);
  await expect(details).toContainText(windows.durability);
  expect(JSON.parse((await details.locator("pre").textContent())!)).toEqual(
    windows,
  );
  await expect(details).not.toContainText("File and directory fsync");
  await expect(
    panel(page).getByRole("button", {
      name: "Select backup " + data.capture.id.slice(0, 8),
      exact: true,
    }),
  ).toBeVisible();
});

test("unknown storage metadata remains unavailable without replacing original source evidence", async ({
  page,
}) => {
  const data = seed();
  await page.route("**" + endpoint, async (route) => {
    const response = await route.fetch(),
      result = await response.json();
    await route.fulfill({
      response,
      json: {
        ...result,
        storage: { profile: "unrecognized", durability: "Incorrect certainty" },
      },
    });
  });
  const details = await enter(page, data);
  await expect(details).toContainText("Current storage policy is unavailable.");
  await expect(details).not.toContainText("Incorrect certainty");
  await expect(details.locator("pre")).toHaveCount(0);
  await expect(
    panel(page).getByRole("button", {
      name: "Select backup " + data.capture.id.slice(0, 8),
      exact: true,
    }),
  ).toBeVisible();
});
