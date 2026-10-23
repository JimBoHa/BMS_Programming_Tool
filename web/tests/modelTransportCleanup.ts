import type { ChildProcessWithoutNullStreams } from "node:child_process";

export type PeerRetirement = {
  pid: number | null;
  process_started: boolean;
  exit_code: number | null;
  signal: string | null;
  reaped: boolean;
  already_exited: boolean;
  normal_stdin_shutdown: boolean;
  forced: boolean;
  errors: string[];
};
function message(error: unknown): string {
  return error instanceof AggregateError
    ? `${error.message}: ${error.errors.map(message).join("; ")}`
    : error instanceof Error
      ? error.message
      : String(error);
}
const ended = (child: ChildProcessWithoutNullStreams) =>
  child.exitCode !== null || child.signalCode !== null;
async function waitForExit(
  child: ChildProcessWithoutNullStreams,
  milliseconds: number,
) {
  if (ended(child)) return true;
  return new Promise<boolean>((resolve) => {
    let timer: ReturnType<typeof setTimeout>;
    const finish = (exited: boolean) => {
      clearTimeout(timer);
      child.removeListener("exit", onExit);
      resolve(exited);
    };
    const onExit = () => finish(true);
    child.once("exit", onExit);
    timer = setTimeout(() => finish(ended(child)), milliseconds);
    if (ended(child)) finish(true); // Close the listener-registration race.
  });
}

/** Never throws: each owned process receives its own bounded retirement. */
export async function retirePeer(
  child: ChildProcessWithoutNullStreams,
  graceMs = 3000,
  reapMs = 1000,
): Promise<PeerRetirement> {
  const errors: string[] = [],
    alreadyExited = ended(child),
    started = child.pid !== undefined;
  let requested = false,
    forced = false;
  // Keep an error listener through stream closure; a late EPIPE is never unhandled.
  child.stdin.on("error", (error) => errors.push("stdin: " + message(error)));
  if (started && !alreadyExited) {
    try {
      if (!child.stdin.writable || child.stdin.destroyed)
        errors.push("stdin is already closed");
      else {
        requested = true;
        child.stdin.end("close\n");
      }
    } catch (error) {
      errors.push("stdin: " + message(error));
    }
    if (!(await waitForExit(child, graceMs))) {
      forced = true;
      errors.push("graceful shutdown deadline exceeded");
      try {
        child.kill("SIGKILL");
      } catch (error) {
        errors.push("kill: " + message(error));
      }
      if (!(await waitForExit(child, reapMs)))
        errors.push(
          "owned child exit remains unconfirmed after bounded escalation",
        );
    }
  }
  if (child.signalCode !== null)
    errors.push("child terminated by " + child.signalCode);
  else if (child.exitCode !== null && child.exitCode !== 0)
    errors.push("child exited " + child.exitCode);
  if (!started) errors.push("owned child never started");
  return {
    pid: child.pid ?? null,
    process_started: started,
    exit_code: child.exitCode,
    signal: child.signalCode,
    reaped: started && ended(child),
    already_exited: alreadyExited,
    normal_stdin_shutdown:
      requested && child.exitCode === 0 && child.signalCode === null && !forced,
    forced,
    errors: [...new Set(errors)],
  };
}

/** Fail only after all children, evidence callbacks and final disconnect ran. */
export async function cleanupPeers<
  T extends { child: ChildProcessWithoutNullStreams },
>(
  peers: T[],
  inspect: (peer: T, retirement: PeerRetirement) => Promise<void>,
  disconnect: () => Promise<void>,
  stop = retirePeer,
) {
  const errors: Error[] = [];
  for (const peer of peers) {
    try {
      const retirement = await stop(peer.child);
      errors.push(
        ...retirement.errors.map(
          (error) => new Error(`peer ${retirement.pid}: ${error}`),
        ),
      );
      try {
        await inspect(peer, retirement);
      } catch (error) {
        errors.push(new Error("peer evidence: " + message(error)));
      }
    } catch (error) {
      errors.push(new Error("peer retirement: " + message(error)));
    }
  }
  try {
    await disconnect();
  } catch (error) {
    errors.push(new Error("disconnect: " + message(error)));
  }
  if (errors.length)
    throw new AggregateError(
      errors,
      "Owned peer cleanup/evidence failures (all peers and disconnect attempted)",
    );
}
