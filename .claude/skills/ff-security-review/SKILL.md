---
name: ff-security-review
description: Security review checklist for FocusFeed changes, mapped to docs/SECURITY_CONTROLS.md (OWASP ASVS 5.0 L2 / MASVS 2.1). Use before merging anything touching auth, collector protocol, URL fetching, model prompts or data export/deletion.
---

# Security review checklist

- **Authentication**: sessions are opaque tokens stored hashed; cookies HttpOnly+SameSite=Lax;
  CSRF double-submit on cookie-authenticated state changes; Origin check; bearer for mobile only.
- **Authorization**: every query filters by principal; two-user tests exist (`tests/test_ownership.py`);
  device credentials cannot reach user routes; revoked devices fail closed.
- **Input**: all bodies are bounded Pydantic models with `extra="forbid"`; collector results are
  validated as untrusted; platform scope enforced on ingest.
- **URLs/SSRF**: any server-side fetch goes through `security/ssrf.py` (`validate_url`/`SafeFetcher`),
  with domain allowlists and per-hop redirect validation. Ollama URL is admin config only.
- **Processes**: subprocesses use fixed argv arrays, `shutil.which`, timeouts; never `shell=True`,
  never interpolate URLs/captions into commands.
- **Model I/O**: untrusted text is passed as JSON data, prompts are versioned; outputs validated
  against allowed evidence refs; invented refs/URLs rejected; bounded retries then labelled fallback.
- **Secrets/logs**: `security/redaction.py` on events and audit data; no secrets in URLs, logs, fixtures.
- **Privacy**: export/delete cover derived data; background jobs re-check owner status before writing.
- **Config**: production rejects insecure defaults (`config.py`). Demo mode cannot be enabled in production.
- Update `docs/THREAT_MODEL.md` residual gaps if the change adds a trust boundary.
