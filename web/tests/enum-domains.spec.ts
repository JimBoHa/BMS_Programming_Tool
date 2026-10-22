import { expect, test, type Page } from "@playwright/test";
import { execFileSync, spawn } from "node:child_process";
import { createSocket } from "node:dgram";
import path from "node:path";
const root = path.resolve("..");
test.afterEach(async ({ request }) => {
  const token = (await (await request.get("/api/session")).json()).token;
  expect(
    (
      await request.post("/api/bacnet/disconnect", {
        headers: { "X-Studio-Token": token },
        data: {},
      })
    ).ok(),
  ).toBe(true);
  expect(
    (await (await request.get("/api/bacnet/status")).json()).connected,
  ).toBe(false);
});
async function connectTab(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  return page.getByRole("region", {
    name: "Operator enum mapping review",
    exact: true,
  });
}
async function example(page: Page) {
  const panel = await connectTab(page);
  await panel
    .getByRole("button", { name: "Load operator mapping example", exact: true })
    .click();
  return panel;
}
async function review(panel: ReturnType<Page["getByRole"]>) {
  await panel
    .getByRole("button", { name: "Review enum mapping", exact: true })
    .click();
  const result = panel.getByLabel("Enum mapping review result", {
    exact: true,
  });
  await expect(result).toBeVisible();
  return result;
}
test("offline enum mapping preserves declarations and exact review export and explicit import review", async ({
  page,
  request,
}) => {
  const panel = await example(page),
    result = await review(panel);
  await expect(result).toContainText("valid_declared_mapping");
  await expect(result).toContainText("Target coverage: false");
  await expect(result).toContainText(
    "target_states_unreachable_from_declared_source",
  );
  let pending = page.waitForEvent("download");
  await panel
    .getByRole("button", { name: "Export exact enum review", exact: true })
    .click();
  const file = (await (await pending).path())!;
  expect(
    execFileSync(
      path.join(root, ".venv/bin/python"),
      [
        "-c",
        `
import hashlib,json,sys
d=json.load(open(sys.argv[1]));seal=d.pop('review_sha256')
assert hashlib.sha256(json.dumps(d,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()==seal
assert d['properties']['native_or_portable_binding']=='not established'
assert d['source_plan']['source']['states'][0]=={'id':'off','code':0,'label':'Off'}
assert d['source_plan']['target']['states'][2]['code']==3
assert d['probes'][-1]['status']=='unknown_value';print('verified')
`,
        file,
      ],
      { encoding: "utf8" },
    ).trim(),
  ).toBe("verified");
  pending = page.waitForEvent("download");
  await panel
    .getByRole("button", { name: "Export reviewed enum plan", exact: true })
    .click();
  const source = (await (await pending).path())!;
  await panel
    .getByRole("button", { name: "Clear enum declaration", exact: true })
    .click();
  await panel
    .getByLabel("Import enum plan", { exact: true })
    .setInputFiles(source);
  await expect(panel).toContainText("Review required; no native binding.");
  await expect(
    panel.getByRole("button", {
      name: "Export exact enum review",
      exact: true,
    }),
  ).toBeDisabled();
  await expect(
    panel.getByLabel("Source state 1 code", { exact: true }),
  ).toHaveValue("0");
  await expect(await review(panel)).toContainText("valid_declared_mapping");
  expect(
    (await (await request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
});

test("enum editor exposes loss, missing codes, strict code input and explicit rationale", async ({
  page,
}) => {
  const panel = await example(page);
  await panel.getByLabel("Mapping 2 target code", { exact: true }).fill("");
  await expect(await review(panel)).toContainText("unmapped_source_code");
  await panel.getByLabel("Mapping 2 target code", { exact: true }).fill("1");
  await expect(await review(panel)).toContainText(
    "many_to_one_loss_not_allowed",
  );
  await panel
    .getByLabel("Allow declared many-to-one information loss", { exact: true })
    .check();
  await expect(await review(panel)).toContainText("loss_rationale_required");
  await panel
    .getByLabel("Enum loss rationale", { exact: true })
    .fill("Operator intentionally combines two source modes.");
  await expect(await review(panel)).toContainText("valid_with_declared_loss");
  await panel
    .getByLabel("Require every target state to be reachable", { exact: true })
    .check();
  await expect(await review(panel)).toContainText("invalid");
  await panel.getByLabel("Source state 1 code", { exact: true }).fill("false");
  await panel
    .getByRole("button", { name: "Review enum mapping", exact: true })
    .click();
  await expect(panel.getByRole("alert")).toContainText(
    "requires an integer code",
  );
});

test("delayed enum export and review cannot survive edited declarations or navigation", async ({
  page,
}) => {
  const panel = await example(page);
  await review(panel);
  let entered!: () => void, release!: () => void;
  const held = new Promise<void>((resolve) => {
      entered = resolve;
    }),
    gate = new Promise<void>((resolve) => {
      release = resolve;
    });
  await page.route("**/api/enum-mapping/export", async (route) => {
    const response = await route.fetch();
    entered();
    await gate;
    await route.fulfill({ response });
  });
  const downloads: string[] = [];
  page.on("download", (file) => downloads.push(file.suggestedFilename()));
  await panel
    .getByRole("button", { name: "Export exact enum review", exact: true })
    .click();
  await held;
  await panel
    .getByLabel("Target state 1 label", { exact: true })
    .fill("Changed after reviewed export request");
  release();
  await expect(
    panel.getByLabel("Enum mapping review result", { exact: true }),
  ).toHaveCount(0);
  await page.waitForTimeout(100);
  expect(downloads).toEqual([]);
  await page.unroute("**/api/enum-mapping/export");
  let reviewed!: () => void, finish!: () => void;
  const waiting = new Promise<void>((resolve) => {
      reviewed = resolve;
    }),
    after = new Promise<void>((resolve) => {
      finish = resolve;
    });
  await page.route("**/api/enum-mapping/review", async (route) => {
    const response = await route.fetch();
    reviewed();
    await after;
    await route.fulfill({ response });
  });
  await panel
    .getByRole("button", { name: "Review enum mapping", exact: true })
    .click();
  await waiting;
  await page.getByRole("button", { name: "Program", exact: true }).click();
  finish();
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(
    page.getByLabel("Enum mapping review result", { exact: true }),
  ).toHaveCount(0);
});

async function freePort(): Promise<number> {
  const socket = createSocket("udp4");
  return new Promise((resolve, reject) => {
    socket.once("error", reject);
    socket.bind(0, "127.0.0.1", () => {
      const port = (socket.address() as any).port;
      socket.close(() => resolve(port));
    });
  });
}
async function peer(routed: boolean, code = 1) {
  const child = spawn(
    path.join(root, ".venv/bin/python"),
    [
      "-u",
      "-c",
      `
import asyncio,sys
from tests.test_native_enum_domain import make_enum_peer
async def main():
 peer=await make_enum_peer(routed=sys.argv[1]=='1',code=int(sys.argv[2]));print(peer.endpoint.split(':')[-1],flush=True)
 try:await asyncio.Event().wait()
 finally:peer.close()
asyncio.run(main())
`,
      routed ? "1" : "0",
      String(code),
    ],
    {
      cwd: root,
      env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  const port = await new Promise<number>((resolve, reject) => {
    let data = "",
      error = "";
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error(error || "Enum peer startup timeout"));
    }, 5000);
    child.stdout!.on("data", (value) => {
      data += String(value);
      if (data.includes("\n")) {
        clearTimeout(timer);
        resolve(Number(data.split("\n")[0]));
      }
    });
    child.stderr!.on("data", (value) => {
      error += String(value);
    });
    child.once("error", reject);
    child.once("exit", (code) => {
      clearTimeout(timer);
      reject(new Error(`Enum peer ${code}: ${error}`));
    });
  });
  return { port, child };
}
for (const routed of [false, true])
  test(`native enum metadata ${routed ? "routed" : "direct"} is opt-in, preserves codes and exact evidence`, async ({
    page,
    request,
  }) => {
    const remote = await peer(routed, routed ? 4 : 1);
    try {
      const headers = {
        "X-Studio-Token": (await (await request.get("/api/session")).json())
          .token,
      };
      expect(
        (
          await request.post("/api/bacnet/connect", {
            headers,
            data: { local_address: `127.0.0.1:${await freePort()}` },
          })
        ).ok(),
      ).toBe(true);
      await connectTab(page);
      const panel = page.getByRole("region", {
        name: "Native point status inspection",
        exact: true,
      });
      await expect(
        panel.getByRole("button", {
          name: "Inspect native point status",
          exact: true,
        }),
      ).toBeEnabled();
      await panel
        .getByLabel("Point-status source address", { exact: true })
        .fill(routed ? "3001:7" : `127.0.0.1:${remote.port}`);
      await panel
        .getByLabel("Point-status Device identifier", { exact: true })
        .fill("device,42");
      if (routed) {
        await panel
          .getByLabel("Point-status router endpoint", { exact: true })
          .fill(`127.0.0.1:${remote.port}`);
        await panel
          .getByLabel("Point-status DNET", { exact: true })
          .fill("3001");
      }
      await panel
        .getByLabel("Selected native points", { exact: true })
        .fill("binary-input,1; multi-state-value,2");
      await panel
        .getByRole("button", {
          name: "Inspect native point status",
          exact: true,
        })
        .click();
      await expect(
        panel.getByLabel("Native point evidence report", { exact: true }),
      ).toBeVisible();
      await expect(
        panel.getByLabel("Native state domain binary-input,1", { exact: true }),
      ).toHaveCount(0);
      await panel
        .getByLabel("Read native binary and multistate domain metadata", {
          exact: true,
        })
        .check();
      await panel
        .getByRole("button", {
          name: "Inspect native point status",
          exact: true,
        })
        .click();
      const binary = panel.getByLabel("Native state domain binary-input,1", {
        exact: true,
      });
      await expect(binary).toContainText("within_standard_domain (code 1)");
      await expect(binary).toContainText('"On"');
      await expect(binary).toContainText('"Off"');
      await expect(binary).toContainText("reverse");
      await expect(
        panel.getByLabel("Native state domain multi-state-value,2", {
          exact: true,
        }),
      ).toContainText(
        routed
          ? "outside_observed_numeric_range (code 4)"
          : "within_observed_numeric_range (code 1)",
      );
      const pending = page.waitForEvent("download");
      await panel
        .getByRole("button", {
          name: "Export exact point evidence",
          exact: true,
        })
        .click();
      const file = (await (await pending).path())!;
      expect(
        execFileSync(
          path.join(root, ".venv/bin/python"),
          [
            "-c",
            `
import hashlib,json,sys
d=json.load(open(sys.argv[1]));seal=d.pop('evidence_sha256')
assert hashlib.sha256(json.dumps(d,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()==seal
binary,multi=d['objects'];assert binary['enum_domain']['states'][0]['label']=='On'
assert binary['enum_domain']['states'][0]['code']==0
assert binary['enum_domain']['value_validation']['code']==1
assert multi['enum_domain']['number_of_states']==3;print('verified')
`,
            file,
          ],
          { encoding: "utf8" },
        ).trim(),
      ).toBe("verified");
    } finally {
      remote.child.kill();
    }
  });
