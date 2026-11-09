"use client";

import type { NotificationOut, WhatsAppLinkStartOut, WhatsAppStatusOut } from "@focusfeed/contracts";
import { useCallback, useEffect, useState } from "react";

import { Badge, ErrorBox, Loading } from "@/components/states";
import { api, unwrap } from "@/lib/api";

export function WhatsAppSettings() {
  const [st, setSt] = useState<WhatsAppStatusOut | null>(null);
  const [link, setLink] = useState<WhatsAppLinkStartOut | null>(null);
  const [history, setHistory] = useState<NotificationOut[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [ack, setAck] = useState(false);
  const [digests, setDigests] = useState(true);
  const [alerts, setAlerts] = useState(true);
  const load = useCallback(async () => {
    setError(null);
    try { const [s, h] = await Promise.all([unwrap(api.GET("/api/v1/channels/whatsapp")), unwrap(api.GET("/api/v1/notifications"))]); setSt(s); setHistory(h); setDigests(s.digest_enabled); setAlerts(s.alerts_enabled); setAck(s.external_disclosure_acknowledged); } catch (e) { setError(e); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  async function startLink() { setError(null); try { setLink(await unwrap(api.POST("/api/v1/channels/whatsapp/link"))); } catch (e) { setError(e); } }
  async function setPrefs(opt: boolean) {
    setError(null);
    try { await unwrap(api.PUT("/api/v1/channels/whatsapp/preferences", { body: { proactive_opt_in: opt, digest_enabled: digests, alerts_enabled: alerts, acknowledge_external_processing: ack } })); await load(); } catch (e) { setError(e); }
  }
  async function unlink() { await unwrap(api.DELETE("/api/v1/channels/whatsapp")); setLink(null); await load(); }

  if (!st && !error) return <Loading />;
  if (!st) return <ErrorBox error={error} onRetry={load} />;
  return (
    <section className="card stack" aria-labelledby="wa-h">
      <h2 id="wa-h">WhatsApp</h2>
      <div className="row"><Badge kind={st.transport_mode === "live" ? "ok" : st.transport_mode === "mock" ? "synthetic" : "bad"}>transport: {st.transport_mode}</Badge><Badge kind={st.linked ? "ok" : ""}>{st.linked ? `linked ${st.display_hint}` : "not linked"}</Badge>{st.linked && <Badge kind={st.proactive_opt_in ? "ok" : ""}>{st.proactive_opt_in ? (st.paused_until ? "paused" : "notifications on") : "notifications off"}</Badge>}</div>
      <p className="muted"><small>{st.eligibility_note}</small></p>
      {st.transport_mode === "disabled" && <div className="notice warn">WhatsApp is not enabled on this service (operator setup: business sender, webhook, templates — see docs/WHATSAPP.md).</div>}
      {!st.linked && st.transport_mode !== "disabled" && (
        <div className="stack">
          <p>Link your <em>own</em> WhatsApp from this phone: get a one-time code and send it to the FocusFeed number. We never ask for your phone number here; the link is confirmed from the message you send.</p>
          <div className="row"><button className="btn-primary" onClick={() => void startLink()}>Connect WhatsApp</button></div>
          {link && (
            <div className="notice success" role="status">
              <p>Send this message within 10 minutes (one use): <code style={{ fontSize: "1.1rem" }}>{link.message_text}</code></p>
              <div className="row">
                {link.deep_link && <a className="btn btn-primary" href={link.deep_link} target="_blank" rel="noopener noreferrer">Open WhatsApp with the code</a>}
                <button className="btn-sm" onClick={() => void navigator.clipboard?.writeText(link.message_text)}>Copy code</button>
                <button className="btn-sm" onClick={() => void load()}>I sent it — check</button>
              </div>
              <small className="muted">{link.instructions}</small>
            </div>
          )}
        </div>
      )}
      {st.linked && (
        <div className="stack">
          <label className="chip" data-checked={digests}><input type="checkbox" checked={digests} onChange={(e) => setDigests(e.target.checked)} />Send my scheduled digests here</label>
          <label className="chip" data-checked={alerts}><input type="checkbox" checked={alerts} onChange={(e) => setAlerts(e.target.checked)} />Send watch alerts here (respects caps and quiet hours)</label>
          {!st.external_disclosure_acknowledged && <label className="chip" data-checked={ack}><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />I understand my WhatsApp requests are processed by our servers and my chosen AI provider, not protected by WhatsApp end-to-end encryption once received</label>}
          <div className="row">
            {!st.proactive_opt_in ? <button className="btn-primary" onClick={() => void setPrefs(true)}>Enable notifications</button> : <button onClick={() => void setPrefs(false)}>Stop notifications</button>}
            <button className="btn-danger btn-sm" onClick={() => void unlink()}>Unlink</button>
          </div>
          <p className="muted"><small>Replying STOP in WhatsApp has the same effect as “Stop notifications”. Proactive messages outside WhatsApp’s 24-hour service window need an operator-approved template{st.templates_approved.digest ? " (digest template approved)" : " (no digest template approved yet — digests stay in the app)"}.</small></p>
        </div>
      )}
      {error ? <ErrorBox error={error} /> : null}
      {history.length > 0 && (
        <details><summary>Delivery history ({history.length})</summary>
          <table><thead><tr><th>When</th><th>Kind</th><th>State</th><th>Preview</th></tr></thead>
            <tbody>{history.map((h) => <tr key={h.id}><td>{new Date(h.created_at).toLocaleString()}</td><td>{h.kind}{h.proactive ? " (proactive)" : ""}</td><td><Badge kind={["delivered", "read", "accepted"].includes(h.state) ? "ok" : ["failed", "expired", "cancelled"].includes(h.state) ? "bad" : ""}>{h.state}</Badge>{h.last_error && <div><small className="muted">{h.last_error}</small></div>}</td><td className="muted"><small>{h.body_preview}</small></td></tr>)}</tbody></table>
        </details>
      )}
    </section>
  );
}
