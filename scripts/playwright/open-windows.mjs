import path from "node:path";
import { spawn } from "node:child_process";
import { ROLE_DEFINITIONS, loadLocalConfig } from "./common.mjs";

loadLocalConfig();

const repoRoot = path.resolve(import.meta.dirname, "..", "..");
const windowScript = path.join(import.meta.dirname, "window.mjs");
const positions = [
  { x: 40, y: 40 },
  { x: 140, y: 100 },
  { x: 240, y: 160 },
  { x: 340, y: 220 },
  { x: 440, y: 280 },
  { x: 540, y: 340 },
];

ROLE_DEFINITIONS.forEach((role, index) => {
  const position = positions[index] ?? { x: 40 + index * 60, y: 40 + index * 60 };
  spawn(process.execPath, [windowScript, role.code, String(position.x), String(position.y)], {
    cwd: repoRoot,
    detached: true,
    stdio: "ignore",
    windowsHide: true,
  }).unref();
});

process.stdout.write(`Launching ${ROLE_DEFINITIONS.length} Playwright role windows in the background.\n`);
