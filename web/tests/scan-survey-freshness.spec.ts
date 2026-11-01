import {
  test,
  expect,
  type Page,
  type APIRequestContext,
} from "@playwright/test";
import { scanSurveyPeer, type PeerState } from "./scan-survey-peer";

async function reset(request: APIRequestContext) {
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  expect(
    (await request.post("/api/bacnet/disconnect", { headers, data: {} })).ok(),
  ).toBeTruthy();
  return headers;
}
async function connect(page: Page, clientPort: number) {
  await page.goto("/");
  await page.getByRole("button", { name: /^Connect to a controller/ }).click();
  await page
    .getByLabel("Local bind address / UDP port", { exact: true })
    .fill(`127.0.0.1:${clientPort}`);
  await page
    .getByRole("button", { name: "Open interface", exact: true })
    .click();
  await page
    .getByRole("navigation", { name: "Discovery method" })
    .getByRole("button", { name: "Direct BACnet/IP", exact: true })
    .click();
  return page.getByRole("region", { name: "BACnet device scan", exact: true });
}
function assertReadsOnly(state: PeerState) {
  expect(state.errors).toEqual([]);
  expect(
    state.requests.some((row) => row.service === "WhoIsRequest"),
  ).toBeTruthy();
  expect(
    state.requests.some((row) => row.service.startsWith("ReadProperty")),
  ).toBeTruthy();
  expect(
    state.requests.filter(
      (row) =>
        ![
          "WhoIsRequest",
          "IAmRequest",
          "ReadPropertyRequest",
          "ReadPropertyMultipleRequest",
        ].includes(row.service),
    ),
  ).toEqual([]);
}

test("fresh IP scan opens its actual random controller and a later hardware survey sees the changed peer input", async ({
  page,
  request,
}, info) => {
  test.setTimeout(60000);
  const headers = await reset(request),
    peer = await scanSurveyPeer(),
    target = peer.identity;
  let primary: unknown;
  try {
    const scan = await connect(page, target.client_port);
    await scan
      .getByLabel("IP scan mode", { exact: true })
      .selectOption("single");
    await scan.getByLabel("Scan IP address", { exact: true }).fill("127.0.0.1");
    await scan
      .getByLabel("Scan UDP port", { exact: true })
      .fill(String(target.port));
    await scan
      .getByLabel("Discovery response seconds", { exact: true })
      .fill("1");
    await scan
      .getByRole("button", { name: "Scan BACnet/IP devices", exact: true })
      .click();
    const row = scan.getByRole("row").filter({ hasText: target.name });
    await expect(row).toContainText(String(target.instance));
    await row.getByRole("button", { name: /^Open controller / }).click();
    await expect(page.getByLabel("Working context")).toContainText(target.name);
    await page
      .getByRole("navigation", { name: "Workspace tasks" })
      .getByRole("button", { name: "Points & I/O", exact: true })
      .click();
    await page
      .getByRole("navigation", { name: "Controller task tools" })
      .getByRole("button", { name: "Hardware survey", exact: true })
      .click();
    const hardware = page.getByRole("region", {
      name: "Controller hardware and input survey",
      exact: true,
    });
    await expect(page.getByLabel("Selected controller path")).toContainText(
      `127.0.0.1:${target.port}`,
    );
    await expect(page.getByLabel("Selected controller path")).toContainText(
      `device,${target.instance}`,
    );
    await expect(
      hardware.getByLabel("Hardware controller address", { exact: true }),
    ).toHaveCount(0);
    const survey = hardware.getByRole("button", {
      name: "Survey controller inputs",
      exact: true,
    });
    await survey.click();
    const report = hardware.getByRole("region", {
      name: "Hardware survey results",
      exact: true,
    });
    await expect(
      report.getByRole("heading", { name: target.name, exact: true }),
    ).toBeVisible({ timeout: 15000 });
    const input = report.getByRole("row").filter({ hasText: target.sensor });
    await expect(input).toContainText(String(target.first));
    await expect(report.getByLabel("Hardware report provenance")).toContainText(
      "Values do not update live",
    );
    const changed = await peer.control({ value: target.second });
    expect(changed.value).toBe(target.second);
    await expect(input).toContainText(String(target.first));
    await survey.click();
    await expect(input).toContainText(String(target.second), {
      timeout: 15000,
    });
    await expect(input).not.toContainText(String(target.first));
    const after = await peer.control();
    expect(after.requests.length).toBeGreaterThan(changed.requests.length);
    assertReadsOnly(after);
    await info.attach("actual-read-only-peer-observations", {
      body: JSON.stringify({ identity: target, before: changed, after }),
      contentType: "application/json",
    });
    await page.screenshot({
      path: info.outputPath("fresh-scan-survey.png"),
      fullPage: true,
    });
  } catch (error) {
    primary = error;
  }
  const cleanup: unknown[] = [];
  try {
    const response = await request.post("/api/bacnet/disconnect", {
      headers,
      data: {},
    });
    expect(response.ok()).toBeTruthy();
  } catch (error) {
    cleanup.push(error);
  }
  try {
    assertReadsOnly(await peer.close());
  } catch (error) {
    cleanup.push(error);
  }
  if (primary && cleanup.length)
    throw new AggregateError(
      [primary, ...cleanup],
      "Scan/survey assertion and owned cleanup failed",
    );
  if (primary) throw primary;
  if (cleanup.length)
    throw new AggregateError(cleanup, "Scan/survey cleanup failed");
});

