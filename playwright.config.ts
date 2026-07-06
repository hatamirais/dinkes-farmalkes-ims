export default {
  testDir: "./playwright",
  timeout: 30_000,
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL || "http://127.0.0.1:8000",
    browserName: "chromium",
    headless: false,
  },
  projects: [
    {
      name: "chromium-local",
      use: {
        browserName: "chromium",
      },
    },
  ],
};
