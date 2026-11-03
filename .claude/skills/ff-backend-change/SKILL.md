---
name: ff-backend-change
description: Add or change a FocusFeed API route end to end (schema -> service -> router -> tests -> regenerate the TypeScript contract). Use when touching services/api or packages/contracts.
---

# Backend change checklist (development guidance, not a runtime capability)

1. **Schema first**: add/modify Pydantic models in `services/api/focusfeed_api/schemas.py`.
   Every string/array must be bounded. Response models must not inherit request
   models (defaulted fields become optional in the OpenAPI client).
2. **Domain logic in services**: `services/api/focusfeed_api/services/*.py`. Routers only
   authenticate, validate and call services. Never duplicate ranking or authorization in clients.
3. **Authorization**: derive the principal from `CurrentUser` / `CurrentDevice`. Every object
   lookup filters by `user_id`. Return 404 (not 403) for objects the caller cannot see.
4. **State changes**: use `services.audit.record(...)` with minimized data; never log tokens or content.
5. **Tests**: add to `services/api/tests/`. Use the `alice`/`bob` fixtures to prove ownership
   isolation for any new object type. Tests run against real PostgreSQL via Alembic migrations.
6. **Migrations**: `cd services/api && DATABASE_URL=... uv run alembic revision --autogenerate -m "..."`,
   review the generated file, then `uv run alembic upgrade head`.
7. **Contract**: `FF_MODE=test uv run focusfeed-api export-openapi && pnpm contracts:generate`;
   commit `packages/contracts/openapi.json` and `src/schema.d.ts` (CI fails on drift).
8. **Verify**: `scripts/test.sh` (or `.ps1`) and update `docs/VERIFICATION.md` with the real result.
