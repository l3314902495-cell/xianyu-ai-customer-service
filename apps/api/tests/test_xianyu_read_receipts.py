from datetime import datetime

from app.models import Message, SenderType
from app.services import xianyu_events


class _SessionContext:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *_args):
        return False


async def test_platform_read_receipt_updates_matching_outbound_message(db, monkeypatch):
    account = db.info["account"]
    conversation = db.info["conversation"]
    conversation.external_conversation_id = f"web:{account.id}:remote-conversation"
    outbound = Message(
        conversation_id=conversation.id,
        external_message_id="remote-message.PNM",
        sender_type=SenderType.human,
        content="已发送消息",
        sent=True,
        platform_read_status=False,
    )
    db.add(outbound)
    await db.commit()
    monkeypatch.setattr(xianyu_events, "SessionLocal", lambda: _SessionContext(db))

    await xianyu_events.handle_xianyu_event(
        "message_read",
        {
            "account_id": account.id,
            "cid": "remote-conversation",
            "message_ids": ["remote-message.PNM"],
            "read": True,
            "timestamp": "1788926400000",
        },
    )

    await db.refresh(outbound)
    assert outbound.platform_read_status is True
    assert outbound.platform_read_at == datetime(2026, 9, 9, 4, 0)


async def test_outbound_echo_reconciles_client_uuid_before_read_receipt(db, monkeypatch):
    account = db.info["account"]
    conversation = db.info["conversation"]
    conversation.external_conversation_id = f"web:{account.id}:remote-conversation"
    outbound = Message(
        conversation_id=conversation.id,
        external_message_id="-17889263990001",
        sender_type=SenderType.human,
        content="已发送消息",
        sent=True,
        platform_read_status=False,
    )
    db.add(outbound)
    await db.commit()
    monkeypatch.setattr(xianyu_events, "SessionLocal", lambda: _SessionContext(db))

    await xianyu_events.handle_xianyu_event(
        "outbound_message_echo",
        {
            "account_id": account.id,
            "cid": "remote-conversation",
            "platform_message_id": "4077151826249.PNM",
            "client_message_id": "-17889263990001",
            "content": "已发送消息",
        },
    )
    await xianyu_events.handle_xianyu_event(
        "message_read",
        {
            "account_id": account.id,
            "cid": "remote-conversation",
            "message_ids": ["4077151826249.PNM"],
            "read": True,
            "timestamp": "1788926400000",
        },
    )

    await db.refresh(outbound)
    assert outbound.external_message_id == "xianyu-history-4077151826249.PNM"
    assert outbound.platform_read_status is True
