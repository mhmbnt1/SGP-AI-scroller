"use client";

import type { BatchSummaryOut, JobOut } from "@focusfeed/contracts";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { Badge, Empty, ErrorBox, Loading } from "@/components/states";
import { api, unwrap } from "@/lib/api";
import { RequireAuth } from "@/lib/auth";

function HistoryInner() {
  const [batches, setBatches] = useState<BatchSummaryOut[] | null>(null);
  const [jobs, setJobs] = useState<JobOut[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const load = useCallback(async () => {
    setError(null);
    try {
      const [b, j] = await Promise.all([unwrap(api.GET("/api/v1/batches")), unwrap(api.GET("/api/v1/jobs"))]);
      setBatches(b.items); setJobs(j.items);
    } catch (e) { setError(e); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  if (error) return <ErrorBox error={error} onRetry={load} />;
  if (!batches || !jobs) return <Loading />;
  return (
    <div className="stack">
      <h1>History</h1>
      <section className="stack">
        <h2>Batches</h2>
        {batches.length === 0 && <Empty title="No batches yet." />}
        {batches.map((b) => (
          <Link key={b.id} href={`/history/${b.id}`} className="card" style={{ textDecoration: "none", color: "inherit" }}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <strong>{b.mode === "search" ? `Search: ${b.query}` : "Daily batch"}</strong>
              <span className="row"><Badge>{b.recommendation_count} items</Badge><Badge>~{Math.round(b.total_estimated_seconds / 60)} min</Badge><Badge kind={b.completion_status === "partial" ? "bad" : "ok"}>{b.completion_status}</Badge>{b.is_synthetic && <Badge kind="synthetic">synthetic</Badge>}</span>
            </div>
            <small className="muted">{new Date(b.generated_at).toLocaleString()}{b.consumed_at ? " · finished" : ""}</small>
          </Link>
        ))}
      </section>
      <section className="stack">
        <h2>Runs</h2>
        <table>
          <thead><tr><th>When</th><th>Mode</th><th>State</th><th>Platforms</th><th>Note</th></tr></thead>
          <tbody>
            {jobs.map((j) => <tr key={j.id}><td>{new Date(j.created_at).toLocaleString()}</td><td>{j.mode}{j.source === "schedule" ? " (scheduled)" : ""}</td><td><Badge kind={["completed"].includes(j.state) ? "ok" : ["failed", "cancelled", "needs_user_action"].includes(j.state) ? "bad" : ""}>{j.state}</Badge></td><td>{Object.entries(j.platform_states).map(([p, s]) => `${p}: ${String(s)}`).join(", ")}</td><td className="muted">{j.stop_reason}</td></tr>)}
            {jobs.length === 0 && <tr><td colSpan={5} className="muted">No runs yet.</td></tr>}
          </tbody>
        </table>
      </section>
    </div>
  );
}

export default function HistoryPage() { return <RequireAuth><HistoryInner /></RequireAuth>; }
