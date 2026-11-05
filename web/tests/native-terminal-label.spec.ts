import { test, expect } from "./nativeScheduleWriteFixture";
import { readFileSync } from "node:fs";
import { seedTerminalLabels } from "./native-terminal-label-fixture";
import { enterTerminals, reviewTerminal } from "./native-terminal-fixture";
import { chooseWorkspaceTask } from "./workspace-navigation";

for (const binary of [false, true])
  for (const effective of [false, true])
    test(`${binary ? "binary" : "analog"} ${effective ? "effective" : "archive"} UCS-2 copy downloads exact native bytes in contextual workflow`, async ({
      page,
      nativeScheduleWriteServer,
    }) => {
      const f = seedTerminalLabels(nativeScheduleWriteServer.directory, binary),
        editor = await enterTerminals(page, f.id, effective);
      await editor
        .getByLabel("Input to reassign")
        .selectOption(`controller/${binary ? 3 : 0}_101`);
      await editor
        .getByLabel("Destination universal terminal")
        .selectOption("3");
      let raw = Buffer.alloc(0);
      await page.route(
        "**/inputs/encoded-labels/*terminal-copy/preview",
        async (route) => {
          const response = await route.fetch();
          raw = await response.body();
          await route.fulfill({ response, body: raw });
        },
      );
      const review = await reviewTerminal(editor),
        v = JSON.parse(raw.toString()),
        proof = effective ? v.compilation.terminal_edit : v.compilation;
      expect(proof.profile).toBe("tagged-moi-local-terminal-copy/3");
      expect(proof.device_type_character_encoding).toBe(4);
      expect(proof.device_type_encoding_preserved).toBe(true);
      await expect(review).toContainText(
        `${binary ? "binary" : "analog"}-input,101: UI IN1 to UI IN3`,
      );
      const original = page.waitForEvent("download");
      await review
        .getByRole("button", { name: "Save terminal review", exact: true })
        .click();
      expect(readFileSync((await (await original).path())!)).toEqual(raw);
      const download = page.waitForEvent("download");
      await review
        .getByRole("button", { name: "Save native terminal copy", exact: true })
        .click();
      expect(readFileSync((await (await download).path())!)).toEqual(
        Buffer.from(f[effective ? "effective" : "archive"].output, "base64"),
      );
      await expect(editor).toContainText(
        "Saved a local native copy. No controller was changed.",
      );
      await chooseWorkspaceTask(page, "Overview");
      await chooseWorkspaceTask(page, "Points & I/O");
      await editor.locator(":scope > summary").click();
      await expect(editor.getByLabel("Input to reassign")).toHaveValue(
        `controller/${binary ? 3 : 0}_101`,
      );
      await expect(
        editor.getByLabel("Destination universal terminal"),
      ).toHaveValue("3");
      await expect(
        editor.getByRole("region", {
          name: "Reviewed local terminal copy",
          exact: true,
        }),
      ).toHaveCount(0);
    });

test("a UTF-16 label converted to ASCII is rejected before saving", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seedTerminalLabels(nativeScheduleWriteServer.directory),
    editor = await enterTerminals(page, f.id);
  await editor.getByLabel("Input to reassign").selectOption("controller/3_101");
  await editor.getByLabel("Destination universal terminal").selectOption("3");
  await page.route(
    "**/inputs/encoded-labels/terminal-copy/preview",
    async (route) => {
      const response = await route.fetch(),
        v = await response.json();
      v.compilation.payloads[1].after = "00554920494e33";
      await route.fulfill({ response, json: v });
    },
  );
  await editor
    .getByRole("button", { name: "Review local terminal copy", exact: true })
    .click();
  await expect(editor.getByRole("alert")).toContainText(
    "does not match this input",
  );
  await expect(
    editor.getByRole("button", {
      name: "Save native terminal copy",
      exact: true,
    }),
  ).toHaveCount(0);
});

test("late exact-document digest cannot restore a retired local review", async ({
  page,
  nativeScheduleWriteServer,
}) => {
  const f = seedTerminalLabels(nativeScheduleWriteServer.directory),
    editor = await enterTerminals(page, f.id);
  await editor.getByLabel("Input to reassign").selectOption("controller/3_101");
  await editor.getByLabel("Destination universal terminal").selectOption("3");
  await page.evaluate(() => {
    const w = window as any,
      original = crypto.subtle.digest.bind(crypto.subtle);
    w.localLabelWaiting = [];
    w.localLabelDelay = true;
    w.localLabelDone = 0;
    crypto.subtle.digest = async (algorithm: any, value: any) => {
      const tracked = new TextDecoder()
        .decode(value)
        .includes("tagged-moi-local-terminal-copy/3");
      if (tracked && w.localLabelDelay)
        await new Promise<void>((r) => w.localLabelWaiting.push(r));
      const result = await original(algorithm, value);
      if (tracked) w.localLabelDone++;
      return result;
    };
  });
  await editor
    .getByRole("button", { name: "Review local terminal copy", exact: true })
    .click();
  await page.waitForFunction(
    () => (window as any).localLabelWaiting.length > 0,
  );
  await page.evaluate(() => {
    const w = window as any;
    window.dispatchEvent(new Event("pagehide"));
    w.localLabelDelay = false;
    w.localLabelWaiting.splice(0).forEach((r: any) => r());
  });
  await page.waitForFunction(() => (window as any).localLabelDone >= 2);
  await editor.locator(":scope > summary").click();
  await expect(
    editor.getByRole("button", {
      name: "Review local terminal copy",
      exact: true,
    }),
  ).toBeEnabled();
  await expect(
    editor.getByRole("region", {
      name: "Reviewed local terminal copy",
      exact: true,
    }),
  ).toHaveCount(0);
  await expect(
    editor.getByRole("button", {
      name: "Save native terminal copy",
      exact: true,
    }),
  ).toHaveCount(0);
});
