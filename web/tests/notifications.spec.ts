import { test, expect } from "./simulationFixture";
import { spawn, execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";

const root = path.resolve("..");
async function receiver(fail = false) {
  const child = spawn(
    path.join(root, ".venv/bin/python"),
    [
      "-u",
      "-c",
      `
import json,sys
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
messages=[]
class Handler(BaseHTTPRequestHandler):
    failed=sys.argv[1]=='fail'
    def log_message(self,*args): pass
    def do_GET(self):
        data=json.dumps(messages).encode()
        self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def do_POST(self):
        raw=self.rfile.read(int(self.headers['Content-Length']))
        if self.path=='/control':
            Handler.failed=False;self.send_response(204);self.end_headers();return
        messages.append({'raw':raw.decode(),'headers':{key.lower():value for key,value in self.headers.items()}})
        self.send_response(400 if Handler.failed else 204);self.end_headers()
server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
print(server.server_port,flush=True)
server.serve_forever()
`,
      fail ? "fail" : "ok",
    ],
    { cwd: root, stdio: ["ignore", "pipe", "pipe"] },
  );
  const port = await new Promise<number>((resolve, reject) => {
    let output = "",
      errors = "",
      ready = false;
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error("Local receiver startup: " + errors));
    }, 5000);
    child.stdout.on("data", (chunk) => {
      output += chunk.toString();
      if (!ready && output.includes("\n")) {
        ready = true;
        clearTimeout(timer);
        resolve(Number(output.split("\n")[0]));
      }
    });
    child.stderr.on("data", (chunk) => {
      errors += chunk.toString();
    });
    child.on("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
    child.on("exit", (code) => {
      clearTimeout(timer);
      if (!ready) reject(new Error(`Local receiver exited ${code}: ${errors}`));
    });
  });
  return { child, url: `http://127.0.0.1:${port}` };
}
const program = () =>
  JSON.parse(
    execFileSync(
      path.join(root, ".venv/bin/python"),
      [
        "-c",
        "from tests.test_observation_api import alarm_program; import json; print(json.dumps(alarm_program()))",
      ],
      { cwd: root, encoding: "utf8" },
    ),
  );

