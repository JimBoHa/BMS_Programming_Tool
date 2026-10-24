import {
  expect,
  test,
  type APIRequestContext,
  type Locator,
  type Page,
  type Route,
} from "@playwright/test";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { createHash } from "node:crypto";
const root = fileURLToPath(new URL("../..", import.meta.url)),
  python = path.join(root, ".venv/bin/python");
const py = (code: string, input = "") =>
  execFileSync(python, ["-c", code], {
    cwd: root,
    input,
    encoding: "utf8",
    env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
  });
function fixture(
  loop = "primary-only",
  arrangement = "headered",
  network = false,
  extra: any = {},
  strategy = "decoupler-flow",
) {
  return JSON.parse(
    py(
      `import json,sys,tempfile
from tests.test_hydronic_io import make_case,topology
from bms_tool.plant_signals import ReviewKey
v=json.load(sys.stdin)
with tempfile.TemporaryDirectory() as d:
 t=topology(v['loop'],v['arrangement'],v['strategy']);t.update(v['extra']);s,r,p=make_case(d,t,network=v['network']);raw=s.plant.export_review(ReviewKey(**r['plant_review']),'json');plant=json.loads(raw);print(json.dumps({'sources':[x['source_json'] for x in plant['sources']],'plan':plant['plan'],'template':r,'topology':t}))`,
      JSON.stringify({ loop, arrangement, network, extra, strategy }),
    ),
  );
}
async function headers(request: APIRequestContext) {
  return {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
}
async function post(request: APIRequestContext, url: string, data: any) {
  const r = await request.post("/api" + url, {
    headers: await headers(request),
    data,
  });
  expect(r.ok(), await r.text()).toBe(true);
  return r;
}
async function seed(request: APIRequestContext, f = fixture()) {
  for (const source of f.sources) {
    const r = await request.post("/api/plant-signals/sources/import", {
      headers: await headers(request),
      multipart: {
        file: {
          name: "literal.json",
          mimeType: "application/json",
          buffer: Buffer.from(source),
        },
      },
    });
    expect(r.ok(), await r.text()).toBe(true);
  }
  const profile = await (
    await request.get("/api/plant-signals/profile")
  ).json();
  const review = await (
    await post(request, "/plant-signals/review", {
      profile_sha256: profile.profile.sha256,
      plan: f.plan,
    })
  ).json();
  const capture = await (
    await post(request, "/plant-signals/captures/save", {
      id: review.id,
      content_sha256: review.content_sha256,
    })
  ).json();
  return { ...f, review, capture };
}
async function open(page: Page, f: any) {
  await page.goto("/");
  await page.getByRole("button", { name: "System sim", exact: true }).click();
  const parent = page.getByRole("region", {
    name: "Plant I/O and network engineering schedule",
    exact: true,
  });
  await parent
    .getByRole("button", {
      name: "Open offline plant engineering schedule",
      exact: true,
    })
    .click();
  await parent
    .getByRole("button", {
      name: "Open plant capture " + f.capture.id.slice(0, 8),
      exact: true,
    })
    .click();
  const panel = parent.getByRole("region", {
    name: "Chilled-water hydraulic I/O planner",
    exact: true,
  });
  await panel
    .getByRole("button", { name: "Open hydraulic I/O planner", exact: true })
    .click();
  await expect(
    panel.getByLabel("Hydraulic loop", { exact: true }),
  ).toBeVisible();
  return { parent, panel };
}
async function configure(panel: Locator, f: any) {
  const t = f.topology;
  await panel
    .getByLabel("Hydraulic loop", { exact: true })
    .selectOption(t.loop);
  await panel
    .getByLabel("Hydraulic primary arrangement", { exact: true })
    .selectOption(t.primary_arrangement);
  await panel
    .getByLabel("Hydraulic chiller count", { exact: true })
    .fill(String(t.chillers));
  if (t.primary_arrangement === "headered") {
    await panel
      .getByLabel("Hydraulic primary pump count", { exact: true })
      .fill(String(t.primary_pumps));
    await panel
      .getByLabel("Confirm equally sized primary pumps", { exact: true })
      .check();
    await panel
      .getByLabel("Hydraulic isolation command", { exact: true })
      .selectOption(t.isolation_command);
  }
  if (t.loop === "primary-secondary") {
    await panel
      .getByLabel("Hydraulic secondary pump count", { exact: true })
      .fill(String(t.secondary_pumps));
    await panel
      .getByLabel("Confirm equally sized secondary pumps", { exact: true })
      .check();
    await panel
      .getByLabel("Hydraulic primary speed measurement", { exact: true })
      .selectOption(t.primary_speed_measurement);
  }
  for (const name of ["flow", "pressure", "temperature"])
    await panel
      .getByLabel(`Hydraulic ${name} unit`, { exact: true })
      .selectOption(t.units[name]);
  if (t.monitoring?.length || t.prove_on?.length) {
    await panel
      .getByText("Optional monitoring and selected prove-on sources", {
        exact: true,
      })
      .click();
    for (const m of t.monitoring ?? [])
      await panel.getByLabel("Hydraulic monitor " + m, { exact: true }).check();
    for (const m of t.prove_on ?? [])
      await panel
        .getByLabel("Hydraulic prove-on " + m, { exact: true })
        .check();
  }
}
async function derive(panel: Locator) {
  await panel
    .getByRole("button", { name: "Derive hydraulic roles", exact: true })
    .click();
  await expect(
    panel.getByLabel("Derived hydraulic role schedule", { exact: true }),
  ).toBeVisible();
}
async function download(page: Page, panel: Locator, name: string) {
  const waiting = page.waitForEvent("download");
  await panel.getByRole("button", { name, exact: true }).click();
  const file = (await (await waiting).path())!;
  return { file, bytes: readFileSync(file) };
}
function verify(file: string) {
  return JSON.parse(
    py(
      `import json,hashlib,sys,math
v=json.load(open(sys.argv[1]));c=lambda x:json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode();assert v['content_sha256']==hashlib.sha256(c({k:x for k,x in v.items() if k!='content_sha256'})).hexdigest()
if 'plant_reference' in v:
 p=v['plant_reference'];assert hashlib.sha256(p['original_review_json'].encode()).hexdigest()==p['raw_sha256'];source=json.loads(p['original_review_json'])
 for s in source['sources']:
  assert hashlib.sha256(s['source_json'].encode()).hexdigest()==s['id']
  program=json.loads(s['source_json'])
  if program['id']=='hydraulic-source':
   assert program['metadata']['opaque'][0]==9007199254740993;assert math.copysign(1,program['metadata']['opaque'][1])==-1
 assert v['hardware_verified'] is False and v['native_allocation_verified'] is False
print(json.dumps({'status':v.get('status'),'roles':[r['id'] for r in v.get('role_plan',v)['roles']]}))`.replace(
        "sys.argv[1]",
        "'" + file.replaceAll("'", "\\'") + "'",
      ),
    ),
  );
}
async function addPhysical(
  panel: Locator,
  kind = "controller",
  model = "FX-PCG2611-0",
) {
  await panel
    .getByLabel("Hydraulic physical label", { exact: true })
    .fill(kind === "module" ? "Explicit expansion" : "Explicit base");
  await panel
    .getByLabel("Hydraulic physical PLANT host", { exact: true })
    .selectOption("mainhost");
  await panel
    .getByLabel("Hydraulic physical kind", { exact: true })
    .selectOption(kind);
  await panel
    .getByLabel("Hydraulic physical model", { exact: true })
    .fill(model);
  if (kind === "module")
    await panel
      .getByLabel("Hydraulic module parent", { exact: true })
      .selectOption("physical1");
  await panel
    .getByRole("button", {
      name: "Add explicit hydraulic physical host",
      exact: true,
    })
    .click();
}
async function bind(panel: Locator, f: any, physicalModule = false) {
  for (const b of f.template.bindings) {
    await panel
      .getByLabel("Hydraulic endpoint " + b.role_id, { exact: true })
      .selectOption(JSON.stringify([b.instance_id, b.node_id]));
    await panel
      .getByLabel("Hydraulic transport " + b.role_id, { exact: true })
      .selectOption(b.transport);
    if (b.transport === "physical") {
      await panel
        .getByLabel("Hydraulic physical host " + b.role_id, { exact: true })
        .selectOption(
          physicalModule && b.role_id === "building.dp"
            ? "physical2"
            : "physical1",
        );
      await panel
        .getByLabel("Hydraulic electrical mode " + b.role_id, { exact: true })
        .selectOption(b.mode);
    } else
      for (const link of b.network_link_ids)
        await panel
          .getByLabel(`Hydraulic network ${b.role_id} ${link}`, { exact: true })
          .check();
  }
}
async function reviewed(panel: Locator) {
  await panel
    .getByRole("button", {
      name: "Review hydraulic bindings and capacity",
      exact: true,
    })
    .click();
  await expect(
    panel.getByLabel("Reviewed hydraulic bindings and capacity", {
      exact: true,
    }),
  ).toBeVisible();
}
async function hold(page: Page, suffix: string) {
  let release!: () => void, seen!: () => void, done!: () => void;
  const gate = new Promise<void>((r) => (release = r)),
    incoming = new Promise<void>((r) => (seen = r)),
    finished = new Promise<void>((r) => (done = r));
  const handler = async (route: Route) => {
    const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 }),
      body = await response.body();
    seen();
    await gate;
    try {
      await route.fulfill({ response, body });
    } finally {
      done();
    }
  };
  await page.route("**/api/hydronic-io" + suffix, handler);
  return {
    release,
    incoming,
    finished,
    dispose: () => page.unroute("**/api/hydronic-io" + suffix, handler),
  };
}

