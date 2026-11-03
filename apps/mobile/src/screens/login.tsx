import { useRouter } from "expo-router";
import { useState } from "react";
import { KeyboardAvoidingView, Platform, ScrollView, View } from "react-native";

import { Button, ErrorView, H1, Input, P, Screen } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { space } from "@/theme";

export function LoginScreen() {
  const { login, register } = useAuth();
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function submit() {
    if (busy) return;
    setBusy(true); setError(null);
    try {
      if (mode === "login") await login(email.trim(), password); else await register(email.trim(), password, name.trim());
      router.replace("/");
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  return (
    <Screen>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={{ padding: space[4], gap: space[3], paddingTop: space[6] }} keyboardShouldPersistTaps="handled">
          <H1>FocusFeed</H1>
          <P muted>A finite daily batch from your feeds. No autoplay, no infinite scroll.</P>
          <View style={{ flexDirection: "row", gap: 8 }}>
            <Button title="Sign in" variant={mode === "login" ? "primary" : "default"} onPress={() => setMode("login")} accessibilityState={{ selected: mode === "login" }} />
            <Button title="Create account" variant={mode === "register" ? "primary" : "default"} onPress={() => setMode("register")} accessibilityState={{ selected: mode === "register" }} />
          </View>
          {mode === "register" ? <Input label="Display name" value={name} onChangeText={setName} autoComplete="name" /> : null}
          <Input label="Email" value={email} onChangeText={setEmail} autoCapitalize="none" keyboardType="email-address" autoComplete="email" textContentType="emailAddress" />
          <Input label="Password" hint={mode === "register" ? "at least 10 characters" : undefined} value={password} onChangeText={setPassword} secureTextEntry autoComplete={mode === "register" ? "new-password" : "password"} textContentType={mode === "register" ? "newPassword" : "password"} onSubmitEditing={() => void submit()} />
          {error ? <ErrorView error={error} /> : null}
          <Button title={mode === "login" ? "Sign in" : "Create account"} variant="primary" loading={busy} disabled={busy || !email || !password} onPress={() => void submit()} />
          <P muted>Password login with a bearer token stored in the OS keychain/keystore. Account recovery is handled by the administrator (see docs/DEPLOYMENT.md).</P>
        </ScrollView>
      </KeyboardAvoidingView>
    </Screen>
  );
}
