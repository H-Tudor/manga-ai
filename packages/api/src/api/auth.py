"""Keycloak JWT authentication dependency for FastAPI.

This module provides a FastAPI dependency (:func:`require_auth`) that validates
****** issued by the configured Keycloak realm.  Token verification is
done locally using the realm's public JWKS endpoint so that every request does
**not** require a round-trip to Keycloak.

Configuration (via environment variables):
    ``KEYCLOAK_URL``
        Base URL of the Keycloak instance, e.g. ``http://keycloak:8080``.
        Defaults to ``http://localhost:8080``.
    ``KEYCLOAK_REALM``
        Realm name.  Defaults to ``manga-ai``.
    ``KEYCLOAK_AUDIENCE``
        Expected ``aud`` claim in the token.  Defaults to ``manga-ai-api``.
    ``AUTH_DISABLED``
        Set to ``true`` or ``1`` to disable authentication entirely.  Every
        request is then treated as an anonymous user without validating any
        token.  **Do not enable in production.**  Defaults to ``false``.

Usage::

    from api.auth import require_auth, UserInfo

    @app.get("/protected")
    async def protected(user: UserInfo = Depends(require_auth)):
        return {"sub": user.sub, "email": user.email}
"""

from __future__ import annotations

import os
from typing import Annotated

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwk, jwt
from jose.utils import base64url_decode
from pydantic import BaseModel

_bearer = HTTPBearer(auto_error=False)

# ---------------------------------------------------------------------------
# Simple in-process JWKS cache (key_id → public key)
# ---------------------------------------------------------------------------
_jwks_cache: dict[str, object] = {}


def _keycloak_url() -> str:
    return os.getenv("KEYCLOAK_URL", "http://localhost:8080").rstrip("/")


def _realm() -> str:
    return os.getenv("KEYCLOAK_REALM", "manga-ai")


def _audience() -> str:
    return os.getenv("KEYCLOAK_AUDIENCE", "manga-ai-api")


def _auth_disabled() -> bool:
    """Return ``True`` when the ``AUTH_DISABLED`` env var is set to a truthy value."""
    return os.getenv("AUTH_DISABLED", "false").strip().lower() in {"1", "true", "yes"}


def _jwks_uri() -> str:
    return f"{_keycloak_url()}/realms/{_realm()}/protocol/openid-connect/certs"


async def _get_public_key(kid: str) -> object:
    """Fetch the JWKS endpoint and return the key matching *kid*.

    Keys are cached in memory for the lifetime of the process.  The cache is
    invalidated (and refetched) when a token presents an unknown *kid*,
    handling Keycloak key rotations transparently.
    """
    if kid not in _jwks_cache:
        async with httpx.AsyncClient() as client:
            resp = await client.get(_jwks_uri(), timeout=10)
            resp.raise_for_status()
        for key_data in resp.json().get("keys", []):
            _jwks_cache[key_data["kid"]] = jwk.construct(key_data)
    return _jwks_cache.get(kid)


# ---------------------------------------------------------------------------
# User info extracted from the verified token
# ---------------------------------------------------------------------------


class UserInfo(BaseModel):
    """Claims extracted from a verified Keycloak access token."""

    sub: str
    email: str = ""
    preferred_username: str = ""
    realm_roles: list[str] = []


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


async def require_auth(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> UserInfo:
    """Verify the ****** and return the decoded :class:`UserInfo`.

    When ``AUTH_DISABLED=true`` the dependency skips all token validation and
    returns an anonymous :class:`UserInfo` so that every request is allowed.

    Raises :class:`fastapi.HTTPException` with status 401 on any validation
    failure (missing token, bad signature, expired, wrong audience, etc.).
    """
    if _auth_disabled():
        return UserInfo(sub="anonymous", email="", preferred_username="anonymous")

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None:
        raise credentials_exception

    token = credentials.credentials

    try:
        # Decode header to get key ID without verifying the signature yet
        headers = jwt.get_unverified_header(token)
        kid = headers.get("kid", "")
    except JWTError:
        raise credentials_exception

    public_key = await _get_public_key(kid)
    if public_key is None:
        raise credentials_exception

    try:
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            audience=_audience(),
            options={"verify_exp": True},
        )
    except JWTError:
        raise credentials_exception

    realm_access: dict = payload.get("realm_access", {})
    return UserInfo(
        sub=payload.get("sub", ""),
        email=payload.get("email", ""),
        preferred_username=payload.get("preferred_username", ""),
        realm_roles=realm_access.get("roles", []),
    )


async def require_admin(
    user: Annotated[UserInfo, Depends(require_auth)],
) -> UserInfo:
    """Extend :func:`require_auth` to also require the ``admin`` realm role.

    When ``AUTH_DISABLED=true`` the role check is skipped and the anonymous
    user is returned directly.
    """
    if _auth_disabled():
        return user
    if "admin" not in user.realm_roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return user
