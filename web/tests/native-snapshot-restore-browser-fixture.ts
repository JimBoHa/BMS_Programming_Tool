import {
  test as base,
  expect,
  type Page,
  type APIRequestContext,
} from "./nativeScheduleWriteFixture";
import { nativeDefaultPeer } from "./native-default-peer";
import { freePort } from "./workflow-peer";
import { python } from "./native-connection-fixture";
import {
  chooseWorkspaceTask,
  chooseWorkspaceTool,
  openNativeCompiler,
} from "./workspace-navigation";
export const nativeBase = "/api/bacnet/controller/native-application";
export const restoreBase = nativeBase + "/application-restore";
export async function seedSnapshot(
  request: APIRequestContext,
  peer: any,
  routed: boolean,
) {
  const headers = {
    Connection: "close",
    "X-Studio-Token": (
      await (
        await request.get("/api/session", { headers: { Connection: "close" } })
      ).json()
    ).token,
  };
  async function post(path: string, data: any) {
    const r = await request.post(path, { headers, data });
    expect(r.ok(), `${path}: ${await r.text()}`).toBe(true);
    return r.json();
  }
  const target = {
    address: routed ? "3001:7" : peer.direct,
    device: "device,5136",
    router: routed ? peer.router : null,
    dnet: routed ? 3001 : null,
  };
  await post("/api/bacnet/connect", {
    local_address: `127.0.0.1:${await freePort()}`,
    instance: 4190001,
    router: target.router,
    dnet: target.dnet,
  });
  await post(nativeBase + "/credentials", {
    backup: "authored-backup",
    restore: "authored-restore",
  });
  const original = await post(nativeBase + "/capture", {
    ...target,
    operation_id: "seed-retained-application",
  });
  await peer.command("snapshot-current");
  return { original, target, headers };
}
export function snapshotFixture(routed = false) {
  return base.extend<{
    snapshot: {
      peer: Awaited<ReturnType<typeof nativeDefaultPeer>>;
      seeded: Awaited<ReturnType<typeof seedSnapshot>>;
    };
  }>({
    snapshot: [
      async ({ request }, use) => {
        const peer = await nativeDefaultPeer("consume", "application-restore");
        try {
          await use({
            peer,
            seeded: await seedSnapshot(request, peer, routed),
          });
        } finally {
          peer.close();
        }
      },
      { timeout: 30000 },
    ],
  });
}
export async function openSnapshot(
  page: Page,
  seeded: any,
  caf = false,
  connect = true,
) {
  await page.goto("/");
  if (caf) {
    const bytes = python(
      "from tests.test_caf_graph import make_graph;import base64;print(base64.b64encode(make_graph()).decode())",
    ).trim();
    await page
      .getByLabel("Open local CAF application", { exact: true })
      .setInputFiles({
        name: "retained-restore-local.caf",
        mimeType: "application/octet-stream",
        buffer: Buffer.from(bytes, "base64"),
      });
    await expect(
      page.getByLabel("Current CAF archive", { exact: true }),
    ).toHaveText("retained-restore-local.caf");
  } else
    await page
      .getByRole("button", { name: "New application", exact: true })
      .click();
  await chooseWorkspaceTask(page, "Program");
  await chooseWorkspaceTool(page, "Graph editor");
  await page
    .getByLabel("Program name", { exact: true })
    .fill("Preserved retained-restore local graph");
  if (connect) {
    await page.getByRole("button", { name: "Connect", exact: true }).click();
    await page
      .getByRole("button", { name: "Known controller address", exact: true })
      .click();
    await page
      .getByLabel("Known controller address", { exact: true })
      .fill(seeded.target.address);
    await page
      .getByLabel("Known Device object", { exact: true })
      .fill(seeded.target.device);
    await page
      .getByLabel("Known router", { exact: true })
      .fill(seeded.target.router || "");
    await page
      .getByLabel("Known network", { exact: true })
      .fill(seeded.target.dnet?.toString() || "");
    await page
      .getByRole("region", { name: "Known controller connection", exact: true })
      .getByRole("button", { name: "Open controller", exact: true })
      .click();
    await expect(
      page.getByRole("region", { name: "Controller overview", exact: true }),
    ).toContainText("Authored controller");
  }
  await openNativeCompiler(page);
  const compiler = page.getByRole("region", {
    name: "Native backup default compiler",
    exact: true,
  });
  await compiler
    .getByLabel("Retained native backup", { exact: true })
    .selectOption(seeded.original.id);
  const inspection = compiler.getByRole("region", {
    name: "Retained native backup inspection",
    exact: true,
  });
  await inspection
    .getByRole("button", {
      name: "Inspect retained native backup",
      exact: true,
    })
    .click();
  await inspection
    .getByText("Restore a retained application", { exact: true })
    .click();
  const panel = inspection.getByRole("region", {
    name: "Retained native application restore",
    exact: true,
  });
  await panel
    .getByRole("button", {
      name: "Inspect retained restore image",
      exact: true,
    })
    .click();
  await expect(panel).toContainText(
    "Reconstructed historical image: 3 native records",
  );
  return { compiler, inspection, panel };
}
export async function reviewSnapshot(page: Page, panel: any, keyboard = false) {
  await panel
    .getByRole("button", {
      name: "Review retained application restore",
      exact: true,
    })
    .click();
  const reviewed = panel.getByRole("region", {
    name: "Reviewed retained application restore",
    exact: true,
  });
  await expect(reviewed).toBeVisible();
  const apply = panel.getByRole("button", {
    name: "Apply retained application to controller",
    exact: true,
  });
  await expect(apply).toBeDisabled();
  if (keyboard) {
    await reviewed.getByRole("checkbox").nth(0).focus();
    await page.keyboard.press("Space");
  } else await reviewed.getByRole("checkbox").nth(0).check();
  await expect(apply).toBeDisabled();
  if (keyboard) {
    await reviewed.getByRole("checkbox").nth(1).focus();
    await page.keyboard.press("Space");
  } else await reviewed.getByRole("checkbox").nth(1).check();
  await expect(apply).toBeEnabled();
  return { reviewed, apply };
}
