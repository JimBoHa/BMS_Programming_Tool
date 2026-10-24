import { test, expect } from "@playwright/test";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { cleanupPeers, retirePeer } from "./modelTransportCleanup";

async function child(code: string) {
  const process = spawn(globalThis.process.execPath, ["-e", code], {
    stdio: ["pipe", "pipe", "pipe"],
  });
  await once(process, "spawn");
  return process;
}
const cooperative =
  "process.stdin.once('data',()=>process.exit(0));process.stdin.resume()";
const stubborn = "setInterval(()=>{},1000)";

test("owned peer ordinary stdin shutdown records actual reaped zero exit", async () => {
  const peer = await child(cooperative),
    result = await retirePeer(peer, 1000, 1000);
  expect(result).toMatchObject({
    reaped: true,
    normal_stdin_shutdown: true,
    forced: false,
    exit_code: 0,
    signal: null,
  });
  expect(result.errors).toEqual([]);
});
test("already signaled child is recognized without waiting for an event that already fired", async () => {
  const peer = await child(stubborn),
    exit = once(peer, "exit");
  peer.kill("SIGTERM");
  await exit;
  const result = await retirePeer(peer, 30, 300);
  expect(result).toMatchObject({
    already_exited: true,
    reaped: true,
    normal_stdin_shutdown: false,
    signal: "SIGTERM",
  });
  expect(result.errors).toContain("child terminated by SIGTERM");
});
test("already exited normal child does not receive another stdin or signal request", async () => {
  const peer = await child("process.exit(0)");
  await once(peer, "exit");
  const result = await retirePeer(peer, 30, 300);
  expect(result).toMatchObject({
    already_exited: true,
    reaped: true,
    normal_stdin_shutdown: false,
    forced: false,
    exit_code: 0,
  });
});
test("closed stdin still receives bounded owned-only escalation and actual exit confirmation", async () => {
  const peer = await child(stubborn);
  peer.stdin.destroy();
  const result = await retirePeer(peer, 30, 1000);
  expect(result).toMatchObject({
    reaped: true,
    forced: true,
    signal: "SIGKILL",
  });
  expect(result.errors).toContain("stdin is already closed");
});
test("synchronous stdin failure cannot skip escalation or reaping", async () => {
  const peer = await child(stubborn);
  peer.stdin.end = (() => {
    throw new Error("authored stdin failure");
  }) as typeof peer.stdin.end;
  const result = await retirePeer(peer, 30, 1000);
  expect(result.reaped && result.forced).toBe(true);
  expect(result.errors).toContain("stdin: authored stdin failure");
});
test("evidence failure for first peer preserves later peer retirement and disconnect", async () => {
  const first = await child(cooperative),
    second = await child(cooperative),
    inspected: number[] = [];
  let disconnected = false,
    failure: any;
  try {
    await cleanupPeers(
      [{ child: first }, { child: second }],
      async (peer, result) => {
        inspected.push(peer.child.pid!);
        expect(result.reaped).toBe(true);
        if (peer.child === first)
          throw new Error("authored post-proof failure");
      },
      async () => {
        disconnected = true;
      },
    );
  } catch (error) {
    failure = error;
  }
  expect(failure).toBeInstanceOf(AggregateError);
  expect(inspected).toEqual([first.pid, second.pid]);
  expect(first.exitCode).toBe(0);
  expect(second.exitCode).toBe(0);
  expect(disconnected).toBe(true);
  expect(failure.errors[0].message).toContain("post-proof failure");
});
test("already signaled first peer and disconnect failure are both retained after later peer cleanup", async () => {
  const first = await child(stubborn),
    exit = once(first, "exit");
  first.kill("SIGTERM");
  await exit;
  const second = await child(cooperative),
    inspected: number[] = [];
  let failure: any;
  try {
    await cleanupPeers(
      [{ child: first }, { child: second }],
      async (peer) => {
        inspected.push(peer.child.pid!);
      },
      async () => {
        throw new Error("authored disconnect failure");
      },
    );
  } catch (error) {
    failure = error;
  }
  expect(inspected).toEqual([first.pid, second.pid]);
  expect(second.exitCode).toBe(0);
  expect(
    failure.errors.map((error: Error) => error.message).join("; "),
  ).toContain("SIGTERM");
  expect(
    failure.errors.map((error: Error) => error.message).join("; "),
  ).toContain("disconnect failure");
});
