"use client";

import { useRouter } from "next/navigation";

import { PreferencesForm } from "@/components/preferences-form";
import { api, unwrap } from "@/lib/api";
import { RequireAuth, useAuth } from "@/lib/auth";

export default function OnboardingPage() {
  const router = useRouter();
  const { refresh } = useAuth();
  return (
    <RequireAuth>
      <div className="page-head"><div><h1>Set up your batch</h1><p className="muted">Interests, exclusions, languages, platforms and a time budget. You can change all of this later in Settings.</p></div></div>
      <PreferencesForm
        submitLabel="Save and continue"
        afterSave={async () => {
          await unwrap(api.POST("/api/v1/preferences/complete-onboarding"));
          await refresh();
          router.replace("/connect?from=onboarding");
        }}
      />
    </RequireAuth>
  );
}
