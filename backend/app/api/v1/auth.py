from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel
from typing import Dict, Any, Optional
import logging

from app.core.security import create_access_token, get_password_hash, verify_password, get_current_user
from app.core.config import settings
from app.db.database import get_db_context
from app.db import schema

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])

# One message for every failure mode. Naming the valid accounts, or
# distinguishing "no such user" from "wrong password", hands an attacker a
# free account-enumeration oracle.
INVALID_CREDENTIALS = "Invalid email or password"


class LoginRequest(BaseModel):
    email: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    user_id: str
    org_id: str
    email: str
    full_name: str

@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest):
    email_clean = req.email.strip().lower()

    with get_db_context() as db:
        user = db.query(schema.User).filter(schema.User.email == email_clean).first()

        # A password is the only thing that authenticates. There is deliberately
        # no dev-password allowlist and no "demo user" branch that mints a token
        # for a known email without checking a credential: the demo seed is
        # skipped in production, so such a branch would be the *only* login path
        # there and would accept any password at all.
        if not user or not verify_password(req.password, user.password_hash):
            logger.warning("[auth] Failed login attempt for %r", email_clean)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=INVALID_CREDENTIALS,
            )

        if not getattr(user, "is_active", True):
            logger.warning("[auth] Login attempt on disabled account %r", email_clean)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=INVALID_CREDENTIALS,
            )

        token = create_access_token(
            subject=user.id,
            org_id=user.org_id,
            role=user.role
        )

        return TokenResponse(
            access_token=token,
            role=user.role,
            user_id=user.id,
            org_id=user.org_id,
            email=user.email,
            full_name=user.full_name
        )

@router.get("/me")
def get_current_user_profile(user: Dict[str, Any] = Depends(get_current_user)):
    """Returns the profile of the current authenticated user."""
    return user
