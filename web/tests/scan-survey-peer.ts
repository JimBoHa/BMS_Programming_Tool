import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import path from "node:path";

const root = path.resolve("..");
export type Observation = { service: string; object: string; property: string };
export type PeerState = {
  event: string;
  requests: Observation[];
  errors: string[];
  name_entered?: boolean;
  value?: number;
};
type Identity = {
  port: number;
  client_port: number;
  instance: number;
  name: string;
  sensor: string;
  first: number;
  second: number;
};

/** Own the existing fixture application; its JSON pipe controls test data only. */
export async function scanSurveyPeer() {
  const child = spawn(
    path.join(root, ".venv/bin/python"),
    ["-u", "-m", "tests.browser_scan_survey_peer"],
    {
      cwd: root,
      env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
      stdio: ["pipe", "pipe", "pipe"],
    },
  );
  let stderr = "",
    exited = false;
  child.stderr.on("data", (data) => {
    stderr += data.toString();
  });
  child.stdin.on("error", (error) => {
    stderr += String(error);
    for (const waiter of waiters.splice(0)) waiter.reject(error);
  });
  const messages: any[] = [],
    waiters: {
      resolve: (data: any) => void;
      reject: (reason: unknown) => void;
    }[] = [];
  const output = createInterface({ input: child.stdout });
  output.on("line", (line) => {
    try {
      const data = JSON.parse(line),
        waiter = waiters.shift();
      if (waiter) waiter.resolve(data);
      else messages.push(data);
    } catch (error) {
      for (const waiter of waiters.splice(0)) waiter.reject(error);
    }
  });
  const exit = new Promise<number | null>((resolve) =>
    child.once("exit", (code) => {
      exited = true;
      for (const waiter of waiters.splice(0))
        waiter.reject(new Error(`Peer exited ${code}: ${stderr}`));
      resolve(code);
    }),
  );
  child.once("error", (error) => {
    for (const waiter of waiters.splice(0)) waiter.reject(error);
  });
  async function next() {
    if (messages.length) return messages.shift();
    if (exited) throw new Error("Peer stopped: " + stderr);
    return new Promise<any>((resolve, reject) => {
      const waiter = {
        resolve: (data: any) => {
          clearTimeout(timer);
          resolve(data);
        },
        reject: (error: unknown) => {
          clearTimeout(timer);
          reject(error);
        },
      };
      const timer = setTimeout(() => {
        const index = waiters.indexOf(waiter);
        if (index >= 0) waiters.splice(index, 1);
        reject(new Error("Peer control deadline: " + stderr));
      }, 10000);
      waiters.push(waiter);
    });
  }
  let ready: any;
  try {
    ready = await next();
  } catch (error) {
    child.kill("SIGTERM");
    output.close();
    throw error;
  }
  if (ready.event !== "ready")
    throw new Error("Unexpected peer startup: " + JSON.stringify(ready));
  return {
    identity: ready as Identity,
    async control(command: Record<string, unknown> = {}) {
      const result = next();
      child.stdin.write(JSON.stringify(command) + "\n");
      const state = (await result) as PeerState;
      if (state.event !== "state")
        throw new Error(
          "Unexpected peer control response: " + JSON.stringify(state),
        );
      return state;
    },
    async close() {
      if (exited) throw new Error(`Peer already stopped: ${stderr}`);
      const deadline = setTimeout(() => child.kill("SIGTERM"), 3000);
      try {
        const stopped = next();
        child.stdin.end(JSON.stringify({ operation: "stop" }) + "\n");
        const state = (await stopped) as PeerState;
        const code = await exit;
        if (code !== 0 || state.event !== "stopped" || state.errors.length)
          throw new Error(
            `Peer shutdown ${code}: ${JSON.stringify(state)} ${stderr}`,
          );
        return state;
      } finally {
        clearTimeout(deadline);
        output.close();
        if (!exited) child.kill("SIGTERM");
      }
    },
  };
}
