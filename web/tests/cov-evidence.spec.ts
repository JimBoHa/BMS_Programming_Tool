import {
  test,
  expect,
  type Page,
  type APIRequestContext,
} from "@playwright/test";
import { spawn, execFileSync } from "node:child_process";
import { createSocket } from "node:dgram";
import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
const root = path.resolve("..");
async function freePort(): Promise<number> {
  const socket = createSocket("udp4");
  return new Promise((resolve, reject) => {
    socket.once("error", reject);
    socket.bind(0, "127.0.0.1", () => {
      const port = (socket.address() as { port: number }).port;
      socket.close(() => resolve(port));
    });
  });
}
async function peer() {
  const child = spawn(
    path.join(root, ".venv/bin/python"),
    [
      "-u",
      "-c",
      `
import asyncio,sys
from tests.test_connections import application,free_udp,point
from tests.test_bacnet_cov import send
from bacpypes3.apdu import UnconfirmedCOVNotificationRequest
from bacpypes3.basetypes import PropertyValue
from bacpypes3.constructeddata import Any
from bacpypes3.primitivedata import Real
from bms_tool.bacnet_read import close_application
async def main():
 port=free_udp();server=application(port,4190010);analog=point();analog.presentValue=2.0;analog.covIncrement=.1;server.add_object(analog)
 original=server.do_SubscribeCOVRequest; latest=None
 async def subscribe(request):
  nonlocal latest
  if request.lifetime: latest=request
  await original(request)
 server.do_SubscribeCOVRequest=subscribe;print(port,flush=True)
 try:
  while True:
   command=await asyncio.to_thread(sys.stdin.readline)
   if not command: break
   values=[-0.0,1e-7,1e20] if command.strip()=='numbers' else [2.0]*104
   for value in values:
    request=latest
    await send(server,UnconfirmedCOVNotificationRequest(subscriberProcessIdentifier=request.subscriberProcessIdentifier,initiatingDeviceIdentifier=('device',4190010),monitoredObjectIdentifier=('analog-value',1),timeRemaining=300,listOfValues=[PropertyValue(propertyIdentifier='present-value',value=Any(Real(value)))],destination=request.pduSource))
    await asyncio.sleep(.01)
   print('SENT',flush=True)
 finally: close_application(server)
asyncio.run(main())
`,
    ],
    {
      cwd: root,
      env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
      stdio: ["pipe", "pipe", "pipe"],
    },
  );
  let complete = 0;
  const port = await new Promise<number>((resolve, reject) => {
    let output = "",
      errors = "",
      ready = false;
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error(errors || "COV peer startup"));
    }, 5000);
    child.stderr.on("data", (chunk) => {
      errors += String(chunk);
    });
    child.stdout.on("data", (chunk) => {
      output += String(chunk);
      while (output.includes("\n")) {
        const end = output.indexOf("\n"),
          line = output.slice(0, end);
        output = output.slice(end + 1);
        if (!ready) {
          ready = true;
          clearTimeout(timer);
          resolve(Number(line));
        } else if (line === "SENT") complete++;
      }
    });
    child.once("error", reject);
    child.once("exit", (code) => {
      clearTimeout(timer);
      if (!ready) reject(new Error(`COV peer ${code}: ${errors}`));
    });
  });
  return {
    child,
    port,
    send: async (command: string) => {
      const expected = complete + 1;
      child.stdin.write(command + "\n");
      await expect.poll(() => complete).toBe(expected);
    },
  };
}
async function setup(page: Page, request: APIRequestContext) {
  const server = await peer();
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  expect(
    (
      await request.post("/api/bacnet/connect", {
        headers,
        data: { local_address: `127.0.0.1:${await freePort()}` },
      })
    ).ok(),
  ).toBe(true);
  const created = await request.post("/api/bacnet/cov/start", {
    headers,
    data: {
      address: `127.0.0.1:${server.port}`,
      device: "device,4190010",
      object_id: "analog-value,1",
      lifetime: 600,
      confirmed: false,
      record_observations: true,
    },
  });
  expect(created.ok()).toBe(true);
  const job = await created.json();
  await expect
    .poll(
      async () =>
        (await (await request.get(`/api/bacnet/cov/jobs/${job.id}`)).json())
          .received,
    )
    .toBeGreaterThan(0);
  await server.send("numbers");
  await expect
    .poll(
      async () =>
        (await (await request.get(`/api/bacnet/cov/jobs/${job.id}`)).json())
          .recording.recorded,
    )
    .toBeGreaterThanOrEqual(4);
  await page.goto("/");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  const panel = page.getByRole("region", {
    name: "BACnet COV monitoring",
    exact: true,
  });
  const monitor = panel.getByRole("region", {
    name: `COV monitor ${job.id}`,
    exact: true,
  });
  await expect(monitor).toBeVisible();
  return {
    server,
    headers,
    job,
    panel,
    monitor,
    close: async () => {
      await request.post("/api/bacnet/disconnect", { headers, data: {} });
      server.child.kill();
    },
  };
}
async function saved(page: Page, id: string) {
  const region = page.getByRole("region", {
    name: "Saved COV observations",
    exact: true,
  });
  await region
    .getByRole("button", { name: "Load saved COV observations", exact: true })
    .click();
  await region
    .getByLabel("Saved COV recording", { exact: true })
    .selectOption(id);
  return region;
}
async function verify(
  page: Page,
  button: ReturnType<Page["getByRole"]>,
  source: Buffer | (() => Buffer),
  kind: "page" | "job",
) {
  const pending = page.waitForEvent("download");
  await button.click();
  const file = (await (await pending).path())!;
  const reference = test.info().outputPath(kind + "-source.json");
  writeFileSync(reference, typeof source === "function" ? source() : source);
  execFileSync(
    path.join(root, ".venv/bin/python"),
    [
      "-c",
      `
import hashlib,json,math,sys
raw=open(sys.argv[1],'rb').read();original=open(sys.argv[2],'rb').read()
assert raw==original and hashlib.sha256(raw).digest()==hashlib.sha256(original).digest()
report=json.loads(raw)
events=[row['evidence'] for row in report['events'] if row['event']=='notification'] if sys.argv[3]=='page' else report['events']
values=[event['values'][0]['value'] for event in events]
assert all(type(value) is float for value in values)
assert any(value==2.0 for value in values)
assert any(value==0 and math.copysign(1,value)<0 for value in values)
assert any(0<value<1e-6 for value in values) and any(value>=1e20 for value in values)
`,
      file,
      reference,
      kind,
    ],
    { cwd: root },
  );
  writeFileSync(
    test.info().outputPath(kind + "-download.json"),
    readFileSync(file),
  );
}

