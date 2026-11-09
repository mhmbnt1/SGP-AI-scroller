/**
 * Phase 2 mobile component tests with a mocked HTTP layer:
 * AI provider choice (consumer mode), WhatsApp linking code display, and the phone-driven hosted
 * sign-in (one-use token header on every session call, normalized tap coordinates).
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react-native";

import { setToken } from "@/lib/api";
import { AiSettingsScreen } from "@/screens/ai-settings";
import { ConnectSessionScreen } from "@/screens/connect-session";
import { WhatsAppScreen } from "@/screens/whatsapp";

jest.mock("expo-clipboard", () => ({ setStringAsync: jest.fn(async () => true) }));
jest.mock("expo-router", () => {
  const React = jest.requireActual("react");
  return {
    useRouter: () => ({ replace: jest.fn(), push: jest.fn(), back: jest.fn() }),
    useLocalSearchParams: () => ({ platform: "youtube" }),
    Link: ({ children }: { children: unknown }) => React.createElement(React.Fragment, null, children),
    Redirect: () => null,
    Stack: { Screen: () => null },
  };
});

type Call = { method: string; url: string; headers: Headers; body: unknown };
const calls: Call[] = [];

function mockFetch(handler: (c: Call) => { status: number; body: unknown; raw?: Blob }) {
  calls.length = 0;
  globalThis.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const req = input instanceof Request ? input : null;
    const url = req ? req.url : typeof input === "string" ? input : input.toString();
    const headers = req ? req.headers : new Headers(init?.headers);
    const method = (req ? req.method : init?.method) ?? "GET";
    let body: unknown = null;
    try { const text = req ? await req.text() : typeof init?.body === "string" ? init.body : ""; body = text ? JSON.parse(text) : null; } catch { body = null; }
    const c = { method, url, headers, body };
    calls.push(c);
    const { status, body: out, raw } = handler(c);
    if (raw) return new Response(raw, { status, headers: { "content-type": "image/jpeg" } });
    return new Response(JSON.stringify(out), { status, headers: { "content-type": "application/json" } });
  }) as unknown as typeof fetch;
}

const options = {
  providers: [
    { provider: "ollama", display_name: "Ollama (service-hosted)", help: "Runs on the service.", configured: true, external: false, models: [{ id: "qwen2.5:7b-instruct", label: "Qwen 2.5 7B", tasks: ["chat"], verified: false }] },
    { provider: "anthropic", display_name: "Anthropic Claude", help: "External provider.", configured: true, external: true, models: [{ id: "claude-haiku-4-5", label: "Claude Haiku 4.5", tasks: ["chat"], verified: false }] },
  ],
  selection: { provider: "ollama", chat_model: null, embedding_model: null, credential_mode: "operator", byok_connection_id: null, allow_fallback_to: [], external_disclosure_acknowledged: false, availability: "ready", availability_detail: "", effective_label: "ollama/qwen2.5:7b-instruct" },
  disclosure_text: "Content leaves this service.",
  byok_enabled: true,
};
const usage = { calls_today: 1, call_quota: 200, tokens_today: 1200, token_quota: 200000, messages_today: 0, message_quota: 20, cost_estimate_today_usd: "0.0000", cost_unknown_calls_today: 0, note: "Estimates only." };

describe("phase 2 mobile screens", () => {
  beforeEach(async () => { await setToken("tok-abc"); });

  it("lists operator-enabled providers and saves a consumer selection with the disclosure acknowledgement", async () => {
    let saved: unknown = null;
    mockFetch((c) => {
      if (c.url.endsWith("/ai/options")) return { status: 200, body: options };
      if (c.url.endsWith("/ai/usage")) return { status: 200, body: usage };
      if (c.url.endsWith("/ai/connections")) return { status: 200, body: [] };
      if (c.url.endsWith("/ai/selection") && c.method === "PUT") { saved = c.body; return { status: 200, body: { ...options.selection, provider: "anthropic", effective_label: "anthropic/claude-haiku-4-5" } }; }
      return { status: 404, body: { error: { code: "not_found", message: "nope", request_id: "r" } } };
    });
    await render(<AiSettingsScreen />);
    await screen.findByText("Anthropic Claude");
    await fireEvent.press(screen.getByText("Anthropic Claude"));
    await fireEvent.press(await screen.findByRole("checkbox"));
    await fireEvent.press(screen.getByLabelText("Save AI choice"));
    await waitFor(() => expect(saved).not.toBeNull());
    expect(saved).toMatchObject({ provider: "anthropic", credential_mode: "operator", acknowledge_external_processing: true, allow_fallback_to: [] });
    expect(JSON.stringify(saved)).not.toContain("api_key"); // the consumer flow never carries keys
    await screen.findByText(/Jobs now use anthropic\/claude-haiku-4-5/);
  });

  it("shows the one-time WhatsApp link code and never asks for a phone number", async () => {
    mockFetch((c) => {
      if (c.url.endsWith("/channels/whatsapp") && c.method === "GET") return { status: 200, body: { transport_mode: "mock", linked: false, display_hint: "", proactive_opt_in: false, paused_until: null, digest_enabled: true, alerts_enabled: true, external_disclosure_acknowledged: false, eligibility_note: "Linking is available.", templates_approved: { digest: false, alert: false }, service_window_open: false } };
      if (c.url.endsWith("/notifications")) return { status: 200, body: [] };
      if (c.url.endsWith("/channels/whatsapp/link") && c.method === "POST") return { status: 200, body: { message_text: "LINK ABCD-EFGH", deep_link: "https://wa.me/15551234567?text=LINK%20ABCD-EFGH", expires_at: "2026-11-04T10:00:00Z", instructions: "Send it from your own WhatsApp." } };
      return { status: 404, body: { error: { code: "not_found", message: "nope", request_id: "r" } } };
    });
    await render(<WhatsAppScreen />);
    await fireEvent.press(await screen.findByLabelText("Connect WhatsApp"));
    expect(await screen.findByTestId("wa-link-code")).toHaveTextContent("LINK ABCD-EFGH");
    expect(screen.queryByLabelText(/phone number/i)).toBeNull();
    expect(calls.some((c) => c.url.endsWith("/channels/whatsapp/link") && c.method === "POST")).toBe(true);
  });

  it("drives a hosted sign-in session: consent, one-use token header, normalized tap", async () => {
    const session = { id: "cs1", platform: "youtube", state: "active", frame_seq: 0, current_url_host: "accounts.google.com", result_status: "", ended_reason: "", created_at: "2026-11-04T09:00:00Z", expires_at: "2026-11-04T09:10:00Z" };
    mockFetch((c) => {
      if (c.url.includes("/connect-sessions") && c.method === "POST" && c.url.endsWith("/youtube/connect-sessions")) return { status: 201, body: { session, token: "one-use-token" } };
      if (c.url.endsWith("/connect-sessions/cs1") && c.method === "GET") return { status: 200, body: { ...session, frame_seq: 1 } };
      if (c.url.endsWith("/connect-sessions/cs1/frame")) return { status: 200, body: null, raw: new Blob([new Uint8Array([255, 216, 255, 217])], { type: "image/jpeg" }) };
      if (c.url.endsWith("/connect-sessions/cs1/input")) return { status: 200, body: { ok: true, message: "" } };
      return { status: 404, body: { error: { code: "not_found", message: "nope", request_id: "r" } } };
    });
    await render(<ConnectSessionScreen />);
    const start = await screen.findByLabelText("Start sign-in");
    expect(start).toBeDisabled();
    await fireEvent.press(screen.getByRole("checkbox"));
    await fireEvent.press(start);
    const frame = await screen.findByTestId("connect-frame");
    await fireEvent(frame, "layout", { nativeEvent: { layout: { width: 200, height: 400 } } });
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/connect-sessions/cs1") && c.headers.get("x-connect-token") === "one-use-token")).toBe(true));
    await fireEvent(frame, "press", { nativeEvent: { locationX: 50, locationY: 100 } });
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/cs1/input"))).toBe(true));
    const tap = calls.find((c) => c.url.endsWith("/cs1/input"));
    expect(tap?.headers.get("x-connect-token")).toBe("one-use-token");
    expect(tap?.body).toMatchObject({ kind: "tap", x: 0.25, y: 0.25 });
    // the consent screen never contains a credential form of its own
    expect(screen.queryByLabelText(/password/i)).toBeNull();
  });
});
