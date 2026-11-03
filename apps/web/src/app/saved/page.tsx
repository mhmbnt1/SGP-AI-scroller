"use client";

import type { SavedOut } from "@focusfeed/contracts";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { Badge, Empty, ErrorBox, Loading } from "@/components/states";
import { api, unwrap } from "@/lib/api";
import { RequireAuth } from "@/lib/auth";

function SavedInner() {
  const [items, setItems] = useState<SavedOut[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const load = useCallback(async () => { setError(null); try { setItems((await unwrap(api.GET("/api/v1/saved"))).items); } catch (e) { setError(e); } }, []);
  useEffect(() => { void load(); }, [load]);
  async function remove(id: string) {
    await unwrap(api.DELETE("/api/v1/saved/{item_id}", { params: { path: { item_id: id } } }));
    setItems((xs) => xs?.filter((x) => x.item.id !== id) ?? null);
  }
  if (error) return <ErrorBox error={error} onRetry={load} />;
  if (!items) return <Loading />;
  return (
    <div className="stack">
      <h1>Saved</h1>
      {items.length === 0 && <Empty title="Nothing saved yet.">Save items from your batch to keep them here.</Empty>}
      {items.map(({ item, saved_at }) => (
        <article key={item.id} className="card rec">
          <div className="rec-meta"><Badge kind="platform">{item.platform}</Badge>{item.is_synthetic && <Badge kind="synthetic">synthetic</Badge>}<span>saved {new Date(saved_at).toLocaleDateString()}</span></div>
          <h3 className="rec-title">{item.title ?? item.caption?.slice(0, 80) ?? item.canonical_url}</h3>
          <div className="rec-actions">
            <a className="btn btn-sm btn-primary" href={item.canonical_url} target="_blank" rel="noopener noreferrer nofollow">Open ↗</a>
            <Link className="btn btn-sm" href={`/items/${item.id}`}>Details</Link>
            <button className="btn-sm btn-ghost" onClick={() => void remove(item.id)}>Remove</button>
          </div>
        </article>
      ))}
    </div>
  );
}

export default function SavedPage() { return <RequireAuth><SavedInner /></RequireAuth>; }
