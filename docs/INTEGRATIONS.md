# Integrations and upstream provenance

This document records every candidate repository named in the brief, what it
actually does (inspected from a shallow clone of the pinned commit in this
session), the adoption decision, and the honest platform capability matrix.

Inspection method: `git clone --depth 1` of each repository on 2026-11-03,
reading `README`, `pyproject.toml`/`package.json`, `SKILL.md` files and the
relevant source modules. No upstream code is vendored into this repository;
where an *approach* was adopted it was re-implemented and tested here.

## Candidates

| Repository | Pinned commit | License | What it actually is | Decision | Why |
|---|---|---|---|---|---|
| `Panniantong/Agent-Reach` | `7a38047` (2026-11-01) | MIT | Python CLI (`agent-reach`) giving agents JSON access to the web and platforms. YouTube channel uses **yt-dlp** for video info, search, subtitles and Whisper transcription. Instagram/LinkedIn/X channels go through the third-party **OpenCLI** tool in a shared browser and expose *profile/user/search* actions only. No authenticated home-feed / Reels / Shorts-shelf access exists. Depends on `yt-dlp==2026.8.19`, `loguru`, `requests`, `pyyaml`; auto-installs tooling at onboarding. | **Approach adopted, code not vendored** | Home-feed access verified absent (see `agent_reach/channels/instagram.py`: `search`, `profile`, `posts` only; `youtube.py`: yt-dlp public info/subtitles). We re-implemented the useful part — subtitle extraction via `yt-dlp --skip-download --write-subs --write-auto-subs` with fixed argv and bounded size/timeout — in `services/api/focusfeed_api/services/evidence.py`. Pulling the whole package would add an auto-installer, loguru and unrelated channels. |
| `vercel-labs/agent-browser` | `66dd1d0` (2026-11-03) | Apache-2.0 | Rust CLI driving a browser one command at a time; returns accessibility-tree snapshots with `@e1` refs; `npm i -g agent-browser` + `agent-browser install` downloads Chrome for Testing. Designed for an LLM agent in the loop. | **Not adopted** | Our collector needs deterministic, scripted bounded scrolling with a persistent per-platform profile, request allowlisting and no LLM in the browsing loop. Playwright (Python) gives that directly; agent-browser would add a Rust binary + global install and an interactive agent model we deliberately avoid. |
| `browser-use/browser-use` | `b49a68e` (2026-10-29) | MIT | Python LLM-driven browser agent; pins `openai`, `anthropic`, `google-genai`, `groq`, `posthog` (telemetry) and many more. | **Not adopted** | Wires paid providers and telemetry by default; the agent decides navigation from page content, which is exactly the prompt-injection surface the brief requires us to keep out of the browsing path. We use one principal engine (Playwright) with fixed extraction scripts. |
| `taoufik123-collab/claude-watch` | `7711231` (2026-07-24) | MIT | Claude Code skill `/watch`: `download.py` (yt-dlp), `frames.py` (scene-change / auto-fps frame sampling via ffmpeg), `whisper.py` (Groq/OpenAI Whisper HTTP APIs, API key required), `report.md` + Obsidian vault ingest. | **Approach adopted for frame sampling; transcription path rejected** | Frame budgeting idea (cap frames by duration) re-implemented in `evidence.sample_frames` with fixed argv. Paid transcription and the Obsidian workflow were removed: we prefer platform captions, then (optional, not yet wired) local ASR. |
| `minitap-ai/mobile-use` | `ae8ff04` (2026-11-03) | Apache-2.0 | LLM agent that controls a *phone* (Android/iOS) via natural language; Python 3.12+, Docker images, LLM config. | **Not adopted (optional future device adapter only)** | It automates a device; it does not create our React Native client. Could later become an optional adapter for platforms without a usable web UI, but that is out of scope and adds a paid-model dependency. |
| `Jakeschincariol/instagram-agent-skill` | `d03c56b` (2026-09-13) | MIT | Skill pack: `ig-caption`, `ig-reel`, `ig-carousel`, `ig-story`, `ig-dm`, `ig-comment`, `ig-reply`, `ig-plan`, `ig-audit`, `ig-repurpose` — all **content creation / engagement** workflows (captions, DMs, comment replies). | **Not adopted** | No feed scanning or extraction component exists; DM/comment/engagement automation is explicitly forbidden by our policy (view/scroll/extract only). |
| `Jakeschincariol/youtube-agent-skill` | `a2feb21` | MIT | Skill pack: `yt-script`, `yt-shorts`, `yt-seo`, `yt-package`, `yt-chapters`, `yt-retention`, `yt-plan`, `yt-viral`, `yt-comment`, `yt-audit`, `yt-edit` — creator-side scripting/SEO/analytics. | **Not adopted** | Scriptwriting/SEO does not implement feed scanning. `yt-chapters` reads a transcript the user supplies; our evidence pipeline already produces timestamped segments. |
| `vercel-labs/skills` | `7a5e920` (2026-11-03) | MIT | The `skills` CLI/registry (skills.sh) and a `find-skills` skill. | **Not adopted as runtime; not installed** | Discovery tooling for development skills; we discovered skills by reading the repositories directly and avoided downloading unrelated skills. |
| `vercel-labs/agent-skills` | `1a2c79d` (2026-10-27) | MIT | Development skills: `react-best-practices`, `web-design-guidelines`, `react-native-skills`, `composition-patterns`, `vercel-optimize`, `deploy-to-vercel`. | **Guidance consulted (development only)** | Used as reading material for React/Next/RN conventions; nothing executes at runtime. No Vercel deployment is part of this brief. |
| `anthropics/skills` | `ca45fc4` | per-skill (see `THIRD_PARTY_NOTICES.md`) | Document/office skills (`docx`, `pptx`, `xlsx`, `pdf`), `frontend-design`, `webapp-testing`, `mcp-builder`, `skill-creator`, etc. | **Development guidance only** | `webapp-testing` and `frontend-design` informed the Playwright e2e structure and the token-based design; no runtime dependency. |
| `expo/skills` | `a9e5bd3` | MIT | Expo development skills: `expo-project-structure`, `expo-router`, `expo-dev-client`, `eas-*`, `expo-ui`, `expo-design-system`, etc. | **Development guidance adopted** | `expo-project-structure` shaped `apps/mobile/src/{app,screens,components,lib}`; `expo-router` conventions used for tabs/stack. No runtime dependency. |

