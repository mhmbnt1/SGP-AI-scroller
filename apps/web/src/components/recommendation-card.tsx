"use client";

import { analysisLabel, formatDuration, type FeedbackAction, type RecommendationOut } from "@focusfeed/contracts";
import Link from "next/link";
import { useState } from "react";

import { Badge } from "@/components/states";

export interface RecommendationCardProps {
  rec: RecommendationOut;
  onFeedback?: (rec: RecommendationOut, action: FeedbackAction) => Promise<void>;
  onToggleSave?: (rec: RecommendationOut) => Promise<void>;
  onOpen?: (rec: RecommendationOut) => void;
}

export function RecommendationCard({ rec, onFeedback, onToggleSave, onOpen }: RecommendationCardProps) {
  const [busy, setBusy] = useState<string | null>(null);
  const [why, setWhy] = useState(false);
  const item = rec.item;
  const title = item.title || item.caption?.slice(0, 80) || item.canonical_url;

  async function run(key: string, fn: () => Promise<void>) {
    if (busy) return; // prevents accidental duplicate submissions
    setBusy(key);
    try {
      await fn();
    } finally {
      setBusy(null);
    }
  }

  return (
    <article className="card rec" data-hidden={rec.hidden} aria-labelledby={`rec-${rec.id}`}>
      <div className="rec-head">
        <div>
          <div className="rec-meta">
            <span className="rec-rank">#{rec.rank}</span>
            <Badge kind="platform">{item.platform}</Badge>
            {item.is_synthetic && <Badge kind="synthetic">synthetic demo</Badge>}
            <Badge>{analysisLabel(rec.analysis_kind)}</Badge>
            <span>{formatDuration(rec.estimated_seconds, rec.duration_known)}</span>
          </div>
          <h3 className="rec-title" id={`rec-${rec.id}`}>{title}</h3>
          <div className="rec-meta">{item.creator_name || item.creator_handle ? <span>by {item.creator_name ?? item.creator_handle}</span> : null}{rec.topics.length > 0 && <span>· {rec.topics.slice(0, 4).join(", ")}</span>}</div>
        </div>
      </div>
      {rec.summary && <p className="rec-summary">{rec.summary}</p>}
      <div className="rec-actions">
        <a className="btn btn-sm btn-primary" href={item.canonical_url} target="_blank" rel="noopener noreferrer nofollow" onClick={() => onOpen?.(rec)}>
          Open on {item.platform} ↗
        </a>
        <Link className="btn btn-sm" href={`/items/${item.id}`}>Details</Link>
        <button className="btn-sm btn-ghost" aria-expanded={why} aria-controls={`why-${rec.id}`} onClick={() => setWhy((v) => !v)}>Why this?</button>
        {onToggleSave && (
          <button className="btn-sm btn-ghost" aria-pressed={rec.saved} disabled={busy !== null} onClick={() => void run("save", () => onToggleSave(rec))}>
            {rec.saved ? "★ Saved" : "☆ Save"}
          </button>
        )}
        {onFeedback && (
          <>
            <button className="btn-sm btn-ghost" disabled={busy !== null} onClick={() => void run("relevant", () => onFeedback(rec, "relevant"))} aria-label="Mark relevant">👍 Relevant</button>
            <button className="btn-sm btn-ghost" disabled={busy !== null} onClick={() => void run("not_relevant", () => onFeedback(rec, "not_relevant"))} aria-label="Mark not relevant">👎 Not relevant</button>
            <button className="btn-sm btn-ghost" disabled={busy !== null} onClick={() => void run("not_interested", () => onFeedback(rec, "not_interested"))}>Not interested</button>
            <button className="btn-sm btn-ghost" disabled={busy !== null} onClick={() => void run("hide_creator", () => onFeedback(rec, "hide_creator"))}>Hide creator</button>
          </>
        )}
      </div>
      {why && (
        <div className="rec-why" id={`why-${rec.id}`}>
          <p style={{ margin: 0 }}>{rec.explanation}</p>
          <details style={{ marginTop: 6 }}>
            <summary>Score components</summary>
            <table aria-label="Score components">
              <tbody>
                {Object.entries(rec.components).filter(([k]) => !["explanation_len"].includes(k)).map(([k, v]) => (
                  <tr key={k}><th scope="row">{k}</th><td>{typeof v === "number" ? v.toFixed(3) : String(v)}</td></tr>
                ))}
              </tbody>
            </table>
          </details>
        </div>
      )}
    </article>
  );
}
