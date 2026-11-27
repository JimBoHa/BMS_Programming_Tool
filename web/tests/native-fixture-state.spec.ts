import { existsSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { test, expect } from "./nativeScheduleWriteFixture";

let ownedDirectory: string;
let siblingFile: string;

test("the native write server keeps its database in this test's result directory", async ({
  nativeScheduleWriteServer,
  request,
}, info) => {
  const { directory, url } = nativeScheduleWriteServer;
  expect(path.dirname(directory)).toBe(info.outputDir);
  expect((await request.get(url + "/api/session")).ok()).toBe(true);
  expect(existsSync(path.join(directory, "studio.sqlite3"))).toBe(true);
  siblingFile = info.outputPath("separate-evidence.txt");
  writeFileSync(siblingFile, "retained", { flag: "wx" });
  ownedDirectory = directory;
});

test.afterAll(() => {
  if (ownedDirectory) {
    expect(existsSync(ownedDirectory)).toBe(false);
    expect(readFileSync(siblingFile, "utf8")).toBe("retained");
  }
});
