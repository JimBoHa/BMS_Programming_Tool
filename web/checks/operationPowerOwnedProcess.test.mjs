// Run with node --test web/checks/operationPowerOwnedProcess.test.mjs.
// These real child-process faults use Node timers, never an OS power provider.
import test from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, mkdirSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { withOwnedPowerProcess } from "../tests/operationPowerOwnedProcess.mjs";

const evidence =
  process.env.BMS_POWER_FIXTURE_FAULT_DIR ||
  mkdtempSync(path.join(tmpdir(), "bms-power-fault-evidence-"));
mkdirSync(evidence, { recursive: true });
function server(name, mode = "passed") {
  const state = mkdtempSync(path.join(tmpdir(), "bms-power-fault-state-")),
    identity = path.join(evidence, name + ".json");
  const child = spawn(
    process.execPath,
    [
      "-e",
      `
const fs=require('node:fs');const mode=process.env.MODE;
process.on('SIGTERM',()=>{if(mode==='stubborn')return;fs.writeFileSync(process.env.POST,JSON.stringify({status:mode,stage:'post_shutdown',error:mode==='failed'?'Deliberate failed post proof':null}));process.exit(0)});
console.log('ready');setInterval(()=>{},1000);`,
    ],
    {
      cwd: state,
      env: { ...process.env, MODE: mode, POST: identity + ".post.json" },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  let output = "";
  const ready = new Promise((resolve, reject) => {
    const timer = setTimeout(
      () => reject(new Error("Fault child startup timeout")),
      1000,
    );
    child.stdout.on("data", (bytes) => {
      output += String(bytes);
      if (output.includes("ready")) {
        clearTimeout(timer);
        resolve();
      }
    });
    child.once("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
  });
  child.stderr.on("data", (bytes) => (output += String(bytes)));
  return {
    child,
    state,
    identity,
    ready,
    options: {
      child,
      state,
      identity,
      output: () => output,
      dispose: async () => {},
      graceMilliseconds: 1000,
      killMilliseconds: 1000,
    },
    proof: () => JSON.parse(readFileSync(identity + ".lifecycle.json", "utf8")),
  };
}
function retired(s) {
  const proof = s.proof();
  assert.equal(proof.exited, true);
  assert.equal(proof.server_log_captured, true);
  assert.equal(proof.state_removed, true);
  assert.equal(existsSync(s.state), false);
  assert.notEqual(s.child.exitCode ?? s.child.signalCode, null);
  return proof;
}
test("context-creation primary failure is preserved while the owned child closes and reaps", async () => {
  const s = server("context-failure"),
    primary = new Error("Context creation refused");
  await assert.rejects(
    withOwnedPowerProcess(s.options, async () => {
      await s.ready;
      await Promise.reject(primary);
    }),
    (error) => error === primary,
  );
  const proof = retired(s);
  assert.equal(proof.primary.message, primary.message);
  assert.equal(proof.post_proof.status, "passed");
  assert.equal(proof.retirement.forced_owned_only, false);
});
test("disposal exception does not skip child shutdown or replace its retained cleanup evidence", async () => {
  const s = server("dispose-failure"),
    failure = new Error("Client disposal refused");
  await assert.rejects(
    withOwnedPowerProcess(
      {
        ...s.options,
        dispose: async () => {
          throw failure;
        },
      },
      async () => {
        await s.ready;
      },
    ),
    (error) =>
      error instanceof AggregateError && error.errors.includes(failure),
  );
  const proof = retired(s);
  assert.equal(proof.post_proof.status, "passed");
  assert.equal(proof.cleanup_errors[0].message, failure.message);
});
test("bounded disposal timeout still retires the owned process", async () => {
  const s = server("dispose-timeout");
  await assert.rejects(
    withOwnedPowerProcess(
      {
        ...s.options,
        disposeMilliseconds: 25,
        dispose: () => new Promise(() => {}),
      },
      async () => {
        await s.ready;
      },
    ),
    AggregateError,
  );
  assert.match(retired(s).cleanup_errors[0].message, /disposal exceeded/);
});
test("stubborn owned child alone is killed/reaped and missing post proof remains a failure", async () => {
  const sibling = server("unrelated-sibling"),
    s = server("stubborn-missing-post", "stubborn");
  try {
    await assert.rejects(
      withOwnedPowerProcess(
        { ...s.options, graceMilliseconds: 25 },
        async () => {
          await Promise.all([s.ready, sibling.ready]);
        },
      ),
      AggregateError,
    );
    const proof = retired(s);
    assert.equal(proof.retirement.forced_owned_only, true);
    assert.equal(proof.retirement.signal, "SIGKILL");
    assert.equal(proof.post_proof, null);
    assert.ok(
      proof.cleanup_errors.some((error) =>
        /proof is missing/.test(error.message),
      ),
    );
    assert.equal(sibling.child.exitCode, null);
    assert.equal(sibling.child.signalCode, null);
    process.kill(sibling.child.pid, 0);
  } finally {
    await withOwnedPowerProcess(sibling.options, async () => {
      await sibling.ready;
    });
    retired(sibling);
  }
});
test("failed post proof is retained unchanged and cannot become a green lifecycle", async () => {
  const s = server("failed-post", "failed");
  await assert.rejects(
    withOwnedPowerProcess(s.options, async () => {
      await s.ready;
    }),
    AggregateError,
  );
  const original = JSON.parse(readFileSync(s.identity + ".post.json", "utf8")),
    proof = retired(s);
  assert.equal(original.status, "failed");
  assert.deepEqual(proof.post_proof, original);
  assert.equal(proof.status, "failed");
});
