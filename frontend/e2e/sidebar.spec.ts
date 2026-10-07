import { test, expect } from '@playwright/test';

test.describe('Sidebar Enforcement & Theme System (M-UI-8)', () => {
  test.beforeEach(async ({ page }) => {
    // Clear localStorage to ensure pristine state
    await page.goto('/');
    await page.evaluate(() => localStorage.clear());
  });

  test('sidebar renders expanded at desktop width', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/');

    const sidebar = page.locator('aside');
    await expect(sidebar).toBeVisible();
    const box = await sidebar.boundingBox();
    expect(box?.width).toBeGreaterThanOrEqual(240);

    // Nav labels rendered
    await expect(page.getByRole('link', { name: 'Designer' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Plans' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Executions' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Audit Trail' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Connections' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Settings' })).toBeVisible();

    // Section headers rendered uppercase
    await expect(page.getByText('WORKSPACE')).toBeVisible();
    await expect(page.getByText('SYSTEM')).toBeVisible();

    // Active row indicator is present on current route
    const activeLink = page.getByRole('link', { name: 'Designer' });
    await expect(activeLink).toHaveAttribute('aria-current', 'page');
    const indicator = activeLink.locator('[data-testid="nav-active-indicator"]');
    await expect(indicator).toBeVisible();

    // Footer row contains env chip and collapse button
    await expect(page.locator('[data-testid="env-chip"]')).toBeVisible();
    await expect(page.locator('[data-testid="sidebar-toggle-btn"]')).toBeVisible();
  });

  test('each nav row contains at most one SVG icon', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/');

    const navLinks = page.locator('aside a');
    const count = await navLinks.count();
    expect(count).toBe(6);

    for (let i = 0; i < count; i++) {
      const link = navLinks.nth(i);
      const svgCount = await link.locator('svg').count();
      expect(svgCount).toBe(1);
    }
  });

  test('sidebar collapses to 64px rail via footer button and via Ctrl+B shortcut', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/');

    const sidebar = page.locator('aside');
    const toggleBtn = page.locator('[data-testid="sidebar-toggle-btn"]');

    // Click toggle button to collapse
    await toggleBtn.click();
    await page.waitForTimeout(200);

    let box = await sidebar.boundingBox();
    expect(box?.width).toBeLessThanOrEqual(64);

    // Active indicator is still retained when collapsed
    const activeLink = page.locator('aside a[aria-current="page"]');
    await expect(activeLink.locator('[data-testid="nav-active-indicator"]')).toBeVisible();

    // Press Ctrl+B to expand back
    await page.keyboard.press('Control+b');
    await page.waitForTimeout(200);

    box = await sidebar.boundingBox();
    expect(box?.width).toBeGreaterThanOrEqual(240);
    await expect(page.getByText('WORKSPACE')).toBeVisible();

    // Press Control+b again to collapse
    await page.keyboard.press('Control+b');
    await page.waitForTimeout(200);
    box = await sidebar.boundingBox();
    expect(box?.width).toBeLessThanOrEqual(64);
  });

  test('collapsed rail displays tooltip on hover and focus', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/');

    // Collapse sidebar
    await page.locator('[data-testid="sidebar-toggle-btn"]').click();
    await page.waitForTimeout(200);

    // Hover over Designer nav item
    const designerLink = page.locator('aside a[aria-label="Designer"]');
    await designerLink.hover();
    const tooltip = page.locator('[role="tooltip"]');
    await expect(tooltip).toBeVisible();
    await expect(tooltip).toHaveText('Designer');

    // Move mouse away to hide tooltip
    await page.mouse.move(0, 0);
    await page.waitForTimeout(100);

    // Focus via keyboard Tab key
    await designerLink.focus();
    await expect(page.locator('[role="tooltip"]')).toBeVisible();
    await expect(page.locator('[role="tooltip"]')).toHaveText('Designer');
  });

  test('theme toggle works and persists across page reloads', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/');

    // Default theme should be dark
    const html = page.locator('html');
    await expect(html).toHaveAttribute('data-theme', 'dark');

    // Find and click theme switcher button in Topbar
    const themeBtn = page.getByRole('button', { name: /switch to light theme/i });
    await expect(themeBtn).toBeVisible();
    await themeBtn.click();

    // Now theme should be light
    await expect(html).toHaveAttribute('data-theme', 'light');
    const storedTheme = await page.evaluate(() => localStorage.getItem('vellum.theme'));
    expect(storedTheme).toBe('light');

    // Reload page and verify persistence
    await page.reload();
    await expect(html).toHaveAttribute('data-theme', 'light');

    // Switch back to dark
    const themeBtnDark = page.getByRole('button', { name: /switch to dark theme/i });
    await themeBtnDark.click();
    await expect(html).toHaveAttribute('data-theme', 'dark');
  });
});