for (const failed of [false, true]) {
  test(`alarm webhook ${failed ? "failed receipt retries the same evidence" : "background receipt retains source evidence without acknowledging alarm"}`, async ({
    page,
    request,
  }) => {
    const sink = await receiver(failed);
    const headers = {
      "X-Studio-Token": (await (await request.get("/api/session")).json())
        .token,
    };
    let routeId = "",
      source = "";
    try {
      await page.goto("/");
      await page
        .getByRole("button", { name: "Alarm delivery", exact: true })
        .click();
      await expect(
        page.getByRole("region", {
          name: "Create alarm delivery route",
          exact: true,
        }),
      ).toBeVisible();
      const name = failed ? "Local retry receiver" : "Local alarm receiver";
      await page.getByLabel("Alarm route name", { exact: true }).fill(name);
      await page
        .getByLabel("Alarm webhook URL", { exact: true })
        .fill(sink.url + "/alarms");
      const created = page.waitForResponse(
        (response) =>
          response.url().endsWith("/api/notifications/routes") &&
          response.request().method() === "POST",
      );
      await page
        .getByRole("button", { name: "Save paused alarm route", exact: true })
        .click();
      const route = await (await created).json();
      routeId = route.id;
      expect(route.enabled).toBe(false);
      await expect(
        page.getByRole("button", { name: `Start route ${name}`, exact: true }),
      ).toBeEnabled();
      expect(await (await request.get(sink.url + "/messages")).json()).toEqual(
        [],
      );
      await page
        .getByLabel("Delivery route filter", { exact: true })
        .selectOption(routeId);
      await page
        .getByRole("button", { name: `Start route ${name}`, exact: true })
        .click();
      const simulation = await request.post("/api/simulation/step", {
        headers,
        data: {
          program: program(),
          inputs: { temperature: 90 },
          record: true,
          clock: "2026-01-05T00:00:00Z",
        },
      });
      expect(simulation.ok()).toBeTruthy();
      source = (await simulation.json()).recording_source;
      const records = page.getByRole("region", {
        name: "Alarm delivery records",
        exact: true,
      });
      const rows = records.locator("tbody tr");
      await expect(rows).toHaveCount(1, { timeout: 10000 });
      await expect(rows.nth(0)).toContainText(failed ? "failed" : "delivered", {
        timeout: 10000,
      });
      const before = await (await request.get(sink.url + "/messages")).json();
      expect(before).toHaveLength(1);
      const payload = JSON.parse(before[0].raw);
      expect(payload.source_kind).toBe("simulation");
      expect(payload.event.source).toBe(source);
      expect(payload.event.clock).toBe("2026-01-05T00:00:00.000000+00:00");
      expect(payload.event.event).toBe("activated");
      if (failed) {
        await request.post(sink.url + "/control", { data: {} });
        await page
          .getByLabel("Delivery action note", { exact: true })
          .fill("Receiver configuration fixed; retry recorded evidence.");
        await rows
          .nth(0)
          .getByRole("button", { name: /^Retry delivery / })
          .click();
        await expect(rows.nth(0)).toContainText("delivered", {
          timeout: 10000,
        });
        const retried = await (
          await request.get(sink.url + "/messages")
        ).json();
        expect(retried).toHaveLength(2);
        expect(retried[1].raw).toBe(before[0].raw);
        expect(retried[1].headers["idempotency-key"]).toBe(
          before[0].headers["idempotency-key"],
        );
      }
      const download = page.waitForEvent("download");
      await rows
        .nth(0)
        .getByRole("button", { name: /^Download delivery / })
        .click();
      const evidence = JSON.parse(
        readFileSync((await (await download).path())!, "utf8"),
      );
      expect(evidence.payload).toEqual(payload);
      expect(evidence.payload_integrity).toBe(true);
      expect(evidence.state).toBe("delivered");
      const alarms = await (
        await request.get(
          "/api/observations/alarms?source=" + encodeURIComponent(source),
        )
      ).json();
      expect(alarms[0].acknowledged).toBe(false);
      await page
        .getByRole("button", { name: `Pause route ${name}`, exact: true })
        .click();
      await expect(
        page.getByRole("button", { name: `Start route ${name}`, exact: true }),
      ).toBeEnabled();
      await page.screenshot({
        path: `test-results/studio-alarm-delivery${failed ? "-retry" : ""}.png`,
        fullPage: true,
      });
    } finally {
      try {
        if (routeId)
          expect(
            (
              await request.post("/api/notifications/routes/enable", {
                headers,
                data: { route_id: routeId, enabled: false },
              })
            ).ok(),
          ).toBeTruthy();
        // Retire only this test's source after verifying unchanged alarm state.
        // Other browser workflows share this isolated server's observation store.
        if (source) {
          expect(
            (
              await request.post("/api/observations/end", {
                headers,
                data: { source, note: "Local webhook test completed." },
              })
            ).ok(),
          ).toBeTruthy();
          const alarms = await (
            await request.get(
              "/api/observations/alarms?source=" + encodeURIComponent(source),
            )
          ).json();
          for (const alarm of alarms)
            if (!alarm.acknowledged)
              expect(
                (
                  await request.post("/api/observations/acknowledge", {
                    headers,
                    data: {
                      alarm_id: alarm.id,
                      note: "Verified local test evidence before cleanup.",
                    },
                  })
                ).ok(),
              ).toBeTruthy();
          expect(
            (
              await request.post("/api/observations/retire", {
                headers,
                data: { source },
              })
            ).ok(),
          ).toBeTruthy();
        }
      } finally {
        sink.child.kill();
      }
    }
  });
}
