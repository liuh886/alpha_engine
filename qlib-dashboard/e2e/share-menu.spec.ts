import { expect, test } from '@playwright/test';

test('Share is one product menu with page sharing and Invite nested inside', async ({ page }, testInfo) => {
  await page.route('**/admin/shared/account-shell.js*', (route) => route.fulfill({ status: 200, contentType: 'application/javascript', body: '' }));
  await page.route('**/admin/shared/product-referral.js*', (route) => route.fulfill({ status: 200, contentType: 'application/javascript', body: '' }));

  await page.goto('/#/');

  const share = page.getByRole('button', { name: 'Share Alpha Engine' });
  await expect(share).toBeVisible();
  await share.click();

  await expect(page.getByRole('button', { name: 'Share this page' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Invite a friend' })).toBeVisible();
  await expect(page.locator('.hao-referral-trigger')).toHaveCount(0);

  await page.screenshot({
    path: `test-results/static-artifact/share-menu-${testInfo.project.name}.png`,
    fullPage: false,
  });
});
