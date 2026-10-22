import { fetchSimulationResponse } from "./simulationFixture";
import { test, expect, type Page } from "./simulationFixture";
import { execFileSync } from "node:child_process";
import path from "node:path";
const root = path.resolve(".."),
  python = path.join(root, ".venv/bin/python");
async function load(page: Page, defaults = "{'a':1.0,'b':0}") {
  const buffer = execFileSync(
    python,
    [
      "-c",
      `from tests.test_temco import graph;p=graph('Add',values=${defaults});[(setattr(n,'x',i*280),setattr(n,'y',100)) for i,n in enumerate(p.nodes)];print(p.model_dump_json())`,
    ],
    { cwd: root },
  );
  await page.goto("/");
  await page.locator('input[type=file][accept*=".st"]').setInputFiles({
    name: "live-values.bms.json",
    mimeType: "application/json",
    buffer,
  });
  await expect(page.locator(".toast")).toContainText(
    "Imported as a new local project",
  );
}
function check(raw: string, selector: string, token: string) {
  execFileSync(
    python,
    [
      "-c",
      `import json,sys,math
v=json.loads(sys.stdin.read())
for key in json.loads(sys.argv[1]): v=v[key]
e=json.loads(sys.argv[2])
assert type(v) is type(e),(type(v),type(e),v,e)
assert v==e,(v,e)
if type(e) is float and e==0: assert math.copysign(1,v)==math.copysign(1,e)
`,
      selector,
      token,
    ],
    { cwd: root, input: raw },
  );
}
async function step(page: Page) {
  const response = page.waitForResponse(
    (r) =>
      r.url().endsWith("/api/simulation/step") &&
      r.request().method() === "POST",
  );
  await page.getByTitle("Step simulation", { exact: true }).click();
  const result = await response;
  expect(result.ok()).toBe(true);
  return result.request().postData()!;
}
test("portable inputs and held force preserve live numeric lexical types through Python HTTP", async ({
  page,
}) => {
  await load(page);
  for (const token of ["1e30", "1.0", "-0.0", "-0", "1152921504606846976"]) {
    await page.getByLabel("Simulate a", { exact: true }).fill(token);
    check(await step(page), '["inputs","a"]', token);
  }
  await page.locator('.react-flow__node[data-id="a"]').click();
  await page.getByLabel("Simulation force value").fill("1e30");
  await page
    .getByRole("button", { name: "Hold simulation value", exact: true })
    .click();
  check(await step(page), '["forces","a"]', "1e30");
  await page.getByTitle("Reset simulation", { exact: true }).click();
});
test("scenario events preserve types and returned force tokens remain exact on the next scan", async ({
  page,
}) => {
  await load(page);
  await page.getByRole("button", { name: "Scenarios", exact: true }).click();
  await page
    .getByLabel("Timed simulation events", { exact: true })
    .fill(
      '[{"time":0,"inputs":{"a":{"value":1.0,"quality":"good"}},"forces":{"b":1e30}}]',
    );
  await page.getByLabel("Scenario duration seconds", { exact: true }).fill("1");
  const pending = page.waitForResponse((r) =>
    r.url().endsWith("/api/simulation/scenario"),
  );
  await page.getByRole("button", { name: "Run scenario", exact: true }).click();
  const response = await pending;
  expect(response.ok()).toBe(true);
  check(
    response.request().postData()!,
    '["events",0,"inputs","a","value"]',
    "1.0",
  );
  check(response.request().postData()!, '["events",0,"forces","b"]', "1e30");
  await expect(page.locator(".elapsed")).toHaveText("1.0 s");
  check(await step(page), '["forces","b"]', "1e30");
  await page.getByTitle("Reset simulation", { exact: true }).click();
});
test("IEC defaults, edits and timed stimuli preserve float intent before genuine native verification", async ({
  page,
}) => {
  await load(page, "{'a':1e30,'b':0}");
  await page.getByRole("button", { name: "IEC native", exact: true }).click();
  await expect(
    page.getByText("MatIEC compiler available", { exact: true }),
  ).toBeVisible();
  const pending = page.waitForResponse((r) =>
    r.url().endsWith("/api/iec/verify"),
  );
  await page
    .getByRole("button", { name: "Run IEC verification", exact: true })
    .click();
  const response = await pending;
  expect(response.ok()).toBe(true);
  check(response.request().postData()!, '["inputs","a","value"]', "1e30");
  await page
    .getByLabel("IEC scenario events", { exact: true })
    .fill('[{"time":0,"inputs":{"a":1.0,"b":-0.0}}]');
  await page.getByLabel("IEC scenario duration", { exact: true }).fill("1");
  const scenario = page.waitForResponse((r) =>
    r.url().endsWith("/api/iec/scenario"),
  );
  await page
    .getByRole("button", { name: "Run native scenario", exact: true })
    .click();
  const event = await scenario;
  expect(event.ok()).toBe(true);
  check(event.request().postData()!, '["events",0,"inputs","a"]', "1.0");
  check(event.request().postData()!, '["events",0,"inputs","b"]', "-0.0");
});
test("Temco and Sedona scan editors use exact live token transport", async ({
  page,
}) => {
  await load(page);
  await page.getByRole("button", { name: "Temco native", exact: true }).click();
  await expect(
    page.getByText("Native compiler available", { exact: true }),
  ).toBeVisible();
  await page.getByLabel("Native value a", { exact: true }).fill("1.0");
  const temco = page.waitForResponse((r) =>
    r.url().endsWith("/api/temco/verify"),
  );
  await page
    .getByRole("button", { name: "Run native verification", exact: true })
    .click();
  const t = await temco;
  expect(t.ok()).toBe(true);
  check(t.request().postData()!, '["inputs","a","value"]', "1.0");
  await page.getByRole("button", { name: "Native sim", exact: true }).click();
  await page
    .getByRole("button", { name: "Compile and start", exact: true })
    .click();
  await expect(
    page.getByLabel("Native input a", { exact: true }),
  ).toBeVisible();
  await page.getByLabel("Native input a", { exact: true }).fill("-0.0");
  const sedona = page.waitForResponse((r) =>
    r.url().endsWith("/api/native/step"),
  );
  await page
    .getByRole("button", { name: "Step native controller", exact: true })
    .click();
  const s = await sedona;
  expect(s.ok()).toBe(true);
  check(s.request().postData()!, '["inputs","a","value"]', "-0.0");
  await page
    .getByRole("button", { name: "Stop native simulator", exact: true })
    .click();
});
test("shared group inputs survive exact large integer and float reopen without loosening structural fields", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "System sim", exact: true }).click();
  const buffer = execFileSync(
    python,
    [
      "-c",
      "from bms_tool.simulation_group import demo_workspace;p=demo_workspace();p.programs[0].program.nodes[1].params['value']=0;print(p.model_dump_json())",
    ],
    { cwd: root },
  );
  await page
    .locator('input[type=file][accept=".bms-workspace.json"]')
    .setInputFiles({
      name: "typed.bms-workspace.json",
      mimeType: "application/json",
      buffer,
    });
  await expect(page.locator(".group-elapsed")).toHaveText("0.0 s");
  for (const token of ["1152921504606846976", "1e30", "1.0", "-0.0"]) {
    await page
      .getByLabel("Group input producer.value", { exact: true })
      .fill(token);
    const pending = page.waitForResponse((r) =>
      r.url().endsWith("/api/groups/step"),
    );
    await page.getByRole("button", { name: "Step group", exact: true }).click();
    const response = await pending;
    expect(response.ok()).toBe(true);
    check(
      response.request().postData()!,
      '["inputs","producer","value","value"]',
      token,
    );
    await page.getByRole("button", { name: "Program", exact: true }).click();
    await page.getByRole("button", { name: "System sim", exact: true }).click();
    await expect(
      page.getByLabel("Group input producer.value", { exact: true }),
    ).toBeVisible();
    const again = page.waitForResponse((r) =>
      r.url().endsWith("/api/groups/step"),
    );
    await page.getByRole("button", { name: "Step group", exact: true }).click();
    check(
      (await again).request().postData()!,
      '["inputs","producer","value","value"]',
      token,
    );
  }
  await page.getByRole("button", { name: "Close group", exact: true }).click();
});
test("runtime preview receives the same typed live input and unsafe integer edits dispatch nothing", async ({
  page,
}) => {
  await load(page);
  const input = page.getByLabel("Simulate a", { exact: true });
  await input.fill("1e30");
  await input.fill("9007199254740993");
  await expect(input).toHaveJSProperty(
    "validationMessage",
    "Error: This integer is not exactly representable by the execution numeric profile",
  );
  await input.fill("1e30");
  await page.getByRole("button", { name: "Runtime", exact: true }).click();
  const pending = page.waitForResponse((r) =>
    r.url().endsWith("/api/runtime/plan"),
  );
  await page
    .getByRole("button", {
      name: "Validate and preview deployment",
      exact: true,
    })
    .click();
  const response = await pending;
  expect(response.ok()).toBe(true);
  check(response.request().postData()!, '["inputs","a"]', "1e30");
});

