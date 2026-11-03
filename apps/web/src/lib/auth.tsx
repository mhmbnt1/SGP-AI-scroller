"use client";

import type { MeOut } from "@focusfeed/contracts";
import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { api, setUnauthorizedHandler, unwrap } from "@/lib/api";

interface AuthState {
  me: MeOut | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [me, setMe] = useState<MeOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    const { data, error: err, response } = await api.GET("/api/v1/me");
    if (data) setMe(data);
    else if (response.status === 401) setMe(null);
    else setError((err as { error?: { message?: string } } | undefined)?.error?.message ?? "Could not reach the server.");
    setLoading(false);
  }, []);

  const logout = useCallback(async () => {
    try {
      await unwrap(api.POST("/api/v1/auth/logout"));
    } finally {
      // Clear every per-user client cache on logout.
      try {
        sessionStorage.clear();
        localStorage.removeItem("ff:lastBatch");
      } catch {}
      setMe(null);
      router.replace("/");
    }
  }, [router]);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setMe(null);
      try { sessionStorage.clear(); } catch {}
    });
    void refresh();
    return () => setUnauthorizedHandler(null);
  }, [refresh]);

  const value = useMemo(() => ({ me, loading, error, refresh, logout }), [me, loading, error, refresh, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

/** Redirects to / when signed out; renders children only when signed in. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { me, loading, error, refresh } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (!loading && !me && !error) router.replace("/?expired=1");
  }, [loading, me, error, router]);
  if (loading) return <div className="stack" aria-busy="true"><div className="skeleton" style={{ height: 40 }} /><div className="skeleton" style={{ height: 120 }} /></div>;
  if (error) return <div className="notice danger" role="alert"><p>{error}</p><button onClick={() => void refresh()}>Retry</button></div>;
  if (!me) return null;
  return <>{children}</>;
}
