"""Tokens minted directly, for tests that exercise protected endpoints."""

from datetime import timedelta

from flask import Flask
from flask_jwt_extended import create_access_token, create_refresh_token

from app.models import User


def access_token_for(app: Flask, user: User, expires_delta: timedelta | None = None) -> str:
    with app.app_context():
        token: str = create_access_token(
            identity=str(user.id), expires_delta=expires_delta or timedelta(minutes=15)
        )
    return token


def refresh_token_for(app: Flask, user: User) -> str:
    with app.app_context():
        token: str = create_refresh_token(identity=str(user.id))
    return token


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
