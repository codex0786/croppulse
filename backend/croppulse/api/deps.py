"""FastAPI dependencies: DB session, authentication, role checks, field loading."""

from __future__ import annotations

from collections.abc import Callable, Iterator

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from croppulse.db import get_sessionmaker
from croppulse.enums import Role
from croppulse.governance import audit, can_read_field, can_write_field
from croppulse.models import Field, User
from croppulse.security import verify_token

bearer = HTTPBearer(auto_error=False)


def db() -> Iterator[Session]:
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()


def current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: Session = Depends(db),
) -> User:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required", headers={"WWW-Authenticate": "Bearer"})
    claims = verify_token(creds.credentials)
    if claims is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token", headers={"WWW-Authenticate": "Bearer"})
    user = session.get(User, claims.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    request.state.user_id = user.id
    return user


def require_roles(*roles: Role) -> Callable[[User], User]:
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in {r.value for r in roles}:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Your role does not permit this action")
        return user

    return dep


def readable_field(field_id: str, session: Session, user: User) -> Field:
    field = session.get(Field, field_id)
    if field is None or not can_read_field(session, user, field):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Field not found")
    if field.owner_id != user.id:
        audit(session, user, "field.read_delegated", "field", field.id)
        session.commit()
    return field


def writable_field(field_id: str, session: Session, user: User) -> Field:
    field = session.get(Field, field_id)
    if field is None or not can_read_field(session, user, field):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Field not found")
    if not can_write_field(user, field):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the field owner can change this field")
    return field
