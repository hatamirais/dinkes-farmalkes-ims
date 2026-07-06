import path from "node:path";
import { spawn } from "node:child_process";
import { loadLocalConfig, listRoleCodes } from "./common.mjs";

loadLocalConfig();

const repoRoot = path.resolve(import.meta.dirname, "..", "..");
const windowScript = path.join(import.meta.dirname, "window.mjs");
const positions = {
  PUSKESMAS: { x: 40, y: 40 },
  GUDANG: { x: 120, y: 110 },
  KEPALA: { x: 200, y: 180 },
  ADMIN: { x: 280, y: 250 },
};

for (const roleCode of listRoleCodes()) {
  const position = positions[roleCode];
  spawn(process.execPath, [windowScript, roleCode, String(position.x), String(position.y)], {
    cwd: repoRoot,
    detached: true,
    stdio: "ignore",
    windowsHide: true,
  }).unref();
}

process.stdout.write("Launching Playwright role windows in the background.\n");
