import type { SavedOut } from "@focusfeed/contracts";
import * as WebBrowser from "expo-web-browser";
import { useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { FlatList, RefreshControl, Text, View } from "react-native";

import { Badge, Button, Card, ErrorView, H1, Loading, Notice, Screen } from "@/components/ui";
import { api, cacheGet, cacheSet, unwrap } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { space, useColors } from "@/theme";

export function SavedScreen() {
  const c = useColors();
  const router = useRouter();
  const { me, offline } = useAuth();
  const [items, setItems] = useState<SavedOut[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const userId = me?.user.id ?? "";
  const load = useCallback(async () => {
    setError(null);
    try { const out = await unwrap(api.GET("/api/v1/saved")); setItems(out.items); await cacheSet(userId, "saved", out.items); }
    catch (e) { const cached = userId ? await cacheGet<SavedOut[]>(userId, "saved") : null; if (cached) setItems(cached); else setError(e); }
  }, [userId]);
  useEffect(() => { void load(); }, [load]);
  async function remove(id: string) { await unwrap(api.DELETE("/api/v1/saved/{item_id}", { params: { path: { item_id: id } } })); setItems((xs) => xs?.filter((x) => x.item.id !== id) ?? null); }
  if (!items && !error) return <Screen><Loading /></Screen>;
  return (
    <Screen>
      <FlatList data={items ?? []} keyExtractor={(s) => s.item.id}
        ListHeaderComponent={<View style={{ marginBottom: space[3] }}><H1>Saved</H1>{offline ? <Notice kind="warn">Offline — showing cached saved items.</Notice> : null}{error ? <ErrorView error={error} onRetry={load} /> : null}</View>}
        ListEmptyComponent={!error ? <Notice kind="info">Nothing saved yet.</Notice> : undefined}
        renderItem={({ item: { item, saved_at } }) => (
          <Card>
            <View style={{ flexDirection: "row", gap: 6, flexWrap: "wrap" }}><Badge kind="platform">{item.platform}</Badge>{item.is_synthetic ? <Badge kind="synthetic">synthetic</Badge> : null}<Text style={{ color: c.muted }}>{new Date(saved_at).toLocaleDateString()}</Text></View>
            <Text style={{ color: c.text, fontWeight: "700", fontSize: 16 }}>{item.title ?? item.caption?.slice(0, 80) ?? item.canonical_url}</Text>
            <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
              <Button title="Open" variant="primary" onPress={() => void WebBrowser.openBrowserAsync(item.canonical_url)} />
              <Button title="Details" onPress={() => router.push(`/item/${item.id}`)} />
              <Button title="Remove" variant="ghost" disabled={offline} onPress={() => void remove(item.id)} />
            </View>
          </Card>
        )}
        ItemSeparatorComponent={() => <View style={{ height: space[3] }} />} contentContainerStyle={{ padding: space[4] }}
        refreshControl={<RefreshControl refreshing={false} onRefresh={() => void load()} />} />
    </Screen>
  );
}
