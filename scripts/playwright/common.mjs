import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const REPO_ROOT = path.resolve(import.meta.dirname, "..", "..");
const LOCAL_ENV_PATH = path.join(REPO_ROOT, ".env.playwright.local");
const PROFILE_ROOT = path.join(REPO_ROOT, ".playwright-profiles");
const LOGIN_PATH = "/login/";
const WINDOW_SIZE = { width: 1440, height: 960 };

export const ROLE_DEFINITIONS = [
  {
    code: "PUSKESMAS",
    slug: "puskesmas",
    label: "Puskesmas",
    landingPath: "/lplpo/my/",
    env: {
      username: "PW_PUSKESMAS_USERNAME",
      password: "PW_PUSKESMAS_PASSWORD",
    },
  },
  {
    code: "GUDANG",
    slug: "gudang",
    label: "Gudang",
    landingPath: "/lplpo/",
    env: {
      username: "PW_GUDANG_USERNAME",
      password: "PW_GUDANG_PASSWORD",
    },
  },
  {
    code: "KEPALA",
    slug: "kepala",
    label: "Kepala",
    landingPath: "/",
    env: {
      username: "PW_KEPALA_USERNAME",
      password: "PW_KEPALA_PASSWORD",
    },
  },
  {
    code: "ADMIN_UMUM",
    slug: "admin-umum",
    label: "Admin Umum",
    landingPath: "/",
    env: {
      username: "PW_ADMIN_UMUM_USERNAME",
      password: "PW_ADMIN_UMUM_PASSWORD",
    },
  },
  {
    code: "AUDITOR",
    slug: "auditor",
    label: "Auditor",
    landingPath: "/reports/",
    env: {
      username: "PW_AUDITOR_USERNAME",
      password: "PW_AUDITOR_PASSWORD",
    },
  },
  {
    code: "ADMIN",
    slug: "admin",
    label: "Admin",
    landingPath: "/admin/",
    env: {
      username: "PW_ADMIN_USERNAME",
      password: "PW_ADMIN_PASSWORD",
    },
  },
];

function parseEnvValue(rawValue) {
  const value = rawValue.trim();
  if (!value) {
    return "";
  }

  if (
    (value.startsWith('"') && value.endsWith('"')) ||
    (value.startsWith("'") && value.endsWith("'"))
  ) {
    return value.slice(1, -1);
  }

  return value;
}

function parseEnvFile(contents) {
  const values = {};
  for (const rawLine of contents.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) {
      continue;
    }

    const separatorIndex = line.indexOf("=");
    if (separatorIndex === -1) {
      continue;
    }

    const key = line.slice(0, separatorIndex).trim();
    const value = line.slice(separatorIndex + 1);
    values[key] = parseEnvValue(value);
  }
  return values;
}

export function loadLocalConfig() {
  if (!fs.existsSync(LOCAL_ENV_PATH)) {
    throw new Error(
      [
        `Missing ${path.basename(LOCAL_ENV_PATH)}.`,
        "Copy .env.playwright.local.example to .env.playwright.local and fill in the role credentials.",
      ].join(" "),
    );
  }

  const fileConfig = parseEnvFile(fs.readFileSync(LOCAL_ENV_PATH, "utf8"));
  return {
    ...fileConfig,
    ...process.env,
  };
}

export function resolveRole(roleCode) {
  const role = ROLE_DEFINITIONS.find((entry) => entry.code === roleCode);
  if (!role) {
    throw new Error(`Unknown role '${roleCode}'. Expected one of: ${ROLE_DEFINITIONS.map((entry) => entry.code).join(", ")}.`);
  }
  return role;
}

export function getRoleCredentials(role, config) {
  const username = config[role.env.username];
  const password = config[role.env.password];

  if (!username || !password) {
    throw new Error(
      `Missing ${role.label} credentials. Set ${role.env.username} and ${role.env.password} in .env.playwright.local.`,
    );
  }

  return { username, password };
}

export function getBaseUrl(config) {
  const baseUrl = config.PLAYWRIGHT_BASE_URL;
  if (!baseUrl) {
    throw new Error("Missing PLAYWRIGHT_BASE_URL in .env.playwright.local.");
  }
  return baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`;
}

export function getProfileDir(role) {
  return path.join(PROFILE_ROOT, role.slug);
}

export function ensureProfileRoot() {
  fs.mkdirSync(PROFILE_ROOT, { recursive: true });
}

export function clearProfileDir(role) {
  fs.rmSync(getProfileDir(role), { recursive: true, force: true });
}

export function buildRoleUrl(baseUrl, role) {
  return new URL(role.landingPath.replace(/^\//, ""), baseUrl).toString();
}

function isLoginUrl(urlValue) {
  try {
    return new URL(urlValue).pathname === LOGIN_PATH;
  } catch {
    return false;
  }
}

async function performLogin(page, username, password) {
  await page.locator("#id_username").fill(username);
  await page.locator("#id_password").fill(password);

  await Promise.all([
    page
      .waitForURL((url) => url.pathname !== LOGIN_PATH, { timeout: 15_000 })
      .catch(() => null),
    page.locator("button[type='submit']").click(),
  ]);

  await page.waitForLoadState("domcontentloaded");
}

export async function launchRoleContext(roleCode, { headless = true, refresh = false, windowPosition } = {}) {
  const config = loadLocalConfig();
  const role = resolveRole(roleCode);
  const credentials = getRoleCredentials(role, config);
  const baseUrl = getBaseUrl(config);
  const targetUrl = buildRoleUrl(baseUrl, role);

  ensureProfileRoot();
  if (refresh) {
    clearProfileDir(role);
  }

  const launchArgs = [`--window-size=${WINDOW_SIZE.width},${WINDOW_SIZE.height}`];
  if (windowPosition) {
    launchArgs.push(`--window-position=${windowPosition.x},${windowPosition.y}`);
  }

  const context = await chromium.launchPersistentContext(getProfileDir(role), {
    headless,
    viewport: null,
    args: launchArgs,
  });

  const page = context.pages()[0] ?? (await context.newPage());
  await page.goto(targetUrl, { waitUntil: "domcontentloaded" });

  if (isLoginUrl(page.url())) {
    await performLogin(page, credentials.username, credentials.password);
  }

  if (isLoginUrl(page.url())) {
    const errorText = await page.locator(".auth-alert").textContent().catch(() => null);
    await context.close();
    throw new Error(
      `Login failed for ${role.label}.${errorText ? ` ${errorText.trim()}` : " Check the credentials in .env.playwright.local."}`,
    );
  }

  await page.goto(targetUrl, { waitUntil: "domcontentloaded" });
  return { context, page, role, targetUrl };
}

export async function closeContext(context) {
  await context.close();
}

export function listRoleCodes() {
  return ROLE_DEFINITIONS.map((role) => role.code);
}
