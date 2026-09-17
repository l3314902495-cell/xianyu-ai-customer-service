from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import and_, or_
from sqlalchemy.sql import Select


@dataclass(frozen=True)
class Cursor:
    timestamp: datetime
    row_id: str


def encode_cursor(timestamp: datetime, row_id: str) -> str:
    value = timestamp.replace(tzinfo=UTC) if timestamp.tzinfo is None else timestamp.astimezone(UTC)
    raw = json.dumps({"t": value.isoformat(), "id": row_id}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(value: str | None) -> Cursor | None:
    if not value:
        return None
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        payload = json.loads(raw)
        timestamp = datetime.fromisoformat(str(payload["t"]))
        if timestamp.tzinfo is not None:
            timestamp = timestamp.astimezone(UTC)
        row_id = str(payload["id"])
        if not row_id:
            raise ValueError
        return Cursor(timestamp=timestamp, row_id=row_id)
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        raise HTTPException(422, "无效的分页游标") from None


def before_cursor(
    statement: Select[Any],
    timestamp_column: Any,
    id_column: Any,
    cursor: Cursor | None,
) -> Select[Any]:
    if cursor is None:
        return statement
    return statement.where(
        or_(
            timestamp_column < cursor.timestamp,
            and_(timestamp_column == cursor.timestamp, id_column < cursor.row_id),
        )
    )


def cursor_page(items: list[Any], limit: int, *, timestamp: Any, row_id: Any) -> dict:
    has_more = len(items) > limit
    page_items = items[:limit]
    next_cursor = (
        encode_cursor(timestamp(page_items[-1]), row_id(page_items[-1]))
        if has_more and page_items
        else None
    )
    return {"items": page_items, "next_cursor": next_cursor}
