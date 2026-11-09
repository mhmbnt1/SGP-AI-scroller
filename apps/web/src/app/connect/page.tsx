"use client";

import type { ConnectionOut, DeviceOut, EnrollmentOut, PlatformCapabilityOut } from "@focusfeed/contracts";
import { useCallback, useEffect, useState } from "react";

import { HostedSources } from "@/components/hosted-sources";
import { Badge, ErrorBox, Loading } from "@/components/states";
import { api, unwrap } from "@/lib/api";
import { RequireAuth, useAuth } from "@/lib/auth";

function ConnectInner() {
  const { me } = useAuth();
  const [devices, setDevices] = useState<DeviceOut[] | null>(null);
  const [conns, setConns] = useState<ConnectionOut[] | null>(null);
  const [caps, setCaps] = useState<PlatformCapabilityOut[]>([]);
  const [enrollment, setEnrollment] = useState<EnrollmentOut | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    setError(null);
    try {
      const [d, c, p] = await Promise.all([unwrap(api.GET("/api/v1/collectors")), unwrap(api.GET("/api/v1/connections")), unwrap(api.GET("/api/v1/platforms"))]);
      setDevices(d); setConns(c); setCaps(p);
    } catch (e) { setError(e); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  async function pair() {
    if (busy) return; setBusy(true); setError(null);
    try { setEnrollment(await unwrap(api.POST("/api/v1/collectors/enrollments", { body: { display_name: "My PC" } }))); } catch (e) { setError(e); } finally { setBusy(false); }
  }
  async function revoke(id: string) { await unwrap(api.DELETE("/api/v1/collectors/{device_id}", { params: { path: { device_id: id } } })); await load(); }
  async function toggle(platform: string, enabled: boolean) { await unwrap(api.PUT("/api/v1/connections/{platform}", { params: { path: { platform } }, body: { enabled } })); await load(); }

  if ((!devices || !conns) && !error) return <Loading />;
  const live = me?.mode === "live";
  return (
    <div className="stack">
      <div className="page-head"><div><h1>Connect</h1><p className="muted">Your feeds are collected by a small program on <em>your own PC</em>. You sign into each platform yourself in a dedicated browser window; cookies never leave your machine.</p></div></div>
      {!live && <div className="notice info" role="status">This server runs in <strong>{me?.mode}</strong> mode: batches use labelled synthetic content and no collector is required. Pairing still works for testing the flow.</div>}
      {error ? <ErrorBox error={error} onRetry={load} /> : null}
      <HostedSources />
      <details className="card">
        <summary>Advanced: run the collector on your own PC instead (optional)</summary>
      <section className="stack" style={{ marginTop: 12 }}>
        <h2>1. Install and pair the collector (Windows)</h2>
        <ol>
          <li>Install Python 3.12+ and <code>uv</code>, then in the repository: <code>uv sync --all-packages</code> and <code>uv run playwright install chromium</code>.</li>
          <li>Run <code>uv run focusfeed-collector preflight</code>.</li>
          <li>Click “Generate pairing code”, then run <code>uv run focusfeed-collector pair --api {typeof window !== "undefined" ? window.location.origin : "http://localhost:3000"}</code> and enter the code. It works once and expires in 10 minutes.</li>
        </ol>
        <div className="row"><button className="btn-primary" onClick={pair} disabled={busy}>Generate pairing code</button></div>
        {enrollment && (
          <div className="notice success" role="status" aria-live="polite">
            <strong>Pairing code:</strong> <code style={{ fontSize: "1.3rem" }}>{enrollment.code}</code>
            <p style={{ margin: "6px 0 0" }}><small>Expires {new Date(enrollment.expires_at).toLocaleTimeString()}. {enrollment.instructions}</small></p>
          </div>
        )}
      </section>
      <section className="stack">
        <h2>2. Sign in to platforms on your PC</h2>
        <p>For each platform run <code>uv run focusfeed-collector login youtube</code> (or <code>instagram</code>). A dedicated browser profile opens; sign in with the official page, then close it. Check with <code>uv run focusfeed-collector status</code>.</p>
        <p className="muted"><small>The collector only views, scrolls and extracts. It never posts, likes, follows, messages or deletes. Viewing content may still influence the platform’s own recommendations for you. If a platform asks for verification, complete it yourself in the official app — the collector stops and waits.</small></p>
      </section>
      <section className="stack">
        <h2>3. Keep it running</h2>
        <p><code>uv run focusfeed-collector run</code> must stay running (a console window) for scheduled runs to be collected. Stop it with Ctrl+C. Remove a platform session with <code>uv run focusfeed-collector clear-session &lt;platform&gt;</code>.</p>
      </section>
      </details>
      <section className="stack">
        <h2>Paired collectors</h2>
        {devices?.length === 0 && <p className="muted">No collector paired yet.</p>}
        {devices?.map((d) => (
          <div key={d.id} className="card row" style={{ justifyContent: "space-between" }}>
            <div><strong>{d.display_name}</strong> <span className="muted">{d.os_name} · v{d.collector_version || "?"}</span><div><small className="muted">{d.last_heartbeat_at ? `last seen ${new Date(d.last_heartbeat_at).toLocaleString()}` : "never connected"}</small></div></div>
            <div className="row"><Badge kind={d.revoked_at ? "bad" : d.online ? "ok" : ""}>{d.revoked_at ? "revoked" : d.online ? "online" : "offline"}</Badge>{!d.revoked_at && <button className="btn-sm btn-danger" onClick={() => void revoke(d.id)}>Revoke</button>}</div>
          </div>
        ))}
      </section>
      <section className="stack">
        <h2>Platform status</h2>
        <table>
          <thead><tr><th>Platform</th><th>Capabilities</th><th>Status</th><th>Next step</th><th></th></tr></thead>
          <tbody>
            {caps.map((c) => {
              const conn = conns?.find((x) => x.platform === c.platform);
              return (
                <tr key={c.platform}>
                  <td><strong>{c.display_name}</strong><div><small className="muted">{c.notes}</small></div></td>
                  <td><div className="row">{c.personalized_feed && <Badge>feed</Badge>}{c.public_search && <Badge>search</Badge>}{c.captions && <Badge>captions</Badge>}<Badge kind={c.status === "implemented" ? "ok" : c.status === "synthetic" ? "synthetic" : ""}>{c.status.replace("_", " ")}</Badge><Badge kind={c.live_verified ? "ok" : "bad"}>{c.live_verified ? "live verified" : "not live verified"}</Badge></div></td>
                  <td>{conn ? <Badge kind={conn.status === "available" ? "ok" : conn.enabled ? "bad" : ""}>{conn.enabled ? conn.status.replace(/_/g, " ") : "disabled"}</Badge> : <span className="muted">—</span>}</td>
                  <td className="muted"><small>{conn?.next_step ?? (live ? "Pair a collector first." : "Not required in demo mode.")}</small></td>
                  <td>{c.status !== "disabled" && <button className="btn-sm" onClick={() => void toggle(c.platform, !(conn?.enabled ?? true))}>{conn?.enabled === false ? "Enable" : "Disable"}</button>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>
    </div>
  );
}

export default function ConnectPage() { return <RequireAuth><ConnectInner /></RequireAuth>; }
