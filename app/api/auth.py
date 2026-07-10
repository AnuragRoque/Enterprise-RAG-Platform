"""Admin authentication endpoints and the require_admin dependency."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.db import get_db
from core.models import AdminUser
from core.config import settings
from core.security import (
    create_session_token,
    hash_password,
    verify_password,
    verify_session_token,
)

router = APIRouter(prefix="/admin/auth", tags=["auth"])

# auto_error=False so we can return a clean 401 JSON instead of the default.
_bearer = HTTPBearer(auto_error=False)


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


def require_admin(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> AdminUser:
    """FastAPI dependency: resolve the Bearer token to an active AdminUser."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    username = verify_session_token(credentials.credentials)
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = db.query(AdminUser).filter(AdminUser.username == username).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account not found or disabled",
        )
    return user


@router.post("/login")
def login(data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(AdminUser).filter(AdminUser.username == data.username.strip()).first()
    # verify_password against a dummy hash when the user is missing keeps the
    # timing similar whether or not the username exists.
    stored = user.password_hash if user else "pbkdf2_sha256$1$00$00"
    if not verify_password(data.password, stored) or not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    user.last_login_at = datetime.now(timezone.utc)
    db.commit()

    token = create_session_token(user.username)
    return {
        "token": token,
        "token_type": "bearer",
        "expires_in": settings.session_ttl_seconds,
        "user": {"username": user.username, "full_name": user.full_name},
    }


@router.get("/me")
def me(current: AdminUser = Depends(require_admin)):
    return {
        "username": current.username,
        "full_name": current.full_name,
        "is_superuser": current.is_superuser,
        "last_login_at": current.last_login_at.isoformat() if current.last_login_at else None,
    }


@router.post("/change-password")
def change_password(
    data: ChangePasswordRequest,
    current: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if not verify_password(data.current_password, current.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    if len(data.new_password) < 8:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="New password must be at least 8 characters")
    current.password_hash = hash_password(data.new_password)
    db.commit()
    return {"status": "ok", "message": "Password updated successfully."}
