"use client";

import type { SourceOut } from "@focusfeed/contracts";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { Badge, ErrorBox, Loading } from "@/components/states";
import { api, unwrap } from "@/lib/api";

/** Standard (hosted) source connection — phone-usable. Local-PC mode is under Advanced. */
export function HostedSources() {
  const [rows, setRows] = useState<SourceOut[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const load = useCallback(async () => { setError(null); try { setRows(await unwrap(api.GET("/api/v1/sources"))); } catch (e) { setError(e); } }, []);
  useEffect(() => { void load(); }, [load]);
  async function disconnect(platform: string) { await unwrap(api.DELETE("/api/v1/sources/{platform}/hosted", { params: { path: { platform } } })); await load(); }
  async function setLocation(location: "hosted" | "local") { await unwrap(api.PUT("/api/v1/sources/location", { body: { location } })); await load(); }
  if (!rows && !error) return <Loading />;
  if (!rows) return <ErrorBox error={error} onRetry={load} />;
  const location = rows[0]?.collection_location ?? "hosted";
  return (
    <section className="card stack" aria-labelledby="src-h">
      <h2 id="src-h">Your sources</h2>
      <p className="muted">Collection runs on our always-on service while your phone is offline. Sign in once from your phone; reconnect when a session expires.</p>
      <table>
        <thead><tr><th>Source</th><th>Status</th><th>Phone-only support</th><th></th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.platform}>
              <td><strong>{r.display_name}</strong><div><small className="muted">{r.support_note}</small></div></td>
              <td><Badge kind={r.hosted_status === "connected" || r.hosted_status === "available" ? "ok" : r.hosted_status === "unsupported" || r.hosted_status === "local_mode" ? "" : "bad"}>{r.hosted_status.replace(/_/g, " ")}</Badge><div><small className="muted">{r.next_step}</small></div></td>
              <td><Badge kind={r.phone_only_support === "unverified" ? "synthetic" : r.phone_only_support === "unsupported" ? "bad" : ""}>{r.phone_only_support}</Badge>{!r.live_verified && r.implemented && <div><small className="muted">not live-verified</small></div>}</td>
              <td className="row">
                {r.implemented && location === "hosted" && (r.hosted_status === "not_connected" || r.hosted_status === "needs_reauth" || r.hosted_status === "challenge_required") && <Link className="btn btn-sm btn-primary" href={`/connect/${r.platform}`}>{r.hosted_status === "not_connected" ? "Connect" : "Reconnect"}</Link>}
                {r.implemented && r.hosted_status === "connected" && <button className="btn-sm btn-danger" onClick={() => void disconnect(r.platform)}>Disconnect</button>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <details>
        <summary>Advanced: collection location ({location})</summary>
        <p className="muted"><small>“Hosted” (default) runs the browser on the service. “Local” uses the optional collector on your own PC — it must be paired, signed in and running for scheduled digests; nothing on your phone can replace it.</small></p>
        <div className="row"><button className={`btn-sm ${location === "hosted" ? "btn-primary" : ""}`} onClick={() => void setLocation("hosted")}>Hosted (service)</button><button className={`btn-sm ${location === "local" ? "btn-primary" : ""}`} onClick={() => void setLocation("local")}>Local PC collector</button></div>
      </details>
    </section>
  );
}