for (const [loop, arrangement, strategy] of [
  ["primary-only", "headered", "decoupler-flow"],
  ["primary-only", "dedicated", "decoupler-flow"],
  ["primary-secondary", "headered", "flow-difference"],
  ["primary-secondary", "dedicated", "temperature-difference"],
])
  test(`authors ${loop} ${arrangement} exact hydraulic roles and original exports`, async ({
    page,
    request,
  }) => {
    const extra =
        loop === "primary-secondary"
          ? {
              units: { flow: "L/s", pressure: "kPa", temperature: "°C" },
              monitoring: ["primary-flow"],
              prove_on: ["chiller"],
            }
          : {},
      f = await seed(
        request,
        fixture(loop, arrangement, false, extra, strategy),
      );
    const { panel } = await open(page, f);
    await configure(panel, f);
    await derive(panel);
    const role = await download(
        page,
        panel,
        "Download original hydraulic role JSON",
      ),
      literal = JSON.parse(role.bytes.toString()),
      check = verify(role.file);
    expect(literal.equipment_counts).toEqual({
      chillers: 1,
      primary_pumps: 1,
      secondary_pumps: loop === "primary-secondary" ? 1 : 0,
    });
    expect(
      check.roles.filter((id: string) => id === "primary.flow"),
    ).toHaveLength(1);
    expect(check.roles.includes("chiller.1.isolation")).toBe(
      arrangement === "headered",
    );
    expect(check.roles.includes("plant.minimum_flow_bypass")).toBe(
      loop === "primary-only",
    );
    expect(check.roles.includes("secondary.flow")).toBe(
      loop === "primary-secondary",
    );
    if (strategy === "temperature-difference") {
      expect(check.roles).toContain("primary.supply_temperature");
      expect(
        literal.roles.find((r: any) => r.id === "primary.supply_temperature")
          .unit,
      ).toBe("°C");
    }
    const csv = await download(page, panel, "Export hydraulic role CSV");
    expect(csv.bytes.toString()).toContain(literal.content_sha256);
    if (loop === "primary-only" && arrangement === "headered") {
      await addPhysical(panel);
      await addPhysical(panel, "module", "FX-PCX2721-0");
      await bind(panel, f, true);
      await reviewed(panel);
      const result = panel.getByLabel(
        "Reviewed hydraulic bindings and capacity",
        { exact: true },
      );
      await expect(result).toContainText(
        "Declared hydraulic subset consistent",
      );
      await expect(result).toContainText("Spare channels established: false");
      const actual = await download(
        page,
        panel,
        "Export original hydraulic review JSON",
      );
      expect(verify(actual.file).status).toBe("declared-subset-consistent");
      const body = JSON.parse(actual.bytes.toString());
      expect(body.capacity_reviews).toHaveLength(2);
      expect(
        body.capacity_reviews.find(
          (r: any) => r.physical_host.kind === "module",
        ).capacity_review.declared_channels,
      ).toBe(1);
      const csv = await download(page, panel, "Export bound hydraulic CSV");
      expect(csv.bytes.toString()).toContain(body.content_sha256);
      expect(csv.bytes.toString()).toContain("FX-PCX2721-0");
      const again = await download(
        page,
        panel,
        "Export original hydraulic review JSON",
      );
      expect(again.bytes).toEqual(actual.bytes);
    } else {
      await reviewed(panel);
      await expect(
        panel.getByLabel("Reviewed hydraulic bindings and capacity", {
          exact: true,
        }),
      ).toContainText("missing-binding");
    }
    expect(
      (await (await request.get("/api/session")).json()).field_network_open,
    ).toBe(false);
  });

