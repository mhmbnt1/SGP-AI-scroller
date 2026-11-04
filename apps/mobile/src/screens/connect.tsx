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
        <H1>Local collector (optional)</H1>
        <Notice kind="info">The standard way is hosted collection: Settings → Manage sources → Connect, entirely from this phone. The steps below are only for the optional local-PC collector.</Notice>
        {me?.mode !== "live" ? <Notice kind="info">This server runs in {me?.mode} mode: batches use labelled synthetic content and no collector is needed.</Notice> : null}
        <Card>
          <Text style={{ color: c.text, fontWeight: "700" }}>When to use it</Text>
          <P>If you prefer your platform sessions to stay on your own Windows PC instead of the service, a small collector program opens a dedicated browser profile there, you sign in yourself, and it scrolls a bounded number of items on your schedule. It must be running for scheduled digests.</P>
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
