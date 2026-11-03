import { createApiClient } from "@focusfeed/contracts";
import AsyncStorage from "@react-native-async-storage/async-storage";
import * as SecureStore from "expo-secure-store";

import { apiBaseUrl } from "@/lib/config";

const TOKEN_KEY = "ff_access_token"; // OS-backed secure storage (Keychain / Keystore), never AsyncStorage

export async function getToken(): Promise<string | null> {
  try { return await SecureStore.getItemAsync(TOKEN_KEY); } catch { return null; }
}
export async function setToken(token: string): Promise<void> {
  await SecureStore.setItemAsync(TOKEN_KEY, token);
}
export async function clearToken(): Promise<void> {
  try { await SecureStore.deleteItemAsync(TOKEN_KEY); } catch {}
}

let unauthorizedHandler: (() => void) | null = null;
export function setUnauthorizedHandler(fn: (() => void) | null) { unauthorizedHandler = fn; }

export const api = createApiClient({
  baseUrl: apiBaseUrl(),
  getAccessToken: getToken,
  onUnauthorized: () => unauthorizedHandler?.(),
});

export class RequestError extends Error {
  constructor(public readonly code: string, message: string, public readonly status: number, public readonly requestId = "", public readonly offline = false) {
    super(message);
  }
}

export async function unwrap<T>(p: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  let res: { data?: T; error?: unknown; response: Response };
  try {
    res = await p;
  } catch (e) {
    throw new RequestError("offline", "Can’t reach the server. Check your connection.", 0, "", true);
  }
  if (res.error) {
    const err = (res.error as { error?: { code?: string; message?: string; request_id?: string } }).error;
    throw new RequestError(err?.code ?? "http_error", err?.message ?? `Request failed (${res.response.status})`, res.response.status, err?.request_id ?? "");
  }
  return res.data as T;
}

/** Per-user, non-sensitive cache (last batch) so the Today tab can show permitted content offline. */
export async function cacheSet(userId: string, key: string, value: unknown): Promise<void> {
  try { await AsyncStorage.setItem(`ff:${userId}:${key}`, JSON.stringify(value)); } catch {}
}
export async function cacheGet<T>(userId: string, key: string): Promise<T | null> {
  try { const raw = await AsyncStorage.getItem(`ff:${userId}:${key}`); return raw ? (JSON.parse(raw) as T) : null; } catch { return null; }
}
export async function cacheClearAll(): Promise<void> {
  try { const keys = (await AsyncStorage.getAllKeys()).filter((k) => k.startsWith("ff:")); if (keys.length) await AsyncStorage.multiRemove(keys); } catch {}
}