test("network bindings use exact existing links and no physical channels", async ({
  page,
  request,
}) => {
  const f = await seed(
      request,
      fixture(
        "primary-secondary",
        "dedicated",
        true,
        {},
        "temperature-difference",
      ),
    ),
    { panel } = await open(page, f);
  await configure(panel, f);
  await derive(panel);
  await bind(panel, f);
  await reviewed(panel);
  const file = await download(
      page,
      panel,
      "Export original hydraulic review JSON",
    ),
    value = JSON.parse(file.bytes.toString());
  expect(verify(file.file).status).toBe("declared-subset-consistent");
  expect(value.capacity_reviews).toEqual([]);
  expect(
    value.binding_results.every(
      (r: any) => r.transport === "network" && r.network_evidence.length === 1,
    ),
  ).toBe(true);
  await download(page, panel, "Export bound hydraulic CSV");
});

test("all three measurement strategies derive their actual flow and temperature dependencies", async ({
  page,
  request,
}) => {
  const f = await seed(request, fixture("primary-secondary", "dedicated")),
    { panel } = await open(page, f);
  await configure(panel, f);
  for (const strategy of [
    "decoupler-flow",
    "flow-difference",
    "temperature-difference",
  ]) {
    await panel
      .getByLabel("Hydraulic primary speed measurement", { exact: true })
      .selectOption(strategy);
    await derive(panel);
    const value = JSON.parse(
        (
          await download(page, panel, "Download original hydraulic role JSON")
        ).bytes.toString(),
      ),
      ids = value.roles.map((r: any) => r.id);
    expect(ids).toContain("secondary.flow");
    expect(ids.includes("decoupler.flow")).toBe(strategy === "decoupler-flow");
    expect(ids.includes("primary.flow")).toBe(strategy === "flow-difference");
    expect(ids.includes("primary.supply_temperature")).toBe(
      strategy === "temperature-difference",
    );
  }
});

