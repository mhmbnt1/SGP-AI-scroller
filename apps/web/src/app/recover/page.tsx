"use client";

import type { RecoveryStatusOut } from "@focusfeed/contracts";
import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";

import { ErrorBox } from "@/components/states";
import { api, unwrap } from "@/lib/api";

/** Self-service account recovery by emailed one-time code (no terminal, no second device needed). */
export default function RecoverPage() {
  const [status, setStatus] = useState<RecoveryStatusOut | null>(null);
  const [step, setStep] = useState<"request" | "confirm" | "done">("request");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { void unwrap(api.GET("/api/v1/auth/recovery")).then(setStatus).catch(setError); }, []);

  async function request(e: FormEvent) {
    e.preventDefault(); if (busy) return; setBusy(true); setError(null);
    try {
      const out = await unwrap(api.POST("/api/v1/auth/recovery/request", { body: { email } }));
      setNote(out.message);
      if (out.delivery === "sent") setStep("confirm");
    } catch (err) { setError(err); } finally { setBusy(false); }
  }
  async function confirm(e: FormEvent) {
    e.preventDefault(); if (busy) return; setBusy(true); setError(null);
    try {
      const out = await unwrap(api.POST("/api/v1/auth/recovery/confirm", { body: { email, code, new_password: password } }));
      setNote(out.message); setStep("done");
    } catch (err) { setError(err); } finally { setBusy(false); }
  }
  return (
    <div className="stack" style={{ maxWidth: 520, margin: "0 auto" }}>
      <h1>Recover your account</h1>
      {status && !status.available && <div className="notice warn" role="status">{status.note}</div>}
      {status?.available && <p className="muted">{status.note}</p>}
      {step === "request" && (
        <form className="card stack" onSubmit={request} aria-label="Request recovery code">
          <label>Email<input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" /></label>
          {error ? <ErrorBox error={error} /> : null}
          <button type="submit" className="btn-primary" disabled={busy || status?.available === false}>Send code</button>
        </form>
      )}
      {step === "confirm" && (
        <form className="card stack" onSubmit={confirm} aria-label="Enter recovery code">
          {note && <div className="notice success" role="status">{note}</div>}
          <label>Code from the email<input type="text" required value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} autoComplete="one-time-code" inputMode="text" maxLength={16} /></label>
          <label>New password <span className="hint">At least 10 characters.</span><input type="password" required minLength={10} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" /></label>
          {error ? <ErrorBox error={error} /> : null}
          <div className="row"><button type="submit" className="btn-primary" disabled={busy}>Set new password</button><button type="button" className="btn-sm" onClick={() => setStep("request")}>Send a new code</button></div>
        </form>
      )}
      {step === "done" && <div className="card stack"><div className="notice success" role="status">{note}</div><p>All previous sessions were signed out.</p><Link className="btn btn-primary" href="/">Sign in</Link></div>}
      <p><Link href="/">Back to sign in</Link></p>
    </div>
  );
}
