import { Redirect } from "expo-router";

import { Loading, Screen } from "@/components/ui";
import { useAuth } from "@/lib/auth";

export default function Index() {
  const { me, ready } = useAuth();
  if (!ready) return <Screen><Loading /></Screen>;
  if (!me) return <Redirect href="/login" />;
  if (me.onboarding_state !== "complete") return <Redirect href="/onboarding" />;
  return <Redirect href="/(tabs)/today" />;
}
