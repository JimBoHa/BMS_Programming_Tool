import { defineConfig } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
const stateDirectory =
  process.env.BMS_TEST_COMPILER_STATE ||
  mkdtempSync(join(tmpdir(), "bms-studio-e2e-"));
process.env.BMS_TEST_COMPILER_STATE = stateDirectory;
export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 30000,
  use: {
    baseURL: "http://127.0.0.1:8766",
    viewport: { width: 1440, height: 1000 },
    trace: "retain-on-failure",
  },
  webServer: {
    command: "../.venv/bin/python -m bms_tool serve --port 8766",
    env: { BMS_STUDIO_DATA: stateDirectory },
    url: "http://127.0.0.1:8766/api/session",
    reuseExistingServer: false,
    timeout: 20000,
  },
});
