import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  outputDir: '../../.artifacts/h1/browser-tests',
  use: {
    baseURL: 'http://localhost:3010',
    launchOptions: process.env.BIB_CHROME_PATH ? { executablePath: process.env.BIB_CHROME_PATH } : {},
    trace: 'retain-on-failure'
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile', use: { ...devices['iPhone 13'], defaultBrowserType: 'chromium' } }
  ],
  webServer: {
    command: 'npm run dev -- --port 3010',
    url: 'http://localhost:3010/health',
    reuseExistingServer: !process.env.CI,
    timeout: 60000
  }
});
