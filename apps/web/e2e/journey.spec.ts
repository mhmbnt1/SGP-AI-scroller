import { expect, test, type Page } from "@playwright/test";

// Requires the API (test/demo mode) + worker running on :8000. See scripts/e2e.sh.
const unique = () => `e2e-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;

async function register(page: Page, email: string, password: string) {
  await page.goto("/");
  await page.getByRole("tab", { name: "Create account" }).click();
  await page.getByLabel("Display name").fill("E2E");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel(/^Password/).fill(password);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/onboarding/);
}

test("register -> onboard -> demo batch -> inspect -> save -> feedback -> refresh -> logout", async ({ page }) => {
  const email = `${unique()}@example.com`;
  const password = "a-long-e2e-passphrase";
  await register(page, email, password);

  // onboarding: pick platforms and an interest
  await page.getByRole("checkbox", { name: /YouTube/ }).check();
  await page.getByRole("checkbox", { name: /Instagram/ }).check();
  await page.getByLabel("Interests: add").fill("cooking");
  await page.getByRole("button", { name: "Add" }).first().click();
  await page.getByRole("button", { name: "Save and continue" }).click();
  await expect(page).toHaveURL(/connect/);

  // today: generate batch via the real queue + worker
  await page.getByRole("link", { name: "Today" }).click();
  await page.getByRole("button", { name: "Refresh batch" }).click();
  await expect(page.getByRole("heading", { name: "That’s the whole batch." })).toBeVisible({ timeout: 60_000 });
  const cards = page.getByRole("article");
  const count = await cards.count();
  expect(count).toBeGreaterThan(0);
  expect(count).toBeLessThanOrEqual(10);
  await expect(page.getByText("synthetic demo data")).toBeVisible();

  // inspect: why + details
  await cards.first().getByRole("button", { name: "Why this?" }).click();
  await expect(cards.first().getByText(/Based on|Matches/)).toBeVisible();
  await cards.first().getByRole("link", { name: "Details" }).click();
  await expect(page.getByRole("heading", { name: "Why this was recommended" })).toBeVisible();
  await expect(page.getByRole("link", { name: /Open original source/ })).toHaveAttribute("rel", /noopener/);
  await page.goBack();

  // save + feedback
  await page.getByRole("article").first().getByRole("button", { name: "☆ Save" }).click();
  await expect(page.getByRole("article").first().getByRole("button", { name: "★ Saved" })).toBeVisible();
  await page.getByRole("article").nth(1).getByRole("button", { name: "Not interested" }).click();
  await page.getByRole("link", { name: "Saved" }).click();
  await expect(page.getByRole("article")).toHaveCount(1);

  // refresh produces a new batch and history has two runs
  await page.getByRole("link", { name: "Today" }).click();
  await page.getByRole("button", { name: "Refresh batch" }).click();
  await expect(page.getByRole("heading", { name: "That’s the whole batch." })).toBeVisible({ timeout: 60_000 });
  await page.getByRole("link", { name: "History" }).click();
  await expect(page.getByRole("row")).toHaveCount(4); // header + 2 runs + ... tolerant: at least 2 runs
  // logout clears the session
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/$/);
  await page.goto("/today");
  await expect(page).toHaveURL(/expired=1/);
});

test("two users cannot access each other's batches via direct URL", async ({ browser }) => {
  const a = await browser.newContext();
  const b = await browser.newContext();
  const pa = await a.newPage();
  const pb = await b.newPage();
  await register(pa, `${unique()}@example.com`, "a-long-e2e-passphrase");
  await pa.getByRole("checkbox", { name: /YouTube/ }).check();
  await pa.getByRole("button", { name: "Save and continue" }).click();
  await pa.getByRole("link", { name: "Today" }).click();
  await pa.getByRole("button", { name: "Refresh batch" }).click();
  await expect(pa.getByRole("heading", { name: "That’s the whole batch." })).toBeVisible({ timeout: 60_000 });
  await pa.getByRole("link", { name: "History" }).click();
  await pa.getByRole("link", { name: /Daily batch/ }).first().click();
  const batchUrl = pa.url();
  expect(batchUrl).toMatch(/history\//);

  await register(pb, `${unique()}@example.com`, "a-long-e2e-passphrase");
  await pb.goto(batchUrl);
  await expect(pb.getByText("Batch unavailable")).toBeVisible();
  await a.close();
  await b.close();
});
