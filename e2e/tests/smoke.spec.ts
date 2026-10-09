import { expect, test } from '@playwright/test';

// Created by the seed and published in the README.
const DEMO_EMAIL = 'demo@datapilot.dev';
const DEMO_PASSWORD = 'DataPilot-demo-2026';
const EXAMPLE_QUESTION = 'What was the monthly revenue over the last 12 months?';

test('an analyst logs in, opens an order and asks an example question', async ({ page }) => {
  await test.step('log in with the demo account', async () => {
    await page.goto('/login');
    await page.getByLabel('Email').fill(DEMO_EMAIL);
    await page.getByLabel('Password').fill(DEMO_PASSWORD);
    await page.getByRole('button', { name: 'Log in' }).click();
    await expect(page.getByRole('heading', { level: 1, name: 'Dashboard' })).toBeVisible();
  });

  await test.step('stay logged in across a reload (refresh cookie)', async () => {
    await page.reload();
    await expect(page.getByRole('heading', { level: 1, name: 'Dashboard' })).toBeVisible();
  });

  await test.step('open the orders and one order', async () => {
    await page.getByRole('link', { name: 'Orders', exact: true }).click();
    const firstOrder = page.getByRole('main').getByRole('link', { name: /^\d+$/ }).first();
    const orderId = (await firstOrder.innerText()).trim();
    await firstOrder.click();
    await expect(page).toHaveURL(new RegExp(`/orders/${orderId}$`));
    await expect(page.getByRole('heading', { level: 1, name: `Order ${orderId}` })).toBeVisible();
    await expect(page.getByRole('table', { name: 'Items' }).getByRole('row')).not.toHaveCount(0);
  });

  await test.step('ask an example question with the demo model', async () => {
    await page.getByRole('link', { name: 'Ask', exact: true }).click();
    await page.getByLabel('Model').selectOption({ label: 'Demo model (example questions only)' });
    await page
      .getByRole('group', { name: 'Example questions' })
      .getByRole('button', { name: EXAMPLE_QUESTION })
      .click();

    const receipt = page.getByRole('article', { name: EXAMPLE_QUESTION });
    await expect(receipt).toBeVisible();
    // A header row and one row per month.
    await expect(receipt.getByRole('table').getByRole('row')).toHaveCount(13);
  });
});
