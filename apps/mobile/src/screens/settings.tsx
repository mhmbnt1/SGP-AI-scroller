import type { ConnectionOut, DeviceOut, ModelsOut, PreferencesOut, ScheduleOut } from "@focusfeed/contracts";
import { useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { ScrollView, Text, View } from "react-native";

import { Badge, Button, Card, ErrorView, H1, Input, Notice, P, Screen } from "@/components/ui";
import { api, unwrap } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { space, useColors } from "@/theme";

export function SettingsScreen() {
  const c = useColors();
  const router = useRouter();
  const { me, logout, offline } = useAuth();
  const [prefs, setPrefs] = useState<PreferencesOut | null>(null);
  const [models, setModels] = useState<ModelsOut | null>(null);
  const [devices, setDevices] = useState<DeviceOut[]>([]);
  const [conns, setConns] = useState<ConnectionOut[]>([]);
  const [schedules, setSchedules] = useState<ScheduleOut[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [p, m, d, cn, s] = await Promise.all([unwrap(api.GET("/api/v1/preferences")), unwrap(api.GET("/api/v1/models")), unwrap(api.GET("/api/v1/collectors")), unwrap(api.GET("/api/v1/connections")), unwrap(api.GET("/api/v1/schedules"))]);
      setPrefs(p); setModels(m); setDevices(d); setConns(cn); setSchedules(s);
    } catch (e) { setError(e); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  async function exportData() {
    try { const data = await unwrap(api.GET("/api/v1/privacy/export")); setMsg(`Export ready: ${data.batches.length} batches, ${data.saved_items.length} saved items, ${data.feedback.length} feedback records. Download the full JSON from the web app Settings page.`); }
    catch (e) { setError(e); }
  }
  async function deleteAccount() {
    try { await unwrap(api.POST("/api/v1/privacy/delete", { body: { password, confirm: "DELETE" } })); await logout(); }
    catch (e) { setError(e); }
  }
  async function toggleSchedule(s: ScheduleOut) {
    await unwrap(api.PUT("/api/v1/schedules/{schedule_id}", { params: { path: { schedule_id: s.id } }, body: { timezone: s.timezone, local_time: s.local_time, days_of_week: s.days_of_week, platforms: s.platforms as ("youtube" | "instagram" | "demo")[], enabled: !s.enabled, missed_run_policy: s.missed_run_policy as "run_once" | "skip" } }));
    await load();
  }

  return (
    <Screen>
      <ScrollView contentContainerStyle={{ padding: space[4], gap: space[3], paddingBottom: space[6] }}>
        <H1>Settings</H1>
        <P muted>Signed in as {me?.user.email} · server mode: {me?.mode}</P>
        {offline ? <Notice kind="warn">Offline — changes need a connection.</Notice> : null}
        {error ? <ErrorView error={error} onRetry={load} /> : null}
        {msg ? <Notice kind="success">{msg}</Notice> : null}
        <Card>
          <Text style={{ color: c.text, fontWeight: "700" }}>Preferences</Text>
          {prefs ? <P muted>{prefs.platforms.join(", ") || "no platforms"} · {prefs.interests.length} interests · {prefs.exclusions.length} exclusions · {prefs.per_platform_limit}/platform · {prefs.total_budget_minutes} min budget</P> : null}
          <Button title="Edit preferences" onPress={() => router.push("/onboarding")} disabled={offline} />
        </Card>
        <Card>
          <Text style={{ color: c.text, fontWeight: "700" }}>Collector & platforms</Text>
          {devices.length === 0 ? <P muted>No collector paired. Pair one from the web app on your PC — phones can’t run the browser agent.</P> : devices.map((d) => <View key={d.id} style={{ flexDirection: "row", gap: 8, alignItems: "center" }}><Text style={{ color: c.text }}>{d.display_name}</Text><Badge kind={d.revoked_at ? "bad" : d.online ? "ok" : "default"}>{d.revoked_at ? "revoked" : d.online ? "online" : "offline"}</Badge></View>)}
          {conns.map((cn) => <View key={cn.id} style={{ gap: 2 }}><View style={{ flexDirection: "row", gap: 8, alignItems: "center" }}><Text style={{ color: c.text }}>{cn.platform}</Text><Badge kind={cn.status === "available" ? "ok" : cn.enabled ? "bad" : "default"}>{cn.enabled ? cn.status.replace(/_/g, " ") : "disabled"}</Badge></View><Text style={{ color: c.muted, fontSize: 12 }}>{cn.next_step}</Text></View>)}
          <Button title="Connection guide" onPress={() => router.push("/connect")} />
        </Card>
        <Card>
          <Text style={{ color: c.text, fontWeight: "700" }}>Schedules</Text>
          {schedules.length === 0 ? <P muted>No schedules. Create them in the web app.</P> : schedules.map((s) => <View key={s.id} style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", gap: 8 }}><Text style={{ color: c.text, flex: 1 }}>{s.local_time} {s.timezone}{"\n"}<Text style={{ color: c.muted, fontSize: 12 }}>{s.enabled && s.next_run_at ? `next ${new Date(s.next_run_at).toLocaleString()}` : "disabled"}</Text></Text><Button title={s.enabled ? "Disable" : "Enable"} disabled={offline} onPress={() => void toggleSchedule(s)} /></View>)}
        </Card>
        {models ? (
          <Card>
            <Text style={{ color: c.text, fontWeight: "700" }}>Models ({models.provider})</Text>
            <Badge kind={models.provider_healthy ? "ok" : "bad"}>{models.provider_detail}</Badge>
            <P muted>{models.resource_note}</P>
            {models.options.map((o) => <Text key={`${o.purpose}-${o.name}`} style={{ color: c.text }}>{o.purpose}: {o.name}{o.is_default ? " (default)" : ""} — {o.available ? "available" : "not installed"}</Text>)}
            <P muted>Choose a model under Preferences. Private feed content only goes to the configured local provider.</P>
          </Card>
        ) : null}
        <Card>
          <Text style={{ color: c.text, fontWeight: "700" }}>Privacy</Text>
          <Button title="Summarise my export" onPress={() => void exportData()} disabled={offline} />
          <Input label="Password" secureTextEntry value={password} onChangeText={setPassword} autoCapitalize="none" />
          <Input label="Type DELETE to confirm" value={confirm} onChangeText={setConfirm} autoCapitalize="characters" />
          <Button title="Delete my account" variant="danger" disabled={offline || confirm !== "DELETE" || !password} onPress={() => void deleteAccount()} />
          <P muted>Account deletion is never queued offline.</P>
        </Card>
        <Button title="Sign out" onPress={() => void logout()} />
      </ScrollView>
    </Screen>
  );
}
