import type { SourceOut } from "@focusfeed/contracts";
import { useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { ScrollView, Text, View } from "react-native";

import { Badge, Button, Card, Choice, ErrorView, H1, Loading, P, Screen } from "@/components/ui";
import { api, unwrap } from "@/lib/api";
import { space, useColors } from "@/theme";

/** Standard (hosted) source connection — phone-only. The local-PC collector is an advanced alternative. */
export function SourcesScreen() {
  const c = useColors();
  const router = useRouter();
  const [rows, setRows] = useState<SourceOut[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [advanced, setAdvanced] = useState(false);
  const load = useCallback(async () => { setError(null); try { setRows(await unwrap(api.GET("/api/v1/sources"))); } catch (e) { setError(e); } }, []);
  useEffect(() => { void load(); }, [load]);
  async function disconnect(platform: string) { try { await unwrap(api.DELETE("/api/v1/sources/{platform}/hosted", { params: { path: { platform } } })); await load(); } catch (e) { setError(e); } }
  async function setLocation(location: "hosted" | "local") { try { await unwrap(api.PUT("/api/v1/sources/location", { body: { location } })); await load(); } catch (e) { setError(e); } }
  if (!rows && !error) return <Screen><Loading /></Screen>;
  const location = (rows?.[0]?.collection_location ?? "hosted") as "hosted" | "local";
  return (
    <Screen>
      <ScrollView contentContainerStyle={{ padding: space[4], gap: space[3], paddingBottom: space[6] }}>
        <H1>Your sources</H1>
        <P muted>Collection runs on our always-on service while your phone is offline. Sign in once from this phone; reconnect when a session expires.</P>
        {error ? <ErrorView error={error} onRetry={load} /> : null}
        {rows?.map((r) => (
          <Card key={r.platform}>
            <View style={{ flexDirection: "row", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <Text style={{ color: c.text, fontWeight: "700", flex: 1 }}>{r.display_name}</Text>
              <Badge kind={r.hosted_status === "connected" || r.hosted_status === "available" ? "ok" : r.hosted_status === "unsupported" || r.hosted_status === "local_mode" ? "default" : "bad"}>{r.hosted_status.replace(/_/g, " ")}</Badge>
              <Badge kind={r.phone_only_support === "unverified" ? "synthetic" : r.phone_only_support === "unsupported" ? "bad" : "default"}>phone-only: {r.phone_only_support}</Badge>
            </View>
            <P muted style={{ fontSize: 13 }}>{r.support_note}</P>
            <P style={{ fontSize: 14 }}>{r.next_step}</P>
            {r.implemented && location === "hosted" && ["not_connected", "needs_reauth", "challenge_required"].includes(r.hosted_status) ? <Button title={r.hosted_status === "not_connected" ? `Connect ${r.display_name}` : `Reconnect ${r.display_name}`} variant="primary" onPress={() => router.push({ pathname: "/connect-session", params: { platform: r.platform } })} /> : null}
            {r.implemented && r.hosted_status === "connected" ? <Button title="Disconnect" variant="danger" onPress={() => void disconnect(r.platform)} /> : null}
          </Card>
        ))}
        <Button title={advanced ? "Hide advanced" : `Advanced: collection location (${location})`} variant="ghost" onPress={() => setAdvanced(!advanced)} />
        {advanced ? (
          <Card>
            <P muted style={{ fontSize: 13 }}>“Hosted” (default) runs the browser on the service. “Local” uses the optional collector on your own Windows PC — it must be paired, signed in and running for scheduled digests; nothing on this phone can replace it.</P>
            <Choice label="Collection location" value={location} onChange={(v) => void setLocation(v)} options={[{ value: "hosted", label: "Hosted (service)" }, { value: "local", label: "Local PC collector" }]} />
            <Button title="Local collector guide" onPress={() => router.push("/connect")} />
          </Card>
        ) : null}
      </ScrollView>
    </Screen>
  );
}
