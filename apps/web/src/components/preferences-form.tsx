"use client";

import type { ModelsOut, PlatformCapabilityOut, PreferencesIn, PreferencesOut } from "@focusfeed/contracts";
import { useEffect, useState, type FormEvent } from "react";

import { ErrorBox, Loading } from "@/components/states";
import { api, unwrap } from "@/lib/api";

type Prefs = Required<PreferencesIn>;
type Plat = Prefs["platforms"][number];
const PLATFORMS: Plat[] = ["youtube", "instagram", "tiktok", "x", "linkedin", "demo"];

function TagInput({ label, hint, values, onChange, max = 30 }: { label: string; hint?: string; values: string[]; onChange: (v: string[]) => void; max?: number }) {
  const [draft, setDraft] = useState("");
  function add() {
    const v = draft.trim();
    if (!v || values.some((x) => x.toLowerCase() === v.toLowerCase()) || values.length >= max) return;
    onChange([...values, v]);
    setDraft("");
  }
  return (
    <div>
      <label>
        {label} {hint && <span className="hint">{hint}</span>}
        <div className="row">
          <input type="text" value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }} maxLength={60} aria-label={`${label}: add`} />
          <button type="button" className="btn-sm" onClick={add}>Add</button>
        </div>
      </label>
      <div className="checks" style={{ marginTop: 8 }} aria-label={`${label} list`}>
        {values.map((v) => (
          <span key={v} className="chip">{v}<button type="button" className="btn-ghost btn-sm" style={{ minHeight: 24, padding: "0 4px" }} aria-label={`Remove ${v}`} onClick={() => onChange(values.filter((x) => x !== v))}>×</button></span>
        ))}
        {values.length === 0 && <small className="muted">None yet.</small>}
      </div>
    </div>
  );
}

