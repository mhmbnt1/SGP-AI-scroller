"use client";

import type { BatchOut } from "@focusfeed/contracts";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { RecommendationCard } from "@/components/recommendation-card";
import { Badge, ErrorBox, Loading } from "@/components/states";
import { api, unwrap } from "@/lib/api";
import { RequireAuth } from "@/lib/auth";

function BatchInner() {
  const { id } = useParams<{ id: string }>();
  const [batch, setBatch] = useState<BatchOut | null>(null);
  const [error, setError] = useState<unknown>(null);
  const load = useCallback(async () => { setError(null); try { setBatch(await unwrap(api.GET("/api/v1/batches/{batch_id}", { params: { path: { batch_id: id } } }))); } catch (e) { setError(e); } }, [id]);
  useEffect(() => { void load(); }, [load]);
  if (error) return <ErrorBox error={error} onRetry={load} title="Batch unavailable" />;
  if (!batch) return <Loading />;
  return (
    <div className="stack">
      <h1>{batch.mode === "search" ? `Search: ${batch.query}` : "Daily batch"}</h1>
      <div className="row"><Badge>{new Date(batch.generated_at).toLocaleString()}</Badge><Badge kind={batch.completion_status === "partial" ? "bad" : "ok"}>{batch.completion_status}</Badge>{batch.is_synthetic && <Badge kind="synthetic">synthetic</Badge>}</div>
      {batch.recommendations.map((r) => <RecommendationCard key={r.id} rec={r} />)}
    </div>
  );
}

export default function BatchPage() { return <RequireAuth><BatchInner /></RequireAuth>; }
