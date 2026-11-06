import { test, expect } from "./nativeScheduleWriteFixture";
import { readFileSync } from "node:fs";
import {
  seed,
  openTerminalLedger,
  openTerminalEvidence,
} from "./native-encoded-analog-recovery-ledger-fixture";
import { python } from "./native-connection-fixture";
import { chooseWorkspaceTask } from "./workspace-navigation";

for (const history of [false, true])
  for (const width of [1440, 390])
    test(`${history ? "History" : "Changes"} displays recorded analog inverse lineage and local parent search at ${width}px`, async ({
      page,
      request,
      nativeScheduleWriteServer,
    }, info) => {
      const f = seed(nativeScheduleWriteServer.directory),
        field: string[] = [];
      await page.setViewportSize({ width, height: 1000 });
      page.on("request", (r) => {
        if (
          r.method() === "POST" &&
          new URL(r.url()).pathname.startsWith("/api/bacnet/")
        )
          field.push(r.url());
      });
      await openTerminalLedger(page, history);
      const evidence = await openTerminalEvidence(page, f.id),
        lineage = evidence.getByRole("region", {
          name: "Recorded analog recovery lineage",
          exact: true,
        });
      await expect(lineage).toContainText(f.parent);
      await expect(lineage).toContainText("UI IN3 to UI IN1");
      await expect(lineage).toContainText("No parent/source lookup");
      await expect(
        lineage.getByRole("button", {
          name: "Apply to controller",
          exact: true,
        }),
      ).toHaveCount(0);
      await expect(evidence).not.toContainText("Recovery metadata unavailable");
      const download = page.waitForEvent("download");
      await evidence
        .getByRole("button", { name: "Download evidence JSON", exact: true })
        .click();
      const bytes = readFileSync((await (await download).path())!);
      expect(bytes).toEqual(
        await (
          await request.get(
            "/api/bacnet/controller/native-application/receipts/" + f.id,
          )
        ).body(),
      );
      await lineage.scrollIntoViewIfNeeded();
      await page.screenshot({
        path: info.outputPath("encoded-analog-recovery-ledger.png"),
      });
      await lineage
        .getByRole("button", {
          name: "Search recorded analog recovery parent receipt",
          exact: true,
        })
        .click();
      await expect(
        page.getByRole("button", {
          name: "Details for native " + f.parent,
          exact: true,
        }),
      ).toBeVisible();
      expect(field).toEqual([]);
      expect(
        (await (await request.get("/api/session")).json()).field_network_open,
      ).toBe(false);
    });

test("unsupported recorded lineage retains original evidence without a parent link", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seed(nativeScheduleWriteServer.directory);
  await openTerminalLedger(page);
  const evidence = await openTerminalEvidence(page, f.invalid),
    lineage = evidence.getByRole("region", {
      name: "Recorded analog recovery lineage",
      exact: true,
    });
  await expect(lineage).toContainText("metadata unavailable");
  await expect(
    lineage.getByRole("button", {
      name: "Search recorded analog recovery parent receipt",
      exact: true,
    }),
  ).toHaveCount(0);
  await expect(
    evidence.getByRole("button", {
      name: "Download evidence JSON",
      exact: true,
    }),
  ).toBeEnabled();
});

for (const fault of [
  "authority",
  "seal",
  "missing-base",
  "legacy-fallback",
] as const)
  test(`substituted ${fault} metadata cannot grant analog parent search or input tools`, async ({
    page,
    nativeScheduleWriteServer,
  }) => {
    const f = seed(nativeScheduleWriteServer.directory);
    await page.route("**/api/changes/query", async (route) => {
      const response = await route.fetch(),
        v = await response.json();
      for (const r of v.rows ?? [])
        if (r.id === f.id) {
          if (fault === "seal")
            r.native_encoded_analog_recovery.origin_sha256 = "0".repeat(64);
          else if (fault === "missing-base")
            delete r.native_encoded_analog_terminal;
          else r.native_encoded_analog_recovery.transfer_authority = true;
          if (fault === "legacy-fallback" || fault === "missing-base") {
            r.native_input = f.legacy;
            r.native_terminal = f.oldTerminal;
            r.native_binary_terminal = f.binary;
            r.native_recovery = {
              state: "recorded",
              scope: "Injected generic recovery",
            };
          }
        }
      await route.fulfill({ response, json: v });
    });
    await openTerminalLedger(page);
    const evidence = await openTerminalEvidence(page, f.id);
    const lineage = evidence.getByRole("region", {
      name: "Recorded analog recovery lineage",
      exact: true,
    });
    await expect(lineage).toContainText("metadata unavailable");
    await expect(
      lineage.getByRole("button", {
        name: "Search recorded analog recovery parent receipt",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      evidence.getByRole("button", { name: "Open input tools", exact: true }),
    ).toHaveCount(0);
    for (const name of [
      "Recorded terminal movement",
      "Recorded binary terminal movement",
      "Recorded native recovery lineage",
      "Recorded native input configuration",
    ])
      await expect(
        evidence.getByRole("region", { name, exact: true }),
      ).toHaveCount(0);
    await expect(
      evidence.getByRole("button", {
        name: "Download evidence JSON",
        exact: true,
      }),
    ).toBeEnabled();
  });

test("CAF context remains separate while inspecting analog inverse lineage", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seed(nativeScheduleWriteServer.directory);
  await page.goto("/");
  await page
    .getByLabel("Open local CAF application", { exact: true })
    .setInputFiles({
      name: "recorded-analog-inverse.caf",
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
  ).toContainText("recorded-analog-inverse.caf");
  await chooseWorkspaceTask(page, "Changes");
  await page
    .getByLabel("Record family", { exact: true })
    .selectOption("native");
  const evidence = await openTerminalEvidence(page, f.id);
  await expect(
    evidence.getByRole("region", {
      name: "Recorded analog recovery lineage",
      exact: true,
    }),
  ).toContainText(f.parent);
  await expect(
    page.getByLabel("Working context", { exact: true }),
  ).toContainText("recorded-analog-inverse.caf");
  await evidence
    .getByRole("button", { name: "Open input tools", exact: true })
    .click();
  const inputs = page.getByRole("region", {
    name: "Native input configuration",
    exact: true,
  });
  await expect(inputs).toBeVisible();
  await expect(
    inputs.getByLabel("Retained native input source", { exact: true }),
  ).toHaveValue("");
  await expect(
    page.getByLabel("Working context", { exact: true }),
  ).toContainText("recorded-analog-inverse.caf");
});

test("recorded analog recovery lineage does not promote an unknown child outcome", async ({
  page,
  request,
  nativeScheduleWriteServer,
}) => {
  const f = seed(nativeScheduleWriteServer.directory),
    field: string[] = [];
  page.on("request", (r) => {
    if (
      r.method() === "POST" &&
      new URL(r.url()).pathname.startsWith("/api/bacnet/")
    )
      field.push(r.url());
  });
  await openTerminalLedger(page);
  const evidence = await openTerminalEvidence(page, f.uncertain);
  await expect(evidence).toContainText("unknown");
  await expect(
    evidence.getByRole("region", {
      name: "Recorded analog recovery lineage",
      exact: true,
    }),
  ).toContainText(f.parent);
  await expect(
    evidence.getByRole("button", { name: "Apply to controller", exact: true }),
  ).toHaveCount(0);
  expect(field).toEqual([]);
  expect(
    (await (await request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
});
