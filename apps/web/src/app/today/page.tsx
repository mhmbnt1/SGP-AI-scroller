"use client";

import type { BatchOut, FeedbackAction, RecommendationOut, TodayOut } from "@focusfeed/contracts";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { JobProgress, useJob } from "@/components/job-progress";
import { RecommendationCard } from "@/components/recommendation-card";
import { Badge, Empty, ErrorBox, Loading } from "@/components/states";
import { api, unwrap } from "@/lib/api";
import { RequireAuth } from "@/lib/auth";

function TodayInner() {
  const [today, setToday] = useState<TodayOut | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [platform, setPlatform] = useState<string>("all");
  const [starting, setStarting] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const t = await unwrap(api.GET("/api/v1/batches/today"));
      setToday(t);
      if (t.active_job) setJobId(t.active_job.id);
    } catch (e) { setError(e); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const { job, cancel } = useJob(jobId, () => { setJobId(null); void load(); });

  async function startRun() {
    if (starting) return;
    setStarting(true);
    setError(null);
    try {
      // No client key: the server collapses accidental double-submits of an *active* run and never
      // blocks a new run behind a finished one.
      const accepted = await unwrap(api.POST("/api/v1/jobs", { body: { mode: "daily" } }));
      setJobId(accepted.job_id);
    } catch (e) { setError(e); } finally { setStarting(false); }
  }

  function patchRec(id: string, patch: Partial<RecommendationOut>) {
    setToday((t) => (t?.batch ? { ...t, batch: { ...t.batch, recommendations: t.batch.recommendations.map((r) => (r.id === id ? { ...r, ...patch } : r)) } } : t));
  }
  async function feedback(rec: RecommendationOut, action: FeedbackAction) {
    await unwrap(api.POST("/api/v1/feedback", { body: { item_id: rec.item.id, action } }));
    if (action === "not_interested") patchRec(rec.id, { hidden: true });
    if (action === "hide_creator") setToday((t) => (t?.batch ? { ...t, batch: { ...t.batch, recommendations: t.batch.recommendations.map((r) => (r.item.creator_handle === rec.item.creator_handle ? { ...r, hidden: true } : r)) } } : t));
  }
  async function toggleSave(rec: RecommendationOut) {
    if (rec.saved) await unwrap(api.DELETE("/api/v1/saved/{item_id}", { params: { path: { item_id: rec.item.id } } }));
    else await unwrap(api.POST("/api/v1/saved", { body: { item_id: rec.item.id } }));
    patchRec(rec.id, { saved: !rec.saved });
  }
  async function markSeen(rec: RecommendationOut) {
    if (!today?.batch) return;
    void api.POST("/api/v1/batches/{batch_id}/recommendations/{rec_id}/seen", { params: { path: { batch_id: today.batch.id, rec_id: rec.id } } });
    patchRec(rec.id, { seen: true });
  }
  async function complete(batch: BatchOut) {
    await unwrap(api.POST("/api/v1/batches/{batch_id}/complete", { params: { path: { batch_id: batch.id } } }));
    await load();
  }

  const batch = today?.batch ?? null;
  const visible = useMemo(() => (batch?.recommendations ?? []).filter((r) => !r.hidden && (platform === "all" || r.platform === platform)), [batch, platform]);
  const platforms = useMemo(() => Array.from(new Set((batch?.recommendations ?? []).map((r) => r.platform))), [batch]);
  const minutes = batch ? Math.round(batch.total_estimated_seconds / 60) : 0;

  if (!today && !error) return <Loading label="Loading today’s batch" />;
  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Today</h1>
          {today && <p className="muted">{today.message}</p>}
        </div>
        <div className="row">
          {today?.collector_status === "not_paired" && <Link className="btn" href="/connect">Pair collector</Link>}
          <button className="btn-primary" onClick={startRun} disabled={starting || !!jobId}>{jobId ? "Running…" : "Refresh batch"}</button>
        </div>
      </div>
      {today?.collector_status === "offline" && <div className="notice warn" role="status">Your collector is offline. Start <code>focusfeed-collector run</code> on your PC; the next run will wait for it.</div>}
      {error ? <ErrorBox error={error} onRetry={load} /> : null}
      {job && <JobProgress job={job} onCancel={() => void cancel()} />}
      {job?.state === "needs_user_action" && <div className="notice warn" role="alert">{job.stop_reason} — <Link href="/connect">open Connect</Link> for the next step.</div>}
      {batch ? (
        <>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <div className="row">
              <Badge>{batch.recommendations.length} items</Badge>
              <Badge>~{minutes} min total</Badge>
              <Badge kind={batch.completion_status === "partial" ? "bad" : "ok"}>{batch.completion_status}</Badge>
              {batch.is_synthetic && <Badge kind="synthetic">synthetic demo data</Badge>}
            </div>
            {platforms.length > 1 && (
              <div className="row" role="group" aria-label="Filter by platform">
                <button className={`btn-sm ${platform === "all" ? "btn-primary" : ""}`} onClick={() => setPlatform("all")} aria-pressed={platform === "all"}>All</button>
                {platforms.map((p) => <button key={p} className={`btn-sm ${platform === p ? "btn-primary" : ""}`} onClick={() => setPlatform(p)} aria-pressed={platform === p}>{p}</button>)}
              </div>
            )}
          </div>
          {batch.completion_status === "partial" && <div className="notice warn">Some platforms did not complete: {Object.entries((batch.platform_summary as { per_platform?: Record<string, number> }).per_platform ?? {}).map(([p, n]) => `${p}: ${n}`).join(", ")}. Valid results from the others are shown.</div>}
          <div className="stack">
            {visible.map((rec) => <RecommendationCard key={rec.id} rec={rec} onFeedback={feedback} onToggleSave={toggleSave} onOpen={markSeen} />)}
            {visible.length === 0 && <Empty title="Nothing left in this view.">Everything here is hidden or filtered. Change the filter or refresh the batch.</Empty>}
          </div>
          <div className="complete" role="status">
            <h2>{batch.consumed_at ? "You finished today’s batch." : "That’s the whole batch."}</h2>
            <p className="muted">No more to scroll. {batch.consumed_at ? "Come back after your next scheduled run." : "Mark it done and step away."}</p>
            {!batch.consumed_at && <button className="btn-primary" onClick={() => void complete(batch)}>I’m done for today</button>}
          </div>
        </>
      ) : (
        !job && <Empty title="No batch yet.">Press “Refresh batch” to generate your first finite batch{today?.collector_status === "not_required" ? " (demo mode uses labelled synthetic content)" : ""}.</Empty>
      )}
    </div>
  );
}

export default function TodayPage() {
  return <RequireAuth><TodayInner /></RequireAuth>;
}
