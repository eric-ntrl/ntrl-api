# app/auth.py
"""Shared authentication dependencies."""

import os
import secrets

from fastapi import Header, HTTPException


def require_admin_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    """Validate admin API key. Fails closed if ADMIN_API_KEY is not set."""
    expected_key = os.getenv("ADMIN_API_KEY")

    if not expected_key:
        raise HTTPException(
            status_code=500,
            detail="Server misconfiguration: admin authentication not configured",
        )

    if not x_api_key or not secrets.compare_digest(x_api_key, expected_key):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key",
        )
