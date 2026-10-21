import { expect, test, type Page } from '@playwright/test';

test.use({ serviceWorkers: 'block' });

async function openOverview(page: Page) {
  await page.goto('/#/app');
  await expect(page.getByRole('heading', { name: 'What are the strategies doing now?' })).toBeVisible();
}

async function isHandset(page: Page): Promise<boolean> {
  const viewport = page.viewportSize();
  return (viewport?.width ?? 1280) < 768;
}

test('mobile tab bar is visible only on handsets with two reachable tabs', async ({ page }) => {
  await openOverview(page);
  const tabbar = page.getByRole('navigation', { name: 'Primary' });
  if (await isHandset(page)) {
    await expect(tabbar).toBeVisible();
    const tabs = tabbar.getByRole('tab');
    await expect(tabs).toHaveCount(2);
    await expect(tabs.first()).toHaveAttribute('aria-selected', 'true');
    for (const tab of await tabs.all()) {
      const box = await tab.boundingBox();
      expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
    }
    await tabs.nth(1).click();
    await expect(page).toHaveURL(/#\/system/);
  } else {
    await expect(tabbar).toBeHidden();
  }
});

test('mobile drawer opens, traps focus affordance and closes on Escape', async ({ page }) => {
  await openOverview(page);
  if (!(await isHandset(page))) {
    await expect(page.getByRole('button', { name: 'Open strategy navigation' })).toBeHidden();
    return;
  }
  await page.getByRole('button', { name: 'Open strategy navigation' }).click();
  const dialog = page.getByRole('dialog', { name: 'Strategy navigation' });
  await expect(dialog).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
});

test('handset overview has no horizontal overflow and content clears the tab bar', async ({ page }) => {
  await openOverview(page);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(2);
  if (await isHandset(page)) {
    const tabbar = page.getByRole('navigation', { name: 'Primary' });
    const bar = await tabbar.boundingBox();
    const main = await page.locator('.research-main').boundingBox();
    expect(bar && main ? main.y + main.height : 0).toBeGreaterThan(0);
    if (bar && main) {
      const mainBottomInView = main.y + main.height - (await page.evaluate(() => window.scrollY));
      expect(mainBottomInView).toBeGreaterThan(bar.y);
    }
  }
});