test("original live job and stored COV page downloads preserve native numbers and bounded page identity", async ({
  page,
  request,
}) => {
  const state = await setup(page, request);
  try {
    let jobBody!: Buffer;
    const jobPath = `**/api/bacnet/cov/jobs/${state.job.id}`;
    await page.route(jobPath, async (route) => {
      const response = await route.fetch();
      jobBody = await response.body();
      await route.fulfill({ response });
    });
    await verify(
      page,
      state.monitor.getByRole("button", {
        name: "Export COV evidence",
        exact: true,
      }),
      () => jobBody,
      "job",
    );
    await page.unroute(jobPath);
    await state.server.send("many");
    await expect
      .poll(
        async () =>
          (
            await (
              await request.get(`/api/bacnet/cov/jobs/${state.job.id}`)
            ).json()
          ).recording.recorded,
      )
      .toBeGreaterThanOrEqual(108);
    let pageBody!: Buffer;
    const pagePath = `**/api/bacnet/cov/recordings/${state.job.id}/page?*`;
    await page.route(pagePath, async (route) => {
      const response = await route.fetch();
      pageBody = await response.body();
      await route.fulfill({ response });
    });
    const region = await saved(page, state.job.id);
    const button = region.getByRole("button", {
      name: "Download saved COV page",
      exact: true,
    });
    await expect(button).toBeEnabled();
    await verify(page, button, pageBody, "page");
    const firstPage = JSON.parse(pageBody.toString());
    expect(firstPage.page.count).toBe(100);
    expect(firstPage.retention.events_retained).toBeGreaterThan(100);
    await region
      .getByRole("button", { name: "Next saved COV page", exact: true })
      .click();
    await expect(button).toBeEnabled();
    expect(JSON.parse(pageBody.toString()).page.after).toBe(
      firstPage.page.last_sequence,
    );
    await region
      .getByRole("button", { name: "Previous saved COV page", exact: true })
      .click();
    await expect(button).toBeEnabled();
    expect(JSON.parse(pageBody.toString()).page.after).toBe(0);
    await region
      .getByLabel("Saved COV recording", { exact: true })
      .selectOption("");
    await expect(button).toHaveCount(0);
  } finally {
    await state.close();
  }
});

test("wrong saved page identities, source, cursor, boundaries, malformed and HTTP failures never retain a download", async ({
  page,
  request,
}) => {
  const state = await setup(page, request);
  try {
    const region = page.getByRole("region", {
      name: "Saved COV observations",
      exact: true,
    });
    await region
      .getByRole("button", { name: "Load saved COV observations", exact: true })
      .click();
    let mode = "monitor";
    const url = `**/api/bacnet/cov/recordings/${state.job.id}/page?*`;
    await page.route(url, async (route) => {
      const response = await route.fetch(),
        data = await response.json();
      if (mode === "http")
        return route.fulfill({
          status: 409,
          json: { detail: "Authored saved page unavailable" },
        });
      if (mode === "json")
        return route.fulfill({
          contentType: "application/json",
          body: '{"broken":',
        });
      if (mode === "wrapper") return route.fulfill({ json: { data } });
      if (mode === "monitor") data.recording.monitor = "unrelated";
      if (mode === "source") data.recording.metadata.config.device = "device,1";
      if (mode === "cursor") data.page.after = 1;
      if (mode === "limit") data.page.limit = 99;
      if (mode === "receipt") data.events[0].source = "cov/unrelated";
      if (mode === "boundary") data.page.last_sequence = 1;
      await route.fulfill({ json: data });
    });
    for (mode of [
      "monitor",
      "source",
      "cursor",
      "limit",
      "receipt",
      "boundary",
      "wrapper",
      "json",
      "http",
    ]) {
      if (mode === "monitor")
        await region
          .getByLabel("Saved COV recording", { exact: true })
          .selectOption(state.job.id);
      else
        await region
          .getByRole("button", {
            name: "Refresh saved COV observations",
            exact: true,
          })
          .click();
      await expect(region.getByRole("alert")).toBeVisible();
      await expect(
        region.getByRole("button", {
          name: "Download saved COV page",
          exact: true,
        }),
      ).toBeDisabled();
    }
  } finally {
    await state.close();
  }
});

