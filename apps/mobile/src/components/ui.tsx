import type { ReactNode } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View, type PressableProps, type TextInputProps } from "react-native";

import { radius, space, touch, useColors } from "@/theme";

export function Screen({ children }: { children: ReactNode }) {
  const c = useColors();
  return <View style={[styles.screen, { backgroundColor: c.bg }]}>{children}</View>;
}

export function H1({ children }: { children: ReactNode }) {
  const c = useColors();
  return <Text accessibilityRole="header" style={[styles.h1, { color: c.text }]}>{children}</Text>;
}

export function P({ children, muted = false, style }: { children: ReactNode; muted?: boolean; style?: object }) {
  const c = useColors();
  return <Text style={[styles.p, { color: muted ? c.muted : c.text }, style]}>{children}</Text>;
}

export function Card({ children, style }: { children: ReactNode; style?: object }) {
  const c = useColors();
  return <View style={[styles.card, { backgroundColor: c.surface, borderColor: c.border }, style]}>{children}</View>;
}

export function Badge({ children, kind = "default" }: { children: ReactNode; kind?: "default" | "ok" | "bad" | "synthetic" | "platform" }) {
  const c = useColors();
  const bg = { default: c.surface2, ok: c.accentSoft, bad: c.dangerSoft, synthetic: c.warnSoft, platform: c.accentSoft }[kind];
  const fg = { default: c.muted, ok: c.text, bad: c.danger, synthetic: c.warn, platform: c.text }[kind];
  return <View style={[styles.badge, { backgroundColor: bg, borderColor: c.border }]}><Text style={{ color: fg, fontSize: 12 }}>{children}</Text></View>;
}

export function Button({ title, variant = "default", loading = false, ...rest }: PressableProps & { title: string; variant?: "default" | "primary" | "danger" | "ghost"; loading?: boolean }) {
  const c = useColors();
  const bg = variant === "primary" ? c.accent : variant === "ghost" ? "transparent" : c.surface;
  const fg = variant === "primary" ? c.accentContrast : variant === "danger" ? c.danger : c.text;
  const border = variant === "primary" ? c.accent : variant === "danger" ? c.danger : variant === "ghost" ? "transparent" : c.border;
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={title} accessibilityState={{ disabled: !!rest.disabled, busy: loading }} {...rest}
      style={({ pressed }) => [styles.button, { backgroundColor: bg, borderColor: border, opacity: rest.disabled ? 0.55 : pressed ? 0.8 : 1 }]}>
      {loading ? <ActivityIndicator color={fg} /> : <Text style={{ color: fg, fontWeight: "600" }}>{title}</Text>}
    </Pressable>
  );
}

export function Input({ label, hint, ...rest }: TextInputProps & { label: string; hint?: string }) {
  const c = useColors();
  return (
    <View style={{ gap: 6 }}>
      <Text style={{ color: c.text, fontWeight: "600" }}>{label}{hint ? <Text style={{ color: c.muted, fontWeight: "400" }}>  {hint}</Text> : null}</Text>
      <TextInput accessibilityLabel={label} placeholderTextColor={c.muted} {...rest} style={[styles.input, { borderColor: c.border, color: c.text, backgroundColor: c.surface }]} />
    </View>
  );
}

export function Notice({ children, kind = "info" }: { children: ReactNode; kind?: "info" | "warn" | "danger" | "success" }) {
  const c = useColors();
  const bg = { info: c.infoSoft, warn: c.warnSoft, danger: c.dangerSoft, success: c.accentSoft }[kind];
  return <View accessibilityRole={kind === "danger" ? "alert" : "text"} style={[styles.notice, { backgroundColor: bg, borderColor: c.border }]}><Text style={{ color: c.text }}>{children}</Text></View>;
}

export function Loading({ label = "Loading" }: { label?: string }) {
  const c = useColors();
  return <View accessibilityLabel={label} accessibilityRole="progressbar" style={{ padding: space[5], alignItems: "center" }}><ActivityIndicator color={c.accent} /></View>;
}

export function ErrorView({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const e = error as { message?: string; offline?: boolean; status?: number; requestId?: string } | null;
  const title = e?.offline ? "You’re offline" : e?.status === 401 ? "Session expired" : e?.status === 403 ? "Not allowed" : "Something went wrong";
  return (
    <Notice kind="danger">
      <Text style={{ fontWeight: "700" }}>{title}</Text>{"\n"}{e?.message ?? "Unknown error"}{e?.requestId ? `\nRef: ${e.requestId}` : ""}
      {onRetry ? <View style={{ marginTop: 8 }}><Button title="Try again" onPress={onRetry} /></View> : null}
    </Notice>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  h1: { fontSize: 26, fontWeight: "700", marginBottom: space[3] },
  p: { fontSize: 16, lineHeight: 22, marginBottom: space[2] },
  card: { borderWidth: 1, borderRadius: radius.md, padding: space[4], gap: space[2] },
  badge: { borderWidth: 1, borderRadius: 999, paddingHorizontal: 8, paddingVertical: 2 },
  button: { minHeight: touch, paddingHorizontal: 14, borderRadius: radius.sm, borderWidth: 1, alignItems: "center", justifyContent: "center" },
  input: { minHeight: touch, borderWidth: 1, borderRadius: radius.sm, paddingHorizontal: 12, fontSize: 16 },
  notice: { borderWidth: 1, borderRadius: radius.sm, padding: space[3] },
});

/** Horizontal single-select chips (used instead of a picker so it works identically on iOS/Android/web). */
export function Choice<T extends string>({ label, value, options, onChange, hint }: { label: string; value: T; options: { value: T; label: string; disabled?: boolean }[]; onChange: (v: T) => void; hint?: string }) {
  const c = useColors();
  return (
    <View style={{ gap: 6 }} accessibilityRole="radiogroup" accessibilityLabel={label}>
      <Text style={{ color: c.text, fontWeight: "600" }}>{label}{hint ? <Text style={{ color: c.muted, fontWeight: "400" }}>  {hint}</Text> : null}</Text>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
        {options.map((o) => (
          <Pressable key={o.value} accessibilityRole="radio" accessibilityLabel={o.label} accessibilityState={{ selected: o.value === value, checked: o.value === value, disabled: !!o.disabled }} disabled={o.disabled} onPress={() => onChange(o.value)}
            style={[styles.badge, { paddingVertical: 8, paddingHorizontal: 12, backgroundColor: o.value === value ? c.accent : c.surface, borderColor: o.value === value ? c.accent : c.border, opacity: o.disabled ? 0.5 : 1 }]}>
            <Text style={{ color: o.value === value ? c.accentContrast : c.text }}>{o.label}</Text>
          </Pressable>
        ))}
      </View>
    </View>
  );
}

export function Check({ label, value, onChange }: { label: string; value: boolean; onChange: (v: boolean) => void }) {
  const c = useColors();
  return (
    <Pressable accessibilityRole="checkbox" accessibilityLabel={label} accessibilityState={{ checked: value }} onPress={() => onChange(!value)} style={{ flexDirection: "row", gap: 10, alignItems: "flex-start", minHeight: touch, paddingVertical: 6 }}>
      <View style={{ width: 22, height: 22, borderRadius: 6, borderWidth: 1, borderColor: value ? c.accent : c.border, backgroundColor: value ? c.accent : c.surface, alignItems: "center", justifyContent: "center", marginTop: 1 }}>{value ? <Text style={{ color: c.accentContrast, fontSize: 14 }}>✓</Text> : null}</View>
      <Text style={{ color: c.text, flex: 1, lineHeight: 20 }}>{label}</Text>
    </Pressable>
  );
}
