"use client";

import { errorMessage } from "@focusfeed/contracts";
import type { ReactNode } from "react";

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="stack" role="status" aria-live="polite" aria-busy="true">
      <span className="sr-only">{label}</span>
      <div className="skeleton" style={{ height: 28, width: "40%" }} />
      <div className="skeleton" style={{ height: 110 }} />
      <div className="skeleton" style={{ height: 110 }} />
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="notice" role="status">
      <strong>{title}</strong>
      {children && <div style={{ marginTop: 8 }}>{children}</div>}
    </div>
  );
}

export function ErrorBox({ error, onRetry, title = "Something went wrong" }: { error: unknown; onRetry?: () => void; title?: string }) {
  const status = (error as { status?: number } | undefined)?.status;
  const offline = typeof navigator !== "undefined" && navigator.onLine === false;
  const heading = offline ? "You appear to be offline" : status === 403 ? "Not allowed" : status === 401 ? "Your session expired" : title;
  const code = (error as { error?: { code?: string; request_id?: string } } | undefined)?.error;
  return (
    <div className="notice danger" role="alert">
      <strong>{heading}</strong>
      <p style={{ margin: "6px 0" }}>{offline ? "Check your connection and try again." : errorMessage(error)}</p>
      {code?.request_id && <small className="muted">Reference: {code.request_id}</small>}
      {onRetry && <div style={{ marginTop: 8 }}><button className="btn-sm" onClick={onRetry}>Try again</button></div>}
    </div>
  );
}

export function Badge({ children, kind = "" }: { children: ReactNode; kind?: string }) {
  return <span className={`badge ${kind}`}>{children}</span>;
}