### Development skills configured in this repository

`.claude/skills/` contains three project-local development skills (procedural
guidance for contributors using Claude Code), clearly separated from runtime
capabilities (`services/api/focusfeed_api/services/capabilities.py`):

* `ff-backend-change` — how to add/modify an API route end to end (schema →
  router → test → regenerate contracts).
* `ff-adapter-fixture` — how to record a DOM fixture and extend a platform adapter.
* `ff-security-review` — the checklist mapped to docs/SECURITY_CONTROLS.md.

## Runtime dependencies that were adopted (pinned by lockfiles)

| Dependency | Role | License | Notes |
|---|---|---|---|
| FastAPI / Pydantic / SQLAlchemy / Alembic / psycopg | API, validation, ORM, migrations | MIT / MIT / MIT / MIT / LGPL-3.0 | `uv.lock` |
| argon2-cffi | Argon2id password hashing | MIT | OWASP parameters |
| structlog | structured sanitized logging | MIT/Apache-2.0 | |
| httpx | outbound HTTP (Ollama, collector, SSRF-guarded fetches) | BSD-3 | |
| Playwright (Python) | collector browser automation | Apache-2.0 | Chromium downloaded by `playwright install chromium` on the user's PC |
| keyring | OS credential store for the collector device credential | MIT | Windows Credential Manager backend |
| typer | collector CLI | MIT | |
| Next.js / React | web client | MIT | `pnpm-lock.yaml` |
| openapi-typescript / openapi-fetch | generated typed client | MIT | contract drift checked in CI |
| Expo SDK 58 / expo-router / expo-secure-store | mobile client | MIT | SecureStore = Keychain/Keystore |
| Ollama (external process) | default local inference | MIT | not bundled; user installs |
| yt-dlp, ffmpeg (external, optional) | captions / frame sampling | Unlicense / LGPL-GPL | disabled unless `FF_ENABLE_YTDLP` / `FF_ENABLE_FFMPEG` |

## Platform capability / status matrix (honest)

| Platform | Personalized feed | Public search | Item extraction | Captions | Implementation status | Fixture-verified | Live-verified | Credentials needed | OS constraints | Limitations |
|---|---|---|---|---|---|---|---|---|---|---|
| YouTube / Shorts | yes (home grid + Shorts shelf) | yes (`/results`) | yes | via yt-dlp (optional) | implemented (`services/collector/focusfeed_collector/adapters/youtube.py`) | yes (`tests/test_adapters.py`, 5 fixture scenarios) | **no** — no account available in this session | user signs into Google in the dedicated profile | collector runs on Windows/macOS/Linux with Chromium | selectors follow current custom-element structure; a redesign surfaces `upstream_changed` and pauses the platform |
| Instagram Reels | yes (`/reels/`) | no (login required) | yes | caption text only | implemented (`adapters/instagram.py`) | yes (3 scenarios) | **no** | user signs into Instagram in the dedicated profile | same | durations unknown from the feed DOM → conservative estimate; challenges stop collection |
| TikTok | contract only | — | — | — | `ContractOnlyAdapter` | contract tests | no | — | — | not dispatched by the API |
| X | contract only | — | — | — | `ContractOnlyAdapter` | contract tests | no | — | — | not dispatched |
| LinkedIn | contract only | — | — | — | `ContractOnlyAdapter` | contract tests | no | — | — | not dispatched |
| Demo (synthetic) | yes | yes | yes | fixture transcripts | in-process `DemoAdapter` | yes (journey tests) | n/a | none | none | labelled synthetic; disabled in live mode |

Distinct capabilities are never conflated: every candidate carries
`collection_mode ∈ {personalized_feed, public_search, public_url, user_import, synthetic_fixture}`
and every batch carries `is_synthetic`.

## Notices

Third-party licenses of adopted dependencies are preserved in the respective
package metadata (`uv.lock`, `pnpm-lock.yaml`). No upstream source files were
copied, so no additional NOTICE files are required beyond those lockfile-managed packages.