test("physical model, module parent, survey reference and incomplete bindings require explicit declarations", async ({
  page,
  request,
}) => {
  const f = await seed(request),
    { panel } = await open(page, f);
  await panel
    .getByRole("button", { name: "Derive hydraulic roles", exact: true })
    .click();
  await expect(panel.getByRole("alert")).toContainText("equally sized");
  await configure(panel, f);
  await derive(panel);
  await panel
    .getByLabel("Hydraulic physical label", { exact: true })
    .fill("Module without parent");
  await panel
    .getByLabel("Hydraulic physical PLANT host", { exact: true })
    .selectOption("mainhost");
  await panel
    .getByLabel("Hydraulic physical kind", { exact: true })
    .selectOption("module");
  await panel
    .getByLabel("Hydraulic physical model", { exact: true })
    .fill("FX-PCX2721-0");
  await panel
    .getByRole("button", {
      name: "Add explicit hydraulic physical host",
      exact: true,
    })
    .click();
  await expect(panel.getByRole("alert")).toContainText("parent controller");
  await addPhysical(panel);
  await panel
    .getByLabel("Bind exact hydraulic hardware survey", { exact: true })
    .check();
  await panel
    .getByRole("button", {
      name: "Add explicit hydraulic physical host",
      exact: true,
    })
    .click();
  await expect(panel.getByRole("alert")).toContainText("Declare a label");
  await panel
    .getByLabel("Hydraulic physical label", { exact: true })
    .fill("Invalid module survey");
  await panel
    .getByLabel("Hydraulic physical PLANT host", { exact: true })
    .selectOption("mainhost");
  await panel
    .getByLabel("Hydraulic physical kind", { exact: true })
    .selectOption("module");
  await panel
    .getByLabel("Hydraulic physical model", { exact: true })
    .fill("FX-PCX2721-0");
  await panel
    .getByLabel("Hydraulic module parent", { exact: true })
    .selectOption("physical1");
  await panel
    .getByLabel("Bind exact hydraulic hardware survey", { exact: true })
    .check();
  await panel
    .getByRole("button", {
      name: "Add explicit hydraulic physical host",
      exact: true,
    })
    .click();
  await expect(panel.getByRole("alert")).toContainText("exact stored ID/hash");
  await panel
    .getByLabel("Hydraulic endpoint building.dp", { exact: true })
    .selectOption('["main","building_dp"]');
  await panel
    .getByRole("button", {
      name: "Review hydraulic bindings and capacity",
      exact: true,
    })
    .click();
  await expect(panel.getByRole("alert")).toContainText("explicit transport");
});

