"use client";

import type { WatchIn, WatchOut } from "@focusfeed/contracts";
import { useCallback, useEffect, useState, type FormEvent } from "react";

import { Badge, Empty, ErrorBox, Loading } from "@/components/states";
import { api, unwrap } from "@/lib/api";
import { RequireAuth } from "@/lib/auth";

type Form = Required<WatchIn>;
const EMPTY: Form = { name: "", topics: [], exclusions: [], languages: [], sources: [], relevance_threshold: 0.5, mode: "digest", max_alerts_per_day: 3, quiet_hours_start: null, quiet_hours_end: null, poll_minutes: 15, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC", enabled: true };

function WatchesInner() {
  const [list, setList] = useState<WatchOut[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [form, setForm] = useState<Form>(EMPTY);
  const [topics, setTopics] = useState("");
  const [sources, setSources] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => { setError(null); try { setList(await unwrap(api.GET("/api/v1/watches"))); } catch (e) { setError(e); } }, []);
  useEffect(() => { void load(); }, [load]);
  async function create(e: FormEvent) {
    e.preventDefault(); if (busy) return; setBusy(true); setError(null);
    try {
      await unwrap(api.POST("/api/v1/watches", { body: { ...form, topics: topics.split(",").map((t) => t.trim()).filter(Boolean), sources: sources.split(/\s+/).filter(Boolean).map((url) => ({ type: "rss" as const, url })) } }));
      setForm(EMPTY); setTopics(""); setSources(""); await load();
    } catch (err) { setError(err); } finally { setBusy(false); }
  }
  async function remove(id: string) { await unwrap(api.DELETE("/api/v1/watches/{watch_id}", { params: { path: { watch_id: id } } })); await load(); }
  if (!list && !error) return <Loading />;
  return (
    <div className="stack">
      <div className="page-head"><div><h1>Watches</h1><p className="muted">Public news sources (RSS/Atom) checked every 15+ minutes — clearly separate from your personal feeds. New matches go into your digest, or as bounded alerts.</p></div></div>
      {error ? <ErrorBox error={error} onRetry={load} /> : null}
      <form className="card stack" onSubmit={create} aria-label="New watch">
        <div className="grid-2">
          <label>Name<input type="text" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required maxLength={120} /></label>
          <label>Topics <span className="hint">comma-separated whole words</span><input type="text" value={topics} onChange={(e) => setTopics(e.target.value)} placeholder="ai, machine learning" required /></label>
        </div>
        <label>RSS/Atom feed URLs <span className="hint">one per line; https only; public feeds</span><textarea value={sources} onChange={(e) => setSources(e.target.value)} placeholder="https://example.com/feed.xml" /></label>
        <div className="grid-2">
          <label>Mode<select value={form.mode} onChange={(e) => setForm({ ...form, mode: e.target.value as Form["mode"] })}><option value="digest">Digest only</option><option value="alert">Prompt alerts (capped)</option></select></label>
          <label>Max alerts per day<input type="number" min={1} max={20} value={form.max_alerts_per_day} onChange={(e) => setForm({ ...form, max_alerts_per_day: Number(e.target.value) })} /></label>
          <label>Quiet hours start<input type="time" value={form.quiet_hours_start ?? ""} onChange={(e) => setForm({ ...form, quiet_hours_start: e.target.value || null })} /></label>
          <label>Quiet hours end<input type="time" value={form.quiet_hours_end ?? ""} onChange={(e) => setForm({ ...form, quiet_hours_end: e.target.value || null })} /></label>
          <label>Relevance threshold<input type="number" min={0} max={1} step={0.1} value={form.relevance_threshold} onChange={(e) => setForm({ ...form, relevance_threshold: Number(e.target.value) })} /></label>
          <label>Check every (minutes)<input type="number" min={15} max={1440} value={form.poll_minutes} onChange={(e) => setForm({ ...form, poll_minutes: Number(e.target.value) })} /></label>
        </div>
        <div className="row"><button type="submit" className="btn-primary" disabled={busy}>Add watch</button></div>
      </form>
      {list && list.length === 0 && <Empty title="No watches yet." />}
      {list?.map((w) => (
        <div key={w.id} className="card row" style={{ justifyContent: "space-between" }}>
          <div><strong>{w.name}</strong> · {w.topics.join(", ")} · {w.mode}{w.mode === "alert" ? ` (≤${w.max_alerts_per_day}/day)` : ""}<div className="muted"><small>{w.sources.length} source(s) · every {w.poll_minutes} min · {w.last_polled_at ? `last checked ${new Date(w.last_polled_at).toLocaleString()}` : "not checked yet"}{w.last_error ? ` · error: ${w.last_error}` : ""}</small></div></div>
          <div className="row"><Badge kind={w.enabled ? "ok" : ""}>{w.enabled ? "enabled" : "disabled"}</Badge><button className="btn-sm btn-danger" onClick={() => void remove(w.id)}>Delete</button></div>
        </div>
      ))}
    </div>
  );
}

export default function WatchesPage() { return <RequireAuth><WatchesInner /></RequireAuth>; }
