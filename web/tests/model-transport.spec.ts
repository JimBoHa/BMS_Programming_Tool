import {
  chooseWorkspaceTask,
  chooseWorkspaceTool,
} from "./workspace-navigation";
import { test, expect } from "./modelTransportFixture";
import { readFileSync } from "node:fs";
import type { Locator, Page } from "@playwright/test";

const rootRegion = (page: Page) =>
  page.getByRole("region", {
    name: "Controller hardware and input survey",
    exact: true,
  });
async function openHardwareSurvey(page: Page) {
  await chooseWorkspaceTask(page, "Points & I/O");
  await chooseWorkspaceTool(page, "Hardware survey", "Controller task tools");
}
async function open(page: Page, peer: any, routed = false) {
  await page.goto("/");
  await page.getByRole("button", { name: /^Connect to a controller/ }).click();
  return selectController(page, peer, routed);
}
async function changeController(page: Page, peer: any) {
  await page
    .getByLabel("Working context")
    .getByRole("button", { name: "Change controller", exact: true })
    .click();
  return selectController(page, peer, false);
}
async function selectController(page: Page, peer: any, routed: boolean) {
  await page
    .getByRole("button", { name: "Known controller address", exact: true })
    .click();
  const form = page.getByRole("region", {
    name: "Known controller connection",
  });
  await form
    .getByLabel("Known controller address", { exact: true })
    .fill(routed ? "3001:7" : peer.address);
  await form
    .getByLabel("Known Device object", { exact: true })
    .fill(peer.device);
  await form
    .getByLabel("Known router", { exact: true })
    .fill(routed ? peer.router : "");
  await form
    .getByLabel("Known network", { exact: true })
    .fill(routed ? "3001" : "");
  const [response] = await Promise.all([
    page.waitForResponse(
      (r) => new URL(r.url()).pathname === "/api/bacnet/device-details",
    ),
    form.getByRole("button", { name: "Open controller", exact: true }).click(),
  ]);
  expect(response.ok(), await response.text()).toBe(true);
  const identity = await response.json();
  expect(identity.identity_verified, JSON.stringify(identity.errors)).toBe(
    true,
  );
  const overview = page.getByRole("region", { name: "Controller overview" });
  await expect(overview).toContainText(identity.properties["object-name"]);
  await expect(overview).toContainText(peer.device);
  const inventory = page.waitForResponse((r) =>
    r.url().endsWith("/api/bacnet/controller/inventory"),
  );
  await openHardwareSurvey(page);
  expect(await (await inventory).json()).toMatchObject({
    identity_verified: true,
    target: {
      address: routed ? "3001:7" : peer.address,
      device: peer.device,
      router: routed ? peer.router : null,
      dnet: routed ? 3001 : null,
    },
  });
  await peer.selectionComplete();
  const panel = rootRegion(page);
  await expect(
    panel.getByLabel("Hardware controller address", { exact: true }),
  ).toHaveCount(0);
  return panel;
}
async function enable(
  panel: Locator,
  model = "MS-FAC4911-0",
  protocol = "bacnet-ip",
) {
  await panel
    .getByLabel("Qualify this hardware read by exact model and protocol", {
      exact: true,
    })
    .check();
  await panel
    .getByRole("button", {
      name: "Load or refresh model transport profile",
      exact: true,
    })
    .click();
  await panel
    .getByLabel("Declared complete controller model", { exact: true })
    .fill(model);
  await panel
    .getByLabel("Declared current controller protocol", { exact: true })
    .selectOption(protocol);
}
async function preview(panel: Locator, admitted = true) {
  await panel
    .getByRole("button", {
      name: "Preview model-qualified target",
      exact: true,
    })
    .click();
  await expect(
    panel.getByLabel("Model target review", { exact: true }),
  ).toContainText(
    admitted
      ? "Model-qualified read admitted"
      : "Model-qualified read not admitted",
  );
  await expect(
    panel.getByRole("button", {
      name: "Survey controller inputs",
      exact: true,
    }),
  ).toBeEnabled({ enabled: admitted });
}
async function survey(
  page: Page,
  panel: Locator,
  peer: any,
  qualified: boolean,
) {
  peer.expectReads();
  const sent = page.waitForRequest(
    (r) => new URL(r.url()).pathname === "/api/bacnet/hardware/survey",
  );
  await panel
    .getByRole("button", { name: "Survey controller inputs", exact: true })
    .click();
  const payload = (await sent).postDataJSON();
  expect("model_qualification" in payload).toBe(qualified);
  await expect(panel.getByText(/^Survey complete\. Results/)).toBeVisible();
  return payload;
}

