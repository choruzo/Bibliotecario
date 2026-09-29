import { defineConfig } from '@playwright/test';
import base from './playwright.config';

// Exercise the compiled Compose deployment, without starting a dev server.
export default defineConfig({ ...base, webServer: undefined,
  use: { ...base.use, baseURL: process.env.BIB_E2E_ORIGIN || 'http://localhost:3000' }
});