for (const token of ["1.0", "1152921504606846976"])
  test(
    "force default retains accepted last scan numeric type: " + token,
    async ({ page }) => {
      await load(page);
      await page.getByLabel("Simulate a", { exact: true }).fill(token);
      await step(page);
      await page.locator('.react-flow__node[data-id="a"]').click();
      await expect(page.getByLabel("Simulation force value")).toHaveValue(
        token,
      );
      await page
        .getByRole("button", { name: "Hold simulation value", exact: true })
        .click();
      check(await step(page), '["forces","a"]', token);
      await page.getByTitle("Reset simulation", { exact: true }).click();
    },
  );
function deepEarlier(receipt: any) {
  let ignored: any = 0;
  for (let i = 0; i < 70; i++) ignored = [ignored];
  return {
    ...receipt,
    history: [
      {
        time: 0,
        clock: receipt.history[0].clock,
        values: {},
        outputs: {},
        ignored,
      },
      ...receipt.history,
    ],
  };
}
test("deep receipt refusal preserves the proved owned handle so Reset retires it", async ({
  page,
  request,
}) => {
  await load(page);
  let owned = "";
  await page.route("**/api/simulation/step", async (route) => {
    const response = await fetchSimulationResponse(route),
      receipt = await response.json();
    owned = receipt.session;
    await route.fulfill({ response, json: deepEarlier(receipt) });
  });
  await page.getByTitle("Step simulation", { exact: true }).click();
  await expect(page.locator(".simulation > .inline-error")).toContainText(
    "depth",
  );
  const retired = page.waitForResponse((r) =>
    r.url().endsWith("/api/simulation/retire"),
  );
  await page.getByTitle("Reset simulation", { exact: true }).click();
  const response = await retired;
  expect(response.request().postDataJSON().session).toBe(owned);
  expect((await response.json()).retired).toBe(true);
  await expect(page.getByText(/unknown session.*expiry/i)).toHaveCount(0);
});
test("a held first receipt after Reset retires its verified handle before irrelevant deep extraction", async ({
  page,
}) => {
  await load(page);
  let release!: () => void, admitted!: () => void;
  const gate = new Promise<void>((r) => (release = r)),
    captured = new Promise<void>((r) => (admitted = r));
  let owned = "";
  await page.route("**/api/simulation/step", async (route) => {
    const response = await fetchSimulationResponse(route),
      receipt = await response.json();
    owned = receipt.session;
    admitted();
    await gate;
    await route.fulfill({ response, json: deepEarlier(receipt) });
  });
  await page.getByTitle("Step simulation", { exact: true }).click();
  await captured;
  await page.getByTitle("Reset simulation", { exact: true }).click();
  const retired = page.waitForResponse((r) =>
    r.url().endsWith("/api/simulation/retire"),
  );
  release();
  const response = await retired;
  expect(response.request().postDataJSON().session).toBe(owned);
  expect((await response.json()).retired).toBe(true);
  await expect(page.locator(".elapsed")).toHaveText("0.0 s");
  await expect(page.locator(".simulation > .inline-error")).toHaveCount(0);
});

