import { ScrollView, Text } from "react-native";

import { Card, H1, Notice, P, Screen } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { space, useColors } from "@/theme";

export function ConnectScreen() {
  const c = useColors();
  const { me } = useAuth();
  return (
    <Screen>
      <ScrollView contentContainerStyle={{ padding: space[4], gap: space[3] }}>
        <H1>Connect your feeds</H1>
        {me?.mode !== "live" ? <Notice kind="info">This server runs in {me?.mode} mode: batches use labelled synthetic content and no collector is needed.</Notice> : null}
        <Card>
          <Text style={{ color: c.text, fontWeight: "700" }}>Why this happens on your PC</Text>
          <P>Your personalized feeds only exist behind your own login. A small collector program on your Windows PC opens a dedicated browser profile, you sign in yourself, and it scrolls a bounded number of items on your schedule. Cookies stay on that PC. Phones cannot run a persistent background browser agent, so this app only consumes results.</P>
        </Card>
        <Card>
          <Text style={{ color: c.text, fontWeight: "700" }}>Steps (on the PC)</Text>
          <P>1. Open the web app → Connect → “Generate pairing code”.</P>
          <P>2. Run <Text style={{ fontFamily: "monospace" }}>uv run focusfeed-collector pair</Text> and enter the code (one use, 10 minutes).</P>
          <P>3. Run <Text style={{ fontFamily: "monospace" }}>uv run focusfeed-collector login youtube</Text> (and instagram) and sign in.</P>
          <P>4. Keep <Text style={{ fontFamily: "monospace" }}>uv run focusfeed-collector run</Text> running.</P>
          <P muted>The collector only views and extracts — never posts, likes, follows or messages. If a platform asks for verification, finish it yourself in the official app; the collector stops and waits.</P>
        </Card>
      </ScrollView>
    </Screen>
  );
}
