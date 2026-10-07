import { test, expect } from '@playwright/test';
import { execSync } from 'child_process';
import path from 'path';

test.describe('Live Execution & Verification Console (Stage 05 & 06 Verification)', () => {
  const planId = 'e2e_seeded_plan';

  test.beforeEach(async ({ page }) => {
    const backendDir = path.resolve(process.cwd(), '../backend');
    execSync(`python3 ../scripts/seed_e2e_plan.py ${planId}`, {
      cwd: backendDir,
      env: { ...process.env, PYTHONPATH: '.' },
    });

    await page.goto('/');
  });

  test('execution console displays live streaming, stage stepper, and successful completion', async ({ page }) => {
    // 1. Navigate to Executions view
    await page.goto('/#/executions');
    await expect(page.getByRole('heading', { name: 'Execution & Console' })).toBeVisible();

    // 2. Find our seeded plan row and click "View Console"
    const planRow = page.locator('div.bg-surface', { hasText: planId }).first();
    await expect(planRow).toBeVisible();
    await planRow.getByRole('button', { name: 'View Console' }).click();

    // 3. Verify Execution Console opened
    await expect(page.getByText('Live Execution & Verification')).toBeVisible();
    await expect(page.locator(`text=${planId}`).first()).toBeVisible();

    // 4. Verify Terminal output is present and streams execution logs
    const terminal = page.getByRole('log');
    await expect(terminal).toBeVisible();

    // 5. Wait for execution and verification to complete (within 15s)
    await expect(page.locator('text=Execution Succeeded')).toBeVisible({ timeout: 15000 });

    // 6. Verify Stage 05 (Execute) is marked 'Applied' and has done status
    const stage5 = page.locator('div', { hasText: 'Stage 05' }).first();
    await expect(stage5).toBeVisible();
    await expect(stage5).toContainText('Applied');
    await expect(stage5).not.toContainText('Failed');

    // 7. Verify Stage 06 (Verify) is marked 'Audited'
    const stage6 = page.locator('div', { hasText: 'Stage 06' }).first();
    await expect(stage6).toBeVisible();
    await expect(stage6).toContainText('Audited');

    // 8. Verify error banner with 'Plan cannot be executed in current status' does NOT exist
    await expect(page.locator('text=Plan cannot be executed in current status')).not.toBeVisible();
    await expect(page.locator('text=Execution Failed')).not.toBeVisible();
  });
});
