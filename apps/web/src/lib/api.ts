"use client";

import { createApiClient } from "@focusfeed/contracts";

export function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.split("; ").find((c) => c.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.slice(name.length + 1)) : null;
}

let unauthorizedHandler: (() => void) | null = null;
export function setUnauthorizedHandler(fn: (() => void) | null) {
  unauthorizedHandler = fn;
}

/** Same-origin client: Next.js rewrites /api/* to the backend, so the HttpOnly cookie is first-party. */
export const api = createApiClient({
  baseUrl: "",
  getCsrfToken: () => readCookie("ff_csrf"),
  onUnauthorized: () => unauthorizedHandler?.(),
});

export function isOffline(): boolean {
  return typeof navigator !== "undefined" && navigator.onLine === false;
}

/** Normalises openapi-fetch results into a thrown ApiError-ish object for simpler UI code. */
export async function unwrap<T>(p: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const { data, error, response } = await p;
  if (error) throw { error: (error as { error?: unknown }).error ?? { code: "http_error", message: `Request failed (${response.status})`, request_id: "" }, status: response.status };
  return data as T;
}