test("qualification stays off by default and original generic survey sends no new field", async ({
  page,
  modelPeer,
}) => {
  const peer = await modelPeer(),
    panel = await open(page, peer);
  const profiles: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes("model-transport")) profiles.push(r.url());
  });
  await expect(
    panel.getByLabel("Qualify this hardware read by exact model and protocol", {
      exact: true,
    }),
  ).not.toBeChecked();
  await survey(page, panel, peer, false);
  expect(profiles).toEqual([]);
  await expect(
    panel.getByLabel("Owned job model transport evidence", { exact: true }),
  ).toHaveCount(0);
});

test("native IP declaration previews locally then reads actual UDP and exports original owned job bytes", async ({
  page,
  request,
  modelPeer,
}, info) => {
  const peer = await modelPeer(),
    panel = await open(page, peer);
  await enable(panel);
  await preview(panel);
  await expect(
    panel.getByLabel("Documented controller capability", { exact: true }),
  ).toContainText("bacnet-ip, bacnet-sc");
  const payload = await survey(page, panel, peer, true);
  expect(payload.model_qualification.model).toBe("MS-FAC4911-0");
  const evidence = panel.getByLabel("Owned job model transport evidence", {
    exact: true,
  });
  await expect(evidence).toContainText("exact_text_match");
  await expect(evidence).toContainText("native compatibility unverified");
  const status = await (
      await request.get("/api/bacnet/hardware/status")
    ).json(),
    id = status.jobs.at(-1).id;
  const original = Buffer.from(
    await (await request.get(`/api/bacnet/hardware/jobs/${id}/export`)).body(),
  );
  await panel
    .getByLabel("Saved hardware job", { exact: true })
    .selectOption(id);
  const download = page.waitForEvent("download");
  await panel
    .getByRole("button", { name: "Download hardware job JSON", exact: true })
    .click();
  const downloaded = readFileSync((await (await download).path())!);
  expect(downloaded).toEqual(original);
  await info.attach("original-server-job-export.json", {
    body: original,
    contentType: "application/json",
  });
  await info.attach("original-browser-job-download.json", {
    body: downloaded,
    contentType: "application/json",
  });
  const job = JSON.parse(original.toString()),
    saved = await (
      await request.get(`/api/bacnet/hardware/reports/${job.report_id}`)
    ).json();
  expect(saved.profile).toBe("bacnet-hardware-survey/1");
  expect(saved).not.toHaveProperty("model_transport_admission");
});

test("routed MS/TP controller retains distinct IP router and one-octet downstream identity", async ({
  page,
  modelPeer,
}) => {
  const peer = await modelPeer("MS-FAC2611-0", true),
    panel = await open(page, peer, true);
  await enable(panel, "MS-FAC2611-0", "bacnet-mstp");
  await preview(panel);
  await expect(
    panel.getByLabel("Model target review", { exact: true }),
  ).toContainText(`via router ${peer.router}`);
  const payload = await survey(page, panel, peer, true);
  expect(payload.transport).toBe("bacnet-ip");
  expect(payload.address).toBe("3001:7");
  expect(payload.router).toBe(peer.router);
  await expect(
    panel.getByLabel("Owned job model transport evidence", { exact: true }),
  ).toContainText("path routed-explicit");
});

test("short observed native model text remains unresolved and is never promoted to declared exact part", async ({
  page,
  modelPeer,
}) => {
  const peer = await modelPeer("FAC4911"),
    panel = await open(page, peer);
  await enable(panel);
  await preview(panel);
  await survey(page, panel, peer, true);
  const evidence = panel.getByLabel("Owned job model transport evidence", {
    exact: true,
  });
  await expect(evidence).toContainText("Operator declaration: MS-FAC4911-0");
  await expect(evidence).toContainText("Observed model text: FAC4911");
  await expect(evidence).toContainText("different_text_unresolved");
});

