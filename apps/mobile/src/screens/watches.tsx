import type { WatchIn, WatchOut } from "@focusfeed/contracts";
import { useCallback, useEffect, useState } from "react";
import { ScrollView, Text, View } from "react-native";

import { Badge, Button, Card, Choice, ErrorView, H1, Input, P, Screen } from "@/components/ui";
import { api, unwrap } from "@/lib/api";
import { space, useColors } from "@/theme";

const TZ = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";

/** Topic watches over public RSS/Atom feeds — separate from personal feeds; bounded alerts. */
export function WatchesScreen() {
  const c = useColors();
  const [list, setList] = useState<WatchOut[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");
  const [topics, setTopics] = useState("");
  const [sources, setSources] = useState("");
  const [mode, setMode] = useState<"digest" | "alert">("digest");
  const [maxAlerts, setMaxAlerts] = useState("3");
  const [quiet, setQuiet] = useState({ start: "", end: "" });
  const load = useCallback(async () => { setError(null); try { setList(await unwrap(api.GET("/api/v1/watches"))); } catch (e) { setError(e); } }, []);
  useEffect(() => { void load(); }, [load]);
  async function create() {
    if (busy) return; setBusy(true); setError(null);
    const body: WatchIn = { name, topics: topics.split(",").map((t) => t.trim()).filter(Boolean), exclusions: [], languages: [], sources: sources.split(/\s+/).filter(Boolean).map((url) => ({ type: "rss", url })), relevance_threshold: 0.5, mode, max_alerts_per_day: Number(maxAlerts) || 3, quiet_hours_start: quiet.start || null, quiet_hours_end: quiet.end || null, poll_minutes: 15, timezone: TZ, enabled: true };
    try { await unwrap(api.POST("/api/v1/watches", { body })); setName(""); setTopics(""); setSources(""); await load(); } catch (e) { setError(e); } finally { setBusy(false); }
  }
  async function remove(id: string) { try { await unwrap(api.DELETE("/api/v1/watches/{watch_id}", { params: { path: { watch_id: id } } })); await load(); } catch (e) { setError(e); } }
  return (
    <Screen>
      <ScrollView contentContainerStyle={{ padding: space[4], gap: space[3], paddingBottom: space[6] }} keyboardShouldPersistTaps="handled">
        <H1>Watches</H1>
        <P muted>Public news sources (RSS/Atom) checked every 15 minutes. New matches go into your digest, or as capped alerts. Nothing is invented: every discovery links to the source.</P>
        {error ? <ErrorView error={error} onRetry={load} /> : null}
        <Card>
          <Input label="Name" value={name} onChangeText={setName} />
          <Input label="Topics" hint="comma-separated" value={topics} onChangeText={setTopics} placeholder="ai, machine learning" autoCapitalize="none" />
          <Input label="Feed URLs" hint="https only, one per line" value={sources} onChangeText={setSources} placeholder="https://example.com/feed.xml" autoCapitalize="none" autoCorrect={false} multiline />
          <Choice label="Mode" value={mode} onChange={setMode} options={[{ value: "digest", label: "Digest only" }, { value: "alert", label: "Alerts (capped)" }]} />
          {mode === "alert" ? (<>
            <Input label="Max alerts per day" value={maxAlerts} onChangeText={setMaxAlerts} keyboardType="number-pad" />
            <Input label="Quiet hours start (HH:MM)" value={quiet.start} onChangeText={(v) => setQuiet({ ...quiet, start: v })} placeholder="22:00" />
            <Input label="Quiet hours end (HH:MM)" value={quiet.end} onChangeText={(v) => setQuiet({ ...quiet, end: v })} placeholder="07:00" />
          </>) : null}
          <Button title="Add watch" variant="primary" loading={busy} disabled={busy || !name || !topics} onPress={() => void create()} />
        </Card>
        {list.length === 0 ? <P muted>No watches yet.</P> : null}
        {list.map((w) => (
          <Card key={w.id}>
            <View style={{ flexDirection: "row", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <Text style={{ color: c.text, fontWeight: "700", flex: 1 }}>{w.name}</Text>
              <Badge kind={w.enabled ? "ok" : "default"}>{w.mode}{w.mode === "alert" ? ` ≤${w.max_alerts_per_day}/day` : ""}</Badge>
            </View>
            <P muted style={{ fontSize: 13 }}>{w.topics.join(", ")} · {w.sources.length} source(s) · every {w.poll_minutes} min · {w.last_polled_at ? `last checked ${new Date(w.last_polled_at).toLocaleString()}` : "not checked yet"}{w.last_error ? ` · error: ${w.last_error}` : ""}</P>
            <Button title="Delete" variant="danger" onPress={() => void remove(w.id)} />
          </Card>
        ))}
      </ScrollView>
    </Screen>
  );
}
