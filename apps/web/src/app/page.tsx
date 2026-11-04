"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState, type FormEvent } from "react";

import { ErrorBox } from "@/components/states";
import { api, unwrap } from "@/lib/api";
import { useAuth } from "@/lib/auth";

function WelcomeInner() {
  const { me, loading, refresh } = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (!loading && me) router.replace(me.onboarding_state === "complete" ? "/today" : "/onboarding");
  }, [loading, me, router]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      if (mode === "register") await unwrap(api.POST("/api/v1/auth/register", { body: { email, password, display_name: name, client: "web" } }));
      else await unwrap(api.POST("/api/v1/auth/login", { body: { email, password, client: "web" } }));
      await refresh();
    } catch (err) {
      setError(err); // form input is preserved
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack" style={{ maxWidth: 520, margin: "0 auto" }}>
      <section>
        <h1>Scroll less. Keep the useful part.</h1>
        <p className="muted">FocusFeed delegates bounded feed browsing to an agent on your own PC and hands you a finite daily batch — with sources and a reason for every pick. No autoplay, no infinite scroll.</p>
      </section>
      {params.get("expired") && <div className="notice warn" role="status">Your session expired. Please sign in again.</div>}
      <form className="card stack" onSubmit={submit} aria-label={mode === "login" ? "Sign in" : "Create account"}>
        <div className="row" role="tablist" aria-label="Sign in or create account">
          <button type="button" role="tab" aria-selected={mode === "login"} className={mode === "login" ? "btn-primary btn-sm" : "btn-sm"} onClick={() => setMode("login")}>Sign in</button>
          <button type="button" role="tab" aria-selected={mode === "register"} className={mode === "register" ? "btn-primary btn-sm" : "btn-sm"} onClick={() => setMode("register")}>Create account</button>
        </div>
        {mode === "register" && (
          <label>Display name<input type="text" value={name} onChange={(e) => setName(e.target.value)} maxLength={120} autoComplete="name" /></label>
        )}
        <label>Email<input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" /></label>
        <label>
          Password {mode === "register" && <span className="hint">At least 10 characters. Passphrases work well.</span>}
          <input type="password" required minLength={mode === "register" ? 10 : 1} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete={mode === "register" ? "new-password" : "current-password"} />
        </label>
        {error ? <ErrorBox error={error} title={mode === "login" ? "Sign-in failed" : "Could not create account"} /> : null}
        <button type="submit" className="btn-primary" disabled={busy}>{busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}</button>
        <small className="muted"><Link href="/recover">Forgot your password?</Link> Recovery works by emailed code when the operator has enabled mail; otherwise the operator resets it for you.</small>
      </form>
    </div>
  );
}

export default function WelcomePage() {
  return <Suspense fallback={null}><WelcomeInner /></Suspense>;
}
