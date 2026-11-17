import { expect, test } from '@playwright/test';

test('formal instrument link opens one chart-first price history with model markers and a retained ledger', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/#/strategies/qqqi_qqq_tqqq_v4_3');
  await page.getByRole('tab', { name: 'Trades', exact: true }).click();
  const link = page.getByRole('link', { name: 'View QQQ price and model events', exact: true }).first();
  await expect(link).toBeVisible();
  await link.click();
  await expect(page).toHaveURL(/#\/securities\/us\/QQQ/);
  await expect(page).toHaveTitle('Instrument Evidence — Alpha Engine');
  await expect(page.getByRole('heading', { name: 'QQQ', exact: true })).toBeVisible();

  const chart = page.getByTestId('security-history-chart');
  await expect(chart).toBeVisible();
  await expect(page.getByRole('region', { name: 'Price and model events' })).toBeVisible();
  await expect(page.getByTestId('security-lightweight-chart-container')).toHaveCount(1);
  await expect(page.getByText('TradingView Lightweight Charts™', { exact: false }).first()).toBeVisible();
  await expect(page.getByTestId('security-last-close')).toHaveText(/\d/);
  await expect(page.getByTestId('security-one-week-change')).toContainText('%');
  await expect(page.getByTestId('security-chart-baseline')).toContainText('Baseline: QQQ · governed US market index');
  await expect(page.getByTestId('security-chart-basis')).toContainText('Raw OHLC price candles');
  await expect(page.getByTestId('security-chart-basis')).toContainText('not split or dividend adjusted');

  // The chart engine selector is retired: exactly one chart, price mode by default.
  await expect(page.getByRole('button', { name: 'TradingView', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Recharts Classic', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Side-by-side POC', exact: true })).toHaveCount(0);
  const baselineControl = page.getByRole('button', { name: 'US baseline: No baseline', exact: true });
  await expect(baselineControl).toBeVisible();
  const disabledReason = page.getByTestId('security-baseline-disabled');
  await expect(disabledReason).toBeVisible();
  await expect(disabledReason).toContainText('QQQ is the governed US market baseline');
  await baselineControl.click();
  const selfOption = page.getByRole('option', { name: /QQQ/ });
  await expect(selfOption).toHaveAttribute('aria-disabled', 'true');
  await expect(selfOption).toContainText('comparing it with itself would add no information');
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('security-lightweight-chart-container')).toHaveCount(1);

  // The marker list is the keyboard-accessible equivalent of the canvas markers.
  await expect(page.getByRole('list', { name: 'Event markers in range' })).toBeVisible();
  const marker = page.getByTestId('security-trade-marker').first();
  await expect(marker).toBeVisible();
  await marker.focus();
  await expect(marker).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(marker).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByTestId('security-selected-event')).toContainText('QQQR v4.3');
  await expect(page.getByTestId('security-selected-event')).toContainText('Weight');

  // Hiding the only bound model with events clears markers without recreating the chart.
  const toggle = page.getByRole('checkbox', { name: /QQQR v4\.3/ });
  await toggle.uncheck();
  await expect(chart).toHaveAttribute('data-marker-count', '0');
  await expect(page.getByTestId('security-trade-marker')).toHaveCount(0);
  await toggle.check();
  await expect(chart).not.toHaveAttribute('data-marker-count', '0');
  await expect(page.getByTestId('security-trade-marker').first()).toBeVisible();

  await page.getByRole('button', { name: '1M', exact: true }).click();
  await expect(page).toHaveURL(/[?&]range=1m/);
  await expect(page.getByRole('button', { name: '1M', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByTestId('security-visible-dates')).toContainText('observed sessions');
  await expect(page.getByTestId('security-lightweight-chart-container')).toHaveCount(1);
  await expect(page.locator('vite-error-overlay')).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false);

  await page.getByRole('checkbox', { name: 'Show complete ledger' }).check();
  await expect(page.getByText('Full retained ledger, including events outside price coverage.', { exact: false })).toBeVisible();
  expect(errors).toEqual([]);
});

test('the shared baseline control indexes the instrument and the governed market index on exact common dates', async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/#/securities/cn/002594');
  await expect(page.getByRole('heading', { name: 'BYD · 002594' })).toBeVisible();
  const chart = page.getByTestId('security-history-chart');
  await expect(chart).toBeVisible();
  await expect(page.getByTestId('security-lightweight-chart-container')).toHaveCount(1);

  const baselineControl = page.getByRole('button', { name: 'CN baseline: No baseline', exact: true });
  await expect(baselineControl).toBeVisible();
  await baselineControl.click();
  await page.getByRole('option', { name: /CSI 300/ }).click();
  await expect(page.getByRole('button', { name: 'CN baseline: CSI 300 (000300.SH)', exact: true })).toBeVisible();
  await expect(page.getByTestId('security-chart-baseline')).toContainText('CSI 300 (000300.SH)');
  await expect(page.getByTestId('security-chart-baseline')).toContainText('governed CN market index');
  await expect(page.getByTestId('security-chart-basis')).toContainText('Open-to-open price return');
  await expect(page.getByTestId('security-chart-basis')).toContainText(/indexed to 100 at \d{4}-\d{2}-\d{2} – \d{4}-\d{2}-\d{2}/);
  await expect(page.getByRole('list', { name: 'Chart series' })).toContainText('000300');
  await expect(page.getByRole('list', { name: 'Chart series' })).toContainText('not total return');
  await expect(page.getByTestId('security-lightweight-chart-container')).toHaveCount(1);
  await expect(page.getByTestId('security-chart-basis')).not.toContainText('raw OHLC');

  // Model identity survives the marker grouping and the shared legend.
  const modelKey = page.getByRole('list', { name: 'Model marker key' });
  await expect(modelKey).toBeVisible();
  await expect(modelKey.getByTestId('model-marker-swatch').first()).toBeVisible();
  await expect(page.getByRole('list', { name: 'Marker direction key' })).toContainText('Buy / increase');

  // Markers stay selectable in baseline mode, and a range change keeps the mode.
  const marker = page.getByTestId('security-trade-marker').first();
  await expect(marker).toBeVisible();
  await marker.focus();
  await page.keyboard.press('Enter');
  const detail = page.getByTestId('security-selected-event');
  await expect(detail).toBeVisible();
  await expect(detail).toContainText('Model');
  await expect(detail).toContainText('Weight');
  await expect(detail).toContainText('Historical ledger dates only');
  await page.screenshot({ path: testInfo.outputPath(`security-marker-detail-${testInfo.project.name}.png`), fullPage: false });

  await page.getByRole('button', { name: '3M', exact: true }).click();
  await expect(page).toHaveURL(/[?&]range=3m/);
  await expect(page.getByRole('button', { name: 'CN baseline: CSI 300 (000300.SH)', exact: true })).toBeVisible();
  await expect(page.getByTestId('security-history-chart')).toHaveAttribute('data-marker-count', /\d+/);
  await expect(page.getByTestId('security-chart-basis')).toContainText('Open-to-open price return');

  await page.getByRole('button', { name: 'Use dark theme', exact: true }).click();
  await expect(page.locator('html')).toHaveClass(/dark/);
  await page.screenshot({ path: testInfo.outputPath(`security-marker-detail-dark-${testInfo.project.name}.png`), fullPage: false });

  await expect(page.locator('vite-error-overlay')).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false);
  expect(errors).toEqual([]);
});
