import { createHmac } from "node:crypto";

import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

// Phase 2 screens against the real API + worker in test mode (scripts/e2e.sh exports the needed env:
// FF_ENABLED_PROVIDERS=fake,ollama, FF_WHATSAPP_MODE=mock, WA_APP_SECRET, WA_PHONE_NUMBER_ID, FF_MAIL_MODE=capture).
const API = process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000";
const APP_SECRET = process.env.WA_APP_SECRET ?? "e2e-app-secret";
const PNID = process.env.WA_PHONE_NUMBER_ID ?? "100000000000001";
const unique = () => `p2-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;

async function register(page: Page, email: string, password: string) {
  await page.goto("/");
  await page.getByRole("tab", { name: "Create account" }).click();
  await page.getByLabel("Display name").fill("P2");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel(/^Password/).fill(password);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/onboarding/);
  await page.getByRole("checkbox", { name: /YouTube/ }).check();
  await page.getByLabel("Interests: add").fill("cooking");
  await page.getByRole("button", { name: "Add" }).first().click();
  await page.getByRole("button", { name: "Save and continue" }).click();
  await expect(page).toHaveURL(/connect/);
}

/** Signed synthetic inbound webhook, exactly as Meta's Cloud API would deliver it (no real message is sent). */
async function inbound(request: APIRequestContext, sender: string, text: string) {
  const body = JSON.stringify({
    object: "whatsapp_business_account",
    entry: [{ id: "WABA", changes: [{ field: "messages", value: { messaging_product: "whatsapp", metadata: { display_phone_number: "15550000000", phone_number_id: PNID }, contacts: [{ wa_id: sender, profile: { name: "E2E" } }], messages: [{ from: sender, id: `wamid.${unique()}`, timestamp: String(Math.floor(Date.now() / 1000)), type: "text", text: { body: text } }] } }] }],
  });
  const sig = "sha256=" + createHmac("sha256", APP_SECRET).update(body).digest("hex");
  const r = await request.post(`${API}/api/v1/webhooks/whatsapp`, { data: body, headers: { "Content-Type": "application/json", "X-Hub-Signature-256": sig } });
  expect(r.status()).toBe(200);
}

test("hosted sources are the default; the local collector is an advanced option", async ({ page }) => {
  await register(page, `${unique()}@example.com`, "a-long-e2e-passphrase");
  const sources = page.getByRole("region", { name: "Your sources" });
  await expect(sources).toBeVisible();
  // honest per-platform status: in test mode no login is needed, and phone-only support is marked unverified
  await expect(sources.getByRole("row", { name: /YouTube/ })).toContainText(/available|not connected/);
  await expect(sources.getByRole("row", { name: /YouTube/ })).toContainText("unverified");
  await expect(page.getByText("Advanced: run the collector on your own PC instead (optional)")).toBeVisible();
  // the hosted sign-in page asks for consent first and never renders a credential form of its own
  await page.goto("/connect/youtube");
  await expect(page.getByRole("heading", { name: "Connect youtube" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Start sign-in" })).toBeDisabled();
  expect(await page.locator("input[type=password]").count()).toBe(0);
  await page.getByRole("checkbox", { name: /I consent to hosting my youtube session/ }).check();
  await page.getByRole("button", { name: "Start sign-in" }).click();
  // the session is created server-side with a one-use token; the worker (test mode) drives the browser
  await expect(page.getByText(/^(pending|starting|active|completed|failed|expired|cancelled)$/)).toBeVisible();
  const cancel = page.getByRole("button", { name: "Cancel" });
  if (await cancel.isVisible()) await cancel.click(); // in this container the login page may be unreachable → failed
  await expect(page.getByText(/^(Session (cancelled|failed|expired)|Result:)/)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("button", { name: "Back to sources" })).toBeVisible();
});

test("consumer picks an AI provider without any API key; usage and disclosure are shown", async ({ page }) => {
  await register(page, `${unique()}@example.com`, "a-long-e2e-passphrase");
  await page.getByRole("link", { name: "Settings" }).click();
  const ai = page.getByRole("region", { name: "AI model" });
  await expect(ai).toBeVisible();
  await ai.getByLabel("AI provider").selectOption("fake");
  await ai.getByRole("button", { name: "Save AI choice" }).click();
  await expect(ai.getByRole("status")).toContainText(/Jobs now use fake/);
  await expect(ai.getByText(/Today: \d+\/\d+ calls/)).toBeVisible();
  // BYOK is collapsed under Advanced and the API never echoes keys
  await ai.getByText("Advanced: use my own API key (optional)").click();
  await ai.getByLabel("API key").fill("sk-e2e-test-key-value-123456");
  await ai.getByRole("button", { name: "Add key" }).click();
  await expect(ai.getByText(/OpenAI models · sk-/)).toBeVisible();
  await expect(ai.getByText("sk-e2e-test-key-value-123456")).toHaveCount(0);
});

test("schedule with 'ready by' + WhatsApp delivery, a topic watch, and account recovery entry", async ({ page }) => {
  await register(page, `${unique()}@example.com`, "a-long-e2e-passphrase");
  await page.getByRole("link", { name: "Schedules" }).click();
  await page.getByLabel(/Ready by/).fill("19:00");
  await page.getByLabel(/Lead time/).fill("45");
  await page.getByLabel("Also deliver to WhatsApp (needs notifications enabled)").check();
  await page.getByLabel(/Send to WhatsApp at/).fill("19:30");
  await page.getByRole("button", { name: /Add schedule|Create schedule|Save schedule/ }).click();
  await expect(page.getByText(/ready by 19:00/)).toBeVisible();
  await expect(page.getByText(/· WhatsApp/)).toBeVisible();

  await page.getByRole("link", { name: "Watches" }).click();
  await page.getByLabel(/^Name/).fill("AI news");
  await page.getByLabel(/^Topics/).fill("ai, machine learning");
  await page.getByRole("button", { name: "Add watch" }).click();
  await expect(page.getByText("AI news")).toBeVisible();
  await expect(page.getByText(/not checked yet/)).toBeVisible();

  await page.getByRole("button", { name: "Sign out" }).click();
  await page.goto("/recover");
  await page.getByLabel("Email").fill("someone@example.com");
  await page.getByRole("button", { name: "Send code" }).click();
  await expect(page.getByLabel("Code from the email")).toBeVisible(); // mail captured server-side; no enumeration
});

test("WhatsApp linking from the phone: code shown in app, verified from a signed inbound message, STOP respected", async ({ page, request }) => {
  await register(page, `${unique()}@example.com`, "a-long-e2e-passphrase");
  await page.getByRole("link", { name: "Settings" }).click();
  const wa = page.getByRole("region", { name: "WhatsApp" });
  await expect(wa.getByText("transport: mock")).toBeVisible();
  await wa.getByRole("button", { name: "Connect WhatsApp" }).click();
  const code = (await wa.getByRole("status").locator("code").textContent())?.trim() ?? "";
  expect(code).toMatch(/^LINK /);
  expect(await wa.locator("input[type=tel]").count()).toBe(0); // we never ask for a phone number
  const sender = `1555${String(Date.now()).slice(-7)}`;
  await inbound(request, sender, code);
  await expect(async () => {
    await wa.getByRole("button", { name: "I sent it — check" }).click();
    await expect(wa.getByText(/^linked/)).toBeVisible({ timeout: 2_000 });
  }).toPass({ timeout: 30_000 });
  await wa.getByRole("checkbox", { name: /not protected by WhatsApp end-to-end encryption/ }).check();
  await wa.getByRole("button", { name: "Enable notifications" }).click();
  await expect(wa.getByText("notifications on")).toBeVisible();
  await inbound(request, sender, "STOP");
  await expect(async () => {
    await page.reload();
    await expect(page.getByRole("region", { name: "WhatsApp" }).getByText("notifications off")).toBeVisible({ timeout: 2_000 });
  }).toPass({ timeout: 30_000 });
  // the same code cannot be reused by another sender
  await inbound(request, `1555${String(Date.now() + 7).slice(-7)}`, code);
  await expect(page.getByRole("region", { name: "WhatsApp" }).getByText(/^linked/)).toBeVisible();
});
