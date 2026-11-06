/** Retain verbatim runtime dependency licenses from the committed npm lock. */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const lock = JSON.parse(
  fs.readFileSync(path.join(root, "web/package-lock.json"), "utf8"),
);
let output =
  "BMS Studio browser dependency notices\n\nGenerated from web/package-lock.json. Runtime and accompanying type package\nlicenses are retained verbatim; this file grants no vendor affiliation.\n";
for (const [name, record] of Object.entries(lock.packages)) {
  if (!name || record.dev) continue;
  const folder = path.join(root, "web", name);
  const files = fs
    .readdirSync(folder)
    .filter((name) => /^(licen[sc]e|copying|notice)(\.|$)/i.test(name))
    .sort();
  if (!files.length) throw new Error("Missing dependency license: " + name);
  output +=
    "\n" +
    "=".repeat(72) +
    "\n" +
    name.replace(/^node_modules\//, "") +
    " " +
    record.version +
    " (" +
    record.license +
    ")\n";
  for (const name of files)
    output +=
      "\n" +
      name +
      "\n\n" +
      fs.readFileSync(path.join(folder, name), "utf8") +
      "\n";
}
const target = path.join(root, "third_party/web-NOTICES.txt");
output = output.trimEnd() + "\n";
if (process.argv.includes("--check")) {
  if (fs.readFileSync(target, "utf8") !== output)
    throw new Error(
      "Browser dependency notices are stale; regenerate and review them.",
    );
} else {
  fs.writeFileSync(target, output);
}
