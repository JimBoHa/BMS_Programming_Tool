import { expect, type APIRequestContext, type Page } from "@playwright/test";
import { python } from "./native-connection-fixture";
import { nativeDefaultPeer } from "./native-default-peer";
import { freePort } from "./workflow-peer";
import { chooseWorkspaceTask } from "./workspace-navigation";

const base = "/api/bacnet/controller/native-application";
export function fieldDocuments(directory: string) {
  return JSON.parse(
    python(
      `
import asyncio,base64,json,sys
from contextlib import aclosing
from pathlib import Path
import pytest
from tests.test_native_applications import native_link
from tests.test_native_terminal_transfer_guards import configured_peer
from tests.test_native_terminal_input import terminal_edit
from tests.test_native_input_transfer import preview
from bms_tool.native_inputs import NativeInputCompiler
from bms_tool.moi_identity import seal
async def main():
 with pytest.MonkeyPatch.context() as patch:
  async with aclosing(native_link.__wrapped__(Path(sys.argv[1]),patch)) as generator:
   link=await anext(generator);peer,service=configured_peer(link);edit=terminal_edit(NativeInputCompiler(peer.files))
   capture,plan=await preview(link,edit,'client-document')
   q={'capture_id':capture['id'],'snapshot_sha256':capture['snapshot_evidence_sha256']}
   source=service.input_source(**q);local_output,local=service.input_copy(**q,edit=edit)
   exact={'values':[1.0,-0.0,0.10000000149011612,1e-7,9007199254740993], '10':'ten','2':'two','\\ue000':'private range','🙂':'astral','name':'é🙂'}
   exact['review_sha256']=seal(exact)
   print(json.dumps({'source':source,'edit':plan['input_edit'],'field_text':json.dumps(plan,ensure_ascii=False),'local_text':json.dumps(local,ensure_ascii=False),'local_output':base64.b64encode(local_output).decode(),'exact_text':json.dumps(exact,ensure_ascii=False)}))
asyncio.run(main())
`,
      directory,
    ),
  );
}

export async function allocatedPeer(request: APIRequestContext) {
  const peer = await nativeDefaultPeer("consume", "input");
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  const post = async (path: string, data: any) => {
    const r = await request.post(path, { headers, data });
    expect(r.ok(), await r.text()).toBe(true);
    return r.json();
  };
  try {
    await post(base + "/credentials", {
      backup: "authored-backup",
      restore: "authored-restore",
    });
    await post("/api/bacnet/connect", {
      local_address: `127.0.0.1:${await freePort()}`,
    });
    const target = {
      address: peer.direct,
      device: "device,5136",
      router: null,
      dnet: null,
    };
    const capture = await post(base + "/capture", {
      ...target,
      operation_id: "seed-terminal-capture",
    });
    const review = await post(base + "/input/preview", {
      ...target,
      capture_id: capture.id,
      snapshot_sha256: capture.snapshot_evidence_sha256,
      operation_id: "seed-terminal-input",
      edit: {
        action: "allocate",
        object_instance: 3000010,
        slot: 1,
        name: "Existing authored analog input",
        configuration: {
          mode: "voltage",
          input_low: 0,
          input_high: 10,
          output_low: 0,
          output_high: 100,
          units: 98,
          minimum: 0,
          maximum: 100,
        },
      },
    });
    const result = await post(base + "/input/apply", {
      operation_id: "seed-terminal-apply",
      token: review.token,
      review_sha256: review.review_sha256,
      physical_wiring_confirmed: true,
      input_change_confirmed: true,
      application_transfer_confirmed: true,
    });
    expect(result.result.status).toBe("verified");
    await post("/api/bacnet/disconnect", {});
    return peer;
  } catch (error) {
    peer.close();
    throw error;
  }
}

export async function openFieldInputs(
  page: Page,
  peer: { direct: string; router: string },
  routed = false,
) {
  await page.route("**/api/bacnet/controller/inventory", (route) =>
    route.fulfill({
      json: {
        identity_verified: true,
        complete: true,
        target: route.request().postDataJSON(),
        offset: 0,
        total: 0,
        next_offset: null,
        objects: [],
        errors: [],
      },
    }),
  );
  await page.goto("/");
  await page.getByRole("button", { name: /^Connect to a controller/ }).click();
  await page
    .getByLabel("Local bind address / UDP port", { exact: true })
    .fill(`127.0.0.1:${await freePort()}`);
  await page
    .getByRole("button", { name: "Open interface", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Known controller address", exact: true })
    .click();
  await page
    .getByLabel("Known controller address", { exact: true })
    .fill(routed ? "3001:7" : peer.direct);
  await page
    .getByLabel("Known Device object", { exact: true })
    .fill("device,5136");
  await page
    .getByLabel("Known router", { exact: true })
    .fill(routed ? peer.router : "");
  await page
    .getByLabel("Known network", { exact: true })
    .fill(routed ? "3001" : "");
  await page
    .getByRole("region", { name: "Known controller connection", exact: true })
    .getByRole("button", { name: "Open controller", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Controller overview", exact: true }),
  ).toContainText("Authored controller");
  await chooseWorkspaceTask(page, "Points & I/O");
  await page
    .getByRole("button", { name: "Configure native inputs", exact: true })
    .click();
  const inputs = page.getByRole("region", {
    name: "Native input configuration",
    exact: true,
  });
  await inputs
    .getByRole("button", { name: "Capture native inputs", exact: true })
    .click();
  await expect(
    inputs.getByLabel("Native input object instance", { exact: true }),
  ).toBeVisible();
  await expect(
    inputs.getByRole("button", { name: "Capture native inputs", exact: true }),
  ).toBeEnabled();
  await inputs
    .getByLabel("Input operation", { exact: true })
    .selectOption("terminal");
  await inputs
    .getByLabel("Configured native input", { exact: true })
    .selectOption("analog-input,3000010");
  await inputs
    .getByLabel("Field terminal destination", { exact: true })
    .selectOption("3");
  return inputs;
}
