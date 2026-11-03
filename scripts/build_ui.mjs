/** Compile a frozen UI snapshot, then publish exact input/output provenance. */
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import crypto from "node:crypto";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const web = path.join(root, "web");
const proofPath = path.join(web, ".bms-ui-build.json");
const profilePath = path.join(root, "scripts/ui_build_profile.json");
const profileInfo = fs.lstatSync(profilePath);
if (
  profileInfo.isSymbolicLink() ||
  !profileInfo.isFile() ||
  profileInfo.size > 65536
)
  throw new Error("Unsupported UI build input profile.");
let profile;
try {
  profile = JSON.parse(fs.readFileSync(profilePath, "utf8"));
} catch {
  throw new Error("Invalid UI build input profile JSON.");
}
const sha = (bytes) => crypto.createHash("sha256").update(bytes).digest("hex");
const compare = (a, b) => Buffer.compare(Buffer.from(a), Buffer.from(b));
function canonical(value) {
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  if (value && typeof value === "object")
    return (
      "{" +
      Object.keys(value)
        .sort(compare)
        .map((key) => JSON.stringify(key) + ":" + canonical(value[key]))
        .join(",") +
      "}"
    );
  return JSON.stringify(value);
}
function relative(name) {
  if (
    typeof name !== "string" ||
    name.length > 1024 ||
    name.includes("\\") ||
    /[\x00-\x1f\x7f]/.test(name) ||
    /^[A-Za-z]:/.test(name) ||
    name.startsWith("/") ||
    name.split("/").some((part) => !part || part === "." || part === "..")
  )
    throw new Error("Unsupported UI build input path.");
  return name;
}
function collectInputs() {
  const files = new Map();
  let total = 0;
  function visit(name, required = true) {
    relative(name);
    const full = path.join(root, name);
    const info = fs.lstatSync(full, { throwIfNoEntry: false });
    if (!info) {
      if (required) throw new Error("Missing UI build input: " + name);
      return;
    }
    if (info.isSymbolicLink())
      throw new Error("UI build inputs must not be symlinks: " + name);
    if (info.isDirectory()) {
      for (const entry of fs.readdirSync(full).sort(compare))
        visit(name + "/" + entry);
      return;
    }
    if (!info.isFile() || info.size > profile.limits.file_bytes)
      throw new Error("Unsupported UI build input: " + name);
    if (files.has(name)) return;
    const bytes = fs.readFileSync(full);
    if (bytes.length > profile.limits.file_bytes)
      throw new Error("UI build input grew beyond its bound: " + name);
    total += bytes.length;
    if (
      files.size >= profile.limits.files ||
      total > profile.limits.input_bytes
    )
      throw new Error("UI build inputs exceed the supported size.");
    files.set(name, bytes);
  }
  for (const name of profile.fixed) visit(name);
  for (const name of profile.trees) visit(name, name === "web/src");
  for (const name of profile.optional) visit(name, false);
  return files;
}
const hashes = (files) =>
  Object.fromEntries(
    [...files]
      .sort(([a], [b]) => compare(a, b))
      .map(([name, bytes]) => [
        name,
        { bytes: bytes.length, sha256: sha(bytes) },
      ]),
  );
function environment() {
  return Object.fromEntries(
    Object.keys(process.env)
      .filter((key) => key === "NODE_ENV" || key.startsWith("VITE_"))
      .sort(compare)
      .map((key) => [key, sha(Buffer.from(process.env[key]))]),
  );
}
function outputs(directory) {
  const result = new Map();
  let total = 0;
  function walk(at, prefix = "") {
    for (const name of fs.readdirSync(at).sort(compare)) {
      const full = path.join(at, name),
        relative = prefix + name,
        info = fs.lstatSync(full);
      if (info.isSymbolicLink())
        throw new Error("Built UI must not contain symlinks.");
      if (info.isDirectory()) {
        walk(full, relative + "/");
        continue;
      }
      if (
        !info.isFile() ||
        info.size > profile.limits.file_bytes ||
        !(
          relative === "index.html" ||
          /^assets\/[^/]+\.(js|css|map|woff|woff2|svg|png)$/.test(relative)
        )
      )
        throw new Error("Unexpected built UI file: " + relative);
      const bytes = fs.readFileSync(full);
      total += bytes.length;
      if (
        bytes.length > profile.limits.file_bytes ||
        total > profile.limits.output_bytes ||
        result.size >= profile.limits.files
      )
        throw new Error("Built UI exceeds the supported size.");
      result.set(relative, bytes);
    }
  }
  walk(directory);
  if (!result.has("index.html"))
    throw new Error("The UI compiler produced no entry page.");
  return hashes(result);
}
function run(script, arguments_, cwd) {
  const result = spawnSync(process.execPath, [script, ...arguments_], {
    cwd,
    env: process.env,
    stdio: "inherit",
  });
  if (result.error) throw result.error;
  if (result.status !== 0)
    throw new Error("UI compiler failed; no build proof was published.");
}

