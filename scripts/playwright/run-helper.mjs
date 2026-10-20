import { spawnSync } from "node:child_process";
import path from "node:path";

// Playwright's persistent Chromium launch hangs under Bun 1.3.14 on Windows.
// Bun owns package installation and command entry; these browser helpers use
// Playwright's supported Node runtime until that compatibility issue is fixed.
const commands = {
  auth: ["auth.mjs"],
  "refresh-auth": ["auth.mjs", "--refresh"],
  open: ["open-windows.mjs"],
};

const args = commands[process.argv[2]];
if (!args) {
  throw new Error("Expected auth, refresh-auth, or open.");
}

const [script, ...scriptArgs] = args;
const result = spawnSync(
  "node",
  [path.join(import.meta.dirname, script), ...scriptArgs],
  { stdio: "inherit" },
);

if (result.error) {
  throw result.error;
}
process.exit(result.status ?? 1);
