from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from croppulse.api.deps import current_user, db
from croppulse.config import get_settings
from croppulse.enums import ConsentPurpose, Role
from croppulse.governance import POLICY_VERSION, audit, consents_for, record_consent
from croppulse.models import Organization, User
from croppulse.schemas import ConsentIn, ConsentsOut, LanguageIn, LoginIn, RegisterIn, TokenOut, UserOut
from croppulse.security import anonymize, hash_password, issue_token, rate_limiter, verify_password

router = APIRouter(prefix="/api/v1", tags=["auth"])


def _client_key(request: Request, route: str) -> str:
    host = request.client.host if request.client else "unknown"
    return f"{route}:{anonymize(host)}"


@router.post("/auth/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, session: Session = Depends(db)) -> TokenOut:
    if not rate_limiter.allow(_client_key(request, "login"), get_settings().login_rate_limit_per_minute):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many login attempts; try again in a minute")
    user = session.scalars(select(User).where(func.lower(User.email) == body.email.lower())).first()
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        audit(session, user, "auth.login", "user", user.id if user else None, outcome="denied")
        session.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    token, exp = issue_token(user.id)
    audit(session, user, "auth.login", "user", user.id)
    session.commit()
    return TokenOut(access_token=token, expires_at=exp)


@router.post("/auth/register", response_model=UserOut, status_code=201)
def register_farmer(body: RegisterIn, request: Request, session: Session = Depends(db)) -> User:
    """Self-registration creates FARMER accounts only. Other roles are provisioned by an admin."""
    if not rate_limiter.allow(_client_key(request, "register"), 5):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many registrations from this client")
    if session.scalars(select(User).where(func.lower(User.email) == body.email.lower())).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    if body.organization_id and session.get(Organization, body.organization_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown organization")
    user = User(
        email=body.email.lower(),
        display_name=body.display_name,
        password_hash=hash_password(body.password),
        role=Role.farmer,
        preferred_language=body.preferred_language,
        organization_id=body.organization_id,
    )
    session.add(user)
    session.flush()
    record_consent(session, user.id, ConsentPurpose.core_service, True)
    audit(session, user, "user.register", "user", user.id)
    session.commit()
    return user


@router.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> User:
    return user


@router.put("/me/language", response_model=UserOut)
def set_language(body: LanguageIn, user: User = Depends(current_user), session: Session = Depends(db)) -> User:
    u = session.get(User, user.id)
    assert u is not None
    u.preferred_language = body.preferred_language
    session.commit()
    return u


@router.get("/me/consents", response_model=ConsentsOut)
def get_consents(user: User = Depends(current_user), session: Session = Depends(db)) -> ConsentsOut:
    return ConsentsOut(policy_version=POLICY_VERSION, consents=consents_for(session, user.id))


@router.post("/me/consents", response_model=ConsentsOut)
def set_consent(body: ConsentIn, user: User = Depends(current_user), session: Session = Depends(db)) -> ConsentsOut:
    if body.purpose == ConsentPurpose.core_service and not body.granted:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Withdrawing core-service consent requires account deletion (see /me/deletion-request)")
    record_consent(session, user.id, body.purpose, body.granted)
    audit(session, user, "consent.change", "user", user.id, purpose=body.purpose.value, granted=body.granted)
    session.commit()
    return ConsentsOut(policy_version=POLICY_VERSION, consents=consents_for(session, user.id))


@router.post("/me/deletion-request", status_code=202)
def deletion_request(user: User = Depends(current_user), session: Session = Depends(db)) -> dict[str, str]:
    """Records a deletion request; processing follows docs/SECURITY_AND_PRIVACY.md §Retention and deletion."""
    audit(session, user, "user.deletion_requested", "user", user.id)
    session.commit()
    return {"status": "recorded", "next": "An administrator will process the request within the documented period."}
