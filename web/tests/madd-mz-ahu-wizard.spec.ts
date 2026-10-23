import {
  test,
  expect,
  simulationServerResponseJSON,
  type Page,
  type Locator,
} from "./simulationFixture";
import {
  sourceFixtureData,
  projectedSourceFixture,
  resealSourceFixture,
} from "./sourceTransportFixtures";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
const root = fileURLToPath(new URL("../..", import.meta.url)),
  python = path.join(root, ".venv/bin/python"),
  base = "/api/madd-mz-ahu-wizard",
  title = "Portable dual-deck browser";
async function open(page: Page) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Equipment wizard", exact: true })
    .click();
  await page
    .getByRole("button", { name: "MADD-MZ AHU wizard", exact: true })
    .click();
  const dialog = page.getByRole("dialog", {
    name: "MADD-MZ AHU wizard",
    exact: true,
  });
  await expect(
    dialog.getByLabel("Dual-deck AHU project name", { exact: true }),
  ).toBeVisible();
  await dialog
    .getByLabel("Dual-deck AHU project name", { exact: true })
    .fill(title);
  return dialog;
}
async function configure(dialog: Locator, econ = "off") {
  await dialog
    .getByLabel("Dual-deck AHU economizer suitability", { exact: true })
    .selectOption(econ);
  for (const name of ["occupied", "unit enabled", "fan proven"])
    await dialog
      .getByLabel("Dual-deck AHU default " + name, { exact: true })
      .check();
  for (const [name, value] of [
    ["continuous proof interval", "1"],
    ["stabilization interval", "1"],
    ["startup deadline", "4"],
    ["proof-loss recovery deadline", "4"],
    ["low-command release interval", "1"],
  ])
    await dialog
      .getByLabel(`Dual-deck AHU ${name} (seconds)`, { exact: true })
      .fill(value);
  if (econ !== "off")
    await dialog
      .getByLabel(
        "Dual-deck AHU economizer high-command assist interval (seconds)",
        { exact: true },
      )
      .fill("1");
}
async function review(page: Page, dialog: Locator) {
  let original: Buffer | undefined;
  await page.route(
    "**" + base + "/preview",
    async (route) => {
      const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 });
      expect(response.status()).toBe(200);
      original = await response.body();
      await route.fulfill({ response, body: original });
    },
    { times: 1 },
  );
  await dialog
    .getByRole("button", { name: "Preview Dual-deck AHU project", exact: true })
    .click();
  await expect(
    dialog.getByRole("region", { name: "Dual-deck AHU preview", exact: true }),
  ).toBeVisible();
  expect(original).toBeDefined();
  await test
    .info()
    .attach("original-preview-source-response", {
      body: original!,
      contentType: "application/json",
    });
  return projectedSourceFixture(JSON.parse(original!.toString()));
}
async function create(page: Page, dialog: Locator) {
  page.once("dialog", (d) => d.accept());
  await dialog
    .getByRole("button", {
      name: "Create editable Dual-deck AHU project",
      exact: true,
    })
    .click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
    title,
  );
}
async function step(page: Page) {
  const receipt = page.waitForResponse(
    (r) => new URL(r.url()).pathname === "/api/simulation/step",
  );
  await page
    .getByRole("button", { name: "Step simulation", exact: true })
    .click();
  const response = await receipt;
  expect(response.status()).toBe(200);
  return simulationServerResponseJSON(response).history.at(-1).outputs;
}
async function downloading(page: Page, dialog: Locator) {
  const waiting = page.waitForEvent("download");
  await dialog
    .getByRole("button", {
      name: "Export original Dual-deck AHU review JSON",
      exact: true,
    })
    .click();
  const file = (await (await waiting).path())!;
  return { file, bytes: readFileSync(file) };
}
async function held(page: Page, endpoint: string) {
  let seen!: () => void, release!: () => void, done!: () => void;
  const incoming = new Promise<void>((r) => (seen = r)),
    gate = new Promise<void>((r) => (release = r)),
    finished = new Promise<void>((r) => (done = r));
  await page.route("**" + base + "/" + endpoint, async (route) => {
    const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 }),
      body = await response.body();
    seen();
    await gate;
    await route.fulfill({ response, body });
    done();
  });
  return { incoming, release, finished };
}

