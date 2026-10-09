import { resolve } from 'node:path';

import { expect, test, type Page } from '@playwright/test';

// Created by the seed and published in the README.
const DEMO_EMAIL = 'demo@datapilot.dev';
const DEMO_PASSWORD = 'DataPilot-demo-2026';

// The demo model answers without an API key; the README's screenshot used a
// real model, chosen by its label in the Model list.
const ASK_MODEL = process.env['SCREENSHOT_MODEL'] || 'Demo model (example questions only)';
const ASK_QUESTION =
  process.env['SCREENSHOT_QUESTION'] || 'Which 10 countries brought in the most revenue last year?';

const OUTPUT = resolve(__dirname, '../../docs/images');
const THEMES = ['light', 'dark'] as const;

// The app follows the system theme until a theme is picked, so each page is
// captured in both themes without reloading it (and the Ask page without
// asking twice).
async function captureBothThemes(page: Page, name: string, fullPage = false): Promise<void> {
  for (const theme of THEMES) {
    await page.emulateMedia({ colorScheme: theme });
    await expect(page.locator('html')).toHaveCSS('color-scheme', theme);
    // Charts read their colors from the tokens when the theme changes.
    await page.waitForTimeout(300);
    await page.screenshot({ path: `${OUTPUT}/${name}-${theme}.png`, fullPage });
  }
}

test('capture the README screenshots in both themes', async ({ page }) => {
  await test.step('log in', async () => {
    await page.goto('/login');
    await page.getByLabel('Email').fill(DEMO_EMAIL);
    await page.getByLabel('Password').fill(DEMO_PASSWORD);
    await page.getByRole('button', { name: 'Log in' }).click();
    await expect(page.getByRole('heading', { level: 1, name: 'Dashboard' })).toBeVisible();
  });

  await test.step('dashboard', async () => {
    await expect(page.locator('[aria-busy="true"]')).toHaveCount(0);
    await expect(page.getByRole('main').locator('canvas').first()).toBeVisible();
    await captureBothThemes(page, 'dashboard');
  });

  await test.step('orders', async () => {
    await page.getByRole('link', { name: 'Orders', exact: true }).click();
    await expect(page.getByRole('main').getByRole('link', { name: /^\d+$/ })).not.toHaveCount(0);
    await captureBothThemes(page, 'orders');
  });

  await test.step('order detail', async () => {
    await page.getByRole('main').getByRole('link', { name: /^\d+$/ }).first().click();
    await expect(page.getByRole('table', { name: 'Items' }).getByRole('row')).not.toHaveCount(0);
    await captureBothThemes(page, 'order');
  });

  await test.step('ask your data', async () => {
    await page.getByRole('link', { name: 'Ask', exact: true }).click();
    await page.getByLabel('Model').selectOption({ label: ASK_MODEL });
    const question = page.getByRole('textbox', { name: 'Your question' });
    await question.fill(ASK_QUESTION);
    await question.press('Enter');
    const receipt = page.getByRole('article', { name: ASK_QUESTION });
    await expect(receipt.getByRole('table')).toBeVisible({ timeout: 60_000 });
    // The chart loads once it scrolls into view.
    await receipt.locator('.receipt__chart-placeholder').scrollIntoViewIfNeeded();
    await expect(receipt.locator('canvas')).toBeVisible();
    // The SQL that ran is the point of the receipt, so it is shown open.
    await receipt.getByText('Show SQL that ran').click();
    await captureBothThemes(page, 'ask', true);
  });
});
