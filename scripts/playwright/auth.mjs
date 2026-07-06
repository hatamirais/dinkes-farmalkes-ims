import { closeContext, launchRoleContext, listRoleCodes } from "./common.mjs";

const shouldRefresh = process.argv.includes("--refresh");

for (const roleCode of listRoleCodes()) {
  process.stdout.write(`Preparing ${roleCode} session...\n`);
  const { context, role } = await launchRoleContext(roleCode, {
    headless: true,
    refresh: shouldRefresh,
  });
  await closeContext(context);
  process.stdout.write(`Saved profile for ${role.label}.\n`);
}

process.stdout.write(
  shouldRefresh
    ? "All role sessions were rebuilt successfully.\n"
    : "All role sessions are ready.\n",
);
