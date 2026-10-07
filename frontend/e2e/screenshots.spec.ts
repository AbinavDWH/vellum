import { test, expect } from '@playwright/test';
import path from 'path';

test.describe('Theme & Screen Verification Screenshots (M-UI-8)', () => {
  const screenshotDir = path.resolve(process.cwd(), 'screenshots');

  test('capture Designer in Dark & Light themes (expanded & collapsed)', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });

    // 1. Dark theme - Expanded
    await page.goto('/#/designer');
    await page.evaluate(() => {
      localStorage.setItem('vellum.theme', 'dark');
      localStorage.setItem('vellum_sidebar_collapsed', 'false');
    });
    await page.reload();
    await page.waitForTimeout(500);
    await page.screenshot({ path: path.join(screenshotDir, 'designer-dark-expanded.png') });

    // 2. Dark theme - Collapsed
    await page.locator('[data-testid="sidebar-toggle-btn"]').click();
    await page.waitForTimeout(300);
    await page.screenshot({ path: path.join(screenshotDir, 'designer-dark-collapsed.png') });

    // 3. Light theme - Collapsed
    await page.getByRole('button', { name: /switch to light theme/i }).click();
    await page.waitForTimeout(300);
    await page.screenshot({ path: path.join(screenshotDir, 'designer-light-collapsed.png') });

    // 4. Light theme - Expanded
    await page.locator('[data-testid="sidebar-toggle-btn"]').click();
    await page.waitForTimeout(300);
    await page.screenshot({ path: path.join(screenshotDir, 'designer-light-expanded.png') });
  });

  test('capture Audit Trail in Dark & Light themes', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });

    // 1. Audit Trail - Dark
    await page.goto('/#/audit');
    await page.evaluate(() => {
      localStorage.setItem('vellum.theme', 'dark');
      localStorage.setItem('vellum_sidebar_collapsed', 'false');
    });
    await page.reload();
    await page.waitForTimeout(600);
    await page.screenshot({ path: path.join(screenshotDir, 'audit-dark.png') });

    // 2. Audit Trail - Light
    await page.getByRole('button', { name: /switch to light theme/i }).click();
    await page.waitForTimeout(300);
    await page.screenshot({ path: path.join(screenshotDir, 'audit-light.png') });
  });

  test('capture Executions in Dark & Light themes', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });

    // 1. Executions - Dark
    await page.goto('/#/executions');
    await page.evaluate(() => {
      localStorage.setItem('vellum.theme', 'dark');
      localStorage.setItem('vellum_sidebar_collapsed', 'false');
    });
    await page.reload();
    await page.waitForTimeout(600);
    await page.screenshot({ path: path.join(screenshotDir, 'executions-dark.png') });

    // 2. Executions - Light
    await page.getByRole('button', { name: /switch to light theme/i }).click();
    await page.waitForTimeout(300);
    await page.screenshot({ path: path.join(screenshotDir, 'executions-light.png') });
  });

  test('capture Command Palette in Dark & Light themes', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });

    // Dark Command Palette
    await page.goto('/#/designer');
    await page.evaluate(() => {
      localStorage.setItem('vellum.theme', 'dark');
    });
    await page.reload();
    await page.waitForTimeout(300);
    await page.keyboard.press('Control+k');
    await page.waitForTimeout(300);
    await page.screenshot({ path: path.join(screenshotDir, 'command-palette-dark.png') });

    // Light Command Palette
    await page.keyboard.press('Escape');
    await page.getByRole('button', { name: /switch to light theme/i }).click();
    await page.waitForTimeout(200);
    await page.keyboard.press('Control+k');
    await page.waitForTimeout(300);
    await page.screenshot({ path: path.join(screenshotDir, 'command-palette-light.png') });
  });
});