export function PreferencesForm({ submitLabel = "Save", afterSave }: { submitLabel?: string; afterSave?: (p: PreferencesOut) => Promise<void> | void }) {
  const [prefs, setPrefs] = useState<Prefs | null>(null);
  const [caps, setCaps] = useState<PlatformCapabilityOut[]>([]);
  const [models, setModels] = useState<ModelsOut | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    setError(null);
    try {
      const [p, c, m] = await Promise.all([unwrap(api.GET("/api/v1/preferences")), unwrap(api.GET("/api/v1/platforms")), unwrap(api.GET("/api/v1/models"))]);
      setPrefs({ interests: p.interests, exclusions: p.exclusions, excluded_creators: p.excluded_creators, languages: p.languages, platforms: p.platforms as Plat[], per_platform_limit: p.per_platform_limit,
        total_budget_minutes: p.total_budget_minutes, consent_saved_signals: p.consent_saved_signals, consent_feedback_learning: p.consent_feedback_learning, text_model: p.text_model, embedding_model: p.embedding_model });
      setCaps(c);
      setModels(m);
    } catch (e) { setError(e); }
  }
  useEffect(() => { void load(); }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!prefs || busy) return;
    setBusy(true);
    setError(null);
    setSaved(null);
    try {
      const out = await unwrap(api.PUT("/api/v1/preferences", { body: prefs }));
      setSaved(`Saved (version ${out.version}).`);
      await afterSave?.(out);
    } catch (err) { setError(err); } finally { setBusy(false); }
  }

  if (!prefs && !error) return <Loading />;
  if (!prefs) return <ErrorBox error={error} onRetry={load} />;
  const p = prefs;
  const set = <K extends keyof Prefs>(k: K, v: Prefs[K]) => setPrefs({ ...p, [k]: v });

  return (
    <form className="stack" onSubmit={submit}>
      <fieldset className="stack">
        <legend>Platforms</legend>
        <div className="checks">
          {PLATFORMS.map((pl) => {
            const cap = caps.find((c) => c.platform === pl);
            const disabled = cap?.status === "disabled";
            const checked = p.platforms.includes(pl);
            return (
              <label key={pl} className="chip" data-checked={checked} style={{ fontWeight: 500 }}>
                <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => set("platforms", e.target.checked ? [...p.platforms, pl] : p.platforms.filter((x) => x !== pl))} />
                {cap?.display_name ?? pl}
                {cap && <span className={`badge ${cap.status === "implemented" ? "ok" : cap.status === "synthetic" ? "synthetic" : ""}`}>{cap.status.replace("_", " ")}</span>}
              </label>
            );
          })}
        </div>
        <small className="muted">“contract only” platforms have a typed adapter contract but no live extraction yet; they are never dispatched. None of the platforms has been live-verified in this build.</small>
      </fieldset>
      <fieldset className="stack">
        <legend>Interests & exclusions</legend>
        <TagInput label="Interests" hint="Topics you want more of" values={p.interests} onChange={(v) => set("interests", v)} />
        <TagInput label="Exclusions" hint="Whole-word topics to drop (e.g. crypto)" values={p.exclusions} onChange={(v) => set("exclusions", v)} max={50} />
        <TagInput label="Excluded creators" hint="Handles to never show" values={p.excluded_creators} onChange={(v) => set("excluded_creators", v)} max={100} />
        <TagInput label="Preferred languages" hint="BCP-47 codes like en, es. Empty = any." values={p.languages} onChange={(v) => set("languages", v)} max={8} />
      </fieldset>
      <fieldset className="grid-2">
        <legend>Budget</legend>
        <label>Items per platform <span className="hint">1–10, default 5</span><input type="number" min={1} max={10} value={p.per_platform_limit} onChange={(e) => set("per_platform_limit", Number(e.target.value))} /></label>
        <label>Total time budget (minutes) <span className="hint">Batch stops when estimated watch time is reached</span><input type="number" min={5} max={240} value={p.total_budget_minutes} onChange={(e) => set("total_budget_minutes", Number(e.target.value))} /></label>
      </fieldset>
      <fieldset className="stack">
        <legend>Signals & consent</legend>
        <label className="chip" data-checked={p.consent_feedback_learning}><input type="checkbox" checked={p.consent_feedback_learning} onChange={(e) => set("consent_feedback_learning", e.target.checked)} />Use my relevant / not-relevant feedback to adjust future batches</label>
        <label className="chip" data-checked={p.consent_saved_signals}><input type="checkbox" checked={p.consent_saved_signals} onChange={(e) => set("consent_saved_signals", e.target.checked)} />Use topics of items I save as a positive signal</label>
        <small className="muted">Private messages are never read. Viewing content through the collector may itself influence what the platform recommends to you.</small>
      </fieldset>
      {models && (
        <fieldset className="grid-2">
          <legend>Models ({models.provider}{models.provider_healthy ? "" : " — unavailable"})</legend>
          <label>Text model<select value={p.text_model ?? ""} onChange={(e) => set("text_model", e.target.value || null)}><option value="">Default</option>{models.options.filter((o) => o.purpose === "text").map((o) => <option key={o.name} value={o.name} disabled={!o.available}>{o.name}{o.available ? "" : " (not installed)"}</option>)}</select></label>
          <label>Embedding model<select value={p.embedding_model ?? ""} onChange={(e) => set("embedding_model", e.target.value || null)}><option value="">Default</option>{models.options.filter((o) => o.purpose === "embedding").map((o) => <option key={o.name} value={o.name} disabled={!o.available}>{o.name}{o.available ? "" : " (not installed)"}</option>)}</select></label>
          <small className="muted" style={{ gridColumn: "1 / -1" }}>{models.resource_note}</small>
        </fieldset>
      )}
      {error ? <ErrorBox error={error} /> : null}
      {saved && <div className="notice success" role="status">{saved}</div>}
      <div className="row"><button type="submit" className="btn-primary" disabled={busy}>{busy ? "Saving…" : submitLabel}</button></div>
    </form>
  );
}
