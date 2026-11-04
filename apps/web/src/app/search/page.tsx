"use client";

import type { BatchOut, FeedbackAction, PlatformCapabilityOut, RecommendationOut } from "@focusfeed/contracts";
import { useEffect, useState, type FormEvent } from "react";

import { JobProgress, useJob } from "@/components/job-progress";
import { RecommendationCard } from "@/components/recommendation-card";
import { Empty, ErrorBox } from "@/components/states";
import { api, unwrap } from "@/lib/api";
import { RequireAuth } from "@/lib/auth";

type Plat = "youtube" | "instagram" | "tiktok" | "x" | "linkedin" | "demo";

function SearchInner() {
  const [query, setQuery] = useState("");
  const [caps, setCaps] = useState<PlatformCapabilityOut[]>([]);
  const [selected, setSelected] = useState<Plat[]>([]);
  const [jobId, setJobId] = useState<string | null>(null);
  const [batch, setBatch] = useState<BatchOut | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void (async () => {
      try {
        const [c, p] = await Promise.all([unwrap(api.GET("/api/v1/platforms")), unwrap(api.GET("/api/v1/preferences"))]);
        setCaps(c);
        const plats = (p.platforms ?? []) as Plat[];
        setSelected(plats.length ? plats : (["demo"] as Plat[]));
      } catch (e) { setError(e); }
    })();
  }, []);

  const { job, cancel } = useJob(jobId, async (j) => {
    setJobId(null);
    if (j.batch_id) {
      try { setBatch(await unwrap(api.GET("/api/v1/batches/{batch_id}", { params: { path: { batch_id: j.batch_id } } }))); } catch (e) { setError(e); }
    }
  });

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy || query.trim().length < 2) return;
    setBusy(true); setError(null); setBatch(null);
    try {
      const accepted = await unwrap(api.POST("/api/v1/search", { body: { mode: "search", query: query.trim(), platforms: selected.length ? selected : null } }));
      setJobId(accepted.job_id);
    } catch (err) { setError(err); } finally { setBusy(false); }
  }
  async function feedback(rec: RecommendationOut, action: FeedbackAction) {
    await unwrap(api.POST("/api/v1/feedback", { body: { item_id: rec.item.id, action } }));
    if (action === "not_interested" || action === "hide_creator") setBatch((b) => (b ? { ...b, recommendations: b.recommendations.map((r) => (r.id === rec.id || (action === "hide_creator" && r.item.creator_handle === rec.item.creator_handle) ? { ...r, hidden: true } : r)) } : b));
  }
  async function toggleSave(rec: RecommendationOut) {
    if (rec.saved) await unwrap(api.DELETE("/api/v1/saved/{item_id}", { params: { path: { item_id: rec.item.id } } }));
    else await unwrap(api.POST("/api/v1/saved", { body: { item_id: rec.item.id } }));
    setBatch((b) => (b ? { ...b, recommendations: b.recommendations.map((r) => (r.id === rec.id ? { ...r, saved: !rec.saved } : r)) } : b));
  }

  return (
    <div className="stack">
      <div className="page-head"><div><h1>Search</h1><p className="muted">Describe what you want right now. Your explicit request takes priority over your long-term interests; your exclusions still apply.</p></div></div>
      <form className="card stack" onSubmit={submit}>
        <label>Request<input type="text" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Find high-protein recipes that take under 20 minutes" minLength={2} maxLength={500} required /></label>
        <div className="checks" role="group" aria-label="Platforms to search">
          {caps.filter((c) => c.status !== "disabled").map((c) => {
            const p = c.platform as Plat;
            const checked = selected.includes(p);
            const searchable = c.public_search || c.personalized_feed;
            return (
              <label key={p} className="chip" data-checked={checked}>
                <input type="checkbox" checked={checked} disabled={!searchable} onChange={(e) => setSelected(e.target.checked ? [...selected, p] : selected.filter((x) => x !== p))} />
                {c.display_name}{!c.public_search && c.personalized_feed ? <small className="muted"> (feed filter)</small> : null}{!searchable ? <small className="muted"> (unsupported)</small> : null}
              </label>
            );
          })}
        </div>
        <div className="row"><button type="submit" className="btn-primary" disabled={busy || !!jobId}>{jobId ? "Searching…" : "Search"}</button></div>
      </form>
      {error ? <ErrorBox error={error} /> : null}
      {job && <JobProgress job={job} onCancel={() => void cancel()} />}
      {batch && (
        <section className="stack" aria-label="Search results">
          <h2>Results for “{batch.query}” <small className="muted">({batch.recommendations.length})</small></h2>
          {batch.recommendations.filter((r) => !r.hidden).map((rec) => <RecommendationCard key={rec.id} rec={rec} onFeedback={feedback} onToggleSave={toggleSave} />)}
          {batch.recommendations.length === 0 && <Empty title="No matching content was found within budget.">Try fewer constraints or another platform.</Empty>}
          <div className="complete"><h2>End of results.</h2><p className="muted">Finite by design.</p></div>
        </section>
      )}
    </div>
  );
}

export default function SearchPage() {
  return <RequireAuth><SearchInner /></RequireAuth>;
}
