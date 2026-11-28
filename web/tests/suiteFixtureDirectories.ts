import { test } from "@playwright/test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

/** Each suite owns the directories holding its authored fixture inputs. */
export function suiteFixtureDirectories() {
  const directories = new Set<string>();
  test.afterAll(() => {
    for (const directory of directories) {
      rmSync(directory, { recursive: true, force: true, maxRetries: 3 });
      directories.delete(directory);
    }
  });
  return (prefix: string) => {
    const directory = mkdtempSync(join(tmpdir(), prefix));
    directories.add(directory);
    return directory;
  };
}
