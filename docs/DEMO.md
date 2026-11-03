# Five-minute walkthrough (graduation project)

Labels used below: **[DEMO]** = synthetic, labelled fixture content through the real pipeline;
**[LIVE]** = requires the Windows collector + your own platform logins (+ Ollama for model analysis).
Nothing in [DEMO] is real feed data, and the UI says so on every batch.

## 0. Setup (one time, ~3 min, no social credentials, no model download)

```
cp .env.example .env            # FF_MODE=demo, FF_LLM_PROVIDER=fake
docker compose up -d db          # or use a local PostgreSQL
scripts/setup.sh                 # uv sync, pnpm install, chromium (Windows: scripts/setup.ps1)
scripts/migrate.sh
scripts/seed.sh                  # demo user + one synthetic batch
scripts/dev.sh                   # API :8000, worker, web :3000
```
Sign in at http://localhost:3000 with `demo@focusfeed.local` / `demo-password-123` (or create an account).

## 1. The problem and the promise (30 s)

Open **Today**. Point out: a finite batch (≤ 5 per platform by default), total estimated time,
"synthetic demo data" badge, no autoplay, no infinite scroll, and the completion card at the end.

## 2. Preferences drive the batch (45 s) [DEMO]

Settings → Preferences: add exclusion `crypto`, exclude creator `gymtok_hype`, set language `en`,
budget 30 min. Back on **Today** press **Refresh batch**: the job is accepted (202) and progresses
`queued → collecting → enriching → ranking → completed` with a live log; the new batch has no crypto
item, no `gymtok_hype`, no Spanish item, and fits the budget.

## 3. Why this? Evidence, not vibes (45 s) [DEMO]

Click **Why this?** on the top card: the explanation lists the interests that matched, freshness,
and the coverage label ("Based on the available transcript (~90% of the runtime)" vs "title/caption
only — not a full-video analysis"). Open **Details**: original source link, timestamped transcript
segments, score components.

## 4. Feedback changes the next batch (45 s) [DEMO]

Press **Hide creator** on a card (it disappears from the current batch), **Not interested** on another,
**Save** a third. Refresh the batch: the hidden creator and the not-interested item never return,
previously shown items carry `novelty = 0`. Saved items are under **Saved**; History shows both runs.

## 5. Explicit intent beats long-term interests (30 s) [DEMO]

**Search**: "high-protein recipes under 20 minutes". The duration constraint is enforced, results
match the request even though interests say "music", and the result list ends — finite by design.

## 6. Mobile (30 s) [DEMO]

`pnpm --filter @focusfeed/mobile start` with `EXPO_PUBLIC_API_URL=http://<PC-IP>:8000`; sign in on
the phone. Same batch, same save/feedback, native tabs, dark mode, offline banner with the cached
batch when Wi-Fi is off. The phone never runs the browser agent.

## 7. The live path (45 s) [LIVE]

**Connect** page: generate a pairing code; on the PC run `focusfeed-collector pair`, `login youtube`,
`status`, `run`. Show the platform matrix: YouTube/Instagram *implemented (fixture-verified, not
live-verified)*, TikTok/X/LinkedIn *contract only*, all with honest next steps. With
`FF_MODE=live` and `FF_LLM_PROVIDER=ollama`, a refresh now waits for your collector; results are real
observations and `is_synthetic=false`. If the platform shows a login wall, the job ends in
`needs_user_action` with instructions — the system never bypasses it.

## 8. Honest limits (15 s)

Time-savings claims need real user evidence (none yet). Platform adapters are fixture-verified only.
See docs/EVALUATION.md (synthetic metrics), docs/VERIFICATION.md (what actually ran) and
docs/ACCEPTANCE.md (gate status).
