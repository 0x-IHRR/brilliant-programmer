import { defineConfig } from '@playwright/test'
import dotenv from 'dotenv'
dotenv.config({ path: '../.env', quiet: true })
export default defineConfig({
  testDir: './tests', fullyParallel: false, workers: 1,
  use: { baseURL: process.env.PLAYWRIGHT_BASE_URL ?? 'http://127.0.0.1:18080', headless: true },
  reporter: 'list',
})
