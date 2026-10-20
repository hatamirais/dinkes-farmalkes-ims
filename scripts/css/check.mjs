import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "../..");
const source = path.join(root, "backend/static_src/css/app.css");
const committed = path.join(root, "backend/static/css/app.tailwind.css");
const temporaryDirectory = fs.mkdtempSync(path.join(root, ".css-check-"));
const rebuilt = path.join(temporaryDirectory, "app.tailwind.css");

try {
  const result = spawnSync(
    process.execPath,
    [path.join(root, "node_modules/@tailwindcss/cli/dist/index.mjs"), "-i", source, "-o", rebuilt, "--minify"],
    { cwd: root, stdio: "inherit" },
  );
  if (result.error) throw result.error;
  if (result.status !== 0) {
    process.exitCode = result.status ?? 1;
  } else if (!fs.existsSync(committed) || !fs.readFileSync(committed).equals(fs.readFileSync(rebuilt))) {
    console.error("Generated CSS is stale. Run bun run css:build and commit backend/static/css/app.tailwind.css.");
    process.exitCode = 1;
  } else {
    console.log("Generated CSS matches the committed output.");
  }
} finally {
  fs.rmSync(temporaryDirectory, { recursive: true, force: true });
}