async function ready(page: Page) {
  let outputs = await step(page);
  for (let i = 0; i < 8 && !outputs.fan_ready; i++) outputs = await step(page);
  expect(outputs.fan_ready).toBe(true);
  return outputs;
}
const environment = () => ({
  ...process.env,
  PYTHONPATH: path.join(root, "backend"),
});

for (const econ of ["off", "fixed-drybulb", "differential-drybulb"])
  for (const unit of ["degF", "degC"])
    test(`authors independent concurrent decks with ${econ} in ${unit}, original export and local simulation`, async ({
      page,
    }) => {
      const dialog = await open(page);
      await configure(dialog, econ);
      await dialog
        .getByLabel("Dual-deck AHU declared controller family", { exact: true })
        .selectOption("johnson-fx");
      await dialog
        .getByLabel("Dual-deck AHU declared model", { exact: true })
        .fill("FX-PCG2611-0");
      if (unit === "degC") {
        await dialog
          .getByLabel("Dual-deck AHU temperature units", { exact: true })
          .selectOption(unit);
        await expect(dialog.getByRole("status")).toHaveCount(0);
      }
      const report = await review(page, dialog);
      expect(report.can_create).toBe(true);
      expect(report.native_compile).toBe(false);
      expect(report.controller_writes).toBe(false);
      expect(report.choices.configuration).toBe("ahu-only");
      expect(report.choices.fan).toBe("single-speed");
      expect(report.program.target.model).toBe("FX-PCG2611-0");
      expect(report.inputs).toHaveLength(
        econ === "off" ? 9 : econ === "fixed-drybulb" ? 11 : 12,
      );
      expect(report.outputs).toHaveLength(16);
      expect(
        report.inputs.some((r: any) => r.id === "outdoor_temperature"),
      ).toBe(econ !== "off");
      expect(
        report.inputs.some((r: any) => r.id === "return_temperature"),
      ).toBe(econ === "differential-drybulb");
      expect(
        report.inputs.some((r: any) => /zone|pressure|sat$/.test(r.id)),
      ).toBe(false);
      let raw: Buffer | undefined,
        header = "";
      await page.route("**" + base + "/export", async (route) => {
        const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 });
        raw = await response.body();
        header = response.headers()["x-file-sha256"];
        await route.fulfill({ response, body: raw });
      });
      const exported = await downloading(page, dialog);
      expect(exported.bytes).toEqual(raw);
      await test
        .info()
        .attach("original-export-response", {
          body: raw!,
          contentType: "application/json",
        });
      execFileSync(
        python,
        [
          "-c",
          "import json,hashlib,sys;from bms_tool.models import Program;b=open(sys.argv[1],'rb').read();r=json.loads(b);assert hashlib.sha256(b).hexdigest()==sys.argv[2];assert Program.model_validate(r['program']).digest()==r['program_sha256'];assert not r['native_compile'] and not r['controller_writes'];assert r['program']['metadata']['application']=='madd-mz-ahu-only'",
          exported.file,
          header,
        ],
        { cwd: root, env: environment() },
      );
      await create(page, dialog);
      let outputs = await ready(page);
      if (econ !== "off") {
        expect(outputs.cold_deck_state).toBe(1);
        expect(outputs.cold_economizer_active).toBe(true);
        expect(outputs.cold_cooling_valve).toBe(0);
        expect(outputs.hot_heating_valve).toBeGreaterThan(0);
      }
      for (let i = 0; i < 3; i++) outputs = await step(page);
      expect(outputs.fan_enable).toBe(true);
      expect(outputs.fan_fault).toBe(false);
      expect(outputs.setpoints_valid).toBe(true);
      expect(outputs.hot_heating_valve).toBeGreaterThan(0);
      expect(outputs.cold_cooling_valve).toBeGreaterThan(0);
      expect(outputs.hot_heating_active).toBe(true);
      expect(outputs.cold_mechanical_active).toBe(true);
      expect(outputs.mixing_damper).toBe(econ === "off" ? 10 : 100);
      if (econ !== "off") {
        expect(outputs.cold_deck_state).toBe(2);
        expect(outputs.economizer_available).toBe(true);
        // Integrated state fixes mixing at 100%; its economizer PI is inactive.
        expect(outputs.cold_economizer_active).toBe(false);
      }
      if (econ === "off") {
        await page
          .getByRole("button", { name: "Save revision", exact: true })
          .click();
        await expect(
          page.getByLabel("Last saved revision", { exact: true }),
        ).toContainText("r1");
        for (const format of ["json", "st", "plcopen", "graphml"]) {
          await page
            .getByLabel("Export format", { exact: true })
            .selectOption(format);
          const waiting = page.waitForEvent("download");
          await page
            .getByRole("button", { name: "Export", exact: true })
            .click();
          const file = await waiting;
          const digest = execFileSync(
            python,
            [
              "-c",
              "import sys;from bms_tool.formats import import_program;p=import_program(open(sys.argv[1],'rb').read(),sys.argv[2]);assert p.revision==1;assert not p.metadata['native_deployment_verified'];assert p.metadata['madd_mz_ahu_wizard']['choices']['configuration']=='ahu-only';p.revision=0;print(p.digest())",
              (await file.path())!,
              file.suggestedFilename(),
            ],
            { cwd: root, env: environment(), encoding: "utf8" },
          ).trim();
          expect(digest).toBe(report.program_sha256);
        }
        await page.reload();
        await expect(
          page.getByLabel("Program name", { exact: true }),
        ).toHaveValue(title);
        const restored = await page.request.get(
          "/api/projects/" + report.program.id,
        );
        const rawSource = await restored.body();
        await test
          .info()
          .attach("original-saved-project-response", {
            body: rawSource,
            contentType: "application/json",
          });
        const digest = execFileSync(
          python,
          [
            "-c",
            "import sys;from bms_tool.models import Program;p=Program.model_validate_json(sys.stdin.buffer.read());assert p.revision==1;p.revision=0;print(p.digest())",
          ],
          { cwd: root, input: rawSource, env: environment(), encoding: "utf8" },
        ).trim();
        expect(digest).toBe(report.program_sha256);
      }
      expect(
        (await (await page.request.get("/api/session")).json())
          .field_network_open,
      ).toBe(false);
    });

