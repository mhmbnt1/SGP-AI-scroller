"use client";

import type { ModelsOut } from "@focusfeed/contracts";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type FormEvent } from "react";

import { AiSettings } from "@/components/ai-settings";
import { PreferencesForm } from "@/components/preferences-form";
import { WhatsAppSettings } from "@/components/whatsapp-settings";
import { Badge, ErrorBox } from "@/components/states";
import { api, unwrap } from "@/lib/api";
import { RequireAuth, useAuth } from "@/lib/auth";

type Session = { id: string; client_kind: string; user_agent: string; created_at: string; last_seen_at: string; current: boolean };

function SettingsInner() {
  const { me } = useAuth();
  const router = useRouter();
  const [models, setModels] = useState<ModelsOut | null>(null);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [theme, setTheme] = useState<string>("system");
  const load = useCallback(async () => {
    setError(null);
    try { const [m, s] = await Promise.all([unwrap(api.GET("/api/v1/models")), unwrap(api.GET("/api/v1/auth/sessions"))]); setModels(m); setSessions(s as Session[]); } catch (e) { setError(e); }
  }, []);
  useEffect(() => { void load(); try { setTheme(localStorage.getItem("ff:theme") ?? "system"); } catch {} }, [load]);

  function applyTheme(t: string) {
    setTheme(t);
    try { localStorage.setItem("ff:theme", t); } catch {}
    if (t === "system") document.documentElement.removeAttribute("data-theme"); else document.documentElement.setAttribute("data-theme", t);
  }
  async function exportData() {
    const data = await unwrap(api.GET("/api/v1/privacy/export"));
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.download = "focusfeed-export.json"; a.click(); URL.revokeObjectURL(url);
  }
  async function deleteAccount(e: FormEvent) {
    e.preventDefault(); setError(null);
    try { await unwrap(api.POST("/api/v1/privacy/delete", { body: { password, confirm: "DELETE" } })); try { sessionStorage.clear(); localStorage.clear(); } catch {} router.replace("/"); window.location.reload(); } catch (err) { setError(err); }
  }
  async function revokeSession(id: string) { await unwrap(api.DELETE("/api/v1/auth/sessions/{session_id}", { params: { path: { session_id: id } } })); await load(); }

  return (
    <div className="stack">
      <h1>Settings</h1>
      {error ? <ErrorBox error={error} onRetry={load} /> : null}
      <section className="card stack"><h2>Appearance</h2><div className="row" role="group" aria-label="Theme">{["system", "light", "dark"].map((t) => <button key={t} className={`btn-sm ${theme === t ? "btn-primary" : ""}`} aria-pressed={theme === t} onClick={() => applyTheme(t)}>{t}</button>)}</div></section>
      <AiSettings />
      <WhatsAppSettings />
      <section className="stack"><h2>Preferences</h2><PreferencesForm /></section>
      {models && (
        <section className="card stack">
          <h2>Model provider</h2>
          <div className="row"><Badge kind={models.provider_healthy ? "ok" : "bad"}>{models.provider}: {models.provider_detail}</Badge></div>
          <p className="muted"><small>{models.resource_note} Private feed content is only sent to the configured local provider; external providers are disabled unless an administrator enables them explicitly.</small></p>
          <table><thead><tr><th>Model</th><th>Purpose</th><th>Available</th><th>Capabilities</th></tr></thead>
            <tbody>{models.options.map((o) => <tr key={`${o.purpose}-${o.name}`}><td>{o.name}{o.is_default ? " (default)" : ""}</td><td>{o.purpose}</td><td><Badge kind={o.available ? "ok" : "bad"}>{o.available ? "yes" : "not installed"}</Badge></td><td className="muted"><small>{Object.entries(o.capabilities).filter(([, v]) => v !== null && v !== undefined).map(([k, v]) => `${k}=${String(v)}`).join(" · ") || "—"}</small></td></tr>)}</tbody></table>
        </section>
      )}
      <section className="card stack">
        <h2>Sessions & devices</h2>
        <table><thead><tr><th>Client</th><th>Last seen</th><th></th></tr></thead>
          <tbody>{sessions.map((s) => <tr key={s.id}><td>{s.client_kind}{s.current ? " (this session)" : ""}<div><small className="muted">{s.user_agent.slice(0, 60)}</small></div></td><td>{new Date(s.last_seen_at).toLocaleString()}</td><td>{!s.current && <button className="btn-sm" onClick={() => void revokeSession(s.id)}>Sign out</button>}</td></tr>)}</tbody></table>
        <p className="muted"><small>Collector devices are managed on the Connect page.</small></p>
      </section>
      <section className="card stack">
        <h2>Privacy</h2>
        <p>Signed in as <strong>{me?.user.email}</strong>. Export includes preferences, batches, saved items, feedback, runs, schedules and devices. Deletion removes all of it, including evidence artifacts; backups may retain copies for up to the configured retention period.</p>
        <div className="row"><button onClick={() => void exportData()}>Export my data (JSON)</button></div>
        <form className="stack" onSubmit={deleteAccount} aria-label="Delete account">
          <label>Confirm your password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required /></label>
          <label>Type DELETE to confirm<input type="text" value={confirm} onChange={(e) => setConfirm(e.target.value)} required /></label>
          <div className="row"><button type="submit" className="btn-danger" disabled={confirm !== "DELETE" || !password}>Delete my account</button></div>
        </form>
      </section>
    </div>
  );
}

export default function SettingsPage() { return <RequireAuth><SettingsInner /></RequireAuth>; }
