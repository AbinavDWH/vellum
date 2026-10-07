import { test, expect } from '@playwright/test';

test.describe('Connection Credentials UI & Service Scope Management (M-17)', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/#/connections');
    await expect(page.getByText('System & Cloud Connections')).toBeVisible();
  });

  test('connections view renders configured cloud connections and Add Connection button', async ({ page }) => {
    // Assert Add Connection button exists
    const addBtn = page.getByRole('button', { name: 'Add Connection' });
    await expect(addBtn).toBeVisible();

    // Assert Cloud Target Connections section is rendered
    await expect(page.getByText('Cloud Target Connections (Credentials & Scope)')).toBeVisible();
  });

  test('drawer blocks invalid Access Key ID inline and disables saving', async ({ page }) => {
    const addBtn = page.getByRole('button', { name: 'Add Connection' });
    await addBtn.click();

    // Assert drawer opened
    const drawer = page.locator('[data-testid="connection-drawer"]');
    await expect(drawer).toBeVisible();
    await expect(drawer.getByText('Add Connection')).toBeVisible();

    // Fill name
    await page.getByPlaceholder('e.g. sandbox-main').fill('bad-key-test');

    // Type invalid access key ID
    const keyInput = page.getByPlaceholder('AKIA****************');
    await keyInput.fill('INVALIDKEY123');

    // Assert inline validation error message appears
    await expect(
      page.getByText('Access Key ID must start with AKIA or ASIA and be exactly 20 uppercase alphanumeric characters.')
    ).toBeVisible();

    // Assert Save Connection button is disabled
    const saveBtn = page.getByRole('button', { name: 'Save Connection' });
    await expect(saveBtn).toBeDisabled();

    // Close drawer
    await page.getByRole('button', { name: 'Cancel' }).click();
    await expect(drawer).not.toBeVisible();
  });

  test('PROD environment requires typed confirmation and creates connection card with masked key', async ({ page }) => {
    const addBtn = page.getByRole('button', { name: 'Add Connection' });
    await addBtn.click();

    const drawer = page.locator('[data-testid="connection-drawer"]');
    await expect(drawer).toBeVisible();

    const connName = `e2e-prod-${Date.now().toString(36)}`;
    await page.getByPlaceholder('e.g. sandbox-main').fill(connName);

    // Switch to PROD
    await page.getByRole('button', { name: 'PROD' }).click();
    await expect(page.getByText('Production Environment Protection')).toBeVisible();

    // Fill valid credentials
    const keyInput = page.getByPlaceholder('AKIA****************');
    await keyInput.fill('AKIAIOSFODNN7EXAMPLE');

    const secretInput = page.getByPlaceholder('••••••••••••••••••••');
    await secretInput.fill('wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY');

    const saveBtn = page.getByRole('button', { name: 'Save Connection' });
    // Before typing confirmation, save is disabled
    await expect(saveBtn).toBeDisabled();

    // Type matching confirmation name
    const confirmInput = page.getByPlaceholder(`Type "${connName}" to confirm`);
    await confirmInput.fill(connName);

    // Now save is enabled
    await expect(saveBtn).toBeEnabled();
    await saveBtn.click();

    // Assert drawer closed
    await expect(drawer).not.toBeVisible();

    // Assert card is rendered with masked key only
    await expect(page.getByRole('heading', { name: connName })).toBeVisible();
    await expect(page.getByText('AKIA****MPLE').first()).toBeVisible();
  });

  test('service scope presets toggle chips correctly in drawer', async ({ page }) => {
    const addBtn = page.getByRole('button', { name: 'Add Connection' });
    await addBtn.click();

    const drawer = page.locator('[data-testid="connection-drawer"]');
    await expect(drawer).toBeVisible();

    // Click 'Storage-only' preset
    await drawer.getByRole('button', { name: 'Storage-only' }).click();
    await expect(drawer.getByRole('button', { name: 's3' })).toHaveClass(/border-brand/);
    await expect(drawer.getByRole('button', { name: 'ec2' })).not.toHaveClass(/border-brand/);

    // Click 'All' preset
    await drawer.getByRole('button', { name: 'All' }).click();
    await expect(drawer.getByRole('button', { name: 's3' })).toHaveClass(/border-brand/);
    await expect(drawer.getByRole('button', { name: 'rds' })).toHaveClass(/border-brand/);
    await expect(drawer.getByRole('button', { name: 'lambda' })).toHaveClass(/border-brand/);

    // Click 'Recommended' preset
    await drawer.getByRole('button', { name: 'Recommended' }).click();
    await expect(drawer.getByRole('button', { name: 's3' })).toHaveClass(/border-brand/);

    await drawer.getByRole('button', { name: 'Cancel' }).click();
    await expect(drawer).not.toBeVisible();
  });

  test('live connection probe renders account ID and service checklist', async ({ page }) => {
    const addBtn = page.getByRole('button', { name: 'Add Connection' });
    await addBtn.click();

    const drawer = page.locator('[data-testid="connection-drawer"]');
    await expect(drawer).toBeVisible();

    await page.getByPlaceholder('e.g. sandbox-main').fill('probe-test-conn');
    await page.getByPlaceholder('AKIA****************').fill('AKIAIOSFODNN7EXAMPLE');
    await page.getByPlaceholder('••••••••••••••••••••').fill('wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY');

    // Run Test Connection probe
    const testProbeBtn = drawer.getByRole('button', { name: 'Test Connection' });
    await expect(testProbeBtn).toBeEnabled();
    await testProbeBtn.click();

    // Verify STS caller identity is rendered
    await expect(drawer.getByText('STS Account ID:')).toBeVisible();
    await expect(drawer.getByText('000000000000', { exact: true })).toBeVisible();

    // Verify service probes list rendered
    await expect(drawer.getByText(/Service Probes/)).toBeVisible();
    await expect(drawer.locator('.space-y-1').getByText('s3')).toBeVisible();

    await drawer.getByRole('button', { name: 'Cancel' }).click();
  });
});
