"use client";

import type { MeOut } from "@focusfeed/contracts";
import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { api, setUnauthorizedHandler, unwrap } from "@/lib/api";

interface AuthState {
  me: MeOut | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
  /** True while a deliberate sign-out is in progress (so guards do not report "session expired"). */
  isSigningOut: () => boolean;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [me, setMe] = useState<MeOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const meRef = useRef<MeOut | null>(null);
  const refresh = useCallback(async () => {
    // Only the first load shows the skeleton; later refreshes are silent so pages are not unmounted.
    if (meRef.current === null) setLoading(true);
    setError(null);
    const { data, error: err, response } = await api.GET("/api/v1/me");
    if (data) {
      meRef.current = data;
      signingOutRef.current = false;
      setMe(data);
    } else if (response.status === 401) {
      meRef.current = null;
      setMe(null);
    } else {
      setError((err as { error?: { message?: string } } | undefined)?.error?.message ?? "Could not reach the server.");
    }
    setLoading(false);
  }, []);

  const signingOutRef = useRef(false);
  const isSigningOut = useCallback(() => signingOutRef.current, []);
  const logout = useCallback(async () => {
    signingOutRef.current = true;
    try {
      await unwrap(api.POST("/api/v1/auth/logout"));
    } finally {
      // Clear every per-user client cache on logout.
      try {
        sessionStorage.clear();
        localStorage.removeItem("ff:lastBatch");
      } catch {}
      meRef.current = null;
      setMe(null);
      router.replace("/");
    }
  }, [router]);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      meRef.current = null;
      setMe(null);
      try { sessionStorage.clear(); } catch {}
    });
    void refresh();
    return () => setUnauthorizedHandler(null);
  }, [refresh]);

  const value = useMemo(() => ({ me, loading, error, refresh, logout, isSigningOut }), [me, loading, error, refresh, logout, isSigningOut]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

/** Redirects to / when signed out; renders children only when signed in. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { me, loading, error, refresh, isSigningOut } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (!loading && !me && !error) router.replace(isSigningOut() ? "/" : "/?expired=1");
  }, [loading, me, error, router, isSigningOut]);
  if (loading) return <div className="stack" aria-busy="true"><div className="skeleton" style={{ height: 40 }} /><div className="skeleton" style={{ height: 120 }} /></div>;
  if (error) return <div className="notice danger" role="alert"><p>{error}</p><button onClick={() => void refresh()}>Retry</button></div>;
  if (!me) return null;
  return <>{children}</>;
}
