/**
 * Mobile API integration tests for the core journey using a mocked HTTP layer.
 * They verify the bearer-token flow, 401 handling, and that the Today screen renders a finite batch
 * with the completion state from real API response shapes.
 */
import { render, waitFor } from "@testing-library/react-native";
import * as SecureStore from "expo-secure-store";

import { api, clearToken, getToken, setToken } from "@/lib/api";
import { AuthProvider } from "@/lib/auth";
import { TodayScreen } from "@/screens/today";

jest.mock("expo-web-browser", () => ({ openBrowserAsync: jest.fn() }));

const me = { user: { id: "u1", email: "m@example.com", display_name: "M", is_admin: false, onboarding_completed: true, created_at: "2026-01-01T00:00:00Z" }, mode: "test", onboarding_state: "complete", has_preferences: true, has_collector: false, connected_platforms: [] };
const today = {
  batch: {
    id: "b1", job_id: "j1", mode: "daily", query: null, generated_at: "2026-11-03T08:00:00Z", completion_status: "completed", platform_summary: {}, total_estimated_seconds: 600, is_synthetic: true, consumed_at: null,
    recommendations: [1, 2, 3].map((n) => ({ id: `r${n}`, rank: n, platform: "youtube", score: 0.5, components: {}, explanation: "e", summary: "s", topics: [], analysis_kind: "metadata_only", estimated_seconds: 200, duration_known: true, seen: false, hidden: false, saved: false,
      item: { id: `i${n}`, platform: "youtube", external_id: `x${n}`, canonical_url: `https://www.youtube.com/watch?v=x${n}`, creator_handle: "c", creator_name: "C", title: `Video ${n}`, caption: "", language: "en", duration_seconds: 200, published_at: null, thumbnail_url: null, is_synthetic: true } })),
  },
  active_job: null, collector_status: "not_required", message: "Here is your finite batch.",
};

type Handler = (url: string, headers: Headers) => { status: number; body: unknown };

/** openapi-fetch calls fetch(Request); read url/headers from either call style. */
function mockFetch(handler: Handler) {
  globalThis.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const req = input instanceof Request ? input : null;
    const url = req ? req.url : typeof input === "string" ? input : input.toString();
    const headers = req ? req.headers : new Headers(init?.headers);
    const { status, body } = handler(url, headers);
    return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
  }) as unknown as typeof fetch;
}

describe("mobile api client", () => {
  beforeEach(async () => { await clearToken(); });

  it("stores the token in SecureStore and sends it as a bearer header", async () => {
    await setToken("tok-123");
    expect(SecureStore.setItemAsync).toHaveBeenCalledWith("ff_access_token", "tok-123");
    let authHeader: string | null = null;
    mockFetch((_url, headers) => { authHeader = headers.get("authorization"); return { status: 200, body: me }; });
    const result = await api.GET("/api/v1/me");
    // eslint-disable-next-line no-console
    if (!result.data) console.log("DEBUG api.GET result", JSON.stringify({ error: result.error, status: result.response?.status, ctype: result.response?.headers?.get("content-type") }));
    expect(result.data?.user.email).toBe("m@example.com");
    expect(authHeader).toBe("Bearer tok-123");
  });

  it("clears the token on 401 (session expiry) via the auth provider", async () => {
    await setToken("expired");
    mockFetch(() => ({ status: 401, body: { error: { code: "session_expired", message: "Session expired.", request_id: "r" } } }));
    await render(<AuthProvider><TodayScreen /></AuthProvider>);
    await waitFor(async () => expect(await getToken()).toBeNull());
  });

  it("renders a finite batch and the completion marker", async () => {
    await setToken("tok");
    mockFetch((url) => (url.endsWith("/api/v1/me") ? { status: 200, body: me } : url.endsWith("/api/v1/batches/today") ? { status: 200, body: today } : { status: 404, body: { error: { code: "not_found", message: "nf", request_id: "" } } }));
    const { getByText, getAllByText } = await render(<AuthProvider><TodayScreen /></AuthProvider>);
    await waitFor(() => expect(getByText("Video 1")).toBeTruthy());
    expect(getAllByText(/^Video \d$/)).toHaveLength(3);
    expect(getByText("That’s the whole batch.")).toBeTruthy();
    expect(getByText("3 items")).toBeTruthy();
  });
});
