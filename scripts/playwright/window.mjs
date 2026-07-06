import { launchRoleContext } from "./common.mjs";

const roleCode = process.argv[2];
if (!roleCode) {
  throw new Error("Missing role code. Usage: node scripts/playwright/window.mjs <ROLE_CODE> [x] [y]");
}

const x = Number(process.argv[3]);
const y = Number(process.argv[4]);
const windowPosition = Number.isFinite(x) && Number.isFinite(y) ? { x, y } : undefined;

const { context, role, targetUrl } = await launchRoleContext(roleCode, {
  headless: false,
  windowPosition,
});

process.stdout.write(`Opened ${role.label} window at ${targetUrl}.\n`);

const browser = context.browser();
if (!browser) {
  throw new Error(`Unable to access browser instance for ${role.label}.`);
}

await new Promise((resolve) => {
  browser.on("disconnected", resolve);
});