test("coupled F/C conversion preserves both deck targets, differences, inverse gains and branch defaults", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog, "differential-drybulb");
  await dialog
    .getByLabel("Dual-deck AHU hot-deck proportional gain (%/degree)", {
      exact: true,
    })
    .fill("18");
  await dialog
    .getByLabel("Dual-deck AHU cold-deck proportional gain (%/degree)", {
      exact: true,
    })
    .fill("9");
  await dialog
    .getByLabel("Dual-deck AHU temperature units", { exact: true })
    .selectOption("degC");
  await expect(dialog.getByRole("status")).toHaveCount(0);
  let report = await review(page, dialog);
  expect(report.choices.hot_deck_setpoint).toBeCloseTo(265 / 9, 10);
  expect(report.choices.cold_deck_setpoint).toBeCloseTo(115 / 9, 10);
  expect(report.choices.hot_entry_delta).toBeCloseTo(5 / 18, 10);
  expect(report.choices.hot_kp).toBeCloseTo(32.4, 10);
  expect(report.choices.cold_kp).toBeCloseTo(16.2, 10);
  expect(report.choices.economizer_control.differential_on).toBeCloseTo(
    5 / 3,
    10,
  );
  expect(report.choices.minimum_oa_percent).toBe(10);
  expect(report.choices.proof_seconds).toBe(1);
  await dialog
    .getByLabel("Dual-deck AHU temperature units", { exact: true })
    .selectOption("degF");
  await expect(dialog.getByRole("status")).toHaveCount(0);
  report = await review(page, dialog);
  expect(report.choices.hot_deck_setpoint).toBeCloseTo(85, 10);
  expect(report.choices.cold_deck_setpoint).toBeCloseTo(55, 10);
  expect(report.choices.hot_kp).toBeCloseTo(18, 10);
  expect(report.choices.cold_kp).toBeCloseTo(9, 10);
  await dialog
    .getByLabel("Dual-deck AHU economizer suitability", { exact: true })
    .selectOption("off");
  report = await review(page, dialog);
  expect(report.choices.economizer_control).toBeNull();
  await dialog
    .getByLabel("Dual-deck AHU temperature units", { exact: true })
    .selectOption("degC");
  await expect(dialog.getByRole("status")).toHaveCount(0);
  await dialog
    .getByLabel("Dual-deck AHU economizer suitability", { exact: true })
    .selectOption("fixed-drybulb");
  await expect(
    dialog.getByLabel("Dual-deck AHU default outdoor-air temperature", {
      exact: true,
    }),
  ).toHaveValue("10");
  report = await review(page, dialog);
  expect(report.choices.economizer_control.ra_default).toBeNull();
  expect(report.inputs.some((r: any) => r.id === "return_temperature")).toBe(
    false,
  );
});

