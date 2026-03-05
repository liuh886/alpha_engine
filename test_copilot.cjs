const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto('http://localhost:5173');
  
  // Navigate to Agent Center
  await page.click('button:has-text("Agent Center")');
  
  // Wait for load
  await page.waitForTimeout(1000);
  
  // Try to find the chat input
  const inputSelector = 'input[placeholder*="Ask"], textarea, [contenteditable="true"]';
  await page.waitForSelector(inputSelector);
  await page.fill(inputSelector, 'Hello, what is the current market status?');
  await page.press(inputSelector, 'Enter');
  
  // Wait for response
  console.log('Waiting for agent response...');
  await page.waitForTimeout(5000);
  
  // Capture content
  const content = await page.textContent('body');
  console.log('Page Body Content Snip:', content.substring(0, 1000));
  
  await browser.close();
})();
