import type { MeOut } from "@focusfeed/contracts";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { AppState } from "react-native";

import { api, cacheClearAll, clearToken, getToken, setToken, setUnauthorizedHandler, unwrap } from "@/lib/api";

interface AuthState {
  me: MeOut | null;
  ready: boolean;
  offline: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, displayName: string) => Promise<void>;
  logout: () => Promise<void>;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<MeOut | null>(null);
  const [ready, setReady] = useState(false);
  const [offline, setOffline] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const refreshing = useRef(false);

  const refresh = useCallback(async () => {
    if (refreshing.current) return;
    refreshing.current = true;
    try {
      const token = await getToken();
      if (!token) { setMe(null); return; }
      const { data, error: err, response } = await api.GET("/api/v1/me");
      if (data) { setMe(data); setOffline(false); setError(null); }
      else if (response.status === 401) { await clearToken(); setMe(null); }
      else setError((err as { error?: { message?: string } } | undefined)?.error?.message ?? "Server error");
    } catch {
      setOffline(true); // keep the cached `me` so permitted cached content stays visible
    } finally {
      refreshing.current = false;
      setReady(true);
    }
  }, []);

  const signOutLocally = useCallback(async () => {
    await clearToken();
    await cacheClearAll();
    setMe(null);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const out = await unwrap(api.POST("/api/v1/auth/login", { body: { email, password, client: "mobile" } }));
    if (!out.access_token) throw new Error("No token in response");
    await setToken(out.access_token);
    await refresh();
  }, [refresh]);

  const register = useCallback(async (email: string, password: string, displayName: string) => {
    const out = await unwrap(api.POST("/api/v1/auth/register", { body: { email, password, display_name: displayName, client: "mobile" } }));
    if (!out.access_token) throw new Error("No token in response");
    await setToken(out.access_token);
    await refresh();
  }, [refresh]);

  const logout = useCallback(async () => {
    try { await api.POST("/api/v1/auth/logout"); } catch {}
    await signOutLocally();
  }, [signOutLocally]);

  useEffect(() => {
    setUnauthorizedHandler(() => { void signOutLocally(); });
    void refresh();
    const sub = AppState.addEventListener("change", (s) => { if (s === "active") void refresh(); }); // re-validate on resume
    return () => { sub.remove(); setUnauthorizedHandler(null); };
  }, [refresh, signOutLocally]);

  const value = useMemo(() => ({ me, ready, offline, error, refresh, login, register, logout }), [me, ready, offline, error, refresh, login, register, logout]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}
