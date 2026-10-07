import { test, expect } from '@playwright/test';

test.describe('F8: Terminate & Stop Buttons in UI', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.clear();
      sessionStorage.clear();
    });
  });

  test('Chat pane: Stop button replaces Send during streaming, absent when idle', async ({ page }) => {
    // Mock clean session so previous historical conversations don't cause layout or loading thrash
    await page.route('**/api/sessions', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            id: 'sess_f8_clean',
            title: 'Clean Session',
            environment: 'local',
            provider: 'aws',
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
            message_count: 0,
          },
        ]),
      });
    });

    await page.route('**/api/sessions/sess_f8_clean/messages', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      });
    });

    await page.route('**/api/sessions/sess_f8_clean/requirements', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ requirements_md: '' }),
      });
    });

    await page.goto('/');

    // 1. Initially idle: Send button is visible, Stop button is absent
    const sendButton = page.getByRole('button', { name: 'Send' });
    await expect(sendButton).toBeVisible();
    await expect(page.getByRole('button', { name: /Stop/i })).not.toBeVisible();

    // 2. Type a message into chat textarea
    const chatInput = page.getByPlaceholder(/Describe your cloud architecture requirement/i);
    await expect(chatInput).toBeVisible();
    await chatInput.fill('create a vpc with a public subnet');

    // Mock slow / streaming response on /api/chat so we can observe the Stop button
    await page.route('**/api/chat', async (route) => {
      // Delay for 4 seconds so we can interact with Stop button
      await new Promise((res) => setTimeout(res, 4000));
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'conversation',
          message: 'Architecture synthesized.',
        }),
      });
    });

    let stopApiCalled = false;
    await page.route('**/api/chat/stop/**', async (route) => {
      stopApiCalled = true;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'stopped' }),
      });
    });

    // 3. Click Send
    await sendButton.click();

    // 4. During streaming, Stop button replaces Send
    const stopButton = page.getByRole('button', { name: /Stop/i });
    await expect(stopButton).toBeVisible();
    await expect(sendButton).not.toBeVisible();

    // 5. Click Stop - must halt in < 2s
    const stopStartTime = Date.now();
    await stopButton.click();

    // 6. Verify Send button is restored and Stop button disappears
    await expect(page.getByRole('button', { name: 'Send' })).toBeVisible({ timeout: 2000 });
    await expect(stopButton).not.toBeVisible();
    const elapsed = Date.now() - stopStartTime;
    expect(elapsed).toBeLessThan(2000);
    expect(stopApiCalled).toBe(true);
  });

  test('Execution Console & Rows: Terminate transitions state to TERMINATING then TERMINATED/RECONCILING, absent when idle', async ({ page }) => {
    const mockPlanId = 'plan_test_f8_active';

    // Intercept WebSocket connection so it remains open and actively streaming
    await page.routeWebSocket('**/ws/execution/**', (ws) => {
      ws.send('[INFO] Connected to execution channel. Pipeline initialized.');
      ws.send('[INFO] Terraform applying infrastructure resources...');
    });

    // Mock getPlan returning an executing plan
    await page.route(`**/api/plans/${mockPlanId}`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          plan_id: mockPlanId,
          status: 'executing',
          intent: 'deploy_cloud',
          risk_level: 'low',
          requires_confirmation_text: false,
          summary_preview: 'Plan executing...',
          ir: { intent: 'deploy_cloud' },
          implementation_plan: [
            { step_number: 1, phase: 'infra', name: 'Infra Step', status: 'active', description: 'desc' }
          ],
        }),
      });
    });

    // Mock terminate API
    let headerTerminateCalls = 0;
    await page.route(`**/api/executions/${mockPlanId}/terminate`, async (route) => {
      headerTerminateCalls++;
      const req = route.request();
      const body = JSON.parse(req.postData() || '{}');
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'cancelled',
          mode: body.force ? 'sigkill' : 'sigint',
        }),
      });
    });

    // 1. Test Execution Console header controls
    await page.goto(`/#/executions?plan=${mockPlanId}`);

    // Execution Console header shows Terminate button while running
    const terminateBtn = page.getByRole('button', { name: /Terminate/i });
    await expect(terminateBtn).toBeVisible({ timeout: 5000 });

    // Click 1: Graceful -> State transitions to TERMINATING
    await terminateBtn.click();
    await expect(page.getByText('TERMINATING')).toBeVisible();
    await expect(page.getByRole('button', { name: /Force Kill/i })).toBeVisible();

    // Click 2: Force -> State transitions to TERMINATED / RECONCILING
    const forceBtn = page.getByRole('button', { name: /Force Kill/i });
    await forceBtn.click();
    await expect(page.getByText('TERMINATED', { exact: true })).toBeVisible();
    expect(headerTerminateCalls).toBe(2);

    // 2. Test Execution History rows (running row has Terminate, idle completed row does NOT)
    const mockRowPlanId = 'plan_running_row_99';
    await page.route('**/api/executions', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            id: 101,
            plan_id: mockRowPlanId,
            run_number: 1,
            status: 'running',
            success: null,
            resources_created: 0,
            resources_updated: 0,
            resources_deleted: 0,
            terraform_output: '',
            execution_time_seconds: 4.2,
            duration_seconds: 4.2,
            created_at: new Date().toISOString(),
          },
          {
            id: 102,
            plan_id: 'plan_completed_idle_88',
            run_number: 1,
            status: 'completed',
            success: true,
            resources_created: 3,
            resources_updated: 0,
            resources_deleted: 0,
            terraform_output: '',
            execution_time_seconds: 15.0,
            duration_seconds: 15.0,
            created_at: new Date().toISOString(),
          },
        ]),
      });
    });

    let rowTerminateCalls = 0;
    await page.route(/.*\/api\/executions\/(101|plan_running_row_99)\/terminate/, async (route) => {
      rowTerminateCalls++;
      const req = route.request();
      const body = JSON.parse(req.postData() || '{}');
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'cancelled',
          mode: body.force ? 'sigkill' : 'sigint',
        }),
      });
    });

    // Navigate to Executions list view
    await page.goto('/#/executions');

    const runningRow = page.locator('div.bg-surface', { hasText: mockRowPlanId }).first();
    await expect(runningRow).toBeVisible();

    // Running row has Terminate button
    const rowTerminateBtn = runningRow.getByRole('button', { name: /Terminate/i });
    await expect(rowTerminateBtn).toBeVisible();

    // Idle completed row has NO Terminate button (absent when idle)
    const completedRow = page.locator('div.bg-surface', { hasText: 'plan_completed_idle_88' }).first();
    await expect(completedRow).toBeVisible();
    await expect(completedRow.getByRole('button', { name: /Terminate/i })).not.toBeVisible();

    // Click 1 on running row: Graceful -> Row status chip becomes TERMINATING
    await rowTerminateBtn.click();
    await expect(runningRow.getByText('TERMINATING')).toBeVisible();
    const rowForceKillBtn = runningRow.getByRole('button', { name: /Force Kill/i });
    await expect(rowForceKillBtn).toBeVisible();

    // Click 2 on running row: Force -> Row status chip becomes TERMINATED/RECONCILING
    await rowForceKillBtn.click();
    await expect(runningRow.getByText(/TERMINATED\/RECONCILING/i)).toBeVisible();
    expect(rowTerminateCalls).toBe(2);
  });

  test('Terminate & Stop buttons verified in light AND dark themes with keyboard accessibility', async ({ page }) => {
    const mockPlanId = 'plan_test_f8_theme';

    await page.routeWebSocket('**/ws/execution/**', (ws) => {
      ws.send('[INFO] Connected to execution channel.');
      ws.send('[INFO] Actively streaming...');
    });

    await page.route(`**/api/plans/${mockPlanId}`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          plan_id: mockPlanId,
          status: 'executing',
          intent: 'deploy_cloud',
          risk_level: 'low',
          requires_confirmation_text: false,
          summary_preview: 'Plan executing...',
          ir: { intent: 'deploy_cloud' },
          implementation_plan: [
            { step_number: 1, phase: 'infra', name: 'Infra Step', status: 'active', description: 'desc' }
          ],
        }),
      });
    });

    await page.goto(`/#/executions?plan=${mockPlanId}`);

    // Verify Terminate button is visible in default Dark theme
    const terminateBtn = page.getByRole('button', { name: /Terminate/i });
    await expect(terminateBtn).toBeVisible();

    // Toggle to Light theme
    const themeToggle = page.getByRole('button', { name: /Switch to (Light|Dark) theme/i });
    await expect(themeToggle).toBeVisible();
    await themeToggle.click();

    // Verify Terminate button remains visible and interactive in Light theme
    await expect(terminateBtn).toBeVisible();

    // Verify keyboard focusability
    await terminateBtn.focus();
    await expect(terminateBtn).toBeFocused();

    // Toggle back to Dark theme
    await themeToggle.click();
    await expect(terminateBtn).toBeVisible();
  });
});
