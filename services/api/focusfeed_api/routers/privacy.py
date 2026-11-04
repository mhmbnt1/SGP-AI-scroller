from __future__ import annotations

from fastapi import APIRouter, Request, Response

from focusfeed_api.auth.deps import DB, AppSettings, CurrentPrincipal
from focusfeed_api.errors import Unauthorized
from focusfeed_api.schemas import DeleteAccountIn, ExportOut, OkOut
from focusfeed_api.security.passwords import verify_password
from focusfeed_api.services import audit
from focusfeed_api.services.privacy import delete_account, export_user_data

router = APIRouter(prefix="/privacy", tags=["privacy"])


@router.get("/export", response_model=ExportOut)
def export(principal: CurrentPrincipal, db: DB, request: Request) -> ExportOut:
    data = export_user_data(db, principal.user)
    audit.record(db, "privacy.exported", user_id=principal.user.id, request=request)
    db.commit()
    return ExportOut(**data)


@router.post("/delete", response_model=OkOut)
def delete(
    body: DeleteAccountIn,
    principal: CurrentPrincipal,
    db: DB,
    settings: AppSettings,
    request: Request,
    response: Response,
) -> OkOut:
    if not verify_password(principal.user.password_hash, body.password):
        raise Unauthorized("Password is incorrect.", code="invalid_credentials")
    uid = principal.user.id
    delete_account(db, principal.user)
    audit.record(db, "privacy.account_deleted", user_id=uid, request=request)
    db.commit()
    response.delete_cookie(settings.ff_cookie_name, path="/")
    response.delete_cookie(settings.ff_csrf_cookie_name, path="/")
    return OkOut(
        message="Your account and data were deleted. Backups may retain copies for up to the configured retention period."
    )
