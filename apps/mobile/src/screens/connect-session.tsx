import type { ConnectSessionOut } from "@focusfeed/contracts";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { Image, Pressable, ScrollView, Text, View, type GestureResponderEvent } from "react-native";

import { Badge, Button, Card, Check, ErrorView, H1, Input, P, Screen } from "@/components/ui";
import { api, getToken, unwrap } from "@/lib/api";
import { apiBaseUrl } from "@/lib/config";
import { space, useColors } from "@/theme";

const TERMINAL = ["completed", "cancelled", "expired", "failed"];

/** Phone-driven hosted sign-in: screenshots in, taps/keys out. Credentials go into the official page only. */
export function ConnectSessionScreen() {
  const c = useColors();
  const router = useRouter();
  const { platform: rawPlatform } = useLocalSearchParams<{ platform?: string }>();
  const platform = typeof rawPlatform === "string" ? rawPlatform : "youtube";
  const [consent, setConsent] = useState(false);
  const [session, setSession] = useState<ConnectSessionOut | null>(null);
  const [token, setToken] = useState("");
  const [frame, setFrame] = useState<string | null>(null);
  const [size, setSize] = useState({ w: 1, h: 1 });
  const [text, setText] = useState("");
  const [error, setError] = useState<unknown>(null);
  const seqRef = useRef(0);

  async function start() {
    setError(null);
    try { const out = await unwrap(api.POST("/api/v1/sources/{platform}/connect-sessions", { params: { path: { platform } }, body: { consent } })); setSession(out.session); setToken(out.token); }
    catch (e) { setError(e); }
  }
  const fetchFrame = useCallback(async (id: string, ct: string) => {
    const bearer = await getToken();
    const res = await fetch(`${apiBaseUrl()}/api/v1/sources/connect-sessions/${id}/frame`, { headers: { Authorization: `Bearer ${bearer ?? ""}`, "X-Connect-Token": ct } });
    if (res.status !== 200) return null;
    const blob = await res.blob();
    return await new Promise<string>((resolve, reject) => { const r = new FileReader(); r.onerror = () => reject(r.error); r.onloadend = () => resolve(String(r.result)); r.readAsDataURL(blob); });
  }, []);
  useEffect(() => {
    if (!session || !token || TERMINAL.includes(session.state)) return;
    let stop = false;
    const tick = async () => {
      try {
        const s = await unwrap(api.GET("/api/v1/sources/connect-sessions/{session_id}", { params: { path: { session_id: session.id }, header: { "X-Connect-Token": token } } }));
        if (stop) return;
        setSession(s);
        if (s.frame_seq !== seqRef.current) { const uri = await fetchFrame(session.id, token); if (uri && !stop) { setFrame(uri); seqRef.current = s.frame_seq; } }
      } catch (e) { if (!stop) setError(e); }
      if (!stop) setTimeout(tick, 1000);
    };
    void tick();
    return () => { stop = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.id, session?.state, token]);

  async function input(body: { kind: "tap" | "type" | "key" | "scroll" | "back"; x?: number; y?: number; text?: string; key?: string; dy?: number }) {
    if (!session) return;
    try { await unwrap(api.POST("/api/v1/sources/connect-sessions/{session_id}/input", { params: { path: { session_id: session.id }, header: { "X-Connect-Token": token } }, body })); } catch (e) { setError(e); }
  }
  async function end(kind: "finish" | "cancel") {
    if (!session) return;
    try {
      const path = kind === "finish" ? "/api/v1/sources/connect-sessions/{session_id}/finish" : "/api/v1/sources/connect-sessions/{session_id}/cancel";
      setSession(await unwrap(api.POST(path, { params: { path: { session_id: session.id }, header: { "X-Connect-Token": token } } })));
    } catch (e) { setError(e); }
  }
  function onTap(e: GestureResponderEvent) { const { locationX, locationY } = e.nativeEvent; void input({ kind: "tap", x: locationX / size.w, y: locationY / size.h }); }

  const done = !!session && TERMINAL.includes(session.state);
  return (
    <Screen>
      <ScrollView contentContainerStyle={{ padding: space[4], gap: space[3], paddingBottom: space[6] }} keyboardShouldPersistTaps="handled">
        <H1>Connect {platform}</H1>
        {!session ? (
          <Card>
            <P>You will sign in on the <Text style={{ fontWeight: "700" }}>official {platform} page</Text>, rendered by our always-on service in a private browser profile only your account can use. This phone shows the screen and sends your taps and typing. No AI sees this screen and keystrokes are not recorded.</P>
            <P muted style={{ fontSize: 13 }}>Trust note: the service operator administers that server; this design does not claim they are technically unable to access it. Sessions expire after 10 minutes. If the platform asks for extra verification, complete it on the page or in the platform’s own app.</P>
            <Check label={`I consent to hosting my ${platform} session on this service for collection`} value={consent} onChange={setConsent} />
            {error ? <ErrorView error={error} /> : null}
            <Button title="Start sign-in" variant="primary" disabled={!consent} onPress={() => void start()} />
          </Card>
        ) : (
          <Card>
            <View style={{ flexDirection: "row", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <Badge kind={session.state === "active" ? "ok" : done ? "bad" : "default"}>{session.state}</Badge>
              {session.current_url_host ? <Badge>{session.current_url_host}</Badge> : null}
              <Text style={{ color: c.muted, fontSize: 12 }}>expires {new Date(session.expires_at).toLocaleTimeString()}</Text>
            </View>
            {!done ? (<>
              <Pressable accessibilityRole="image" accessibilityLabel="Remote sign-in screen; tap to interact" testID="connect-frame" onPress={onTap} onLayout={(e) => setSize({ w: e.nativeEvent.layout.width || 1, h: e.nativeEvent.layout.height || 1 })} style={{ width: "100%", aspectRatio: 412 / 800, borderWidth: 1, borderColor: c.border, borderRadius: 8, overflow: "hidden", backgroundColor: c.surface2 }}>
                {frame ? <Image source={{ uri: frame }} style={{ width: "100%", height: "100%" }} resizeMode="stretch" /> : <Text style={{ color: c.muted, padding: 12 }}>Waiting for the first screen…</Text>}
              </Pressable>
              <Input label="Type here, then Send" hint="goes to the focused field on the page" value={text} onChangeText={setText} autoCapitalize="none" autoCorrect={false} onSubmitEditing={() => { if (text) { void input({ kind: "type", text }); setText(""); } }} />
              <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
                <Button title="Send text" onPress={() => { if (text) { void input({ kind: "type", text }); setText(""); } }} />
                <Button title="Enter" onPress={() => void input({ kind: "key", key: "Enter" })} />
                <Button title="Backspace" onPress={() => void input({ kind: "key", key: "Backspace" })} />
                <Button title="Tab" onPress={() => void input({ kind: "key", key: "Tab" })} />
                <Button title="Scroll ↓" onPress={() => void input({ kind: "scroll", dy: 600 })} />
                <Button title="Scroll ↑" onPress={() => void input({ kind: "scroll", dy: -600 })} />
                <Button title="Back" onPress={() => void input({ kind: "back" })} />
              </View>
              <Button title="Done — I’m signed in" variant="primary" onPress={() => void end("finish")} />
              <Button title="Cancel" variant="danger" onPress={() => void end("cancel")} />
            </>) : (<>
              <P>{session.state === "completed" ? `Result: ${session.result_status.replace(/_/g, " ") || "checked"}.` : `Session ${session.state}${session.ended_reason ? `: ${session.ended_reason}` : ""}.`}</P>
              <Button title="Back to sources" variant="primary" onPress={() => router.back()} />
            </>)}
            {error ? <ErrorView error={error} /> : null}
          </Card>
        )}
      </ScrollView>
    </Screen>
  );
}
