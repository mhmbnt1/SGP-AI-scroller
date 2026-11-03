import { analysisLabel, formatDuration, type ItemDetailOut } from "@focusfeed/contracts";
import * as WebBrowser from "expo-web-browser";
import { useCallback, useEffect, useState } from "react";
import { ScrollView, Text, View } from "react-native";

import { Badge, Button, Card, ErrorView, H1, Loading, P, Screen } from "@/components/ui";
import { api, unwrap } from "@/lib/api";
import { space, useColors } from "@/theme";

export function ItemDetailScreen({ id }: { id: string }) {
  const c = useColors();
  const [d, setD] = useState<ItemDetailOut | null>(null);
  const [error, setError] = useState<unknown>(null);
  const load = useCallback(async () => { setError(null); try { setD(await unwrap(api.GET("/api/v1/items/{item_id}", { params: { path: { item_id: id } } }))); } catch (e) { setError(e); } }, [id]);
  useEffect(() => { void load(); }, [load]);
  if (error) return <Screen><View style={{ padding: space[4] }}><ErrorView error={error} onRetry={load} /></View></Screen>;
  if (!d) return <Screen><Loading /></Screen>;
  const { item, recommendation: rec } = d;
  return (
    <Screen>
      <ScrollView contentContainerStyle={{ padding: space[4], gap: space[3], paddingBottom: space[6] }}>
        <View style={{ flexDirection: "row", gap: 6, flexWrap: "wrap" }}><Badge kind="platform">{item.platform}</Badge>{item.is_synthetic ? <Badge kind="synthetic">synthetic demo</Badge> : null}<Badge>{analysisLabel(d.analysis_kind)}</Badge></View>
        <H1>{item.title ?? "Untitled"}</H1>
        <P muted>{item.creator_name ?? item.creator_handle ?? "Unknown creator"}{item.duration_seconds != null ? ` · ${formatDuration(item.duration_seconds, true)}` : " · duration unknown"}{item.language ? ` · ${item.language}` : ""}</P>
        <Button title="Open original source" variant="primary" onPress={() => void WebBrowser.openBrowserAsync(item.canonical_url)} />
        {item.caption ? <Card><Text style={{ color: c.text, fontWeight: "700" }}>Caption</Text><P>{item.caption}</P></Card> : null}
        {rec ? <Card><Text style={{ color: c.text, fontWeight: "700" }}>Why this was recommended</Text><P>{rec.explanation}</P><Text style={{ color: c.text, fontWeight: "700" }}>Evidence-supported summary</Text><P>{rec.summary}</P><P muted>{d.coverage_label}</P></Card> : null}
        <Card>
          <Text style={{ color: c.text, fontWeight: "700" }}>Evidence ({d.evidence.length})</Text>
          {d.evidence.length === 0 ? <P muted>No transcript or frame evidence captured; summary is metadata-only.</P> : null}
          {d.evidence.map((ev) => (
            <View key={ev.id} style={{ gap: 4 }}>
              <Text style={{ color: c.muted }}>{ev.kind} · {ev.transcript_source} · coverage {Math.round(ev.coverage_ratio * 100)}% · {ev.extraction_method}</Text>
              {ev.segments.slice(0, 40).map((s, i) => { const seg = s as { start_s: number; end_s: number; text: string }; return <Text key={i} style={{ color: c.text }}><Text style={{ color: c.muted }}>{seg.start_s}s–{seg.end_s}s </Text>{seg.text}</Text>; })}
            </View>
          ))}
        </Card>
      </ScrollView>
    </Screen>
  );
}
