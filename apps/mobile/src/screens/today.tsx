import type { BatchOut, FeedbackAction, RecommendationOut, TodayOut } from "@focusfeed/contracts";
import { useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { FlatList, RefreshControl, Text, View } from "react-native";

import { JobProgress, useJob } from "@/components/job-progress";
import { RecommendationCard } from "@/components/recommendation-card";
import { Badge, Button, ErrorView, H1, Loading, Notice, P, Screen } from "@/components/ui";
import { api, cacheGet, cacheSet, unwrap } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { space, useColors } from "@/theme";

export function TodayScreen() {
  const { me, offline } = useAuth();
  const router = useRouter();
  const c = useColors();
  const [today, setToday] = useState<TodayOut | null>(null);
  const [fromCache, setFromCache] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const userId = me?.user.id ?? "";

  const load = useCallback(async () => {
    setError(null);
    try {
      const t = await unwrap(api.GET("/api/v1/batches/today"));
      setToday(t); setFromCache(false);
      if (t.active_job) setJobId(t.active_job.id);
      if (t.batch) await cacheSet(userId, "today", t);
    } catch (e) {
      const cached = userId ? await cacheGet<TodayOut>(userId, "today") : null;
      if (cached) { setToday(cached); setFromCache(true); } else setError(e);
    }
  }, [userId]);
  useEffect(() => { void load(); }, [load]);
  const { job, cancel } = useJob(jobId, () => { setJobId(null); void load(); });

  async function start() {
    if (starting || jobId) return;
    setStarting(true); setError(null);
    try { const a = await unwrap(api.POST("/api/v1/jobs", { body: { mode: "daily", idempotency_key: `mobile-${new Date().toISOString().slice(0, 16)}` } })); setJobId(a.job_id); }
    catch (e) { setError(e); } finally { setStarting(false); }
  }
  function patch(id: string, p: Partial<RecommendationOut>) {
    setToday((t) => (t?.batch ? { ...t, batch: { ...t.batch, recommendations: t.batch.recommendations.map((r) => (r.id === id ? { ...r, ...p } : r)) } } : t));
  }
  async function feedback(rec: RecommendationOut, action: FeedbackAction) {
    await unwrap(api.POST("/api/v1/feedback", { body: { item_id: rec.item.id, action } }));
    if (action === "not_interested") patch(rec.id, { hidden: true });
    if (action === "hide_creator") setToday((t) => (t?.batch ? { ...t, batch: { ...t.batch, recommendations: t.batch.recommendations.map((r) => (r.item.creator_handle === rec.item.creator_handle ? { ...r, hidden: true } : r)) } } : t));
  }
  async function toggleSave(rec: RecommendationOut) {
    if (rec.saved) await unwrap(api.DELETE("/api/v1/saved/{item_id}", { params: { path: { item_id: rec.item.id } } }));
    else await unwrap(api.POST("/api/v1/saved", { body: { item_id: rec.item.id } }));
    patch(rec.id, { saved: !rec.saved });
  }
  async function complete(b: BatchOut) {
    await unwrap(api.POST("/api/v1/batches/{batch_id}/complete", { params: { path: { batch_id: b.id } } }));
    await load();
  }

  const batch = today?.batch ?? null;
  const visible = (batch?.recommendations ?? []).filter((r) => !r.hidden);
  const header = (
    <View style={{ gap: space[3], marginBottom: space[3] }}>
      <H1>Today</H1>
      {today ? <P muted>{today.message}</P> : null}
      {(offline || fromCache) ? <Notice kind="warn">You’re offline. Showing your last batch from this device. Feedback and new runs need a connection.</Notice> : null}
      {today?.collector_status === "not_paired" ? <Notice kind="info">Pair your collector from the web app (Connect page) to collect from your real feeds. Phones don’t run the browser agent.</Notice> : null}
      {today?.collector_status === "offline" ? <Notice kind="warn">Your collector is offline. Start it on your PC; the next run will wait for it.</Notice> : null}
      {error ? <ErrorView error={error} onRetry={load} /> : null}
      {job ? <JobProgress job={job} onCancel={() => void cancel()} /> : null}
      {job?.state === "needs_user_action" ? <Notice kind="warn">{job.stop_reason}</Notice> : null}
      <View style={{ flexDirection: "row", gap: space[2], flexWrap: "wrap" }}>
        <Button title={jobId ? "Running…" : "Refresh batch"} variant="primary" disabled={starting || !!jobId || offline} onPress={() => void start()} />
        {batch ? <><Badge>{batch.recommendations.length} items</Badge><Badge>~{Math.round(batch.total_estimated_seconds / 60)} min</Badge><Badge kind={batch.completion_status === "partial" ? "bad" : "ok"}>{batch.completion_status}</Badge>{batch.is_synthetic ? <Badge kind="synthetic">synthetic</Badge> : null}</> : null}
      </View>
    </View>
  );
  const footer = batch ? (
    <View style={{ alignItems: "center", padding: space[5], borderWidth: 2, borderStyle: "dashed", borderColor: c.border, borderRadius: 12, marginTop: space[3], gap: space[2] }}>
      <Text accessibilityRole="header" style={{ color: c.text, fontSize: 20, fontWeight: "700" }}>{batch.consumed_at ? "You finished today’s batch." : "That’s the whole batch."}</Text>
      <P muted>No more to scroll.</P>
      {!batch.consumed_at ? <Button title="I’m done for today" variant="primary" onPress={() => void complete(batch)} disabled={offline} /> : null}
    </View>
  ) : (!job && today ? <Notice kind="info">No batch yet. Tap “Refresh batch”.</Notice> : undefined);

  if (!today && !error) return <Screen><Loading label="Loading today’s batch" /></Screen>;
  return (
    <Screen>
      <FlatList
        data={visible}
        keyExtractor={(r) => r.id}
        renderItem={({ item }) => <RecommendationCard rec={item} onFeedback={offline ? undefined : feedback} onToggleSave={offline ? undefined : toggleSave} />}
        ListHeaderComponent={header}
        ListFooterComponent={footer}
        ItemSeparatorComponent={() => <View style={{ height: space[3] }} />}
        contentContainerStyle={{ padding: space[4], paddingBottom: space[6] }}
        refreshControl={<RefreshControl refreshing={false} onRefresh={() => void load()} />}
        keyboardShouldPersistTaps="handled"
        onEndReachedThreshold={undefined}
      />
      {me && !me.has_preferences ? <View style={{ padding: space[4] }}><Button title="Finish setup" onPress={() => router.push("/onboarding")} /></View> : null}
    </Screen>
  );
}
