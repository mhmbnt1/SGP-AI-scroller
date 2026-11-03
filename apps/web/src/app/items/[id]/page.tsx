"use client";

import { analysisLabel, formatDuration, type ItemDetailOut } from "@focusfeed/contracts";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Badge, ErrorBox, Loading } from "@/components/states";
import { api, unwrap } from "@/lib/api";
import { RequireAuth } from "@/lib/auth";

function ItemInner() {
  const params = useParams<{ id: string }>();
  const [detail, setDetail] = useState<ItemDetailOut | null>(null);
  const [error, setError] = useState<unknown>(null);
  const load = useCallback(async () => {
    setError(null);
    try { setDetail(await unwrap(api.GET("/api/v1/items/{item_id}", { params: { path: { item_id: params.id } } }))); } catch (e) { setError(e); }
  }, [params.id]);
  useEffect(() => { void load(); }, [load]);

  if (error) return <ErrorBox error={error} onRetry={load} title="Item unavailable" />;
  if (!detail) return <Loading />;
  const { item, recommendation: rec } = detail;
  return (
    <article className="stack">
      <div className="row"><Badge kind="platform">{item.platform}</Badge>{item.is_synthetic && <Badge kind="synthetic">synthetic demo</Badge>}<Badge>{analysisLabel(detail.analysis_kind)}</Badge></div>
      <h1>{item.title ?? "Untitled"}</h1>
      <p className="muted">{item.creator_name ?? item.creator_handle ?? "Unknown creator"}{item.duration_seconds != null ? ` · ${formatDuration(item.duration_seconds, true)}` : " · duration unknown"}{item.published_at ? ` · ${new Date(item.published_at).toLocaleDateString()}` : ""}{item.language ? ` · ${item.language}` : ""}</p>
      <div className="row"><a className="btn btn-primary" href={item.canonical_url} target="_blank" rel="noopener noreferrer nofollow">Open original source ↗</a></div>
      {item.caption && <section className="card"><h3>Caption</h3><p style={{ whiteSpace: "pre-wrap" }}>{item.caption}</p></section>}
      {rec && (
        <section className="card stack">
          <h3>Why this was recommended</h3>
          <p>{rec.explanation}</p>
          <h3>Evidence-supported summary</h3>
          <p>{rec.summary}</p>
          <p className="muted">{detail.coverage_label}</p>
          {rec.topics.length > 0 && <div className="row">{rec.topics.map((t) => <Badge key={t}>{t}</Badge>)}</div>}
        </section>
      )}
      <section className="card stack">
        <h3>Evidence ({detail.evidence.length})</h3>
        {detail.evidence.length === 0 && <p className="muted">No transcript or frame evidence was captured. The summary above is based on metadata only.</p>}
        {detail.evidence.map((ev) => (
          <details key={ev.id}>
            <summary>{ev.kind} · source {ev.transcript_source} · coverage {Math.round(ev.coverage_ratio * 100)}% · {ev.extraction_method}</summary>
            {ev.segments.length > 0 && (
              <table aria-label="Transcript segments"><thead><tr><th>Start</th><th>End</th><th>Text</th></tr></thead>
                <tbody>{ev.segments.map((s, i) => { const seg = s as { start_s: number; end_s: number; text: string }; return <tr key={i}><td>{seg.start_s}s</td><td>{seg.end_s}s</td><td>{seg.text}</td></tr>; })}</tbody></table>
            )}
            {ev.frames.length > 0 && <ul>{ev.frames.map((f, i) => { const fr = f as { timestamp_s: number; observation: string }; return <li key={i}>{fr.timestamp_s}s — {fr.observation || "no observation"}</li>; })}</ul>}
          </details>
        ))}
      </section>
      {detail.feedback.length > 0 && <p className="muted">Your feedback: {detail.feedback.join(", ")}</p>}
    </article>
  );
}

export default function ItemPage() {
  return <RequireAuth><ItemInner /></RequireAuth>;
}
