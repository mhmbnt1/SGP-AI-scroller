import type { ScheduleIn, ScheduleOut } from "@focusfeed/contracts";
import { useCallback, useEffect, useState } from "react";
import { ScrollView, Text, View } from "react-native";

import { Badge, Button, Card, Check, Choice, ErrorView, H1, Input, P, Screen } from "@/components/ui";
import { api, unwrap } from "@/lib/api";
import { space, useColors } from "@/theme";

const TZ = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
const EMPTY: ScheduleIn = { timezone: TZ, local_time: "08:00", days_of_week: [0, 1, 2, 3, 4, 5, 6], platforms: [], enabled: true, missed_run_policy: "run_once", ready_by_time: "19:00", lead_minutes: 60, deliver_time: null, deliver_channels: ["app"] };

/** Readiness schedule: “ready by” (collect earlier) vs “send at” (WhatsApp delivery time). */
export function SchedulesScreen() {
  const c = useColors();
  const [list, setList] = useState<ScheduleOut[]>([]);
  const [form, setForm] = useState<ScheduleIn>(EMPTY);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => { setError(null); try { setList(await unwrap(api.GET("/api/v1/schedules"))); } catch (e) { setError(e); } }, []);
  useEffect(() => { void load(); }, [load]);
  async function create() {
    if (busy) return; setBusy(true); setError(null);
    try { await unwrap(api.POST("/api/v1/schedules", { body: form })); setForm(EMPTY); await load(); } catch (e) { setError(e); } finally { setBusy(false); }
  }
  async function toggle(s: ScheduleOut) {
    try { await unwrap(api.PUT("/api/v1/schedules/{schedule_id}", { params: { path: { schedule_id: s.id } }, body: { timezone: s.timezone, local_time: s.local_time, days_of_week: s.days_of_week, platforms: s.platforms as ScheduleIn["platforms"], enabled: !s.enabled, missed_run_policy: s.missed_run_policy as ScheduleIn["missed_run_policy"], ready_by_time: s.ready_by_time, lead_minutes: s.lead_minutes, deliver_time: s.deliver_time, deliver_channels: s.deliver_channels as ScheduleIn["deliver_channels"] } })); await load(); }
    catch (e) { setError(e); }
  }
  async function remove(id: string) { try { await unwrap(api.DELETE("/api/v1/schedules/{schedule_id}", { params: { path: { schedule_id: id } } })); await load(); } catch (e) { setError(e); } }
  const wa = (form.deliver_channels ?? []).includes("whatsapp");
  return (
    <Screen>
      <ScrollView contentContainerStyle={{ padding: space[4], gap: space[3], paddingBottom: space[6] }} keyboardShouldPersistTaps="handled">
        <H1>Schedules</H1>
        <P muted>Your batch is collected on the service ahead of time so it is waiting when you want it. “Ready by” and “send at” are different: collection starts before “ready by”; WhatsApp delivery happens at “send at”.</P>
        {error ? <ErrorView error={error} onRetry={load} /> : null}
        <Card>
          <Input label="Ready by (HH:MM, local)" value={form.ready_by_time ?? ""} onChangeText={(v) => setForm({ ...form, ready_by_time: v || null })} placeholder="19:00" keyboardType="numbers-and-punctuation" />
          <Input label="Lead time (minutes)" hint="how early collection starts" value={String(form.lead_minutes)} onChangeText={(v) => setForm({ ...form, lead_minutes: Number(v) || 60 })} keyboardType="number-pad" />
          <Check label="Also deliver to WhatsApp (needs notifications enabled)" value={wa} onChange={(v) => setForm({ ...form, deliver_channels: v ? ["app", "whatsapp"] : ["app"] })} />
          {wa ? <Input label="Send to WhatsApp at (HH:MM)" hint="empty = as soon as ready" value={form.deliver_time ?? ""} onChangeText={(v) => setForm({ ...form, deliver_time: v || null })} placeholder="19:30" /> : null}
          <Choice label="If a run is missed" value={form.missed_run_policy} onChange={(v) => setForm({ ...form, missed_run_policy: v })} options={[{ value: "run_once", label: "Run once when back" }, { value: "skip", label: "Skip" }]} />
          <P muted style={{ fontSize: 13 }}>Time zone: {form.timezone}. Every day. Platforms: all connected.</P>
          <Button title="Add schedule" variant="primary" loading={busy} disabled={busy} onPress={() => void create()} />
        </Card>
        {list.length === 0 ? <P muted>No schedules yet.</P> : null}
        {list.map((s) => (
          <Card key={s.id}>
            <View style={{ flexDirection: "row", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <Text style={{ color: c.text, fontWeight: "700", flex: 1 }}>{s.ready_by_time ? `Ready by ${s.ready_by_time}` : s.local_time} {s.timezone}{s.deliver_channels.includes("whatsapp") ? ` · WhatsApp${s.deliver_time ? ` at ${s.deliver_time}` : ""}` : ""}</Text>
              <Badge kind={s.enabled ? "ok" : "default"}>{s.enabled ? "enabled" : "disabled"}</Badge>
            </View>
            <P muted style={{ fontSize: 13 }}>{s.enabled && s.next_run_at ? `next collection ${new Date(s.next_run_at).toLocaleString()}` : "disabled"}{s.last_run_at ? ` · last ${new Date(s.last_run_at).toLocaleString()}` : ""}</P>
            <View style={{ flexDirection: "row", gap: 8 }}><Button title={s.enabled ? "Disable" : "Enable"} onPress={() => void toggle(s)} /><Button title="Delete" variant="danger" onPress={() => void remove(s.id)} /></View>
          </Card>
        ))}
      </ScrollView>
    </Screen>
  );
}
