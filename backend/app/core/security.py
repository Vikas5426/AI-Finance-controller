from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Union
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from app.core.config import settings

ph = PasswordHasher()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login", auto_error=False)

def get_password_hash(password: str) -> str:
    return ph.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return ph.verify(hashed_password, plain_password)
    except Exception:
        return False

def create_access_token(subject: Union[str, Any], org_id: str, role: str, expires_delta: Optional[timedelta] = None) -> str:
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode = {
        "exp": expire,
        "sub": str(subject),
        "org_id": str(org_id),
        "role": role,
        "iat": datetime.now(timezone.utc)
    }
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except jwt.PyJWTError:
        return None

def get_current_user(token: Optional[str] = Depends(oauth2_scheme)) -> Dict[str, Any]:
    """Resolves current authenticated user from JWT bearer token. Fails closed (401) on missing or invalid token."""
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please provide a valid Bearer token.",
            headers={"WWW-Authenticate": "Bearer"}
        )

    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication credentials",
            headers={"WWW-Authenticate": "Bearer"}
        )

    # A token with no role claim is malformed, not an analyst. Defaulting a
    # privilege grants access that was never issued, so this fails closed.
    role = payload.get("role")
    if not role:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials: token carries no role claim",
            headers={"WWW-Authenticate": "Bearer"}
        )

    org_id = payload.get("org_id")
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials: token carries no org claim",
            headers={"WWW-Authenticate": "Bearer"}
        )

    return {
        "user_id": payload["sub"],
        "org_id": org_id,
        "role": role,
        "email": payload.get("email", "")
    }

def require_roles(allowed_roles: List[str], allow_admin: bool = True):
    """
    Role-based access control guard dependency.

    ``allow_admin`` grants admin an implicit pass, which is convenient for
    operational endpoints. Set it to False for segregation-of-duties gates
    (approval, sign-off): if admin can satisfy every role, one account can act
    as both maker and checker and dual control is not actually enforced.
    """
    def role_checker(current_user: Dict[str, Any] = Depends(get_current_user)):
        user_role = current_user.get("role")
        if user_role in allowed_roles:
            return current_user
        if allow_admin and user_role == "admin":
            return current_user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: Role '{user_role}' does not have sufficient permissions for this operation. Required: {allowed_roles}"
        )
    return role_checker
