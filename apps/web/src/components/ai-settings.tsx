"use client";

import type { AiOptionsOut, ProviderConnectionOut, UsageOut } from "@focusfeed/contracts";
import { useCallback, useEffect, useState } from "react";

import { Badge, ErrorBox, Loading } from "@/components/states";
import { api, unwrap } from "@/lib/api";

type Provider = "openai" | "anthropic" | "gemini" | "xai" | "ollama" | "fake";

/** Consumer AI choice: one provider/model from the operator-enabled list; BYOK and fallbacks collapsed under Advanced. */
export function AiSettings() {
  const [opts, setOpts] = useState<AiOptionsOut | null>(null);
  const [usage, setUsage] = useState<UsageOut | null>(null);
  const [conns, setConns] = useState<ProviderConnectionOut[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [provider, setProvider] = useState<Provider>("ollama");
  const [chatModel, setChatModel] = useState<string>("");
  const [ack, setAck] = useState(false);
  const [mode, setMode] = useState<"operator" | "byok">("operator");
  const [connId, setConnId] = useState<string>("");
  const [fallback, setFallback] = useState<string>("");
  const [newKey, setNewKey] = useState({ provider: "openai" as Provider, api_key: "", label: "" });

  const load = useCallback(async () => {
    setError(null);
    try {
      const [o, u, c] = await Promise.all([unwrap(api.GET("/api/v1/ai/options")), unwrap(api.GET("/api/v1/ai/usage")), unwrap(api.GET("/api/v1/ai/connections"))]);
      setOpts(o); setUsage(u); setConns(c);
      if (o.selection.provider) setProvider(o.selection.provider as Provider);
      setChatModel(o.selection.chat_model ?? "");
      setMode(o.selection.credential_mode);
      setConnId(o.selection.byok_connection_id ?? "");
      setAck(o.selection.external_disclosure_acknowledged);
      setFallback(o.selection.allow_fallback_to[0] ?? "");
    } catch (e) { setError(e); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  async function save() {
    if (busy) return;
    setBusy(true); setError(null); setSaved(null);
    try {
      const out = await unwrap(api.PUT("/api/v1/ai/selection", { body: { provider: provider as "openai" | "anthropic" | "gemini" | "xai" | "ollama" | "fake", credential_mode: mode, chat_model: chatModel || null, byok_connection_id: mode === "byok" && connId ? connId : null, allow_fallback_to: fallback ? [fallback] : [], acknowledge_external_processing: ack } }));
      setSaved(`Saved. Jobs now use ${out.effective_label} (${out.availability}).`);
      await load();
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  async function addKey() {
    if (busy || newKey.api_key.length < 8) return;
    setBusy(true); setError(null);
    try {
      await unwrap(api.POST("/api/v1/ai/connections", { body: { provider: newKey.provider as "openai" | "anthropic" | "gemini" | "xai", api_key: newKey.api_key, label: newKey.label } }));
      setNewKey({ ...newKey, api_key: "" }); // key leaves memory; the server only ever returns a hint
      await load();
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  async function testConn(id: string) {
    setBusy(true); setError(null);
    try { const r = await unwrap(api.POST("/api/v1/ai/connections/{connection_id}/test", { params: { path: { connection_id: id } }, body: {} })); setSaved(r.ok ? `Connection OK (${r.model}, ${r.latency_ms} ms)` : `Connection failed: ${r.error}`); await load(); }
    catch (e) { setError(e); } finally { setBusy(false); }
  }
  async function removeConn(id: string) { await unwrap(api.DELETE("/api/v1/ai/connections/{connection_id}", { params: { path: { connection_id: id } } })); await load(); }

  if (!opts && !error) return <Loading />;
  if (!opts) return <ErrorBox error={error} onRetry={load} />;
  const current = opts.providers.find((p) => p.provider === provider);
  const sel = opts.selection;
  return (
    <section className="card stack" aria-labelledby="ai-h">
      <h2 id="ai-h">AI model</h2>
      <div className="row">
        <Badge kind={sel.availability === "ready" ? "ok" : "bad"}>{sel.availability.replace(/_/g, " ")}</Badge>
        <span className="muted">{sel.effective_label !== "none" ? `Current: ${sel.effective_label}` : "No model active"}</span>
      </div>
      {sel.availability_detail && <p className="muted">{sel.availability_detail}</p>}
      {opts.providers.length === 0 && <div className="notice warn">No AI provider is enabled on this service yet. This is an operator task (docs/PHASE2_SETUP.md); you do not need an API key.</div>}
      <div className="grid-2">
        <label>Provider
          <select aria-label="AI provider" value={provider} onChange={(e) => { setProvider(e.target.value as Provider); setChatModel(""); }}>
            {opts.providers.map((p) => <option key={p.provider} value={p.provider} disabled={!p.configured && mode === "operator"}>{p.display_name}{p.configured ? "" : " (not configured by operator)"}</option>)}
          </select>
          {current && <span className="hint">{current.help}</span>}
        </label>
        <label>Model
          <select aria-label="Chat model" value={chatModel} onChange={(e) => setChatModel(e.target.value)}>
            <option value="">Default for this provider</option>
            {(current?.models ?? []).filter((m) => (m.tasks as string[]).includes("chat")).map((m) => <option key={m.id as string} value={m.id as string}>{m.label as string}{m.verified ? "" : " (id unverified)"}</option>)}
          </select>
        </label>
      </div>
      {current?.external && (
        <label className="chip" data-checked={ack}><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />I understand that my feed items and WhatsApp requests will be sent to this external provider</label>
      )}
      {current?.external && <p className="muted"><small>{opts.disclosure_text}</small></p>}
      {usage && <p className="muted"><small>Today: {usage.calls_today}/{usage.call_quota} calls · {usage.tokens_today.toLocaleString()}/{usage.token_quota.toLocaleString()} tokens · est. ${usage.cost_estimate_today_usd}{usage.cost_unknown_calls_today ? ` (+${usage.cost_unknown_calls_today} unpriced)` : ""}. {usage.note}</small></p>}
      {error ? <ErrorBox error={error} /> : null}
      {saved && <div className="notice success" role="status">{saved}</div>}
      <div className="row"><button className="btn-primary" onClick={() => void save()} disabled={busy}>Save AI choice</button></div>
      {opts.byok_enabled && (
        <details>
          <summary>Advanced: use my own API key (optional)</summary>
          <div className="stack" style={{ marginTop: 8 }}>
            <label>Credential mode<select value={mode} onChange={(e) => setMode(e.target.value as "operator" | "byok")}><option value="operator">Service-provided (default)</option><option value="byok">My own key</option></select></label>
            {mode === "byok" && (
              <label>Connection<select value={connId} onChange={(e) => setConnId(e.target.value)}><option value="">Select…</option>{conns.map((c) => <option key={c.id} value={c.id}>{c.display_name} · {c.label || c.key_hint} ({c.status})</option>)}</select></label>
            )}
            <label>Explicit fallback (off by default)<input type="text" value={fallback} onChange={(e) => setFallback(e.target.value)} placeholder="provider/model, e.g. anthropic/claude-haiku-4-5" /></label>
            <h3>My keys</h3>
            {conns.map((c) => <div key={c.id} className="row" style={{ justifyContent: "space-between" }}><span>{c.display_name} · {c.key_hint} <Badge kind={c.status === "ok" ? "ok" : c.status === "untested" ? "" : "bad"}>{c.status}</Badge></span><span className="row"><button className="btn-sm" onClick={() => void testConn(c.id)} disabled={busy}>Test</button><button className="btn-sm btn-danger" onClick={() => void removeConn(c.id)}>Remove</button></span></div>)}
            <div className="grid-2">
              <label>Provider<select aria-label="Key provider" value={newKey.provider} onChange={(e) => setNewKey({ ...newKey, provider: e.target.value as Provider })}>{["openai", "anthropic", "gemini", "xai"].map((p) => <option key={p} value={p}>{p}</option>)}</select></label>
              <label>API key <span className="hint">stored encrypted; never shown again</span><input type="password" value={newKey.api_key} onChange={(e) => setNewKey({ ...newKey, api_key: e.target.value })} autoComplete="off" /></label>
            </div>
            <div className="row"><button className="btn-sm" onClick={() => void addKey()} disabled={busy || newKey.api_key.length < 8}>Add key</button></div>
          </div>
        </details>
      )}
    </section>
  );
}