for (const protocol of ["bacnet-sc", "n2"])
  test(`${protocol} is explicitly unavailable and pure preview sends no native reads`, async ({
    page,
    modelPeer,
  }) => {
    const peer = await modelPeer(),
      panel = await open(page, peer);
    await enable(
      panel,
      protocol === "n2" ? "MS-FAC2611-0" : "MS-FAC4911-0",
      protocol,
    );
    await preview(panel, false);
    await expect(
      panel.getByLabel("Selected protocol adapter", { exact: true }),
    ).toContainText("unavailable");
    await expect(
      panel.getByLabel("Model target review", { exact: true }),
    ).toContainText("adapter_unavailable");
  });

test("unknown exact part and unknown current mode remain unresolved including prototype-shaped labels", async ({
  page,
  modelPeer,
}) => {
  const peer = await modelPeer(),
    panel = await open(page, peer);
  await enable(panel, "__proto__", "unknown");
  await preview(panel, false);
  await expect(
    panel.getByLabel("Documented controller capability", { exact: true }),
  ).toContainText("Unknown exact part");
  await expect(
    panel.getByLabel("Model target review", { exact: true }),
  ).toContainText("unresolved_current_protocol");
});

test("native MS/TP declaration cannot silently become a direct native IP controller", async ({
  page,
  modelPeer,
}) => {
  const peer = await modelPeer(),
    panel = await open(page, peer);
  await enable(panel, "MS-FAC2611-0", "bacnet-mstp");
  await preview(panel, false);
  await expect(
    panel.getByLabel("Model target review", { exact: true }),
  ).toContainText("native_mstp_requires_explicit_path");
});

test("model protocol target and explicit discard each retire read admission", async ({
  page,
  modelPeer,
}) => {
  const peer = await modelPeer(),
    panel = await open(page, peer);
  await enable(panel);
  await preview(panel);
  await panel
    .getByLabel("Declared complete controller model", { exact: true })
    .fill("MS-FAC2611-0");
  await expect(
    panel.getByLabel("Model target review", { exact: true }),
  ).toHaveCount(0);
  await expect(
    panel.getByRole("button", {
      name: "Survey controller inputs",
      exact: true,
    }),
  ).toBeDisabled();
  await panel
    .getByLabel("Declared complete controller model", { exact: true })
    .fill("MS-FAC4911-0");
  await preview(panel);
  await panel
    .getByLabel("Declared current controller protocol", { exact: true })
    .selectOption("unknown");
  await expect(
    panel.getByRole("button", {
      name: "Survey controller inputs",
      exact: true,
    }),
  ).toBeDisabled();
  await panel
    .getByLabel("Declared current controller protocol", { exact: true })
    .selectOption("bacnet-ip");
  await preview(panel);
  await changeController(page, await modelPeer());
  await expect(
    panel.getByLabel("Model target review", { exact: true }),
  ).toHaveCount(0);
  await enable(panel);
  await preview(panel);
  await panel
    .getByRole("button", { name: "Discard model target preview", exact: true })
    .click();
  await expect(
    panel.getByRole("button", {
      name: "Survey controller inputs",
      exact: true,
    }),
  ).toBeDisabled();
});

for (const leave of ["target", "unmount"])
  test(`held pure preview cannot restore admission after ${leave}`, async ({
    page,
    modelPeer,
  }) => {
    const peer = await modelPeer(),
      panel = await open(page, peer);
    await enable(panel);
    let release!: () => void, arrived!: () => void;
    const gate = new Promise<void>((r) => (release = r)),
      seen = new Promise<void>((r) => (arrived = r));
    await page.route(
      "**/api/bacnet/hardware/model-transport/review",
      async (route) => {
        const response = await route.fetch();
        arrived();
        await gate;
        await route.fulfill({ response });
      },
    );
    await panel
      .getByRole("button", {
        name: "Preview model-qualified target",
        exact: true,
      })
      .click();
    await seen;
    if (leave === "target") await changeController(page, await modelPeer());
    else
      await chooseWorkspaceTool(
        page,
        "Detailed point evidence",
        "Controller task tools",
      );
    release();
    await page.unrouteAll({ behavior: "wait" });
    if (leave === "unmount")
      await chooseWorkspaceTool(
        page,
        "Hardware survey",
        "Controller task tools",
      );
    await expect(
      rootRegion(page).getByLabel("Model target review", { exact: true }),
    ).toHaveCount(0);
    if (leave === "target") await enable(panel);
    if (leave === "target")
      await expect(
        panel.getByRole("button", {
          name: "Survey controller inputs",
          exact: true,
        }),
      ).toBeDisabled();
  });

