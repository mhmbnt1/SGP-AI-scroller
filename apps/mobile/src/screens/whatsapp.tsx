import type { NotificationOut, WhatsAppLinkStartOut, WhatsAppStatusOut } from "@focusfeed/contracts";
import * as Clipboard from "expo-clipboard";
import { useCallback, useEffect, useState } from "react";
import { Linking, ScrollView, Text, View } from "react-native";

import { Badge, Button, Card, Check, ErrorView, H1, Loading, Notice, P, Screen } from "@/components/ui";
import { api, unwrap } from "@/lib/api";
import { space, useColors } from "@/theme";

/** WhatsApp linking (code sent FROM the user's phone to the business number), consent and history. */
export function WhatsAppScreen() {
  const c = useColors();
  const [st, setSt] = useState<WhatsAppStatusOut | null>(null);
  const [link, setLink] = useState<WhatsAppLinkStartOut | null>(null);
  const [history, setHistory] = useState<NotificationOut[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [ack, setAck] = useState(false);
  const [digests, setDigests] = useState(true);
  const [alerts, setAlerts] = useState(true);
  const [copied, setCopied] = useState(false);
  const load = useCallback(async () => {
    setError(null);
    try { const [s, h] = await Promise.all([unwrap(api.GET("/api/v1/channels/whatsapp")), unwrap(api.GET("/api/v1/notifications"))]); setSt(s); setHistory(h); setDigests(s.digest_enabled); setAlerts(s.alerts_enabled); setAck(s.external_disclosure_acknowledged); }
    catch (e) { setError(e); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  async function startLink() { setError(null); try { setLink(await unwrap(api.POST("/api/v1/channels/whatsapp/link"))); } catch (e) { setError(e); } }
  async function setPrefs(opt: boolean) { setError(null); try { await unwrap(api.PUT("/api/v1/channels/whatsapp/preferences", { body: { proactive_opt_in: opt, digest_enabled: digests, alerts_enabled: alerts, acknowledge_external_processing: ack } })); await load(); } catch (e) { setError(e); } }
  async function unlink() { try { await unwrap(api.DELETE("/api/v1/channels/whatsapp")); setLink(null); await load(); } catch (e) { setError(e); } }
  if (!st && !error) return <Screen><Loading /></Screen>;
  if (!st) return <Screen><View style={{ padding: space[4] }}><ErrorView error={error} onRetry={load} /></View></Screen>;
  return (
    <Screen>
      <ScrollView contentContainerStyle={{ padding: space[4], gap: space[3], paddingBottom: space[6] }}>
        <H1>WhatsApp</H1>
        <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
          <Badge kind={st.transport_mode === "live" ? "ok" : st.transport_mode === "mock" ? "synthetic" : "bad"}>transport: {st.transport_mode}</Badge>
          <Badge kind={st.linked ? "ok" : "default"}>{st.linked ? `linked ${st.display_hint}` : "not linked"}</Badge>
          {st.linked ? <Badge kind={st.proactive_opt_in ? "ok" : "default"}>{st.proactive_opt_in ? (st.paused_until ? "paused" : "notifications on") : "notifications off"}</Badge> : null}
        </View>
        <P muted style={{ fontSize: 13 }}>{st.eligibility_note}</P>
        {st.transport_mode === "disabled" ? <Notice kind="warn">WhatsApp is not enabled on this service (operator setup: business sender, webhook, approved templates).</Notice> : null}
        {!st.linked && st.transport_mode !== "disabled" ? (
          <Card>
            <P>Link your own WhatsApp from this phone: get a one-time code and send it to the FocusFeed number. We never ask for your phone number here; the link is confirmed from the message you send.</P>
            <Button title="Connect WhatsApp" variant="primary" onPress={() => void startLink()} />
            {link ? (<>
              <Notice kind="success">Send this message within 10 minutes (one use):{"\n"}<Text style={{ fontWeight: "700", fontSize: 18 }} testID="wa-link-code">{link.message_text}</Text></Notice>
              {link.deep_link ? <Button title="Open WhatsApp with the code" variant="primary" onPress={() => void Linking.openURL(link.deep_link as string)} /> : null}
              <Button title={copied ? "Copied" : "Copy code"} onPress={() => { void Clipboard.setStringAsync(link.message_text); setCopied(true); }} />
              <Button title="I sent it — check" onPress={() => void load()} />
              <P muted style={{ fontSize: 13 }}>{link.instructions}</P>
            </>) : null}
          </Card>
        ) : null}
        {st.linked ? (
          <Card>
            <Check label="Send my scheduled digests here" value={digests} onChange={setDigests} />
            <Check label="Send watch alerts here (respects caps and quiet hours)" value={alerts} onChange={setAlerts} />
            {!st.external_disclosure_acknowledged ? <Check label="I understand my WhatsApp requests are processed by our servers and my chosen AI provider, and are not protected by WhatsApp end-to-end encryption once received" value={ack} onChange={setAck} /> : null}
            {!st.proactive_opt_in ? <Button title="Enable notifications" variant="primary" onPress={() => void setPrefs(true)} /> : <Button title="Stop notifications" onPress={() => void setPrefs(false)} />}
            <Button title="Unlink" variant="danger" onPress={() => void unlink()} />
            <P muted style={{ fontSize: 13 }}>Replying STOP in WhatsApp has the same effect as “Stop notifications”. Messages outside WhatsApp’s 24-hour service window need an operator-approved template{st.templates_approved.digest ? " (digest template approved)" : " (no digest template approved yet — digests stay in the app)"}.</P>
          </Card>
        ) : null}
        {error ? <ErrorView error={error} /> : null}
        {history.length > 0 ? (
          <Card>
            <Text style={{ color: c.text, fontWeight: "700" }}>Delivery history</Text>
            {history.map((h) => <View key={h.id} style={{ gap: 2 }}><View style={{ flexDirection: "row", gap: 8, alignItems: "center" }}><Text style={{ color: c.text, flex: 1 }}>{h.kind}{h.proactive ? " (proactive)" : ""} · {new Date(h.created_at).toLocaleString()}</Text><Badge kind={["delivered", "read", "accepted"].includes(h.state) ? "ok" : ["failed", "expired", "cancelled"].includes(h.state) ? "bad" : "default"}>{h.state}</Badge></View><Text style={{ color: c.muted, fontSize: 12 }}>{h.body_preview}{h.last_error ? ` · ${h.last_error}` : ""}</Text></View>)}
          </Card>
        ) : null}
      </ScrollView>
    </Screen>
  );
}
