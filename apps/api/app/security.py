from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import User

hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return hasher.verify(hashed, password)
    except Exception:
        return False


def create_token(user_id: str) -> str:
    settings = get_settings()
    payload = {"sub": user_id, "exp": datetime.now(UTC) + timedelta(minutes=settings.jwt_expire_minutes)}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token_subject(access_token: str) -> str | None:
    try:
        subject = jwt.decode(
            access_token,
            get_settings().jwt_secret,
            algorithms=["HS256"],
        ).get("sub")
    except jwt.PyJWTError:
        return None
    return subject if isinstance(subject, str) and subject else None


async def current_user(
    access_token: str | None = Cookie(default=None), db: AsyncSession = Depends(get_db)
) -> User:
    if not access_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    user_id = decode_token_subject(access_token)
    if not user_id:
        raise HTTPException(status_code=401, detail="登录已失效")
    user = await db.scalar(select(User).where(User.id == user_id))
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    return user
