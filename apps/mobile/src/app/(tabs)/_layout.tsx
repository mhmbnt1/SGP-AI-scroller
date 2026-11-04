import { Redirect, Tabs } from "expo-router";
import { Text, type ColorValue } from "react-native";

import { useAuth } from "@/lib/auth";
import { useColors } from "@/theme";

function Icon({ glyph, color }: { glyph: string; color: ColorValue }) {
  return <Text accessibilityElementsHidden style={{ color, fontSize: 18 }}>{glyph}</Text>;
}

export default function TabsLayout() {
  const c = useColors();
  const { me, ready } = useAuth();
  if (ready && !me) return <Redirect href="/login" />;
  return (
    <Tabs screenOptions={{ tabBarActiveTintColor: c.accent, tabBarInactiveTintColor: c.muted, tabBarStyle: { backgroundColor: c.surface, borderTopColor: c.border }, headerStyle: { backgroundColor: c.surface }, headerTintColor: c.text, sceneStyle: { backgroundColor: c.bg } }}>
      <Tabs.Screen name="today" options={{ title: "Today", tabBarIcon: ({ color }) => <Icon glyph="◎" color={color} /> }} />
      <Tabs.Screen name="search" options={{ title: "Search", tabBarIcon: ({ color }) => <Icon glyph="⌕" color={color} /> }} />
      <Tabs.Screen name="saved" options={{ title: "Saved", tabBarIcon: ({ color }) => <Icon glyph="★" color={color} /> }} />
      <Tabs.Screen name="settings" options={{ title: "Settings", tabBarIcon: ({ color }) => <Icon glyph="⚙" color={color} /> }} />
    </Tabs>
  );
}