for (const action of [
  "derive-edit",
  "review-cancel",
  "review-source",
  "export-navigation",
])
  test(`held ${action} result cannot restore stale hydraulic evidence or download`, async ({
    page,
    request,
  }) => {
    const f = await seed(request),
      { panel, parent } = await open(page, f);
    await configure(panel, f);
    if (action !== "derive-edit") await derive(panel);
    if (action === "export-navigation") await reviewed(panel);
    const endpoint =
        action === "derive-edit"
          ? "/derive"
          : action === "export-navigation"
            ? "/reviews/export/json"
            : "/review",
      gate = await hold(page, endpoint);
    let downloads = 0;
    page.on("download", () => downloads++);
    try {
      await panel
        .getByRole("button", {
          name:
            action === "derive-edit"
              ? "Derive hydraulic roles"
              : action === "export-navigation"
                ? "Export original hydraulic review JSON"
                : "Review hydraulic bindings and capacity",
          exact: true,
        })
        .click();
      await gate.incoming;
      if (action === "derive-edit")
        await panel
          .getByLabel("Hydraulic chiller count", { exact: true })
          .fill("2");
      else if (action === "review-cancel")
        await panel
          .getByRole("button", {
            name: "Cancel hydraulic response",
            exact: true,
          })
          .click();
      else if (action === "review-source")
        await parent
          .getByLabel("Plant host label mainhost", { exact: true })
          .fill("Changed source authority");
      else
        await page
          .getByRole("button", { name: "Program", exact: true })
          .click();
      gate.release();
      await gate.finished;
      await expect(
        page.getByLabel("Reviewed hydraulic bindings and capacity", {
          exact: true,
        }),
      ).toHaveCount(0);
      if (action === "derive-edit")
        await expect(
          panel.getByLabel("Derived hydraulic role schedule", { exact: true }),
        ).toHaveCount(0);
      expect(downloads).toBe(0);
    } finally {
      gate.release();
      await gate.dispose();
    }
  });

