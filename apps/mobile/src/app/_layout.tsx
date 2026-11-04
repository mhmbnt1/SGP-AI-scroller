import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { AuthProvider } from "@/lib/auth";
import { useColors } from "@/theme";

function Root() {
  const c = useColors();
  return (
    <Stack screenOptions={{ headerStyle: { backgroundColor: c.surface }, headerTintColor: c.text, contentStyle: { backgroundColor: c.bg } }}>
      <Stack.Screen name="index" options={{ headerShown: false }} />
      <Stack.Screen name="login" options={{ headerShown: false }} />
      <Stack.Screen name="onboarding" options={{ title: "Preferences" }} />
      <Stack.Screen name="connect" options={{ title: "Connect" }} />
      <Stack.Screen name="recover" options={{ title: "Account recovery" }} />
      <Stack.Screen name="ai" options={{ title: "AI model" }} />
      <Stack.Screen name="sources" options={{ title: "Sources" }} />
      <Stack.Screen name="connect-session" options={{ title: "Sign in to source" }} />
      <Stack.Screen name="schedules" options={{ title: "Schedules" }} />
      <Stack.Screen name="watches" options={{ title: "Watches" }} />
      <Stack.Screen name="whatsapp" options={{ title: "WhatsApp" }} />
      <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
      <Stack.Screen name="item/[id]" options={{ title: "Item" }} />
    </Stack>
  );
}

export default function RootLayout() {
  return (
    <SafeAreaProvider>
      <AuthProvider>
        <StatusBar style="auto" />
        <Root />
      </AuthProvider>
    </SafeAreaProvider>
  );
}