test("independent deck targets accept reversed order, inhibit out-of-range good values, and preserve whole-scan rollback", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog);
  await review(page, dialog);
  await create(page, dialog);
  let out = await ready(page);
  expect(out.hot_heating_valve).toBeGreaterThan(0);
  expect(out.cold_cooling_valve).toBeGreaterThan(0);
  await page
    .getByLabel("Simulate hot_deck_setpoint", { exact: true })
    .fill("50");
  await page
    .getByLabel("Simulate cold_deck_setpoint", { exact: true })
    .fill("90");
  out = await step(page);
  expect(out.setpoints_valid).toBe(true);
  expect(out.fan_ready).toBe(true);
  expect(out.hot_target_above_cold).toBe(false);
  expect(out.nominal_deck_spread).toBe(-40);
  await page
    .getByLabel("Simulate hot_deck_setpoint", { exact: true })
    .fill("400");
  out = await step(page);
  expect(out.setpoints_valid).toBe(false);
  expect(out.fan_ready).toBe(false);
  expect(out.fan_fault).toBe(false);
  for (const id of ["hot_heating_valve", "cold_cooling_valve", "mixing_damper"])
    expect(out[id]).toBe(0);
  await page
    .getByLabel("Simulate hot_deck_setpoint", { exact: true })
    .fill("85");
  await page
    .getByLabel("Simulate cold_deck_setpoint", { exact: true })
    .fill("55");
  out = await ready(page);
  expect(out.hot_heating_valve).toBeGreaterThan(0);
  expect(out.cold_cooling_valve).toBeGreaterThan(0);
  const previous = out;
  await page
    .getByLabel("Quality hot_deck_temperature", { exact: true })
    .selectOption("open-circuit");
  await page.getByLabel("Simulate unit_enable", { exact: true }).uncheck();
  out = await step(page);
  expect(out).toEqual(previous);
  await page
    .getByLabel("Quality hot_deck_temperature", { exact: true })
    .selectOption("good");
  out = await step(page);
  expect(out.fan_enable).toBe(false);
  expect(out.hot_heating_valve).toBe(0);
  expect(out.cold_cooling_valve).toBe(0);
});

test("independent fan proof loss closes both decks, times out and needs a rising reset with operator request off", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog);
  await review(page, dialog);
  await create(page, dialog);
  await ready(page);
  await page.getByLabel("Simulate fan_proven", { exact: true }).uncheck();
  let out = await step(page);
  expect(out.fan_ready).toBe(false);
  for (const id of ["hot_heating_valve", "cold_cooling_valve", "mixing_damper"])
    expect(out[id]).toBe(0);
  for (let i = 0; i < 6 && !out.fan_fault; i++) out = await step(page);
  expect(out.fan_fault).toBe(true);
  expect(out.fan_enable).toBe(false);
  await page.getByLabel("Simulate fan_reset", { exact: true }).check();
  out = await step(page);
  expect(out.fan_fault).toBe(true);
  await page.getByLabel("Simulate unit_enable", { exact: true }).uncheck();
  out = await step(page);
  expect(out.fan_fault).toBe(true);
  await page.getByLabel("Simulate fan_reset", { exact: true }).uncheck();
  await step(page);
  await page.getByLabel("Simulate fan_reset", { exact: true }).check();
  out = await step(page);
  expect(out.fan_fault).toBe(false);
  expect(out.fan_enable).toBe(false);
});

