"use client";

import type { ConnectSessionOut } from "@focusfeed/contracts";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { Badge, ErrorBox } from "@/components/states";
import { api, unwrap } from "@/lib/api";
import { RequireAuth } from "@/lib/auth";

/** Phone-driven hosted login: screenshots in, taps/keys out. Credentials go into the official page only. */
function ConnectInner() {
  const { platform } = useParams<{ platform: string }>();
  const router = useRouter();
  const [consent, setConsent] = useState(false);
  const [session, setSession] = useState<ConnectSessionOut | null>(null);
  const [token, setToken] = useState<string>("");
  const [frame, setFrame] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [error, setError] = useState<unknown>(null);
  const seqRef = useRef(0);
  const hdr = useCallback(() => ({ "X-Connect-Token": token }), [token]);

  async function start() {
    setError(null);
    try {
      const out = await unwrap(api.POST("/api/v1/sources/{platform}/connect-sessions", { params: { path: { platform } }, body: { consent } }));
      setSession(out.session); setToken(out.token);
    } catch (e) { setError(e); }
  }
  useEffect(() => {
    if (!session || !token || ["completed", "cancelled", "expired", "failed"].includes(session.state)) return;
    let stop = false;
    const tick = async () => {
      try {
        const s = await unwrap(api.GET("/api/v1/sources/connect-sessions/{session_id}", { params: { path: { session_id: session.id }, header: { "X-Connect-Token": token } } }));
        if (stop) return;
        setSession(s);
        if (s.frame_seq !== seqRef.current) {
          const r = await fetch(`/api/v1/sources/connect-sessions/${session.id}/frame`, { headers: hdr(), credentials: "include" });
          if (r.status === 200) { const blob = await r.blob(); setFrame((old) => { if (old) URL.revokeObjectURL(old); return URL.createObjectURL(blob); }); seqRef.current = s.frame_seq; }
        }
      } catch (e) { if (!stop) setError(e); }
      if (!stop) setTimeout(tick, 1000);
    };
    void tick();
    return () => { stop = true; };
  }, [session?.id, session?.state, token, hdr]); // eslint-disable-line react-hooks/exhaustive-deps

  async function input(body: { kind: "tap" | "type" | "key" | "scroll" | "back"; x?: number; y?: number; text?: string; key?: string; dy?: number }) {
    if (!session) return;
    try { await unwrap(api.POST("/api/v1/sources/connect-sessions/{session_id}/input", { params: { path: { session_id: session.id }, header: { "X-Connect-Token": token } }, body })); } catch (e) { setError(e); }
  }
  async function finish() { if (!session) return; try { setSession(await unwrap(api.POST("/api/v1/sources/connect-sessions/{session_id}/finish", { params: { path: { session_id: session.id }, header: { "X-Connect-Token": token } } }))); } catch (e) { setError(e); } }
  async function cancel() { if (!session) return; try { setSession(await unwrap(api.POST("/api/v1/sources/connect-sessions/{session_id}/cancel", { params: { path: { session_id: session.id }, header: { "X-Connect-Token": token } } }))); } catch (e) { setError(e); } }

  const done = session && ["completed", "cancelled", "expired", "failed"].includes(session.state);
  return (
    <div className="stack">
      <h1>Connect {platform}</h1>
      {!session && (
        <div className="card stack">
          <p>You will sign in on the <strong>official {platform} page</strong>, rendered by our always-on service inside a private browser profile that only your account can use. Your phone shows the screen and sends your taps and typing. Nothing else is recorded; no AI sees this screen.</p>
          <p className="muted"><small>Trust note: the service operator administers that server; this design does not claim they are technically unable to access it. Sessions expire after 10 minutes. The platform may ask for extra verification; complete it on the page or in the platform’s own app. Viewing content through the service may influence the platform’s own recommendations for you.</small></p>
          <label className="chip" data-checked={consent}><input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />I consent to hosting my {platform} session on this service for collection</label>
          {error ? <ErrorBox error={error} /> : null}
          <div className="row"><button className="btn-primary" disabled={!consent} onClick={() => void start()}>Start sign-in</button><Link className="btn" href="/connect">Back</Link></div>
        </div>
      )}
      {session && (
        <div className="card stack">
          <div className="row"><Badge kind={session.state === "active" ? "ok" : done ? "bad" : ""}>{session.state}</Badge>{session.current_url_host && <Badge>{session.current_url_host}</Badge>}<span className="muted">expires {new Date(session.expires_at).toLocaleTimeString()}</span></div>
          {!done && (
            <>
              {frame ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={frame} alt="Remote sign-in screen" style={{ width: "100%", maxWidth: 412, border: "1px solid var(--ff-border)", borderRadius: 8, touchAction: "manipulation", display: "block" }}
                  onClick={(e) => { const r = (e.target as HTMLImageElement).getBoundingClientRect(); void input({ kind: "tap", x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height }); }} />
              ) : <div className="skeleton" style={{ height: 300, maxWidth: 412 }} aria-label="Waiting for the first screen" />}
              <div className="row">
                <input type="text" value={text} onChange={(e) => setText(e.target.value)} placeholder="Type here, then Send (goes to the focused field on the page)" aria-label="Text to type" autoComplete="off" />
                <button className="btn-sm" onClick={() => { if (text) { void input({ kind: "type", text }); setText(""); } }}>Send text</button>
              </div>
              <div className="row">
                <button className="btn-sm" onClick={() => void input({ kind: "key", key: "Enter" })}>Enter</button>
                <button className="btn-sm" onClick={() => void input({ kind: "key", key: "Backspace" })}>Backspace</button>
                <button className="btn-sm" onClick={() => void input({ kind: "key", key: "Tab" })}>Tab</button>
                <button className="btn-sm" onClick={() => void input({ kind: "scroll", dy: 600 })}>Scroll ↓</button>
                <button className="btn-sm" onClick={() => void input({ kind: "scroll", dy: -600 })}>Scroll ↑</button>
                <button className="btn-sm" onClick={() => void input({ kind: "back" })}>Back</button>
              </div>
              <div className="row"><button className="btn-primary" onClick={() => void finish()}>Done — I’m signed in</button><button className="btn-danger btn-sm" onClick={() => void cancel()}>Cancel</button></div>
            </>
          )}
          {done && (
            <div className="stack">
              <p>{session.state === "completed" ? `Result: ${session.result_status.replace(/_/g, " ") || "checked"}.` : `Session ${session.state}${session.ended_reason ? `: ${session.ended_reason}` : ""}.`}</p>
              <div className="row"><button className="btn-primary" onClick={() => router.push("/connect")}>Back to sources</button></div>
            </div>
          )}
          {error ? <ErrorBox error={error} /> : null}
        </div>
      )}
    </div>
  );
}

export default function ConnectPlatformPage() { return <RequireAuth><ConnectInner /></RequireAuth>; }