test("reopening the same IP interface leaves retained scan names paused until an explicit details resume", async ({
  page,
  request,
}, info) => {
  test.setTimeout(60000);
  const headers = await reset(request),
    peer = await scanSurveyPeer(),
    target = peer.identity;
  let primary: unknown;
  try {
    const scan = await connect(page, target.client_port);
    await peer.control({ operation: "hold-name" });
    await scan
      .getByLabel("IP scan mode", { exact: true })
      .selectOption("single");
    await scan.getByLabel("Scan IP address", { exact: true }).fill("127.0.0.1");
    await scan
      .getByLabel("Scan UDP port", { exact: true })
      .fill(String(target.port));
    await scan
      .getByLabel("Discovery response seconds", { exact: true })
      .fill("1");
    await scan
      .getByRole("button", { name: "Scan BACnet/IP devices", exact: true })
      .click();
    await expect
      .poll(async () => (await peer.control()).name_entered)
      .toBeTruthy();
    await page
      .getByRole("button", { name: "Close BACnet interface", exact: true })
      .click();
    await expect(
      page.getByText("No BACnet interface open", { exact: true }),
    ).toBeVisible();
    const closed = await peer.control({ operation: "release-name" });
    await expect(scan).not.toContainText(target.name);
    await page
      .getByRole("button", { name: "1 · Connection", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Open interface", exact: true })
      .click();
    await page
      .getByRole("navigation", { name: "Discovery method" })
      .getByRole("button", { name: "Direct BACnet/IP", exact: true })
      .click();
    const resume = scan.getByRole("button", {
      name: "Resume shown-page details",
      exact: true,
    });
    await expect(resume).toBeEnabled();
    await expect(scan).not.toContainText(target.name);
    const reopened = await peer.control();
    const names = (state: PeerState) =>
      state.requests.filter(
        (row) =>
          row.object === `device,${target.instance}` &&
          row.property === "object-name",
      ).length;
    expect(names(reopened)).toBe(names(closed));
    await resume.click();
    await expect(
      scan.getByRole("row").filter({ hasText: target.name }),
    ).toContainText(String(target.instance), { timeout: 15000 });
    const resumed = await peer.control();
    expect(names(resumed)).toBeGreaterThan(names(reopened));
    expect(
      resumed.requests.filter((row) => row.service === "WhoIsRequest"),
    ).toHaveLength(1);
    assertReadsOnly(resumed);
    await info.attach("actual-interface-reopen-observations", {
      body: JSON.stringify({ identity: target, closed, reopened, resumed }),
      contentType: "application/json",
    });
  } catch (error) {
    primary = error;
  }
  const cleanup: unknown[] = [];
  try {
    const response = await request.post("/api/bacnet/disconnect", {
      headers,
      data: {},
    });
    expect(response.ok()).toBeTruthy();
  } catch (error) {
    cleanup.push(error);
  }
  try {
    assertReadsOnly(await peer.close());
  } catch (error) {
    cleanup.push(error);
  }
  if (primary && cleanup.length)
    throw new AggregateError(
      [primary, ...cleanup],
      "Reopen assertion and owned cleanup failed",
    );
  if (primary) throw primary;
  if (cleanup.length)
    throw new AggregateError(cleanup, "Reopen cleanup failed");
});
