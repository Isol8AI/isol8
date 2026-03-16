import { test, expect } from '@playwright/test';

test('landing page loads and redirects to chat', async ({ page }) => {
  test.slow(); // Increase timeout for heavy visuals
  // 1. Visit the root URL
  await page.goto('/');

  // 2. Check for key landing page elements
  await expect(page).toHaveTitle(/isol8/); 
  await expect(page.locator('h1')).toContainText('Intelligence');

  // Check for the "Start Encrypted Session" button
  const getStartedBtn = page.getByRole('link', { name: /Start Encrypted Session/i });
  await expect(getStartedBtn).toBeVisible();
  
  // Wait for animations to settle or use force click
  await getStartedBtn.click({ force: true });

  // 5. Expect redirection to /chat
  await expect(page).toHaveURL(/.*\/chat|.*\/sign-in/);
});

test('landing page shows pricing and toggles', async ({ page }) => {
  await page.goto('/');
  
  // Check for Pricing section
  const pricingHeader = page.getByRole('heading', { name: /Pricing|Plans/i });
  await expect(pricingHeader).toBeVisible();

  // Check for Monthly/Yearly toggle
  // Check for text "Yearly" (toggle button)
  const yearlyText = page.getByText('Yearly');
  await expect(yearlyText).toBeVisible();

  // Check for Pro plan
  await expect(page.getByText('Pro', { exact: true })).toBeVisible();
});
