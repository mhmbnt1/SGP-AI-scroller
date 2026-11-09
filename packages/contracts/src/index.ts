/**
 * Shared, typed API client for web and mobile.
 *
 * - Types come from `schema.d.ts`, generated from the backend's OpenAPI document
 *   (`pnpm contracts:generate`). Never edit the generated file by hand.
 * - Web passes `credentials: "include"` and the CSRF header; mobile passes a bearer token.
 * - Domain rules (ranking, authorization) live on the backend; this client only transports.
 */
import createClient, { type Middleware } from "openapi-fetch";

import type { components, paths } from "./schema";

export type Schemas = components["schemas"];
export type Paths = paths;

export type AuthResponse = Schemas["AuthResponse"];
export type MeOut = Schemas["MeOut"];
export type PreferencesIn = Schemas["PreferencesIn"];
export type PreferencesOut = Schemas["PreferencesOut"];
export type JobOut = Schemas["JobOut"];
export type JobDetailOut = Schemas["JobDetailOut"];
export type JobAccepted = Schemas["JobAccepted"];
export type BatchOut = Schemas["BatchOut"];
export type BatchSummaryOut = Schemas["BatchSummaryOut"];
export type TodayOut = Schemas["TodayOut"];
export type RecommendationOut = Schemas["RecommendationOut"];
export type ItemDetailOut = Schemas["ItemDetailOut"];
export type ItemSummaryOut = Schemas["ItemSummaryOut"];
export type SavedOut = Schemas["SavedOut"];
export type FeedbackIn = Schemas["FeedbackIn"];
export type FeedbackOut = Schemas["FeedbackOut"];
export type ScheduleIn = Schemas["ScheduleIn"];
export type ScheduleOut = Schemas["ScheduleOut"];
export type ModelsOut = Schemas["ModelsOut"];
export type PlatformCapabilityOut = Schemas["PlatformCapabilityOut"];
export type ConnectionOut = Schemas["ConnectionOut"];
export type DeviceOut = Schemas["DeviceOut"];
export type EnrollmentOut = Schemas["EnrollmentOut"];
export type ExportOut = Schemas["ExportOut"];
export type AiOptionsOut = Schemas["AiOptionsOut"];
export type AiSelectionIn = Schemas["AiSelectionIn"];
export type AiSelectionOut = Schemas["AiSelectionOut"];
export type UsageOut = Schemas["UsageOut"];
export type ConnectionCreateIn = Schemas["ConnectionCreateIn"];
export type ProviderConnectionOut = Schemas["ProviderConnectionOut"];
export type ConnectionTestOut = Schemas["ConnectionTestOut"];
export type SourceOut = Schemas["SourceOut"];
export type ConnectSessionOut = Schemas["ConnectSessionOut"];
export type ConnectSessionStartOut = Schemas["ConnectSessionStartOut"];
export type ConnectInputIn = Schemas["ConnectInputIn"];
export type WatchIn = Schemas["WatchIn"];
export type WatchOut = Schemas["WatchOut"];
export type WatchDiscoveryOut = Schemas["WatchDiscoveryOut"];
export type WhatsAppStatusOut = Schemas["WhatsAppStatusOut"];
export type WhatsAppLinkStartOut = Schemas["WhatsAppLinkStartOut"];
export type WhatsAppPreferencesIn = Schemas["WhatsAppPreferencesIn"];
export type NotificationOut = Schemas["NotificationOut"];
export type RecoveryStatusOut = Schemas["RecoveryStatusOut"];
export type RecoveryRequestOut = Schemas["RecoveryRequestOut"];

export type FeedbackAction = FeedbackIn["action"];
export type JobState = JobOut["state"];

export interface ApiError {
  code: string;
  message: string;
  request_id: string;
  details?: unknown;
}

export interface ClientOptions {
  baseUrl: string;
  /** Web: cookie session + CSRF double-submit header. */
  getCsrfToken?: () => string | null | undefined;
  /** Mobile: bearer token from secure storage. */
  getAccessToken?: () => Promise<string | null | undefined> | string | null | undefined;
  /** Called on 401 so the app can clear state and redirect to login. */
  onUnauthorized?: (error: ApiError) => void;
  fetch?: typeof fetch;
}

export function isApiError(value: unknown): value is { error: ApiError } {
  return !!value && typeof value === "object" && "error" in (value as Record<string, unknown>);
}

export function errorMessage(error: unknown, fallback = "Something went wrong."): string {
  if (isApiError(error)) return error.error.message || fallback;
  if (error && typeof error === "object" && "message" in error) return String((error as { message: unknown }).message);
  return fallback;
}

export function createApiClient(options: ClientOptions) {
  const client = createClient<paths>({
    baseUrl: options.baseUrl,
    credentials: options.getAccessToken ? "omit" : "include",
    fetch: options.fetch,
  });

  const auth: Middleware = {
    async onRequest({ request }) {
      if (options.getAccessToken) {
        const token = await options.getAccessToken();
        if (token) request.headers.set("Authorization", `Bearer ${token}`);
      } else if (!["GET", "HEAD", "OPTIONS"].includes(request.method)) {
        const csrf = options.getCsrfToken?.();
        if (csrf) request.headers.set("X-CSRF-Token", csrf);
      }
      return request;
    },
    async onResponse({ response }) {
      // Do not read the body here (openapi-fetch requires an untouched Response); the caller still
      // receives the full error envelope. We only signal the app so it can clear session state.
      if (response.status === 401 && options.onUnauthorized) {
        options.onUnauthorized({
          code: "unauthorized",
          message: "Your session is no longer valid. Please sign in again.",
          request_id: response.headers.get("x-request-id") ?? "",
        });
      }
      return undefined;
    },
  };
  client.use(auth);
  return client;
}

export type ApiClient = ReturnType<typeof createApiClient>;

/** Human-readable label for the evidence coverage of a recommendation. */
export function analysisLabel(kind: string): string {
  switch (kind) {
    case "transcript_supported":
      return "Transcript-supported";
    case "sampled_visual":
      return "Sampled frames";
    case "combined":
      return "Transcript + frames";
    default:
      return "Metadata only";
  }
}

export function formatDuration(seconds: number, known: boolean): string {
  const m = Math.round(seconds / 60);
  const label = m < 1 ? "<1 min" : `${m} min`;
  return known ? label : `~${label} (est.)`;
}
