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

class RegisterRequest(BaseModel):
    full_name: str
    email: str
    password: str
    role: Optional[str] = "admin"

@router.post("/register", response_model=TokenResponse)
def register(req: RegisterRequest):
    import uuid
    email_clean = req.email.strip().lower()
    if not email_clean or "@" not in email_clean:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please provide a valid work email address."
        )
    if len(req.password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 6 characters long."
        )

    with get_db_context() as db:
        existing = db.query(schema.User).filter(schema.User.email == email_clean).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An account with this email address already exists. Please sign in."
            )

        user_id = str(uuid.uuid4())
        role_clean = req.role if req.role in ["admin", "approver", "analyst"] else "admin"
        approval_limit = 100000000 if role_clean == "admin" else (50000000 if role_clean == "approver" else 500000)
        new_user = schema.User(
            id=user_id,
            org_id=settings.DEFAULT_ORG_ID,
            email=email_clean,
            password_hash=get_password_hash(req.password),
            full_name=req.full_name.strip() or email_clean.split("@")[0].capitalize(),
            role=role_clean,
            approval_limit_minor=approval_limit
        )
        db.add(new_user)
        db.commit()

        token = create_access_token(
            subject=user_id,
            org_id=settings.DEFAULT_ORG_ID,
            role=role_clean
        )

        return TokenResponse(
            access_token=token,
            role=role_clean,
            user_id=user_id,
            org_id=settings.DEFAULT_ORG_ID,
            email=email_clean,
            full_name=new_user.full_name
        )

@router.get("/me")
def get_current_user_profile(user: Dict[str, Any] = Depends(get_current_user)):
    """Returns the profile of the current authenticated user."""
    return user