test("explicit economizer, aligned timing and declined replacement preserve current editor", async ({
  page,
}) => {
  const dialog = await open(page),
    original = await page
      .getByLabel("Program name", { exact: true })
      .inputValue();
  await expect(
    dialog.getByRole("button", {
      name: "Preview Dual-deck AHU project",
      exact: true,
    }),
  ).toBeDisabled();
  await configure(dialog);
  await dialog
    .getByLabel("Dual-deck AHU continuous proof interval (seconds)", {
      exact: true,
    })
    .fill("1.5");
  await dialog
    .getByRole("button", { name: "Preview Dual-deck AHU project", exact: true })
    .click();
  await expect(dialog.getByRole("alert")).toBeVisible();
  await dialog
    .getByLabel("Dual-deck AHU continuous proof interval (seconds)", {
      exact: true,
    })
    .fill("1");
  await dialog
    .getByLabel("Dual-deck AHU scan interval (seconds)", { exact: true })
    .fill("2");
  await dialog
    .getByRole("button", { name: "Preview Dual-deck AHU project", exact: true })
    .click();
  await expect(dialog.getByRole("alert")).toBeVisible();
  await dialog
    .getByLabel("Dual-deck AHU scan interval (seconds)", { exact: true })
    .fill("1");
  await review(page, dialog);
  page.once("dialog", (d) => d.dismiss());
  await dialog
    .getByRole("button", {
      name: "Create editable Dual-deck AHU project",
      exact: true,
    })
    .click();
  await expect(dialog).toBeVisible();
  await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
    original,
  );
});

for (const kind of [
  "preview-source",
  "preview-discard",
  "export-source",
  "export-back",
  "units-close",
])
  test(`held ${kind} cannot authorize stale dual-deck work or downloads`, async ({
    page,
  }) => {
    const dialog = await open(page);
    await configure(dialog, "differential-drybulb");
    const endpoint = kind.split("-")[0];
    if (endpoint === "export") await review(page, dialog);
    const gate = await held(page, endpoint);
    let downloads = 0;
    page.on("download", () => downloads++);
    try {
      if (endpoint === "units")
        await dialog
          .getByLabel("Dual-deck AHU temperature units", { exact: true })
          .selectOption("degC");
      else
        await dialog
          .getByRole("button", {
            name:
              endpoint === "preview"
                ? "Preview Dual-deck AHU project"
                : "Export original Dual-deck AHU review JSON",
            exact: true,
          })
          .click();
      await gate.incoming;
      if (kind.endsWith("source"))
        await page
          .getByLabel("Program name", { exact: true })
          .fill("Different editor source");
      else
        await dialog
          .getByRole("button", {
            name: kind.endsWith("discard")
              ? "Discard pending Dual-deck AHU response"
              : kind.endsWith("back")
                ? "Back to equipment wizard"
                : "Cancel Dual-deck AHU wizard",
            exact: true,
          })
          .click();
      gate.release();
      await gate.finished;
      expect(downloads).toBe(0);
      await expect(
        page.getByRole("button", {
          name: "Create editable Dual-deck AHU project",
          exact: true,
        }),
      ).toHaveCount(0);
      if (kind.endsWith("source"))
        await expect(dialog.getByRole("alert")).toContainText(
          "Current editor changed",
        );
      if (kind.endsWith("discard"))
        await expect(dialog.getByRole("alert")).toContainText("ignored");
    } finally {
      gate.release();
    }
  });

for (const malformed of [
  "profile",
  "choices",
  "manifest",
  "native-claim",
  "deck-unit",
])
  test(`malformed ${malformed} preview cannot authorize independent-deck creation`, async ({
    page,
  }) => {
    const dialog = await open(page);
    await configure(dialog, "differential-drybulb");
    await page.route("**" + base + "/preview", async (route) => {
      const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 }),
        envelope = await response.json(),
        value = sourceFixtureData(envelope);
      if (malformed === "profile") value.profile_sha256 = "0".repeat(64);
      else if (malformed === "choices") value.choices.hot_deck_setpoint = 99;
      else if (malformed === "manifest")
        value.inputs.find((r: any) => r.id === "hot_deck_temperature").id =
          "zone_temperature";
      else if (malformed === "deck-unit")
        value.outputs.find((r: any) => r.id === "nominal_deck_spread").unit =
          "degF";
      else value.program.metadata.native_deployment_verified = true;
      await route.fulfill({
        response,
        json: resealSourceFixture(envelope, value),
      });
    });
    await dialog
      .getByRole("button", {
        name: "Preview Dual-deck AHU project",
        exact: true,
      })
      .click();
    await expect(dialog.getByRole("alert")).toBeVisible();
    await expect(
      dialog.getByRole("button", {
        name: "Create editable Dual-deck AHU project",
        exact: true,
      }),
    ).toHaveCount(0);
  });

