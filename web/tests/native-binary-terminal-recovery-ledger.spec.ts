import { test, expect } from "./nativeScheduleWriteFixture";
import { readFileSync } from "node:fs";
import {
  seed,
  openTerminalLedger,
  openTerminalEvidence,
} from "./native-binary-terminal-recovery-ledger-fixture";
import { python } from "./native-connection-fixture";
import { chooseWorkspaceTask } from "./workspace-navigation";

for (const history of [false, true])
  for (const width of [1440, 390])
    test(`${history ? "History" : "Changes"} displays recorded binary inverse lineage and local parent search at ${width}px`, async ({
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
          name: "Recorded binary recovery lineage",
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
        path: info.outputPath("binary-recovery-ledger.png"),
      });
      await lineage
        .getByRole("button", {
          name: "Search recorded binary recovery parent receipt",
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
      name: "Recorded binary recovery lineage",
      exact: true,
    });
  await expect(lineage).toContainText("metadata unavailable");
  await expect(
    lineage.getByRole("button", {
      name: "Search recorded binary recovery parent receipt",
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
  "mixed-analog",
  "point-name-fallback",
  "connection-fallback",
  "generic-kind-fallback",
] as const)
  test(`substituted ${fault} metadata cannot grant binary parent search or input tools`, async ({
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
            r.native_binary_terminal_recovery.origin_sha256 = "0".repeat(64);
          else if (fault === "missing-base") delete r.native_binary_terminal;
          else if (fault === "authority" || fault === "legacy-fallback")
            r.native_binary_terminal_recovery.transfer_authority = true;
          if (fault === "mixed-analog") {
            r.native_encoded_analog_terminal = f.analog;
            r.native_encoded_analog_recovery = {
              state: "recorded",
              profile: "other",
            };
          }
          if (fault === "point-name-fallback") {
            r.native_change_kind = "point-name";
            r.native_point_name = f.point;
            r.native_point_name_recovery = f.pointRecovery;
          }
          if (fault === "connection-fallback") {
            r.native_change_kind = "connection";
            r.native_connection = f.connection;
          }
          if (fault === "generic-kind-fallback") {
            r.native_change_kind = "signal-default";
            r.native_recovery = {
              state: "recorded",
              parent_receipt_id: f.parent,
              verified_proof: { kind: "result", time: "2026-11-05T00:00:00Z" },
              scope: "Injected generic recovery",
            };
          }
          if (fault === "legacy-fallback" || fault === "missing-base") {
            r.native_input = f.legacy;
            r.native_terminal = f.oldTerminal;
            r.native_encoded_analog_terminal = f.analog;
            r.native_recovery = {
              state: "recorded",
              scope: "Injected generic recovery",
            };
          }
        }
      await route.fulfill({ response, json: v });
    });
    await openTerminalLedger(page);
    const row = page
      .getByRole("row")
      .filter({
        has: page.getByRole("button", {
          name: "Details for native " + f.id,
          exact: true,
        }),
      });
    for (const text of [
      "Recorded name:",
      "Previous point-name recovery",
      "Matching connection",
      "Previous-value recovery",
    ])
      await expect(row).not.toContainText(text);
    const evidence = await openTerminalEvidence(page, f.id);
    const lineage = evidence.getByRole("region", {
      name: "Recorded binary recovery lineage",
      exact: true,
    });
    await expect(lineage).toContainText("metadata unavailable");
    await expect(
      lineage.getByRole("button", {
        name: "Search recorded binary recovery parent receipt",
        exact: true,
      }),
    ).toHaveCount(0);
    for (const name of [
      "Open input tools",
      "Open point tools",
      "Open native program tools",
      "Open identity tools",
      "Search recorded point-name parent receipt",
      "Search recorded parent receipt",
    ])
      await expect(
        evidence.getByRole("button", { name, exact: true }),
      ).toHaveCount(0);
    for (const name of [
      "Recorded terminal movement",
      "Recorded native recovery lineage",
      "Recorded native input configuration",
      "Recorded native point name",
      "Recorded point name recovery lineage",
      "Recorded native matching connection",
      "Recorded analog terminal movement",
      "Recorded analog recovery lineage",
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

test("CAF context remains separate while inspecting binary inverse lineage", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seed(nativeScheduleWriteServer.directory);
  await page.goto("/");
  await page
    .getByLabel("Open local CAF application", { exact: true })
    .setInputFiles({
      name: "recorded-binary-inverse.caf",
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
  ).toContainText("recorded-binary-inverse.caf");
  await chooseWorkspaceTask(page, "Changes");
  await page
    .getByLabel("Record family", { exact: true })
    .selectOption("native");
  const evidence = await openTerminalEvidence(page, f.id);
  await expect(
    evidence.getByRole("region", {
      name: "Recorded binary recovery lineage",
      exact: true,
    }),
  ).toContainText(f.parent);
  await expect(
    page.getByLabel("Working context", { exact: true }),
  ).toContainText("recorded-binary-inverse.caf");
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
  ).toContainText("recorded-binary-inverse.caf");
});

test("recorded binary recovery lineage does not promote an unknown child outcome", async ({
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
      name: "Recorded binary recovery lineage",
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

test("graph context remains separate while opening fresh binary recovery input tools", async ({
  page,
  request,
  nativeScheduleWriteServer,
}) => {
  const f = seed(nativeScheduleWriteServer.directory);
  await openTerminalLedger(page);
  const working = page.getByLabel("Working context", { exact: true });
  const before = await working.textContent();
  const evidence = await openTerminalEvidence(page, f.id);
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
  await expect(working).toHaveText(before!);
  expect(
    (await (await request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
});
