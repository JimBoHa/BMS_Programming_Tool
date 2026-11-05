import { test, expect } from "./nativeScheduleWriteFixture";
import { readFileSync } from "node:fs";
import {
  seed,
  openTerminal,
  terminalTable,
} from "./native-terminal-capability-fixture";
import { chooseWorkspaceTask } from "./workspace-navigation";
import { python } from "./native-connection-fixture";

for (const width of [1440, 390])
  test(`${width}px terminal support reports exact source evidence without a field request`, async ({
    page,
    request,
    nativeScheduleWriteServer,
  }, info) => {
    const f = seed(nativeScheduleWriteServer.directory),
      calls: string[] = [];
    await page.setViewportSize({ width, height: 1000 });
    let exact = Buffer.alloc(0),
      body: any;
    page.on("request", (r) => {
      if (r.method() === "POST" && /\/api\/bacnet\//.test(r.url()))
        calls.push(new URL(r.url()).pathname);
    });
    await page.route("**/inspection/capabilities", async (route) => {
      const query = route.request().postDataJSON();
      const response = await route.fetch({ maxRetries: 0 });
      if (query.capability_profile.endsWith("/16")) {
        body = query;
        exact = await response.body();
      }
      await route.fulfill({ response });
    });
    const { terminal } = await openTerminal(page, f.analog.id),
      table = await terminalTable(terminal);
    expect(body.capability_profile).toBe(
      "native-backup-operation-capabilities/16",
    );
    await expect(
      table
        .locator('[data-operation="encoded-local-terminal-copy"]')
        .locator("td")
        .first(),
    ).toHaveText("source qualified");
    await expect(
      table
        .locator('[data-operation="analog-terminal-transfer"]')
        .locator("td")
        .first(),
    ).toHaveText("preflight required");
    await expect(terminal).toContainText("does not confirm physical wiring");
    expect(
      await terminal
        .getByRole("button", { name: "Apply to controller", exact: true })
        .count(),
    ).toBe(0);
    const download = page.waitForEvent("download");
    await terminal
      .getByRole("button", {
        name: "Save exact terminal analysis",
        exact: true,
      })
      .click();
    expect(readFileSync((await (await download).path())!)).toEqual(exact);
    expect(
      (await (await request.get("/api/session")).json()).field_network_open,
    ).toBe(false);
    expect(
      calls.every(
        (p) =>
          p.includes("/inspection/") || p.endsWith("/signal-default/source"),
      ),
    ).toBe(true);
    await terminal.scrollIntoViewIfNeeded();
    await page.screenshot({
      path: info.outputPath("terminal-capabilities.png"),
    });
  });
for (const [kind, expected] of [
  ["binary", ["source qualified", "source qualified", "unsupported source"]],
  ["unknown", ["source qualified", "unsupported source", "unsupported source"]],
  ["unverified", ["source qualified", "unsupported source", "source mismatch"]],
  [
    "output",
    ["source qualified", "source qualified", "preflight required"],
  ],
  ["serial", ["source qualified", "source qualified", "transport unavailable"]],
] as const)
  test(`${kind} source keeps terminal copy and field preflight support separate`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const f = seed(nativeScheduleWriteServer.directory),
      { terminal } = await openTerminal(page, f[kind].id),
      table = await terminalTable(terminal);
    expect(
      await table.locator("tbody td:first-of-type").allTextContents(),
    ).toEqual(expected);
  });
test("malformed terminal evidence withholds only its own table and exact download until explicit reanalysis", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seed(nativeScheduleWriteServer.directory);
  await page.route("**/inspection/capabilities", async (route) => {
    const response = await route.fetch();
    if (route.request().postDataJSON().capability_profile.endsWith("/16")) {
      const v = await response.json();
      v.qualification.archive_terminal.physical_terminal_or_wiring_verified = true;
      await route.fulfill({ response, json: v });
    } else await route.fulfill({ response });
  });
  const { terminal, support } = await openTerminal(page, f.analog.id);
  await expect(terminal.getByRole("alert")).toContainText(
    "differs from this retained source",
  );
  await expect(terminal.getByRole("table")).toHaveCount(0);
  await expect(
    terminal.getByRole("button", {
      name: "Save exact terminal analysis",
      exact: true,
    }),
  ).toHaveCount(0);
  await expect(
    support
      .getByRole("table", { name: "Native backup operations", exact: true })
      .getByRole("row"),
  ).toHaveCount(28);
  await page.unroute("**/inspection/capabilities");
  await terminal
    .getByRole("button", {
      name: "Analyze terminal support again",
      exact: true,
    })
    .click();
  await terminalTable(terminal);
});
test("late terminal analysis cannot return after leaving the application task", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seed(nativeScheduleWriteServer.directory);
  let release!: () => void, arrived!: () => void;
  const gate = new Promise<void>((r) => (release = r)),
    seen = new Promise<void>((r) => (arrived = r));
  await page.route("**/inspection/capabilities", async (route) => {
    const response = await route.fetch();
    if (route.request().postDataJSON().capability_profile.endsWith("/16")) {
      arrived();
      await gate;
    }
    await route.fulfill({ response });
  });
  await openTerminal(page, f.analog.id);
  await seen;
  await chooseWorkspaceTask(page, "Overview");
  release();
  await chooseWorkspaceTask(page, "Program");
  await expect(
    page.getByRole("button", {
      name: "Save exact terminal analysis",
      exact: true,
    }),
  ).toHaveCount(0);
});
test("CAF context stays open during retained terminal analysis", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seed(nativeScheduleWriteServer.directory);
  await page.goto("/");
  await page
    .getByLabel("Open local CAF application", { exact: true })
    .setInputFiles({
      name: "terminal-context.caf",
      mimeType: "application/octet-stream",
      buffer: Buffer.from(
        python(
          "from tests.test_caf_graph import make_graph;import base64;print(base64.b64encode(make_graph()).decode())",
        ),
        "base64",
      ),
    });
  await expect(
    page.getByLabel("Working context", { exact: true }),
  ).toContainText("terminal-context.caf");
  const { openNativeCompiler } = await import("./workspace-navigation");
  const { inspect, analyze } = await import(
    "./native-connection-capability-fixture"
  );
  await openNativeCompiler(page);
  const compiler = page.getByRole("region", {
    name: "Native backup default compiler",
    exact: true,
  });
  await compiler
    .getByLabel("Retained native backup", { exact: true })
    .selectOption(f.analog.id);
  const support = await inspect(compiler);
  await analyze(support);
  const terminal = support.getByLabel("Native terminal operation support", {
    exact: true,
  });
  await terminal.locator(":scope > summary").click();
  await terminalTable(terminal);
  await expect(
    page.getByLabel("Working context", { exact: true }),
  ).toContainText("terminal-context.caf");
});