for (const kind of ["page", "job"] as const)
  test(`delayed ${kind} evidence cannot download or reappear after navigation`, async ({
    page,
    request,
  }) => {
    const state = await setup(page, request);
    let release = () => {};
    try {
      const downloads: string[] = [];
      page.on("download", (file) => downloads.push(file.suggestedFilename()));
      const held = new Promise<void>((resolve) => {
        release = resolve;
      });
      let entered!: () => void, delivered!: () => void;
      const received = new Promise<void>((resolve) => {
          entered = resolve;
        }),
        completed = new Promise<void>((resolve) => {
          delivered = resolve;
        });
      const url =
        kind === "page"
          ? `**/api/bacnet/cov/recordings/${state.job.id}/page?*`
          : `**/api/bacnet/cov/jobs/${state.job.id}`;
      await page.route(url, async (route) => {
        const response = await route.fetch();
        entered();
        await held;
        await route.fulfill({ response });
        delivered();
      });
      if (kind === "page") await saved(page, state.job.id);
      else
        await state.monitor
          .getByRole("button", { name: "Export COV evidence", exact: true })
          .click();
      await received;
      await page
        .getByRole("button", { name: "Device history", exact: true })
        .click();
      release();
      await completed;
      await page.unroute(url);
      await page.getByRole("button", { name: "Connect", exact: true }).click();
      await expect(
        page.getByRole("button", {
          name: "Load saved COV observations",
          exact: true,
        }),
      ).toBeEnabled();
      expect(downloads).toEqual([]);
      await expect(
        page.getByRole("button", {
          name: "Download saved COV page",
          exact: true,
        }),
      ).toHaveCount(0);
    } finally {
      release();
      await state.close();
    }
  });

test("live job wrong identity, configuration, receipt source and errors suppress evidence export", async ({
  page,
  request,
}) => {
  const state = await setup(page, request);
  try {
    let mode = "id";
    const url = `**/api/bacnet/cov/jobs/${state.job.id}`;
    await page.route(url, async (route) => {
      const response = await route.fetch(),
        data = await response.json();
      if (mode === "http")
        return route.fulfill({
          status: 409,
          json: { detail: "Authored job unavailable" },
        });
      if (mode === "json")
        return route.fulfill({
          contentType: "application/json",
          body: '{"broken":',
        });
      if (mode === "id") data.id = "unrelated";
      if (mode === "config") data.config.object_id = "analog-value,2";
      if (mode === "receipt") data.events[0].source = "192.0.2.1";
      await route.fulfill({ json: data });
    });
    const downloads: string[] = [];
    page.on("download", (file) => downloads.push(file.suggestedFilename()));
    for (mode of ["id", "config", "receipt", "json", "http"]) {
      await state.monitor
        .getByRole("button", { name: "Export COV evidence", exact: true })
        .click();
      await expect(state.panel.getByRole("alert")).toBeVisible();
    }
    expect(downloads).toEqual([]);
  } finally {
    await state.close();
  }
});

test("changing the selected controller suppresses a delayed original-source job export", async ({
  page,
  request,
}) => {
  const state = await setup(page, request);
  let release = () => {};
  try {
    const downloads: string[] = [];
    page.on("download", (file) => downloads.push(file.suggestedFilename()));
    let entered!: () => void, delivered!: () => void;
    const received = new Promise<void>((resolve) => {
      entered = resolve;
    });
    const completed = new Promise<void>((resolve) => {
      delivered = resolve;
    });
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    await page.route(
      `**/api/bacnet/cov/jobs/${state.job.id}`,
      async (route) => {
        const response = await route.fetch();
        entered();
        await held;
        await route.fulfill({ response });
        delivered();
      },
    );
    await state.monitor
      .getByRole("button", { name: "Export COV evidence", exact: true })
      .click();
    await received;
    await page.getByLabel("Unicast target", { exact: true }).fill("127.0.0.2");
    release();
    await completed;
    await expect(
      state.monitor.getByRole("button", {
        name: "Export COV evidence",
        exact: true,
      }),
    ).toBeEnabled();
    expect(downloads).toEqual([]);
    expect(
      (await (await request.get(`/api/bacnet/cov/jobs/${state.job.id}`)).json())
        .config.address,
    ).toBe(`127.0.0.1:${state.server.port}`);
  } finally {
    release();
    await state.close();
  }
});
