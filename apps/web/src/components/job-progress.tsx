"use client";

import type { JobDetailOut } from "@focusfeed/contracts";
import { useEffect, useRef, useState } from "react";

import { api, unwrap } from "@/lib/api";

const TERMINAL = new Set(["completed", "partial", "needs_user_action", "cancelled", "failed"]);

/** Polls an accepted job (authenticated polling with backoff) until a terminal state. */
export function useJob(jobId: string | null, onDone?: (job: JobDetailOut) => void) {
  const [job, setJob] = useState<JobDetailOut | null>(null);
  const [error, setError] = useState<unknown>(null);
  const doneRef = useRef(onDone);
  doneRef.current = onDone;

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    let delay = 1000;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        const j = await unwrap(api.GET("/api/v1/jobs/{job_id}", { params: { path: { job_id: jobId } } }));
        if (cancelled) return;
        setJob(j);
        setError(null);
        if (TERMINAL.has(j.state)) { doneRef.current?.(j); return; }
        delay = 1000;
      } catch (e) {
        if (cancelled) return;
        setError(e);
        delay = Math.min(delay * 2, 10_000); // reconnect with backoff
      }
      timer = setTimeout(tick, delay);
    };
    void tick();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [jobId]);

  async function cancel() {
    if (!jobId) return;
    const j = await unwrap(api.POST("/api/v1/jobs/{job_id}/cancel", { params: { path: { job_id: jobId } } }));
    setJob((prev) => (prev ? { ...prev, ...j } : prev));
  }
  return { job, error, cancel };
}

export function JobProgress({ job, onCancel }: { job: JobDetailOut; onCancel?: () => void }) {
  const terminal = TERMINAL.has(job.state);
  return (
    <section className="card stack" aria-live="polite">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <strong>{job.mode === "search" ? "Searching" : "Collecting your batch"} — {job.state.replace(/_/g, " ")}</strong>
        {!terminal && onCancel && <button className="btn-sm btn-danger" onClick={onCancel} disabled={job.cancel_requested}>{job.cancel_requested ? "Cancelling…" : "Cancel"}</button>}
      </div>
      <div className="progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={job.progress} aria-label="Job progress"><div style={{ width: `${job.progress}%` }} /></div>
      <p className="muted" style={{ margin: 0 }}>{job.next_step}</p>
      {Object.keys(job.platform_states).length > 0 && (
        <div className="row">{Object.entries(job.platform_states).map(([p, s]) => <span key={p} className={`badge ${s === "available" ? "ok" : s === "pending" ? "" : "bad"}`}>{p}: {String(s)}</span>)}</div>
      )}
      {job.events.length > 0 && (
        <details>
          <summary>Progress log ({job.events.length})</summary>
          <ol className="event-log">{job.events.map((e) => <li key={e.seq}>{e.kind}: {e.message}</li>)}</ol>
        </details>
      )}
    </section>
  );
}