let temporary, publishing, previous;
try {
  if (process.argv.length !== 2)
    throw new Error(
      "The portable UI profile uses npm run build without additional arguments.",
    );
  if (profile.profile !== "bms-ui-build-inputs/1")
    throw new Error("Unknown UI build input profile.");
  const ceilings = {
    files: 4096,
    file_bytes: 16777216,
    input_bytes: 67108864,
    output_bytes: 134217728,
    proof_bytes: 1048576,
  };
  if (
    Object.keys(profile).sort().join() !==
      "fixed,limits,optional,profile,trees" ||
    ![profile.fixed, profile.trees, profile.optional].every(
      (list) =>
        Array.isArray(list) &&
        list.length <= 128 &&
        list.every((value) => typeof value === "string"),
    ) ||
    Object.keys(profile.limits ?? {})
      .sort()
      .join() !== Object.keys(ceilings).sort().join() ||
    !Object.entries(ceilings).every(
      ([key, max]) =>
        Number.isSafeInteger(profile.limits[key]) &&
        profile.limits[key] > 0 &&
        profile.limits[key] <= max,
    )
  )
    throw new Error("Unsupported UI build input profile shape or limits.");
  fs.rmSync(proofPath, { force: true });
  const inputs = collectInputs(),
    inputHashes = hashes(inputs),
    initialEnvironment = environment();
  const lock = JSON.parse(inputs.get("web/package-lock.json").toString("utf8"));
  const tools = { node: process.versions.node };
  for (const name of ["typescript", "vite"]) {
    const version = JSON.parse(
      fs.readFileSync(
        path.join(web, "node_modules", name, "package.json"),
        "utf8",
      ),
    ).version;
    if (version !== lock.packages?.["node_modules/" + name]?.version)
      throw new Error(
        "Installed " + name + " differs from the package lock; run npm ci.",
      );
    tools[name] = version;
  }
  temporary = fs.mkdtempSync(path.join(os.tmpdir(), "bms-ui-build-"));
  for (const [name, bytes] of inputs) {
    const target = path.join(temporary, name);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, bytes);
  }
  const snapshotWeb = path.join(temporary, "web");
  fs.symlinkSync(
    path.join(web, "node_modules"),
    path.join(snapshotWeb, "node_modules"),
    process.platform === "win32" ? "junction" : "dir",
  );
  run(path.join(web, "node_modules/typescript/bin/tsc"), ["-b"], snapshotWeb);
  run(
    path.join(web, "node_modules/vite/bin/vite.js"),
    ["build", "--mode", "production"],
    snapshotWeb,
  );
  const outputHashes = outputs(path.join(snapshotWeb, "dist"));
  if (
    canonical(hashes(collectInputs())) !== canonical(inputHashes) ||
    canonical(environment()) !== canonical(initialEnvironment)
  )
    throw new Error(
      "UI inputs changed during compilation. Rebuild the UI before packaging.",
    );
  const proof = {
    profile: "bms-ui-build-provenance/1",
    input_profile: profile.profile,
    recipe: "snapshot-tsc-vite-production/1",
    mode: "production",
    tools,
    environment: initialEnvironment,
    inputs: inputHashes,
    outputs: outputHashes,
  };
  proof.proof_sha256 = sha(Buffer.from(canonical(proof)));
  const encoded = JSON.stringify(proof, null, 2) + "\n";
  if (Buffer.byteLength(encoded) > profile.limits.proof_bytes)
    throw new Error("UI build proof exceeds its bound.");
  const token = crypto.randomUUID();
  publishing = path.join(web, ".bms-ui-dist-" + token);
  fs.cpSync(path.join(snapshotWeb, "dist"), publishing, { recursive: true });
  if (canonical(outputs(publishing)) !== canonical(outputHashes))
    throw new Error("Published UI bytes differ from the compiled snapshot.");
  const temporaryProof = path.join(web, ".bms-ui-proof-" + token);
  const dist = path.join(web, "dist");
  let replaced = false;
  try {
    fs.writeFileSync(temporaryProof, encoded, { flag: "wx", mode: 0o600 });
    if (fs.existsSync(dist)) {
      previous = path.join(web, ".bms-ui-previous-" + token);
      fs.renameSync(dist, previous);
    }
    fs.renameSync(publishing, dist);
    publishing = undefined;
    replaced = true;
    fs.renameSync(temporaryProof, proofPath);
  } catch (error) {
    if (replaced) fs.rmSync(dist, { recursive: true, force: true });
    if (previous) {
      fs.renameSync(previous, dist);
      previous = undefined;
    }
    throw error;
  } finally {
    fs.rmSync(temporaryProof, { force: true });
  }
  console.log(
    "UI input/output proof recorded for " +
      Object.keys(inputHashes).length +
      " inputs and " +
      Object.keys(outputHashes).length +
      " assets.",
  );
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
} finally {
  for (const directory of [temporary, publishing, previous])
    if (directory) fs.rmSync(directory, { recursive: true, force: true });
}
