import type { RecoveryStatusOut } from "@focusfeed/contracts";
import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { ScrollView } from "react-native";

import { Button, ErrorView, H1, Input, Notice, P, Screen } from "@/components/ui";
import { api, unwrap } from "@/lib/api";
import { space } from "@/theme";

/** Self-service recovery by emailed one-time code; usable entirely from the phone. */
export function RecoverScreen() {
  const router = useRouter();
  const [status, setStatus] = useState<RecoveryStatusOut | null>(null);
  const [step, setStep] = useState<"request" | "confirm" | "done">("request");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { void unwrap(api.GET("/api/v1/auth/recovery")).then(setStatus).catch(setError); }, []);

  async function request() {
    if (busy) return; setBusy(true); setError(null);
    try { const out = await unwrap(api.POST("/api/v1/auth/recovery/request", { body: { email: email.trim() } })); setNote(out.message); if (out.delivery === "sent") setStep("confirm"); }
    catch (e) { setError(e); } finally { setBusy(false); }
  }
  async function confirm() {
    if (busy) return; setBusy(true); setError(null);
    try { const out = await unwrap(api.POST("/api/v1/auth/recovery/confirm", { body: { email: email.trim(), code: code.trim(), new_password: password } })); setNote(out.message); setStep("done"); }
    catch (e) { setError(e); } finally { setBusy(false); }
  }
  return (
    <Screen>
      <ScrollView contentContainerStyle={{ padding: space[4], gap: space[3] }} keyboardShouldPersistTaps="handled">
        <H1>Recover your account</H1>
        {status && !status.available ? <Notice kind="warn">{status.note}</Notice> : status ? <P muted>{status.note}</P> : null}
        {step === "request" ? (<>
          <Input label="Email" value={email} onChangeText={setEmail} autoCapitalize="none" keyboardType="email-address" autoComplete="email" />
          {error ? <ErrorView error={error} /> : null}
          <Button title="Send code" variant="primary" loading={busy} disabled={busy || !email || status?.available === false} onPress={() => void request()} />
        </>) : null}
        {step === "confirm" ? (<>
          {note ? <Notice kind="success">{note}</Notice> : null}
          <Input label="Code from the email" value={code} onChangeText={(v) => setCode(v.toUpperCase())} autoCapitalize="characters" autoComplete="one-time-code" textContentType="oneTimeCode" />
          <Input label="New password" hint="at least 10 characters" value={password} onChangeText={setPassword} secureTextEntry autoComplete="new-password" />
          {error ? <ErrorView error={error} /> : null}
          <Button title="Set new password" variant="primary" loading={busy} disabled={busy || code.length < 6 || password.length < 10} onPress={() => void confirm()} />
          <Button title="Send a new code" variant="ghost" onPress={() => setStep("request")} />
        </>) : null}
        {step === "done" ? (<>
          <Notice kind="success">{note}</Notice>
          <P>All previous sessions were signed out.</P>
          <Button title="Sign in" variant="primary" onPress={() => router.replace("/login")} />
        </>) : null}
        <Button title="Back to sign in" variant="ghost" onPress={() => router.back()} />
      </ScrollView>
    </Screen>
  );
}
