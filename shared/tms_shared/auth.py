"""FastAPI JWT authentication dependency for all TMS services."""

from __future__ import annotations

import os
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import ExpiredSignatureError, JWTError, jwt

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def _get_jwt_secret() -> str:
    secret = os.environ.get("JWT_SECRET")
    if not secret:
        raise RuntimeError("JWT_SECRET environment variable is not set")
    return secret


def _get_jwt_algorithm() -> str:
    return os.environ.get("JWT_ALGORITHM", "HS256")


async def verify_token(
    token: Annotated[str, Depends(oauth2_scheme)],
) -> dict:
    """Validate a Bearer JWT and return its decoded payload.

    Args:
        token: The raw JWT string extracted from the ``Authorization`` header.

    Returns:
        The decoded token payload as a plain dictionary.

    Raises:
        :class:`fastapi.HTTPException` with status 401 when the token is
        missing, malformed, expired, or signed with a wrong secret.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token,
            _get_jwt_secret(),
            algorithms=[_get_jwt_algorithm()],
        )
        return payload
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except JWTError:
        raise credentials_exception


# Convenience alias – use as ``Depends(require_auth)`` in route definitions.
require_auth = Depends(verify_token)
