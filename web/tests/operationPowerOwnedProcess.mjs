import { existsSync, readFileSync, rmSync, writeFileSync } from "node:fs";

const information = (error) => ({
  name: error instanceof Error ? error.name : typeof error,
  message: error instanceof Error ? error.message : String(error),
  stack: error instanceof Error ? error.stack : null,
});
const bounded = (promise, milliseconds, message) => {
  let timer;
  return Promise.race([
    promise,
    new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(message)), milliseconds);
    }),
  ]).finally(() => clearTimeout(timer));
};
async function reap(child, graceMilliseconds, killMilliseconds) {
  const result = {
    pid: child.pid ?? null,
    graceful_requested: false,
    forced_owned_only: false,
    exited: false,
    code: child.exitCode,
    signal: child.signalCode,
  };
  if (!child.pid || child.exitCode !== null || child.signalCode !== null)
    return { ...result, exited: true };
  const exit = new Promise((resolve) =>
    child.once("exit", (code, signal) => resolve({ code, signal })),
  );
  result.graceful_requested = true;
  child.kill("SIGTERM");
  try {
    Object.assign(
      result,
      await bounded(
        exit,
        graceMilliseconds,
        "Owned fixture graceful stop exceeded its bound",
      ),
    );
  } catch {
    result.forced_owned_only = true;
    child.kill("SIGKILL");
    Object.assign(
      result,
      await bounded(
        exit,
        killMilliseconds,
        "Owned fixture could not be reaped after its own SIGKILL",
      ),
    );
  }
  result.exited = true;
  return result;
}

/** Call immediately after spawn. Client creation and every later await belong
 * inside body; disposal failure never bypasses owned process retirement.
 */
export async function withOwnedPowerProcess(options, body) {
  const { child, state, identity, output, dispose } = options;
  let primary,
    hasPrimary = false;
  try {
    return await body();
  } catch (error) {
    primary = error;
    hasPrimary = true;
    throw error;
  } finally {
    const errors = [];
    let retirement = null,
      post = null,
      logCaptured = false,
      stateRemoved = false;
    try {
      await bounded(
        Promise.resolve().then(dispose),
        options.disposeMilliseconds ?? 3000,
        "Owned fixture client disposal exceeded its bound",
      );
    } catch (error) {
      errors.push(error);
    }
    try {
      retirement = await reap(
        child,
        options.graceMilliseconds ?? 5000,
        options.killMilliseconds ?? 3000,
      );
      if (retirement.forced_owned_only)
        errors.push(
          new Error(
            "Owned fixture required SIGKILL; graceful cleanup is unconfirmed",
          ),
        );
    } catch (error) {
      errors.push(error);
    }
    const exited =
      !child.pid || child.exitCode !== null || child.signalCode !== null;
    try {
      if (!existsSync(identity + ".post.json"))
        throw new Error("Owned fixture post-shutdown proof is missing");
      post = JSON.parse(readFileSync(identity + ".post.json", "utf8"));
      if (post.status !== "passed" || post.stage !== "post_shutdown")
        throw new Error("Owned fixture post-shutdown proof failed");
    } catch (error) {
      errors.push(error);
    }
    try {
      writeFileSync(identity + ".server.log", output(), { flag: "wx" });
      logCaptured = true;
    } catch (error) {
      errors.push(error);
    }
    if (exited && logCaptured) {
      try {
        rmSync(state, { recursive: true, force: true });
        stateRemoved = true;
      } catch (error) {
        errors.push(error);
      }
    }
    const evidence = {
      status: hasPrimary || errors.length ? "failed" : "passed",
      metadata: options.metadata ?? null,
      primary: hasPrimary ? information(primary) : null,
      cleanup_errors: errors.map(information),
      retirement,
      exited,
      post_proof: post,
      server_log_captured: logCaptured,
      state_removed: stateRemoved,
      retained_state_path: stateRemoved ? null : state,
      qualification:
        "Only the exact spawned test fixture process is signalled. Original startup/post proofs remain unchanged; a missing or failed post proof is a failure.",
    };
    try {
      writeFileSync(
        identity + ".lifecycle.json",
        JSON.stringify(evidence, null, 2) + "\n",
        { flag: "wx" },
      );
    } catch (error) {
      errors.push(error);
    }
    if (errors.length)
      throw new AggregateError(
        hasPrimary ? [primary, ...errors] : errors,
        "Owned power fixture primary/cleanup failures",
        hasPrimary ? { cause: primary } : undefined,
      );
  }
}
