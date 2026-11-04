import type { AiOptionsOut, ProviderConnectionOut, UsageOut } from "@focusfeed/contracts";
import { useCallback, useEffect, useState } from "react";
import { ScrollView, Text, View } from "react-native";

import { Badge, Button, Card, Check, Choice, ErrorView, H1, Input, Loading, Notice, P, Screen } from "@/components/ui";
import { api, unwrap } from "@/lib/api";
import { space, useColors } from "@/theme";

type Provider = "openai" | "anthropic" | "gemini" | "xai" | "ollama" | "fake";

/** Consumer choice of AI model from the operator-enabled list. BYOK is optional and collapsed. */
export function AiSettingsScreen() {
  const c = useColors();
  const [opts, setOpts] = useState<AiOptionsOut | null>(null);
  const [usage, setUsage] = useState<UsageOut | null>(null);
  const [conns, setConns] = useState<ProviderConnectionOut[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [provider, setProvider] = useState<Provider>("ollama");
  const [chatModel, setChatModel] = useState("");
  const [ack, setAck] = useState(false);
  const [mode, setMode] = useState<"operator" | "byok">("operator");
  const [connId, setConnId] = useState("");
  const [advanced, setAdvanced] = useState(false);
  const [newKey, setNewKey] = useState({ provider: "openai" as Provider, api_key: "" });

  const load = useCallback(async () => {
    setError(null);
    try {
      const [o, u, cn] = await Promise.all([unwrap(api.GET("/api/v1/ai/options")), unwrap(api.GET("/api/v1/ai/usage")), unwrap(api.GET("/api/v1/ai/connections"))]);
      setOpts(o); setUsage(u); setConns(cn);
      if (o.selection.provider) setProvider(o.selection.provider as Provider);
      setChatModel(o.selection.chat_model ?? ""); setMode(o.selection.credential_mode); setConnId(o.selection.byok_connection_id ?? ""); setAck(o.selection.external_disclosure_acknowledged);
    } catch (e) { setError(e); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  async function save() {
    if (busy) return; setBusy(true); setError(null); setSaved(null);
    try {
      const out = await unwrap(api.PUT("/api/v1/ai/selection", { body: { provider, credential_mode: mode, chat_model: chatModel || null, byok_connection_id: mode === "byok" && connId ? connId : null, allow_fallback_to: [], acknowledge_external_processing: ack } }));
      setSaved(`Saved. Jobs now use ${out.effective_label} (${out.availability}).`); await load();
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  async function addKey() {
    if (busy || newKey.api_key.length < 8) return; setBusy(true); setError(null);
    try { await unwrap(api.POST("/api/v1/ai/connections", { body: { provider: newKey.provider as "openai" | "anthropic" | "gemini" | "xai", api_key: newKey.api_key, label: "" } })); setNewKey({ ...newKey, api_key: "" }); await load(); }
    catch (e) { setError(e); } finally { setBusy(false); }
  }
  async function testConn(id: string) {
    setBusy(true); setError(null);
    try { const r = await unwrap(api.POST("/api/v1/ai/connections/{connection_id}/test", { params: { path: { connection_id: id } }, body: {} })); setSaved(r.ok ? `Connection OK (${r.model})` : `Connection failed: ${r.error}`); await load(); }
    catch (e) { setError(e); } finally { setBusy(false); }
  }

  if (!opts && !error) return <Screen><Loading /></Screen>;
  if (!opts) return <Screen><View style={{ padding: space[4] }}><ErrorView error={error} onRetry={load} /></View></Screen>;
  const current = opts.providers.find((p) => p.provider === provider);
  const sel = opts.selection;
  const chatModels = (current?.models ?? []).filter((m) => (m.tasks as string[]).includes("chat"));
  return (
    <Screen>
      <ScrollView contentContainerStyle={{ padding: space[4], gap: space[3], paddingBottom: space[6] }} keyboardShouldPersistTaps="handled">
        <H1>AI model</H1>
        <View style={{ flexDirection: "row", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <Badge kind={sel.availability === "ready" ? "ok" : "bad"}>{sel.availability.replace(/_/g, " ")}</Badge>
          <Text style={{ color: c.muted }}>{sel.effective_label !== "none" ? `Current: ${sel.effective_label}` : "No model active"}</Text>
        </View>
        {sel.availability_detail ? <P muted>{sel.availability_detail}</P> : null}
        {opts.providers.length === 0 ? <Notice kind="warn">No AI provider is enabled on this service yet. That is an operator task; you do not need an API key.</Notice> : null}
        <Card>
          <Choice label="Provider" value={provider} onChange={(v) => { setProvider(v); setChatModel(""); }} options={opts.providers.map((p) => ({ value: p.provider as Provider, label: p.display_name + (p.configured ? "" : " (not configured)"), disabled: !p.configured && mode === "operator" }))} />
          {current ? <P muted>{current.help}</P> : null}
          {chatModels.length > 0 ? <Choice label="Model" value={chatModel} onChange={setChatModel} options={[{ value: "", label: "Default" }, ...chatModels.map((m) => ({ value: m.id as string, label: (m.label as string) + (m.verified ? "" : " (id unverified)") }))]} /> : null}
          {current?.external ? <Check label="I understand that my feed items and WhatsApp requests will be sent to this external provider" value={ack} onChange={setAck} /> : null}
          {current?.external ? <P muted style={{ fontSize: 13 }}>{opts.disclosure_text}</P> : null}
          {error ? <ErrorView error={error} /> : null}
          {saved ? <Notice kind="success">{saved}</Notice> : null}
          <Button title="Save AI choice" variant="primary" loading={busy} disabled={busy} onPress={() => void save()} />
        </Card>
        {usage ? <P muted style={{ fontSize: 13 }}>Today: {usage.calls_today}/{usage.call_quota} calls · {usage.tokens_today}/{usage.token_quota} tokens · est. ${usage.cost_estimate_today_usd}{usage.cost_unknown_calls_today ? ` (+${usage.cost_unknown_calls_today} unpriced)` : ""}. {usage.note}</P> : null}
        {opts.byok_enabled ? (
          <Card>
            <Button title={advanced ? "Hide advanced (own API key)" : "Advanced: use my own API key (optional)"} variant="ghost" onPress={() => setAdvanced(!advanced)} />
            {advanced ? (<>
              <Choice label="Credential mode" value={mode} onChange={setMode} options={[{ value: "operator", label: "Service-provided (default)" }, { value: "byok", label: "My own key" }]} />
              {mode === "byok" ? <Choice label="Connection" value={connId} onChange={setConnId} options={conns.map((cn) => ({ value: cn.id, label: `${cn.display_name} · ${cn.key_hint} (${cn.status})` }))} /> : null}
              {conns.map((cn) => <View key={cn.id} style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", gap: 8 }}><Text style={{ color: c.text, flex: 1 }}>{cn.display_name} · {cn.key_hint}</Text><Badge kind={cn.status === "ok" ? "ok" : cn.status === "untested" ? "default" : "bad"}>{cn.status}</Badge><Button title="Test" disabled={busy} onPress={() => void testConn(cn.id)} /></View>)}
              <Choice label="New key for" value={newKey.provider} onChange={(v) => setNewKey({ ...newKey, provider: v })} options={(["openai", "anthropic", "gemini", "xai"] as Provider[]).map((p) => ({ value: p, label: p }))} />
              <Input label="API key" hint="stored encrypted; never shown again" value={newKey.api_key} onChangeText={(v) => setNewKey({ ...newKey, api_key: v })} secureTextEntry autoCapitalize="none" autoCorrect={false} />
              <Button title="Add key" disabled={busy || newKey.api_key.length < 8} onPress={() => void addKey()} />
            </>) : null}
          </Card>
        ) : null}
      </ScrollView>
    </Screen>
  );
}
