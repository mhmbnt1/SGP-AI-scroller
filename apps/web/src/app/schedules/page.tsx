"use client";

import type { ScheduleIn, ScheduleOut } from "@focusfeed/contracts";
import { useCallback, useEffect, useState, type FormEvent } from "react";

import { Badge, Empty, ErrorBox, Loading } from "@/components/states";
import { api, unwrap } from "@/lib/api";
import { RequireAuth } from "@/lib/auth";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
type Form = Required<ScheduleIn>;
type Plat = Form["platforms"][number];

function SchedulesInner() {
  const [list, setList] = useState<ScheduleOut[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [form, setForm] = useState<Form>({ timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC", local_time: "08:00", days_of_week: [0, 1, 2, 3, 4, 5, 6], platforms: [], enabled: true, missed_run_policy: "run_once" });
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => { setError(null); try { setList(await unwrap(api.GET("/api/v1/schedules"))); } catch (e) { setError(e); } }, []);
  useEffect(() => { void load(); }, [load]);

  async function create(e: FormEvent) {
    e.preventDefault(); if (busy) return; setBusy(true); setError(null);
    try { await unwrap(api.POST("/api/v1/schedules", { body: form })); await load(); } catch (err) { setError(err); } finally { setBusy(false); }
  }
  async function toggle(s: ScheduleOut) {
    await unwrap(api.PUT("/api/v1/schedules/{schedule_id}", { params: { path: { schedule_id: s.id } }, body: { timezone: s.timezone, local_time: s.local_time, days_of_week: s.days_of_week, platforms: s.platforms as Plat[], enabled: !s.enabled, missed_run_policy: s.missed_run_policy as Form["missed_run_policy"] } }));
    await load();
  }
  async function remove(s: ScheduleOut) { await unwrap(api.DELETE("/api/v1/schedules/{schedule_id}", { params: { path: { schedule_id: s.id } } })); await load(); }

  if (!list && !error) return <Loading />;
  return (
    <div className="stack">
      <div className="page-head"><div><h1>Schedules</h1><p className="muted">Runs happen at your local time (DST-aware) and never overlap. In live mode your collector must be running at that time.</p></div></div>
      {error ? <ErrorBox error={error} onRetry={load} /> : null}
      <form className="card stack" onSubmit={create} aria-label="New schedule">
        <div className="grid-2">
          <label>Local time<input type="time" value={form.local_time} onChange={(e) => setForm({ ...form, local_time: e.target.value })} required /></label>
          <label>Timezone (IANA)<input type="text" value={form.timezone} onChange={(e) => setForm({ ...form, timezone: e.target.value })} required maxLength={64} /></label>
        </div>
        <div className="checks" role="group" aria-label="Days of week">
          {DAYS.map((d, i) => { const on = form.days_of_week.includes(i); return <label key={d} className="chip" data-checked={on}><input type="checkbox" checked={on} onChange={(e) => setForm({ ...form, days_of_week: e.target.checked ? [...form.days_of_week, i] : form.days_of_week.filter((x) => x !== i) })} />{d}</label>; })}
        </div>
        <div className="checks" role="group" aria-label="Platforms (empty = your preference platforms)">
          {(["youtube", "instagram", "demo"] as Plat[]).map((p) => { const on = form.platforms.includes(p); return <label key={p} className="chip" data-checked={on}><input type="checkbox" checked={on} onChange={(e) => setForm({ ...form, platforms: e.target.checked ? [...form.platforms, p] : form.platforms.filter((x) => x !== p) })} />{p}</label>; })}
        </div>
        <label>Missed runs<select value={form.missed_run_policy} onChange={(e) => setForm({ ...form, missed_run_policy: e.target.value as Form["missed_run_policy"] })}><option value="run_once">Run once when the worker is back</option><option value="skip">Skip until the next slot</option></select></label>
        <div className="row"><button type="submit" className="btn-primary" disabled={busy || form.days_of_week.length === 0}>Add schedule</button></div>
      </form>
      {list && list.length === 0 && <Empty title="No schedules yet." />}
      {list?.map((s) => (
        <div key={s.id} className="card row" style={{ justifyContent: "space-between" }}>
          <div>
            <strong>{s.local_time} {s.timezone}</strong> · {s.days_of_week.map((d) => DAYS[d]).join(", ")} · {s.platforms.length ? s.platforms.join(", ") : "preference platforms"}
            <div className="muted"><small>{s.enabled && s.next_run_at ? `Next run ${new Date(s.next_run_at).toLocaleString()}` : "Disabled"}{s.last_run_at ? ` · last ran ${new Date(s.last_run_at).toLocaleString()}` : ""}</small></div>
          </div>
          <div className="row"><Badge kind={s.enabled ? "ok" : ""}>{s.enabled ? "enabled" : "disabled"}</Badge><button className="btn-sm" onClick={() => void toggle(s)}>{s.enabled ? "Disable" : "Enable"}</button><button className="btn-sm btn-danger" onClick={() => void remove(s)}>Delete</button></div>
        </div>
      ))}
    </div>
  );
}

export default function SchedulesPage() { return <RequireAuth><SchedulesInner /></RequireAuth>; }
