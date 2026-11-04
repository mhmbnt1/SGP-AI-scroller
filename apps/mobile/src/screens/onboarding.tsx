import type { PlatformCapabilityOut, PreferencesIn } from "@focusfeed/contracts";
import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { Pressable, ScrollView, Text, View } from "react-native";

import { Badge, Button, ErrorView, H1, Input, Loading, Notice, P, Screen } from "@/components/ui";
import { api, unwrap } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { space, useColors } from "@/theme";

type Prefs = Required<PreferencesIn>;
type Plat = Prefs["platforms"][number];

function Chips({ label, values, onChange }: { label: string; values: string[]; onChange: (v: string[]) => void }) {
  const c = useColors();
  const [draft, setDraft] = useState("");
  function add() { const v = draft.trim(); if (!v || values.some((x) => x.toLowerCase() === v.toLowerCase())) return; onChange([...values, v]); setDraft(""); }
  return (
    <View style={{ gap: 8 }}>
      <Input label={label} value={draft} onChangeText={setDraft} onSubmitEditing={add} returnKeyType="done" placeholder="Type and press return" />
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
        {values.map((v) => <Pressable key={v} accessibilityRole="button" accessibilityLabel={`Remove ${v}`} onPress={() => onChange(values.filter((x) => x !== v))} style={{ paddingHorizontal: 10, minHeight: 36, justifyContent: "center", borderRadius: 999, borderWidth: 1, borderColor: c.border, backgroundColor: c.surface2 }}><Text style={{ color: c.text }}>{v} ×</Text></Pressable>)}
      </View>
    </View>
  );
}

export function OnboardingScreen() {
  const c = useColors();
  const router = useRouter();
  const { refresh } = useAuth();
  const [prefs, setPrefs] = useState<Prefs | null>(null);
  const [caps, setCaps] = useState<PlatformCapabilityOut[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void (async () => {
      try {
        const [p, cp] = await Promise.all([unwrap(api.GET("/api/v1/preferences")), unwrap(api.GET("/api/v1/platforms"))]);
        setPrefs({ interests: p.interests, exclusions: p.exclusions, excluded_creators: p.excluded_creators, languages: p.languages, platforms: p.platforms as Plat[], per_platform_limit: p.per_platform_limit, total_budget_minutes: p.total_budget_minutes, consent_saved_signals: p.consent_saved_signals, consent_feedback_learning: p.consent_feedback_learning, text_model: p.text_model, embedding_model: p.embedding_model });
        setCaps(cp);
      } catch (e) { setError(e); }
    })();
  }, []);

  async function save() {
    if (!prefs || busy) return;
    setBusy(true); setError(null);
    try {
      await unwrap(api.PUT("/api/v1/preferences", { body: prefs }));
      await unwrap(api.POST("/api/v1/preferences/complete-onboarding"));
      await refresh();
      router.replace("/(tabs)/today");
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  if (!prefs) return <Screen>{error ? <View style={{ padding: space[4] }}><ErrorView error={error} /></View> : <Loading />}</Screen>;
  const p = prefs;
  return (
    <Screen>
      <ScrollView contentContainerStyle={{ padding: space[4], gap: space[4], paddingBottom: space[6] }} keyboardShouldPersistTaps="handled">
        <H1>Set up your batch</H1>
        <P muted>Pick platforms, interests, exclusions and a time budget. Everything can change later.</P>
        <Text style={{ color: c.text, fontWeight: "700" }}>Platforms</Text>
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
          {caps.filter((cp) => cp.status !== "disabled").map((cp) => { const pl = cp.platform as Plat; const on = p.platforms.includes(pl); return (
            <Pressable key={pl} accessibilityRole="checkbox" accessibilityState={{ checked: on }} accessibilityLabel={cp.display_name} onPress={() => setPrefs({ ...p, platforms: on ? p.platforms.filter((x) => x !== pl) : [...p.platforms, pl] })}
              style={{ flexDirection: "row", gap: 6, alignItems: "center", minHeight: 44, paddingHorizontal: 12, borderRadius: 999, borderWidth: 1, borderColor: on ? c.accent : c.border, backgroundColor: on ? c.accentSoft : c.surface }}>
              <Text style={{ color: c.text }}>{cp.display_name}</Text><Badge kind={cp.status === "implemented" ? "ok" : cp.status === "synthetic" ? "synthetic" : "default"}>{cp.status.replace("_", " ")}</Badge>
            </Pressable>); })}
        </View>
        <Chips label="Interests" values={p.interests} onChange={(v) => setPrefs({ ...p, interests: v })} />
        <Chips label="Exclusions (whole words)" values={p.exclusions} onChange={(v) => setPrefs({ ...p, exclusions: v })} />
        <Chips label="Excluded creators" values={p.excluded_creators} onChange={(v) => setPrefs({ ...p, excluded_creators: v })} />
        <Chips label="Languages (e.g. en, es)" values={p.languages} onChange={(v) => setPrefs({ ...p, languages: v })} />
        <Input label="Items per platform" hint="1–10" keyboardType="number-pad" value={String(p.per_platform_limit)} onChangeText={(t) => setPrefs({ ...p, per_platform_limit: Math.max(1, Math.min(10, Number(t) || 1)) })} />
        <Input label="Total time budget (minutes)" hint="5–240" keyboardType="number-pad" value={String(p.total_budget_minutes)} onChangeText={(t) => setPrefs({ ...p, total_budget_minutes: Math.max(5, Math.min(240, Number(t) || 5)) })} />
        <Pressable accessibilityRole="checkbox" accessibilityState={{ checked: p.consent_feedback_learning }} onPress={() => setPrefs({ ...p, consent_feedback_learning: !p.consent_feedback_learning })} style={{ minHeight: 44, justifyContent: "center" }}><Text style={{ color: c.text }}>{p.consent_feedback_learning ? "☑" : "☐"} Use my feedback to adjust future batches</Text></Pressable>
        <Pressable accessibilityRole="checkbox" accessibilityState={{ checked: p.consent_saved_signals }} onPress={() => setPrefs({ ...p, consent_saved_signals: !p.consent_saved_signals })} style={{ minHeight: 44, justifyContent: "center" }}><Text style={{ color: c.text }}>{p.consent_saved_signals ? "☑" : "☐"} Use topics of saved items as a positive signal</Text></Pressable>
        <Notice kind="info">Private messages are never read. Viewing through the collector may influence the platform’s own recommendations.</Notice>
        {error ? <ErrorView error={error} /> : null}
        <Button title="Save and continue" variant="primary" loading={busy} disabled={busy || p.platforms.length === 0} onPress={() => void save()} />
      </ScrollView>
    </Screen>
  );
}