test("shared initial numeric token survives authoring, workspace export and reopening", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "System sim", exact: true }).click();
  await page
    .getByRole("button", { name: "Load shared-signal demo", exact: true })
    .click();
  await expect(page.locator(".group-elapsed")).toHaveText("0.0 s");
  await page.getByLabel("Remove shared signal 0").click();
  await page
    .getByLabel("Shared signal source", { exact: true })
    .selectOption("producer.signal");
  await page
    .getByLabel("Shared signal destination", { exact: true })
    .selectOption("consumer.incoming");
  await page
    .getByLabel("Shared signal initial value", { exact: true })
    .fill("1.0");
  await page
    .getByRole("button", { name: "Add shared signal", exact: true })
    .click();
  const pending = page.waitForResponse((r) =>
    r.url().endsWith("/api/groups/start"),
  );
  await page.getByRole("button", { name: "Start group", exact: true }).click();
  check(
    (await pending).request().postData()!,
    '["definition","links",0,"initial"]',
    "1.0",
  );
  await expect(page.locator(".group-elapsed")).toHaveText("0.0 s");
  const downloading = page.waitForEvent("download");
  await page
    .locator(".system-simulation")
    .getByRole("button", { name: "Save workspace", exact: true })
    .click();
  const file = await downloading;
  execFileSync(python, [
    "-c",
    "import json,sys;v=json.load(open(sys.argv[1]));assert type(v['links'][0]['initial']) is float and v['links'][0]['initial']==1.0",
    (await file.path())!,
  ]);
  await page.getByRole("button", { name: "Program", exact: true }).click();
  await page.getByRole("button", { name: "System sim", exact: true }).click();
  await expect(page.locator(".group-elapsed")).toHaveText("0.0 s");
  const restarted = page.waitForResponse((r) =>
    r.url().endsWith("/api/groups/start"),
  );
  await page.getByRole("button", { name: "Start group", exact: true }).click();
  check(
    (await restarted).request().postData()!,
    '["definition","links",0,"initial"]',
    "1.0",
  );
  await page.getByRole("button", { name: "Close group", exact: true }).click();
});
