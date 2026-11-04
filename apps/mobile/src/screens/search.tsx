import type { BatchOut, FeedbackAction, PlatformCapabilityOut, RecommendationOut } from "@focusfeed/contracts";
import { useEffect, useState } from "react";
import { FlatList, Pressable, Text, View } from "react-native";

import { JobProgress, useJob } from "@/components/job-progress";
import { RecommendationCard } from "@/components/recommendation-card";
import { Button, ErrorView, H1, Input, Notice, P, Screen } from "@/components/ui";
import { api, unwrap } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { space, useColors } from "@/theme";

type Plat = "youtube" | "instagram" | "tiktok" | "x" | "linkedin" | "demo";

export function SearchScreen() {
  const c = useColors();
  const { offline } = useAuth();
  const [query, setQuery] = useState("");
  const [caps, setCaps] = useState<PlatformCapabilityOut[]>([]);
  const [selected, setSelected] = useState<Plat[]>([]);
  const [jobId, setJobId] = useState<string | null>(null);
  const [batch, setBatch] = useState<BatchOut | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void (async () => {
      try {
        const [cp, p] = await Promise.all([unwrap(api.GET("/api/v1/platforms")), unwrap(api.GET("/api/v1/preferences"))]);
        setCaps(cp.filter((x) => x.status !== "disabled" && (x.public_search || x.personalized_feed)));
        setSelected(((p.platforms ?? []) as Plat[]).length ? (p.platforms as Plat[]) : ["demo"]);
      } catch (e) { setError(e); }
    })();
  }, []);
  const { job, cancel } = useJob(jobId, async (j) => {
    setJobId(null);
    if (j.batch_id) { try { setBatch(await unwrap(api.GET("/api/v1/batches/{batch_id}", { params: { path: { batch_id: j.batch_id } } }))); } catch (e) { setError(e); } }
  });
  async function submit() {
    if (busy || jobId || query.trim().length < 2) return;
    setBusy(true); setError(null); setBatch(null);
    try { const a = await unwrap(api.POST("/api/v1/search", { body: { mode: "search", query: query.trim(), platforms: selected.length ? selected : null } })); setJobId(a.job_id); }
    catch (e) { setError(e); } finally { setBusy(false); }
  }
  async function feedback(rec: RecommendationOut, action: FeedbackAction) {
    await unwrap(api.POST("/api/v1/feedback", { body: { item_id: rec.item.id, action } }));
    if (action === "not_interested" || action === "hide_creator") setBatch((b) => (b ? { ...b, recommendations: b.recommendations.map((r) => (r.id === rec.id || (action === "hide_creator" && r.item.creator_handle === rec.item.creator_handle) ? { ...r, hidden: true } : r)) } : b));
  }
  async function toggleSave(rec: RecommendationOut) {
    if (rec.saved) await unwrap(api.DELETE("/api/v1/saved/{item_id}", { params: { path: { item_id: rec.item.id } } })); else await unwrap(api.POST("/api/v1/saved", { body: { item_id: rec.item.id } }));
    setBatch((b) => (b ? { ...b, recommendations: b.recommendations.map((r) => (r.id === rec.id ? { ...r, saved: !rec.saved } : r)) } : b));
  }
  const header = (
    <View style={{ gap: space[3], marginBottom: space[3] }}>
      <H1>Search</H1>
      <P muted>Your explicit request takes priority over long-term interests. Exclusions still apply.</P>
      <Input label="Request" placeholder="High-protein recipes under 20 minutes" value={query} onChangeText={setQuery} onSubmitEditing={() => void submit()} returnKeyType="search" maxLength={500} />
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }} accessibilityRole="radiogroup">
        {caps.map((cp) => { const p = cp.platform as Plat; const on = selected.includes(p); return (
          <Pressable key={p} accessibilityRole="checkbox" accessibilityState={{ checked: on }} accessibilityLabel={cp.display_name} onPress={() => setSelected(on ? selected.filter((x) => x !== p) : [...selected, p])}
            style={{ minHeight: 40, paddingHorizontal: 12, justifyContent: "center", borderRadius: 999, borderWidth: 1, borderColor: on ? c.accent : c.border, backgroundColor: on ? c.accentSoft : c.surface }}>
            <Text style={{ color: c.text }}>{cp.display_name}</Text>
          </Pressable>); })}
      </View>
      <Button title={jobId ? "Searching…" : "Search"} variant="primary" disabled={busy || !!jobId || offline || query.trim().length < 2} onPress={() => void submit()} />
      {offline ? <Notice kind="warn">Search needs a connection.</Notice> : null}
      {error ? <ErrorView error={error} /> : null}
      {job ? <JobProgress job={job} onCancel={() => void cancel()} /> : null}
      {batch ? <P>Results for “{batch.query}” ({batch.recommendations.length})</P> : null}
    </View>
  );
  return (
    <Screen>
      <FlatList data={batch?.recommendations.filter((r) => !r.hidden) ?? []} keyExtractor={(r) => r.id} renderItem={({ item }) => <RecommendationCard rec={item} onFeedback={feedback} onToggleSave={toggleSave} />}
        ListHeaderComponent={header} ListFooterComponent={batch ? <Notice kind="info">End of results — finite by design.</Notice> : undefined}
        ItemSeparatorComponent={() => <View style={{ height: space[3] }} />} contentContainerStyle={{ padding: space[4], paddingBottom: space[6] }} keyboardShouldPersistTaps="handled" />
    </Screen>
  );
}