for (const corruption of [
  "profile",
  "file-header",
  "review-source",
  "csv-source",
])
  test(`unsupported or mismatched ${corruption} cannot authorize hydraulic export`, async ({
    page,
    request,
  }) => {
    const f = await seed(request);
    if (corruption === "profile")
      await page.route("**/api/hydronic-io/profile", async (route) => {
        const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 }),
          value = await response.json();
        value.profile.sha256 = "0".repeat(64);
        await route.fulfill({ response, json: value });
      });
    if (corruption === "profile") {
      await page.goto("/");
      await page
        .getByRole("button", { name: "System sim", exact: true })
        .click();
      const parent = page.getByRole("region", {
        name: "Plant I/O and network engineering schedule",
        exact: true,
      });
      await parent
        .getByRole("button", {
          name: "Open offline plant engineering schedule",
          exact: true,
        })
        .click();
      await parent
        .getByRole("button", {
          name: "Open plant capture " + f.capture.id.slice(0, 8),
          exact: true,
        })
        .click();
      const panel = parent.getByRole("region", {
        name: "Chilled-water hydraulic I/O planner",
        exact: true,
      });
      await panel
        .getByRole("button", {
          name: "Open hydraulic I/O planner",
          exact: true,
        })
        .click();
      await expect(panel.getByRole("alert")).toContainText("unsupported");
      await expect(
        panel.getByLabel("Hydraulic loop", { exact: true }),
      ).toHaveCount(0);
      return;
    }
    const { panel } = await open(page, f);
    await configure(panel, f);
    if (corruption === "file-header") {
      await page.route("**/api/hydronic-io/derive", async (route) => {
        const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 });
        await route.fulfill({
          response,
          headers: { ...response.headers(), "x-file-sha256": "0".repeat(64) },
        });
      });
      await panel
        .getByRole("button", { name: "Derive hydraulic roles", exact: true })
        .click();
      await expect(panel.getByRole("alert")).toContainText("digest");
      await expect(
        panel.getByLabel("Derived hydraulic role schedule", { exact: true }),
      ).toHaveCount(0);
      return;
    }
    await derive(panel);
    if (corruption === "review-source") {
      await page.route("**/api/hydronic-io/review", async (route) => {
        const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 }),
          value = await response.json();
        value.plant_reference.original_review_json += " ";
        const body = Buffer.from(JSON.stringify(value));
        await route.fulfill({
          response,
          body,
          headers: {
            ...response.headers(),
            "x-file-sha256": createHash("sha256").update(body).digest("hex"),
          },
        });
      });
      await panel
        .getByRole("button", {
          name: "Review hydraulic bindings and capacity",
          exact: true,
        })
        .click();
      await expect(panel.getByRole("alert")).toContainText(
        "another declaration/source",
      );
      await expect(
        panel.getByLabel("Reviewed hydraulic bindings and capacity", {
          exact: true,
        }),
      ).toHaveCount(0);
      return;
    }
    await reviewed(panel);
    await page.route("**/api/hydronic-io/reviews/export/csv", async (route) => {
      const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 }),
        body = Buffer.from(
          (await response.text())
            .replaceAll(f.review.content_sha256, "f".repeat(64))
            .replaceAll(/(?<=,)[a-f0-9]{64}(?=,)/g, "0".repeat(64)),
        );
      await route.fulfill({
        response,
        body,
        headers: {
          ...response.headers(),
          "x-file-sha256": createHash("sha256").update(body).digest("hex"),
        },
      });
    });
    let downloads = 0;
    page.on("download", () => downloads++);
    await panel
      .getByRole("button", { name: "Export bound hydraulic CSV", exact: true })
      .click();
    await expect(panel.getByRole("alert")).toContainText(
      "another source/review",
    );
    expect(downloads).toBe(0);
  });

test("unsupported profile reload retires prior role and bound export authority while retaining draft choices", async ({
  page,
  request,
}) => {
  const f = await seed(request),
    { panel } = await open(page, f);
  await configure(panel, f);
  await derive(panel);
  await reviewed(panel);
  await expect(
    panel.getByRole("button", {
      name: "Download original hydraulic role JSON",
      exact: true,
    }),
  ).toBeVisible();
  await page.route("**/api/hydronic-io/profile", async (route) => {
    const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 }),
      value = await response.json();
    value.profile.sha256 = "0".repeat(64);
    await route.fulfill({ response, json: value });
  });
  await panel
    .getByRole("button", { name: "Reload hydraulic authority", exact: true })
    .click();
  await expect(panel.getByRole("alert")).toContainText("unsupported");
  await expect(
    panel.getByRole("button", {
      name: "Download original hydraulic role JSON",
      exact: true,
    }),
  ).toHaveCount(0);
  await expect(
    panel.getByRole("button", {
      name: "Export original hydraulic review JSON",
      exact: true,
    }),
  ).toHaveCount(0);
  await page.unroute("**/api/hydronic-io/profile");
  await panel
    .getByRole("button", { name: "Reload hydraulic authority", exact: true })
    .click();
  await expect(
    panel.getByLabel("Hydraulic chiller count", { exact: true }),
  ).toHaveValue("1");
  await expect(
    panel.getByLabel("Confirm equally sized primary pumps", { exact: true }),
  ).toBeChecked();
  await expect(
    panel.getByLabel("Derived hydraulic role schedule", { exact: true }),
  ).toHaveCount(0);
});