test("conversion cannot silently change an independent deck or nonthermal setting", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog, "differential-drybulb");
  await page.route("**" + base + "/units", async (route) => {
    const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 }),
      value = await response.json();
    value.choices.cold_kp += 1;
    value.choices.proof_seconds += 1;
    await route.fulfill({ response, json: value });
  });
  await dialog
    .getByLabel("Dual-deck AHU temperature units", { exact: true })
    .selectOption("degC");
  await expect(dialog.getByRole("alert")).toContainText("conversion changed");
  await expect(
    dialog.getByLabel("Dual-deck AHU temperature units", { exact: true }),
  ).toHaveValue("degF");
});

test("wrong original-export byte digest prevents a download", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog);
  await review(page, dialog);
  await page.route("**" + base + "/export", async (route) => {
    const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 });
    await route.fulfill({
      response,
      body: await response.body(),
      headers: { ...response.headers(), "x-file-sha256": "0".repeat(64) },
    });
  });
  let downloads = 0;
  page.on("download", () => downloads++);
  await dialog
    .getByRole("button", {
      name: "Export original Dual-deck AHU review JSON",
      exact: true,
    })
    .click();
  await expect(dialog.getByRole("alert")).toContainText("changed after");
  expect(downloads).toBe(0);
});

test("unsupported same-ID catalog cannot initialize dual-deck choices", async ({
  page,
}) => {
  await page.route("**" + base + "/catalog", async (route) => {
    const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 }),
      value = await response.json();
    value.profile_sha256 = "0".repeat(64);
    await route.fulfill({ response, json: value });
  });
  await page.goto("/");
  await page
    .getByRole("button", { name: "Equipment wizard", exact: true })
    .click();
  await page
    .getByRole("button", { name: "MADD-MZ AHU wizard", exact: true })
    .click();
  const dialog = page.getByRole("dialog", {
    name: "MADD-MZ AHU wizard",
    exact: true,
  });
  await expect(dialog.getByRole("alert")).toContainText("unsupported");
  await expect(
    dialog.getByLabel("Dual-deck AHU project name", { exact: true }),
  ).toHaveCount(0);
  await expect(
    dialog.getByRole("button", {
      name: "Preview Dual-deck AHU project",
      exact: true,
    }),
  ).toBeDisabled();
});

test("scientific deck gain and default retain original Program tokens through review/export/create", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog);
  await dialog
    .getByLabel("Dual-deck AHU hot-deck proportional gain (%/degree)", {
      exact: true,
    })
    .fill("0.000001");
  await dialog
    .getByLabel("Dual-deck AHU default cold-deck temperature", { exact: true })
    .fill("0.000001");
  const value = await review(page, dialog);
  expect(value.choices.hot_kp).toBe(0.000001);
  expect(value.choices.cold_deck_default).toBe(0.000001);
  const exported = await downloading(page, dialog);
  expect(exported.bytes.toString()).toContain("1e-06");
  execFileSync(
    python,
    [
      "-c",
      "import json,sys;from bms_tool.models import Program;r=json.load(open(sys.argv[1]));p=Program.model_validate(r['program']);assert p.digest()==r['program_sha256'];assert p.metadata['madd_mz_ahu_wizard']['choices']['hot_kp']==1e-6;assert next(n for n in p.nodes if n.id=='cold_deck_temperature').params['default']==1e-6",
      exported.file,
    ],
    { cwd: root, env: environment() },
  );
  await create(page, dialog);
  await page
    .getByRole("button", { name: "Save revision", exact: true })
    .click();
  await expect(
    page.getByLabel("Last saved revision", { exact: true }),
  ).toContainText("r1");
  await page.reload();
  await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
    title,
  );
});
