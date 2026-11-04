import { analysisLabel, formatDuration, type FeedbackAction, type RecommendationOut } from "@focusfeed/contracts";
import * as WebBrowser from "expo-web-browser";
import { useRouter } from "expo-router";
import { useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { Badge, Button, Card, P } from "@/components/ui";
import { space, useColors } from "@/theme";

export function RecommendationCard({ rec, onFeedback, onToggleSave, onOpen }: {
  rec: RecommendationOut;
  onFeedback?: (rec: RecommendationOut, action: FeedbackAction) => Promise<void>;
  onToggleSave?: (rec: RecommendationOut) => Promise<void>;
  onOpen?: (rec: RecommendationOut) => void;
}) {
  const c = useColors();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [why, setWhy] = useState(false);
  const item = rec.item;
  const title = item.title || item.caption?.slice(0, 80) || item.canonical_url;

  async function run(fn: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    try { await fn(); } finally { setBusy(false); }
  }
  async function open() {
    onOpen?.(rec);
    // System browser sheet keeps attribution and the platform's own session; no autoplay inside the app.
    await WebBrowser.openBrowserAsync(item.canonical_url);
  }

  return (
    <Card style={{ opacity: rec.hidden ? 0.6 : 1 }}>
      <View style={styles.row}>
        <Text style={{ color: c.muted, fontVariant: ["tabular-nums"] }}>#{rec.rank}</Text>
        <Badge kind="platform">{item.platform}</Badge>
        {item.is_synthetic ? <Badge kind="synthetic">synthetic demo</Badge> : null}
        <Badge>{analysisLabel(rec.analysis_kind)}</Badge>
        <Text style={{ color: c.muted }}>{formatDuration(rec.estimated_seconds, rec.duration_known)}</Text>
      </View>
      <Text accessibilityRole="header" style={[styles.title, { color: c.text }]}>{title}</Text>
      <Text style={{ color: c.muted }}>{item.creator_name ?? item.creator_handle ?? ""}{rec.topics.length ? ` · ${rec.topics.slice(0, 3).join(", ")}` : ""}</Text>
      {rec.summary ? <P>{rec.summary}</P> : null}
      <View style={styles.row}>
        <Button title={`Open on ${item.platform}`} variant="primary" onPress={() => void open()} />
        <Button title="Details" onPress={() => router.push(`/item/${item.id}`)} />
        <Button title={why ? "Hide why" : "Why this?"} variant="ghost" onPress={() => setWhy((v) => !v)} accessibilityState={{ expanded: why }} />
      </View>
      {why ? (
        <View style={[styles.why, { backgroundColor: c.surface2 }]} accessibilityLiveRegion="polite">
          <Text style={{ color: c.text }}>{rec.explanation}</Text>
          <Text style={{ color: c.muted, marginTop: 6, fontSize: 12 }}>{Object.entries(rec.components).filter(([k]) => k !== "explanation_len").map(([k, v]) => `${k}=${typeof v === "number" ? v.toFixed(2) : String(v)}`).join("  ")}</Text>
        </View>
      ) : null}
      {(onFeedback || onToggleSave) ? (
        <View style={styles.row}>
          {onToggleSave ? <Button title={rec.saved ? "★ Saved" : "☆ Save"} variant="ghost" disabled={busy} onPress={() => void run(() => onToggleSave(rec))} accessibilityState={{ selected: rec.saved }} /> : null}
          {onFeedback ? (
            <>
              <Button title="👍 Relevant" variant="ghost" disabled={busy} onPress={() => void run(() => onFeedback(rec, "relevant"))} />
              <Button title="👎 Not relevant" variant="ghost" disabled={busy} onPress={() => void run(() => onFeedback(rec, "not_relevant"))} />
              <Button title="Not interested" variant="ghost" disabled={busy} onPress={() => void run(() => onFeedback(rec, "not_interested"))} />
              <Button title="Hide creator" variant="ghost" disabled={busy} onPress={() => void run(() => onFeedback(rec, "hide_creator"))} />
            </>
          ) : null}
        </View>
      ) : null}
    </Card>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", flexWrap: "wrap", gap: space[2], alignItems: "center" },
  title: { fontSize: 17, fontWeight: "700" },
  why: { borderRadius: 8, padding: space[3] },
});