test("refreshing a changed open interface retires the prior model review", async ({
  page,
  request,
  modelPeer,
}) => {
  const peer = await modelPeer(),
    panel = await open(page, peer);
  await enable(panel);
  await preview(panel);
  const refreshInterface = async (connected: boolean) => {
    const pending = page.waitForResponse((r) =>
      r.url().endsWith("/api/bacnet/status"),
    );
    await page
      .getByRole("button", { name: "Refresh interface status", exact: true })
      .click();
    expect(await (await pending).json()).toMatchObject({ connected });
  };
  await refreshInterface(true);
  await expect(
    panel.getByLabel("Model target review", { exact: true }),
  ).toContainText("Model-qualified read admitted");
  const response = await request.post("/api/bacnet/disconnect", {
    headers: { "X-Studio-Token": peer.token },
    data: {},
  });
  expect(response.ok()).toBe(true);
  await refreshInterface(false);
  await expect(
    panel.getByLabel("Model target review", { exact: true }),
  ).toHaveCount(0);
  await expect(
    panel.getByRole("button", {
      name: "Survey controller inputs",
      exact: true,
    }),
  ).toBeDisabled();
});

test("unsupported or altered source profile never enables a model review", async ({
  page,
  modelPeer,
}) => {
  const peer = await modelPeer(),
    panel = await open(page, peer);
  await page.route(
    "**/api/bacnet/hardware/model-transport/profile",
    async (route) => {
      const response = await route.fetch(),
        body = await response.json();
      body.profile.models["MS-FAC4911-0"].native_protocols.push("bacnet-mstp");
      await route.fulfill({ response, json: body });
    },
  );
  await panel
    .getByLabel("Qualify this hardware read by exact model and protocol", {
      exact: true,
    })
    .check();
  await panel
    .getByRole("button", {
      name: "Load or refresh model transport profile",
      exact: true,
    })
    .click();
  await expect(panel.getByRole("alert")).toContainText(
    "Unsupported or altered",
  );
  await expect(
    panel.getByRole("button", {
      name: "Survey controller inputs",
      exact: true,
    }),
  ).toBeDisabled();
});

for (const corruption of ["target", "profile", "false-admit"])
  test(`malformed ${corruption} review cannot authorize a qualified survey`, async ({
    page,
    modelPeer,
  }) => {
    const peer = await modelPeer(),
      panel = await open(page, peer);
    await enable(
      panel,
      corruption === "false-admit" ? "MS-FAC2611-0" : "MS-FAC4911-0",
      corruption === "false-admit" ? "n2" : "bacnet-ip",
    );
    await page.route(
      "**/api/bacnet/hardware/model-transport/review",
      async (route) => {
        const response = await route.fetch(),
          body = await response.json();
        if (corruption === "target") body.target.device = "device,1";
        if (corruption === "profile") body.profile_sha256 = "0".repeat(64);
        if (corruption === "false-admit") {
          body.dispatch_admitted = true;
          body.findings = [];
        }
        await route.fulfill({ response, json: body });
      },
    );
    await panel
      .getByRole("button", {
        name: "Preview model-qualified target",
        exact: true,
      })
      .click();
    await expect(panel.getByRole("alert")).toContainText(
      corruption === "false-admit" ? "incorrectly admits" : "does not match",
    );
    await expect(
      panel.getByRole("button", {
        name: "Survey controller inputs",
        exact: true,
      }),
    ).toBeDisabled();
  });
